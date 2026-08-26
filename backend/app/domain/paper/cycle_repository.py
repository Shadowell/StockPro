"""Transactional recorded-replay Paper cycles for sealed A-share evidence."""
from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from typing import Any, Callable
import uuid

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.domain.paper.repository import PAPER_ID_SQL
from app.services.ashare_execution import AShareSpotBroker, DEFAULT_ASHARE_COST, explicit_instrument_key, storage_symbol


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class PostgresPaperCycleRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for Paper cycles")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    @staticmethod
    def _event(cursor, instance_uuid: str, cycle_id: str | None, event_type: str, level: str, message: str, payload: dict | None = None) -> None:
        cursor.execute(
            "INSERT INTO paper_instance_events(paper_instance_id,cycle_id,event_type,level,message,payload) VALUES (%s,%s,%s,%s,%s,%s)",
            (instance_uuid, cycle_id, event_type, level, message, psycopg2.extras.Json(payload or {})),
        )

    @staticmethod
    def _instance(cursor, public_id: int | str, *, lock: bool = False) -> dict:
        suffix = " FOR UPDATE OF i" if lock else ""
        cursor.execute(
            f"""
            SELECT i.*,p.initial_cash,p.cash_balance,p.status AS portfolio_status,
                   s.legacy_strategy_id,s.name AS strategy_name,s.script_content,s.parameter_schema,
                   ds.knowledge_cutoff_at,ds.manifest_hash AS dataset_manifest_hash,
                   fs.manifest_hash AS factor_manifest_hash,ps.manifest_hash AS pool_manifest_hash
            FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
            JOIN strategy_versions s ON s.id=i.strategy_version_id
            JOIN dataset_snapshots ds ON ds.id=i.dataset_snapshot_id
            JOIN factor_snapshots fs ON fs.id=i.factor_snapshot_id
            JOIN stock_pool_snapshots ps ON ps.id=i.pool_snapshot_id
            WHERE {PAPER_ID_SQL}=%s{suffix}
            """,
            (int(public_id),),
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError("Paper 实例不存在")
        return dict(row)

    def pending_dates(self, instance_id: int | str) -> list[str]:
        with self._connect(readonly=True) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                instance = self._instance(cursor, instance_id)
                if instance["status"] != "running":
                    raise ValueError("只有运行中 Paper 实例可以推进周期")
                cursor.execute(
                    """
                    SELECT DISTINCT r.payload->>'trade_date' AS trade_date
                    FROM dataset_snapshot_items i JOIN dataset_partition_records r ON r.partition_id=i.partition_id
                    WHERE i.snapshot_id=%s AND i.dataset_code='daily_bars'
                    ORDER BY trade_date
                    """,
                    (instance["dataset_snapshot_id"],),
                )
                dates = [str(row["trade_date"])[:10] for row in cursor.fetchall() if row.get("trade_date")]
        feed = dict(instance.get("feed_config") or {})
        last = str(instance.get("last_processed_trade_date") or "")[:10]
        start = str(feed.get("start_date") or "")[:10]
        end = str(feed.get("end_date") or "")[:10]
        return [day for day in dates if (not last or day > last) and (not start or day >= start) and (not end or day <= end)]

    @staticmethod
    def _load_dataset(cursor, snapshot_id: int, code: str, symbols: list[str], start_date: str, end_date: str) -> list[dict]:
        query = """
            SELECT r.payload FROM dataset_snapshot_items i
            JOIN dataset_partition_records r ON r.partition_id=i.partition_id
            WHERE i.snapshot_id=%s AND i.dataset_code=%s
              AND COALESCE(r.payload->>'trade_date',r.payload->>'ex_date','') BETWEEN %s AND %s
        """
        params: list[Any] = [snapshot_id, code, start_date, end_date]
        if code in {"daily_bars", "price_limits", "suspensions", "corporate_actions"}:
            aliases = sorted({alias for symbol in symbols for alias in (symbol, storage_symbol(symbol))})
            query += " AND COALESCE(r.payload->>'symbol',r.payload->>'ts_code','')=ANY(%s)"
            params.append(aliases)
        elif code == "benchmark_bars":
            query += " AND COALESCE(r.payload->>'symbol',r.payload->>'ts_code','')=ANY(%s)"
            params.append(["000300.SH", "SH_000300"])
        query += " ORDER BY COALESCE(r.payload->>'trade_date',r.payload->>'ex_date',''),r.record_ordinal"
        cursor.execute(query, params)
        output = []
        for raw in cursor.fetchall():
            row = dict(raw["payload"])
            if code in {"daily_bars", "benchmark_bars", "price_limits", "suspensions", "corporate_actions"}:
                symbol = explicit_instrument_key(row.get("symbol") or row.get("ts_code"))
                if not symbol:
                    raise ValueError(f"sealed {code} 包含无效证券代码")
                row["symbol"] = symbol
            output.append(row)
        return output

    @staticmethod
    def _factor_values(cursor, factor_snapshot_id: int, symbols: list[str], end_date: str) -> list[dict]:
        aliases = sorted({alias for symbol in symbols for alias in (symbol, storage_symbol(symbol))})
        cursor.execute(
            """
            SELECT f.trade_date,f.symbol,f.processed_value,f.available_at,d.factor_code
            FROM factor_snapshot_items i
            JOIN factor_versions v ON v.id=i.factor_version_id
            JOIN factor_definitions d ON d.id=v.factor_definition_id
            JOIN factor_daily_values f ON f.compute_run_id=i.compute_run_id AND f.factor_version_id=i.factor_version_id
            WHERE i.snapshot_id=%s AND f.trade_date<=%s AND f.symbol=ANY(%s)
            ORDER BY f.trade_date,d.factor_code,f.symbol
            """,
            (factor_snapshot_id, end_date, aliases),
        )
        rows = []
        for raw in cursor.fetchall():
            row = dict(raw)
            symbol = explicit_instrument_key(row["symbol"])
            if symbol:
                row["symbol"] = symbol
                rows.append(row)
        return rows

    @staticmethod
    def _apply_corporate_actions(cursor, instance: dict, trade_date: str, actions: list[dict]) -> None:
        for action in actions:
            symbol = action["symbol"]
            cursor.execute("SELECT * FROM positions WHERE portfolio_id=%s AND symbol=%s", (instance["portfolio_id"], symbol))
            position = cursor.fetchone()
            if not position:
                continue
            available_at = str(action.get("announcement_available_at") or "")
            if available_at and available_at[:10] > trade_date:
                continue
            old_quantity = int(position["quantity"])
            share_rate = sum(float(action.get(key) or 0) for key in ("stk_div", "stk_bo_rate", "stk_co_rate"))
            new_quantity = int(old_quantity * (1 + share_rate)) if share_rate > 0 else old_quantity
            avg_cost = float(position["avg_cost"] or 0) * old_quantity / new_quantity if new_quantity else 0
            cash_dividend = float(action.get("cash_div_tax") if action.get("cash_div_tax") is not None else action.get("cash_div") or 0)
            cash_delta = old_quantity * cash_dividend
            cursor.execute(
                "UPDATE positions SET quantity=%s,available_quantity=%s,avg_cost=%s,updated_at=NOW() WHERE id=%s",
                (new_quantity, new_quantity, avg_cost, position["id"]),
            )
            if cash_delta:
                cursor.execute("UPDATE portfolios SET cash_balance=cash_balance+%s,updated_at=NOW() WHERE id=%s RETURNING cash_balance", (cash_delta, instance["portfolio_id"]))
                balance = cursor.fetchone()[0]
                cursor.execute(
                    "INSERT INTO cash_ledger(portfolio_id,paper_instance_id,event_type,amount,balance_after,ref_type,note) VALUES (%s,%s,'adjustment',%s,%s,'corporate_action',%s)",
                    (instance["portfolio_id"], instance["id"], cash_delta, balance, f"{symbol} 公司行动现金分红"),
                )

    @staticmethod
    def _intent_delta(intent_type: str, value: float, current: int, equity: float, price: float) -> tuple[int, str | None]:
        if intent_type == "order":
            delta = int(value)
            if delta % 100:
                return 0, "INVALID_LOT_SIZE"
        elif intent_type == "order_value": delta = int(value / price)
        elif intent_type == "order_target": delta = int(value) - current
        elif intent_type == "order_target_value": delta = int(value / price) - current
        elif intent_type == "order_target_percent":
            if not 0 <= value <= 1:
                return 0, "SHORT_OR_LEVERAGE_NOT_SUPPORTED"
            delta = int(equity * value / price) - current
        else:
            return 0, "UNSUPPORTED_INTENT"
        if delta > 0: delta = delta // 100 * 100
        elif delta < 0:
            desired = current if abs(delta) >= current else abs(delta) // 100 * 100
            delta = -desired
        return delta, None
    def _execute_pending(self, cursor, instance: dict, cycle_id: str, trade_date: str, bars: dict[str, dict], datasets: dict[str, list[dict]]) -> tuple[int, int]:
        cursor.execute(
            "SELECT * FROM strategy_signals WHERE paper_instance_id=%s AND status='new' AND signal_time::date<%s ORDER BY signal_time,id",
            (instance["id"], trade_date),
        )
        signals = [dict(row) for row in cursor.fetchall()]
        if not signals:
            cursor.execute("UPDATE positions SET available_quantity=quantity,updated_at=NOW() WHERE portfolio_id=%s", (instance["portfolio_id"],))
            return 0, 0

        cursor.execute("SELECT * FROM positions WHERE portfolio_id=%s ORDER BY symbol", (instance["portfolio_id"],))
        positions = {}
        for raw in cursor.fetchall():
            row = dict(raw)
            symbol = explicit_instrument_key(row["symbol"])
            if symbol:
                row["symbol"] = symbol
                row["available_quantity"] = int(row.get("quantity") or 0)
                positions[symbol] = row
        cursor.execute("SELECT * FROM portfolios WHERE id=%s", (instance["portfolio_id"],))
        portfolio = dict(cursor.fetchone())
        cursor.execute("SELECT equity,drawdown FROM paper_equity_snapshots WHERE paper_instance_id=%s ORDER BY trade_date DESC LIMIT 1", (instance["id"],))
        latest = cursor.fetchone()
        equity = float((latest or {}).get("equity") or portfolio["initial_cash"])
        cash = float(portfolio["cash_balance"])
        cursor.execute("SELECT signal_id FROM orders WHERE paper_instance_id=%s AND signal_id=ANY(%s::uuid[])", (instance["id"], [str(row["id"]) for row in signals]))
        existing_signal_ids = {str(row["signal_id"]) for row in cursor.fetchall()}

        broker = AShareSpotBroker(
            DEFAULT_ASHARE_COST,
            calendar_rows=datasets["trade_calendar"],
            price_limits=datasets["price_limits"],
            suspensions=datasets["suspensions"],
        )
        capacity = dict(instance.get("capacity_limits") or {})
        order_rows = []
        trade_rows = []
        ledger_rows = []
        signal_updates = []
        event_rows = []
        zero_symbols = set()
        for signal in signals:
            if str(signal["id"]) in existing_signal_ids:
                continue
            symbol = explicit_instrument_key(signal["symbol"])
            bar = bars.get(symbol)
            if not symbol or not bar:
                continue
            position = positions.get(symbol) or {
                "symbol": symbol, "quantity": 0, "available_quantity": 0, "avg_cost": 0,
                "last_price": 0, "market_value": 0,
            }
            open_price = float(bar.get("open") or 0)
            intent = dict(signal.get("payload") or {})
            intent_type = str(intent.get("intent_type") or "order_target_percent")
            value = float(intent.get("value") or 0)
            delta, rejection = self._intent_delta(intent_type, value, int(position.get("quantity") or 0), equity, open_price)
            if rejection or delta == 0:
                signal_updates.append((str(signal["id"]), "invalidated" if rejection else "closed"))
                continue
            side = "buy" if delta > 0 else "sell"
            quantity = abs(delta)
            slippage = float(DEFAULT_ASHARE_COST["slippage_rate"])
            execution_price = open_price * (1 + slippage if side == "buy" else 1 - slippage)
            order_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"stockpro:paper-order:{instance['id']}:{cycle_id}:{signal['id']}"))
            decision = broker.evaluate(
                side=side, symbol=symbol, quantity=quantity, price=execution_price, trade_date=trade_date,
                cash=cash, available_quantity=int(position.get("available_quantity") or 0), bar=bar,
                explicit_lot=intent_type == "order",
            )
            amount = execution_price * quantity
            if decision.get("accepted") and side == "buy":
                if amount / max(equity, 1) > float(capacity.get("max_single_symbol_weight") or 0.20):
                    decision = {"accepted": False, "rejection_code": "MAX_SYMBOL_WEIGHT", "rejection_reason": "目标单票权重超过上限"}
                elif float(bar.get("volume") or 0) <= 0 or quantity / float(bar.get("volume") or 1) > float(capacity.get("max_participation_ratio") or 0.10):
                    decision = {"accepted": False, "rejection_code": "CAPACITY", "rejection_reason": "成交参与率超过上限"}
                elif cash + float(decision["cash_delta"]) < float(portfolio["initial_cash"]) * float(capacity.get("cash_floor_ratio") or 0.05):
                    decision = {"accepted": False, "rejection_code": "CASH_FLOOR", "rejection_reason": "成交后现金低于安全底线"}
            if not decision.get("accepted"):
                reason = str(decision.get("rejection_reason") or decision.get("rejection_code") or "拒绝")
                order_rows.append((
                    order_id, instance["portfolio_id"], instance["id"], signal["id"], symbol, side,
                    execution_price, quantity, 0, "rejected", signal["signal_time"],
                    signal.get("data_available_at") or signal["signal_time"], f"{trade_date}T09:30:00+08:00", reason,
                ))
                signal_updates.append((str(signal["id"]), "invalidated"))
                event_rows.append(("risk", "warning", "Paper 风控拒单", {"order_id": order_id, "symbol": symbol, "reason": reason}))
                continue

            fees = decision["fees"]
            cash_delta = float(decision["cash_delta"])
            cash += cash_delta
            current_quantity = int(position.get("quantity") or 0)
            if side == "buy":
                new_quantity = current_quantity + quantity
                old_cost = current_quantity * float(position.get("avg_cost") or 0)
                avg_cost = (old_cost + float(decision["book_cost"])) / new_quantity
                available_quantity = int(position.get("available_quantity") or 0)
            else:
                new_quantity = current_quantity - quantity
                avg_cost = float(position.get("avg_cost") or 0) if new_quantity else 0
                available_quantity = max(0, int(position.get("available_quantity") or 0) - quantity)
            if new_quantity > 0:
                positions[symbol] = {
                    **position, "symbol": symbol, "quantity": new_quantity,
                    "available_quantity": available_quantity, "avg_cost": avg_cost,
                    "last_price": execution_price, "market_value": new_quantity * execution_price,
                }
            else:
                positions.pop(symbol, None)
                zero_symbols.add(symbol)
            fee_note = (
                f"commission={float(fees['commission']):.4f};tax={float(fees['tax']):.4f};"
                f"transfer={float(fees['transfer_fee']):.4f};slippage={abs(execution_price-open_price)*quantity:.4f}"
            )
            trade_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"stockpro:paper-trade:{order_id}"))
            filled_at = f"{trade_date}T09:30:00+08:00"
            order_rows.append((
                order_id, instance["portfolio_id"], instance["id"], signal["id"], symbol, side,
                execution_price, quantity, quantity, "filled", signal["signal_time"],
                signal.get("data_available_at") or signal["signal_time"], filled_at, fee_note,
            ))
            trade_rows.append((
                trade_id, instance["portfolio_id"], instance["id"], order_id, f"paper:{order_id}",
                symbol, side, execution_price, quantity, float(decision["amount"]),
                float(fees["commission"]), signal["signal_time"],
                signal.get("data_available_at") or signal["signal_time"], filled_at, filled_at,
            ))
            ledger_rows.append((
                instance["portfolio_id"], instance["id"], side, cash_delta, cash, order_id, fee_note,
            ))
            signal_updates.append((str(signal["id"]), "ordered"))
            event_rows.append(("broker", "info", "Paper 订单已模拟成交", {
                "order_id": order_id, "trade_id": trade_id, "symbol": symbol, "side": side,
                "quantity": quantity, "price": execution_price, "fees": fees,
            }))

        if order_rows:
            psycopg2.extras.execute_values(cursor, """
                INSERT INTO orders
                (id,portfolio_id,paper_instance_id,signal_id,symbol,side,order_type,price,quantity,
                 filled_quantity,status,signal_time,data_available_at,earliest_fill_at,filled_at,message)
                VALUES %s
            """, [
                (row[0], row[1], row[2], row[3], row[4], row[5], "market", row[6], row[7], row[8], row[9], row[10], row[11], row[12], row[12] if row[9] == "filled" else None, row[13])
                for row in order_rows
            ], page_size=200)
        if trade_rows:
            psycopg2.extras.execute_values(cursor, """
                INSERT INTO trades
                (id,portfolio_id,paper_instance_id,order_id,broker_trade_id,symbol,side,price,quantity,
                 amount,commission,signal_time,data_available_at,earliest_fill_at,traded_at)
                VALUES %s
            """, trade_rows, page_size=200)
        if ledger_rows:
            psycopg2.extras.execute_values(cursor, """
                INSERT INTO cash_ledger
                (portfolio_id,paper_instance_id,event_type,amount,balance_after,ref_type,ref_id,note)
                VALUES %s
            """, [(*row[:5], "order", row[5], row[6]) for row in ledger_rows], page_size=200)
        if signal_updates:
            psycopg2.extras.execute_values(cursor, """
                UPDATE strategy_signals AS s SET status=v.status,updated_at=NOW()
                FROM (VALUES %s) AS v(id,status) WHERE s.id=v.id::uuid
            """, signal_updates, template="(%s,%s)", page_size=500)
        if positions:
            psycopg2.extras.execute_values(cursor, """
                INSERT INTO positions(portfolio_id,symbol,quantity,available_quantity,avg_cost,last_price,market_value)
                VALUES %s
                ON CONFLICT(portfolio_id,symbol) DO UPDATE SET
                    quantity=EXCLUDED.quantity,available_quantity=EXCLUDED.available_quantity,
                    avg_cost=EXCLUDED.avg_cost,last_price=EXCLUDED.last_price,
                    market_value=EXCLUDED.market_value,updated_at=NOW()
            """, [
                (instance["portfolio_id"], symbol, row["quantity"], row["available_quantity"], row["avg_cost"], row["last_price"], row["market_value"])
                for symbol, row in positions.items()
            ], page_size=200)
        if zero_symbols:
            cursor.execute("DELETE FROM positions WHERE portfolio_id=%s AND symbol=ANY(%s)", (instance["portfolio_id"], sorted(zero_symbols)))
        cursor.execute("UPDATE portfolios SET cash_balance=%s,updated_at=NOW() WHERE id=%s", (cash, instance["portfolio_id"]))
        if event_rows:
            psycopg2.extras.execute_values(cursor, """
                INSERT INTO paper_instance_events(paper_instance_id,cycle_id,event_type,level,message,payload)
                VALUES %s
            """, [
                (instance["id"], cycle_id, event_type, level, message, psycopg2.extras.Json(payload))
                for event_type, level, message, payload in event_rows
            ], page_size=200)
        return len(order_rows), len(trade_rows)


    def _persist_signals(self, cursor, instance: dict, cycle_id: str, trade_date: str, intents: list[dict]) -> int:
        inserted = 0
        for intent in intents:
            if str(intent.get("simulated_at") or "")[:10] != trade_date:
                continue
            symbol = explicit_instrument_key(intent.get("symbol"))
            if not symbol:
                raise ValueError("策略生成了无效 A 股标的")
            value = float(intent.get("value") or 0)
            signal_key = _hash({"instance": str(instance["id"]), "simulated_at": intent.get("simulated_at"), "available_at": intent.get("available_at"), "symbol": symbol, "intent_type": intent.get("intent_type"), "value": value})
            cursor.execute(
                """
                INSERT INTO strategy_signals
                (strategy_version_id,legacy_strategy_id,paper_instance_id,signal_key,symbol,signal_type,status,
                 signal_time,data_available_at,strength,reason,payload)
                VALUES (%s,%s,%s,%s,%s,%s,'new',%s,%s,%s,%s,%s)
                ON CONFLICT(paper_instance_id,signal_key) WHERE paper_instance_id IS NOT NULL DO NOTHING RETURNING id
                """,
                (
                    instance["strategy_version_id"], instance.get("legacy_strategy_id"), instance["id"], signal_key,
                    symbol, "buy" if value > 0 else "sell", intent["simulated_at"], intent["available_at"],
                    abs(value), f"{intent.get('intent_type')}={value}", psycopg2.extras.Json(intent),
                ),
            )
            row = cursor.fetchone()
            if row:
                inserted += 1
                self._event(cursor, str(instance["id"]), cycle_id, "strategy", "info", "策略信号已持久化，最早下一交易日执行", {"signal_id": str(row["id"]), "symbol": symbol})
        return inserted

    def _persist_equity(self, cursor, instance: dict, cycle_id: str, trade_date: str, bars: dict[str, dict]) -> dict:
        cursor.execute("SELECT * FROM positions WHERE portfolio_id=%s ORDER BY symbol", (instance["portfolio_id"],))
        positions = [dict(row) for row in cursor.fetchall()]
        market_value = 0.0
        for position in positions:
            bar = bars.get(str(position["symbol"])) or {}
            price = float(bar.get("close") or position.get("last_price") or position.get("avg_cost") or 0)
            value = int(position["quantity"]) * price
            market_value += value
            cursor.execute("UPDATE positions SET last_price=%s,market_value=%s,updated_at=NOW() WHERE id=%s", (price, value, position["id"]))
        cursor.execute("SELECT initial_cash,cash_balance FROM portfolios WHERE id=%s", (instance["portfolio_id"],))
        portfolio = dict(cursor.fetchone())
        cash = float(portfolio["cash_balance"])
        initial = float(portfolio["initial_cash"])
        equity = cash + market_value
        cursor.execute("SELECT MAX(equity) AS peak FROM paper_equity_snapshots WHERE paper_instance_id=%s", (instance["id"],))
        peak_row = cursor.fetchone()
        peak = max(equity, float((peak_row or {}).get("peak") or initial))
        drawdown = 1 - equity / peak if peak else 0.0
        cursor.execute("SELECT COALESCE(SUM(amount),0) AS total FROM cash_ledger WHERE paper_instance_id=%s", (instance["id"],))
        ledger_cash = float(cursor.fetchone()["total"])
        difference = cash - ledger_cash
        if abs(difference) > 0.01:
            raise RuntimeError(f"PAPER_LEDGER_RECONCILIATION_FAILED:{difference}")
        cursor.execute(
            """
            INSERT INTO paper_equity_snapshots
            (paper_instance_id,cycle_id,trade_date,cash,market_value,equity,gross_exposure,nav,drawdown,ledger_difference)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(paper_instance_id,trade_date) DO NOTHING RETURNING id
            """,
            (instance["id"], cycle_id, trade_date, cash, market_value, equity, market_value / equity if equity else 0, equity / initial if initial else 0, drawdown, difference),
        )
        if not cursor.fetchone():
            raise ValueError("该交易日权益证据已存在，拒绝覆盖")
        return {"cash": cash, "market_value": market_value, "equity": equity, "drawdown": drawdown, "ledger_difference": difference}

    def process_date(self, instance_id: int | str, trade_date: str, runner) -> dict:
        trade_date = date.fromisoformat(str(trade_date)[:10]).isoformat()
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                instance = self._instance(cursor, instance_id, lock=True)
                if instance["status"] != "running":
                    raise ValueError("只有运行中 Paper 实例可以推进周期")
                cycle_key = f"{trade_date}:close"
                manifest = {
                    "paper_instance_id": str(instance["id"]), "cycle_key": cycle_key, "trade_date": trade_date,
                    "dataset_snapshot_id": int(instance["dataset_snapshot_id"]), "factor_snapshot_id": int(instance["factor_snapshot_id"]),
                    "pool_snapshot_id": int(instance["pool_snapshot_id"]), "strategy_version_id": str(instance["strategy_version_id"]),
                    "runtime_version": "paper-runtime.v2",
                }
                input_hash = _hash(manifest)
                cursor.execute("SELECT * FROM paper_runtime_cycles WHERE paper_instance_id=%s AND cycle_key=%s", (instance["id"], cycle_key))
                existing = cursor.fetchone()
                if existing:
                    if str(existing["input_hash"]) != input_hash:
                        raise ValueError("相同 cycle_key 的输入证据发生变化，拒绝覆盖")
                    if existing["status"] in {"success", "blocked"}:
                        return {**dict(existing), "reused": True}
                    raise ValueError("该周期存在未收敛记录，需要先审计后再推进")
                data_at = f"{trade_date}T15:00:00+08:00"
                cursor.execute(
                    """
                    INSERT INTO paper_runtime_cycles
                    (paper_instance_id,cycle_key,trade_date,data_available_at,observed_at,input_hash,status)
                    VALUES (%s,%s,%s,%s,%s,%s,'running') RETURNING id
                    """,
                    (instance["id"], cycle_key, trade_date, data_at, data_at, input_hash),
                )
                cycle_id = str(cursor.fetchone()["id"])
                cursor.execute("SELECT symbol FROM stock_pool_snapshot_members WHERE snapshot_id=%s ORDER BY ordinal", (instance["pool_snapshot_id"],))
                symbols = [explicit_instrument_key(row["symbol"]) for row in cursor.fetchall()]
                symbols = [symbol for symbol in symbols if symbol]
                if not symbols:
                    raise ValueError("sealed Paper 股票池为空")
                feed = dict(instance.get("feed_config") or {})
                history_start = max(str(feed.get("start_date") or "1900-01-01")[:10], (date.fromisoformat(trade_date) - timedelta(days=180)).isoformat())
                datasets = {
                    code: self._load_dataset(cursor, int(instance["dataset_snapshot_id"]), code, symbols, history_start, trade_date)
                    for code in ("daily_bars", "trade_calendar", "benchmark_bars", "price_limits", "suspensions", "corporate_actions")
                }
                if not datasets["trade_calendar"]:
                    datasets["trade_calendar"] = [{"trade_date": day, "is_open": True, "source": "derived_sealed_daily_bars"} for day in sorted({str(row["trade_date"])[:10] for row in datasets["daily_bars"]})]
                bars = {row["symbol"]: row for row in datasets["daily_bars"] if str(row.get("trade_date"))[:10] == trade_date}
                if not bars:
                    raise ValueError("sealed 股票池在该交易日没有行情")
                self._apply_corporate_actions(cursor, instance, trade_date, [row for row in datasets["corporate_actions"] if str(row.get("ex_date"))[:10] == trade_date])
                order_count, trade_count = self._execute_pending(cursor, instance, cycle_id, trade_date, bars, datasets)
                factor_values = self._factor_values(cursor, int(instance["factor_snapshot_id"]), symbols, trade_date)
                replay = runner.run(
                    {
                        "strategy_version": {"id": instance["strategy_version_id"], "script_content": instance["script_content"]},
                        "dataset_snapshot": {"id": instance["dataset_snapshot_id"], "knowledge_cutoff_at": instance["knowledge_cutoff_at"], "manifest_hash": instance["dataset_manifest_hash"]},
                        "factor_snapshot": {"id": instance["factor_snapshot_id"], "manifest_hash": instance["factor_manifest_hash"]},
                        "pool_snapshot": {"id": instance["pool_snapshot_id"], "manifest_hash": instance["pool_manifest_hash"]},
                        "symbols": symbols, "start_date": history_start, "end_date": trade_date,
                        "initial_cash": float(instance["initial_cash"]), "datasets": datasets, "factor_values": factor_values,
                    }
                )
                if not replay.get("success"):
                    raise ValueError(str(replay.get("error_message") or "Paper 策略回放失败"))
                signal_count = self._persist_signals(cursor, instance, cycle_id, trade_date, list(replay.get("intents") or []))
                equity = self._persist_equity(cursor, instance, cycle_id, trade_date, bars)
                cursor.execute(
                    "UPDATE paper_runtime_cycles SET status='success',signal_count=%s,order_count=%s,trade_count=%s,ledger_difference=%s,finished_at=NOW() WHERE id=%s",
                    (signal_count, order_count, trade_count, equity["ledger_difference"], cycle_id),
                )
                cursor.execute(
                    "UPDATE paper_instances SET last_processed_trade_date=%s,last_cycle_key=%s,heartbeat_at=NOW(),runtime_version='paper-runtime.v2',updated_at=NOW() WHERE id=%s",
                    (trade_date, cycle_key, instance["id"]),
                )
                self._event(cursor, str(instance["id"]), cycle_id, "cycle", "info", "Paper 周期处理完成", {"trade_date": trade_date, "signals": signal_count, "orders": order_count, "trades": trade_count, "equity": equity["equity"], "ledger_difference": equity["ledger_difference"]})
                cursor.execute("SELECT * FROM paper_runtime_cycles WHERE id=%s", (cycle_id,))
                return dict(cursor.fetchone())

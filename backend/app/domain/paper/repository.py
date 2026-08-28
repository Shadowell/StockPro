"""PostgreSQL Paper repository for the original BitPro live workspace."""
from __future__ import annotations

from typing import Callable
import uuid
from datetime import date, datetime, timezone

import psycopg2
import psycopg2.extras

from app.core.config import settings
from app.domain.backtest.input_repository import PostgresBacktestInputGateway
from app.domain.strategy.naming import display_strategy_name, require_strategy_name
from app.services.ashare_execution import explicit_instrument_key


PAPER_ID_SQL = "((('x'||substr(replace(i.id::text,'-',''),1,8))::bit(32)::bigint & 2147483647)::integer)"
PAPER_PROMOTION_CHECK_CODES = (
    "FULL_SEALED_RUN", "SEALED_PROTOCOL", "TRAIN_PASS", "VALIDATION_PASS",
    "OUT_OF_SAMPLE_PASS", "COST_MODEL_PASS", "CAPACITY_RULES_DEFINED", "CAPACITY_PASS",
    "PROMOTION_THRESHOLDS_DEFINED", "BENCHMARK_PASS", "DATA_QUALITY_PASS",
)


class PaperRepository:
    def __init__(self, database_url: str | None = None, *, connection_factory: Callable[..., object] = psycopg2.connect) -> None:
        self.database_url = database_url or settings.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self, *, readonly: bool = True):
        if not self.database_url: raise RuntimeError("DATABASE_URL is required for the A-share Paper port")
        connection = self.connection_factory(self.database_url)
        connection.set_session(readonly=readonly, autocommit=False)
        return connection

    @staticmethod
    def _event(cursor, instance_uuid: str, message: str, *, level: str = "info", payload: dict | None = None) -> None:
        cursor.execute(
            "INSERT INTO paper_instance_events(paper_instance_id,event_type,level,message,payload) VALUES (%s,'lifecycle',%s,%s,%s)",
            (instance_uuid, level, message, psycopg2.extras.Json(payload or {})),
        )

    def list_instances(self) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""
                    SELECT {PAPER_ID_SQL} AS id,i.id AS instance_uuid,i.name,i.status,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,s.name AS strategy_name,s.validation_status,
                           p.initial_cash,p.cash_balance,i.portfolio_id,i.dataset_snapshot_id,i.created_at,i.started_at,i.updated_at,
                           (SELECT e.equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY e.trade_date DESC,e.id DESC LIMIT 1) AS current_equity,
                           (SELECT MAX(e.drawdown) FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id) AS max_drawdown,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) AS trade_count,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS symbols,
                           COALESCE((
                               SELECT jsonb_object_agg(
                                   pos.symbol,
                                   jsonb_build_object(
                                       'quantity',pos.quantity,
                                       'available_quantity',pos.available_quantity,
                                       'avg_cost',pos.avg_cost,
                                       'last_price',pos.last_price,
                                       'market_value',pos.market_value,
                                       'updated_at',pos.updated_at
                                   )
                               )
                               FROM positions pos
                               WHERE pos.portfolio_id=i.portfolio_id AND pos.quantity>0
                           ),'{{}}'::jsonb) AS positions
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id
                    ORDER BY i.created_at DESC,i.id
                """)
                return [dict(row) for row in cursor.fetchall()]

    def get_instance(self, instance_id: int | str) -> dict | None:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""
                    SELECT {PAPER_ID_SQL} AS id,i.id AS instance_uuid,i.name,i.status,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,s.name AS strategy_name,s.validation_status,
                           p.initial_cash,p.cash_balance,i.portfolio_id,i.dataset_snapshot_id,i.created_at,i.started_at,i.updated_at,
                           (SELECT e.equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY e.trade_date DESC,e.id DESC LIMIT 1) AS current_equity,
                           (SELECT MAX(e.drawdown) FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id) AS max_drawdown,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) AS trade_count,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS symbols
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id
                    WHERE {PAPER_ID_SQL}=%s LIMIT 1
                """, (int(instance_id),))
                row = cursor.fetchone()
        return dict(row) if row else None

    def list_candidates(self) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT r.id AS qualifying_backtest_run_id,s.id AS strategy_version_id,
                           s.legacy_strategy_id AS strategy_id,s.name AS strategy_name,s.description,
                           r.dataset_snapshot_id,r.factor_snapshot_id,r.universe_snapshot_id,r.pool_snapshot_id,
                           r.research_protocol_id,r.initial_cash,r.start_date,r.end_date,r.created_at,
                           COALESCE((r.metrics->>'strategy_return')::numeric,0)*100 AS return_pct,
                           COALESCE((r.metrics->>'maximum_drawdown')::numeric,0)*100 AS max_drawdown_pct,
                           (r.metrics->>'sharpe')::numeric AS sharpe_ratio,
                           COALESCE((r.metrics->>'completed_trades')::numeric,0)::integer AS total_trades
                    FROM backtest_runs r JOIN strategy_versions s ON s.id=r.strategy_version_id
                    WHERE r.status='success' AND r.sealed_at IS NOT NULL AND r.run_mode='full'
                      AND r.promotion_status='paper_eligible'
                      AND s.legacy_strategy_id IS NOT NULL
                      AND r.dataset_snapshot_id IS NOT NULL AND r.factor_snapshot_id IS NOT NULL
                      AND r.universe_snapshot_id IS NOT NULL AND r.pool_snapshot_id IS NOT NULL
                      AND r.research_protocol_id IS NOT NULL
                      AND NOT EXISTS (
                          SELECT 1 FROM paper_instances i
                          WHERE i.qualifying_backtest_run_id=r.id
                            AND i.status IN ('draft','starting','running','paused')
                      )
                    ORDER BY r.created_at DESC
                    """
                )
                return [dict(row) for row in cursor.fetchall()]

    def create_instance(self, payload: dict) -> dict:
        run_id = str(payload.get("qualifying_backtest_run_id") or "")
        if not run_id:
            raise ValueError("创建 Paper 必须选择已通过门禁的回测")
        with self._connect(readonly=False) as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT r.*,s.name AS strategy_name,s.parameter_schema,s.validation_status,s.strategy_api_version,
                           ds.status AS dataset_status,fs.status AS factor_status,us.status AS universe_status,
                           ps.status AS pool_status,rp.status AS protocol_status
                    FROM backtest_runs r JOIN strategy_versions s ON s.id=r.strategy_version_id
                    JOIN dataset_snapshots ds ON ds.id=r.dataset_snapshot_id
                    JOIN factor_snapshots fs ON fs.id=r.factor_snapshot_id
                    JOIN universe_snapshots us ON us.id=r.universe_snapshot_id
                    JOIN stock_pool_snapshots ps ON ps.id=r.pool_snapshot_id
                    JOIN research_protocols rp ON rp.id=r.research_protocol_id
                    WHERE r.id=%s AND r.status='success' AND r.sealed_at IS NOT NULL
                      AND r.run_mode='full' AND r.promotion_status='paper_eligible'
                    FOR UPDATE OF r
                    """,
                    (run_id,),
                )
                run = cursor.fetchone()
                if not run:
                    raise ValueError("晋级回测不存在或未通过 Paper 门禁")
                cursor.execute(
                    "SELECT 1 FROM paper_instances WHERE qualifying_backtest_run_id=%s AND status IN ('draft','starting','running','paused') LIMIT 1",
                    (run_id,),
                )
                if cursor.fetchone():
                    raise ValueError("该晋级回测已有活动 Paper 实例")
                if run["validation_status"] != "valid" or run["strategy_api_version"] != "stockpro.v1":
                    raise ValueError("策略版本未通过 stockpro.v1 验证")
                if any(run[key] != "sealed" for key in ("dataset_status", "factor_status", "universe_status", "pool_status", "protocol_status")):
                    raise ValueError("Paper 固定输入缺失或未封存")
                cursor.execute("SELECT check_code,status FROM backtest_promotion_checks WHERE backtest_run_id=%s", (run_id,))
                passed = {str(row["check_code"]) for row in cursor.fetchall() if row["status"] == "passed"}
                missing = [code for code in PAPER_PROMOTION_CHECK_CODES if code not in passed]
                if missing:
                    raise ValueError(f"Paper 启动需要通过完整晋级门禁：{','.join(missing)}")
                initial_cash = float(payload.get("initial_cash") or run.get("initial_cash") or 1_000_000)
                if not 0 < initial_cash <= 1_000_000_000:
                    raise ValueError("初始资金必须在 0 到 10 亿元之间")
                raw_name = str(payload.get("name") or run.get("strategy_name") or "").strip()
                try:
                    name = require_strategy_name(raw_name or run.get("strategy_name") or "")
                except ValueError:
                    name = display_strategy_name(raw_name, fallback=display_strategy_name(str(run.get("strategy_name") or "")))
                    if not name:
                        raise ValueError("策略名称须为「[市场][周期][风格] 策略简称」") from None
                portfolio_name = f"{name} [{uuid.uuid4().hex[:8]}]"
                cursor.execute(
                    "INSERT INTO portfolios(name,mode,base_currency,initial_cash,cash_balance,status) VALUES (%s,'paper','CNY',%s,%s,'paused') RETURNING id",
                    (portfolio_name, initial_cash, initial_cash),
                )
                portfolio_id = str(cursor.fetchone()["id"])
                parameters = {**dict(run.get("parameter_schema") or {}), **dict(payload.get("parameters") or {})}
                capacity_limits = {
                    "cash_floor_ratio": 0.05,
                    "max_single_symbol_weight": 0.20,
                    "max_participation_ratio": 0.10,
                    "max_drawdown": 0.20,
                    "max_daily_turnover": 2.0,
                    **dict(payload.get("capacity_limits") or {}),
                }
                feed_config = {
                    "mode": "recorded_replay",
                    "provider": "sealed_pg_snapshot",
                    "start_date": str(run["end_date"]),
                    "end_date": str(run["end_date"]),
                    "stale_after_seconds": 900,
                }
                cursor.execute(
                    """
                    INSERT INTO paper_instances
                    (name,strategy_version_id,dataset_snapshot_id,factor_snapshot_id,universe_snapshot_id,
                     pool_snapshot_id,research_protocol_id,qualifying_backtest_run_id,portfolio_id,
                     parameters,capacity_limits,feed_config,status,runtime_version,data_purpose)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft','paper-runtime.v1','user')
                    RETURNING id
                    """,
                    (
                        name, run["strategy_version_id"], run["dataset_snapshot_id"], run["factor_snapshot_id"],
                        run["universe_snapshot_id"], run["pool_snapshot_id"], run["research_protocol_id"], run_id,
                        portfolio_id, psycopg2.extras.Json(parameters), psycopg2.extras.Json(capacity_limits),
                        psycopg2.extras.Json(feed_config),
                    ),
                )
                instance_uuid = str(cursor.fetchone()["id"])
                cursor.execute(
                    "INSERT INTO cash_ledger(portfolio_id,paper_instance_id,event_type,amount,balance_after,ref_type,note) VALUES (%s,%s,'deposit',%s,%s,'paper_instance','初始模拟资金')",
                    (portfolio_id, instance_uuid, initial_cash, initial_cash),
                )
                self._event(cursor, instance_uuid, "Paper 实例草稿已创建", payload={"qualifying_backtest_run_id": run_id})
        row = self.get_instance_by_uuid(instance_uuid)
        if not row:
            raise RuntimeError("Paper 实例创建后无法回读")
        return row

    def get_instance_by_uuid(self, instance_uuid: str) -> dict | None:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""
                    SELECT {PAPER_ID_SQL} AS id,i.id AS instance_uuid,i.name,i.status,
                           COALESCE(s.legacy_strategy_id,0) AS strategy_id,s.name AS strategy_name,
                           p.initial_cash,p.cash_balance,i.portfolio_id,i.dataset_snapshot_id,i.created_at,i.started_at,i.updated_at,
                           (SELECT e.equity FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id ORDER BY e.trade_date DESC,e.id DESC LIMIT 1) AS current_equity,
                           (SELECT MAX(e.drawdown) FROM paper_equity_snapshots e WHERE e.paper_instance_id=i.id) AS max_drawdown,
                           (SELECT COUNT(*) FROM trades t WHERE t.paper_instance_id=i.id) AS trade_count,
                           ARRAY(SELECT DISTINCT pos.symbol FROM positions pos WHERE pos.portfolio_id=i.portfolio_id ORDER BY pos.symbol) AS symbols
                    FROM paper_instances i JOIN portfolios p ON p.id=i.portfolio_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id WHERE i.id=%s
                """, (instance_uuid,))
                row = cursor.fetchone()
        return dict(row) if row else None

    def _transition(self, instance_id: int | str, *, allowed: set[str], target: str, portfolio_status: str, message: str, level: str = "info") -> dict:
        current = self.get_instance(instance_id)
        if not current:
            raise ValueError("Paper 实例不存在")
        if current["status"] == target:
            return current
        if str(current["status"]) not in allowed:
            raise ValueError(f"当前状态不能切换为 {target}：{current['status']}")
        instance_uuid = str(current["instance_uuid"])
        with self._connect(readonly=False) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT portfolio_id FROM paper_instances WHERE id=%s", (instance_uuid,))
                portfolio_id = str(cursor.fetchone()[0])
                cursor.execute("UPDATE portfolios SET status=%s,updated_at=NOW() WHERE id=%s", (portfolio_status, portfolio_id))
                cursor.execute(
                    """
                    UPDATE paper_instances SET status=%s,heartbeat_at=CASE WHEN %s='running' THEN NOW() ELSE heartbeat_at END,
                        started_at=CASE WHEN %s='running' THEN COALESCE(started_at,NOW()) ELSE started_at END,
                        stopped_at=CASE WHEN %s='stopped' THEN NOW() ELSE stopped_at END,updated_at=NOW()
                    WHERE id=%s
                    """,
                    (target, target, target, target, instance_uuid),
                )
                self._event(cursor, instance_uuid, message, level=level)
        refreshed = self.get_instance(instance_id)
        if not refreshed:
            raise RuntimeError("Paper 状态更新后无法回读")
        return refreshed

    def start(self, instance_id: int | str) -> dict:
        return self._transition(instance_id, allowed={"draft", "stopped"}, target="running", portfolio_status="active", message="Paper 实例已运行")

    def pause(self, instance_id: int | str) -> dict:
        return self._transition(instance_id, allowed={"running"}, target="paused", portfolio_status="paused", message="Paper 实例已暂停，全部历史保持不变", level="warning")

    def resume(self, instance_id: int | str) -> dict:
        return self._transition(instance_id, allowed={"paused"}, target="running", portfolio_status="active", message="Paper 实例从持久化状态恢复")

    def stop(self, instance_id: int | str) -> dict:
        return self._transition(instance_id, allowed={"running", "paused", "failed"}, target="stopped", portfolio_status="archived", message="Paper 实例已停止，持仓、现金和历史证据保留", level="warning")

    @staticmethod
    def _timestamp_ms(value) -> int:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00")) if "T" in value else date.fromisoformat(value)
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
        if isinstance(value, datetime):
            observed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return int(observed.timestamp() * 1000)
        return 0

    def _account_instance(self, account_id: str) -> dict:
        raw = str(account_id or "").strip()
        if raw.startswith("paper:"):
            raw = raw.split(":", 1)[1]
        if raw and raw not in {"paper", "default"}:
            row = self.get_instance(raw)
            if row:
                return row
        rows = [item for item in self.list_instances() if item.get("status") in {"running", "paused"}]
        if not rows:
            raise ValueError("没有可用 A 股 Paper 账户")
        return rows[0]

    @staticmethod
    def _canonical_symbol(raw: str) -> str:
        value = str(raw or "").strip().upper()
        if "." in value:
            return value
        if "_" in value:
            exchange, digits = value.split("_", 1)
            return f"{digits}.{exchange}"
        return explicit_instrument_key(value) or value

    @classmethod
    def _storage_symbol(cls, raw: str) -> str:
        canonical = cls._canonical_symbol(raw)
        if "." not in canonical:
            return canonical
        digits, exchange = canonical.rsplit(".", 1)
        return f"{exchange}_{digits}"

    def _market_watchlist(self, limit: int) -> list[dict]:
        size = max(1, min(int(limit), 20))
        rows: list[dict] = []
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT r.code, COALESCE(NULLIF(d.name, ''), r.name) AS name, r.price, r.change_percent
                    FROM all_stocks_realtime r
                    LEFT JOIN instrument_definitions d
                      ON d.market='CN'
                     AND d.symbol=(split_part(r.code,'_',2)||'.'||split_part(r.code,'_',1))
                    WHERE r.change_percent IS NOT NULL
                    ORDER BY r.change_percent DESC
                    LIMIT %s
                    """,
                    (size,),
                )
                rows = [dict(item) for item in cursor.fetchall()]
        output = []
        for row in rows:
            symbol = self._canonical_symbol(str(row.get("code") or ""))
            if not symbol:
                continue
            output.append(
                {
                    "symbol": symbol,
                    "source_strategy_id": 0,
                    "source_strategy_name": str(row.get("name") or "当日异动"),
                    "last_side": None,
                    "last_action": None,
                    "last_price": float(row.get("price") or 0) or None,
                    "last_quantity": None,
                    "last_notional_usdt": None,
                    "last_execution_at": None,
                    "order_count": 0,
                }
            )
        return output

    def _history_watch_market(self, account_id: str, symbol: str, timeframe: str, limit: int) -> dict:
        if str(timeframe).lower() != "1d":
            raise ValueError("A 股盯盘当前仅支持 1d")
        normalized = self._canonical_symbol(symbol)
        if not normalized:
            raise ValueError("无效 A 股标的")
        storage = self._storage_symbol(normalized)
        size = max(1, min(int(limit), 800))
        rows: list[dict] = []
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT date, open, high, low, close, volume, turnover
                    FROM stock_history
                    WHERE symbol=%s
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (storage, size),
                )
                rows = list(reversed([dict(item) for item in cursor.fetchall()]))
        klines = [
            {
                "timestamp": self._timestamp_ms(row.get("date")),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0),
                "volume": float(row.get("volume") or 0),
                "quote_volume": float(row.get("turnover") or 0),
            }
            for row in rows
        ]
        last = klines[-1] if klines else {"close": 0, "open": 0, "high": 0, "low": 0, "volume": 0}
        first_close = klines[0]["close"] if klines else 0
        return {
            "account_id": account_id,
            "exchange": "CN",
            "symbol": normalized,
            "timeframe": "1d",
            "ticker": {
                "symbol": normalized,
                "last": last["close"],
                "open": last["open"],
                "high": last["high"],
                "low": last["low"],
                "volume": last["volume"],
                "change_percent": ((last["close"] / first_close) - 1) * 100 if first_close else 0,
                "source": "stock_history",
                "data_status": "ok" if klines else "empty",
            },
            "klines": klines,
            "orderbook": {"bids": [], "asks": []},
            "recent_trades": [],
            "positions": [],
        }

    def accounts(self) -> list[dict]:
        rows = [item for item in self.list_instances() if item.get("status") in {"running", "paused"}]
        if not rows:
            return [
                {
                    "account_id": "market",
                    "name": "A股市场盯盘",
                    "exchange": "CN",
                    "exchange_alias": "A股",
                    "is_default": True,
                    "configured": True,
                    "enabled": True,
                    "testnet": True,
                    "display_only": True,
                    "can_trade": False,
                }
            ]
        return [
            {
                "account_id": f"paper:{item['id']}",
                "name": item["name"],
                "exchange": "CN",
                "exchange_alias": "A股",
                "is_default": index == 0,
                "configured": True,
                "enabled": item["status"] == "running",
                "testnet": True,
                "display_only": True,
                "can_trade": False,
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
            for index, item in enumerate(rows)
        ]

    def account_positions(self, account_id: str) -> list[dict]:
        instance = self._account_instance(account_id)
        output = []
        for row in self.positions(instance["id"]):
            quantity = float(row.get("quantity") or 0)
            if quantity <= 0:
                continue
            free = float(row.get("available_quantity") or 0)
            entry = float(row.get("avg_cost") or 0)
            mark = float(row.get("last_price") or entry)
            output.append(
                {
                    "symbol": explicit_instrument_key(row.get("symbol")) or row.get("symbol"),
                    "name": str(row.get("name") or "").strip() or None,
                    "currency": "CNY",
                    "asset_type": "stock",
                    "side": "long",
                    "amount": quantity,
                    "free": free,
                    "used": max(0.0, quantity - free),
                    "base_amount": quantity,
                    "notional": float(row.get("market_value") or quantity * mark),
                    "notional_usdt": float(row.get("market_value") or quantity * mark),
                    "entry_price": entry,
                    "mark_price": mark,
                    "mark_price_source": "paper_position_last_price" if float(row.get("last_price") or 0) > 0 else "paper_position_avg_cost",
                    "mark_price_at": row.get("updated_at"),
                    "unrealized_pnl": (mark - entry) * quantity,
                    "paper_instance_id": instance["id"],
                }
            )
        return output

    def account_orders(self, account_id: str, limit: int) -> list[dict]:
        instance = self._account_instance(account_id)
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT o.*,s.legacy_strategy_id,s.name AS strategy_name
                    FROM orders o JOIN paper_instances i ON i.id=o.paper_instance_id
                    LEFT JOIN strategy_versions s ON s.id=i.strategy_version_id
                    WHERE i.id=%s ORDER BY o.created_at DESC,o.id DESC LIMIT %s
                    """,
                    (instance["instance_uuid"], max(1, min(int(limit), 500))),
                )
                rows = [dict(row) for row in cursor.fetchall()]
        return [
            {
                "id": str(row["id"]), "symbol": explicit_instrument_key(row.get("symbol")) or row.get("symbol"),
                "side": row.get("side"), "type": row.get("order_type"), "price": float(row.get("price") or 0),
                "amount": float(row.get("quantity") or 0), "filled": float(row.get("filled_quantity") or 0),
                "remaining": max(0.0, float(row.get("quantity") or 0) - float(row.get("filled_quantity") or 0)),
                "status": row.get("status"), "created_timestamp": self._timestamp_ms(row.get("created_at")),
                "created_datetime": str(row.get("created_at")), "source_strategy_id": int(row.get("legacy_strategy_id") or 0),
                "source_strategy_name": row.get("strategy_name"), "bitpro_source": "strategy", "bitpro_source_label": "A 股 Paper",
            }
            for row in rows
        ]

    def watchlist(self, account_id: str, limit: int) -> list[dict]:
        try:
            instance = self._account_instance(account_id)
        except ValueError as exc:
            if str(exc) == "没有可用 A 股 Paper 账户":
                return self._market_watchlist(limit)
            raise
        positions = self.account_positions(account_id)
        orders = self.account_orders(account_id, 500)
        symbols = []
        active_orders = [row for row in orders if row.get("status") in {"pending", "submitted", "partial"}]
        for source in [*(row.get("symbol") for row in positions), *(row.get("symbol") for row in active_orders)]:
            symbol = explicit_instrument_key(source)
            if symbol and symbol not in symbols:
                symbols.append(symbol)
        output = []
        trades = self.trades(instance["id"], 500)
        for symbol in symbols[: max(1, min(int(limit), 100))]:
            related_orders = [row for row in orders if row.get("symbol") == symbol]
            related_trades = [row for row in trades if (explicit_instrument_key(row.get("symbol")) or row.get("symbol")) == symbol]
            latest = related_trades[0] if related_trades else None
            output.append(
                {
                    "symbol": symbol, "source_strategy_id": int(instance.get("strategy_id") or 0),
                    "source_strategy_name": instance.get("strategy_name") or instance.get("name"),
                    "last_side": latest.get("side") if latest else None, "last_action": latest.get("side") if latest else None,
                    "last_price": float(latest.get("price") or 0) if latest else None,
                    "last_quantity": float(latest.get("quantity") or 0) if latest else None,
                    "last_notional_usdt": float(latest.get("amount") or 0) if latest else None,
                    "last_execution_at": str(latest.get("traded_at")) if latest else None,
                    "order_count": len(related_orders),
                }
            )
        return output or self._market_watchlist(limit)

    def watch_market(self, account_id: str, symbol: str, timeframe: str, limit: int) -> dict:
        if str(timeframe).lower() != "1d":
            raise ValueError("A 股盯盘当前仅支持 1d")
        try:
            instance = self._account_instance(account_id)
        except ValueError as exc:
            if str(exc) == "没有可用 A 股 Paper 账户":
                return self._history_watch_market(account_id, symbol, timeframe, limit)
            raise
        normalized = explicit_instrument_key(symbol)
        if not normalized:
            raise ValueError("无效 A 股标的")
        gateway = PostgresBacktestInputGateway(self.database_url, connection_factory=self.connection_factory)
        rows = gateway.load_dataset(int(instance["dataset_snapshot_id"]), "daily_bars", symbols=[normalized], start_date="1900-01-01", end_date="9999-12-31")
        rows = sorted(rows, key=lambda row: str(row.get("trade_date")))[-max(1, min(int(limit), 800)):]
        klines = [
            {
                "timestamp": self._timestamp_ms(row.get("trade_date")), "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0), "low": float(row.get("low") or 0),
                "close": float(row.get("close") or 0), "volume": float(row.get("volume") or 0),
                "quote_volume": float(row.get("turnover") or 0),
            }
            for row in rows
        ]
        if not klines:
            return self._history_watch_market(account_id, symbol, timeframe, limit)
        last = klines[-1] if klines else {"close": 0, "open": 0, "high": 0, "low": 0, "volume": 0}
        first_close = klines[0]["close"] if klines else 0
        return {
            "account_id": account_id, "exchange": "CN", "symbol": normalized, "timeframe": "1d",
            "ticker": {
                "symbol": normalized, "last": last["close"], "open": last["open"], "high": last["high"],
                "low": last["low"], "volume": last["volume"],
                "change_percent": ((last["close"] / first_close) - 1) * 100 if first_close else 0,
            },
            "klines": klines, "orderbook": {"bids": [], "asks": []}, "recent_trades": [],
            "positions": [row for row in self.account_positions(account_id) if row.get("symbol") == normalized],
        }

    def trade_markers(self, account_id: str, symbol: str, limit: int) -> list[dict]:
        instance = self._account_instance(account_id)
        normalized = explicit_instrument_key(symbol)
        rows = [row for row in self.trades(instance["id"], limit) if explicit_instrument_key(row.get("symbol")) == normalized]
        return [
            {
                "id": int(uuid.UUID(str(row["id"])).hex[:8], 16) & 2147483647,
                "label": "B" if row.get("side") == "buy" else "S", "side": row.get("side"),
                "action": row.get("side"), "symbol": normalized, "price": float(row.get("price") or 0),
                "quantity": float(row.get("quantity") or 0), "timestamp": self._timestamp_ms(row.get("traded_at")),
                "datetime": str(row.get("traded_at")), "source_strategy_id": int(instance.get("strategy_id") or 0),
                "source_strategy_name": instance.get("strategy_name") or instance.get("name"),
                "subscription_id": int(instance["id"]), "live_order_id": str(row.get("order_id") or ""),
            }
            for row in rows
        ]

    def positions(self, instance_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT pos.* FROM positions pos JOIN paper_instances i ON i.portfolio_id=pos.portfolio_id WHERE {PAPER_ID_SQL}=%s ORDER BY pos.symbol""", (int(instance_id),))
                return [dict(row) for row in cursor.fetchall()]

    def trades(self, instance_id: int | str, limit: int) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT t.* FROM trades t JOIN paper_instances i ON i.id=t.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY t.traded_at DESC,t.id DESC LIMIT %s""", (int(instance_id), max(1, min(int(limit), 500))))
                return [dict(row) for row in cursor.fetchall()]

    def events(self, instance_id: int | str, limit: int) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT e.event_type,e.level,e.message,e.payload,e.occurred_at FROM paper_instance_events e JOIN paper_instances i ON i.id=e.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY e.occurred_at DESC,e.id DESC LIMIT %s""", (int(instance_id), max(1, min(int(limit), 500))))
                return [dict(row) for row in cursor.fetchall()]

    def equity_curve(self, instance_id: int | str) -> list[dict]:
        with self._connect() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(f"""SELECT e.trade_date,e.equity,e.drawdown,e.cash,e.market_value FROM paper_equity_snapshots e JOIN paper_instances i ON i.id=e.paper_instance_id WHERE {PAPER_ID_SQL}=%s ORDER BY e.trade_date,e.id""", (int(instance_id),))
                return [dict(row) for row in cursor.fetchall()]

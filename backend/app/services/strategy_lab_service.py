"""
A股策略研发闭环服务。

V1 使用 Backtrader 作为回测主框架，同时保留 BitPro 风格的“策略生成 ->
回测 -> 模拟运行 -> 监控”产品闭环。策略代码支持完整 bt.Strategy 类，但在
加载前做 AST 安全检查，并在受限 globals 中执行。
"""
import ast
import json
import math
import sys
import types
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

import backtrader as bt
import akshare as ak
import pandas as pd

from app.db import db_instance as default_db


class AShareCommissionInfo(bt.CommInfoBase):
    params = (
        ("commission", 0.0003),
        ("stamp_duty", 0.001),
        ("min_commission", 5.0),
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_PERC),
    )

    def _getcommission(self, size, price, pseudoexec):
        amount = abs(size) * price
        commission = max(amount * self.p.commission, self.p.min_commission)
        if size < 0:
            commission += amount * self.p.stamp_duty
        return commission


class PortfolioTraceAnalyzer(bt.Analyzer):
    def start(self):
        self.equity_curve = []
        self.orders = []
        self.closed_trades = []

    def next(self):
        data = self.strategy.datas[0]
        self.equity_curve.append(
            {
                "date": data.datetime.date(0).isoformat(),
                "equity": round(float(self.strategy.broker.getvalue()), 2),
                "cash": round(float(self.strategy.broker.getcash()), 2),
            }
        )

    def notify_order(self, order):
        if order.status != order.Completed:
            return
        executed_dt = bt.num2date(order.executed.dt).date().isoformat()
        size = int(abs(order.executed.size))
        price = float(order.executed.price)
        self.orders.append(
            {
                "date": executed_dt,
                "symbol": order.data._name,
                "name": getattr(order.data, "_stock_name", "") or order.data._name,
                "side": "buy" if order.isbuy() else "sell",
                "price": round(price, 4),
                "quantity": size,
                "amount": round(price * size, 2),
                "fee": round(float(order.executed.comm), 2),
                "pnl": 0.0,
                "reason": "strategy_signal",
            }
        )

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        self.closed_trades.append(
            {
                "symbol": trade.data._name,
                "pnl": round(float(trade.pnlcomm), 2),
            }
        )

    def get_analysis(self):
        return {
            "equity_curve": self.equity_curve,
            "orders": self.orders,
            "closed_trades": self.closed_trades,
        }


class RegisteredMomentumStrategy(bt.Strategy):
    params = dict(position_pct=0.9, max_positions=5)

    def __init__(self):
        self.entry_date = {}

    def next(self):
        available_slots = max(int(self.p.max_positions) - self._open_position_count(), 0)
        if available_slots <= 0:
            return

        candidates = []
        for data in self.datas:
            if len(data.close) < 3:
                continue
            pos = self.getposition(data)
            if pos.size:
                # T+1: do not sell on the same trading day as entry.
                entry_date = self.entry_date.get(data._name)
                current_date = data.datetime.date(0)
                if entry_date and current_date <= entry_date:
                    continue
                if data.close[0] < data.close[-1]:
                    self.sell(data=data, size=pos.size)
                continue

            momentum = (data.close[0] - data.close[-2]) / data.close[-2] if data.close[-2] else 0
            if momentum > 0.015 and data.volume[0] >= data.volume[-1]:
                candidates.append((momentum, data))

        if not candidates:
            return

        candidates.sort(key=lambda item: item[0], reverse=True)
        cash = self.broker.getcash()
        allocation = cash * float(self.p.position_pct) / max(min(len(candidates), available_slots), 1)
        for _, data in candidates[:available_slots]:
            size = int((allocation / data.close[0]) // 100) * 100
            if size <= 0:
                continue
            self.buy(data=data, size=size)
            self.entry_date[data._name] = data.datetime.date(0)

    def _open_position_count(self):
        return sum(1 for data in self.datas if self.getposition(data).size)


class StrategyLabService:
    SYMBOL_NAME_FALLBACKS = {
        "SH_600000": "浦发银行",
        "SZ_000001": "平安银行",
    }
    SAFE_IMPORTS = {"backtrader", "math", "statistics", "numpy", "pandas"}
    FORBIDDEN_CALLS = {
        "eval",
        "exec",
        "compile",
        "open",
        "input",
        "__import__",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
    }
    FORBIDDEN_ATTRS = {
        "system",
        "popen",
        "spawn",
        "remove",
        "unlink",
        "rmdir",
        "rename",
        "replace",
        "walk",
        "chmod",
        "chown",
        "kill",
    }

    def __init__(self, db=None):
        self.db = db or default_db

    def auto_develop_strategy(
        self,
        objective: str = "首板突破",
        symbols: Optional[List[str]] = None,
        risk_level: str = "balanced",
    ) -> Dict[str, Any]:
        resolved_symbols = self._resolve_symbols(strategy_id=0, symbols=symbols)
        if not resolved_symbols:
            raise ValueError("No symbols available for strategy development")

        objective_clean = (objective or "首板突破").strip()[:40]
        risk_level_clean = risk_level if risk_level in {"conservative", "balanced", "aggressive"} else "balanced"
        risk_label = {
            "conservative": "稳健",
            "balanced": "均衡",
            "aggressive": "进取",
        }[risk_level_clean]
        symbol_label = "-".join(resolved_symbols[:2])
        strategy_name = f"本地生成-{objective_clean}-{symbol_label}"
        generated_plan = (
            f"A股自动开发计划：围绕“{objective_clean}”生成 Backtrader 多股组合策略，"
            f"标的池 {', '.join(resolved_symbols)}，风险档位 {risk_label}；"
            "先用日线数据回测，再进入模拟盘观察权益、现金、订单、持仓和事件流。"
        )
        script_content = self._build_generated_strategy_script(
            objective=objective_clean,
            symbols=resolved_symbols,
            risk_level=risk_level_clean,
        )
        description = f"自动生成 Backtrader：{objective_clean} / {risk_label} / 标的池 {', '.join(resolved_symbols)}"

        strategy_id = self.db.save_strategy(
            name=strategy_name,
            description=description,
            script_content=script_content,
            interval_seconds=60,
        )
        strategy = self.db.get_strategy_by_id(strategy_id)
        return {
            "success": True,
            "id": strategy_id,
            "strategy": strategy,
            "symbols": resolved_symbols,
            "generated_plan": generated_plan,
        }

    def run_backtest(
        self,
        strategy_id: int,
        symbols: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        initial_capital: float = 100000.0,
        position_pct: float = 0.9,
        commission: float = 0.0003,
        stamp_duty: float = 0.001,
        slippage: float = 0.0002,
        min_commission: float = 5.0,
    ) -> Dict[str, Any]:
        strategy = self.db.get_strategy_by_id(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")

        resolved_symbols = self._resolve_symbols(strategy_id, symbols)
        if not resolved_symbols:
            raise ValueError("No symbols available for backtest")

        histories = {
            symbol: self._load_history(symbol, start_date, end_date)
            for symbol in resolved_symbols
        }
        histories = {symbol: rows for symbol, rows in histories.items() if rows}
        if not histories:
            raise ValueError("No local kline_1d data available for selected symbols")

        strategy_cls = self._strategy_class_from_script(strategy.get("script_content") or "")
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.broker.setcash(float(initial_capital))
        cerebro.broker.addcommissioninfo(
            AShareCommissionInfo(
                commission=float(commission),
                stamp_duty=float(stamp_duty),
                min_commission=float(min_commission),
            )
        )
        if slippage:
            cerebro.broker.set_slippage_perc(float(slippage))

        for symbol, rows in histories.items():
            feed = self._build_data_feed(symbol, rows)
            cerebro.adddata(feed, name=symbol)

        cerebro.addstrategy(strategy_cls, position_pct=float(position_pct))
        cerebro.addanalyzer(PortfolioTraceAnalyzer, _name="trace")
        run_result = cerebro.run()
        trace = run_result[0].analyzers.trace.get_analysis()
        equity_curve = trace["equity_curve"]
        trades = self._merge_trade_pnl(trace["orders"], trace["closed_trades"])
        symbol_names = self._symbol_name_map(list(histories.keys()), histories)
        for trade in trades:
            symbol = self._normalize_symbol(trade.get("symbol") or "")
            if symbol:
                trade["name"] = trade.get("name") or symbol_names.get(symbol) or ""
        final_capital = round(float(cerebro.broker.getvalue()), 2)
        initial = round(float(initial_capital), 2)
        total_return = self._pct(final_capital - initial, initial)
        max_drawdown = self._max_drawdown(equity_curve)
        annual_return = self._annual_return(equity_curve, initial, final_capital)
        sharpe = self._sharpe(equity_curve)
        sell_trades = [trade for trade in trades if trade["side"] == "sell"]
        wins = [trade for trade in sell_trades if trade.get("pnl", 0) > 0]
        losses = [trade for trade in sell_trades if trade.get("pnl", 0) < 0]
        gross_profit = sum(trade["pnl"] for trade in wins)
        gross_loss = abs(sum(trade["pnl"] for trade in losses))

        result = {
            "engine": "backtrader",
            "status": "completed",
            "strategy_id": strategy_id,
            "strategy_name": strategy["name"],
            "symbols": list(histories.keys()),
            "symbol_names": symbol_names,
            "start_date": start_date or min(rows[0]["date"] for rows in histories.values()),
            "end_date": end_date or max(rows[-1]["date"] for rows in histories.values()),
            "initial_capital": initial,
            "final_capital": final_capital,
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "sharpe": sharpe,
            "win_rate": round(len(wins) / len(sell_trades) * 100, 2) if sell_trades else 0.0,
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else (round(gross_profit, 2) if gross_profit else 0.0),
            "total_trades": len(trades),
            "equity_curve": equity_curve,
            "trades": trades,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        result["backtest_id"] = self._save_backtest_result(result)
        return result

    def load_custom_strategy_class(self, script_content: str) -> Type[bt.Strategy]:
        tree = ast.parse(script_content or "")
        self._validate_strategy_ast(tree)
        module_name = "stockpro_strategy"
        module = types.ModuleType(module_name)
        sys.modules[module_name] = module
        safe_globals: Dict[str, Any] = module.__dict__
        safe_globals.update({
            "__builtins__": {
                "abs": abs,
                "all": all,
                "any": any,
                "bool": bool,
                "dict": dict,
                "enumerate": enumerate,
                "float": float,
                "int": int,
                "len": len,
                "list": list,
                "max": max,
                "min": min,
                "pow": pow,
                "print": print,
                "range": range,
                "round": round,
                "set": set,
                "sum": sum,
                "tuple": tuple,
                "ValueError": ValueError,
                "__build_class__": __build_class__,
                "__import__": self._safe_import,
            },
            "__name__": module_name,
            "bt": bt,
            "backtrader": bt,
            "math": math,
        })
        compiled = compile(tree, "<stockpro-strategy>", "exec")
        local_vars: Dict[str, Any] = {}
        exec(compiled, safe_globals, local_vars)
        candidates = [
            obj
            for obj in local_vars.values()
            if isinstance(obj, type) and issubclass(obj, bt.Strategy) and obj is not bt.Strategy
        ]
        if not candidates:
            raise ValueError("Strategy code must define a bt.Strategy subclass")
        return candidates[-1]

    def run_paper_trading(
        self,
        strategy_id: int,
        symbols: Optional[List[str]] = None,
        initial_capital: float = 100000.0,
        position_pct: float = 0.3,
        commission: float = 0.0003,
        slippage: float = 0.0002,
    ) -> Dict[str, Any]:
        strategy = self.db.get_strategy_by_id(strategy_id)
        if not strategy:
            raise ValueError(f"Strategy {strategy_id} not found")

        resolved_symbols = self._resolve_symbols(strategy_id, symbols)
        if not resolved_symbols:
            raise ValueError("No symbols available for paper trading")

        cash = float(initial_capital)
        orders: List[Dict[str, Any]] = []
        positions: List[Dict[str, Any]] = []
        account_name = f"{strategy['name']} 模拟盘"
        account_id = self._create_paper_account(strategy_id, account_name, initial_capital)
        position_pct = min(max(float(position_pct), 0.01), 1.0)
        allocation = initial_capital * position_pct / max(len(resolved_symbols), 1)

        for symbol in resolved_symbols:
            latest = self._load_latest_bar(symbol)
            if not latest:
                continue
            price = float(latest["close"]) * (1 + float(slippage))
            quantity = self._round_lot(allocation / price)
            if quantity <= 0:
                continue
            amount = price * quantity
            fee = max(amount * float(commission), 5.0)
            if amount + fee > cash:
                quantity = self._round_lot(cash / (price * (1 + float(commission))))
                amount = price * quantity
                fee = max(amount * float(commission), 5.0)
            if quantity <= 0:
                continue

            cash -= amount + fee
            last_price = float(latest["close"])
            order = {
                "account_id": account_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "name": latest.get("name") or "",
                "side": "buy",
                "price": round(price, 4),
                "quantity": quantity,
                "amount": round(amount, 2),
                "fee": round(fee, 2),
                "status": "filled",
                "reason": "strategy_signal",
            }
            position = {
                "account_id": account_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "name": latest.get("name") or "",
                "quantity": quantity,
                "avg_price": round(price, 4),
                "last_price": round(last_price, 4),
                "market_value": round(last_price * quantity, 2),
                "pnl": round((last_price - price) * quantity - fee, 2),
                "pnl_pct": self._pct(last_price - price, price),
            }
            self._insert_paper_order(order)
            self._upsert_paper_position(position)
            orders.append(order)
            positions.append(position)

        equity = round(cash + sum(item["market_value"] for item in positions), 2)
        self._update_paper_account(account_id, cash, equity)
        self._insert_equity_point(account_id, cash, equity)
        self._insert_paper_event(account_id, "info", "模拟盘已启动", {"symbols": resolved_symbols})
        return self.get_paper_account(account_id)

    def refresh_paper_account(self, account_id: int) -> Dict[str, Any]:
        account = self.get_paper_account(account_id)
        if account["status"] != "running":
            self._insert_paper_event(account_id, "warning", "模拟盘不是运行状态，刷新跳过")
            return self.get_paper_account(account_id)

        positions = []
        for item in account["positions"]:
            latest = self._load_latest_bar(item["symbol"])
            if not latest:
                positions.append(item)
                continue
            last_price = float(latest["close"])
            quantity = int(item["quantity"])
            market_value = round(last_price * quantity, 2)
            pnl = round((last_price - float(item["avg_price"])) * quantity, 2)
            pnl_pct = self._pct(last_price - float(item["avg_price"]), float(item["avg_price"]))
            position = {
                "account_id": account_id,
                "strategy_id": account["strategy_id"],
                "symbol": item["symbol"],
                "name": item.get("name") or latest.get("name") or "",
                "quantity": quantity,
                "avg_price": item["avg_price"],
                "last_price": round(last_price, 4),
                "market_value": market_value,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
            }
            self._upsert_paper_position(position)
            positions.append(position)

        equity = round(float(account["cash"]) + sum(item["market_value"] for item in positions), 2)
        self._update_paper_account(account_id, float(account["cash"]), equity)
        self._insert_equity_point(account_id, float(account["cash"]), equity)
        self._insert_paper_event(account_id, "info", "手动刷新完成", {"equity": equity})
        return self.get_paper_account(account_id)

    def stop_paper_account(self, account_id: int) -> Dict[str, Any]:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE paper_accounts SET status = {ph}, updated_at = {self._now_expr()} WHERE id = {ph}",
            ("stopped", account_id),
        )
        conn.commit()
        conn.close()
        self._insert_paper_event(account_id, "warning", "模拟盘已停止")
        return self.get_paper_account(account_id)

    def list_paper_accounts(self) -> List[Dict[str, Any]]:
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT pa.id, pa.strategy_id, ss.name, pa.name, pa.initial_capital,
                   pa.cash, pa.equity, pa.status, pa.created_at, pa.updated_at
            FROM paper_accounts pa
            LEFT JOIN strategy_scripts ss ON ss.id = pa.strategy_id
            ORDER BY pa.updated_at DESC
            LIMIT 50
            """
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "account_id": row[0],
                "strategy_id": row[1],
                "strategy_name": row[2],
                "name": row[3],
                "initial_capital": row[4],
                "cash": row[5],
                "equity": row[6],
                "status": row[7],
                "created_at": str(row[8]) if row[8] is not None else None,
                "updated_at": str(row[9]) if row[9] is not None else None,
            }
            for row in rows
        ]

    def get_paper_account(self, account_id: int) -> Dict[str, Any]:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT pa.id, pa.strategy_id, ss.name, pa.name, pa.initial_capital,
                   pa.cash, pa.equity, pa.status, pa.created_at, pa.updated_at
            FROM paper_accounts pa
            LEFT JOIN strategy_scripts ss ON ss.id = pa.strategy_id
            WHERE pa.id = {ph}
            """,
            (account_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.close()
            raise ValueError(f"Paper account {account_id} not found")

        cursor.execute(
            f"""
            SELECT symbol, name, side, price, quantity, amount, fee, status,
                   reason, created_at
            FROM paper_orders
            WHERE account_id = {ph}
            ORDER BY created_at DESC, id DESC
            """,
            (account_id,),
        )
        orders = [
            {
                "symbol": r[0],
                "name": r[1],
                "side": r[2],
                "price": r[3],
                "quantity": r[4],
                "amount": r[5],
                "fee": r[6],
                "status": r[7],
                "reason": r[8],
                "created_at": str(r[9]) if r[9] is not None else None,
            }
            for r in cursor.fetchall()
        ]
        cursor.execute(
            f"""
            SELECT symbol, name, quantity, avg_price, last_price, market_value,
                   pnl, pnl_pct, updated_at
            FROM paper_positions
            WHERE account_id = {ph}
            ORDER BY market_value DESC
            """,
            (account_id,),
        )
        positions = [
            {
                "symbol": r[0],
                "name": r[1],
                "quantity": r[2],
                "avg_price": r[3],
                "last_price": r[4],
                "market_value": r[5],
                "pnl": r[6],
                "pnl_pct": r[7],
                "updated_at": str(r[8]) if r[8] is not None else None,
            }
            for r in cursor.fetchall()
        ]
        cursor.execute(
            f"""
            SELECT equity, cash, created_at
            FROM paper_equity_curve
            WHERE account_id = {ph}
            ORDER BY created_at ASC, id ASC
            """,
            (account_id,),
        )
        equity_curve = [
            {
                "time": str(r[2]) if r[2] is not None else None,
                "equity": r[0],
                "cash": r[1],
            }
            for r in cursor.fetchall()
        ]
        cursor.execute(
            f"""
            SELECT level, message, payload, created_at
            FROM paper_events
            WHERE account_id = {ph}
            ORDER BY created_at ASC, id ASC
            """,
            (account_id,),
        )
        events = [
            {
                "level": r[0],
                "message": r[1],
                "payload": json.loads(r[2]) if r[2] else None,
                "created_at": str(r[3]) if r[3] is not None else None,
            }
            for r in cursor.fetchall()
        ]
        conn.close()

        return {
            "status": row[7],
            "account_id": row[0],
            "strategy_id": row[1],
            "strategy_name": row[2],
            "name": row[3],
            "initial_capital": row[4],
            "cash": row[5],
            "equity": row[6],
            "created_at": str(row[8]) if row[8] is not None else None,
            "updated_at": str(row[9]) if row[9] is not None else None,
            "orders": orders,
            "positions": positions,
            "equity_curve": equity_curve,
            "events": events,
        }

    def _strategy_class_from_script(self, script_content: str) -> Type[bt.Strategy]:
        if "bt.Strategy" in script_content or "backtrader.Strategy" in script_content:
            return self.load_custom_strategy_class(script_content)
        return RegisteredMomentumStrategy

    def _validate_strategy_ast(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in self.SAFE_IMPORTS:
                        raise ValueError(f"Import not allowed: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                if root not in self.SAFE_IMPORTS:
                    raise ValueError(f"Import not allowed: {node.module}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in self.FORBIDDEN_CALLS:
                    raise ValueError(f"Call not allowed: {node.func.id}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in self.FORBIDDEN_ATTRS:
                    raise ValueError(f"Attribute call not allowed: {node.func.attr}")

    def _safe_import(self, name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0]
        if root not in self.SAFE_IMPORTS:
            raise ImportError(f"Import not allowed: {name}")
        return __import__(name, globals, locals, fromlist, level)

    def _build_data_feed(self, symbol: str, rows: List[Dict[str, Any]]):
        df = pd.DataFrame(rows)
        df["datetime"] = pd.to_datetime(df["date"])
        for column in ["open", "high", "low", "close", "volume"]:
            df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
        df = df.sort_values("datetime")
        feed = bt.feeds.PandasData(
            dataname=df,
            datetime="datetime",
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume",
            openinterest=-1,
        )
        feed._stock_name = rows[0].get("name") or symbol
        return feed

    def _resolve_symbols(self, strategy_id: int, symbols: Optional[List[str]]) -> List[str]:
        cleaned = [self._normalize_symbol(s) for s in (symbols or []) if str(s or "").strip()]
        if cleaned:
            return list(dict.fromkeys(cleaned))

        if strategy_id:
            strategy = self.db.get_strategy_by_id(strategy_id)
            if strategy:
                parsed = self._extract_symbols_from_script(strategy.get("script_content") or "")
                if parsed:
                    return parsed

        latest = self.db.get_latest_strategy_result(strategy_id)
        if latest and latest.get("result_data"):
            try:
                payload = json.loads(latest["result_data"])
                items = payload.get("stocks") or []
                output = []
                for item in items:
                    code = item.get("code") if isinstance(item, dict) else item
                    if code:
                        output.append(self._normalize_symbol(str(code)))
                if output:
                    return list(dict.fromkeys(output))[:5]
            except Exception:
                pass

        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT symbol FROM kline_history
            WHERE timeframe = '1d'
            GROUP BY symbol
            ORDER BY COUNT(*) DESC, symbol ASC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        conn.close()
        return [row[0]] if row else []

    def _extract_symbols_from_script(self, script_content: str) -> List[str]:
        symbols: List[str] = []
        for token in script_content.replace('"', "'").split("'"):
            normalized = self._normalize_symbol(token.strip())
            if normalized.startswith(("SH_", "SZ_", "BJ_")) and normalized not in symbols:
                symbols.append(normalized)
        return symbols[:10]

    def _build_generated_strategy_script(self, objective: str, symbols: List[str], risk_level: str) -> str:
        risk_params = {
            "conservative": {"max_positions": 3, "entry_change": 0.008, "exit_change": -0.006},
            "balanced": {"max_positions": 5, "entry_change": 0.012, "exit_change": -0.008},
            "aggressive": {"max_positions": 8, "entry_change": 0.016, "exit_change": -0.01},
        }[risk_level]
        symbols_json = json.dumps(symbols, ensure_ascii=False)
        return f'''# StockPro 自动生成 A股 Backtrader 策略：{objective}
import backtrader as bt


class GeneratedAshareStrategy(bt.Strategy):
    params = dict(
        target_symbols={symbols_json},
        max_positions={risk_params["max_positions"]},
        position_pct=0.9,
        entry_change={risk_params["entry_change"]},
        exit_change={risk_params["exit_change"]},
    )

    def __init__(self):
        self.entry_date = {{}}

    def next(self):
        open_count = sum(1 for data in self.datas if self.getposition(data).size)
        slots = max(int(self.p.max_positions) - open_count, 0)
        candidates = []
        for data in self.datas:
            if data._name not in self.p.target_symbols or len(data.close) < 3:
                continue
            pos = self.getposition(data)
            momentum = (data.close[0] - data.close[-2]) / data.close[-2] if data.close[-2] else 0
            if pos.size:
                entry_date = self.entry_date.get(data._name)
                if entry_date and data.datetime.date(0) <= entry_date:
                    continue
                if momentum <= self.p.exit_change:
                    self.sell(data=data, size=pos.size)
            elif momentum >= self.p.entry_change and data.volume[0] >= data.volume[-1]:
                candidates.append((momentum, data))

        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates or slots <= 0:
            return
        allocation = self.broker.getcash() * self.p.position_pct / max(min(len(candidates), slots), 1)
        for _, data in candidates[:slots]:
            size = int((allocation / data.close[0]) // 100) * 100
            if size > 0:
                self.buy(data=data, size=size)
                self.entry_date[data._name] = data.datetime.date(0)
'''

    def _load_history(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        normalized = self._normalize_symbol(symbol)
        if hasattr(self.db, "get_kline_history"):
            rows = self.db.get_kline_history(
                normalized,
                timeframe="1d",
                start_date=start_date,
                end_date=end_date,
            )
        else:
            rows = self.db.get_stock_history(normalized, start_date=start_date, end_date=end_date)
        if len(rows) < 2:
            self._fetch_and_cache_history(normalized, start_date, end_date)
            if hasattr(self.db, "get_kline_history"):
                rows = self.db.get_kline_history(
                    normalized,
                    timeframe="1d",
                    start_date=start_date,
                    end_date=end_date,
                )
            else:
                rows = self.db.get_stock_history(normalized, start_date=start_date, end_date=end_date)
        result = []
        fallback_name = self._resolve_symbol_name(normalized)
        for row in rows:
            row_symbol = self._normalize_symbol(row.get("symbol") or row.get("code") or normalized)
            row_name = row.get("name") if self._is_valid_symbol_name(row_symbol, row.get("name")) else fallback_name
            result.append(
                {
                    "symbol": row_symbol,
                    "name": row_name,
                    "date": str(row.get("date")),
                    "open": row.get("open"),
                    "high": row.get("high"),
                    "low": row.get("low"),
                    "close": row.get("close"),
                    "volume": row.get("volume") or 0,
                    "turnover": row.get("turnover") or row.get("amount") or 0,
                }
            )
        return sorted(result, key=lambda item: item["date"])

    def _fetch_and_cache_history(self, symbol: str, start_date: Optional[str], end_date: Optional[str]) -> None:
        digits = "".join(ch for ch in symbol if ch.isdigit())
        if not digits:
            return
        start = (start_date or "2025-01-01").replace("-", "")
        end = (end_date or datetime.now().date().isoformat()).replace("-", "")
        try:
            df = ak.stock_zh_a_hist(symbol=digits, period="daily", start_date=start, end_date=end, adjust="qfq")
        except Exception:
            return
        if df is None or df.empty:
            return
        stock_name = self._resolve_symbol_name(symbol)
        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "symbol": symbol,
                    "name": str(row.get("股票简称") or row.get("名称") or stock_name or ""),
                    "date": str(row.get("日期")),
                    "open": row.get("开盘"),
                    "high": row.get("最高"),
                    "low": row.get("最低"),
                    "close": row.get("收盘"),
                    "volume": row.get("成交量") or 0,
                    "turnover": row.get("成交额") or 0,
                }
            )
        if hasattr(self.db, "insert_klines"):
            self.db.insert_klines(records, timeframe="1d")
        else:
            self.db.insert_stock_history_batch(records)

    def _load_latest_bar(self, symbol: str) -> Optional[Dict[str, Any]]:
        rows = self._load_history(symbol)
        return rows[-1] if rows else None

    def _save_backtest_result(self, result: Dict[str, Any]) -> int:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO strategy_backtest_results
            (strategy_id, symbols, start_date, end_date, initial_capital,
             final_capital, total_return, max_drawdown, win_rate, total_trades,
             equity_curve, trades, status)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            RETURNING id
            """,
            self._backtest_insert_params(result),
        )
        backtest_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return backtest_id

    def list_backtest_results(self, limit: int = 20) -> List[Dict[str, Any]]:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT b.id, b.strategy_id, COALESCE(s.name, '未命名策略') AS strategy_name,
                   b.symbols, b.start_date, b.end_date, b.initial_capital,
                   b.final_capital, b.total_return, b.max_drawdown, b.win_rate,
                   b.total_trades, b.equity_curve, b.trades, b.status, b.created_at
            FROM strategy_backtest_results b
            LEFT JOIN strategy_scripts s ON s.id = b.strategy_id
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT {ph}
            """,
            (limit,),
        )
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return [self._backtest_result_row(row) for row in rows]

    def _backtest_result_row(self, row: Dict[str, Any]) -> Dict[str, Any]:
        equity_curve = self._json_loads(row.get("equity_curve"), [])
        trades = self._json_loads(row.get("trades"), [])
        symbols = self._json_loads(row.get("symbols"), [])
        if isinstance(symbols, str):
            symbols = [symbols]
        symbol_names = self._symbol_name_map(symbols)
        trade_items = trades if isinstance(trades, list) else []
        for trade in trade_items:
            if not isinstance(trade, dict):
                continue
            symbol = self._normalize_symbol(trade.get("symbol") or "")
            if self._is_valid_symbol_name(symbol, trade.get("name")):
                symbol_names[symbol] = trade["name"]
            elif symbol:
                trade["name"] = symbol_names.get(symbol) or ""
        return {
            "engine": "backtrader",
            "status": row.get("status") or "completed",
            "backtest_id": row.get("id"),
            "strategy_id": row.get("strategy_id"),
            "strategy_name": row.get("strategy_name") or "未命名策略",
            "symbols": symbols,
            "symbol_names": symbol_names,
            "start_date": self._date_str(row.get("start_date")),
            "end_date": self._date_str(row.get("end_date")),
            "initial_capital": float(row.get("initial_capital") or 0),
            "final_capital": float(row.get("final_capital") or 0),
            "total_return": float(row.get("total_return") or 0),
            "annual_return": None,
            "max_drawdown": float(row.get("max_drawdown") or 0),
            "sharpe": None,
            "profit_factor": None,
            "win_rate": float(row.get("win_rate") or 0),
            "total_trades": int(row.get("total_trades") or 0),
            "equity_curve": equity_curve if isinstance(equity_curve, list) else [],
            "trades": trades if isinstance(trades, list) else [],
            "created_at": self._date_str(row.get("created_at"), include_time=True),
        }

    def _json_loads(self, value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, (list, dict)):
            return value
        try:
            return json.loads(value)
        except Exception:
            return default

    def _date_str(self, value: Any, include_time: bool = False) -> str:
        if value is None:
            return ""
        if hasattr(value, "isoformat"):
            return value.isoformat(timespec="seconds") if include_time and isinstance(value, datetime) else value.isoformat()
        return str(value)

    def _backtest_insert_params(self, result: Dict[str, Any]) -> Tuple[Any, ...]:
        return (
            result["strategy_id"],
            json.dumps(result["symbols"], ensure_ascii=False),
            result["start_date"],
            result["end_date"],
            result["initial_capital"],
            result["final_capital"],
            result["total_return"],
            result["max_drawdown"],
            result["win_rate"],
            result["total_trades"],
            json.dumps(result["equity_curve"], ensure_ascii=False),
            json.dumps(result["trades"], ensure_ascii=False),
            result["status"],
        )

    def _create_paper_account(self, strategy_id: int, name: str, initial_capital: float) -> int:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO paper_accounts
            (strategy_id, name, initial_capital, cash, equity, status)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, 'running')
            RETURNING id
            """,
            (strategy_id, name, initial_capital, initial_capital, initial_capital),
        )
        account_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return account_id

    def _update_paper_account(self, account_id: int, cash: float, equity: float) -> None:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            UPDATE paper_accounts
            SET cash = {ph}, equity = {ph}, updated_at = {self._now_expr()}
            WHERE id = {ph}
            """,
            (round(cash, 2), round(equity, 2), account_id),
        )
        conn.commit()
        conn.close()

    def _insert_paper_order(self, order: Dict[str, Any]) -> int:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        params = (
            order["account_id"],
            order["strategy_id"],
            order["symbol"],
            order.get("name"),
            order["side"],
            order["price"],
            order["quantity"],
            order["amount"],
            order["fee"],
            order["status"],
            order.get("reason"),
        )
        cursor.execute(
            f"""
            INSERT INTO paper_orders
            (account_id, strategy_id, symbol, name, side, price, quantity,
             amount, fee, status, reason)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
            RETURNING id
            """,
            params,
        )
        order_id = cursor.fetchone()[0]
        conn.commit()
        conn.close()
        return order_id

    def _upsert_paper_position(self, position: Dict[str, Any]) -> None:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        params = (
            position["account_id"],
            position["strategy_id"],
            position["symbol"],
            position.get("name"),
            position["quantity"],
            position["avg_price"],
            position["last_price"],
            position["market_value"],
            position["pnl"],
            position["pnl_pct"],
        )
        cursor.execute(
            f"""
            INSERT INTO paper_positions
            (account_id, strategy_id, symbol, name, quantity, avg_price,
             last_price, market_value, pnl, pnl_pct, updated_at)
            VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, CURRENT_TIMESTAMP)
            ON CONFLICT (account_id, symbol) DO UPDATE SET
                name = EXCLUDED.name,
                quantity = EXCLUDED.quantity,
                avg_price = EXCLUDED.avg_price,
                last_price = EXCLUDED.last_price,
                market_value = EXCLUDED.market_value,
                pnl = EXCLUDED.pnl,
                pnl_pct = EXCLUDED.pnl_pct,
                updated_at = CURRENT_TIMESTAMP
            """,
            params,
        )
        conn.commit()
        conn.close()

    def _insert_equity_point(self, account_id: int, cash: float, equity: float) -> None:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO paper_equity_curve (account_id, equity, cash)
            VALUES ({ph}, {ph}, {ph})
            """,
            (account_id, round(equity, 2), round(cash, 2)),
        )
        conn.commit()
        conn.close()

    def _insert_paper_event(self, account_id: int, level: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        ph = self._placeholder()
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO paper_events (account_id, level, message, payload)
            VALUES ({ph}, {ph}, {ph}, {ph})
            """,
            (account_id, level, message, json.dumps(payload, ensure_ascii=False) if payload else None),
        )
        conn.commit()
        conn.close()

    def _merge_trade_pnl(self, orders: List[Dict[str, Any]], closed_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pnl_by_symbol: Dict[str, List[float]] = {}
        for trade in closed_trades:
            pnl_by_symbol.setdefault(trade["symbol"], []).append(trade["pnl"])
        merged = []
        for order in orders:
            item = dict(order)
            if item["side"] == "sell" and pnl_by_symbol.get(item["symbol"]):
                item["pnl"] = pnl_by_symbol[item["symbol"]].pop(0)
            merged.append(item)
        return merged

    def _symbol_name_map(
        self,
        symbols: List[str],
        histories: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    ) -> Dict[str, str]:
        normalized_symbols = [self._normalize_symbol(symbol) for symbol in symbols if str(symbol or "").strip()]
        normalized_symbols = list(dict.fromkeys(normalized_symbols))
        names: Dict[str, str] = {}
        histories = histories or {}
        for symbol in normalized_symbols:
            for row in histories.get(symbol, []):
                name = str(row.get("name") or "").strip()
                if self._is_valid_symbol_name(symbol, name):
                    names[symbol] = name
                    break
        missing = [symbol for symbol in normalized_symbols if not names.get(symbol)]
        if missing:
            names.update(self._lookup_symbol_names(missing))
        for symbol in normalized_symbols:
            names.setdefault(symbol, self.SYMBOL_NAME_FALLBACKS.get(symbol, ""))
        return names

    def _resolve_symbol_name(self, symbol: str) -> str:
        normalized = self._normalize_symbol(symbol)
        return self._symbol_name_map([normalized]).get(normalized, "")

    def _lookup_symbol_names(self, symbols: List[str]) -> Dict[str, str]:
        normalized_symbols = [self._normalize_symbol(symbol) for symbol in symbols if str(symbol or "").strip()]
        normalized_symbols = list(dict.fromkeys(normalized_symbols))
        if not normalized_symbols:
            return {}

        names: Dict[str, str] = {}
        table_queries = [
            ("all_stocks_realtime", "code", True),
            ("stock_fundamentals", "symbol", False),
            ("stock_history", "symbol", False),
            ("kline_history", "symbol", False),
        ]
        conn = self.db.get_connection()
        cursor = conn.cursor()
        try:
            for table, symbol_column, include_digits in table_queries:
                missing = [symbol for symbol in normalized_symbols if not names.get(symbol)]
                if not missing:
                    break
                candidates: List[str] = []
                for symbol in missing:
                    candidates.append(symbol)
                    digits = "".join(ch for ch in symbol if ch.isdigit())
                    if include_digits and digits:
                        candidates.append(digits)
                candidates = list(dict.fromkeys(candidates))
                placeholders = ", ".join([self._placeholder()] * len(candidates))
                cursor.execute(
                    f"""
                    SELECT {symbol_column}, name
                    FROM {table}
                    WHERE {symbol_column} IN ({placeholders})
                      AND COALESCE(name, '') <> ''
                    """,
                    tuple(candidates),
                )
                for raw_symbol, name in cursor.fetchall():
                    normalized = self._normalize_symbol(raw_symbol)
                    if normalized in normalized_symbols and self._is_valid_symbol_name(normalized, name) and not names.get(normalized):
                        names[normalized] = str(name).strip()
        except Exception:
            pass
        finally:
            conn.close()
        return names

    def _is_valid_symbol_name(self, symbol: str, name: Any) -> bool:
        clean_name = str(name or "").strip()
        if not clean_name:
            return False
        normalized_symbol = self._normalize_symbol(symbol)
        return self._normalize_symbol(clean_name) != normalized_symbol and clean_name.upper() != normalized_symbol

    def _normalize_symbol(self, symbol: str) -> str:
        text = str(symbol or "").strip().upper().replace(".", "_")
        if text.startswith(("SH_", "SZ_", "BJ_")):
            return text
        digits = "".join(ch for ch in text if ch.isdigit())
        if not digits:
            return text
        if digits.startswith("6"):
            return f"SH_{digits}"
        if digits.startswith(("8", "4")):
            return f"BJ_{digits}"
        return f"SZ_{digits}"

    def _round_lot(self, quantity: float) -> int:
        if math.isnan(quantity) or quantity <= 0:
            return 0
        return int(quantity // 100) * 100

    def _pct(self, numerator: float, denominator: float) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator * 100, 2)

    def _max_drawdown(self, equity_curve: List[Dict[str, Any]]) -> float:
        peak = 0.0
        max_dd = 0.0
        for point in equity_curve:
            equity = float(point["equity"])
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        return round(max_dd, 2)

    def _annual_return(self, equity_curve: List[Dict[str, Any]], initial: float, final: float) -> float:
        if len(equity_curve) < 2 or initial <= 0:
            return self._pct(final - initial, initial)
        try:
            start = datetime.fromisoformat(equity_curve[0]["date"])
            end = datetime.fromisoformat(equity_curve[-1]["date"])
            days = max((end - start).days, 1)
            return round(((final / initial) ** (365 / days) - 1) * 100, 2)
        except Exception:
            return self._pct(final - initial, initial)

    def _sharpe(self, equity_curve: List[Dict[str, Any]]) -> float:
        if len(equity_curve) < 3:
            return 0.0
        returns = []
        for prev, current in zip(equity_curve, equity_curve[1:]):
            prev_value = float(prev["equity"])
            if prev_value:
                returns.append((float(current["equity"]) - prev_value) / prev_value)
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
        std = math.sqrt(variance)
        return round((mean / std) * math.sqrt(252), 2) if std else 0.0

    def _placeholder(self) -> str:
        return "%s"

    def _now_expr(self) -> str:
        return "CURRENT_TIMESTAMP"


strategy_lab_service = StrategyLabService()

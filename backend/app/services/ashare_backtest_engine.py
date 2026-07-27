"""Deterministic daily A-share broker and portfolio accounting engine."""
from __future__ import annotations

import math
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from app.services.backtest_metrics_service import calculate_backtest_metrics, drawdown_series, monthly_returns


def _date_text(value: Any) -> str:
    return str(value)[:10]


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def next_weekday(value: str) -> str:
    current = date.fromisoformat(value) + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current.isoformat()


class AShareBacktestEngine:
    calculation_version = "ashare-broker.v1"

    def __init__(
        self,
        *,
        bars: Sequence[Mapping[str, Any]],
        intents: Sequence[Mapping[str, Any]],
        initial_cash: float,
        cost_model: Mapping[str, Any],
        price_limits: Sequence[Mapping[str, Any]] = (),
        suspensions: Sequence[Mapping[str, Any]] = (),
        corporate_actions: Sequence[Mapping[str, Any]] = (),
        benchmark_bars: Sequence[Mapping[str, Any]] = (),
        benchmark_symbol: str = "SH_000300",
        industry_by_symbol: Optional[Mapping[str, Optional[str]]] = None,
    ):
        self.initial_cash = float(initial_cash)
        if self.initial_cash <= 0:
            raise ValueError("initial_cash 必须为正数")
        self.cost = dict(cost_model)
        self.industry_by_symbol = dict(industry_by_symbol or {})
        self.bars = [dict(item) for item in bars]
        self.intents = [dict(item) for item in intents]
        self.benchmark_symbol = str(benchmark_symbol)
        self.bar_map = {(_date_text(item["trade_date"]), str(item["symbol"])): dict(item) for item in self.bars}
        self.dates = sorted({_date_text(item["trade_date"]) for item in self.bars})
        self.symbols = sorted({str(item["symbol"]) for item in self.bars})
        self.limit_map = {(_date_text(item["trade_date"]), str(item["symbol"])): dict(item) for item in price_limits}
        self.suspension_map = {(_date_text(item["trade_date"]), str(item["symbol"])): dict(item) for item in suspensions if str(item.get("suspend_type") or "S") == "S"}
        self.actions_by_date: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in corporate_actions:
            self.actions_by_date[_date_text(item.get("ex_date"))].append(dict(item))
        self.benchmark_map = {
            _date_text(item["trade_date"]): dict(item)
            for item in benchmark_bars
            if str(item.get("symbol")) == self.benchmark_symbol
        }

    def run(self) -> Dict[str, Any]:
        if not self.dates:
            raise ValueError("回测区间没有封存日线")
        cash = self.initial_cash
        positions: Dict[str, Dict[str, Any]] = {}
        orders = self._build_orders()
        trades: List[Dict[str, Any]] = []
        daily_positions: List[Dict[str, Any]] = []
        equity_rows: List[Dict[str, Any]] = []
        logs: List[Dict[str, Any]] = []
        quality_warnings: set[str] = set()
        capacity_warning_count = 0
        cost_totals = defaultdict(float)
        turnover_amount = 0.0
        realized_by_symbol = defaultdict(float)
        peak_single_weight = 0.0
        first_benchmark_close: Optional[float] = None
        last_benchmark_nav: Optional[float] = None

        for current_date in self.dates:
            for position in positions.values():
                position["available_quantity"] = position["quantity"]
            cash = self._apply_corporate_actions(current_date, positions, cash, logs)

            for order in orders:
                if order["status"] != "created" or order["earliest_fill_date"] > current_date:
                    continue
                symbol = order["symbol"]
                bar = self.bar_map.get((current_date, symbol))
                if not bar or (current_date, symbol) in self.suspension_map:
                    order["last_blocker"] = "SUSPENDED"
                    continue
                order["submitted_at"] = order["submitted_at"] or f"{current_date}T09:25:00+08:00"
                base_price = _number(bar.get("open"))
                if base_price <= 0:
                    order["last_blocker"] = "INVALID_EXECUTION_PRICE"
                    continue
                portfolio_at_open = cash + sum(
                    item["quantity"] * _number((self.bar_map.get((current_date, code)) or {}).get("open"), item["avg_cost"])
                    for code, item in positions.items()
                )
                delta, rejection = self._resolve_quantity(order, positions.get(symbol), portfolio_at_open, base_price)
                if rejection:
                    self._reject(order, rejection, current_date)
                    continue
                if delta == 0:
                    order.update({"status": "cancelled", "rejection_code": "TARGET_ALREADY_MET", "rejection_reason": "目标仓位已满足"})
                    continue
                side = "buy" if delta > 0 else "sell"
                quantity = abs(int(delta))
                rule = self.limit_map.get((current_date, symbol))
                if rule is None:
                    quality_warnings.add(f"MISSING_PRICE_LIMIT:{current_date}:{symbol}")
                elif bool(rule.get("has_price_limit", True)):
                    if side == "buy" and rule.get("up_limit") is not None and base_price >= _number(rule["up_limit"]):
                        self._reject(order, "LIMIT_UP", current_date)
                        continue
                    if side == "sell" and rule.get("down_limit") is not None and base_price <= _number(rule["down_limit"]):
                        self._reject(order, "LIMIT_DOWN", current_date)
                        continue

                slippage_rate = _number(self.cost.get("slippage_rate"))
                execution_price = base_price * (1 + slippage_rate if side == "buy" else 1 - slippage_rate)
                if side == "buy":
                    quantity = self._affordable_quantity(quantity, execution_price, cash)
                    if quantity <= 0:
                        self._reject(order, "INSUFFICIENT_CASH", current_date)
                        continue
                amount = execution_price * quantity
                fees = self._fees(side, amount)
                if side == "sell":
                    position = positions.get(symbol)
                    if not position or quantity > int(position["available_quantity"]):
                        self._reject(order, "T1_NOT_AVAILABLE", current_date)
                        continue

                turnover = _number(bar.get("turnover"))
                if str(bar.get("source") or "").lower() == "tushare":
                    turnover *= 1000.0
                capacity_ratio = amount / turnover if turnover > 0 else None
                if capacity_ratio is None:
                    quality_warnings.add(f"MISSING_TURNOVER:{current_date}:{symbol}")
                elif capacity_ratio > _number(self.cost.get("max_participation_rate"), 0.10):
                    capacity_warning_count += 1

                order_id = order["id"]
                realized_pnl = None
                holding_days = None
                if side == "buy":
                    total_cost = amount + fees["commission"] + fees["transfer_fee"]
                    cash -= total_cost
                    position = positions.setdefault(symbol, {
                        "quantity": 0,
                        "available_quantity": 0,
                        "avg_cost": 0.0,
                        "first_acquired_date": current_date,
                    })
                    old_cost = position["avg_cost"] * position["quantity"]
                    position["quantity"] += quantity
                    position["avg_cost"] = (old_cost + total_cost) / position["quantity"]
                else:
                    position = positions[symbol]
                    cash += amount - fees["commission"] - fees["tax"] - fees["transfer_fee"]
                    realized_pnl = (execution_price - position["avg_cost"]) * quantity - fees["commission"] - fees["tax"] - fees["transfer_fee"]
                    holding_days = (date.fromisoformat(current_date) - date.fromisoformat(position["first_acquired_date"])).days
                    realized_by_symbol[symbol] += realized_pnl
                    position["quantity"] -= quantity
                    position["available_quantity"] -= quantity
                    if position["quantity"] <= 0:
                        del positions[symbol]

                slippage_cost = abs(execution_price - base_price) * quantity
                turnover_amount += amount
                cost_totals["commission"] += fees["commission"]
                cost_totals["tax"] += fees["tax"]
                cost_totals["transfer_fee"] += fees["transfer_fee"]
                cost_totals["slippage_cost"] += slippage_cost
                order.update({
                    "status": "filled", "side": side, "requested_quantity": abs(int(delta)),
                    "filled_quantity": quantity, "filled_at": f"{current_date}T09:30:00+08:00",
                    "execution_price": round(execution_price, 4), "execution_price_source": "unadjusted_daily_open",
                    "capacity_ratio": capacity_ratio,
                })
                trades.append({
                    "id": str(uuid.uuid4()), "backtest_order_id": order_id, "trade_date": current_date,
                    "symbol": symbol, "name": bar.get("name") or "", "side": side,
                    "price": round(execution_price, 4), "quantity": quantity, "amount": round(amount, 4),
                    "commission": round(fees["commission"], 4), "tax": round(fees["tax"], 4),
                    "transfer_fee": round(fees["transfer_fee"], 4), "slippage_cost": round(slippage_cost, 4),
                    "realized_pnl": round(realized_pnl, 4) if realized_pnl is not None else None,
                    "holding_days": holding_days, "reason": "strategy_intent", "signal_at": order["signal_at"],
                    "data_available_at": order["data_available_at"], "submitted_at": order["submitted_at"],
                    "earliest_fill_at": order["earliest_fill_at"], "filled_at": order["filled_at"],
                    "execution_price_source": "unadjusted_daily_open",
                })

            market_value = 0.0
            position_marks: List[Dict[str, Any]] = []
            for symbol, position in positions.items():
                bar = self.bar_map.get((current_date, symbol))
                close = _number((bar or {}).get("close"), position["avg_cost"])
                value = close * position["quantity"]
                market_value += value
                position_marks.append({"symbol": symbol, "position": position, "close": close, "market_value": value})
            equity = cash + market_value
            strategy_nav = equity / self.initial_cash
            previous_nav = equity_rows[-1]["strategy_nav"] if equity_rows else None
            strategy_return = strategy_nav / previous_nav - 1 if previous_nav else None
            benchmark = self.benchmark_map.get(current_date)
            benchmark_close = _number((benchmark or {}).get("close"))
            if benchmark_close > 0 and first_benchmark_close is None:
                first_benchmark_close = benchmark_close
            benchmark_nav = benchmark_close / first_benchmark_close if benchmark_close > 0 and first_benchmark_close else last_benchmark_nav
            benchmark_return = benchmark_nav / last_benchmark_nav - 1 if benchmark_nav is not None and last_benchmark_nav else None
            if benchmark_nav is not None:
                last_benchmark_nav = benchmark_nav
            excess_nav = strategy_nav / benchmark_nav if benchmark_nav else None
            equity_rows.append({
                "trade_date": current_date, "strategy_nav": strategy_nav, "strategy_return": strategy_return,
                "benchmark_nav": benchmark_nav, "benchmark_return": benchmark_return,
                "excess_nav": excess_nav, "excess_return": strategy_return - benchmark_return if strategy_return is not None and benchmark_return is not None else None,
                "equity": equity, "cash": cash, "market_value": market_value,
                "gross_exposure": market_value / equity if equity else 0.0,
                "net_exposure": market_value / equity if equity else 0.0,
                "position_count": len(positions), "drawdown": 0.0, "excess_drawdown": None,
            })
            for mark in position_marks:
                weight = mark["market_value"] / equity if equity else 0.0
                peak_single_weight = max(peak_single_weight, weight)
                position = mark["position"]
                daily_positions.append({
                    "trade_date": current_date, "symbol": mark["symbol"], "quantity": position["quantity"],
                    "available_quantity": position["available_quantity"], "avg_cost": position["avg_cost"],
                    "close_price": mark["close"], "market_value": mark["market_value"], "weight": weight,
                    "unrealized_pnl": (mark["close"] - position["avg_cost"]) * position["quantity"],
                    "industry_code": self.industry_by_symbol.get(mark["symbol"]),
                })

        for order in orders:
            if order["status"] == "created":
                code = order.get("last_blocker") or "NO_FUTURE_EXECUTABLE_BAR"
                order.update({"status": "expired", "rejection_code": code, "rejection_reason": self._reason(code)})

        strategy_drawdowns, _, _, _ = drawdown_series([item["strategy_nav"] for item in equity_rows])
        excess_values = [item["excess_nav"] for item in equity_rows if item["excess_nav"] is not None]
        excess_drawdowns, _, _, _ = drawdown_series(excess_values)
        excess_index = 0
        for index, row in enumerate(equity_rows):
            row["drawdown"] = strategy_drawdowns[index]
            if row["excess_nav"] is not None:
                row["excess_drawdown"] = excess_drawdowns[excess_index]
                excess_index += 1

        metrics = calculate_backtest_metrics(
            equity_rows, trades, orders, initial_cash=self.initial_cash,
            total_commission=cost_totals["commission"], total_tax=cost_totals["tax"],
            total_transfer_fee=cost_totals["transfer_fee"], total_slippage_cost=cost_totals["slippage_cost"],
            turnover_amount=turnover_amount, peak_single_symbol_weight=peak_single_weight,
            capacity_warning_count=capacity_warning_count, data_quality_warning_count=len(quality_warnings),
        )
        ending_positions = {item["symbol"]: item for item in daily_positions if item["trade_date"] == self.dates[-1]}
        attribution = [
            {"attribution_type": "symbol", "attribution_key": symbol, "amount": amount, "contribution": amount / self.initial_cash, "payload": {}}
            for symbol, amount in sorted(realized_by_symbol.items())
        ]
        attribution.extend([
            {"attribution_type": "cost", "attribution_key": "commission", "amount": -cost_totals["commission"], "contribution": -cost_totals["commission"] / self.initial_cash, "payload": {}},
            {"attribution_type": "cost", "attribution_key": "tax", "amount": -cost_totals["tax"], "contribution": -cost_totals["tax"] / self.initial_cash, "payload": {}},
            {"attribution_type": "cost", "attribution_key": "transfer_fee", "amount": -cost_totals["transfer_fee"], "contribution": -cost_totals["transfer_fee"] / self.initial_cash, "payload": {}},
            {"attribution_type": "cost", "attribution_key": "slippage", "amount": -cost_totals["slippage_cost"], "contribution": -cost_totals["slippage_cost"] / self.initial_cash, "payload": {}},
        ])
        return {
            "status": "success", "orders": orders, "trades": trades, "daily_equity": equity_rows,
            "daily_positions": daily_positions, "metrics": metrics, "logs": logs,
            "attribution": attribution, "monthly_returns": monthly_returns(equity_rows),
            "quality_warnings": sorted(quality_warnings), "capacity_warning_count": capacity_warning_count,
            "ending_positions": ending_positions,
        }

    def _build_orders(self) -> List[Dict[str, Any]]:
        output = []
        for raw in self.intents:
            payload = dict(raw.get("payload") or raw)
            signal_date = _date_text(raw.get("simulated_at") or payload.get("simulated_at"))
            future_dates = [item for item in self.dates if item > signal_date]
            earliest_date = future_dates[0] if future_dates else next_weekday(signal_date)
            output.append({
                "id": str(uuid.uuid4()), "replay_intent_id": raw.get("id"),
                "event_ordinal": int(raw.get("event_ordinal") or payload.get("event_ordinal") or 0),
                "symbol": str(raw.get("symbol") or payload.get("symbol") or ""),
                "intent_type": str(raw.get("intent_type") or payload.get("intent_type") or ""),
                "side": None, "requested_value": payload.get("value"), "requested_quantity": None,
                "filled_quantity": 0, "status": "created",
                "signal_at": str(raw.get("simulated_at") or payload.get("simulated_at")),
                "data_available_at": str(raw.get("available_at") or payload.get("available_at")),
                "submitted_at": None, "earliest_fill_date": earliest_date,
                "earliest_fill_at": f"{earliest_date}T09:30:00+08:00", "filled_at": None,
                "execution_price": None, "execution_price_source": None,
                "rejection_code": None, "rejection_reason": None, "capacity_ratio": None,
                "intent_payload": payload, "last_blocker": None,
            })
        return output

    def _resolve_quantity(
        self,
        order: Mapping[str, Any],
        position: Optional[Mapping[str, Any]],
        equity: float,
        price: float,
    ) -> tuple[int, Optional[str]]:
        intent_type = str(order["intent_type"])
        value = _number(order.get("requested_value"))
        current = int((position or {}).get("quantity") or 0)
        available = int((position or {}).get("available_quantity") or 0)
        explicit = intent_type == "order"
        if intent_type == "order":
            delta = int(value)
        elif intent_type == "order_value":
            delta = int(value / price)
        elif intent_type == "order_target":
            delta = int(value) - current
        elif intent_type == "order_target_value":
            delta = int(value / price) - current
        elif intent_type == "order_target_percent":
            if value < 0 or value > 1:
                return 0, "SHORT_OR_LEVERAGE_NOT_SUPPORTED"
            delta = int((equity * value) / price) - current
        elif intent_type == "cancel_order":
            return 0, "CANCEL_NOT_MATCHED"
        else:
            return 0, "UNSUPPORTED_INTENT"
        if delta > 0:
            if explicit and delta % 100 != 0:
                return 0, "INVALID_LOT_SIZE"
            delta = (delta // 100) * 100
        elif delta < 0:
            desired = abs(delta)
            if desired >= current:
                desired = current
            elif explicit and desired % 100 != 0:
                return 0, "INVALID_LOT_SIZE"
            else:
                desired = (desired // 100) * 100
            if desired > available:
                return 0, "T1_NOT_AVAILABLE"
            delta = -desired
        return delta, None

    def _fees(self, side: str, amount: float) -> Dict[str, float]:
        commission = max(amount * _number(self.cost.get("commission_rate")), _number(self.cost.get("minimum_commission"), 5.0))
        tax = amount * _number(self.cost.get("stamp_duty_rate")) if side == "sell" else 0.0
        transfer_fee = amount * _number(self.cost.get("transfer_fee_rate"))
        return {"commission": commission, "tax": tax, "transfer_fee": transfer_fee}

    def _affordable_quantity(self, requested: int, price: float, cash: float) -> int:
        quantity = (requested // 100) * 100
        while quantity > 0:
            amount = price * quantity
            fees = self._fees("buy", amount)
            if amount + fees["commission"] + fees["transfer_fee"] <= cash + 1e-9:
                return quantity
            quantity -= 100
        return 0

    def _apply_corporate_actions(
        self,
        current_date: str,
        positions: Dict[str, Dict[str, Any]],
        cash: float,
        logs: List[Dict[str, Any]],
    ) -> float:
        for action in self.actions_by_date.get(current_date, []):
            symbol = str(action.get("symbol") or "")
            position = positions.get(symbol)
            if not position:
                continue
            available_at = action.get("announcement_available_at")
            if available_at and _date_text(available_at) > current_date:
                continue
            old_quantity = int(position["quantity"])
            share_rate = sum(_number(action.get(field)) for field in ("stk_div", "stk_bo_rate", "stk_co_rate"))
            if share_rate > 0:
                new_quantity = int(math.floor(old_quantity * (1 + share_rate)))
                if new_quantity > old_quantity:
                    position["quantity"] = new_quantity
                    position["available_quantity"] = new_quantity
                    position["avg_cost"] = position["avg_cost"] * old_quantity / new_quantity
            cash_dividend = action.get("cash_div_tax") if action.get("cash_div_tax") is not None else action.get("cash_div")
            cash_delta = old_quantity * _number(cash_dividend)
            cash += cash_delta
            logs.append({
                "simulated_at": f"{current_date}T09:00:00+08:00", "level": "info", "source": "corporate_action",
                "message": f"{symbol} 公司行动已入账", "payload": {"share_rate": share_rate, "cash_delta": cash_delta},
            })
        return cash

    def _reject(self, order: Dict[str, Any], code: str, current_date: str) -> None:
        order.update({
            "status": "rejected", "submitted_at": order.get("submitted_at") or f"{current_date}T09:25:00+08:00",
            "rejection_code": code, "rejection_reason": self._reason(code),
        })

    @staticmethod
    def _reason(code: str) -> str:
        return {
            "INVALID_LOT_SIZE": "买入委托必须为 100 股整数手",
            "T1_NOT_AVAILABLE": "卖出数量超过 T+1 可用数量",
            "SUSPENDED": "证券停牌或没有可执行日线",
            "LIMIT_UP": "涨停价不接受买入",
            "LIMIT_DOWN": "跌停价不接受卖出",
            "INSUFFICIENT_CASH": "可用现金不足",
            "SHORT_OR_LEVERAGE_NOT_SUPPORTED": "初始模型不支持做空或杠杆",
            "NO_FUTURE_EXECUTABLE_BAR": "回测结束前没有下一可执行日线",
            "INVALID_EXECUTION_PRICE": "执行价格不可用",
            "UNSUPPORTED_INTENT": "运行时委托类型不受回测 Broker 支持",
            "CANCEL_NOT_MATCHED": "未找到可取消的待处理委托",
        }.get(code, code)

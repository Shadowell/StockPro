"""TradFi 高波动美股 / 杠杆 ETF 永续 1H 趋势策略（paper-only 观察盘）。

在 CTA 趋势基类（1H EMA5/20 + 2.5 ATR 止损 + 浮盈保护套件 + 美股时段过滤）之上叠加：

1. 效率比 regime 门（`er_window` / `er_min`）：1H 收盘序列的方向位移/路径长度低于
   门槛时禁止新开仓，压制杠杆 ETF 震荡期的波动衰减磨损；
2. 杠杆 ETF 名义折减（`etf_symbols` / `etf_size_mult`）：内置杠杆标的按系数折减名义；
3. 亏损冷却（`loss_cooldown_bars`）：单标的每笔已平仓亏损后冷却 N 根 K 线再允许新开仓；
4. 账户级权益棘轮（`ratchet_step_pct` / `ratchet_lock_fraction`）：权益每较基准增长一个
   台阶就抬高锁定地板，权益跌破地板时暂停全部新开仓（存量持仓仍按退出规则管理）。

棘轮与冷却状态经 `_tradfi_trend_runtime` 持久化，重启自动恢复。

研究背景（docs/contracts/tradfi-leveraged-trend-strategy.md）：回测样本内该配置为
最优变体但组合净期望仍为负（-56U/7 标的），本策略为操作者要求的 paper 观察性部署，
不是已验证正期望策略，禁止在未重新过研究闸门前提升实盘。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional

from app.core.execution.base_strategy import BarData
from app.services.contract_paper_account import normalize_contract_symbol
from app.strategies.cta_trend_following_strategy import CtaTrendFollowingStrategy

logger = logging.getLogger(__name__)

RUNTIME_STATE_KEY = "_tradfi_trend_runtime"
_RUNTIME_STATE_VERSION = 1


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class TradfiLeveragedTrendStrategy(CtaTrendFollowingStrategy):
    """1H 力度的 TradFi 永续趋势策略：ER regime 门 + ETF 折减 + 亏损冷却 + 权益棘轮。"""

    async def on_init(self) -> None:
        await super().on_init()
        cfg = self.config or {}

        self.er_window = max(2, int(cfg.get("er_window", 24)))
        self.er_min = max(0.0, float(cfg.get("er_min", 0.25)))
        self.etf_size_mult = min(1.0, max(0.0, float(cfg.get("etf_size_mult", 0.5))))
        self.etf_symbols = {
            normalize_contract_symbol(str(symbol))
            for symbol in (cfg.get("etf_symbols") or [])
            if str(symbol).strip()
        }
        self.loss_cooldown_bars = max(0, int(cfg.get("loss_cooldown_bars", 6)))
        self.ratchet_step_pct = max(0.0, float(cfg.get("ratchet_step_pct", 25.0)))
        self.ratchet_lock_fraction = min(1.0, max(0.0, float(cfg.get("ratchet_lock_fraction", 0.5))))

        self._bar_interval_ms = max(1, self._timeframe_minutes(str(cfg.get("timeframe", "1h")))) * 60_000
        self._ratchet_base = 0.0
        self._ratchet_floor = 0.0
        self._cooldown_until_ms: Dict[str, int] = {}
        self._seen_trade_count = 0
        self._restore_runtime_state()

    # -- 状态持久化 ---------------------------------------------------------

    def _restore_runtime_state(self) -> None:
        payload = self.state.positions.get(RUNTIME_STATE_KEY)
        if not isinstance(payload, Mapping):
            return
        if _safe_int(payload.get("version"), -1) != _RUNTIME_STATE_VERSION:
            logger.warning("TradFi 趋势策略运行时状态版本不匹配，回退全新状态")
            return
        self._ratchet_base = max(0.0, _safe_float(payload.get("ratchet_base")))
        self._ratchet_floor = max(0.0, _safe_float(payload.get("ratchet_floor")))
        cooldowns = payload.get("cooldown_until_ms") or {}
        if isinstance(cooldowns, Mapping):
            self._cooldown_until_ms = {
                normalize_contract_symbol(str(symbol)): _safe_int(until)
                for symbol, until in cooldowns.items()
            }

    def _persist_runtime_state(self) -> None:
        self.state.positions[RUNTIME_STATE_KEY] = {
            "version": _RUNTIME_STATE_VERSION,
            "ratchet_base": float(self._ratchet_base),
            "ratchet_floor": float(self._ratchet_floor),
            "cooldown_until_ms": dict(self._cooldown_until_ms),
        }

    # -- 每根 K 线维护棘轮与冷却 ---------------------------------------------

    async def on_bar(self, bar: BarData) -> None:
        now_ms = _safe_int(getattr(bar, "timestamp", 0))
        if now_ms:
            self._update_cooldowns_from_trades(now_ms)
        self._update_ratchet()
        await super().on_bar(bar)

    def _update_ratchet(self) -> None:
        if self.ratchet_step_pct <= 0:
            return
        equity = self._account_equity()
        if equity <= 0:
            return
        if self._ratchet_base <= 0:
            self._ratchet_base = equity
            self._persist_runtime_state()
            return
        threshold = self._ratchet_base * (1.0 + self.ratchet_step_pct / 100.0)
        if equity >= threshold:
            gain = equity - self._ratchet_base
            new_floor = self._ratchet_base + gain * self.ratchet_lock_fraction
            self._ratchet_floor = max(self._ratchet_floor, new_floor)
            self._ratchet_base = equity
            self._persist_runtime_state()

    def _ratchet_allows_entry(self) -> bool:
        if self._ratchet_floor <= 0:
            return True
        equity = self._account_equity()
        return equity <= 0 or equity >= self._ratchet_floor

    def _update_cooldowns_from_trades(self, now_ms: int) -> None:
        if self.loss_cooldown_bars <= 0:
            return
        trades = getattr(self.broker, "trades", None)
        if not isinstance(trades, list) or len(trades) <= self._seen_trade_count:
            return
        new_trades = trades[self._seen_trade_count:]
        self._seen_trade_count = len(trades)
        changed = False
        for trade in new_trades:
            data = trade if isinstance(trade, Mapping) else getattr(trade, "__dict__", {})
            action = str(data.get("action") or data.get("side_effect") or "").lower()
            pnl = data.get("realized_pnl", data.get("pnl"))
            if pnl is None or ("close" not in action and "reduce" not in action):
                continue
            symbol = normalize_contract_symbol(str(data.get("symbol") or ""))
            if not symbol or _safe_float(pnl) >= 0:
                continue
            self._cooldown_until_ms[symbol] = int(now_ms + self.loss_cooldown_bars * self._bar_interval_ms)
            changed = True
        if changed:
            self._persist_runtime_state()

    # -- 入场门控 ------------------------------------------------------------

    def _efficiency_ratio(self, bars: List[BarData]) -> Optional[float]:
        if len(bars) < self.er_window + 1:
            return None
        values = [float(item.close) for item in bars[-(self.er_window + 1):]]
        path_length = sum(abs(current - previous) for previous, current in zip(values, values[1:]))
        if path_length <= 0:
            return 0.0
        return abs(values[-1] - values[0]) / path_length

    def _entry_signal(self, symbol: str, bars: List[BarData], raw_signal: int) -> int:
        signal = super()._entry_signal(symbol, bars, raw_signal)
        if signal == 0:
            return 0
        if self.er_min > 0:
            er = self._efficiency_ratio(bars)
            if er is None or er < self.er_min:
                return 0
        normalized = normalize_contract_symbol(symbol)
        now_ms = _safe_int(getattr(bars[-1], "timestamp", 0)) if bars else 0
        cooldown_until = self._cooldown_until_ms.get(normalized)
        if cooldown_until is not None and now_ms and now_ms < cooldown_until:
            return 0
        if not self._ratchet_allows_entry():
            return 0
        return signal

    # -- 仓位（ETF 名义折减） -------------------------------------------------

    def _risk_sized_notional(self, symbol: str, side: str, price: float, volatility: float) -> float:
        notional = super()._risk_sized_notional(symbol, side, price, volatility)
        if notional <= 0:
            return notional
        if normalize_contract_symbol(symbol) in self.etf_symbols:
            notional *= self.etf_size_mult
        return notional

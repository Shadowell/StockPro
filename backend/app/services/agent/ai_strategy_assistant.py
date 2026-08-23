"""Local AI strategy-assistant workflow blueprint.

This module is intentionally deterministic and LLM-free.  It gives Hermes/BitPro a
safe local strategy-research loop that can run without OKX private connectivity or
server-side LLM API keys.  The output is a paper-only research artifact: market
scan -> strategy design -> risk gate -> paper execution plan -> review plan.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import uuid

import numpy as np

from app.core.config import settings
from app.services.funding_service import funding_service
from app.services.indicators import ATR, EMA
from app.services.market_service import market_service
from app.services.strategy_registry import get_base_strategy_registry


DEFAULT_AUTO_RESEARCH_SYMBOLS = [
    "ETH/USDT:USDT",
    "BTC/USDT:USDT",
    "BSB/USDT:USDT",
    "HYPE/USDT:USDT",
    "SOL/USDT:USDT",
    "ZEC/USDT:USDT",
    "BEAT/USDT:USDT",
    "DOGE/USDT:USDT",
    "NEAR/USDT:USDT",
    "BILL/USDT:USDT",
    "EDEN/USDT:USDT",
    "XRP/USDT:USDT",
    "WLD/USDT:USDT",
    "XAU/USDT:USDT",
    "CL/USDT:USDT",
    "SUI/USDT:USDT",
    "PEPE/USDT:USDT",
    "LAB/USDT:USDT",
    "ONDO/USDT:USDT",
    "UB/USDT:USDT",
    "XAG/USDT:USDT",
    "LIT/USDT:USDT",
    "FIL/USDT:USDT",
    "BNB/USDT:USDT",
    "TON/USDT:USDT",
    "ADA/USDT:USDT",
    "LINK/USDT:USDT",
    "GRASS/USDT:USDT",
    "SNDK/USDT:USDT",
    "TRUMP/USDT:USDT",
]


@dataclass(frozen=True)
class AutoAgentBacktestScenario:
    """One paper-first validation scenario for an auto-agent candidate."""

    label: str
    strategy_key: str
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    config: Dict[str, Any]


@dataclass(frozen=True)
class AutoAgentBacktestOutcome:
    """Normalized backtest result used by the closed-loop report."""

    scenario: AutoAgentBacktestScenario
    status: str
    metrics: Dict[str, Any]
    error: str = ""


@dataclass(frozen=True)
class AutoAgentClosedLoopConfig:
    """Conservative v1 defaults: research -> backtest matrix -> candidate report only."""

    enabled: bool = True
    strategy_keys: Sequence[str] = ("contract_ema_atr_trend", "dynamic_cta_trend_following_top15", "superpnl_contract_mainstream")
    timeframes: Sequence[str] = ("15m", "30m")
    windows: Sequence[Dict[str, str]] = (
        {"label": "recent_14d", "start_date": "2026-04-29", "end_date": "2026-05-13"},
        {"label": "recent_30d", "start_date": "2026-04-13", "end_date": "2026-05-13"},
    )
    initial_capital: float = 10_000.0
    commission: float = 0.0004
    slippage: float = 0.0001
    min_total_return_pct: float = 0.0
    min_profit_factor: float = 1.05
    max_drawdown_pct: float = 8.0
    min_completed_backtests: int = 2
    max_scenarios: int = 8


@dataclass(frozen=True)
class MarketSnapshot:
    """Minimal public-market snapshot used by the local assistant cycle."""

    symbol: str
    quote_volume_24h: float = 0.0
    spread_bps: float = 999.0
    depth_usdt: float = 0.0
    change_1h_pct: float = 0.0
    change_4h_pct: float = 0.0
    atr_pct: float = 0.0
    adx: float = 0.0
    ema_gap_bps: float = 0.0
    funding_rate: float = 0.0

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "MarketSnapshot":
        return cls(
            symbol=str(raw.get("symbol") or "").strip(),
            quote_volume_24h=float(raw.get("quote_volume_24h") or 0),
            spread_bps=float(raw.get("spread_bps") if raw.get("spread_bps") is not None else 999),
            depth_usdt=float(raw.get("depth_usdt") or 0),
            change_1h_pct=float(raw.get("change_1h_pct") or 0),
            change_4h_pct=float(raw.get("change_4h_pct") or 0),
            atr_pct=float(raw.get("atr_pct") or 0),
            adx=float(raw.get("adx") or 0),
            ema_gap_bps=float(raw.get("ema_gap_bps") or 0),
            funding_rate=float(raw.get("funding_rate") or 0),
        )


def assistant_blueprint() -> Dict[str, Any]:
    """Return the five-agent product blueprint shown by the UI/API."""

    return {
        "mode": "paper_research_first",
        "live_boundary": "任何输出都只是 paper/simulation 研究计划；实盘必须另走 /live-real 预检、确认和订阅执行。",
        "agents": [
            {
                "key": "market_agent",
                "name": "Market Agent",
                "role": "扫描 OKX 公开市场流动性、趋势强度、波动率和震荡风险，形成候选池。",
                "outputs": ["liquidity_score", "trend_score", "anti_chop_score", "opportunity_score"],
            },
            {
                "key": "strategy_agent",
                "name": "Strategy Agent",
                "role": "把候选机会转成可复查的策略模板，而不是直接自由下单。",
                "outputs": ["strategy_template", "entry_logic", "exit_logic", "anti_chop_rules"],
            },
            {
                "key": "risk_agent",
                "name": "Risk Agent",
                "role": "用硬风控否决低流动性、过度交易、震荡和超仓位机会。",
                "outputs": ["approved", "risk_limits", "reject_reasons"],
            },
            {
                "key": "execution_agent",
                "name": "Execution Agent",
                "role": "只生成 BitPro paper/simulation trade_intent，不直接触碰 OKX 实盘。",
                "outputs": ["paper_trade_intent", "ttl_seconds", "audit_fields"],
            },
            {
                "key": "review_agent",
                "name": "Review Agent",
                "role": "定义回测、模拟观察、晋级和人工审批标准，形成闭环复盘。",
                "outputs": ["review_window", "success_metrics", "promotion_gate"],
            },
        ],
    }


class HermesAgentBridge:
    """Optional adapter for calling a locally installed Hermes CLI on the server.

    The bridge is disabled by default.  Production can enable it tomorrow by setting
    HERMES_AGENT_ENABLED=true and configuring HERMES_AGENT_COMMAND.  The command may
    contain either {prompt_file} or {prompt}; if neither is present, the prompt is
    sent on stdin.
    """

    def __init__(self, command: str | None = None, timeout: int | None = None, enabled: bool | None = None):
        self.command = command or settings.HERMES_AGENT_COMMAND
        self.timeout = int(timeout or settings.HERMES_AGENT_TIMEOUT)
        self.enabled = settings.HERMES_AGENT_ENABLED if enabled is None else bool(enabled)

    def run(self, prompt: str, session_id: str | None = None) -> Dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "called": False, "status": "disabled", "message": "HERMES_AGENT_ENABLED 未开启"}
        if not self.command.strip():
            return {"enabled": True, "called": False, "status": "not_configured", "message": "HERMES_AGENT_COMMAND 为空"}

        try:
            command = self._materialize_command(prompt, session_id=session_id)
            if "{prompt_file}" in self.command:
                completed = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
            elif "{prompt}" in self.command:
                completed = subprocess.run(command, text=True, capture_output=True, timeout=self.timeout)
            else:
                completed = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=self.timeout)
            result = {
                "enabled": True,
                "called": True,
                "status": "ok" if completed.returncode == 0 else "failed",
                "returncode": completed.returncode,
                "stdout": completed.stdout[-12000:],
                "stderr": completed.stderr[-4000:],
            }
            parsed_session_id = self._extract_session_id(completed.stdout, completed.stderr)
            if parsed_session_id:
                result["session_id"] = parsed_session_id
            return result
        except subprocess.TimeoutExpired:
            return {"enabled": True, "called": True, "status": "timeout", "timeout_sec": self.timeout}
        except FileNotFoundError as exc:
            return {"enabled": True, "called": False, "status": "missing_command", "message": str(exc)}
        except Exception as exc:  # pragma: no cover - defensive boundary for operator tooling
            return {"enabled": True, "called": False, "status": "error", "message": str(exc)}

    def _materialize_command(self, prompt: str, session_id: str | None = None) -> List[str]:
        session_id = self._clean_session_id(session_id)
        command_text = self.command
        if "{resume_session_arg}" in command_text:
            resume_arg = f"--resume {shlex.quote(session_id)}" if session_id else ""
            command_text = command_text.replace("{resume_session_arg}", resume_arg)
        if "{session_id}" in command_text:
            command_text = command_text.replace("{session_id}", shlex.quote(session_id or ""))
        if "{prompt_file}" in self.command:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as fp:
                fp.write(prompt)
                prompt_file = fp.name
            command_text = command_text.replace("{prompt_file}", shlex.quote(prompt_file))
        if "{prompt}" in self.command:
            command_text = command_text.replace("{prompt}", shlex.quote(prompt))
        command = shlex.split(command_text)
        if session_id and "{session_id}" not in self.command and "{resume_session_arg}" not in self.command:
            command = self._inject_resume_session_arg(command, session_id)
        return command

    @staticmethod
    def _clean_session_id(session_id: str | None) -> str:
        return str(session_id or "").strip()

    @staticmethod
    def _extract_session_id(stdout: str, stderr: str) -> str:
        text = f"{stderr or ''}\n{stdout or ''}"
        match = re.search(r"(?im)^\s*session_id:\s*([A-Za-z0-9_.:-]+)\s*$", text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _inject_resume_session_arg(command: List[str], session_id: str) -> List[str]:
        if not command or any(
            token in {"--resume", "-r", "--continue", "-c"} or token.startswith("--resume=")
            for token in command
        ):
            return command

        hermes_index = -1
        for idx, token in enumerate(command):
            if Path(token).name == "hermes":
                hermes_index = idx
                break
        if hermes_index < 0:
            return command

        insert_at = hermes_index + 1
        if len(command) > insert_at and command[insert_at] == "chat":
            insert_at += 1
        return [*command[:insert_at], "--resume", session_id, *command[insert_at:]]


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _last_finite(values: Sequence[float], default: float = 0.0) -> float:
    for value in reversed(values):
        number = _finite_float(value, float("nan"))
        if math.isfinite(number):
            return number
    return default


def _estimate_adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> float:
    length = len(close)
    if length < period * 2 + 1:
        return 0.0
    tr = np.zeros(length, dtype=float)
    plus_dm = np.zeros(length, dtype=float)
    minus_dm = np.zeros(length, dtype=float)
    for i in range(1, length):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]
        plus_dm[i] = up_move if up_move > down_move and up_move > 0 else 0.0
        minus_dm[i] = down_move if down_move > up_move and down_move > 0 else 0.0
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = np.full(length, np.nan, dtype=float)
    plus_smoothed = np.full(length, np.nan, dtype=float)
    minus_smoothed = np.full(length, np.nan, dtype=float)
    atr[period] = np.sum(tr[1:period + 1])
    plus_smoothed[period] = np.sum(plus_dm[1:period + 1])
    minus_smoothed[period] = np.sum(minus_dm[1:period + 1])
    for i in range(period + 1, length):
        atr[i] = atr[i - 1] - (atr[i - 1] / period) + tr[i]
        plus_smoothed[i] = plus_smoothed[i - 1] - (plus_smoothed[i - 1] / period) + plus_dm[i]
        minus_smoothed[i] = minus_smoothed[i - 1] - (minus_smoothed[i - 1] / period) + minus_dm[i]

    plus_di = np.where(atr > 0, 100.0 * plus_smoothed / atr, np.nan)
    minus_di = np.where(atr > 0, 100.0 * minus_smoothed / atr, np.nan)
    dx = np.where((plus_di + minus_di) > 0, 100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di), np.nan)
    valid_dx = dx[np.isfinite(dx)]
    if len(valid_dx) < period:
        return 0.0
    return round(float(np.mean(valid_dx[-period:])), 2)


async def collect_public_market_snapshots(
    symbols: Sequence[str] | None = None,
    *,
    exchange: str = "okx",
    timeframe: str = "1m",
    kline_limit: int = 80,
) -> List[MarketSnapshot]:
    """Collect real public-market snapshots for the auto-research cycle."""

    snapshots: List[MarketSnapshot] = []
    for symbol in list(symbols or DEFAULT_AUTO_RESEARCH_SYMBOLS):
        try:
            ticker = await market_service.get_ticker(exchange, symbol)
            orderbook = await market_service.get_orderbook(exchange, symbol, 20)
            klines = await market_service.get_klines(exchange, symbol, timeframe, kline_limit)
            if len(klines) < 20:
                continue
            closes = np.array([_finite_float(k.get("close")) for k in klines], dtype=float)
            highs = np.array([_finite_float(k.get("high")) for k in klines], dtype=float)
            lows = np.array([_finite_float(k.get("low")) for k in klines], dtype=float)
            if closes[-1] <= 0:
                continue

            best_bid = _finite_float(ticker.get("bid"))
            best_ask = _finite_float(ticker.get("ask"))
            if (not best_bid or not best_ask) and orderbook.get("bids") and orderbook.get("asks"):
                best_bid = _finite_float(orderbook["bids"][0][0])
                best_ask = _finite_float(orderbook["asks"][0][0])
            mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else closes[-1]
            spread_bps = ((best_ask - best_bid) / mid * 10_000) if mid > 0 and best_ask >= best_bid > 0 else 999.0
            depth_usdt = 0.0
            for side in (orderbook.get("bids") or [])[:10]:
                depth_usdt += _finite_float(side[0]) * _finite_float(side[1])
            for side in (orderbook.get("asks") or [])[:10]:
                depth_usdt += _finite_float(side[0]) * _finite_float(side[1])

            atr_values = ATR(highs, lows, closes, 14)
            atr_pct = _last_finite(atr_values, 0.0) / closes[-1] * 100.0 if closes[-1] > 0 else 0.0
            ema_fast = EMA(closes, 12)
            ema_slow = EMA(closes, 26)
            ema_gap_bps = abs(_last_finite(ema_fast) - _last_finite(ema_slow)) / closes[-1] * 10_000.0
            funding_rate = 0.0
            try:
                funding = await funding_service.get_funding_rate(exchange, symbol)
                funding_rate = _finite_float((funding or {}).get("current_rate"), 0.0)
            except Exception:
                funding_rate = 0.0

            one_hour_index = -min(61, len(closes))
            one_hour_base = closes[one_hour_index]
            snapshots.append(MarketSnapshot(
                symbol=symbol,
                quote_volume_24h=_finite_float(ticker.get("quote_volume")),
                spread_bps=round(spread_bps, 4),
                depth_usdt=round(depth_usdt, 2),
                change_1h_pct=round((closes[-1] - one_hour_base) / one_hour_base * 100.0, 4) if one_hour_base > 0 else 0.0,
                change_4h_pct=_finite_float(ticker.get("change_percent")),
                atr_pct=round(atr_pct, 4),
                adx=_estimate_adx(highs, lows, closes, 14),
                ema_gap_bps=round(ema_gap_bps, 4),
                funding_rate=funding_rate,
            ))
        except Exception:
            continue
    return snapshots


def build_hermes_research_prompt(cycle_result: Dict[str, Any]) -> str:
    """Build a self-contained prompt for server-local Hermes strategy research."""

    payload = json.dumps(cycle_result, ensure_ascii=False, indent=2)
    return f"""你是 BitPro 服务器本地 Hermes 策略研发 Agent。请基于下面五 Agent 本地闭环结果继续研发，但必须遵守边界：

1. 只允许输出 research / backtest / paper-simulation 计划或代码建议。
2. 不允许直接实盘下单，不允许绕过 /live-real 预检、账户绑定和人工确认。
3. 没有真实行情/K线证据时必须明确说“不交易/等待数据”，不得编造市场机会。
4. 如要写策略，必须符合 BitPro BaseStrategy 合约，并先经过回测和模拟盘。
5. 若 preferred_direction 为 long/short，则只研究对应方向；若为 auto，则允许多空双向机会。
6. 输出结构：市场判断、策略假设、风控规则、paper 执行意图、回测/模拟验收标准、下一步命令建议。

五 Agent 本地闭环结果：
```json
{payload}
```
"""


class AiStrategyAssistantCycle:
    """Deterministic five-agent local strategy research cycle."""

    MIN_SCORE_TO_PAPER_TRADE = 78.0

    def __init__(
        self,
        *,
        backtest_runner: Optional[Callable[[AutoAgentBacktestScenario, AutoAgentClosedLoopConfig], Dict[str, Any]]] = None,
        closed_loop_config: Optional[AutoAgentClosedLoopConfig] = None,
    ) -> None:
        self.backtest_runner = backtest_runner
        self.closed_loop_config = closed_loop_config or AutoAgentClosedLoopConfig()

    def run(
        self,
        objective: str,
        snapshots: Iterable[MarketSnapshot | Dict[str, Any]],
        *,
        max_candidates: int = 5,
        use_hermes_agent: bool = False,
        hermes_bridge: Optional[HermesAgentBridge] = None,
        run_closed_loop: bool = True,
        preferred_direction: str = "auto",
    ) -> Dict[str, Any]:
        normalized = [s if isinstance(s, MarketSnapshot) else MarketSnapshot.from_dict(s) for s in snapshots]
        normalized = [s for s in normalized if s.symbol]
        agents = assistant_blueprint()["agents"]
        direction = self._normalize_preferred_direction(preferred_direction)
        market_scan = self._market_agent(normalized, max_candidates=max_candidates, preferred_direction=direction)
        selected = market_scan["candidates"][0] if market_scan["candidates"] else None
        strategy_brief = self._strategy_agent(selected, objective)
        risk_review = self._risk_agent(selected, strategy_brief)
        trade_intent = self._execution_agent(selected, strategy_brief, risk_review)
        execution_plan = self._execution_plan(trade_intent)
        review_plan = self._review_agent(selected, strategy_brief, risk_review)
        result = {
            "run_id": f"local-cycle-{uuid.uuid4().hex[:10]}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "paper_research",
            "objective": objective,
            "preferred_direction": direction,
            "agents": agents,
            "market_scan": market_scan,
            "selected_opportunity": selected,
            "strategy_brief": strategy_brief,
            "risk_review": risk_review,
            "trade_intent": trade_intent,
            "execution_plan": execution_plan,
            "review_plan": review_plan,
        }
        if use_hermes_agent:
            bridge = hermes_bridge or HermesAgentBridge()
            result["hermes_agent"] = bridge.run(build_hermes_research_prompt(result))
        else:
            result["hermes_agent"] = {"enabled": False, "called": False, "status": "not_requested"}
        result["closed_loop"] = self._closed_loop_agent(result) if run_closed_loop else {
            "status": "skipped",
            "reason": "closed-loop backtest matrix not requested",
            "live_trading_allowed": False,
            "candidate_strategy": None,
        }
        return result

    @staticmethod
    def _normalize_preferred_direction(value: str | None) -> str:
        normalized = str(value or "auto").strip().lower().replace("-", "_")
        if normalized in {"long", "short"}:
            return normalized
        return "auto"

    def _market_agent(self, snapshots: List[MarketSnapshot], *, max_candidates: int, preferred_direction: str = "auto") -> Dict[str, Any]:
        scored = [self._score_snapshot(s) for s in snapshots]
        candidates: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for row in scored:
            direction_mismatch = preferred_direction != "auto" and row["direction"] != preferred_direction
            if direction_mismatch:
                next_row = dict(row)
                next_row["reject_reasons"] = list(next_row.get("reject_reasons") or []) + [f"方向不符合{preferred_direction}偏好"]
                rejected.append(next_row)
                continue
            if row["opportunity_score"] >= self.MIN_SCORE_TO_PAPER_TRADE:
                candidates.append(row)
            else:
                rejected.append(row)
        candidates.sort(key=lambda row: row["opportunity_score"], reverse=True)
        rejected.sort(key=lambda row: row["opportunity_score"], reverse=True)
        return {
            "agent": "market_agent",
            "summary": "基于本地传入/缓存的公开行情快照评分；无快照时不编造机会。",
            "preferred_direction": preferred_direction,
            "candidates": candidates[:max_candidates],
            "rejected": rejected,
            "threshold": self.MIN_SCORE_TO_PAPER_TRADE,
        }

    def _score_snapshot(self, s: MarketSnapshot) -> Dict[str, Any]:
        liquidity_score = min(25.0, s.quote_volume_24h / 20_000_000 * 10 + s.depth_usdt / 500_000 * 8 + max(0.0, 7 - s.spread_bps))
        trend_direction = "long" if s.change_1h_pct + s.change_4h_pct >= 0 else "short"
        trend_score = min(30.0, abs(s.change_1h_pct) * 4 + abs(s.change_4h_pct) * 5 + max(0.0, s.adx - 15) + s.ema_gap_bps / 2)
        volatility_score = min(15.0, max(0.0, 15 - abs(s.atr_pct - 1.5) * 5))
        anti_chop_score = min(20.0, max(0.0, (s.adx - 12) * 1.2) + min(8.0, s.ema_gap_bps / 2))
        funding_penalty = min(8.0, abs(s.funding_rate) * 10_000)
        opportunity_score = round(max(0.0, liquidity_score + trend_score + volatility_score + anti_chop_score - funding_penalty), 2)
        reject_reasons: List[str] = []
        if liquidity_score < 12:
            reject_reasons.append("流动性/深度不足或价差偏大")
        if anti_chop_score < 10:
            reject_reasons.append("ADX/EMA 间距显示震荡风险偏高")
        if trend_score < 18:
            reject_reasons.append("趋势强度不足")
        return {
            "symbol": s.symbol,
            "direction": trend_direction,
            "liquidity_score": round(liquidity_score, 2),
            "trend_score": round(trend_score, 2),
            "volatility_score": round(volatility_score, 2),
            "anti_chop_score": round(anti_chop_score, 2),
            "funding_penalty": round(funding_penalty, 2),
            "opportunity_score": opportunity_score,
            "reject_reasons": reject_reasons,
            "inputs": s.__dict__,
        }

    def _strategy_agent(self, opportunity: Optional[Dict[str, Any]], objective: str) -> Dict[str, Any]:
        if not opportunity:
            return {
                "agent": "strategy_agent",
                "status": "no_strategy",
                "template": None,
                "reason": "没有通过 Market Agent 阈值的真实市场快照。",
            }
        direction_text = "做多" if opportunity["direction"] == "long" else "做空"
        return {
            "agent": "strategy_agent",
            "status": "drafted",
            "template": "ADX + EMA-gap anti-chop trend following",
            "strategy_name": f"[合约] AI策略助手 · {opportunity['symbol']} 趋势过滤模拟版",
            "entry_logic": f"仅当流动性、ADX、EMA 间距和多周期动量同时达标时{direction_text}。",
            "exit_logic": "ATR 初始止损 + 盈利保护 + 反向信号需二次确认，避免一根 K 内来回开平。",
            "anti_chop_rules": {
                "min_adx": 18,
                "min_ema_gap_bps": 10,
                "cooldown_bars_after_loss": 3,
                "max_trades_per_symbol_per_hour": 2,
                "reentry_price_improve_bps": 12,
            },
            "objective_alignment": objective,
        }

    def _risk_agent(self, opportunity: Optional[Dict[str, Any]], strategy: Dict[str, Any]) -> Dict[str, Any]:
        if not opportunity or strategy.get("status") != "drafted":
            return {"agent": "risk_agent", "approved": False, "reject_reasons": ["缺少可交易候选或策略草案"]}
        reasons = list(opportunity.get("reject_reasons") or [])
        if opportunity["opportunity_score"] < self.MIN_SCORE_TO_PAPER_TRADE:
            reasons.append("机会评分低于自动模拟阈值")
        approved = not reasons
        return {
            "agent": "risk_agent",
            "approved": approved,
            "reject_reasons": reasons,
            "risk_limits": {
                "execution_mode": "paper_only",
                "max_leverage": 3,
                "target_notional_usdt": 30,
                "max_total_notional_usdt": 150,
                "daily_loss_limit_pct": 2,
                "kill_switch_drawdown_pct": 5,
            },
        }

    def _execution_agent(
        self,
        opportunity: Optional[Dict[str, Any]],
        strategy: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not opportunity or not risk.get("approved"):
            return None
        action = "open_long" if opportunity["direction"] == "long" else "open_short"
        return {
            "agent": "execution_agent",
            "execution_mode": "paper_only",
            "symbol": opportunity["symbol"],
            "action": action,
            "confidence": round(min(0.95, opportunity["opportunity_score"] / 100), 2),
            "target_notional_usdt": risk["risk_limits"]["target_notional_usdt"],
            "leverage": risk["risk_limits"]["max_leverage"],
            "ttl_seconds": 60,
            "audit_reason": strategy.get("entry_logic"),
        }

    def _execution_plan(self, trade_intent: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not trade_intent:
            return {
                "agent": "execution_agent",
                "target": "none",
                "live_trading_allowed": False,
                "next_step": "等待真实市场快照或本地 K 线覆盖",
            }
        return {
            "agent": "execution_agent",
            "target": "BitPro paper/simulation only",
            "live_trading_allowed": False,
            "next_step": "写入 paper 策略/模拟任务前仍需回测或人工确认；不得直接调用 OKX 实盘。",
        }

    def _review_agent(
        self,
        opportunity: Optional[Dict[str, Any]],
        strategy: Dict[str, Any],
        risk: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "agent": "review_agent",
            "review_window": "先回测 7/14/30 天，再模拟盘观察至少 24 小时",
            "success_metrics": {
                "min_profit_factor": 1.15,
                "max_drawdown_pct": 3,
                "max_trades_per_symbol_per_hour": 2,
                "must_reduce_churn_vs_baseline": True,
            },
            "promotion_gate": {
                "requires_human_approval": True,
                "requires_live_preflight": True,
                "live_default": "disabled",
            },
            "summary": "Review Agent 只给晋级标准，不会把本地闭环自动升级为实盘。",
        }

    def _closed_loop_agent(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Run the v1 closed loop: research artifact -> backtest matrix -> candidate report.

        The method never starts live trading.  It can return an actionable candidate
        strategy name/logic only after the configured matrix has enough completed
        paper backtests and passes conservative gates.
        """

        cfg = self.closed_loop_config
        selected = result.get("selected_opportunity")
        strategy = result.get("strategy_brief") or {}
        risk = result.get("risk_review") or {}
        if not cfg.enabled:
            return {"status": "disabled", "candidate_strategy": None, "live_trading_allowed": False}
        if not selected or not risk.get("approved"):
            return {
                "status": "waiting_for_research_candidate",
                "reason": "没有通过 Market/Risk Agent 的真实行情候选，因此不生成回测矩阵。",
                "backtest_matrix": [],
                "candidate_strategy": None,
                "live_trading_allowed": False,
            }

        scenarios = self._build_backtest_matrix(selected, strategy, cfg)
        outcomes = [self._run_backtest_scenario(item, cfg) for item in scenarios]
        completed = [item for item in outcomes if item.status == "completed"]
        passed = [item for item in completed if self._metrics_pass_candidate_gate(item.metrics, cfg)]
        status = "candidate_ready" if len(passed) >= cfg.min_completed_backtests else "needs_more_validation"
        candidate = self._candidate_strategy_record(selected, strategy, completed, passed, cfg) if status == "candidate_ready" else None
        return {
            "status": status,
            "stage": "backtest_matrix_completed",
            "live_trading_allowed": False,
            "paper_only": True,
            "backtest_matrix": [self._outcome_to_dict(item) for item in outcomes],
            "summary": {
                "scenario_count": len(outcomes),
                "completed_count": len(completed),
                "passed_count": len(passed),
                "min_completed_backtests": cfg.min_completed_backtests,
            },
            "candidate_strategy": candidate,
            "promotion_gate": {
                "requires_human_approval": True,
                "requires_live_preflight": True,
                "live_default": "disabled",
                "paper_simulation_min_hours": 24,
            },
        }

    def _build_backtest_matrix(
        self,
        selected: Dict[str, Any],
        strategy: Dict[str, Any],
        cfg: AutoAgentClosedLoopConfig,
    ) -> List[AutoAgentBacktestScenario]:
        symbol = str(selected.get("symbol") or "BTC/USDT:USDT")
        normalized_symbol = symbol.replace(":USDT", "")
        available = get_base_strategy_registry()
        scenarios: List[AutoAgentBacktestScenario] = []
        for strategy_key in cfg.strategy_keys:
            if strategy_key not in available:
                continue
            for timeframe in cfg.timeframes:
                for window in cfg.windows:
                    scenario_config = {
                        "strategy_key": strategy_key,
                        "auto_agent_generated": True,
                        "source": "ai_strategy_assistant_closed_loop_v1",
                        "selected_symbol": symbol,
                        "direction": selected.get("direction"),
                        "paper_only": True,
                        "anti_chop_rules": strategy.get("anti_chop_rules") or {},
                    }
                    scenarios.append(AutoAgentBacktestScenario(
                        label=str(window.get("label") or f"{timeframe}_window"),
                        strategy_key=strategy_key,
                        symbol=normalized_symbol,
                        timeframe=str(timeframe),
                        start_date=str(window.get("start_date") or "2026-04-13"),
                        end_date=str(window.get("end_date") or "2026-05-13"),
                        config=scenario_config,
                    ))
                    if len(scenarios) >= cfg.max_scenarios:
                        return scenarios
        return scenarios

    def _run_backtest_scenario(
        self,
        scenario: AutoAgentBacktestScenario,
        cfg: AutoAgentClosedLoopConfig,
    ) -> AutoAgentBacktestOutcome:
        if self.backtest_runner is None:
            return AutoAgentBacktestOutcome(
                scenario=scenario,
                status="not_configured",
                metrics={},
                error="backend backtest runner not injected; matrix is recorded for asynchronous/production execution",
            )
        try:
            metrics = self.backtest_runner(scenario, cfg)
            return AutoAgentBacktestOutcome(scenario=scenario, status="completed", metrics=self._normalize_metrics(metrics))
        except Exception as exc:
            return AutoAgentBacktestOutcome(scenario=scenario, status="failed", metrics={}, error=str(exc))

    def _normalize_metrics(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        keys = (
            "total_return_pct",
            "max_drawdown_pct",
            "sharpe_ratio",
            "win_rate_pct",
            "profit_factor",
            "total_trades",
        )
        normalized = {key: _finite_float(raw.get(key), 0.0) for key in keys}
        normalized["total_trades"] = int(normalized["total_trades"])
        return normalized

    def _metrics_pass_candidate_gate(self, metrics: Dict[str, Any], cfg: AutoAgentClosedLoopConfig) -> bool:
        return (
            _finite_float(metrics.get("total_return_pct")) >= cfg.min_total_return_pct
            and _finite_float(metrics.get("profit_factor")) >= cfg.min_profit_factor
            and _finite_float(metrics.get("max_drawdown_pct"), 999.0) <= cfg.max_drawdown_pct
            and int(_finite_float(metrics.get("total_trades"))) > 0
        )

    def _candidate_strategy_record(
        self,
        selected: Dict[str, Any],
        strategy: Dict[str, Any],
        completed: List[AutoAgentBacktestOutcome],
        passed: List[AutoAgentBacktestOutcome],
        cfg: AutoAgentClosedLoopConfig,
    ) -> Dict[str, Any]:
        best = max(passed, key=lambda item: (_finite_float(item.metrics.get("profit_factor")), _finite_float(item.metrics.get("total_return_pct"))))
        returns = [_finite_float(item.metrics.get("total_return_pct")) for item in completed]
        drawdowns = [_finite_float(item.metrics.get("max_drawdown_pct"), 999.0) for item in completed]
        strategy_name = f"候选实盘策略 · {best.scenario.strategy_key} · {selected.get('symbol')} · paper验证"
        return {
            "name": strategy_name,
            "strategy_key": best.scenario.strategy_key,
            "symbol": best.scenario.symbol,
            "timeframe": best.scenario.timeframe,
            "logic": strategy.get("entry_logic") or "基于五 Agent 评分的趋势/震荡过滤策略",
            "exit_logic": strategy.get("exit_logic") or "ATR 止损 + 盈利保护 + 反向信号确认",
            "config": best.scenario.config,
            "evidence": {
                "best_metrics": best.metrics,
                "completed_backtests": len(completed),
                "passed_backtests": len(passed),
                "avg_return_pct": round(sum(returns) / len(returns), 4) if returns else 0.0,
                "worst_drawdown_pct": round(max(drawdowns), 4) if drawdowns else 0.0,
                "gates": {
                    "min_total_return_pct": cfg.min_total_return_pct,
                    "min_profit_factor": cfg.min_profit_factor,
                    "max_drawdown_pct": cfg.max_drawdown_pct,
                },
            },
            "recommended_next_step": "只进入 paper/simulation 观察；如要实盘，必须人工审批并走 /live-real 预检。",
            "live_trading_allowed": False,
        }

    def _outcome_to_dict(self, outcome: AutoAgentBacktestOutcome) -> Dict[str, Any]:
        return {
            "scenario": asdict(outcome.scenario),
            "status": outcome.status,
            "metrics": outcome.metrics,
            "error": outcome.error,
        }

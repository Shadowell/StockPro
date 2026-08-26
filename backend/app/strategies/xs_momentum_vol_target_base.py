"""[合约][1H][CTA] Top40 · 截面动量波动率目标组合 · 100U

【镜像文件】本文件是 strategies/cross_sectional_momentum_vol_target.py 的
包内镜像副本，供 contract_xs_momentum_ml_gate_strategy 等注册策略继承使用。
两份文件必须保持同步修改；修改任一侧时必须在另一侧应用相同变更，
并在 docs/project/progress.md 记录。生产 446 实例仍通过 db script_content
运行 strategies/ 下的原文件，本副本不影响其行为。


设计动机（2026-08-23 生产模拟盘全量复盘，185 策略 / 74,243 笔成交）：
- 撒网式单标的 EMA5/20 激进版同批 101 个只有 19% 盈利：赢家是事后才知道的
  趋势币。改为横截面动量排序，把"挑中强势币"从运气问题变成规则问题。
- >5 次 round-trip/天 的策略群 82% 亏损、手续费普遍吃掉毛利 30%~150%。
  用 4 小时一次重平衡 + 截面排名失效退出控制换手与成本。
- 固定名义仓位在波动放大时回撤失控（441 基准版 2026-08-22 单段回撤 18.2%，
  同期 BTC 仅 -1.24%）。用已实现波动反推目标名义：波动越大仓位越小。

信号层：风险调整动量分数（3 天 / 7 天 Sharpe 式收益/波动 加权），
        EMA200 趋势方向过滤 + ADX14 强度过滤；每 rebalance_bars 根重排一次。
仓位层：组合年化波动目标 target_portfolio_vol，按 sqrt(max_total_positions)
        分摊到单标的；名义 clamp 到权益百分比上限；组合总名义 <= 权益 x
        max_gross_leverage。
退出层：每根已确认 K 线用 high/low 检查，同一根同时触发时保守先止损：
        ATR 初始止损 -> 保本 -> chandelier ATR 跟踪 + 峰值利润回撤锁利 ->
        保证金 ROI 硬止损/硬止盈兜底 -> 截面排名失效 -> 时间止损。
组合风控：当日权益回撤暂停新开仓；单标的连亏冷却。

所有保护参数均为显式正数配置并被真实 close_contract 平仓路径消费；
全部执行为策略内部 paper 行为，不代表交易所原生条件单。
"""

import math
from collections import deque

from app.core.execution.base_strategy import BarData, BaseStrategy

HOUR_MS = 3_600_000
_EPS = 1e-12


def _ema(values, window):
    """标准 EMA；数据不足返回 None。"""
    if not values or len(values) < window:
        return None
    k = 2.0 / (window + 1.0)
    ema = sum(values[:window]) / float(window)
    for v in values[window:]:
        ema = v * k + ema * (1.0 - k)
    return ema


def _wilder_adx(highs, lows, closes, window):
    """Wilder ADX；数据不足或无波动时返回 None。"""
    n = len(closes)
    need = 2 * window + 1
    if n < need:
        return None
    trs, p_dm, m_dm = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        p_dm.append(up if up > dn and up > 0 else 0.0)
        m_dm.append(dn if dn > up and dn > 0 else 0.0)
        trs.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )
    atr = sum(trs[:window])
    pdm = sum(p_dm[:window])
    mdm = sum(m_dm[:window])
    if atr <= _EPS:
        return None
    dxs = []
    for i in range(window, len(trs)):
        atr = atr - atr / window + trs[i]
        pdm = pdm - pdm / window + p_dm[i]
        mdm = mdm - mdm / window + m_dm[i]
        if atr <= _EPS:
            continue
        pdi = 100.0 * pdm / atr
        mdi = 100.0 * mdm / atr
        denom = pdi + mdi
        dx = 100.0 * abs(pdi - mdi) / denom if denom > _EPS else 0.0
        dxs.append(dx)
        if len(dxs) >= window:
            break
    if len(dxs) < window:
        return None
    adx = sum(dxs[:window]) / float(window)
    for dx in dxs[window:]:
        adx = (adx * (window - 1) + dx) / float(window)
    return adx


class CrossSectionalMomentumVolTargetStrategy(BaseStrategy):
    """Top40 截面动量 + 波动率目标仓位的 1H 合约组合策略。"""

    async def on_init(self) -> None:
        cfg = self.config
        # ---- 节奏与池 ----
        self.rebalance_bars = max(1, int(cfg.get("rebalance_bars", 4)))
        self.min_symbol_turnover_usdt = float(cfg.get("min_symbol_turnover_usdt", 50000.0))
        self.liquidity_window_bars = int(cfg.get("liquidity_window_bars", 24))
        self.min_cross_section_symbols = int(cfg.get("min_cross_section_symbols", 5))

        # ---- 动量 ----
        self.mom_fast_window_bars = int(cfg.get("mom_fast_window_bars", 72))
        self.mom_slow_window_bars = int(cfg.get("mom_slow_window_bars", 168))
        self.mom_fast_weight = float(cfg.get("mom_fast_weight", 0.6))
        self.vol_window_bars = int(cfg.get("vol_window_bars", 480))

        # ---- 趋势过滤 ----
        self.trend_ema_window = int(cfg.get("trend_ema_window", 200))
        self.adx_window = int(cfg.get("adx_window", 14))
        self.entry_min_adx = float(cfg.get("entry_min_adx", 15.0))

        # ---- 排名与名额 ----
        self.rank_pct_long = float(cfg.get("rank_pct_long", 0.25))
        self.rank_pct_short = float(cfg.get("rank_pct_short", 0.25))
        self.exit_rank_long = float(cfg.get("exit_rank_long", 0.5))
        self.exit_rank_short = float(cfg.get("exit_rank_short", 0.5))
        self.max_long_positions = int(cfg.get("max_long_positions", 3))
        self.max_short_positions = int(cfg.get("max_short_positions", 3))
        self.max_total_positions = max(1, int(cfg.get("max_total_positions", 6)))

        # ---- 波动率目标仓位 ----
        self.target_portfolio_vol = float(cfg.get("target_portfolio_vol", 0.30))
        self.max_position_equity_pct = float(cfg.get("max_position_equity_pct", 0.35))
        self.max_gross_leverage = float(cfg.get("max_gross_leverage", 1.5))
        self.min_notional_usdt = float(cfg.get("min_notional_usdt", 20.0))
        self.leverage = max(1.0, float(cfg.get("leverage", 5.0)))

        # ---- 退出保护（强制规则：全部被 close_contract 消费）----
        self.atr_window = int(cfg.get("atr_window", 14))
        self.atr_stop_mult = float(cfg.get("atr_stop_mult", 2.0))
        self.hard_stop_loss_pct = float(cfg.get("hard_stop_loss_pct", 0.12))
        self.hard_take_profit_pct = float(cfg.get("hard_take_profit_pct", 0.45))
        self.break_even_at_r = float(cfg.get("break_even_at_r", 1.0))
        self.break_even_buffer_bps = float(cfg.get("break_even_buffer_bps", 10))
        self.profit_trailing_start_r = float(cfg.get("profit_trailing_start_r", 1.5))
        self.trail_atr_mult = float(cfg.get("trail_atr_mult", 2.5))
        self.peak_pullback_pct = float(cfg.get("peak_pullback_pct", 0.35))
        self.max_holding_bars = int(cfg.get("max_holding_bars", 96))

        # ---- 组合风控 ----
        self.daily_pause_drawdown_pct = float(cfg.get("daily_pause_drawdown_pct", 0.04))
        self.loss_cooldown_count = int(cfg.get("loss_cooldown_count", 3))
        self.loss_cooldown_hours = float(cfg.get("loss_cooldown_hours", 12))

        need = max(
            self.vol_window_bars,
            self.mom_slow_window_bars,
            self.trend_ema_window,
            2 * (self.adx_window + 2),
        )
        # warmup_bars 是截面计算的最小样本门槛；
        # deque 再多留 rebalance 余量，避免 aligned_ts 截去最新一根后永远差一根。
        self.warmup_bars = need + 10
        self._deque_maxlen = self.warmup_bars + self.rebalance_bars + 5

        self.market = {}
        self.next_rebalance_ts = None
        self.day_key = None
        self.day_start_equity = 0.0
        self.entry_state = {}
        self.cooldown_until = {}
        self.loss_streak = {}

    # ------------------------------------------------------------------
    # per-symbol 数据维护
    # ------------------------------------------------------------------

    def _sym_state(self, symbol):
        st = self.market.get(symbol)
        if st is None:
            st = {
                "ts": deque(maxlen=self._deque_maxlen),
                "high": deque(maxlen=self._deque_maxlen),
                "low": deque(maxlen=self._deque_maxlen),
                "close": deque(maxlen=self._deque_maxlen),
                "vol": deque(maxlen=self._deque_maxlen),
            }
            self.market[symbol] = st
        return st

    def _snapshot_upto(self, symbol, ts_ms):
        """取该标的 timestamp <= ts_ms 的已确认序列（防截面前视）。"""
        st = self._sym_state(symbol)
        rows = list(zip(st["ts"], st["high"], st["low"], st["close"], st["vol"]))
        return [r for r in rows if r[0] is not None and r[0] <= ts_ms]

    # ------------------------------------------------------------------
    # 指标
    # ------------------------------------------------------------------

    @staticmethod
    def _ann_vol(closes, window):
        seg = closes[-window:]
        if len(seg) < window // 2:
            return None
        rets = []
        for i in range(1, len(seg)):
            prev = seg[i - 1]
            if prev <= _EPS:
                continue
            rets.append(math.log(seg[i] / prev))
        if len(rets) < window // 2:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        return math.sqrt(var) * math.sqrt(24 * 365)

    @staticmethod
    def _momentum_score(rows, fast, slow, fast_weight):
        closes = [r[3] for r in rows]
        out = {}
        for label, w in (("fast", fast), ("slow", slow)):
            if len(closes) <= w:
                return None
            base = closes[-(w + 1)]
            ret = closes[-1] / base - 1.0 if base > _EPS else 0.0
            vol = CrossSectionalMomentumVolTargetStrategy._ann_vol(closes, w)
            if vol is None or vol <= _EPS:
                return None
            out[label] = ret / vol
        return fast_weight * out["fast"] + (1.0 - fast_weight) * out["slow"]

    @staticmethod
    def _atr_from_rows(rows, window):
        highs = [r[1] for r in rows]
        lows = [r[2] for r in rows]
        closes = [r[3] for r in rows]
        if len(closes) < window + 1:
            return None
        trs = []
        for i in range(len(closes) - window, len(closes)):
            trs.append(
                max(
                    highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]),
                )
            )
        return sum(trs) / float(len(trs)) if trs else None

    # ------------------------------------------------------------------
    # 权益与持仓
    # ------------------------------------------------------------------

    def _equity(self):
        if hasattr(self.broker, "equity"):
            try:
                value = float(self.broker.equity)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                pass
        value = float(self.state.positions.get("_capital", 0.0) or 0.0)
        return value if value > 0 else 100.0

    async def _open_positions(self):
        rows = []
        seen = set()
        for symbol in list(self.market.keys()):
            for side in ("long", "short"):
                pos = await self.get_contract_position(symbol, side)
                if pos:
                    rows.append((symbol, side, pos))
                    seen.add(symbol)
        return rows

    def _day_roll(self, ts_ms):
        day = int(ts_ms // 86_400_000)
        equity = self._equity()
        if self.day_key != day:
            self.day_key = day
            self.day_start_equity = equity
        if self.day_start_equity <= 0:
            self.day_start_equity = equity
        return equity

    def _daily_paused(self, equity):
        if self.day_start_equity <= 0:
            return False
        dd = (self.day_start_equity - equity) / self.day_start_equity
        return dd >= self.daily_pause_drawdown_pct

    # ------------------------------------------------------------------
    # 退出保护
    # ------------------------------------------------------------------

    def _entry_key(self, symbol, side):
        return f"{symbol}|{side}"

    def _register_entry(self, symbol, side, entry_price, entry_atr, ts_ms, notional):
        stop_dist = max(self.atr_stop_mult * entry_atr, entry_price * 1e-4)
        self.entry_state[self._entry_key(symbol, side)] = {
            "entry_price": float(entry_price),
            "stop_dist": float(stop_dist),
            "peak": float(entry_price),
            "trough": float(entry_price),
            "bars_in_trade": 0,
            "opened_ts": ts_ms,
            "notional_usdt": float(notional),
        }

    def _gross_notional(self):
        return sum(
            float(es.get("notional_usdt", 0.0) or 0.0)
            for es in self.entry_state.values()
        )

    async def _close_side(self, symbol, side, price, reason, ts_ms=None):
        key = self._entry_key(symbol, side)
        es = self.entry_state.get(key)
        result = await self.close_contract(symbol, side, ratio=1.0, price=price)
        status = str(result.get("status", ""))
        # 回测 broker 的 close_contract 不返回 realized_pnl；
        # 统一用开仓价 vs 平仓价方向判定盈亏，runtime 与回测口径一致。
        if es is not None:
            entry_price = float(es.get("entry_price", 0.0) or 0.0)
            won = price > entry_price if side == "long" else price < entry_price
            del self.entry_state[key]
            if status in ("submitted", "closed", "filled"):
                if won:
                    self.loss_streak[symbol] = 0
                else:
                    self.loss_streak[symbol] = self.loss_streak.get(symbol, 0) + 1
                    if (
                        self.loss_streak[symbol] >= self.loss_cooldown_count
                        and ts_ms
                    ):
                        self.cooldown_until[symbol] = int(
                            ts_ms + self.loss_cooldown_hours * HOUR_MS
                        )
        return status in ("submitted", "closed", "filled")

    async def _check_exits_for_bar(self, bar):
        """每根已确认 K 线用 high/low 检查；同一根同触保守先止损。"""
        symbol = bar["symbol"]
        for side in ("long", "short"):
            key = self._entry_key(symbol, side)
            es = self.entry_state.get(key)
            if es is None:
                continue
            pos = await self.get_contract_position(symbol, side)
            if not pos:
                self.entry_state.pop(key, None)
                continue
            entry = es["entry_price"]
            dist = max(es["stop_dist"], entry * 1e-4)
            high, low, close = bar["high"], bar["low"], bar["close"]

            es["bars_in_trade"] += 1
            if side == "long":
                es["peak"] = max(es["peak"], high)
            else:
                es["trough"] = min(es["trough"], low)

            progress = (close - entry) / dist if side == "long" else (entry - close) / dist

            # 1) 保证金 ROI 硬兜底（用 bar 内最差价，保守）
            worst = low if side == "long" else high
            best = high if side == "long" else low
            roi_worst = self.leverage * ((worst / entry) - 1.0 if side == "long" else (1.0 - worst / entry))
            roi_best = self.leverage * ((best / entry) - 1.0 if side == "long" else (1.0 - best / entry))
            if roi_worst <= -self.hard_stop_loss_pct:
                await self._close_side(symbol, side, entry * (1 - self.hard_stop_loss_pct / self.leverage) if side == "long" else entry * (1 + self.hard_stop_loss_pct / self.leverage), "hard_stop", ts_ms=bar["ts"])
                continue
            if roi_best >= self.hard_take_profit_pct:
                exit_price = entry * (1 + self.hard_take_profit_pct / self.leverage) if side == "long" else entry * (1 - self.hard_take_profit_pct / self.leverage)
                await self._close_side(symbol, side, exit_price, "hard_tp", ts_ms=bar["ts"])
                continue

            # 2) 结构性止损价：初始 ATR -> 保本 -> 跟踪
            stop_price = entry - dist if side == "long" else entry + dist
            if progress >= self.break_even_at_r:
                buffer = entry * self.break_even_buffer_bps / 10000.0
                be = entry + buffer if side == "long" else entry - buffer
                stop_price = max(stop_price, be) if side == "long" else min(stop_price, be)
            if progress >= self.profit_trailing_start_r:
                rows = self._snapshot_upto(symbol, bar["ts"] - HOUR_MS)
                atr_now = self._atr_from_rows(rows, self.atr_window) if rows else None
                if atr_now:
                    trail = es["peak"] - self.trail_atr_mult * atr_now if side == "long" else es["trough"] + self.trail_atr_mult * atr_now
                    stop_price = max(stop_price, trail) if side == "long" else min(stop_price, trail)

            hit_stop = low <= stop_price if side == "long" else high >= stop_price

            # 3) 峰值利润回撤锁利（close 判定）
            peak_r = (
                (es["peak"] - entry) / dist
                if side == "long"
                else (entry - es["trough"]) / dist
            )
            pullback_exit = (
                peak_r >= self.profit_trailing_start_r
                and progress <= peak_r * (1.0 - self.peak_pullback_pct)
            )

            # 4) 时间止损：超时且无明显进展
            timed_out = es["bars_in_trade"] >= self.max_holding_bars and progress < 0.5

            if hit_stop:
                await self._close_side(symbol, side, stop_price, "stop_or_lock", ts_ms=bar["ts"])
            elif pullback_exit:
                await self._close_side(symbol, side, close, "profit_pullback", ts_ms=bar["ts"])
            elif timed_out:
                await self._close_side(symbol, side, close, "time_stop", ts_ms=bar["ts"])

    # ------------------------------------------------------------------
    # 截面排序与重平衡
    # ------------------------------------------------------------------

    def _compute_cross_section(self, aligned_ts):
        scored = []
        for symbol in self.market.keys():
            rows = self._snapshot_upto(symbol, aligned_ts)
            if len(rows) < self.warmup_bars:
                continue
            score = self._momentum_score(
                rows, self.mom_fast_window_bars, self.mom_slow_window_bars, self.mom_fast_weight
            )
            if score is None:
                continue
            liq_rows = rows[-self.liquidity_window_bars :]
            turnover = sum(r[3] * r[4] for r in liq_rows) / max(1, len(liq_rows))
            if turnover < self.min_symbol_turnover_usdt:
                continue
            closes = [r[3] for r in rows]
            ema_trend = _ema(closes, self.trend_ema_window)
            adx = _wilder_adx(
                [r[1] for r in rows], [r[2] for r in rows], closes, self.adx_window
            )
            close = closes[-1]
            trend_ok_long = ema_trend is not None and close > ema_trend
            trend_ok_short = ema_trend is not None and close < ema_trend
            adx_ok = adx is not None and adx >= self.entry_min_adx
            atr = self._atr_from_rows(rows, self.atr_window)
            ann_vol = self._ann_vol(closes, self.vol_window_bars)
            scored.append(
                {
                    "symbol": symbol,
                    "score": score,
                    "close": close,
                    "trend_ok_long": trend_ok_long,
                    "trend_ok_short": trend_ok_short,
                    "adx_ok": adx_ok,
                    "atr": atr,
                    "ann_vol": ann_vol,
                }
            )
        scored.sort(key=lambda item: -item["score"])
        return scored

    def _rank_percentiles(self, scored):
        n = len(scored)
        percentiles = {}
        for i, item in enumerate(scored):
            percentiles[item["symbol"]] = (i + 1) / float(n) if n else 1.0
        return percentiles

    def _target_notional(self, ann_vol, equity):
        if not ann_vol or ann_vol <= _EPS:
            return 0.0
        target_pos_vol = self.target_portfolio_vol / math.sqrt(self.max_total_positions)
        raw = equity * target_pos_vol / ann_vol
        cap = equity * self.max_position_equity_pct
        return min(raw, cap)

    async def _rebalance(self, aligned_ts):
        equity = self._equity()
        paused = self._daily_paused(equity)
        now_ms = int(aligned_ts)
        scored = self._compute_cross_section(aligned_ts)
        if len(scored) < self.min_cross_section_symbols:
            return
        pct = self._rank_percentiles(scored)
        by_symbol = {item["symbol"]: item for item in scored}

        # --- 先处理截面失效退出 ---
        for symbol, side, _pos in list(await self._open_positions()):
            rank = pct.get(symbol)
            if rank is None:
                continue
            if side == "long" and rank > self.exit_rank_long:
                await self._close_side(symbol, side, by_symbol[symbol]["close"], "cross_section_exit", ts_ms=now_ms)
            elif side == "short" and rank < (1.0 - self.exit_rank_short):
                await self._close_side(symbol, side, by_symbol[symbol]["close"], "cross_section_exit", ts_ms=now_ms)

        if paused:
            return

        positions = await self._open_positions()
        held = {(s, d) for s, d, _ in positions}
        gross = self._gross_notional()
        long_count = sum(1 for _, d, _ in positions if d == "long")
        short_count = sum(1 for _, d, _ in positions if d == "short")
        remaining_gross = max(0.0, equity * self.max_gross_leverage - gross)

        k = max(1, int(round(len(scored) * self.rank_pct_long)))
        ks = max(1, int(round(len(scored) * self.rank_pct_short)))

        opened_symbols = set()

        # --- 多头入场 ---
        long_opened = 0
        for item in scored[:k]:
            if long_count >= self.max_long_positions:
                break
            sym = item["symbol"]
            if sym in opened_symbols or (sym, "long") in held:
                continue
            if not (item["trend_ok_long"] and item["adx_ok"]):
                continue
            until = self.cooldown_until.get(sym, 0)
            if until > now_ms:
                continue
            notional = min(self._target_notional(item["ann_vol"], equity), remaining_gross)
            if notional < self.min_notional_usdt:
                continue
            atr = item["atr"]
            if not atr or atr <= 0:
                continue
            if (sym, "short") in held:
                await self._close_side(sym, "short", item["close"], "flip_to_long", ts_ms=now_ms)
                held.discard((sym, "short"))
            result = await self.open_contract(
                sym, "long", notional, leverage=self.leverage, price=item["close"]
            )
            if str(result.get("status", "")) in ("submitted", "closed", "filled"):
                self._register_entry(sym, "long", item["close"], atr, now_ms, notional)
                remaining_gross -= notional
                long_count += 1
                opened_symbols.add(sym)

        # --- 空头入场 ---
        short_opened = 0
        for item in scored[-ks:][::-1]:
            if short_count >= self.max_short_positions:
                break
            sym = item["symbol"]
            if sym in opened_symbols or (sym, "short") in held:
                continue
            if not (item["trend_ok_short"] and item["adx_ok"]):
                continue
            until = self.cooldown_until.get(sym, 0)
            if until > now_ms:
                continue
            notional = min(self._target_notional(item["ann_vol"], equity), remaining_gross)
            if notional < self.min_notional_usdt:
                continue
            atr = item["atr"]
            if not atr or atr <= 0:
                continue
            if (sym, "long") in held:
                await self._close_side(sym, "long", item["close"], "flip_to_short", ts_ms=now_ms)
                held.discard((sym, "long"))
            result = await self.open_contract(
                sym, "short", notional, leverage=self.leverage, price=item["close"]
            )
            if str(result.get("status", "")) in ("submitted", "closed", "filled"):
                self._register_entry(sym, "short", item["close"], atr, now_ms, notional)
                remaining_gross -= notional
                short_count += 1
                opened_symbols.add(sym)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def on_bar(self, bar: BarData) -> None:
        symbol = bar.symbol
        ts = int(bar.timestamp)
        row = {
            "symbol": symbol,
            "ts": ts,
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "vol": float(bar.volume or 0.0),
        }
        if row["close"] <= 0 or row["high"] < row["low"]:
            return

        st = self._sym_state(symbol)
        if st["ts"] and st["ts"][-1] >= ts:
            return
        st["ts"].append(ts)
        st["high"].append(row["high"])
        st["low"].append(row["low"])
        st["close"].append(row["close"])
        st["vol"].append(row["vol"])

        self._day_roll(ts)
        await self._check_exits_for_bar(row)

        if self.next_rebalance_ts is None:
            self.next_rebalance_ts = ts + self.rebalance_bars * HOUR_MS
        elif ts >= self.next_rebalance_ts:
            while self.next_rebalance_ts <= ts:
                self.next_rebalance_ts += self.rebalance_bars * HOUR_MS
            aligned = ts - HOUR_MS
            await self._rebalance(aligned)

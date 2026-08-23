import math

from app.core.execution.base_strategy import BaseStrategy


class AntiMartingaleVolatilityBreakoutStrategy(BaseStrategy):
    """Paper-only dynamic breakout strategy with winner-only pyramiding."""

    runtime_key = "_antimartingale_runtime"
    pool_view_key = "_dynamic_pool_view"

    async def on_init(self):
        cfg = self.config or {}
        self.feed_symbols = list(self.symbols())
        self.min_h1_bars = max(24, int(cfg.get("min_h1_bars", 110)))
        self.ema_window = max(5, int(cfg.get("ema_window", 20)))
        self.atr_window = max(5, int(cfg.get("atr_window", 14)))
        self.efficiency_window = max(4, int(cfg.get("efficiency_window", 24)))
        self.candidate_count = max(1, int(cfg.get("candidate_count", 60)))
        self.score_min = min(100.0, max(0.0, float(cfg.get("score_min", 65.0))))
        self.score_confirmations = max(1, int(cfg.get("score_confirmations", 2)))
        self.atr_pct_min = max(0.0, float(cfg.get("atr_pct_min", 2.0)))
        self.atr_pct_max = max(self.atr_pct_min, float(cfg.get("atr_pct_max", 8.0)))
        self.efficiency_min = max(0.0, float(cfg.get("efficiency_min", 0.12)))
        self.extension_atr_max = max(0.1, float(cfg.get("extension_atr_max", 2.5)))
        self.breakout_window = max(5, int(cfg.get("breakout_window", 20)))
        self.breakout_volume_ratio = max(1.0, float(cfg.get("breakout_volume_ratio", 1.8)))
        self.leverage = max(1.0, float(cfg.get("leverage", 5.0)))
        self.risk_per_trade_pct = max(0.001, float(cfg.get("risk_per_trade_pct", 0.04)))
        self.reduced_risk_per_trade_pct = max(
            0.001, float(cfg.get("reduced_risk_per_trade_pct", 0.02))
        )
        self.risk_reduction_equity = max(0.0, float(cfg.get("risk_reduction_equity", 80.0)))
        self.stop_atr_mult = max(0.1, float(cfg.get("stop_atr_mult", 1.2)))
        self.hard_stop_price_pct = max(0.001, float(cfg.get("hard_stop_price_pct", 0.03)))
        self.max_position_equity_mult = max(
            0.1, float(cfg.get("max_position_equity_mult", 2.5))
        )
        self.break_even_buffer_bps = max(0.0, float(cfg.get("break_even_buffer_bps", 10.0)))
        self.first_add_at_r = max(0.1, float(cfg.get("first_add_at_r", 1.0)))
        self.second_add_at_r = max(self.first_add_at_r, float(cfg.get("second_add_at_r", 2.0)))
        self.first_add_mult = max(0.0, float(cfg.get("first_add_mult", 0.5)))
        self.second_add_mult = max(0.0, float(cfg.get("second_add_mult", 0.25)))
        self.trailing_start_r = max(0.1, float(cfg.get("trailing_start_r", 2.0)))
        self.trailing_atr_mult = max(0.1, float(cfg.get("trailing_atr_mult", 2.0)))
        self.trailing_pullback_pct = min(
            0.95, max(0.01, float(cfg.get("trailing_pullback_pct", 0.40)))
        )
        self.tighten_at_r = max(self.trailing_start_r, float(cfg.get("tighten_at_r", 4.0)))
        self.tight_atr_mult = max(0.1, float(cfg.get("tight_atr_mult", 1.2)))
        self.tight_pullback_pct = min(
            self.trailing_pullback_pct,
            max(0.01, float(cfg.get("tight_pullback_pct", 0.22))),
        )
        self.hard_take_profit_r = max(1.0, float(cfg.get("hard_take_profit_r", 10.0)))
        self.daily_loss_pct = min(0.5, max(0.0, float(cfg.get("daily_loss_pct", 0.08))))
        self.terminal_floor_equity = max(0.0, float(cfg.get("terminal_floor_equity", 60.0)))
        self.terminal_target_equity = max(
            self.terminal_floor_equity, float(cfg.get("terminal_target_equity", 200.0))
        )
        self.challenge_duration_ms = max(
            86_400_000, int(cfg.get("challenge_duration_ms", 7 * 86_400_000))
        )
        self.event_limit = max(50, min(500, int(cfg.get("pool_event_limit", 200))))
        self.h1_bars = {}
        self.h1_building = {}
        self.bars_15m = {}
        self.latest_scores = {}
        self.score_confirm = {}
        self.candidate_symbols = set()
        self.trigger_symbols = set()
        self.pool_member_keys = set()
        self.hour_seen = {}
        self.last_scored_hour = -1
        restored = self.state.positions.get(self.runtime_key)
        self.runtime = dict(restored) if isinstance(restored, dict) else {}
        restored_entry_state = self.runtime.get("entry_state")
        self.entry_state = dict(restored_entry_state) if isinstance(restored_entry_state, dict) else {}
        restored_events = self.runtime.get("events")
        self.events = (
            [dict(item) for item in restored_events if isinstance(item, dict)][-self.event_limit :]
            if isinstance(restored_events, list)
            else []
        )
        restored_candidates = self.runtime.get("candidate_symbols")
        if isinstance(restored_candidates, list):
            self.candidate_symbols = {str(item) for item in restored_candidates}
        restored_members = self.runtime.get("pool_member_keys")
        if isinstance(restored_members, list):
            self.pool_member_keys = {str(item) for item in restored_members}
        self.runtime.setdefault("challenge_started_at_ms", 0)
        self.runtime.setdefault("challenge_ends_at_ms", 0)
        self.runtime.setdefault("day_number", -1)
        self.runtime.setdefault("day_start_equity", 0.0)
        self.runtime.setdefault("pause_until_day", -1)
        self.runtime.setdefault("equity_floor", 0.0)
        self.runtime.setdefault("terminal_reason", "")
        self.last_scored_hour = int(self.runtime.get("last_scored_hour", -1) or -1)
        restored_confirm = self.runtime.get("score_confirm")
        if isinstance(restored_confirm, dict):
            self.score_confirm = dict(restored_confirm)
        self._persist_runtime()
        self._write_pool_view(self.last_scored_hour)

    async def on_bar(self, bar):
        symbol = str(bar.symbol)
        bars_15m = list(self.bars_15m.get(symbol, []))
        bars_15m.append(bar)
        self.bars_15m[symbol] = bars_15m[-400:]
        if not self.broker.warmup_mode:
            if await self._apply_portfolio_guards(int(bar.timestamp)):
                self._persist_runtime()
                self._write_pool_view(self.last_scored_hour)
                return None
            for side in ("long", "short"):
                result = await self._manage_position(symbol, side, bar)
                if self._filled(result) and str(result.get("side") or "") == side:
                    self._persist_runtime()
                    return result
        completed = self._aggregate_15m_bar(bar)
        if completed is not None:
            bucket = int(completed["timestamp"]) // 3_600_000
            seen = list(self.hour_seen.get(str(bucket), []))
            if symbol not in seen:
                seen.append(symbol)
            self.hour_seen[str(bucket)] = seen
            eligible = {
                item for item in self.feed_symbols if len(self.h1_bars.get(item, [])) >= self.min_h1_bars
            }
            required = max(1, (len(eligible) * 3 + 4) // 5)
            if bucket > self.last_scored_hour and len(eligible.intersection(seen)) >= required:
                self._refresh_cross_section(bucket)
        if not self.broker.warmup_mode and len(self.entry_state) < 2:
            trigger = self._entry_trigger(symbol, bar)
            if isinstance(trigger, dict):
                result = await self._open_trigger(trigger, bar)
                self._persist_runtime()
                return result
        self._persist_runtime()
        return None

    def _ema(self, values, period):
        if not values:
            return []
        alpha = 2.0 / (float(period) + 1.0)
        output = [float(values[0])]
        for value in values[1:]:
            output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
        return output

    def _atr_series(self, bars, period):
        if not bars:
            return []
        true_ranges = []
        previous_close = float(bars[0]["close"])
        for row in bars:
            high = float(row["high"])
            low = float(row["low"])
            true_ranges.append(
                max(high - low, abs(high - previous_close), abs(low - previous_close))
            )
            previous_close = float(row["close"])
        return self._ema(true_ranges, period)

    def _atr(self, bars, period):
        values = self._atr_series(bars, period)
        return float(values[-1]) if values else 0.0

    def _efficiency(self, closes, window):
        if len(closes) < 2:
            return 0.0
        sample = [float(value) for value in closes[-(max(1, int(window)) + 1) :]]
        if len(sample) < 2:
            return 0.0
        path = sum(abs(sample[index] - sample[index - 1]) for index in range(1, len(sample)))
        return abs(sample[-1] - sample[0]) / path if path > 0 else 0.0

    def _percentile_rank(self, value, sample):
        numbers = [float(item) for item in sample if self._finite(item)]
        if not numbers:
            return 0.0
        target = float(value)
        below = sum(1 for item in numbers if item < target)
        equal = sum(1 for item in numbers if item == target)
        return 100.0 * (float(below) + 0.5 * float(equal)) / float(len(numbers))

    def _correlation(self, left, right):
        count = min(len(left), len(right))
        if count < 2:
            return 0.0
        lhs = [float(item) for item in left[-count:]]
        rhs = [float(item) for item in right[-count:]]
        lhs_mean = sum(lhs) / float(count)
        rhs_mean = sum(rhs) / float(count)
        numerator = sum(
            (lhs[index] - lhs_mean) * (rhs[index] - rhs_mean) for index in range(count)
        )
        lhs_var = sum((item - lhs_mean) ** 2 for item in lhs)
        rhs_var = sum((item - rhs_mean) ** 2 for item in rhs)
        denominator = math.sqrt(lhs_var * rhs_var)
        return numerator / denominator if denominator > 0 else 0.0

    def _finite(self, value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _aggregate_15m_bar(self, bar):
        symbol = str(bar.symbol)
        bucket = int(bar.timestamp) // 3_600_000
        current = self.h1_building.get(symbol)
        if current is None:
            self.h1_building[symbol] = self._new_h1_bar(bar, bucket)
            return None
        if int(current["bucket"]) == bucket:
            current["high"] = max(float(current["high"]), float(bar.high))
            current["low"] = min(float(current["low"]), float(bar.low))
            current["close"] = float(bar.close)
            current["volume"] = float(current["volume"]) + float(bar.volume)
            return None
        completed = dict(current)
        completed.pop("bucket", None)
        rows = list(self.h1_bars.get(symbol, []))
        rows.append(completed)
        self.h1_bars[symbol] = rows[-800:]
        self.h1_building[symbol] = self._new_h1_bar(bar, bucket)
        return completed

    def _new_h1_bar(self, bar, bucket):
        return {
            "bucket": int(bucket),
            "timestamp": int(bucket) * 3_600_000,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }

    def _score_symbol(self, symbol, completed_hour):
        bars = list(self.h1_bars.get(symbol, []))
        if len(bars) < self.min_h1_bars:
            return None
        closes = [float(row["close"]) for row in bars]
        ema_values = self._ema(closes, self.ema_window)
        atr_value = self._atr(bars, self.atr_window)
        close = closes[-1]
        if close <= 0 or atr_value <= 0 or len(ema_values) < 2:
            return None
        slope = float(ema_values[-1]) - float(ema_values[-2])
        direction = 1 if slope > 0 else -1 if slope < 0 else 0
        if direction == 0:
            return None
        row = {
            "symbol": symbol,
            "direction": direction,
            "completed_hour": int(completed_hour),
            "atr": atr_value,
            "atr_pct": atr_value / close * 100.0,
            "efficiency": self._efficiency(closes, self.efficiency_window),
            "ema20": float(ema_values[-1]),
            "ema_slope": slope,
            "extension_atr": abs(close - float(ema_values[-1])) / atr_value,
            "momentum_6h": (close / closes[-7] - 1.0) * 100.0,
            "momentum_24h": (close / closes[-25] - 1.0) * 100.0,
            "volume_ratio": float(bars[-1]["volume"])
            / max(1e-12, self._median([float(item["volume"]) for item in bars[-21:-1]])),
            "compression_ratio": atr_value / max(1e-12, self._atr(bars, 48)),
            "turnover_24h": sum(
                float(item["close"]) * float(item["volume"]) for item in bars[-24:]
            ),
        }
        if row["momentum_6h"] * float(direction) <= 0 or row["momentum_24h"] * float(direction) <= 0:
            return None
        history_15m = list(self.bars_15m.get(symbol, []))[-self.breakout_window :]
        if len(history_15m) >= self.breakout_window:
            boundary = (
                max(float(item.high) for item in history_15m)
                if direction > 0
                else min(float(item.low) for item in history_15m)
            )
            row["breakout_distance_atr"] = abs(boundary - close) / atr_value
        else:
            row["breakout_distance_atr"] = 999.0
        self.latest_scores[symbol] = row
        return row

    def _refresh_cross_section(self, completed_hour):
        rows = []
        for symbol in self.feed_symbols:
            row = self._score_symbol(symbol, completed_hour)
            if isinstance(row, dict):
                rows.append(row)
        if not rows:
            self.latest_scores = {}
            self.candidate_symbols = set()
            self.trigger_symbols = set()
            self.last_scored_hour = int(completed_hour)
            self._write_pool_view(completed_hour)
            return
        relative_values = [
            float(row["momentum_24h"]) * float(row["direction"]) for row in rows
        ]
        compression_values = [float(row["compression_ratio"]) for row in rows]
        distance_values = [float(row["breakout_distance_atr"]) for row in rows]
        efficiency_values = [float(row["efficiency"]) for row in rows]
        slope_values = [float(row["ema_slope"]) * float(row["direction"]) for row in rows]
        volume_values = [float(row["volume_ratio"]) for row in rows]
        turnover_values = [float(row["turnover_24h"]) for row in rows]
        self.latest_scores = {}
        for row in rows:
            relative = float(row["momentum_24h"]) * float(row["direction"])
            slope = float(row["ema_slope"]) * float(row["direction"])
            score = (
                self._percentile_rank(relative, relative_values) * 0.25
                + (100.0 - self._percentile_rank(row["compression_ratio"], compression_values)) * 0.20
                + (100.0 - self._percentile_rank(row["breakout_distance_atr"], distance_values)) * 0.15
                + self._percentile_rank(row["efficiency"], efficiency_values) * 0.15
                + self._percentile_rank(slope, slope_values) * 0.10
                + self._percentile_rank(row["volume_ratio"], volume_values) * 0.10
                + self._percentile_rank(row["turnover_24h"], turnover_values) * 0.05
            )
            row["score"] = min(100.0, max(0.0, score))
            row["confirmed"] = 0
            row["openable"] = False
            self.latest_scores[str(row["symbol"])] = row
        self._rank_candidates(completed_hour)

    def _passes_hard_gates(self, row):
        if not isinstance(row, dict):
            return False
        direction = int(row.get("direction", 0) or 0)
        slope = float(row.get("ema_slope", 0.0) or 0.0)
        return (
            direction in (-1, 1)
            and self.atr_pct_min <= float(row.get("atr_pct", 0.0) or 0.0) <= self.atr_pct_max
            and float(row.get("efficiency", 0.0) or 0.0) >= self.efficiency_min
            and float(row.get("extension_atr", 999.0) or 999.0) <= self.extension_atr_max
            and float(row.get("score", 0.0) or 0.0) >= self.score_min
            and int(row.get("confirmed", 0) or 0) >= self.score_confirmations
            and slope * float(direction) > 0
        )

    def _rank_candidates(self, completed_hour):
        previous_candidates = set(self.candidate_symbols)
        previous_members = set(self.pool_member_keys)
        rows = [row for row in self.latest_scores.values() if isinstance(row, dict)]
        rows.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
        selected = {str(row.get("symbol")) for row in rows[: self.candidate_count] if row.get("symbol")}
        self.candidate_symbols = selected
        longs = [row for row in rows if int(row.get("direction", 0) or 0) > 0][:5]
        shorts = [row for row in rows if int(row.get("direction", 0) or 0) < 0][:5]
        self.trigger_symbols = {
            str(row.get("symbol")) for row in longs + shorts if row.get("symbol")
        }
        for row in rows:
            symbol = str(row.get("symbol") or "")
            direction = int(row.get("direction", 0) or 0)
            key = symbol + "|" + str(direction)
            if symbol in self.trigger_symbols and self._base_score_gates(row):
                self.score_confirm[key] = int(self.score_confirm.get(key, 0) or 0) + 1
            else:
                self.score_confirm[key] = 0
            row["confirmed"] = int(self.score_confirm[key])
            row["openable"] = self._passes_hard_gates(row)
        self.pool_member_keys = {
            str(row.get("symbol")) + "|" + str(int(row.get("direction", 0) or 0))
            for row in rows
            if bool(row.get("openable"))
        }
        ts = int(completed_hour) * 3_600_000
        for symbol in sorted(selected - previous_candidates):
            self._record_event("candidate_enter", ts, symbol)
        for symbol in sorted(previous_candidates - selected):
            self._record_event("candidate_exit", ts, symbol)
        for key in sorted(self.pool_member_keys - previous_members):
            symbol, direction = key.rsplit("|", 1)
            row = self.latest_scores.get(symbol, {})
            self._record_event(
                "pool_enter",
                ts,
                symbol,
                direction=int(direction),
                side="long" if int(direction) > 0 else "short",
                score=float(row.get("score", 0.0) or 0.0),
                tier="normal",
            )
        for key in sorted(previous_members - self.pool_member_keys):
            symbol, direction = key.rsplit("|", 1)
            self._record_event(
                "pool_exit",
                ts,
                symbol,
                direction=int(direction),
                side="long" if int(direction) > 0 else "short",
            )
        self.last_scored_hour = max(int(self.last_scored_hour), int(completed_hour))
        self._write_pool_view(completed_hour)

    def _base_score_gates(self, row):
        probe = dict(row)
        probe["confirmed"] = self.score_confirmations
        return self._passes_hard_gates(probe)

    def _median(self, values):
        numbers = sorted(float(value) for value in values)
        if not numbers:
            return 0.0
        middle = len(numbers) // 2
        if len(numbers) % 2:
            return numbers[middle]
        return (numbers[middle - 1] + numbers[middle]) / 2.0

    def _entry_trigger(self, symbol, bar):
        score = self.latest_scores.get(symbol)
        if not isinstance(score, dict) or not self._passes_hard_gates(score):
            return None
        history = list(self.bars_15m.get(symbol, []))
        if history and int(history[-1].timestamp) == int(bar.timestamp):
            history = history[:-1]
        sample = history[-self.breakout_window :]
        if len(sample) < self.breakout_window:
            return None
        median_volume = self._median([float(item.volume) for item in sample])
        if median_volume <= 0 or float(bar.volume) < median_volume * self.breakout_volume_ratio:
            return None
        direction = int(score.get("direction", 0) or 0)
        if direction > 0 and float(bar.close) > max(float(item.high) for item in sample):
            return {"symbol": symbol, "side": "long", "score": float(score["score"])}
        if direction < 0 and float(bar.close) < min(float(item.low) for item in sample):
            return {"symbol": symbol, "side": "short", "score": float(score["score"])}
        return None

    def _equity(self):
        return max(0.0, float(self.broker.equity))

    def _initial_order_plan(self, equity, entry_price, atr):
        equity_value = max(0.0, float(equity))
        entry = max(1e-12, float(entry_price))
        atr_value = max(1e-12, float(atr))
        risk_pct = (
            self.reduced_risk_per_trade_pct
            if equity_value < self.risk_reduction_equity
            else self.risk_per_trade_pct
        )
        risk_usdt = equity_value * risk_pct
        risk_price = min(atr_value * self.stop_atr_mult, entry * self.hard_stop_price_pct)
        stop_distance_pct = risk_price / entry
        notional = min(
            risk_usdt / max(1e-12, stop_distance_pct),
            equity_value * self.max_position_equity_mult,
        )
        return {
            "risk_usdt": risk_usdt,
            "risk_price": risk_price,
            "stop_distance_pct": stop_distance_pct,
            "notional_usdt": notional,
            "leverage": self.leverage,
        }

    async def _open_trigger(self, trigger, bar):
        symbol = str(trigger["symbol"])
        side = str(trigger["side"])
        score = self.latest_scores.get(symbol)
        if not isinstance(score, dict):
            return None
        entry = float(bar.close)
        plan = self._initial_order_plan(self._equity(), entry, float(score["atr"]))
        result = await self.open_contract(
            symbol,
            side,
            float(plan["notional_usdt"]),
            leverage=float(plan["leverage"]),
            price=entry,
        )
        if not self._filled(result):
            return result
        risk_price = float(plan["risk_price"])
        key = symbol + "|" + side
        self.entry_state[key] = {
            "entry_price": entry,
            "initial_risk_price": risk_price,
            "initial_risk_usdt": float(plan["risk_usdt"]),
            "initial_notional": float(plan["notional_usdt"]),
            "total_notional": float(plan["notional_usdt"]),
            "adds": 0,
            "highest": entry,
            "lowest": entry,
            "stop_price": entry - risk_price if side == "long" else entry + risk_price,
            "peak_r": 0.0,
            "entry_hour": int(bar.timestamp) // 3_600_000,
            "score": float(trigger.get("score", 0.0) or 0.0),
            "legs": [{"price": entry, "notional": float(plan["notional_usdt"])}],
        }
        self._record_event(
            "position_open",
            int(bar.timestamp),
            symbol,
            side=side,
            score=float(trigger.get("score", 0.0) or 0.0),
            notional_usdt=float(plan["notional_usdt"]),
        )
        return result

    def _filled(self, result):
        if not isinstance(result, dict):
            return False
        return str(result.get("status") or "").lower() in ("filled", "closed", "success")

    def _basket_worst_pnl(self, state, side):
        legs = state.get("legs")
        if not isinstance(legs, list) or not legs:
            legs = [
                {
                    "price": float(state["entry_price"]),
                    "notional": float(state["initial_notional"]),
                }
            ]
        stop = float(state["stop_price"])
        direction = 1.0 if side == "long" else -1.0
        total = 0.0
        for leg in legs:
            price = max(1e-12, float(leg["price"]))
            quantity = float(leg["notional"]) / price
            total += (stop - price) * direction * quantity
        return total

    async def _manage_position(self, symbol, side, bar):
        position = await self.get_contract_position(symbol, side)
        if not isinstance(position, dict):
            return None
        key = symbol + "|" + side
        state = self.entry_state.get(key)
        if not isinstance(state, dict):
            return None
        entry = float(state["entry_price"])
        risk = max(1e-12, float(state["initial_risk_price"]))
        previous_stop = float(state["stop_price"])
        take_profit = entry + risk * self.hard_take_profit_r if side == "long" else entry - risk * self.hard_take_profit_r
        stop_hit = float(bar.low) <= previous_stop if side == "long" else float(bar.high) >= previous_stop
        take_profit_hit = float(bar.high) >= take_profit if side == "long" else float(bar.low) <= take_profit
        if stop_hit or take_profit_hit:
            close_price = previous_stop if stop_hit else take_profit
            result = await self.close_contract(symbol, side, ratio=1.0, price=close_price)
            if self._filled(result):
                self._record_event(
                    "position_close",
                    int(bar.timestamp),
                    symbol,
                    side=side,
                    reason="stop_loss_or_trailing" if stop_hit else "hard_take_profit_10r",
                    price=float(close_price),
                    pnl=float(result.get("realized_pnl", 0.0) or 0.0),
                )
                self.entry_state.pop(key, None)
            return result

        if side == "long":
            state["highest"] = max(float(state.get("highest", entry)), float(bar.high))
            state["lowest"] = min(float(state.get("lowest", entry)), float(bar.low))
            best_r = (float(state["highest"]) - entry) / risk
        else:
            state["lowest"] = min(float(state.get("lowest", entry)), float(bar.low))
            state["highest"] = max(float(state.get("highest", entry)), float(bar.high))
            best_r = (entry - float(state["lowest"])) / risk
        state["peak_r"] = max(float(state.get("peak_r", 0.0)), best_r)
        buffer = entry * self.break_even_buffer_bps / 10_000.0
        if best_r >= self.first_add_at_r:
            state["stop_price"] = (
                max(float(state["stop_price"]), entry + buffer)
                if side == "long"
                else min(float(state["stop_price"]), entry - buffer)
            )
        atr_value = float(self.latest_scores.get(symbol, {}).get("atr", risk / self.stop_atr_mult))
        if best_r >= self.trailing_start_r:
            pullback = self.tight_pullback_pct if best_r >= self.tighten_at_r else self.trailing_pullback_pct
            atr_mult = self.tight_atr_mult if best_r >= self.tighten_at_r else self.trailing_atr_mult
            if side == "long":
                state["stop_price"] = max(
                    float(state["stop_price"]),
                    entry + best_r * (1.0 - pullback) * risk,
                    float(state["highest"]) - atr_value * atr_mult,
                )
            else:
                state["stop_price"] = min(
                    float(state["stop_price"]),
                    entry - best_r * (1.0 - pullback) * risk,
                    float(state["lowest"]) + atr_value * atr_mult,
                )
        adds = int(state.get("adds", 0) or 0)
        add_mult = 0.0
        if adds == 0 and best_r >= self.first_add_at_r:
            add_mult = self.first_add_mult
        elif adds == 1 and best_r >= self.second_add_at_r:
            if side == "long":
                state["stop_price"] = max(float(state["stop_price"]), entry + 0.8 * risk)
            else:
                state["stop_price"] = min(float(state["stop_price"]), entry - 0.8 * risk)
            add_mult = self.second_add_mult
        if add_mult > 0:
            add_notional = float(state["initial_notional"]) * add_mult
            legs = state.get("legs")
            if not isinstance(legs, list) or not legs:
                legs = [
                    {
                        "price": entry,
                        "notional": float(state["initial_notional"]),
                    }
                ]
            candidate_legs = list(legs) + [
                {"price": float(bar.close), "notional": add_notional}
            ]
            candidate_state = dict(state)
            candidate_state["legs"] = candidate_legs
            max_reopened_loss = -0.25 * float(state["initial_risk_usdt"])
            if self._basket_worst_pnl(candidate_state, side) < max_reopened_loss:
                return None
            result = await self.open_contract(
                symbol, side, add_notional, leverage=self.leverage, price=float(bar.close)
            )
            if self._filled(result):
                state["adds"] = adds + 1
                state["total_notional"] = float(state.get("total_notional", 0.0)) + add_notional
                state["legs"] = candidate_legs
                self._record_event(
                    "antimartingale_add",
                    int(bar.timestamp),
                    symbol,
                    side=side,
                    add_number=adds + 1,
                    notional_usdt=add_notional,
                    peak_r=float(state["peak_r"]),
                )
            return result
        return None

    def _record_event(self, kind, ts, symbol, **fields):
        event = {
            "event_id": str(int(ts)) + "|" + str(kind) + "|" + str(symbol) + "|" + str(fields.get("side") or ""),
            "ts": int(ts),
            "kind": str(kind),
            "symbol": str(symbol),
        }
        event.update(fields)
        if not any(str(item.get("event_id")) == event["event_id"] for item in self.events):
            self.events.append(event)
            self.events = self.events[-self.event_limit :]

    async def _close_all_positions(self, reason, ts):
        for key in list(self.entry_state):
            symbol, side = key.rsplit("|", 1)
            state = self.entry_state.get(key, {})
            price = float(state.get("stop_price", state.get("entry_price", 0.0)) or 0.0)
            result = await self.close_contract(symbol, side, ratio=1.0, price=price)
            if self._filled(result):
                self._record_event(
                    "position_close",
                    ts,
                    symbol,
                    side=side,
                    reason=reason,
                    price=price,
                    pnl=float(result.get("realized_pnl", 0.0) or 0.0),
                )
                self.entry_state.pop(key, None)

    async def _apply_portfolio_guards(self, now_ms):
        now = int(now_ms)
        terminal = str(self.runtime.get("terminal_reason") or "")
        if terminal:
            return True
        equity = self._equity()
        started = int(self.runtime.get("challenge_started_at_ms", 0) or 0)
        if started <= 0:
            started = now
            self.runtime["challenge_started_at_ms"] = started
            self.runtime["challenge_ends_at_ms"] = started + self.challenge_duration_ms
        day = now // 86_400_000
        if int(self.runtime.get("day_number", -1) or -1) != day:
            self.runtime["day_number"] = day
            self.runtime["day_start_equity"] = equity
            if int(self.runtime.get("pause_until_day", -1) or -1) <= day:
                self.runtime["pause_until_day"] = -1
        if equity <= self.terminal_floor_equity:
            await self._close_all_positions("equity_floor_60", now)
            self.runtime["terminal_reason"] = "equity_floor_60"
            self._record_event("challenge_terminal", now, "PORTFOLIO", reason="equity_floor_60", equity=equity)
            return True
        if equity >= self.terminal_target_equity:
            await self._close_all_positions("target_200", now)
            self.runtime["terminal_reason"] = "target_200"
            self._record_event("challenge_terminal", now, "PORTFOLIO", reason="target_200", equity=equity)
            return True
        if now >= int(self.runtime.get("challenge_ends_at_ms", 0) or 0):
            await self._close_all_positions("challenge_expired", now)
            self.runtime["terminal_reason"] = "challenge_expired"
            self._record_event("challenge_terminal", now, "PORTFOLIO", reason="challenge_expired", equity=equity)
            return True
        floor = float(self.runtime.get("equity_floor", 0.0) or 0.0)
        for threshold, candidate_floor in ((120.0, 108.0), (140.0, 120.0), (160.0, 138.0), (180.0, 160.0)):
            if equity >= threshold:
                floor = max(floor, candidate_floor)
        if floor > float(self.runtime.get("equity_floor", 0.0) or 0.0):
            self.runtime["equity_floor"] = floor
            self._record_event("equity_floor_up", now, "PORTFOLIO", floor=floor, equity=equity)
        if floor > 0 and equity < floor:
            await self._close_all_positions("ratchet_exit", now)
            self.runtime["terminal_reason"] = "ratchet_exit"
            self._record_event("challenge_terminal", now, "PORTFOLIO", reason="ratchet_exit", equity=equity)
            return True
        day_start = float(self.runtime.get("day_start_equity", equity) or equity)
        if day_start > 0 and equity <= day_start * (1.0 - self.daily_loss_pct):
            await self._close_all_positions("daily_loss_pause", now)
            self.runtime["pause_until_day"] = day + 1
            self._record_event("daily_pause", now, "PORTFOLIO", equity=equity, until_day=day + 1)
            return True
        return int(self.runtime.get("pause_until_day", -1) or -1) > day

    def _persist_runtime(self):
        self.runtime["last_scored_hour"] = int(self.last_scored_hour)
        self.runtime["score_confirm"] = dict(self.score_confirm)
        self.runtime["entry_state"] = dict(self.entry_state)
        self.runtime["events"] = list(self.events)
        self.runtime["candidate_symbols"] = sorted(self.candidate_symbols)
        self.runtime["pool_member_keys"] = sorted(self.pool_member_keys)
        self.state.positions[self.runtime_key] = self.runtime

    def _write_pool_view(self, completed_hour):
        timestamp = int(completed_hour) * 3_600_000 if int(completed_hour) >= 0 else None
        self.state.positions[self.pool_view_key] = {
            "schema_version": 3,
            "mode": "ema_factor_adaptive",
            "status": "ready" if timestamp is not None else "warming",
            "selection_summary": "1H波动爆发评分 · 15M放量突破 · 反马丁盈利加仓",
            "updated_at_ms": timestamp,
            "last_scan_ms": timestamp,
            "next_scan_ms": timestamp + 3_600_000 if timestamp is not None else None,
            "candidates_total": len(self.candidate_symbols),
            "eligible_symbols": len(self.latest_scores),
            "candidates_near": [],
            "members": [
                {
                    "symbol": row["symbol"],
                    "direction": row["direction"],
                    "score": round(float(row.get("score", 0.0)), 2),
                    "tier": "normal",
                    "confirmed": int(row.get("confirmed", 0) or 0),
                    "openable": bool(row.get("openable")),
                    "reasons": [] if row.get("openable") else ["等待连续确认或突破"],
                    "atr_pct": round(float(row.get("atr_pct", 0.0)), 2),
                    "efficiency": round(float(row.get("efficiency", 0.0)), 4),
                }
                for row in self.latest_scores.values()
                if str(row.get("symbol")) in self.trigger_symbols
            ],
            "positions": [
                {
                    "symbol": key.rsplit("|", 1)[0],
                    "side": key.rsplit("|", 1)[1],
                    "tier": "normal",
                    "entry_price": state.get("entry_price"),
                    "notional_usdt": state.get("total_notional"),
                    "pyramid_adds": state.get("adds", 0),
                }
                for key, state in self.entry_state.items()
                if isinstance(state, dict)
            ],
            "events": list(self.events),
        }

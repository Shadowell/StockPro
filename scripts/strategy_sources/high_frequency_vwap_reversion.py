import math

from app.core.execution.base_strategy import BaseStrategy


class HighFrequencyVwapReversionStrategy(BaseStrategy):
    """Paper-only 5M VWAP reversion strategy gated by completed 1H range state."""

    runtime_key = "_vwap_reversion_runtime"
    pool_view_key = "_dynamic_pool_view"

    async def on_init(self):
        cfg = self.config or {}
        self.feed_symbols = list(self.symbols())
        self.h1_history_limit = max(48, int(cfg.get("h1_history_limit", 360)))
        self.min_h1_bars = max(24, int(cfg.get("min_h1_bars", 36)))
        self.turnover_window = max(6, int(cfg.get("turnover_window", 24)))
        self.candidate_count = max(1, int(cfg.get("candidate_count", 20)))
        self.state_confirmations = max(1, int(cfg.get("state_confirmations", 2)))
        self.atr_window = max(2, int(cfg.get("atr_window", 14)))
        self.adx_window = max(2, int(cfg.get("adx_window", 14)))
        self.adx_min = max(0.0, float(cfg.get("adx_min", 8.0)))
        self.adx_max = max(self.adx_min, float(cfg.get("adx_max", 18.0)))
        self.efficiency_window = max(4, int(cfg.get("efficiency_window", 24)))
        self.efficiency_max = max(0.0, float(cfg.get("efficiency_max", 0.18)))
        self.direction_window = max(2, int(cfg.get("direction_window", 12)))
        self.direction_atr_max = max(0.0, float(cfg.get("direction_atr_max", 0.80)))
        self.atr_pct_min = max(0.0, float(cfg.get("atr_pct_min", 0.5)))
        self.atr_pct_max = max(self.atr_pct_min, float(cfg.get("atr_pct_max", 5.0)))
        self.vwap_window = max(4, int(cfg.get("h1_vwap_window", 24)))
        self.vwap_crosses_min = max(0, int(cfg.get("vwap_crosses_min", 4)))
        self.extension_atr_max = max(0.0, float(cfg.get("extension_atr_max", 1.2)))
        self.vwap_5m_window = max(12, int(cfg.get("vwap_5m_window", 48)))
        self.z_entry = max(0.5, float(cfg.get("z_entry", 2.0)))
        self.z_recovery_min = max(0.0, float(cfg.get("z_recovery_min", 0.25)))
        self.volume_window = max(3, int(cfg.get("volume_window", 20)))
        self.volume_ratio_min = max(0.0, float(cfg.get("volume_ratio_min", 0.8)))
        self.volume_ratio_max = max(
            self.volume_ratio_min, float(cfg.get("volume_ratio_max", 2.5))
        )
        self.max_bar_range_atr = max(0.1, float(cfg.get("max_bar_range_atr", 1.8)))
        self.round_trip_cost_bps = max(0.0, float(cfg.get("round_trip_cost_bps", 20.0)))
        self.cost_edge_multiple = max(1.0, float(cfg.get("cost_edge_multiple", 3.0)))
        self.initial_stop_atr_mult = max(0.1, float(cfg.get("initial_stop_atr_mult", 0.9)))
        self.extreme_stop_buffer_atr = max(
            0.0, float(cfg.get("extreme_stop_buffer_atr", 0.35))
        )
        self.hard_take_profit_r = max(0.1, float(cfg.get("hard_take_profit_r", 1.10)))
        self.risk_per_trade_pct = max(0.0001, float(cfg.get("risk_per_trade_pct", 0.0035)))
        self.max_position_notional_usdt = max(
            0.5, float(cfg.get("max_position_notional_usdt", 40.0))
        )
        self.max_positions = max(1, int(cfg.get("max_positions", 4)))
        self.same_direction_cap = max(1, int(cfg.get("same_direction_cap", 2)))
        self.max_total_notional_equity_pct = max(
            0.1, float(cfg.get("max_total_notional_equity_pct", 1.2))
        )
        self.min_order_notional_usdt = max(0.0, float(cfg.get("min_order_notional_usdt", 0.5)))
        self.break_even_at_r = max(0.1, float(cfg.get("break_even_at_r", 0.40)))
        self.profit_trailing_start_r = max(
            self.break_even_at_r, float(cfg.get("profit_trailing_start_r", 0.70))
        )
        self.profit_peak_pullback_pct = min(
            0.95, max(0.01, float(cfg.get("profit_peak_pullback_pct", 0.25)))
        )
        self.profit_atr_stop_mult = max(0.1, float(cfg.get("profit_atr_stop_mult", 0.55)))
        self.regime_break_adx = max(0.0, float(cfg.get("regime_break_adx", 24.0)))
        self.regime_break_efficiency = max(
            0.0, float(cfg.get("regime_break_efficiency", 0.35))
        )
        self.regime_break_direction_atr = max(
            0.0, float(cfg.get("regime_break_direction_atr", 1.5))
        )
        self.max_holding_bars = max(1, int(cfg.get("max_holding_bars", 24)))
        self.cooldown_bars = max(1, int(cfg.get("cooldown_bars", 6)))
        self.loss_cooldown_count = max(1, int(cfg.get("loss_cooldown_count", 4)))
        self.loss_cooldown_ms = max(
            3_600_000, int(float(cfg.get("loss_cooldown_hours", 2)) * 3_600_000)
        )
        self.daily_loss_pct = min(0.5, max(0.0, float(cfg.get("daily_loss_pct", 0.025))))
        self.daily_lock_activation_pct = max(
            0.0, float(cfg.get("daily_lock_activation_pct", 0.015))
        )
        self.daily_lock_fraction = min(
            0.95, max(0.01, float(cfg.get("daily_lock_fraction", 0.50)))
        )
        self.terminal_floor_equity = max(
            0.0, float(cfg.get("terminal_floor_equity", 88.0))
        )
        self.leverage = max(1.0, float(cfg.get("leverage", 5.0)))
        self.event_limit = max(50, min(500, int(cfg.get("pool_event_limit", 300))))
        self.h1_bars = {}
        self.h1_building = {}
        self.last_5m_timestamp = {}
        self.bars_5m = {}
        self.five_minute_counts = {}
        self.candidate_symbols = set()
        self.latest_states = {}
        self.state_confirm = {}
        self.hour_seen = {}
        self.cooldown_until_bar = {}
        self.entry_state = {}
        restored = self.state.positions.get(self.runtime_key)
        self.runtime = dict(restored) if isinstance(restored, dict) else {}
        self.runtime.setdefault("events", [])
        self.runtime.setdefault("day_number", -1)
        self.runtime.setdefault("day_start_equity", 0.0)
        self.runtime.setdefault("day_peak_equity", 0.0)
        self.runtime.setdefault("daily_profit_floor", 0.0)
        self.runtime.setdefault("pause_until_day", -1)
        self.runtime.setdefault("pause_until_ms", 0)
        self.runtime.setdefault("terminal_reason", "")
        self.runtime.setdefault("last_guard_reason", "")
        self.runtime.setdefault("last_exit_reason", "")
        self.runtime.setdefault("loss_streak", 0)
        restored_candidates = self.runtime.get("candidate_symbols")
        if isinstance(restored_candidates, list):
            self.candidate_symbols = {str(item) for item in restored_candidates}
        restored_confirm = self.runtime.get("state_confirm")
        if isinstance(restored_confirm, dict):
            self.state_confirm = dict(restored_confirm)
        restored_cooldown = self.runtime.get("cooldown_until_bar")
        if isinstance(restored_cooldown, dict):
            self.cooldown_until_bar = dict(restored_cooldown)
        restored_entry_state = self.runtime.get("entry_state")
        if isinstance(restored_entry_state, dict):
            self.entry_state = dict(restored_entry_state)
        self.last_scored_hour = int(self.runtime.get("last_scored_hour", -1) or -1)
        self._persist_runtime()
        self._write_pool_view()

    async def on_bar(self, bar):
        symbol = str(bar.symbol)
        warmup = bool(self.broker.warmup_mode) if hasattr(self.broker, "warmup_mode") else False
        blocked = False
        if not warmup:
            blocked = await self._apply_portfolio_guards(int(bar.timestamp))
            for side in ("long", "short"):
                result = await self._manage_position(symbol, side, bar)
                if self._filled(result):
                    self._append_5m_history(symbol, bar)
                    self._aggregate_5m_bar(bar)
                    self._persist_runtime()
                    self._write_pool_view()
                    return result
        completed = self._aggregate_5m_bar(bar)
        if completed is not None:
            hour = int(completed["timestamp"]) // 3_600_000
            if self._register_completed_hour(str(bar.symbol), hour):
                self._refresh_universe(hour)
                self._refresh_range_states(hour)
        result = None
        if not warmup and not blocked:
            trigger = self._entry_trigger(symbol, bar)
            if isinstance(trigger, dict):
                result = await self._open_trigger(trigger)
        self._append_5m_history(symbol, bar)
        self._persist_runtime()
        self._write_pool_view()
        return result

    def _append_5m_history(self, symbol, bar):
        history = list(self.bars_5m.get(symbol, []))
        history.append(bar)
        self.bars_5m[symbol] = history[-480:]
        self.five_minute_counts[symbol] = int(self.five_minute_counts.get(symbol, 0)) + 1

    def _ema(self, values, period):
        if not values:
            return []
        alpha = 2.0 / (float(max(1, int(period))) + 1.0)
        output = [float(values[0])]
        for value in values[1:]:
            output.append(alpha * float(value) + (1.0 - alpha) * output[-1])
        return output

    def _atr_series(self, bars, period):
        if not bars:
            return []
        values = []
        previous_close = float(bars[0]["close"])
        for row in bars:
            high = float(row["high"])
            low = float(row["low"])
            values.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            previous_close = float(row["close"])
        return self._ema(values, period)

    def _atr(self, bars, period):
        values = self._atr_series(bars, period)
        return float(values[-1]) if values else 0.0

    def _efficiency(self, closes, window):
        sample = [float(value) for value in closes[-(max(1, int(window)) + 1) :]]
        if len(sample) < 2:
            return 0.0
        path = sum(abs(sample[index] - sample[index - 1]) for index in range(1, len(sample)))
        return abs(sample[-1] - sample[0]) / path if path > 0 else 0.0

    def _adx(self, bars, period):
        period = max(2, int(period))
        if len(bars) < period + 2:
            return 0.0
        true_ranges = []
        plus_dm = []
        minus_dm = []
        for index in range(1, len(bars)):
            current = bars[index]
            previous = bars[index - 1]
            up = float(current["high"]) - float(previous["high"])
            down = float(previous["low"]) - float(current["low"])
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
            true_ranges.append(
                max(
                    float(current["high"]) - float(current["low"]),
                    abs(float(current["high"]) - float(previous["close"])),
                    abs(float(current["low"]) - float(previous["close"])),
                )
            )
        dx_values = []
        for end in range(period, len(true_ranges) + 1):
            start = end - period
            tr_sum = sum(true_ranges[start:end])
            if tr_sum <= 0:
                continue
            plus_di = 100.0 * sum(plus_dm[start:end]) / tr_sum
            minus_di = 100.0 * sum(minus_dm[start:end]) / tr_sum
            denominator = plus_di + minus_di
            if denominator > 0:
                dx_values.append(100.0 * abs(plus_di - minus_di) / denominator)
        if not dx_values:
            return 0.0
        return sum(dx_values[-period:]) / float(min(period, len(dx_values)))

    def _finite(self, value):
        try:
            return math.isfinite(float(value))
        except (TypeError, ValueError):
            return False

    def _aggregate_5m_bar(self, bar):
        if str(bar.timeframe).strip().lower() != "5m":
            raise ValueError("仅接受5M已确认K线")
        symbol = str(bar.symbol)
        timestamp = int(bar.timestamp)
        previous = int(self.last_5m_timestamp.get(symbol, -1))
        if previous >= 0 and timestamp <= previous:
            raise ValueError("5M时间戳必须严格递增")
        self.last_5m_timestamp[symbol] = timestamp
        bucket = timestamp // 3_600_000
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
        history = list(self.h1_bars.get(symbol, []))
        history.append(completed)
        self.h1_bars[symbol] = history[-self.h1_history_limit :]
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

    def _completed_h1(self, symbol, completed_hour):
        return [
            dict(row)
            for row in self.h1_bars.get(symbol, [])
            if int(row.get("bucket", int(row.get("timestamp", 0)) // 3_600_000))
            <= int(completed_hour)
        ]

    def _refresh_universe(self, completed_hour):
        ranked = []
        for symbol in self.feed_symbols:
            bars = self._completed_h1(symbol, completed_hour)
            if len(bars) < self.turnover_window:
                continue
            turnover = sum(
                max(0.0, float(row["close"])) * max(0.0, float(row["volume"]))
                for row in bars[-self.turnover_window :]
            )
            if turnover > 0:
                ranked.append((turnover, str(symbol)))
        ranked.sort(key=lambda item: (-float(item[0]), str(item[1])))
        self.candidate_symbols = {symbol for _, symbol in ranked[: self.candidate_count]}
        return ranked[: self.candidate_count]

    def _rolling_vwap(self, bars):
        sample = bars[-self.vwap_window :]
        denominator = sum(max(0.0, float(row["volume"])) for row in sample)
        if denominator <= 0:
            return 0.0
        return sum(
            ((float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0)
            * max(0.0, float(row["volume"]))
            for row in sample
        ) / denominator

    def _range_state_gate(self, metrics):
        return bool(
            self.adx_min <= float(metrics["adx"]) <= self.adx_max
            and float(metrics["efficiency"]) <= self.efficiency_max
            and float(metrics["direction_atr"]) <= self.direction_atr_max
            and self.atr_pct_min <= float(metrics["atr_pct"]) <= self.atr_pct_max
            and int(metrics["vwap_crosses"]) >= self.vwap_crosses_min
            and float(metrics["extension_atr"]) <= self.extension_atr_max
        )

    def _score_range_state(self, symbol, completed_hour):
        if symbol not in self.candidate_symbols:
            return None
        bars = self._completed_h1(symbol, completed_hour)
        required = max(
            self.min_h1_bars,
            self.atr_window + 2,
            self.adx_window + 2,
            self.efficiency_window + 1,
            self.direction_window + 1,
            self.vwap_window,
        )
        if len(bars) < required:
            return None
        closes = [float(row["close"]) for row in bars]
        close = closes[-1]
        atr_value = self._atr(bars, self.atr_window)
        if close <= 0 or atr_value <= 0:
            return None
        vwap = self._rolling_vwap(bars)
        if vwap <= 0:
            return None
        signs = []
        for value in closes[-self.vwap_window :]:
            signs.append(1 if value > vwap else -1 if value < vwap else 0)
        crosses = sum(
            1
            for index in range(1, len(signs))
            if signs[index] != 0 and signs[index - 1] != 0 and signs[index] != signs[index - 1]
        )
        metrics = {
            "adx": self._adx(bars, self.adx_window),
            "efficiency": self._efficiency(closes, self.efficiency_window),
            "direction_atr": abs(closes[-1] - closes[-1 - self.direction_window]) / atr_value,
            "atr_pct": 100.0 * atr_value / close,
            "vwap_crosses": crosses,
            "extension_atr": abs(close - vwap) / atr_value,
        }
        if not self._range_state_gate(metrics):
            return None
        return {"symbol": str(symbol), "vwap": float(vwap), **metrics}

    def _refresh_range_states(self, completed_hour):
        latest = {}
        active = set()
        for symbol in sorted(self.candidate_symbols):
            row = self._score_range_state(symbol, completed_hour)
            if not isinstance(row, dict):
                self.state_confirm.pop(symbol, None)
                continue
            confirmed = int(self.state_confirm.get(symbol, 0)) + 1
            self.state_confirm[symbol] = confirmed
            row["confirmed"] = confirmed
            row["openable"] = confirmed >= self.state_confirmations
            latest[symbol] = row
            active.add(symbol)
        for symbol in list(self.state_confirm):
            if symbol not in active:
                self.state_confirm.pop(symbol, None)
        self.latest_states = latest
        return latest

    def _register_completed_hour(self, symbol, completed_hour):
        key = str(int(completed_hour))
        seen = set(self.hour_seen.get(key, []))
        seen.add(str(symbol))
        self.hour_seen[key] = sorted(seen)
        eligible = {
            item for item in self.feed_symbols if len(self.h1_bars.get(item, [])) >= self.min_h1_bars
        }
        required = max(1, (len(eligible) * 3 + 4) // 5) if eligible else 1
        if len(eligible.intersection(seen)) < required or int(completed_hour) <= self.last_scored_hour:
            return False
        self.last_scored_hour = int(completed_hour)
        return True

    def _bar_row(self, bar):
        if isinstance(bar, dict):
            return {
                "timestamp": int(bar.get("timestamp", 0)),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": float(bar["volume"]),
            }
        return {
            "timestamp": int(bar.timestamp),
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": float(bar.volume),
        }

    def _median(self, values):
        numbers = sorted(float(value) for value in values if self._finite(value))
        if not numbers:
            return 0.0
        middle = len(numbers) // 2
        if len(numbers) % 2:
            return numbers[middle]
        return (numbers[middle - 1] + numbers[middle]) / 2.0

    def _vwap_snapshot(self, symbol):
        history = list(self.bars_5m.get(symbol, []))
        if len(history) < self.vwap_5m_window:
            return None
        rows = [self._bar_row(item) for item in history[-self.vwap_5m_window :]]
        volumes = [max(0.0, float(row["volume"])) for row in rows]
        denominator = sum(volumes)
        if denominator <= 0:
            return None
        typical = [
            (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3.0
            for row in rows
        ]
        vwap = sum(typical[index] * volumes[index] for index in range(len(rows))) / denominator
        residuals = [value - vwap for value in typical]
        mean_residual = sum(residuals) / float(len(residuals))
        variance = sum((value - mean_residual) ** 2 for value in residuals) / float(
            len(residuals)
        )
        residual_std = math.sqrt(variance)
        if residual_std <= 0:
            return None
        return {
            "sample_count": len(rows),
            "vwap": float(vwap),
            "residual_std": float(residual_std),
            "previous_typical": float(typical[-1]),
            "previous_close": float(rows[-1]["close"]),
            "previous_z": float((typical[-1] - vwap) / residual_std),
        }

    def _entry_trigger(self, symbol, bar):
        state = self.latest_states.get(symbol)
        if not isinstance(state, dict) or not bool(state.get("openable")):
            return None
        snapshot = self._vwap_snapshot(symbol)
        if not isinstance(snapshot, dict):
            return None
        current = self._bar_row(bar)
        current_typical = (
            float(current["high"]) + float(current["low"]) + float(current["close"])
        ) / 3.0
        current_z = (current_typical - float(snapshot["vwap"])) / float(
            snapshot["residual_std"]
        )
        previous_z = float(snapshot["previous_z"])
        side = None
        if (
            previous_z <= -self.z_entry
            and current_z - previous_z >= self.z_recovery_min
            and float(current["close"]) > float(snapshot["previous_close"])
        ):
            side = "long"
        elif (
            previous_z >= self.z_entry
            and previous_z - current_z >= self.z_recovery_min
            and float(current["close"]) < float(snapshot["previous_close"])
        ):
            side = "short"
        if side is None:
            return None
        current_count = int(self.five_minute_counts.get(symbol, 0))
        cooldown_key = str(symbol) + "|" + side
        if current_count < int(self.cooldown_until_bar.get(cooldown_key, -1)):
            return None
        history_rows = [self._bar_row(item) for item in self.bars_5m.get(symbol, [])]
        atr_value = self._atr(history_rows[-(self.atr_window + 2) :] + [current], self.atr_window)
        if atr_value <= 0:
            return None
        volume_sample = [float(row["volume"]) for row in history_rows[-self.volume_window :]]
        volume_median = self._median(volume_sample)
        if volume_median <= 0:
            return None
        volume_ratio = float(current["volume"]) / volume_median
        if volume_ratio < self.volume_ratio_min or volume_ratio > self.volume_ratio_max:
            return None
        bar_range_atr = (float(current["high"]) - float(current["low"])) / atr_value
        if bar_range_atr > self.max_bar_range_atr:
            return None
        entry = float(current["close"])
        recent_rows = history_rows[-3:] + [current]
        if side == "long":
            extreme = min(float(row["low"]) for row in recent_rows)
            raw_distance = entry - (extreme - atr_value * self.extreme_stop_buffer_atr)
        else:
            extreme = max(float(row["high"]) for row in recent_rows)
            raw_distance = (extreme + atr_value * self.extreme_stop_buffer_atr) - entry
        minimum_distance = entry * (2.0 * self.round_trip_cost_bps / 10_000.0)
        stop_distance = min(
            max(raw_distance, minimum_distance),
            atr_value * self.initial_stop_atr_mult,
        )
        if stop_distance <= 0:
            return None
        target_by_r = (
            entry + stop_distance * self.hard_take_profit_r
            if side == "long"
            else entry - stop_distance * self.hard_take_profit_r
        )
        vwap = float(snapshot["vwap"])
        target = min(vwap, target_by_r) if side == "long" else max(vwap, target_by_r)
        target_distance = target - entry if side == "long" else entry - target
        target_distance_bps = 10_000.0 * target_distance / entry
        if target_distance_bps < self.round_trip_cost_bps * self.cost_edge_multiple:
            return None
        stop = entry - stop_distance if side == "long" else entry + stop_distance
        return {
            "symbol": str(symbol),
            "side": side,
            "entry_price": entry,
            "stop_price": float(stop),
            "take_profit_price": float(target),
            "target_vwap": vwap,
            "initial_risk_price": float(stop_distance),
            "atr": float(atr_value),
            "previous_z": previous_z,
            "current_z": float(current_z),
            "volume_ratio": float(volume_ratio),
            "bar_range_atr": float(bar_range_atr),
            "vwap_distance_bps": float(target_distance_bps),
        }

    def _order_plan(self, equity, entry, stop, side):
        equity = float(equity)
        entry = float(entry)
        stop = float(stop)
        if equity <= 0 or entry <= 0 or side not in ("long", "short"):
            return None
        positions = [row for row in self.entry_state.values() if isinstance(row, dict)]
        if len(positions) >= self.max_positions:
            return None
        if sum(1 for row in positions if str(row.get("side")) == side) >= self.same_direction_cap:
            return None
        stop_pct = abs(entry - stop) / entry
        if stop_pct <= 0:
            return None
        risk_budget = equity * self.risk_per_trade_pct
        current_notional = sum(max(0.0, float(row.get("notional_usdt", 0.0))) for row in positions)
        remaining = max(0.0, equity * self.max_total_notional_equity_pct - current_notional)
        notional = min(risk_budget / stop_pct, self.max_position_notional_usdt, remaining)
        if notional < self.min_order_notional_usdt:
            return None
        return {
            "side": side,
            "notional_usdt": float(notional),
            "risk_usdt": float(notional * stop_pct),
            "stop_distance_pct": float(stop_pct),
        }

    async def _open_trigger(self, trigger):
        plan = self._order_plan(
            self._equity(),
            float(trigger["entry_price"]),
            float(trigger["stop_price"]),
            str(trigger["side"]),
        )
        if not isinstance(plan, dict):
            return None
        result = await self.open_contract(
            str(trigger["symbol"]),
            str(trigger["side"]),
            float(plan["notional_usdt"]),
            leverage=self.leverage,
            price=float(trigger["entry_price"]),
        )
        if not self._filled(result):
            return result
        symbol = str(trigger["symbol"])
        side = str(trigger["side"])
        entry = float(trigger["entry_price"])
        key = symbol + "|" + side
        self.entry_state[key] = {
            "symbol": symbol,
            "side": side,
            "entry_price": entry,
            "initial_risk_price": float(trigger["initial_risk_price"]),
            "stop_price": float(trigger["stop_price"]),
            "take_profit_price": float(trigger["take_profit_price"]),
            "target_vwap": float(trigger["target_vwap"]),
            "highest": entry,
            "lowest": entry,
            "entry_bar_count": int(self.five_minute_counts.get(symbol, 0)),
            "atr": float(trigger["atr"]),
            "notional_usdt": float(plan["notional_usdt"]),
        }
        self._record_event("position_open", symbol, side=side, price=entry)
        return result

    async def _manage_position(self, symbol, side, bar):
        key = str(symbol) + "|" + str(side)
        state = self.entry_state.get(key)
        if not isinstance(state, dict):
            return None
        position = await self.get_contract_position(symbol, side)
        if not position:
            self.entry_state.pop(key, None)
            return None
        current = self._bar_row(bar)
        entry = float(state["entry_price"])
        risk = max(1e-12, float(state["initial_risk_price"]))
        stop = float(state["stop_price"])
        take = float(state["take_profit_price"])
        high = float(current["high"])
        low = float(current["low"])
        close = float(current["close"])
        count = int(self.five_minute_counts.get(symbol, 0))
        bars_held = max(0, count - int(state.get("entry_bar_count", count)))
        stop_hit = low <= stop if side == "long" else high >= stop
        take_hit = high >= take if side == "long" else low <= take
        if stop_hit:
            return await self._close_position(symbol, side, stop, "stop_loss_or_profit_lock")
        if take_hit:
            return await self._close_position(
                symbol, side, take, "fixed_or_vwap_take_profit"
            )
        range_state = self.latest_states.get(symbol)
        if isinstance(range_state, dict) and (
            float(range_state.get("adx", 0.0)) >= self.regime_break_adx
            or float(range_state.get("efficiency", 0.0)) >= self.regime_break_efficiency
            or float(range_state.get("direction_atr", 0.0)) >= self.regime_break_direction_atr
        ):
            return await self._close_position(symbol, side, close, "range_state_broken")
        if bars_held >= self.max_holding_bars:
            return await self._close_position(symbol, side, close, "time_exit_120m")
        state["highest"] = max(float(state.get("highest", entry)), high)
        state["lowest"] = min(float(state.get("lowest", entry)), low)
        favorable = (
            float(state["highest"]) - entry
            if side == "long"
            else entry - float(state["lowest"])
        )
        peak_r = max(0.0, favorable / risk)
        cost_buffer = entry * self.round_trip_cost_bps / 10_000.0
        if peak_r >= self.break_even_at_r:
            stop = max(stop, entry + cost_buffer) if side == "long" else min(
                stop, entry - cost_buffer
            )
        if peak_r >= self.profit_trailing_start_r:
            atr_value = max(0.0, float(state.get("atr", 0.0)))
            if side == "long":
                peak_lock = entry + favorable * (1.0 - self.profit_peak_pullback_pct)
                atr_lock = float(state["highest"]) - atr_value * self.profit_atr_stop_mult
                stop = max(stop, peak_lock, atr_lock)
            else:
                peak_lock = entry - favorable * (1.0 - self.profit_peak_pullback_pct)
                atr_lock = float(state["lowest"]) + atr_value * self.profit_atr_stop_mult
                stop = min(stop, peak_lock, atr_lock)
        state["stop_price"] = float(stop)
        state["peak_r"] = float(peak_r)
        state["bars_held"] = int(bars_held)
        return None

    async def _close_position(self, symbol, side, price, reason):
        key = str(symbol) + "|" + str(side)
        result = await self.close_contract(symbol, side, ratio=1.0, price=float(price))
        if not self._filled(result):
            return result
        self.entry_state.pop(key, None)
        self.cooldown_until_bar[key] = int(self.five_minute_counts.get(symbol, 0)) + self.cooldown_bars
        self.runtime["last_exit_reason"] = str(reason)
        self._record_closed_result(
            float(result.get("realized_pnl", 0.0) or 0.0),
            int(self.last_5m_timestamp.get(symbol, 0) or 0),
        )
        self._record_event("position_close", str(symbol), side=str(side), price=float(price), reason=str(reason))
        if isinstance(result, dict):
            result["exit_reason"] = str(reason)
        return result

    async def _apply_portfolio_guards(self, now_ms):
        if str(self.runtime.get("terminal_reason") or ""):
            return True
        if int(now_ms) < int(self.runtime.get("pause_until_ms", 0) or 0):
            self.runtime["last_guard_reason"] = "loss_streak_pause"
            return True
        equity = self._equity()
        day = int(now_ms) // 86_400_000
        if int(self.runtime.get("day_number", -1)) != day:
            self.runtime["day_number"] = day
            self.runtime["day_start_equity"] = equity
            self.runtime["day_peak_equity"] = equity
            self.runtime["daily_profit_floor"] = 0.0
            self.runtime["pause_until_day"] = -1
        day_start = float(self.runtime.get("day_start_equity", equity) or equity)
        if equity <= self.terminal_floor_equity:
            await self._close_all_positions("equity_floor_88")
            self.runtime["terminal_reason"] = "equity_floor_88"
            self.runtime["last_guard_reason"] = "equity_floor_88"
            return True
        peak = max(float(self.runtime.get("day_peak_equity", day_start) or day_start), equity)
        self.runtime["day_peak_equity"] = peak
        if peak >= day_start * (1.0 + self.daily_lock_activation_pct):
            floor = day_start + (peak - day_start) * self.daily_lock_fraction
            self.runtime["daily_profit_floor"] = max(
                float(self.runtime.get("daily_profit_floor", 0.0) or 0.0), floor
            )
        if equity <= day_start * (1.0 - self.daily_loss_pct):
            self.runtime["pause_until_day"] = day + 1
            self.runtime["last_guard_reason"] = "daily_loss_pause"
            return True
        profit_floor = float(self.runtime.get("daily_profit_floor", 0.0) or 0.0)
        if profit_floor > 0 and equity < profit_floor:
            await self._close_all_positions("daily_profit_floor")
            self.runtime["pause_until_day"] = day + 1
            self.runtime["last_guard_reason"] = "daily_profit_floor"
            return True
        return int(self.runtime.get("pause_until_day", -1)) > day

    def _record_closed_result(self, pnl, now_ms):
        if float(pnl) < 0:
            streak = int(self.runtime.get("loss_streak", 0) or 0) + 1
            if streak >= self.loss_cooldown_count:
                self.runtime["pause_until_ms"] = int(now_ms) + self.loss_cooldown_ms
                streak = 0
            self.runtime["loss_streak"] = streak
        else:
            self.runtime["loss_streak"] = 0

    async def _close_all_positions(self, reason):
        for key, state in list(self.entry_state.items()):
            if not isinstance(state, dict) or "|" not in key:
                continue
            symbol, side = key.rsplit("|", 1)
            price = float(state.get("entry_price", 0.0) or 0.0)
            result = await self.close_contract(symbol, side, ratio=1.0, price=price)
            if self._filled(result):
                self.entry_state.pop(key, None)
                self._record_event("position_close", symbol, side=side, price=price, reason=str(reason))

    def _equity(self):
        if hasattr(self.broker, "equity") and self._finite(self.broker.equity):
            return float(self.broker.equity)
        if hasattr(self.broker, "balance") and self._finite(self.broker.balance):
            return float(self.broker.balance)
        return 100.0

    def _filled(self, result):
        return str((result or {}).get("status") or "").lower() in {
            "filled",
            "submitted",
            "accepted",
        }

    def _record_event(self, kind, symbol, **payload):
        events = list(self.runtime.get("events", []))
        event = {
            "event_id": str(kind) + "|" + str(symbol) + "|" + str(len(events) + 1),
            "kind": str(kind),
            "symbol": str(symbol),
        }
        event.update(payload)
        events.append(event)
        self.runtime["events"] = events[-self.event_limit :]

    def _persist_runtime(self):
        self.runtime["candidate_symbols"] = sorted(self.candidate_symbols)
        self.runtime["state_confirm"] = dict(self.state_confirm)
        self.runtime["cooldown_until_bar"] = dict(self.cooldown_until_bar)
        self.runtime["entry_state"] = dict(self.entry_state)
        self.runtime["last_scored_hour"] = int(self.last_scored_hour)
        self.state.positions[self.runtime_key] = self.runtime

    def _write_pool_view(self):
        members = [dict(row) for row in self.latest_states.values() if bool(row.get("openable"))]
        near = [dict(row) for row in self.latest_states.values() if not bool(row.get("openable"))]
        self.state.positions[self.pool_view_key] = {
            "schema_version": 3,
            "mode": "high_frequency_vwap_reversion",
            "status": "ready" if self.last_scored_hour >= 0 else "warming",
            "selection_summary": "完成1H震荡状态 + 5M VWAP偏离回归",
            "members": members,
            "candidates_near": near,
            "positions": [],
            "events": list(self.runtime.get("events", [])),
        }

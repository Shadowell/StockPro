import unittest
from pathlib import Path

from app.services.strategy_runtime_service import (
    DEFAULT_RUNTIME_LIMITS,
    StrategyRuntimeService,
    validate_strategy_python,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = REPO_ROOT / "strategies"
BOARD_T_FILES = [
    "board_first_weak_to_strong.py",
    "board_consecutive_relay.py",
    "board_broken_reclaim.py",
    "board_space_avoid_yizi.py",
    "board_first_volume.py",
    "board_high_ladder.py",
    "board_limit_down_bounce.py",
    "board_seal_quality.py",
    "t_gap_down_recovery.py",
    "t_gap_up_hold.py",
    "t_lower_shadow.py",
    "t_close_strength.py",
    "t_amplitude_reversion.py",
    "t_volume_yang.py",
    "t_tight_breakout.py",
    "t_overnight_follow.py",
    "daily_reversal_3d.py",
    "daily_momentum_20d.py",
    "daily_ma_breakout.py",
    "daily_low_vol_defense.py",
]


def _bar(open_px, high, low, close, volume=1_000_000):
    return {"open": open_px, "high": high, "low": low, "close": close, "volume": volume, "turnover": close * volume}


def _series(values):
    return {
        "open": [item["open"] for item in values],
        "high": [item["high"] for item in values],
        "low": [item["low"] for item in values],
        "close": [item["close"] for item in values],
        "volume": [item["volume"] for item in values],
        "turnover": [item["turnover"] for item in values],
    }


class BoardTStrategyValidationTests(unittest.TestCase):
    def test_twenty_preset_files_exist_and_pass_strategy_api(self):
        self.assertEqual(len(BOARD_T_FILES), 20)
        for filename in BOARD_T_FILES:
            code = (STRATEGIES_DIR / filename).read_text(encoding="utf-8")
            result = validate_strategy_python(code)
            self.assertTrue(result["valid"], f"{filename}: {result['issues']}")
            self.assertIn("initialize", code)
            self.assertIn("handle_data", code)
            self.assertIn("run_daily", code)


class BoardTStrategyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.service = StrategyRuntimeService.__new__(StrategyRuntimeService)
        self.service.worker_path = Path(__file__).resolve().parents[1] / "app" / "services" / "strategy_runtime_worker.py"
        self.limits = {**DEFAULT_RUNTIME_LIMITS, "wall_seconds": 2.0, "memory_mb": 256, "max_intents": 200, "max_records": 200}

    def payload(self, code: str):
        def walk(start, pattern, volume_base):
            price = start
            rows = []
            for index, move in enumerate(pattern):
                close = round(price * (1 + move), 4)
                high = round(max(price, close) * 1.01, 4)
                low = round(min(price, close) * 0.99, 4)
                open_px = round((price + close) / 2, 4)
                volume = volume_base * (2 if abs(move) >= 0.09 else 1)
                rows.append(_bar(open_px, high, low, close, volume))
                price = close
            return rows

        aaa = walk(10.0, [0.01, 0.10, -0.03, 0.01, 0.02] + [0.01] * 20, 800_000)
        bbb = walk(20.0, [-0.01, -0.095, 0.05, 0.01, 0.02] + [-0.005] * 20, 700_000)
        ccc = walk(8.0, [0.0, 0.005, 0.006, 0.055, -0.01] + [0.002] * 20, 500_000)
        dates = [f"2025-01-{str(index + 2).zfill(2)}" for index in range(25)]
        events = []
        for index, trade_date in enumerate(dates):
            events.append(
                {
                    "trade_date": trade_date,
                    "simulated_at": f"{trade_date}T15:00:00+08:00",
                    "available_at": f"{trade_date}T15:00:00+08:00",
                    "previous_date": dates[index - 1] if index else None,
                    "bars": {"AAA": aaa[index], "BBB": bbb[index], "CCC": ccc[index]},
                    "factors": {
                        "momentum_20d": {"AAA": 0.12, "BBB": -0.08, "CCC": 0.03},
                        "reversal_3d": {"AAA": -0.02, "BBB": 0.06, "CCC": -0.01},
                        "volatility_20d": {"AAA": 0.02, "BBB": 0.05, "CCC": 0.01},
                    },
                }
            )
        return {
            "code": code,
            "strategy_api_version": "stockpro.v1",
            "parameters": {},
            "symbols": ["AAA", "BBB", "CCC"],
            "events": events,
            "series": {"AAA": _series(aaa), "BBB": _series(bbb), "CCC": _series(ccc)},
            "limits": self.limits,
            "dataset_snapshot_id": 10,
            "factor_snapshot_id": 4,
            "knowledge_cutoff_at": "2025-01-08T17:30:00+08:00",
        }

    def test_each_strategy_emits_intents_on_synthetic_daily_bars(self):
        for filename in BOARD_T_FILES:
            code = (STRATEGIES_DIR / filename).read_text(encoding="utf-8")
            result = self.service._run_worker(self.payload(code), self.limits)
            self.assertTrue(result.get("success"), f"{filename}: {result}")
            self.assertGreater(len(result.get("intents") or []), 0, filename)
            self.assertTrue(all(item["intent_type"] == "order_target_percent" for item in result["intents"]))


if __name__ == "__main__":
    unittest.main()

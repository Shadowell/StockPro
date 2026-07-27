import unittest
from pathlib import Path

from app.services.strategy_runtime_service import (
    DEFAULT_RUNTIME_LIMITS,
    StrategyRuntimeService,
    normalize_runtime_limits,
    validate_strategy_python,
)


VALID_CODE = '''def initialize(context):
    context.security = "SH_600000"
    set_option("avoid_future_data", True)

def handle_data(context, data):
    closes = history(context.security, 2, "1d", "close")
    if len(closes) == 2:
        order_target_percent(context.security, 1.0)
        record(last=closes[-1])
'''


class StrategyValidationTests(unittest.TestCase):
    def test_minimal_lifecycle_is_valid_and_api_pinned(self):
        result = validate_strategy_python(VALID_CODE)

        self.assertTrue(result["valid"])
        self.assertEqual(result["api_version"], "stockpro.v1")
        self.assertIn("history", result["dependencies"])

    def test_missing_lifecycle_has_stable_issue_code(self):
        result = validate_strategy_python("def initialize(context):\n    pass\n")

        self.assertFalse(result["valid"])
        self.assertIn("MISSING_LIFECYCLE", {item["code"] for item in result["issues"]})

    def test_invalid_signature_is_rejected(self):
        result = validate_strategy_python("def initialize():\n    pass\ndef handle_data(data):\n    pass\n")

        self.assertIn("INVALID_SIGNATURE", {item["code"] for item in result["issues"]})

    def test_imports_network_database_and_files_are_rejected(self):
        examples = [
            "import os\ndef initialize(context): pass\ndef handle_data(context,data): pass",
            "def initialize(context): open('/tmp/x')\ndef handle_data(context,data): pass",
            "def initialize(context): requests.get('x')\ndef handle_data(context,data): pass",
            "def initialize(context): psycopg.connect('x')\ndef handle_data(context,data): pass",
        ]

        for code in examples:
            with self.subTest(code=code):
                result = validate_strategy_python(code)
                self.assertFalse(result["valid"])
                self.assertIn("FORBIDDEN_CAPABILITY", {item["code"] for item in result["issues"]})

    def test_dunder_introspection_is_rejected(self):
        result = validate_strategy_python("def initialize(context): context.__class__\ndef handle_data(context,data): pass")

        self.assertIn("FORBIDDEN_CAPABILITY", {item["code"] for item in result["issues"]})

    def test_top_level_execution_is_rejected(self):
        result = validate_strategy_python("x = history('A', 1)\ndef initialize(context): pass\ndef handle_data(context,data): pass")

        self.assertIn("TOP_LEVEL_EXECUTION", {item["code"] for item in result["issues"]})

    def test_explicit_date_data_access_is_rejected(self):
        code = "def initialize(context): pass\ndef handle_data(context,data): get_price('A', end_date='2099-01-01')"
        result = validate_strategy_python(code)

        self.assertIn("EXPLICIT_DATE_ACCESS_FORBIDDEN", {item["code"] for item in result["issues"]})

    def test_unknown_function_api_is_rejected_before_execution(self):
        code = "def initialize(context): pass\ndef handle_data(context,data): send_order('SH_600000')"

        result = validate_strategy_python(code)

        self.assertIn("UNSUPPORTED_API", {item["code"] for item in result["issues"]})

    def test_user_defined_callback_is_not_mistaken_for_platform_api(self):
        code = '''def initialize(context):
    run_daily(rebalance)
def rebalance(context):
    record(kind="scheduled")
def handle_data(context, data):
    pass
'''

        self.assertTrue(validate_strategy_python(code)["valid"])

    def test_runtime_limits_can_only_be_reduced_inside_platform_bounds(self):
        limits = normalize_runtime_limits({"wall_seconds": 1.0, "max_records": 50})

        self.assertEqual(limits["wall_seconds"], 1.0)
        self.assertEqual(limits["max_records"], 50)
        self.assertEqual(limits["memory_mb"], DEFAULT_RUNTIME_LIMITS["memory_mb"])

    def test_runtime_limit_expansion_and_unknown_keys_are_rejected(self):
        with self.assertRaises(ValueError):
            normalize_runtime_limits({"memory_mb": DEFAULT_RUNTIME_LIMITS["memory_mb"] + 1})
        with self.assertRaises(ValueError):
            normalize_runtime_limits({"network_requests": 1})

    def test_wall_clock_classmethods_are_rejected(self):
        code = "def initialize(context): pass\ndef handle_data(context,data): context.current_dt.now()"

        result = validate_strategy_python(code)

        self.assertIn("WALL_CLOCK_ACCESS_FORBIDDEN", {item["code"] for item in result["issues"]})


class StrategyWorkerTests(unittest.TestCase):
    def setUp(self):
        self.service = StrategyRuntimeService.__new__(StrategyRuntimeService)
        self.service.worker_path = Path(__file__).resolve().parents[1] / "app" / "services" / "strategy_runtime_worker.py"
        self.limits = {**DEFAULT_RUNTIME_LIMITS, "wall_seconds": 1.5, "memory_mb": 256}

    def payload(self, code=VALID_CODE):
        return {
            "code": code,
            "strategy_api_version": "stockpro.v1",
            "parameters": {},
            "symbols": ["SH_600000"],
            "events": [
                {"trade_date": "2025-01-01", "simulated_at": "2025-01-01T15:00:00+08:00", "available_at": "2025-01-01T15:00:00+08:00", "previous_date": None, "bars": {"SH_600000": {"close": 10}}, "factors": {}},
                {"trade_date": "2025-01-02", "simulated_at": "2025-01-02T15:00:00+08:00", "available_at": "2025-01-02T15:00:00+08:00", "previous_date": "2025-01-01", "bars": {"SH_600000": {"close": 11}}, "factors": {}},
            ],
            "series": {"SH_600000": {"close": [10, 11]}},
            "limits": self.limits,
            "dataset_snapshot_id": 1,
            "factor_snapshot_id": None,
            "knowledge_cutoff_at": "2025-01-02T17:30:00+08:00",
        }

    def test_worker_is_deterministic_and_never_reads_future_history(self):
        first = self.service._run_worker(self.payload(), self.limits)
        second = self.service._run_worker(self.payload(), self.limits)

        self.assertTrue(first["success"])
        self.assertEqual(first["intents"], second["intents"])
        self.assertEqual(first["records"], second["records"])
        self.assertEqual(first["records"][0]["payload"]["last"], 11)
        self.assertEqual(first["intents"][0]["simulated_at"], first["intents"][0]["available_at"])

    def test_backtest_and_paper_payload_share_one_worker_semantics(self):
        backtest = self.payload()
        paper = self.payload()
        backtest["mode"] = "backtest"
        paper["mode"] = "paper_replay"

        left = self.service._run_worker(backtest, self.limits)
        right = self.service._run_worker(paper, self.limits)

        self.assertEqual(left["intents"], right["intents"])
        self.assertEqual(left["records"], right["records"])

    def test_non_terminating_strategy_is_killed_by_wall_limit(self):
        code = "def initialize(context): pass\ndef handle_data(context,data):\n    while True:\n        pass"
        limits = {**self.limits, "wall_seconds": 0.2}
        payload = self.payload(code)
        payload["limits"] = limits

        result = self.service._run_worker(payload, limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "WALL_TIME_LIMIT")
        self.assertTrue(result["resource_failure"])

    def test_record_flood_is_stopped_at_versioned_limit(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    for index in range(20):
        record(value=index)
'''
        limits = {**self.limits, "max_records": 5}
        payload = self.payload(code)
        payload["limits"] = limits

        result = self.service._run_worker(payload, limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "RECORD_LIMIT_EXCEEDED")
        self.assertTrue(result["resource_failure"])

    def test_scheduled_callback_uses_same_simulated_clock(self):
        code = '''def initialize(context):
    run_daily(rebalance, time="open")
def rebalance(context):
    record(kind="scheduled")
def handle_data(context, data):
    pass
'''

        result = self.service._run_worker(self.payload(code), self.limits)

        self.assertTrue(result["success"])
        self.assertEqual(len(result["records"]), 2)
        self.assertEqual(result["records"][0]["simulated_at"], "2025-01-01T15:00:00+08:00")

    def test_cost_and_slippage_accept_keyword_configuration(self):
        code = '''def initialize(context):
    set_order_cost(open_tax=0.0, close_tax=0.0005, commission=0.0003)
    set_slippage(fixed=0.01)
def handle_data(context, data):
    pass
'''

        result = self.service._run_worker(self.payload(code), self.limits)

        self.assertTrue(result["success"])
        self.assertEqual(result["options"]["order_cost"]["close_tax"], 0.0005)
        self.assertEqual(result["options"]["slippage"]["fixed"], 0.01)

    def test_context_state_must_remain_json_serializable(self):
        code = '''def initialize(context):
    context.bad_state = set([1, 2])
def handle_data(context, data):
    pass
'''

        result = self.service._run_worker(self.payload(code), self.limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "CONTEXT_NOT_SERIALIZABLE")

    def test_intent_flood_is_a_resource_failure(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    order("SH_600000", 100)
'''
        limits = {**self.limits, "max_intents": 1}
        payload = self.payload(code)
        payload["limits"] = limits

        result = self.service._run_worker(payload, limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INTENT_LIMIT_EXCEEDED")
        self.assertTrue(result["resource_failure"])

    def test_log_limit_is_a_resource_failure(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    log.info("x" * 800)
'''
        limits = {**self.limits, "log_bytes": 1024}
        payload = self.payload(code)
        payload["events"] = payload["events"] * 2
        payload["limits"] = limits

        result = self.service._run_worker(payload, limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "LOG_LIMIT_EXCEEDED")
        self.assertTrue(result["resource_failure"])

    def test_all_order_forms_emit_normalized_timestamps(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    if context.previous_date:
        order("SH_600000", 100)
        order_value("SH_600000", 1000)
        order_target("SH_600000", 200)
        order_target_value("SH_600000", 2000)
        order_target_percent("SH_600000", 0.2)
'''

        result = self.service._run_worker(self.payload(code), self.limits)

        self.assertTrue(result["success"])
        self.assertEqual([item["intent_type"] for item in result["intents"]], [
            "order", "order_value", "order_target", "order_target_value", "order_target_percent",
        ])
        self.assertTrue(all(item["simulated_at"] == item["available_at"] for item in result["intents"]))

    def test_factor_bindings_are_snapshot_scoped(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    values = get_factor_values("momentum_20d")
    info = get_factor_snapshot_info()
    record(value=values["SH_600000"], snapshot=info["factor_snapshot_id"])
'''
        payload = self.payload(code)
        payload["factor_snapshot_id"] = 3
        payload["events"][0]["factors"] = {"momentum_20d": {"SH_600000": 0.25}}
        payload["events"][1]["factors"] = {"momentum_20d": {"SH_600000": 0.5}}

        result = self.service._run_worker(payload, self.limits)

        self.assertTrue(result["success"])
        self.assertEqual(result["records"][0]["payload"], {"value": 0.25, "snapshot": 3})
        self.assertEqual(result["records"][1]["payload"], {"value": 0.5, "snapshot": 3})

    def test_non_serializable_record_is_rejected(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    record(values=set([1, 2]))
'''

        result = self.service._run_worker(self.payload(code), self.limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "RECORD_NOT_SERIALIZABLE")

    def test_output_quota_returns_a_resource_failure(self):
        code = '''def initialize(context):
    pass
def handle_data(context, data):
    for index in range(100):
        record(index=index, payload="x" * 50)
'''
        limits = {**self.limits, "output_bytes": 1024, "max_records": 500}
        payload = self.payload(code)
        payload["limits"] = limits

        result = self.service._run_worker(payload, limits)

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "OUTPUT_LIMIT_EXCEEDED")
        self.assertTrue(result["resource_failure"])


class FactorAvailabilityTests(unittest.TestCase):
    class FactorService:
        def factor_snapshot_values(self, snapshot_id, limit):
            return {
                "snapshot_id": snapshot_id,
                "dataset_snapshot_id": 9,
                "manifest_hash": "factor-hash",
                "knowledge_cutoff_at": "2025-01-02T17:30:00+08:00",
                "items": [
                    {"trade_date": "2025-01-02", "available_at": "2025-01-02T17:30:00+08:00", "factor_code": "momentum_20d", "symbol": "SH_600000", "processed_value": 0.5},
                ],
            }

    def setUp(self):
        self.service = StrategyRuntimeService.__new__(StrategyRuntimeService)
        self.service.factor_service = self.FactorService()

    def test_factor_values_are_hidden_before_snapshot_cutoff_and_forward_filled_after_it(self):
        events = [
            {"trade_date": "2025-01-02", "simulated_at": "2025-01-02T15:00:00+08:00", "factors": {}},
            {"trade_date": "2025-01-03", "simulated_at": "2025-01-03T15:00:00+08:00", "factors": {}},
        ]

        info = self.service._attach_factor_values(events, 3, "2025-01-03T18:00:00+08:00")

        self.assertEqual(events[0]["factors"], {})
        self.assertEqual(events[1]["factors"]["momentum_20d"]["SH_600000"], 0.5)
        self.assertEqual(info["factor_snapshot_id"], 3)

    def test_factor_snapshot_seal_time_does_not_override_fact_availability(self):
        events = [{"trade_date": "2025-01-03", "simulated_at": "2025-01-03T15:00:00+08:00", "factors": {}}]

        self.service._attach_factor_values(events, 3, "2025-01-02T16:00:00+08:00")

        self.assertEqual(events[0]["factors"]["momentum_20d"]["SH_600000"], 0.5)


if __name__ == "__main__":
    unittest.main()

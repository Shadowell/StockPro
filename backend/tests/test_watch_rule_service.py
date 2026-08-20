import unittest

from app.services.watch_rule_service import WatchRuleService


class WatchRuleServiceTests(unittest.TestCase):
    def test_price_rule_filters_target_symbols_and_all_conditions(self):
        rule = {
            "rule_type": "price",
            "config": {
                "symbols": ["600519.SH"],
                "logic": "all",
                "conditions": [
                    {"field": "price", "operator": "gte", "value": 1500},
                    {"field": "change_percent", "operator": "gt", "value": 1},
                ],
            },
        }
        rows = [
            {"code": "600519.SH", "price": 1510, "change_percent": 2},
            {"code": "000001.SZ", "price": 12, "change_percent": 3},
        ]
        self.assertEqual(["600519.SH"], [item["code"] for item in WatchRuleService.match_rows(rule, rows)])

    def test_abnormal_rule_supports_any_logic(self):
        rule = {
            "rule_type": "abnormal",
            "config": {
                "symbols": [],
                "logic": "any",
                "conditions": [
                    {"field": "amplitude", "operator": "gte", "value": 10},
                    {"field": "volume_ratio", "operator": "gte", "value": 3},
                ],
            },
        }
        rows = [
            {"code": "600000.SH", "amplitude": 11, "volume_ratio": 1},
            {"code": "000001.SZ", "amplitude": 2, "volume_ratio": 2},
        ]
        self.assertEqual(1, len(WatchRuleService.match_rows(rule, rows)))

    def test_invalid_indicator_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "不支持的盯盘字段"):
            WatchRuleService.validate_payload({
                "name": "非法指标",
                "rule_type": "indicator",
                "severity": "warning",
                "config": {"logic": "all", "conditions": [{"field": "pe_dynamic", "operator": "gt", "value": 1}]},
            })

    def test_strategy_rule_only_accepts_signal_fields(self):
        normalized = WatchRuleService.validate_payload({
            "name": "开仓信号",
            "rule_type": "strategy",
            "severity": "info",
            "config": {"logic": "all", "conditions": [{"field": "signal_type", "operator": "eq", "value": "buy"}]},
        })
        self.assertEqual("signal_type", normalized["config"]["conditions"][0]["field"])

    def test_unknown_data_purpose_is_rejected_before_database_write(self):
        with self.assertRaisesRegex(ValueError, "不支持的数据用途"):
            WatchRuleService.validate_payload({
                "name": "非法用途",
                "rule_type": "price",
                "data_purpose": "unknown",
                "config": {"conditions": [{"field": "price", "operator": "gte", "value": 1}]},
            })


if __name__ == "__main__":
    unittest.main()

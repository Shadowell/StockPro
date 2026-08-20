"""Versioned, explicit-evaluation watch rules that can only create alerts."""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Mapping, Sequence

import psycopg2.extras


class WatchRuleService:
    RULE_TYPES = {"strategy", "indicator", "price", "abnormal"}
    SEVERITIES = {"info", "warning", "critical"}
    OPERATORS = {"gt", "gte", "lt", "lte", "eq"}
    REALTIME_FIELDS = {"price", "change_percent", "volume", "amount", "turnover", "volume_ratio", "amplitude"}
    INDICATOR_FIELDS = {"change_percent", "volume", "amount", "turnover", "volume_ratio", "amplitude"}
    STRATEGY_FIELDS = {"signal_type", "status", "strength", "symbol"}

    def __init__(self, database):
        self.database = database

    @classmethod
    def validate_payload(cls, payload: Mapping[str, Any]) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        rule_type = str(payload.get("rule_type") or "").strip()
        severity = str(payload.get("severity") or "warning").strip()
        config = dict(payload.get("config") or {})
        if not name:
            raise ValueError("规则名称不能为空")
        if rule_type not in cls.RULE_TYPES:
            raise ValueError("不支持的盯盘规则类型")
        if severity not in cls.SEVERITIES:
            raise ValueError("不支持的告警级别")
        data_purpose = str(payload.get("data_purpose") or "user")
        if data_purpose not in {"user", "acceptance", "seed"}:
            raise ValueError("不支持的数据用途")
        logic = str(config.get("logic") or "all").lower()
        if logic not in {"all", "any"}:
            raise ValueError("规则逻辑只能是 all 或 any")
        conditions = config.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ValueError("至少需要一个盯盘条件")
        allowed = cls.STRATEGY_FIELDS if rule_type == "strategy" else (
            {"price", "change_percent"} if rule_type == "price" else cls.INDICATOR_FIELDS
        )
        normalized_conditions = []
        for item in conditions:
            condition = dict(item or {})
            field = str(condition.get("field") or "")
            operator = str(condition.get("operator") or "")
            if field not in allowed:
                raise ValueError(f"不支持的盯盘字段: {field}")
            if operator not in cls.OPERATORS:
                raise ValueError(f"不支持的比较符: {operator}")
            if "value" not in condition:
                raise ValueError("盯盘条件缺少比较值")
            normalized_conditions.append({"field": field, "operator": operator, "value": condition["value"]})
        symbols = [str(item).strip().upper() for item in config.get("symbols", []) if str(item).strip()]
        return {
            "name": name,
            "rule_type": rule_type,
            "severity": severity,
            "enabled": bool(payload.get("enabled", True)),
            "data_purpose": data_purpose,
            "config": {"logic": logic, "symbols": symbols, "conditions": normalized_conditions},
        }

    def list_watch_rules(self) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT DISTINCT ON (code) * FROM alert_rules
            WHERE rule_type <> 'system'
            ORDER BY code, rule_version DESC, created_at DESC
            """
        )

    def create_watch_rule(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        normalized = self.validate_payload(payload)
        code = f"watch_{uuid.uuid4().hex}"
        return self._insert_version(code, 1, normalized)

    def create_watch_rule_version(self, rule_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
        current = self._rule(rule_id)
        normalized = self.validate_payload(payload)
        return self._insert_version(str(current["code"]), int(current["rule_version"]) + 1, normalized)

    def preview_watch_rule(self, rule_id: str) -> Dict[str, Any]:
        rule = self._rule(rule_id)
        rows = self._source_rows(rule)
        matched = self.match_rows(rule, rows)
        return self._preview_payload(rule, rows, matched)

    def evaluate_watch_rule(self, rule_id: str) -> Dict[str, Any]:
        rule = self._rule(rule_id)
        if not rule.get("enabled"):
            raise ValueError("规则已停用")
        rows = self._source_rows(rule)
        matched = self.match_rows(rule, rows)
        created = 0
        category = "signal" if rule["rule_type"] == "strategy" else "data"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                for row in matched:
                    source_id = str(row.get("id") or row.get("code") or row.get("symbol") or "unknown")
                    observed_at = str(row.get("signal_time") or row.get("updated_at") or "snapshot")
                    dedupe_key = f"watch:{rule['id']}:{source_id}:{observed_at}"
                    evidence = {
                        "rule_type": rule["rule_type"],
                        "rule_version": rule["rule_version"],
                        "config": rule["config"],
                        "matched_row": dict(row),
                        "execution_boundary": "alert_only",
                    }
                    cursor.execute(
                        """
                        INSERT INTO alerts(alert_rule_id,category,severity,title,message,source_object_type,source_object_id,evidence,dedupe_key)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(dedupe_key) DO NOTHING RETURNING id
                        """,
                        (rule["id"], category, rule["severity"], rule["name"],
                         f"{rule['name']} 命中 {source_id}", f"watch_{rule['rule_type']}", source_id,
                         psycopg2.extras.Json(evidence), dedupe_key),
                    )
                    alert = cursor.fetchone()
                    if alert:
                        cursor.execute(
                            "INSERT INTO notification_deliveries(alert_id,channel,status,delivered_at) VALUES (%s,'in_app','delivered',NOW())",
                            (alert["id"],),
                        )
                        created += 1
                cursor.execute("UPDATE alert_rules SET last_evaluated_at=NOW() WHERE id=%s", (rule["id"],))
        return {**self._preview_payload(rule, rows, matched), "writes_performed": True, "alerts_created": created, "orders_created": 0}

    @classmethod
    def match_rows(cls, rule: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
        config = dict(rule.get("config") or {})
        symbols = {cls._symbol_key(item) for item in config.get("symbols", [])}
        conditions = list(config.get("conditions") or [])
        logic = str(config.get("logic") or "all")
        output = []
        for raw in rows:
            row = dict(raw)
            symbol = row.get("code") or row.get("symbol")
            if symbols and cls._symbol_key(symbol) not in symbols:
                continue
            verdicts = [cls._compare(row.get(item["field"]), item["operator"], item["value"]) for item in conditions]
            if verdicts and (all(verdicts) if logic == "all" else any(verdicts)):
                output.append(row)
        return output

    def _source_rows(self, rule: Mapping[str, Any]) -> List[Dict[str, Any]]:
        if rule["rule_type"] == "strategy":
            return self._rows("SELECT * FROM strategy_signals ORDER BY signal_time DESC,id DESC LIMIT 500")
        return list(self.database.get_all_stocks_realtime(include_listing_status=False) or [])

    def _rule(self, rule_id: str) -> Dict[str, Any]:
        row = self._row("SELECT * FROM alert_rules WHERE id=%s AND rule_type <> 'system'", (rule_id,))
        if not row:
            raise ValueError("盯盘规则不存在")
        return row

    def _insert_version(self, code: str, version: int, normalized: Mapping[str, Any]) -> Dict[str, Any]:
        content = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        category = "signal" if normalized["rule_type"] == "strategy" else "data"
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO alert_rules(code,rule_version,name,rule_type,category,severity,config,content_hash,enabled,data_purpose)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *
                    """,
                    (code, version, normalized["name"], normalized["rule_type"], category,
                     normalized["severity"], psycopg2.extras.Json(normalized["config"]), content_hash,
                     normalized["enabled"], normalized["data_purpose"]),
                )
                return self._dict_row(cursor.fetchone())

    @staticmethod
    def _compare(actual: Any, operator: str, expected: Any) -> bool:
        if actual is None:
            return False
        if operator == "eq":
            return str(actual).lower() == str(expected).lower()
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[operator]

    @staticmethod
    def _symbol_key(value: Any) -> str:
        return str(value or "").upper().replace("SH_", "").replace("SZ_", "").replace("BJ_", "").split(".")[0]

    @staticmethod
    def _preview_payload(rule: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], matched: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
        return {
            "rule_id": str(rule["id"]),
            "rule_version": int(rule["rule_version"]),
            "source_count": len(rows),
            "matched": len(matched),
            "items": [dict(item) for item in matched[:50]],
            "writes_performed": False,
        }

    def _rows(self, query: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, tuple(params))
                return [self._dict_row(row) for row in cursor.fetchall()]

    def _row(self, query: str, params: Sequence[Any] = ()) -> Dict[str, Any] | None:
        rows = self._rows(query, params)
        return rows[0] if rows else None

    @staticmethod
    def _dict_row(row: Mapping[str, Any]) -> Dict[str, Any]:
        return dict(row)

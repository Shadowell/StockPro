"""Read-only first-run readiness; reports evidence and never repairs state."""
from __future__ import annotations

from typing import Any, Dict

import psycopg2.extras


class OnboardingReadinessService:
    def __init__(self, database, settings, expected_migrations: int):
        self.database = database
        self.settings = settings
        self.expected_migrations = expected_migrations

    def build(self) -> Dict[str, Any]:
        counts = self._counts()
        steps = [
            self._step("security", "管理员安全", True, bool(self.settings.ADMIN_PASSWORD and self.settings.ADMIN_TOKEN_SECRET), "管理员密码与令牌签名已配置", "配置 ADMIN_PASSWORD 与 ADMIN_TOKEN_SECRET", "/admin/login"),
            self._step("storage", "PostgreSQL", True, counts["migrations"] == self.expected_migrations, f"迁移 {counts['migrations']}/{self.expected_migrations}", "运行数据库迁移并检查存储健康", "/data"),
            self._step("provider", "研究数据源", True, bool(self.settings.ENABLE_TUSHARE and self.settings.TUSHARE_TOKEN), "TuShare 主源已配置", "配置 TuShare；AKShare 仅作显式补充或整类回退", "/data"),
            self._step("snapshot", "封存研究数据", True, counts["snapshots"] > 0, f"封存快照 {counts['snapshots']} 个", "同步、质检并封存至少一个研究快照", "/data"),
            self._step("strategy", "策略版本", False, counts["strategies"] > 0, f"有效版本 {counts['strategies']} 个", "创建并验证 Strategy API v1 版本", "/strategy"),
            self._step("paper", "模拟验证", False, counts["paper"] > 0, f"Paper 实例 {counts['paper']} 个", "完整回测通过门禁后创建 Paper", "/paper"),
            self._step("review", "盘后复盘", False, counts["reviews"] > 0, f"复盘 {counts['reviews']} 份", "从真实交易日证据组装复盘", "/review"),
        ]
        required = [item for item in steps if item["required"]]
        return {
            "status": "ready" if all(item["status"] == "ready" for item in required) else "action_required",
            "steps": steps,
            "required_ready": sum(item["status"] == "ready" for item in required),
            "required_total": len(required),
            "writes_performed": False,
        }

    def _counts(self) -> Dict[str, int]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM schema_migrations)::INTEGER AS migrations,
                      (SELECT COUNT(*) FROM dataset_snapshots WHERE status='sealed')::INTEGER AS snapshots,
                      (SELECT COUNT(*) FROM strategy_versions WHERE validation_status='valid')::INTEGER AS strategies,
                      (SELECT COUNT(*) FROM paper_instances)::INTEGER AS paper,
                      (SELECT COUNT(*) FROM daily_reviews)::INTEGER AS reviews
                    """
                )
                return dict(cursor.fetchone())

    @staticmethod
    def _step(code: str, label: str, required: bool, ready: bool, ready_detail: str, missing_detail: str, route: str) -> Dict[str, Any]:
        return {"code": code, "label": label, "required": required, "status": "ready" if ready else "missing", "detail": ready_detail if ready else missing_detail, "action_route": route}

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.repositories.protocols import StrategyRepository


PRIVATE_CONTRACT_KEYS = {"api_version", "strategy_api_version", "migration_status"}


def _public_payload(value: Any, *, include_audit: bool = False) -> Any:
    if isinstance(value, list):
        return [_public_payload(item, include_audit=include_audit) for item in value]
    if not isinstance(value, dict):
        return value
    output: dict[str, Any] = {}
    historical: dict[str, object] = {}
    for key, item in value.items():
        if key in PRIVATE_CONTRACT_KEYS:
            historical[key] = item
            continue
        if key == "historical_contract_metadata" and not include_audit:
            continue
        output[key] = _public_payload(item, include_audit=include_audit)
    if include_audit and historical:
        output["historical_contract_metadata"] = historical
    return output


class StrategyApplicationService:
    def __init__(self, repository: StrategyRepository) -> None:
        self.repository = repository

    def list_strategies(self) -> list[dict[str, Any]]:
        return [_public_payload(item) for item in self.repository.list_strategies()]

    def get_strategy(self, version_id: str, *, include_audit: bool = False) -> dict[str, Any] | None:
        item = self.repository.get_strategy_version(version_id)
        return None if item is None else _public_payload(item, include_audit=include_audit)

    def create_strategy(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _public_payload(self.repository.create_strategy(deepcopy(payload)))

    def create_version(self, parent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return _public_payload(self.repository.create_version(parent_id, deepcopy(payload)))

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _public_payload(self.repository.validate(deepcopy(payload)))

    def quick_run(self, version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = _public_payload(self.repository.quick_run(version_id, deepcopy(payload)))
        result["promotion_status"] = "not_evaluated"
        return result

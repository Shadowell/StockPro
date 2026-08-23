from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from app.repositories.protocols import BacktestRepository


def _public(value: Any) -> Any:
    if isinstance(value, list):
        return [_public(item) for item in value]
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items() if key not in {"api_version", "strategy_api_version", "migration_status"}}
    return value


class BacktestApplicationService:
    def __init__(self, repository: BacktestRepository) -> None:
        self.repository = repository

    def configuration(self) -> dict[str, Any]: return _public(self.repository.configuration())
    def list_runs(self, limit: int) -> list[dict[str, Any]]: return _public(self.repository.list_runs(limit))
    def get_run(self, run_id: str) -> dict[str, Any]: return _public(self.repository.get_run(run_id))

    def run(self, payload: dict[str, Any], *, mode: Literal["quick", "full"]) -> dict[str, Any]:
        result = _public(deepcopy(self.repository.run(payload, mode)))
        if mode == "quick":
            result["promotion_status"] = "not_evaluated"
            result["promotion_checks"] = []
        return result

    def run_matrix(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(self.repository.run_matrix(payload))
        cells = result.get("cells") or result.get("items") or []
        for cell in cells:
            cell["promotion_status"] = "not_evaluated"
        result["cells"] = cells
        return result

    def run_walk_forward(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(self.repository.run_walk_forward(payload))
        for fold in result.get("folds") or []:
            fold["promotion_eligible"] = False
        return result

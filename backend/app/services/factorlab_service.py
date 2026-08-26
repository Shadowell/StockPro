"""FactorLab catalog and controlled research-task application service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional

from app.db.local_db import LocalDatabase, db_instance
from app.factorlab.builtins import builtin_factor_definitions
from app.factorlab.proposals import ResearchProviderFactorProposer
from app.factorlab.registry import FactorRegistry
from app.factorlab.research_models import FactorResearchTaskConfig, FactorTrial
from app.factorlab.research_repository import (
    FactorResearchRepository,
    FactorResearchStateError,
)
from app.factorlab.research_runner import FactorResearchRunner
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderExecutionConfig,
    capability_snapshot_hash,
    validate_provider_selection,
)
from app.services.agent.schemas import validate_provider_snapshot_payload
from app.services.kline_file_store import TIMEFRAME_MS


class FactorResearchCapacityError(RuntimeError):
    """Raised when starting another worker would exceed the CPU safety cap."""


class FactorLabService:
    def __init__(
        self,
        database: Optional[LocalDatabase] = None,
        *,
        factor_root: Optional[Path | str] = None,
        experiment_root: Optional[Path | str] = None,
        runner_factory: Callable[[FactorResearchTaskConfig], Any] | None = None,
        provider_capability_resolver: Callable[[str], Awaitable[ProviderCapabilities]] | None = None,
        max_concurrent_runners: int = 2,
        max_estimated_input_rows: int = 2_000_000,
    ):
        self.database = database or db_instance
        project_root = Path(__file__).resolve().parents[3]
        self.factor_root = Path(factor_root) if factor_root is not None else project_root / "data" / "factors"
        self.experiment_root = (
            Path(experiment_root)
            if experiment_root is not None
            else self.factor_root / "experiments"
        )
        self.registry = FactorRegistry(self.database)
        self.research_repository = FactorResearchRepository(self.database)
        self._runner_factory = runner_factory
        self._provider_capability_resolver = provider_capability_resolver
        self._max_concurrent_runners = max(1, int(max_concurrent_runners))
        self._max_estimated_input_rows = max(1, int(max_estimated_input_rows))
        self._runner_tasks: dict[str, asyncio.Task[Any]] = {}
        self._runner_lock = asyncio.Lock()

    def bootstrap(self) -> None:
        """Register immutable built-ins and one deterministic default instance each."""
        self.registry.register_builtins()
        for definition in builtin_factor_definitions():
            defaults = {
                name: schema["default"]
                for name, schema in definition.parameter_schema.items()
                if "default" in schema
            }
            self.registry.create_instance(
                definition.definition_id,
                definition.definition_version,
                defaults,
            )
        self.research_repository.pause_running_tasks(stop_reason="service_restarted")

    @property
    def active_runner_count(self) -> int:
        self._prune_finished_runners()
        return len(self._runner_tasks)

    async def create_research_task(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        values = dict(payload)
        factor_ids = tuple(str(item) for item in values.get("factor_instance_ids") or ())
        if not factor_ids:
            raise ValueError("factor_instance_ids must not be empty")
        for instance_id in factor_ids:
            self.registry.get_instance(instance_id)
        values["factor_instance_ids"] = factor_ids
        self._validate_input_budget(values)
        mode = str(values.get("mode") or "").strip().lower()
        if mode in {"auto", "hybrid"}:
            values["provider_snapshot"] = await self._pin_provider(values)
        else:
            values.update(
                {
                    "provider_key": "",
                    "model": "",
                    "reasoning_effort": "auto",
                    "speed_mode": "standard",
                    "provider_snapshot": {},
                }
            )
        config = FactorResearchTaskConfig.from_dict(values)
        task = self.research_repository.create_task(config)
        try:
            await self._schedule(task.task_id, config)
        except FactorResearchCapacityError:
            self.research_repository.transition(
                task.task_id,
                {"queued"},
                "failed",
                stop_reason="runner_capacity_exhausted",
            )
            raise
        return self._task_response(self.research_repository.get_task(task.task_id))

    def _validate_input_budget(self, values: Mapping[str, Any]) -> None:
        timeframe = str(values.get("timeframe") or "").strip().lower()
        timeframe_ms = TIMEFRAME_MS.get(timeframe)
        if timeframe_ms is None:
            raise ValueError("unsupported FactorLab timeframe")
        start_ms = int(values.get("start_ms", -1))
        end_ms = int(values.get("end_ms", -1))
        symbols = values.get("symbols") or []
        if start_ms < 0 or end_ms <= start_ms or not isinstance(symbols, (list, tuple)):
            raise ValueError("invalid FactorLab input range")
        estimated_rows = ((end_ms - start_ms) // timeframe_ms + 1) * len(symbols)
        if estimated_rows > self._max_estimated_input_rows:
            raise ValueError("FactorLab estimated input rows exceed the resource budget")

    def list_research_tasks(self) -> list[dict[str, Any]]:
        return [self._task_response(task) for task in self.research_repository.list_tasks()]

    def get_research_task(self, task_id: str) -> dict[str, Any]:
        return self._task_response(self.research_repository.get_task(task_id))

    def list_research_trials(self, task_id: str) -> list[dict[str, Any]]:
        self.research_repository.get_task(task_id)
        return [self._trial_response(trial) for trial in self.research_repository.list_trials(task_id)]

    def pause_research_task(self, task_id: str) -> dict[str, Any]:
        task = self.research_repository.get_task(task_id)
        if task.archived_at is not None:
            raise FactorResearchStateError("archived tasks cannot be paused")
        if task.status not in {"queued", "running"}:
            raise FactorResearchStateError("only queued or running tasks can be paused")
        paused = self.research_repository.transition(
            task_id,
            {task.status},
            "paused",
            stop_reason="operator_paused",
        )
        return self._task_response(paused)

    async def resume_research_task(self, task_id: str) -> dict[str, Any]:
        task = self.research_repository.get_task(task_id)
        if task.archived_at is not None:
            raise FactorResearchStateError("archived tasks cannot be resumed")
        if task.status != "paused":
            raise FactorResearchStateError("only paused tasks can be resumed")
        self._prune_finished_runners()
        if task_id in self._runner_tasks:
            raise FactorResearchStateError("task runner is still stopping")
        await self._schedule(task_id, task.config)
        return self._task_response(self.research_repository.get_task(task_id))

    def archive_research_task(self, task_id: str) -> dict[str, Any]:
        return self._task_response(self.research_repository.archive_task(task_id))

    async def _pin_provider(self, values: Mapping[str, Any]) -> dict[str, Any]:
        provider_key = str(values.get("provider_key") or "").strip()
        model = str(values.get("model") or "").strip()
        reasoning_effort = str(values.get("reasoning_effort") or "auto")
        speed_mode = str(values.get("speed_mode") or "standard")
        if not provider_key or not model:
            raise ValueError("automatic research requires Provider and model")
        if self._provider_capability_resolver is None:
            from app.services.agent.providers.managed_login import (
                get_runtime_provider_capabilities,
            )
            from app.services.agent.providers.registry import ProviderRegistry

            registry = ProviderRegistry()
            capabilities = await get_runtime_provider_capabilities(registry, provider_key)
            default_model = registry.get_definition(provider_key).default_model
        else:
            capabilities = await self._provider_capability_resolver(provider_key)
            default_model = model
        execution = ProviderExecutionConfig(
            provider_key=provider_key,
            model=model,
            reasoning_effort=reasoning_effort,
            speed_mode=speed_mode,
            provider_config_revision=capabilities.config_revision,
            capability_snapshot_hash=capability_snapshot_hash(capabilities),
        )
        validate_provider_selection(capabilities, execution)
        snapshot = capabilities.model_dump(mode="json")
        snapshot.update(
            {
                "default_model": default_model,
                "provider_config_revision": capabilities.config_revision,
                "capability_snapshot_hash": execution.capability_snapshot_hash,
            }
        )
        return validate_provider_snapshot_payload(
            provider_key=provider_key,
            model=model,
            reasoning_effort=reasoning_effort,
            speed_mode=speed_mode,
            snapshot=snapshot,
        )

    async def _schedule(self, task_id: str, config: FactorResearchTaskConfig) -> None:
        async with self._runner_lock:
            self._prune_finished_runners()
            if task_id in self._runner_tasks:
                raise FactorResearchStateError("task runner is already active")
            if len(self._runner_tasks) >= self._max_concurrent_runners:
                raise FactorResearchCapacityError("factor research runner capacity exhausted")
            runner = self._build_runner(config)
            background = asyncio.create_task(
                asyncio.to_thread(self._run_runner_safely, runner, task_id)
            )
            self._runner_tasks[task_id] = background
            background.add_done_callback(
                lambda completed, key=task_id: self._on_runner_done(key, completed)
            )

    def _run_runner_safely(self, runner: Any, task_id: str) -> Any:
        try:
            return runner.run(task_id)
        except BaseException:
            try:
                current = self.research_repository.get_task(task_id)
                if current.status in {"queued", "running"}:
                    return self.research_repository.transition(
                        task_id,
                        {current.status},
                        "failed",
                        stop_reason="runner_crashed",
                    )
            except Exception:
                pass
            return None

    def _on_runner_done(self, task_id: str, completed: asyncio.Task[Any]) -> None:
        self._runner_tasks.pop(task_id, None)
        if completed.cancelled():
            return
        exception = completed.exception()
        if exception is None:
            return
        try:
            current = self.research_repository.get_task(task_id)
            if current.status in {"queued", "running"}:
                self.research_repository.transition(
                    task_id,
                    {current.status},
                    "failed",
                    stop_reason="runner_crashed",
                )
        except Exception:
            # The callback must consume the runner exception even when the
            # persistence layer is unavailable. Raw runner details are never
            # copied into API state or logs here.
            return

    def _build_runner(self, config: FactorResearchTaskConfig):
        if self._runner_factory is not None:
            return self._runner_factory(config)
        proposer = (
            ResearchProviderFactorProposer()
            if config.mode in {"auto", "hybrid"}
            else None
        )
        return FactorResearchRunner(
            repository=self.research_repository,
            registry=self.registry,
            provider_proposer=proposer,
            artifact_root=self.experiment_root,
        )

    def _prune_finished_runners(self) -> None:
        for task_id, runner in list(self._runner_tasks.items()):
            if runner.done():
                self._runner_tasks.pop(task_id, None)

    @staticmethod
    def _task_response(task) -> dict[str, Any]:
        config = task.config
        return {
            "task_id": task.task_id,
            "status": task.status,
            "mode": config.mode,
            "exchange": config.exchange,
            "market_type": config.market_type,
            "symbols": list(config.symbols),
            "timeframe": config.timeframe,
            "start_ms": config.start_ms,
            "end_ms": config.end_ms,
            "factor_instance_ids": list(config.factor_instance_ids),
            "manual_combination_count": len(config.manual_combinations),
            "provider_key": config.provider_key,
            "model": config.model,
            "reasoning_effort": config.reasoning_effort,
            "speed_mode": config.speed_mode,
            "horizon_bars": config.horizon_bars,
            "base_cost_bps": config.base_cost_bps,
            "stress_cost_bps": config.stress_cost_bps,
            "n_splits": config.n_splits,
            "max_candidates": config.max_candidates,
            "max_runtime_sec": config.max_runtime_sec,
            "max_no_improvement": config.max_no_improvement,
            "max_combination_leaves": config.max_combination_leaves,
            "target_accepted_candidates": config.target_accepted_candidates,
            "dataset_snapshot_id": task.dataset_snapshot_id,
            "trial_cursor": task.trial_cursor,
            "best_trial_id": task.best_trial_id,
            "stop_reason": task.stop_reason,
            "archived_at": task.archived_at,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    @staticmethod
    def _trial_response(trial: FactorTrial) -> dict[str, Any]:
        return {
            "trial_id": trial.trial_id,
            "task_id": trial.task_id,
            "ordinal": trial.ordinal,
            "semantic_hash": trial.semantic_hash,
            "model_type": trial.model_type,
            "feature_ids": list(trial.feature_ids),
            "parameters": dict(trial.parameters),
            "status": trial.status,
            "metrics": dict(trial.metrics),
            "hard_gate_failures": list(trial.hard_gate_failures),
            "created_at": trial.created_at,
        }

    def summary(self) -> dict[str, Any]:
        definitions = [asdict(definition) for definition in self.registry.list_definitions()]
        connection = self.database.get_connection()
        instance_rows = connection.execute(
            """
            SELECT instance_id, definition_id, definition_version, parameters_json,
                   parameter_hash, required_bars, created_at
            FROM factor_instances
            ORDER BY definition_id, definition_version, instance_id
            """
        ).fetchall()
        latest_rows = connection.execute(
            """
            SELECT exchange, market_type, symbol, timeframe, instance_id,
                   event_time, available_at, computed_at, value, value_status,
                   dataset_revision
            FROM factor_latest
            ORDER BY event_time DESC, instance_id, symbol
            LIMIT 100
            """
        ).fetchall()

        instances = []
        for row in instance_rows:
            item = dict(row)
            parameters = json.loads(item["parameters_json"])
            definition = self.registry.get_definition(
                item["definition_id"],
                int(item["definition_version"]),
            )
            defaults = {
                name: schema.get("default")
                for name, schema in definition.parameter_schema.items()
            }
            item["parameters"] = parameters
            item["is_default"] = parameters == defaults
            instances.append(item)

        latest_values = [dict(row) for row in latest_rows]
        partition_count = sum(1 for _ in self.factor_root.glob("values/**/part-*.parquet"))
        return {
            "status": "ready" if definitions else "empty",
            "phase": "phase2_ml_research",
            "statistics": {
                "definition_count": len(definitions),
                "instance_count": len(instances),
                "latest_value_count": self._table_count("factor_latest"),
                "materialized_partition_count": partition_count,
                "research_task_count": self._table_count("factor_research_tasks"),
                "trial_count": self._table_count("factor_trials"),
            },
            "definitions": definitions,
            "instances": instances,
            "latest_values": latest_values,
            "data_plane": {
                "format": "parquet",
                "layout": "exchange/market_type/timeframe/factor_instance/date",
                "manifest": "manifest.json",
            },
            "capabilities": {
                "api_mode": "controlled_research",
                "materialization_store_ready": True,
                "research_metrics_available": True,
                "strategy_runtime_connected": False,
                "paper_live_connected": False,
            },
        }

    def _table_count(self, table: str) -> int:
        allowed = {"factor_latest", "factor_research_tasks", "factor_trials"}
        if table not in allowed:
            raise ValueError(f"unsupported FactorLab table: {table}")
        row = self.database.get_connection().execute(
            f"SELECT COUNT(*) AS count FROM {table}"
        ).fetchone()
        return int(row["count"])


factorlab_service = FactorLabService()

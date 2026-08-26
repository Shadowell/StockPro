"""Agent task-level Provider selection and persistence regression tests."""

from __future__ import annotations

import json
import asyncio
import copy
import sys
import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.services.agent import evaluator_agent, planner_agent, strategist_agent  # noqa: E402
from app.services.agent.orchestrator import AgentOrchestrator  # noqa: E402
from app.services.agent.providers.contracts import (  # noqa: E402
    ProviderError,
    ProviderExecutionError,
    ProviderRunResult,
)
from app.services.agent.schemas import (  # noqa: E402
    AgentTask,
    CreateTaskRequest,
    _provider_capability_hash,
)
from app.services.agent.providers.managed_login import (  # noqa: E402
    ManagedLoginProbeService,
    get_runtime_provider_capabilities,
)
from app.services.agent.providers.registry import ProviderRegistry  # noqa: E402


def _task_payload(task: AgentTask) -> dict:
    return {
        "id": task.task_id,
        "status": task.status,
        "stage": task.stage,
        "stage_label": task.stage_label,
        "goal_criteria": task.goal.to_dict(),
        "market_type": task.market_type,
        "symbol": task.symbol,
        "timeframe": task.timeframe,
        "backtest_start": task.backtest_start,
        "backtest_end": task.backtest_end,
        "max_iterations": task.max_iterations,
        "current_iteration": task.current_iteration,
        "best_iteration": task.best_iteration,
        "user_prompt": task.user_prompt,
        "llm_provider": task.llm_provider,
        "llm_model": task.llm_model,
        "llm_reasoning_effort": task.llm_reasoning_effort,
        "llm_speed_mode": task.llm_speed_mode,
        "llm_provider_snapshot": task.llm_provider_snapshot,
        "strategy_spec": None,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def _pinned_task() -> AgentTask:
    from app.services.agent.providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    capabilities = registry.get_capabilities("grok")
    capabilities = capabilities.model_copy(update={"configured": True, "status_detail": "环境变量已配置"})
    definition = registry.get_definition("grok")
    snapshot = capabilities.model_dump(mode="json")
    snapshot.update(
        {
            "default_model": definition.default_model,
            "provider_config_revision": capabilities.config_revision,
            "capability_snapshot_hash": _provider_capability_hash(capabilities),
        }
    )
    return AgentTask(
        task_id="task-provider",
        llm_provider="grok",
        llm_model="grok-4.6",
        llm_reasoning_effort="high",
        llm_speed_mode="standard",
        llm_provider_snapshot=snapshot,
    )


def _legacy_v1_snapshot(task: AgentTask, *, include_runtime_fields: bool = False) -> dict:
    """Build either known pre-v2 v1 shape and its original full-model hash."""

    import hashlib

    capabilities = task.llm_provider_snapshot.copy()
    if not include_runtime_fields:
        capabilities.pop("command_available", None)
        capabilities.pop("login_verified", None)
    capabilities["schema_version"] = "provider-capability-v1"
    hash_payload = {
        key: value
        for key, value in capabilities.items()
        if key not in {"default_model", "provider_config_revision", "capability_snapshot_hash"}
    }
    legacy_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            hash_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    capabilities["capability_snapshot_hash"] = legacy_hash
    return capabilities


def test_agent_task_persists_provider_execution_config(tmp_path):
    database = LocalDatabase(str(tmp_path / "agent-provider.db"))
    database.init_db()
    task = _pinned_task()

    database.save_agent_task(_task_payload(task))
    restored = database.get_agent_task(task.task_id)

    assert restored["llm_provider"] == "grok"
    assert restored["llm_model"] == "grok-4.6"
    assert restored["llm_reasoning_effort"] == "high"
    assert restored["llm_speed_mode"] == "standard"
    assert json.loads(restored["llm_provider_snapshot"])["transport_type"] == "xai_api"


def test_existing_pinned_task_update_preserves_provider_fields_when_absent(tmp_path):
    database = LocalDatabase(str(tmp_path / "agent-provider-update.db"))
    database.init_db()
    task = _pinned_task()
    database.save_agent_task(_task_payload(task))

    update = _task_payload(task)
    for key in ("llm_provider", "llm_model", "llm_reasoning_effort", "llm_speed_mode", "llm_provider_snapshot"):
        update.pop(key)
    update.update({"status": "running", "stage": "planner"})
    database.save_agent_task(update)

    restored = database.get_agent_task(task.task_id)
    assert restored["llm_provider"] == "grok"
    assert restored["llm_model"] == "grok-4.6"
    assert restored["llm_reasoning_effort"] == "high"
    assert restored["llm_speed_mode"] == "standard"
    assert json.loads(restored["llm_provider_snapshot"])["provider_key"] == "grok"


@pytest.mark.parametrize("legacy_snapshot", ["", "{}", None])
def test_existing_legacy_partial_update_normalizes_empty_snapshot(
    tmp_path, legacy_snapshot
):
    database = LocalDatabase(str(tmp_path / f"legacy-partial-{legacy_snapshot!r}.db"))
    database.init_db()
    task = AgentTask(task_id="legacy-partial")
    database.save_agent_task(_task_payload(task))

    connection = database.get_connection()
    connection.execute(
        "UPDATE agent_tasks SET llm_provider_snapshot = ? WHERE id = ?",
        (legacy_snapshot, task.task_id),
    )
    connection.commit()

    database.save_agent_task(
        {
            "id": task.task_id,
            "status": "interrupted",
            "symbol": task.symbol,
            "timeframe": task.timeframe,
            "backtest_start": task.backtest_start,
            "backtest_end": task.backtest_end,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
    )

    restored = database.get_agent_task(task.task_id)
    assert restored["llm_provider"] == ""
    assert restored["llm_provider_snapshot"] == "{}"
    assert json.loads(restored["llm_provider_snapshot"]) == {}


def test_existing_pinned_partial_update_preserves_valid_snapshot(tmp_path):
    database = LocalDatabase(str(tmp_path / "pinned-partial.db"))
    database.init_db()
    task = _pinned_task()
    database.save_agent_task(_task_payload(task))
    before = database.get_agent_task(task.task_id)

    database.save_agent_task(
        {
            "id": task.task_id,
            "status": "interrupted",
            "symbol": task.symbol,
            "timeframe": task.timeframe,
            "backtest_start": task.backtest_start,
            "backtest_end": task.backtest_end,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }
    )

    restored = database.get_agent_task(task.task_id)
    assert restored["llm_provider"] == before["llm_provider"]
    assert restored["llm_model"] == before["llm_model"]
    assert restored["llm_reasoning_effort"] == before["llm_reasoning_effort"]
    assert restored["llm_speed_mode"] == before["llm_speed_mode"]
    assert restored["llm_provider_snapshot"] == before["llm_provider_snapshot"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"llm_provider": ""},
        {"llm_model": "grok-4.7"},
        {
            "llm_provider": "grok",
            "llm_model": "grok-4.6",
            "llm_reasoning_effort": "high",
            "llm_speed_mode": "standard",
            "llm_provider_snapshot": "not-json",
        },
        {
            "llm_provider": "cursor",
            "llm_model": "auto",
            "llm_reasoning_effort": "auto",
            "llm_speed_mode": "standard",
            "llm_provider_snapshot": _pinned_task().llm_provider_snapshot,
        },
    ],
)
def test_existing_pinned_task_rejects_partial_or_invalid_provider_update(tmp_path, mutation):
    database = LocalDatabase(str(tmp_path / "agent-provider-atomic.db"))
    database.init_db()
    task = _pinned_task()
    database.save_agent_task(_task_payload(task))
    before = database.get_agent_task(task.task_id)
    update = {"id": task.task_id, "status": "running", "symbol": task.symbol, "timeframe": task.timeframe,
              "backtest_start": task.backtest_start, "backtest_end": task.backtest_end,
              "created_at": task.created_at, "updated_at": task.updated_at}
    update.update(mutation)

    with pytest.raises((ValueError, ProviderExecutionError)):
        database.save_agent_task(update)

    after = database.get_agent_task(task.task_id)
    assert after["llm_provider"] == before["llm_provider"]
    assert after["llm_model"] == before["llm_model"]
    assert after["llm_reasoning_effort"] == before["llm_reasoning_effort"]
    assert after["llm_speed_mode"] == before["llm_speed_mode"]
    assert after["llm_provider_snapshot"] == before["llm_provider_snapshot"]


@pytest.mark.parametrize(
    ("snapshot_value", "include_snapshot"),
    [({}, True), ("{}", True), ("", True), (None, True), (None, False)],
)
def test_legacy_empty_provider_snapshots_store_json_object_and_reload(
    tmp_path, snapshot_value, include_snapshot
):
    database = LocalDatabase(str(tmp_path / f"legacy-empty-{include_snapshot}-{snapshot_value!r}.db"))
    database.init_db()
    payload = _task_payload(AgentTask(task_id="legacy-empty"))
    if include_snapshot:
        payload["llm_provider_snapshot"] = snapshot_value
    else:
        payload.pop("llm_provider_snapshot")

    database.save_agent_task(payload)
    first = database.get_agent_task("legacy-empty")
    database.save_agent_task({
        "id": "legacy-empty",
        "status": "interrupted",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
        "backtest_start": "2025-01-01",
        "backtest_end": "2025-02-01",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:01",
    })
    reloaded = database.get_agent_task("legacy-empty")

    assert first["llm_provider_snapshot"] == "{}"
    assert reloaded["llm_provider_snapshot"] == "{}"
    assert json.loads(reloaded["llm_provider_snapshot"]) == {}


def test_legacy_agent_task_schema_gets_compatible_provider_defaults(tmp_path):
    database = LocalDatabase(str(tmp_path / "legacy-agent.db"))
    database.init_db()
    payload = _task_payload(AgentTask(task_id="legacy-provider"))
    for key in ("llm_provider", "llm_reasoning_effort", "llm_speed_mode", "llm_provider_snapshot"):
        payload.pop(key)

    database.save_agent_task(payload)
    restored = database.get_agent_task("legacy-provider")

    assert restored["llm_provider"] == ""
    assert restored["llm_reasoning_effort"] == "auto"
    assert restored["llm_speed_mode"] == "standard"
    assert json.loads(restored["llm_provider_snapshot"]) == {}


def test_agent_task_migration_preserves_existing_rows(tmp_path):
    database_path = tmp_path / "agent-migration.db"
    connection = sqlite3.connect(database_path)
    connection.execute(
        """
        CREATE TABLE agent_tasks (
            id TEXT PRIMARY KEY,
            status TEXT,
            stage TEXT,
            stage_label TEXT,
            goal_criteria TEXT,
            market_type TEXT,
            symbol TEXT,
            timeframe TEXT,
            backtest_start TEXT,
            backtest_end TEXT,
            max_iterations INTEGER,
            current_iteration INTEGER,
            best_iteration INTEGER,
            user_prompt TEXT,
            llm_model TEXT,
            strategy_spec TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO agent_tasks
        (id, status, stage, stage_label, goal_criteria, market_type, symbol, timeframe,
         backtest_start, backtest_end, max_iterations, current_iteration, best_iteration,
         user_prompt, llm_model, strategy_spec, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "legacy-row",
            "interrupted",
            "planner",
            "服务重启已中断",
            "{}",
            "spot",
            "BTC/USDT",
            "15m",
            "2025-01-01",
            "2025-02-01",
            2,
            0,
            None,
            "legacy task",
            "qwen3.6-plus",
            None,
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    connection.commit()
    connection.close()

    database = LocalDatabase(str(database_path))
    database.init_db()
    restored = database.get_agent_task("legacy-row")

    assert restored["llm_model"] == "qwen3.6-plus"
    assert restored["llm_provider"] == ""
    assert restored["llm_reasoning_effort"] == "auto"
    assert restored["llm_speed_mode"] == "standard"
    assert json.loads(restored["llm_provider_snapshot"]) == {}


def test_legacy_task_restore_pins_global_provider_and_persists_snapshot(tmp_path, monkeypatch):
    from app.api.v2.endpoints import agent as agent_endpoint
    from app.services.agent import llm_client

    config_path = tmp_path / "models.json"
    config_path.write_text(
        json.dumps(
            {
                "provider_key": "openai",
                "providers": [
                    {
                        "provider_key": "openai",
                        "name": "OpenAI",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "default_model": "gpt-5.1",
                        "models": ["gpt-5.1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    database = LocalDatabase(str(tmp_path / "legacy-restore.db"))
    database.init_db()
    payload = _task_payload(AgentTask(task_id="legacy-restore", llm_model="gpt-5.1"))
    for key in ("llm_provider", "llm_reasoning_effort", "llm_speed_mode", "llm_provider_snapshot"):
        payload.pop(key)
    database.save_agent_task(payload)
    monkeypatch.setattr(agent_endpoint, "db", database)

    restored = agent_endpoint._task_from_db(database.get_agent_task("legacy-restore"))
    persisted = database.get_agent_task("legacy-restore")

    assert restored.llm_provider == "openai"
    assert json.loads(persisted["llm_provider_snapshot"])["provider_key"] == "openai"


def test_task_status_snapshot_does_not_expose_provider_secrets_or_paths():
    from app.api.v2.endpoints import agent as agent_endpoint

    task = _pinned_task()
    task.llm_provider_snapshot.update(
        {
            "api_key": "secret-value",
            "token": "login-token",
            "command": "/private/bin/agent",
        }
    )

    response = agent_endpoint._task_to_status(task)

    assert "secret-value" not in json.dumps(response)
    assert "login-token" not in json.dumps(response)
    assert "/private/bin/agent" not in json.dumps(response)
    assert response["llm_provider_snapshot"]["transport_type"] == "xai_api"


def test_provider_snapshot_persistence_canonicalizes_unknown_secret_fields(tmp_path):
    task = _pinned_task()
    task.llm_provider_snapshot.update({
        "api_key": "secret-value",
        "token": "login-token",
        "command": "/private/bin/agent",
        "unknown_extension": {"secret": "nested"},
    })
    database = LocalDatabase(str(tmp_path / "canonical-snapshot.db"))
    database.init_db()

    database.save_agent_task(_task_payload(task))
    persisted = database.get_agent_task(task.task_id)
    snapshot = json.loads(persisted["llm_provider_snapshot"])

    assert "api_key" not in snapshot
    assert "token" not in snapshot
    assert "command" not in snapshot
    assert "unknown_extension" not in snapshot
    assert snapshot["provider_key"] == "grok"
    assert snapshot["default_model"] == "grok-4.6"


@pytest.mark.parametrize("include_runtime_fields", [False, True])
def test_legacy_v1_snapshot_is_migrated_and_atomically_canonicalized(
    tmp_path, monkeypatch, include_runtime_fields
):
    task = _pinned_task()
    task.llm_provider_snapshot = _legacy_v1_snapshot(task, include_runtime_fields=include_runtime_fields)
    task.llm_provider = "grok"
    task.llm_model = "grok-4.6"
    task.llm_reasoning_effort = "high"
    task.llm_speed_mode = "standard"

    database = LocalDatabase(str(tmp_path / "legacy-v1-migration.db"))
    database.init_db()
    database.save_agent_task(_task_payload(task))
    persisted = database.get_agent_task(task.task_id)
    migrated = json.loads(persisted["llm_provider_snapshot"])

    assert persisted["llm_provider"] == "grok"
    assert persisted["llm_model"] == "grok-4.6"
    assert persisted["llm_reasoning_effort"] == "high"
    assert persisted["llm_speed_mode"] == "standard"
    assert migrated["schema_version"] == "provider-capability-v2"
    assert migrated["provider_key"] == "grok"
    assert migrated["default_model"] == "grok-4.6"
    assert "command_available" in migrated
    assert "login_verified" in migrated

    monkeypatch.setattr(
        "app.services.agent.llm_client.get_llm_model_config",
        lambda: (_ for _ in ()).throw(AssertionError("legacy restore must not read global defaults")),
    )
    restored = AgentTask(
        task_id=task.task_id,
        llm_provider=persisted["llm_provider"],
        llm_model=persisted["llm_model"],
        llm_reasoning_effort=persisted["llm_reasoning_effort"],
        llm_speed_mode=persisted["llm_speed_mode"],
        llm_provider_snapshot=migrated,
    )
    execution = restored.provider_execution_config()
    assert execution.provider_key == "grok"
    assert execution.model == "grok-4.6"
    assert execution.reasoning_effort == "high"
    assert execution.speed_mode == "standard"


def test_provider_snapshot_migration_failure_leaves_existing_db_row_unchanged(tmp_path):
    database = LocalDatabase(str(tmp_path / "migration-failure-unchanged.db"))
    database.init_db()
    task = _pinned_task()
    database.save_agent_task(_task_payload(task))
    before = database.get_agent_task(task.task_id)

    invalid_update = _task_payload(task)
    invalid_update["llm_provider_snapshot"] = dict(task.llm_provider_snapshot)
    invalid_update["llm_provider_snapshot"]["capability_snapshot_hash"] = "sha256:invalid"

    with pytest.raises(ProviderExecutionError) as exc_info:
        database.save_agent_task(invalid_update)

    assert exc_info.value.error_code == "provider_snapshot_invalid"
    assert database.get_agent_task(task.task_id) == before


def test_provider_failure_status_write_failure_returns_service_unavailable(monkeypatch):
    from app.api.v2.endpoints import agent as agent_endpoint

    class FailingDb:
        def update_agent_task_status(self, task_id, status, updated_at=None):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(agent_endpoint, "db", FailingDb())
    with pytest.raises(ProviderError) as exc_info:
        agent_endpoint._mark_agent_task_provider_failed("task-db-failure")

    assert exc_info.value.error_code == "provider_status_persist_failed"
    assert exc_info.value.status_code == 503


@pytest.mark.parametrize("persisted_result", [False, 0])
def test_provider_failure_status_falsey_write_result_returns_service_unavailable(
    monkeypatch,
    persisted_result,
):
    from app.api.v2.endpoints import agent as agent_endpoint

    class MissingRowDb:
        def update_agent_task_status(self, task_id, status, updated_at=None):
            return persisted_result

    monkeypatch.setattr(agent_endpoint, "db", MissingRowDb())
    with pytest.raises(ProviderError) as exc_info:
        agent_endpoint._mark_agent_task_provider_failed("task-row-missing")

    assert exc_info.value.error_code == "provider_status_persist_failed"
    assert exc_info.value.status_code == 503


def test_orchestrator_pins_requested_provider_on_task_creation(monkeypatch):
    monkeypatch.setattr("app.services.agent.providers.registry.shutil.which", lambda command: "/usr/bin/agent")
    service = ManagedLoginProbeService(
        runner=lambda *args, **kwargs: type(
            "Result",
            (),
            {"returncode": 0, "stdout": "authenticated", "stderr": ""},
        )(),
        which=lambda command: "/usr/bin/agent",
        ttl_sec=60,
    )
    capabilities = asyncio.run(
        get_runtime_provider_capabilities(ProviderRegistry(), "cursor", service=service)
    )

    task = AgentOrchestrator().create_task(
        CreateTaskRequest(
            llm_provider="cursor",
            llm_model="auto",
            llm_reasoning_effort="auto",
            llm_speed_mode="standard",
        ),
        provider_capabilities=capabilities,
    )

    assert task.llm_provider == "cursor"
    assert task.llm_model == "auto"
    assert task.provider_execution_config().provider_key == "cursor"
    assert task.llm_provider_snapshot["transport_type"] == "cursor_cli"


class _FakeResearchProviderClient:
    def __init__(self, response: dict):
        self.response = response
        self.executions = []
        self.requests = []
        self.close_count = 0

    async def run(self, request):
        self.requests.append(request)
        self.executions.append(request.execution)
        return ProviderRunResult(
            provider_key=request.execution.provider_key,
            model=request.execution.model,
            text=json.dumps(self.response),
            structured=self.response,
            duration_ms=0,
        )

    async def close(self):
        self.close_count += 1


def test_planner_strategist_and_evaluator_use_task_provider(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    task = _pinned_task()
    fake = _FakeResearchProviderClient(
        {
            "market_analysis": "test",
            "strategy_candidates": [],
            "recommended_approach": "test",
            "risk_considerations": "test",
            "iteration_plan": "test",
        }
    )
    monkeypatch.setattr(planner_agent, "get_research_provider_client", lambda execution, **kwargs: fake)
    monkeypatch.setattr(strategist_agent, "get_research_provider_client", lambda execution, **kwargs: fake)
    monkeypatch.setattr(evaluator_agent, "get_research_provider_client", lambda execution, **kwargs: fake)
    monkeypatch.setattr(strategist_agent, "validate_base_strategy_contract", lambda code: None)

    async def _noop_runtime_smoke(*args, **kwargs):
        return None

    monkeypatch.setattr(strategist_agent, "validate_strategy_runtime_smoke", _noop_runtime_smoke)

    async def run_agents():
        await planner_agent.PlannerAgent().plan(task)

        fake.response = {
            "action": "new",
            "strategy_direction": "test",
            "key_indicators": [],
            "entry_logic_desc": "test",
            "exit_logic_desc": "test",
            "risk_management_desc": "test",
            "acceptance_criteria": [],
        }
        await strategist_agent.StrategistAgent().propose_contract(task)

        fake.response = {"verdict": "approved", "added_criteria": [], "feedback": ""}
        await evaluator_agent.EvaluatorAgent().review_contract({}, task)

        fake.response = {
            "strategy_name": "test",
            "strategy_class_code": "class Test: pass",
            "stop_loss": 0.02,
            "timeframe": "15m",
            "reasoning": "test",
        }
        await strategist_agent.StrategistAgent().generate(task)

        fake.response = {
            "risk_control": 50,
            "profitability": 50,
            "robustness": 50,
            "strategy_logic": 50,
            "originality": 50,
            "meets_goal": False,
            "analysis": "test",
            "issues": [],
            "suggestions": [],
            "contract_verdict": [],
            "next_action": "refine",
        }
        await evaluator_agent.EvaluatorAgent().evaluate(task, "class Test: pass", {})

    asyncio.run(run_agents())

    assert len(fake.executions) == 5
    assert {execution.provider_key for execution in fake.executions} == {"grok"}
    assert {execution.reasoning_effort for execution in fake.executions} == {"high"}
    assert {execution.speed_mode for execution in fake.executions} == {"standard"}
    assert len(fake.requests) == 5
    assert all(request.response_schema for request in fake.requests)
    assert fake.close_count == 5


def test_agent_provider_failure_propagates_and_closes_client(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    task = _pinned_task()

    class FailingClient(_FakeResearchProviderClient):
        async def run(self, request):
            self.requests.append(request)
            self.executions.append(request.execution)
            raise ProviderExecutionError(
                "Provider 已停用",
                provider_key=request.execution.provider_key,
                error_code="provider_disabled",
            )

    for module, call in (
        (planner_agent, lambda: planner_agent.PlannerAgent().plan(task)),
        (strategist_agent, lambda: strategist_agent.StrategistAgent().propose_contract(task)),
        (evaluator_agent, lambda: evaluator_agent.EvaluatorAgent().review_contract({}, task)),
    ):
        fake = FailingClient({})
        monkeypatch.setattr(module, "get_research_provider_client", lambda execution, fake=fake, **kwargs: fake)

        async def run_call(call=call):
            with pytest.raises(ProviderExecutionError) as exc_info:
                await call()
            assert exc_info.value.error_code == "provider_disabled"

        asyncio.run(run_call())
        assert fake.close_count == 1


def test_provider_cancellation_closes_client(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    task = _pinned_task()

    class CancelledClient(_FakeResearchProviderClient):
        async def run(self, request):
            self.requests.append(request)
            raise asyncio.CancelledError

    fake = CancelledClient({})
    monkeypatch.setattr(planner_agent, "get_research_provider_client", lambda execution, **kwargs: fake)

    async def run_call():
        with pytest.raises(asyncio.CancelledError):
            await planner_agent.PlannerAgent().plan(task)

    asyncio.run(run_call())
    assert fake.close_count == 1


def test_invalid_structured_provider_output_does_not_use_agent_defaults(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    task = _pinned_task()
    fake = _FakeResearchProviderClient({})
    monkeypatch.setattr(planner_agent, "get_research_provider_client", lambda execution, **kwargs: fake)

    async def run_call():
        with pytest.raises(ProviderExecutionError) as exc_info:
            await planner_agent.PlannerAgent().plan(task)
        assert exc_info.value.error_code == "provider_structured_output_invalid"

    asyncio.run(run_call())
    assert fake.close_count == 1


def test_bad_provider_snapshot_never_repins_current_global():
    task = _pinned_task()
    task.llm_provider_snapshot = "not-json"

    with pytest.raises(ProviderExecutionError) as exc_info:
        task.provider_execution_config()

    assert exc_info.value.error_code == "provider_snapshot_invalid"
    assert task.llm_provider == "grok"


def test_provider_snapshot_shape_and_selection_mismatch_fail_closed():
    task = _pinned_task()
    task.llm_provider_snapshot = {"provider_key": "grok"}

    with pytest.raises(ProviderExecutionError) as exc_info:
        task.provider_execution_config()

    assert exc_info.value.error_code == "provider_snapshot_invalid"


def test_provider_snapshot_revision_drift_fails_closed(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    task = _pinned_task()
    from app.services.agent.providers import registry as provider_registry

    original = provider_registry.ProviderRegistry.get_capabilities

    def drifted_capabilities(registry, provider_key):
        capabilities = original(registry, provider_key)
        return capabilities.model_copy(update={"config_revision": "sha256:drifted"})

    monkeypatch.setattr(provider_registry.ProviderRegistry, "get_capabilities", drifted_capabilities)

    with pytest.raises(ProviderExecutionError) as exc_info:
        task.provider_execution_config()

    assert exc_info.value.error_code == "provider_config_changed"


def _configured_openai_task_row(tmp_path, monkeypatch, *, snapshot=None):
    from app.services.agent import llm_client
    from app.services.agent.providers.registry import ProviderRegistry

    config_path = tmp_path / "auto-resume-models.json"
    config_path.write_text(
        json.dumps(
            {
                "provider_key": "openai",
                "providers": [
                    {
                        "provider_key": "openai",
                        "name": "OpenAI",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                        "default_model": "gpt-5.1",
                        "models": ["gpt-5.1"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(llm_client, "_MODEL_CONFIG_PATH", config_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    registry = ProviderRegistry()
    capabilities = registry.get_capabilities("openai")
    definition = registry.get_definition("openai")
    capability_snapshot = capabilities.model_dump(mode="json")
    capability_snapshot.update(
        {
            "default_model": definition.default_model,
            "provider_config_revision": capabilities.config_revision,
            "capability_snapshot_hash": _provider_capability_hash(capabilities),
        }
    )
    task = AgentTask(
        task_id="auto-resume-provider",
        status="interrupted",
        max_iterations=1,
        llm_provider="openai",
        llm_model="gpt-5.1",
        llm_provider_snapshot=snapshot or capability_snapshot,
    )
    return _task_payload(task)


def test_auto_resume_accepts_valid_snapshot_without_repin(monkeypatch, tmp_path):
    from app.api.v2.endpoints import agent as agent_endpoint

    row = _configured_openai_task_row(tmp_path, monkeypatch)

    class FakeDb:
        def __init__(self):
            self.saved = []

        def get_interrupted_agent_tasks(self, updated_at=None, limit=50):
            return [row]

        def get_agent_iterations(self, task_id):
            return []

        def save_agent_task(self, payload):
            self.saved.append(payload)

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    class Runner:
        def done(self):
            return True

    def fake_create_task(coro):
        coro.close()
        return Runner()

    monkeypatch.setattr(agent_endpoint.asyncio, "create_task", fake_create_task)

    resumed = asyncio.run(agent_endpoint.auto_resume_interrupted_agent_tasks("restart-1"))

    assert resumed == 1
    assert fake_db.saved
    agent_endpoint.orchestrator.tasks.pop("auto-resume-provider", None)
    agent_endpoint.orchestrator._runner_tasks.pop("auto-resume-provider", None)


@pytest.mark.parametrize("snapshot", ["not-json", json.dumps({"provider_key": "openai"})])
def test_auto_resume_rejects_bad_snapshot_without_repin(monkeypatch, tmp_path, snapshot):
    from app.api.v2.endpoints import agent as agent_endpoint

    row = _configured_openai_task_row(tmp_path, monkeypatch, snapshot=snapshot)

    class FakeDb:
        def __init__(self):
            self.status_updates = []

        def get_interrupted_agent_tasks(self, updated_at=None, limit=50):
            return [row]

        def get_agent_iterations(self, task_id):
            return []

        def save_agent_task(self, payload):
            raise AssertionError("bad snapshot must not be repinned or persisted")

        def update_agent_task_status(self, task_id, status, updated_at=None):
            self.status_updates.append((task_id, status))

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    resumed = asyncio.run(agent_endpoint.auto_resume_interrupted_agent_tasks("restart-bad"))

    assert resumed == 0
    assert fake_db.status_updates == [("auto-resume-provider", "failed")]


def test_auto_resume_rejects_drifted_snapshot(monkeypatch, tmp_path):
    from app.api.v2.endpoints import agent as agent_endpoint
    from app.services.agent.providers import registry as provider_registry

    row = _configured_openai_task_row(tmp_path, monkeypatch)
    original = provider_registry.ProviderRegistry.get_capabilities

    def drifted_capabilities(registry, provider_key):
        capabilities = original(registry, provider_key)
        return capabilities.model_copy(update={"config_revision": "sha256:drifted"})

    monkeypatch.setattr(provider_registry.ProviderRegistry, "get_capabilities", drifted_capabilities)

    class FakeDb:
        def __init__(self):
            self.status_updates = []

        def get_interrupted_agent_tasks(self, updated_at=None, limit=50):
            return [row]

        def get_agent_iterations(self, task_id):
            return []

        def save_agent_task(self, payload):
            raise AssertionError("drifted snapshot must not be repinned or persisted")

        def update_agent_task_status(self, task_id, status, updated_at=None):
            self.status_updates.append((task_id, status))

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    resumed = asyncio.run(agent_endpoint.auto_resume_interrupted_agent_tasks("restart-drift"))

    assert resumed == 0
    assert fake_db.status_updates == [("auto-resume-provider", "failed")]


@pytest.mark.parametrize(
    ("snapshot", "reasoning_effort", "speed_mode"),
    [
        ("not-json", "auto", "standard"),
        (None, "invalid", "standard"),
        (None, "auto", "invalid"),
    ],
)
def test_manual_resume_returns_sanitized_provider_error_and_marks_failed(
    monkeypatch, tmp_path, snapshot, reasoning_effort, speed_mode
):
    from app.api.v2.endpoints import agent as agent_endpoint

    row = _configured_openai_task_row(tmp_path, monkeypatch)
    if snapshot is not None:
        row["llm_provider_snapshot"] = snapshot
    row["llm_reasoning_effort"] = reasoning_effort
    row["llm_speed_mode"] = speed_mode

    class FakeDb:
        def __init__(self):
            self.status_updates = []

        def get_agent_task(self, task_id):
            return row

        def get_agent_iterations(self, task_id):
            return []

        def update_agent_task_status(self, task_id, status, updated_at=None):
            self.status_updates.append((task_id, status))

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    async def run_resume():
        with pytest.raises(agent_endpoint.HTTPException) as exc_info:
            await agent_endpoint.resume_task("auto-resume-provider")
        return exc_info.value

    error = asyncio.run(run_resume())

    assert error.status_code == 409
    assert error.detail["code"] in {"provider_snapshot_invalid", "provider_config_changed"}
    assert "traceback" not in json.dumps(error.detail).lower()
    assert fake_db.status_updates == [("auto-resume-provider", "failed")]


def test_manual_resume_drifted_snapshot_returns_controlled_error(monkeypatch, tmp_path):
    from app.api.v2.endpoints import agent as agent_endpoint
    from app.services.agent.providers import registry as provider_registry

    row = _configured_openai_task_row(tmp_path, monkeypatch)
    original = provider_registry.ProviderRegistry.get_capabilities

    def drifted_capabilities(registry, provider_key):
        capabilities = original(registry, provider_key)
        return capabilities.model_copy(update={"config_revision": "sha256:drifted"})

    monkeypatch.setattr(provider_registry.ProviderRegistry, "get_capabilities", drifted_capabilities)

    class FakeDb:
        def __init__(self):
            self.status_updates = []

        def get_agent_task(self, task_id):
            return row

        def get_agent_iterations(self, task_id):
            return []

        def update_agent_task_status(self, task_id, status, updated_at=None):
            self.status_updates.append((task_id, status))

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    async def run_resume():
        with pytest.raises(agent_endpoint.HTTPException) as exc_info:
            await agent_endpoint.resume_task("auto-resume-provider")
        return exc_info.value

    error = asyncio.run(run_resume())

    assert error.status_code == 409
    assert error.detail["code"] == "provider_config_changed"
    assert fake_db.status_updates == [("auto-resume-provider", "failed")]


@pytest.mark.parametrize("field", ["max_iterations", "score"])
def test_manual_resume_historical_data_error_is_not_provider_error(monkeypatch, tmp_path, field):
    from app.api.v2.endpoints import agent as agent_endpoint

    row = _configured_openai_task_row(tmp_path, monkeypatch)
    iterations = []
    if field == "max_iterations":
        row[field] = "not-an-integer"
    else:
        iterations = [{"iteration": 0, "score": "not-a-number"}]

    class FakeDb:
        def __init__(self):
            self.status_updates = []

        def get_agent_task(self, task_id):
            return row

        def get_agent_iterations(self, task_id):
            return iterations

        def update_agent_task_status(self, task_id, status, updated_at=None):
            self.status_updates.append((task_id, status))

    fake_db = FakeDb()
    monkeypatch.setattr(agent_endpoint, "db", fake_db)

    async def run_resume():
        with pytest.raises(agent_endpoint.HTTPException) as exc_info:
            await agent_endpoint.resume_task("auto-resume-provider")
        return exc_info.value

    error = asyncio.run(run_resume())

    assert error.status_code == 409
    assert error.detail["code"] == "task_state_invalid"
    assert error.detail["code"] != "provider_snapshot_invalid"
    assert fake_db.status_updates == [("auto-resume-provider", "failed")]


@pytest.mark.parametrize("corrupted_field", ["goal_criteria", "strategy_spec"])
def test_manual_resume_corrupted_task_json_is_sanitized_and_marks_failed(
    monkeypatch, tmp_path, corrupted_field
):
    from app.api.v2.endpoints import agent as agent_endpoint

    database = LocalDatabase(str(tmp_path / f"corrupt-{corrupted_field}.db"))
    database.init_db()
    task = _pinned_task()
    task.task_id = f"corrupt-{corrupted_field}"
    database.save_agent_task(_task_payload(task))

    connection = database.get_connection()
    connection.execute(
        f"UPDATE agent_tasks SET {corrupted_field} = ? WHERE id = ?",
        ("{not-valid-json", task.task_id),
    )
    connection.commit()
    monkeypatch.setattr(agent_endpoint, "db", database)

    async def run_resume():
        with pytest.raises(agent_endpoint.HTTPException) as exc_info:
            await agent_endpoint.resume_task(task.task_id)
        return exc_info.value

    error = asyncio.run(run_resume())

    assert error.status_code == 409
    assert error.detail["code"] == "task_state_invalid"
    assert error.detail["error_code"] == "task_state_invalid"
    assert "provider" not in json.dumps(error.detail).lower()
    assert "traceback" not in json.dumps(error.detail).lower()
    assert set(error.detail) == {"code", "error_code", "message"}

    row = connection.execute(
        "SELECT status FROM agent_tasks WHERE id = ?", (task.task_id,)
    ).fetchone()
    assert row["status"] == "failed"


def test_manual_resume_missing_task_keeps_404(monkeypatch):
    from app.api.v2.endpoints import agent as agent_endpoint

    class FakeDb:
        def get_agent_task(self, task_id):
            return None

    monkeypatch.setattr(agent_endpoint, "db", FakeDb())

    async def run_resume():
        with pytest.raises(agent_endpoint.HTTPException) as exc_info:
            await agent_endpoint.resume_task("missing-task")
        return exc_info.value

    error = asyncio.run(run_resume())
    assert error.status_code == 404


def test_orchestrator_provider_failure_marks_task_failed():
    orchestrator = AgentOrchestrator()
    task = AgentTask(task_id="provider-failure", max_iterations=1)

    class FailingPlanner:
        async def plan(self, task):
            raise ProviderExecutionError(
                "Provider 不可用",
                provider_key="grok",
                error_code="provider_execution_failed",
            )

    orchestrator._planner = FailingPlanner()
    orchestrator.register_task(task)

    async def run_task():
        with pytest.raises(ProviderExecutionError):
            await orchestrator.run_task(task.task_id)

    asyncio.run(run_task())
    assert task.status == "failed"
    assert task.stage == "failed"


def test_orchestrator_evaluator_provider_failure_never_meets_goal(monkeypatch):
    from app.services.agent.schemas import StrategySpec

    orchestrator = AgentOrchestrator()
    task = AgentTask(
        task_id="evaluator-provider-failure",
        max_iterations=1,
        strategy_spec=StrategySpec(recommended_approach="test"),
    )

    class Strategist:
        async def generate(self, **kwargs):
            return {
                "strategy_name": "test",
                "strategy_class_code": "class Test: pass",
                "stop_loss": 0.02,
                "reasoning": "test",
            }

    class Backtester:
        async def run(self, **kwargs):
            return {
                "metrics": {
                    "sharpe_ratio": 2.0,
                    "max_drawdown_pct": 1.0,
                    "win_rate_pct": 80.0,
                    "total_return_pct": 50.0,
                    "annual_return_pct": 50.0,
                    "total_trades": 100,
                    "profit_factor": 2.0,
                }
            }

    class FailingEvaluator:
        async def evaluate(self, **kwargs):
            raise ProviderExecutionError(
                "Provider 执行失败",
                provider_key="grok",
                error_code="provider_execution_failed",
            )

    orchestrator._strategist = Strategist()
    orchestrator._backtester = Backtester()
    orchestrator._evaluator = FailingEvaluator()
    orchestrator.register_task(task)

    async def run_task():
        with pytest.raises(ProviderExecutionError):
            await orchestrator.run_task(task.task_id)

    asyncio.run(run_task())
    assert task.status == "failed"
    assert task.stage == "failed"
    assert task.best_iteration is None


def test_orchestrator_does_not_complete_when_all_backtests_fail():
    orchestrator = AgentOrchestrator()
    task = AgentTask(
        task_id="backtest-failure",
        max_iterations=1,
        strategy_spec=copy.deepcopy(AgentTask(task_id="seed").strategy_spec),
    )

    class Planner:
        async def plan(self, task):
            from app.services.agent.schemas import StrategySpec

            return StrategySpec(recommended_approach="test")

    class Strategist:
        async def generate(self, **kwargs):
            return {
                "strategy_name": "test",
                "strategy_class_code": "class Test: pass",
                "reasoning": "test",
            }

    class Backtester:
        async def run(self, **kwargs):
            return {"metrics": {}, "error": "deterministic backtest failed"}

    orchestrator._planner = Planner()
    orchestrator._strategist = Strategist()
    orchestrator._backtester = Backtester()
    orchestrator.register_task(task)

    async def run_task():
        with pytest.raises(RuntimeError):
            await orchestrator.run_task(task.task_id)

    asyncio.run(run_task())
    assert task.status == "failed"
    assert task.stage == "failed"

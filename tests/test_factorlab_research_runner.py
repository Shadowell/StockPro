from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.local_db import LocalDatabase  # noqa: E402
from app.factorlab.research_models import FactorResearchTaskConfig  # noqa: E402
from app.factorlab.research_repository import FactorResearchRepository  # noqa: E402
from app.factorlab.research_runner import (  # noqa: E402
    FactorResearchRunner,
    HistoryBundle,
    KlineFactorHistoryLoader,
)
from app.factorlab.registry import FactorRegistry  # noqa: E402
from app.factorlab.validation import ValidationThresholds  # noqa: E402
from app.services.agent.providers.contracts import (  # noqa: E402
    ProviderCapabilities,
    capability_snapshot_hash,
)


HOUR_MS = 3_600_000


def history_bars(count: int = 180) -> list[dict]:
    rows = []
    close = 100.0
    for index in range(count):
        drift = 0.35 if (index // 12) % 2 == 0 else -0.25
        close = max(20.0, close + drift + (0.8 if index % 7 == 0 else -0.4 if index % 5 == 0 else 0.0))
        rows.append(
            {
                "event_time": 1_700_000_000_000 + index * HOUR_MS,
                "confirmed": True,
                "open": close - drift * 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100.0 + index % 20,
            }
        )
    return rows


class FixtureHistoryLoader:
    def load(self, config):
        return HistoryBundle(
            bars_by_symbol={symbol: history_bars() for symbol in config.symbols},
            dataset_revisions={symbol: "fixture-history-r1" for symbol in config.symbols},
        )


def setup(tmp_path: Path, *, repository_class=FactorResearchRepository):
    database = LocalDatabase(str(tmp_path / "factor-runner.db"))
    database.init_db()
    registry = FactorRegistry(database)
    registry.register_builtins()
    roc = registry.create_instance("momentum.roc", 1, {"window": 3})
    rsi = registry.create_instance("momentum.rsi", 1, {"window": 4})
    repo = repository_class(database)
    return repo, registry, roc, rsi


def manual_config(roc_id: str, rsi_id: str) -> FactorResearchTaskConfig:
    return FactorResearchTaskConfig(
        exchange="okx",
        market_type="swap",
        symbols=("BTC/USDT:USDT", "ETH/USDT:USDT"),
        timeframe="1h",
        start_ms=1_699_000_000_000,
        end_ms=1_800_000_000_000,
        mode="manual",
        factor_instance_ids=(roc_id, rsi_id),
        manual_combinations=(
            {
                "hypothesis": "ROC direction with RSI quality",
                "expression": {
                    "type": "weighted_sum",
                    "terms": [
                        {"weight": 0.7, "node": {"type": "factor", "instance_id": roc_id}},
                        {"weight": 0.3, "node": {"type": "factor", "instance_id": rsi_id}},
                    ],
                },
            },
        ),
        horizon_bars=3,
        base_cost_bps=20,
        stress_cost_bps=40,
        min_coverage=0.95,
        n_splits=2,
        max_candidates=10,
        max_runtime_sec=120,
        max_no_improvement=100,
        max_combination_leaves=4,
        target_accepted_candidates=100,
        random_seed=11,
    )


def relaxed_thresholds() -> ValidationThresholds:
    return ValidationThresholds(
        min_coverage=0.9,
        min_folds=2,
        min_profit_factor=0.1,
        max_drawdown=1.0,
        min_profitable_fold_ratio=0.0,
        max_symbol_concentration=1.0,
        min_score=0.0,
        min_stress_return=-1.0,
        max_stress_degradation=1.0,
    )


def pinned_provider_snapshot() -> dict:
    capability = ProviderCapabilities(
        provider_key="codex",
        display_name="Codex",
        transport_type="codex_cli",
        credential_mode="managed_login",
        credential_source="managed_login",
        models=["gpt-5.6-sol"],
        reasoning_efforts=["high"],
        speed_modes=["standard"],
        supports_structured_output=True,
        configured=True,
        healthy=True,
        command_available=True,
        login_verified=True,
        config_revision="sha256:provider-config",
    )
    snapshot = capability.model_dump(mode="json")
    snapshot.update(
        {
            "default_model": "gpt-5.6-sol",
            "provider_config_revision": capability.config_revision,
            "capability_snapshot_hash": capability_snapshot_hash(capability),
        }
    )
    return snapshot


def test_runner_builds_dataset_and_records_every_model_trial(tmp_path: Path) -> None:
    repo, registry, roc, rsi = setup(tmp_path)
    task = repo.create_task(manual_config(roc.instance_id, rsi.instance_id))
    runner = FactorResearchRunner(
        repository=repo,
        registry=registry,
        history_loader=FixtureHistoryLoader(),
        artifact_root=tmp_path / "artifacts",
        thresholds=relaxed_thresholds(),
    )

    completed = runner.run(task.task_id)
    trials = repo.list_trials(task.task_id)

    assert completed.status == "completed"
    assert completed.stop_reason == "search_exhausted"
    assert completed.dataset_snapshot_id
    assert completed.trial_cursor == 9
    assert len(trials) == 9
    assert {trial.model_type for trial in trials} == {"equal_weight", "ridge", "logistic"}
    assert {trial.ordinal for trial in trials} == set(range(9))
    assert all(trial.status in {"completed", "rejected", "failed"} for trial in trials)
    snapshot = repo.get_dataset_snapshot(completed.dataset_snapshot_id)
    assert Path(snapshot.artifact_path).exists()
    assert Path(snapshot.artifact_path).suffix == ".parquet"


def test_pause_is_hard_stop_and_resume_continues_without_duplicate_trial(tmp_path: Path) -> None:
    class PausingRepository(FactorResearchRepository):
        paused_once = False

        def append_trial(self, trial):
            super().append_trial(trial)
            if not self.paused_once:
                self.paused_once = True
                self.transition(trial.task_id, {"running"}, "paused", stop_reason="operator_paused")

    repo, registry, roc, rsi = setup(tmp_path, repository_class=PausingRepository)
    task = repo.create_task(manual_config(roc.instance_id, rsi.instance_id))
    runner = FactorResearchRunner(
        repository=repo,
        registry=registry,
        history_loader=FixtureHistoryLoader(),
        artifact_root=tmp_path / "artifacts",
        thresholds=relaxed_thresholds(),
    )

    paused = runner.run(task.task_id)
    assert paused.status == "paused"
    assert paused.trial_cursor == 1
    assert len(repo.list_trials(task.task_id)) == 1

    completed = runner.run(task.task_id)
    trials = repo.list_trials(task.task_id)
    assert completed.status == "completed"
    assert completed.trial_cursor == 9
    assert len(trials) == 9
    assert len({trial.trial_id for trial in trials}) == 9


def test_provider_failure_marks_auto_task_failed_without_baseline_fallback(tmp_path: Path) -> None:
    class FailingProposer:
        def propose(self, config, catalog):
            raise RuntimeError("provider unavailable")

    repo, registry, roc, rsi = setup(tmp_path)
    config = manual_config(roc.instance_id, rsi.instance_id)
    payload = config.to_dict()
    payload.update(
        {
            "mode": "auto",
            "manual_combinations": [],
            "provider_key": "codex",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "provider_snapshot": pinned_provider_snapshot(),
        }
    )
    task = repo.create_task(FactorResearchTaskConfig.from_dict(payload))
    runner = FactorResearchRunner(
        repository=repo,
        registry=registry,
        history_loader=FixtureHistoryLoader(),
        provider_proposer=FailingProposer(),
        artifact_root=tmp_path / "artifacts",
        thresholds=relaxed_thresholds(),
    )

    failed = runner.run(task.task_id)

    assert failed.status == "failed"
    assert failed.stop_reason == "factor_proposal_failed"
    assert repo.list_trials(task.task_id) == []


def test_production_history_loader_normalizes_numpy_scalars_and_excludes_open_bar() -> None:
    start = 1_700_000_000_000

    class FakeStore:
        def read_klines(self, exchange, symbol, timeframe, *, start_ms, end_ms):
            return [
                {
                    "timestamp": np.int64(start),
                    "open": np.float64(100),
                    "high": np.float64(101),
                    "low": np.float64(99),
                    "close": np.float64(100.5),
                    "volume": np.float64(10),
                },
                {
                    "timestamp": np.int64(start + HOUR_MS),
                    "open": np.float64(101),
                    "high": np.float64(102),
                    "low": np.float64(100),
                    "close": np.float64(101.5),
                    "volume": np.float64(11),
                },
            ]

    config = manual_config("momentum.roc@1:roc", "momentum.rsi@1:rsi")
    payload = config.to_dict()
    payload.update({"start_ms": start, "end_ms": start + 2 * HOUR_MS})
    normalized_config = FactorResearchTaskConfig.from_dict(payload)
    bundle = KlineFactorHistoryLoader(
        FakeStore(),
        clock_ms=lambda: start + 90 * 60 * 1000,
    ).load(normalized_config)

    restored = bundle.bars_by_symbol["BTC/USDT:USDT"]
    assert len(restored) == 1
    assert type(restored[0]["event_time"]) is int
    assert type(restored[0]["open"]) is float
    assert type(restored[0]["volume"]) is float
    assert restored[0]["confirmed"] is True
    assert bundle.dataset_revisions["BTC/USDT:USDT"].startswith("kline-sha256:")

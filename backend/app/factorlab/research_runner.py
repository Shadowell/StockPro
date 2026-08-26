"""Resumable FactorLab research orchestration over real historical bars."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd

from app.factorlab.combinations import FactorCombination
from app.factorlab.datasets import BuiltDataset, FactorDatasetBuilder
from app.factorlab.engine import FactorEngine
from app.factorlab.ml_models import FactorModelError, train_and_predict
from app.factorlab.proposals import (
    FactorProposal,
    FactorProposalError,
    FactorProposalProvider,
    resolve_factor_proposals,
)
from app.factorlab.registry import FactorRegistry
from app.factorlab.research_models import DatasetSnapshot, FactorResearchTask, FactorTrial
from app.factorlab.research_repository import FactorResearchRepository
from app.factorlab.validation import ValidationThresholds, evaluate_oos
from app.factorlab.walk_forward import PurgedWalkForwardSplitter
from app.services.kline_file_store import TIMEFRAME_MS, KlineFileStore, kline_store


class FactorResearchRunnerError(ValueError):
    """Raised for an invalid runner invocation, not a rejected trial."""


@dataclass(frozen=True)
class HistoryBundle:
    bars_by_symbol: Mapping[str, list[dict[str, Any]]]
    dataset_revisions: Mapping[str, str]


class FactorHistoryLoader(Protocol):
    def load(self, config) -> HistoryBundle: ...


class KlineFactorHistoryLoader:
    def __init__(self, store: KlineFileStore | None = None, *, clock_ms=None):
        self.store = store or kline_store
        self.clock_ms = clock_ms or (lambda: int(time.time() * 1000))

    def load(self, config) -> HistoryBundle:
        timeframe_ms = TIMEFRAME_MS.get(config.timeframe)
        if timeframe_ms is None:
            raise FactorResearchRunnerError(f"unsupported timeframe: {config.timeframe}")
        cutoff = self.clock_ms()
        by_symbol: dict[str, list[dict[str, Any]]] = {}
        revisions: dict[str, str] = {}
        for symbol in config.symbols:
            raw_rows = self.store.read_klines(
                config.exchange,
                symbol,
                config.timeframe,
                start_ms=config.start_ms,
                end_ms=config.end_ms,
            )
            rows: list[dict[str, Any]] = []
            for raw in raw_rows:
                event_time = int(raw.get("timestamp", -1))
                if event_time < 0 or event_time + timeframe_ms > cutoff:
                    continue
                rows.append(
                    {
                        "event_time": event_time,
                        "available_at": event_time + timeframe_ms,
                        "confirmed": True,
                        "open": float(raw["open"]),
                        "high": float(raw["high"]),
                        "low": float(raw["low"]),
                        "close": float(raw["close"]),
                        "volume": float(raw["volume"]),
                    }
                )
            encoded = json.dumps(
                rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            by_symbol[symbol] = rows
            revisions[symbol] = (
                f"kline-sha256:{digest}:rows={len(rows)}:"
                f"first={rows[0]['event_time'] if rows else 'none'}:"
                f"last={rows[-1]['event_time'] if rows else 'none'}"
            )
        return HistoryBundle(bars_by_symbol=by_symbol, dataset_revisions=revisions)


class FactorResearchRunner:
    MODEL_TYPES = ("equal_weight", "ridge", "logistic")

    def __init__(
        self,
        *,
        repository: FactorResearchRepository,
        registry: FactorRegistry,
        history_loader: FactorHistoryLoader | None = None,
        provider_proposer: FactorProposalProvider | None = None,
        artifact_root: Path | str | None = None,
        thresholds: ValidationThresholds | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.history_loader = history_loader or KlineFactorHistoryLoader()
        self.provider_proposer = provider_proposer
        project_root = Path(__file__).resolve().parents[3]
        self.artifact_root = (
            Path(artifact_root)
            if artifact_root is not None
            else project_root / "data" / "factors" / "experiments"
        )
        self.thresholds = thresholds or ValidationThresholds()

    def run(self, task_id: str) -> FactorResearchTask:
        task = self.repository.get_task(task_id)
        if task.status == "queued":
            task = self.repository.transition(task_id, {"queued"}, "running")
        elif task.status == "paused":
            task = self.repository.transition(task_id, {"paused"}, "running")
        else:
            raise FactorResearchRunnerError(
                f"factor research task cannot start from status: {task.status}"
            )
        started = time.monotonic()
        try:
            return self._run_active(task, started=started)
        except FactorProposalError:
            return self._fail_running_task(task_id, "factor_proposal_failed")
        except Exception:
            return self._fail_running_task(task_id, "research_execution_failed")

    def _run_active(self, task: FactorResearchTask, *, started: float) -> FactorResearchTask:
        config = task.config
        instances = [self.registry.get_instance(instance_id) for instance_id in config.factor_instance_ids]
        catalog = []
        for instance in instances:
            definition = self.registry.get_definition(
                instance.definition_id,
                instance.definition_version,
            )
            catalog.append(
                {
                    "instance_id": instance.instance_id,
                    "definition_id": definition.definition_id,
                    "definition_version": definition.definition_version,
                    "display_name": definition.display_name,
                    "family": definition.family,
                    "role": definition.role,
                    "parameters": dict(instance.parameters),
                }
            )
        history = self.history_loader.load(config)
        dataset = FactorDatasetBuilder(FactorEngine(self.registry)).build(
            config,
            instances,
            history.bars_by_symbol,
            dataset_revisions=history.dataset_revisions,
        )
        self._persist_dataset(task.task_id, dataset)
        task = self.repository.get_task(task.task_id)

        proposed = resolve_factor_proposals(
            config,
            catalog,
            provider_proposer=self.provider_proposer,
        )
        proposals = self._with_single_factor_baselines(config, proposed)
        trial_plan = [
            (proposal, model_type)
            for proposal in proposals[: config.max_candidates]
            for model_type in self.MODEL_TYPES
        ]
        if task.trial_cursor > len(trial_plan):
            raise FactorResearchRunnerError("trial cursor exceeds the deterministic plan")
        best_score, best_trial_id, no_improvement, accepted_count = self._existing_progress(
            task.task_id
        )
        for ordinal in range(task.trial_cursor, len(trial_plan)):
            current = self.repository.get_task(task.task_id)
            if current.status == "paused":
                return current
            if current.status != "running":
                raise FactorResearchRunnerError("research task left running state unexpectedly")
            if time.monotonic() - started >= config.max_runtime_sec:
                return self.repository.transition(
                    task.task_id,
                    {"running"},
                    "completed",
                    stop_reason="time_budget_exhausted",
                )
            proposal, model_type = trial_plan[ordinal]
            trial = self._execute_trial(
                task_id=task.task_id,
                ordinal=ordinal,
                proposal=proposal,
                model_type=model_type,
                dataset=dataset,
                config=config,
            )
            self.repository.append_trial(trial)
            score = float(trial.metrics.get("score", float("-inf")))
            if score > best_score:
                best_score = score
                best_trial_id = trial.trial_id
                no_improvement = 0
            else:
                no_improvement += 1
            if bool(trial.metrics.get("accepted")):
                accepted_count += 1
            self.repository.update_progress(
                task.task_id,
                trial_cursor=ordinal + 1,
                best_trial_id=best_trial_id,
            )
            if accepted_count >= config.target_accepted_candidates:
                return self.repository.transition(
                    task.task_id,
                    {"running"},
                    "completed",
                    stop_reason="accepted_target_reached",
                )
            if no_improvement >= config.max_no_improvement:
                return self.repository.transition(
                    task.task_id,
                    {"running"},
                    "completed",
                    stop_reason="no_improvement_budget_exhausted",
                )
        return self.repository.transition(
            task.task_id,
            {"running"},
            "completed",
            stop_reason="search_exhausted",
        )

    def _persist_dataset(self, task_id: str, dataset: BuiltDataset) -> None:
        task = self.repository.get_task(task_id)
        destination_dir = self.artifact_root / task_id / dataset.snapshot_id
        destination_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        artifact_path = destination_dir / "dataset.parquet"
        manifest_path = destination_dir / "manifest.json"
        if task.dataset_snapshot_id is not None:
            if task.dataset_snapshot_id != dataset.snapshot_id:
                raise FactorResearchRunnerError("resumed task dataset snapshot changed")
            stored = self.repository.get_dataset_snapshot(dataset.snapshot_id)
            if dict(stored.manifest) != dict(dataset.manifest) or not Path(stored.artifact_path).exists():
                raise FactorResearchRunnerError("resumed task dataset evidence is unavailable")
            return
        temp_artifact = artifact_path.with_suffix(".parquet.tmp")
        temp_manifest = manifest_path.with_suffix(".json.tmp")
        dataset.frame.to_parquet(temp_artifact, index=False)
        temp_manifest.write_text(
            json.dumps(dataset.manifest, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temp_artifact.replace(artifact_path)
        temp_manifest.replace(manifest_path)
        snapshot = DatasetSnapshot(
            snapshot_id=dataset.snapshot_id,
            task_id=task_id,
            manifest=dict(dataset.manifest),
            artifact_path=str(artifact_path),
            row_count=len(dataset.frame),
            feature_count=len(dataset.feature_ids),
        )
        self.repository.save_dataset_snapshot(snapshot)
        self.repository.update_progress(task_id, dataset_snapshot_id=dataset.snapshot_id)

    @staticmethod
    def _with_single_factor_baselines(
        config,
        proposals: list[FactorProposal],
    ) -> list[FactorProposal]:
        candidates = [
            FactorProposal(
                hypothesis=f"单因子基线：{instance_id}",
                combination=FactorCombination.from_payload(
                    {"type": "factor", "instance_id": instance_id},
                    set(config.factor_instance_ids),
                    max_leaves=config.max_combination_leaves,
                ),
                source="system_baseline",
            )
            for instance_id in config.factor_instance_ids
        ]
        candidates.extend(proposals)
        unique: list[FactorProposal] = []
        seen: set[str] = set()
        for proposal in candidates:
            if proposal.combination.semantic_hash in seen:
                continue
            seen.add(proposal.combination.semantic_hash)
            unique.append(proposal)
        return unique

    def _execute_trial(
        self,
        *,
        task_id: str,
        ordinal: int,
        proposal: FactorProposal,
        model_type: str,
        dataset: BuiltDataset,
        config,
    ) -> FactorTrial:
        identity = json.dumps(
            {
                "dataset_snapshot_id": dataset.snapshot_id,
                "combination_hash": proposal.combination.semantic_hash,
                "model_type": model_type,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        semantic_hash = "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
        trial_id = f"{task_id}:{ordinal:04d}:{model_type}"
        fold_manifests: list[dict[str, Any]] = []
        oos_frames: list[pd.DataFrame] = []
        try:
            folds = PurgedWalkForwardSplitter(
                n_splits=config.n_splits,
                purge_bars=config.horizon_bars,
                embargo_bars=config.horizon_bars,
                label_horizon_bars=config.horizon_bars,
            ).split(dataset.frame["decision_time"].tolist())
            for fold in folds:
                train = dataset.frame[
                    dataset.frame["decision_time"].isin(fold.train_times)
                ].copy()
                test = dataset.frame[
                    dataset.frame["decision_time"].isin(fold.test_times)
                ].copy()
                baseline = train_and_predict(
                    "equal_weight",
                    train,
                    test,
                    proposal.combination.factor_instance_ids,
                    seed=config.random_seed + fold.fold_index,
                )
                prediction = (
                    baseline
                    if model_type == "equal_weight"
                    else train_and_predict(
                        model_type,
                        train,
                        test,
                        proposal.combination.factor_instance_ids,
                        seed=config.random_seed + fold.fold_index,
                    )
                )
                evidence = test[
                    [
                        "symbol",
                        "decision_time",
                        "forward_long_net_return",
                        "forward_short_net_return",
                        "forward_long_stress_return",
                        "forward_short_stress_return",
                    ]
                ].copy()
                evidence.insert(0, "fold_index", fold.fold_index)
                evidence["prediction"] = prediction.values
                evidence["baseline_prediction"] = baseline.values
                oos_frames.append(evidence)
                fold_manifests.append(
                    {
                        "fold_index": fold.fold_index,
                        "train_time_start": fold.train_times[0],
                        "train_time_end": fold.train_times[-1],
                        "validation_time_start": fold.validation_times[0],
                        "validation_time_end": fold.validation_times[-1],
                        "test_time_start": fold.test_times[0],
                        "test_time_end": fold.test_times[-1],
                        "candidate_model": dict(prediction.manifest),
                        "baseline_model": dict(baseline.manifest),
                    }
                )
            report = evaluate_oos(
                pd.concat(oos_frames, ignore_index=True),
                coverage=float(dataset.manifest["coverage"]),
                thresholds=self.thresholds,
            )
            return FactorTrial(
                trial_id=trial_id,
                task_id=task_id,
                ordinal=ordinal,
                semantic_hash=semantic_hash,
                model_type=model_type,
                feature_ids=proposal.combination.factor_instance_ids,
                parameters={
                    "hypothesis": proposal.hypothesis,
                    "source": proposal.source,
                    "combination": dict(proposal.combination.canonical_payload),
                },
                status="completed" if report.accepted else "rejected",
                metrics=report.to_dict(),
                hard_gate_failures=report.hard_gate_failures,
                artifact_manifest={
                    "dataset_snapshot_id": dataset.snapshot_id,
                    "folds": fold_manifests,
                },
            )
        except FactorModelError as exc:
            return FactorTrial(
                trial_id=trial_id,
                task_id=task_id,
                ordinal=ordinal,
                semantic_hash=semantic_hash,
                model_type=model_type,
                feature_ids=proposal.combination.factor_instance_ids,
                parameters={
                    "hypothesis": proposal.hypothesis,
                    "source": proposal.source,
                    "combination": dict(proposal.combination.canonical_payload),
                },
                status="failed",
                metrics={},
                hard_gate_failures=("factor_model_error",),
                artifact_manifest={
                    "dataset_snapshot_id": dataset.snapshot_id,
                    "error_type": exc.__class__.__name__,
                },
            )

    def _existing_progress(self, task_id: str) -> tuple[float, str | None, int, int]:
        best_score = float("-inf")
        best_trial_id: str | None = None
        no_improvement = 0
        accepted_count = 0
        for trial in self.repository.list_trials(task_id):
            score = float(trial.metrics.get("score", float("-inf")))
            if score > best_score:
                best_score = score
                best_trial_id = trial.trial_id
                no_improvement = 0
            else:
                no_improvement += 1
            if bool(trial.metrics.get("accepted")):
                accepted_count += 1
        return best_score, best_trial_id, no_improvement, accepted_count

    def _fail_running_task(self, task_id: str, stop_reason: str) -> FactorResearchTask:
        current = self.repository.get_task(task_id)
        if current.status == "running":
            return self.repository.transition(
                task_id,
                {"running"},
                "failed",
                stop_reason=stop_reason,
            )
        return current

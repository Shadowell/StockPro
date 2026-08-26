from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.factorlab.proposals import (  # noqa: E402
    FactorProposalError,
    ResearchProviderFactorProposer,
    resolve_factor_proposals,
)
from app.factorlab.research_models import FactorResearchTaskConfig  # noqa: E402
from app.services.agent.providers.contracts import (  # noqa: E402
    ProviderCapabilities,
    ProviderRunResult,
    capability_snapshot_hash,
)


ADX = "trend.adx@1:adx"
RSI = "momentum.rsi@1:rsi"


def provider_snapshot() -> dict:
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
        status_detail="verified",
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


def task_config(*, mode: str, manual_combinations=()) -> FactorResearchTaskConfig:
    return FactorResearchTaskConfig(
        exchange="okx",
        market_type="swap",
        symbols=("BTC/USDT:USDT",),
        timeframe="1h",
        start_ms=1_700_000_000_000,
        end_ms=1_710_000_000_000,
        mode=mode,
        factor_instance_ids=(ADX, RSI),
        manual_combinations=tuple(manual_combinations),
        provider_key="" if mode == "manual" else "codex",
        model="" if mode == "manual" else "gpt-5.6-sol",
        reasoning_effort="high" if mode != "manual" else "auto",
        speed_mode="standard",
        provider_snapshot={} if mode == "manual" else provider_snapshot(),
        horizon_bars=3,
        n_splits=2,
        max_candidates=10,
        max_runtime_sec=60,
        max_no_improvement=5,
        max_combination_leaves=4,
    )


CATALOG = [
    {"instance_id": ADX, "definition_id": "trend.adx", "family": "trend_quality", "role": "alpha_quality"},
    {"instance_id": RSI, "definition_id": "momentum.rsi", "family": "momentum", "role": "alpha_quality"},
]


def test_manual_mode_validates_combinations_without_calling_provider() -> None:
    manual = [
        {
            "hypothesis": "trend quality plus momentum",
            "expression": {
                "type": "weighted_sum",
                "terms": [
                    {"weight": 0.4, "node": {"type": "factor", "instance_id": ADX}},
                    {"weight": 0.6, "node": {"type": "factor", "instance_id": RSI}},
                ],
            },
        }
    ]

    proposals = resolve_factor_proposals(task_config(mode="manual", manual_combinations=manual), CATALOG)

    assert len(proposals) == 1
    assert proposals[0].source == "manual"
    assert proposals[0].hypothesis == "trend quality plus momentum"
    assert proposals[0].combination.factor_instance_ids == (RSI, ADX)


def test_auto_mode_uses_pinned_provider_and_strict_structured_output() -> None:
    captured = {}

    class FakeClient:
        async def run(self, request):
            captured["request"] = request
            return ProviderRunResult(
                provider_key="codex",
                model="gpt-5.6-sol",
                text="",
                structured={
                    "combinations": [
                        {
                            "hypothesis": "ADX confirms RSI momentum",
                            "terms": [
                                {"instance_id": ADX, "weight": 0.25},
                                {"instance_id": RSI, "weight": 0.75},
                            ],
                        }
                    ]
                },
                duration_ms=3,
            )

        async def close(self):
            captured["closed"] = True

    proposer = ResearchProviderFactorProposer(
        client_factory=lambda execution, capabilities: FakeClient()
    )

    proposals = resolve_factor_proposals(
        task_config(mode="auto"),
        CATALOG,
        provider_proposer=proposer,
    )

    assert len(proposals) == 1
    assert proposals[0].source == "provider"
    assert proposals[0].combination.evaluate_row({ADX: 20.0, RSI: 60.0}) == 50.0
    assert captured["request"].execution.provider_key == "codex"
    assert captured["request"].execution.model == "gpt-5.6-sol"
    assert captured["request"].response_schema["additionalProperties"] is False
    assert "Paper" not in captured["request"].messages[-1]["content"]
    assert captured["closed"] is True


def test_provider_unknown_factor_or_malformed_output_fails_without_local_fallback() -> None:
    class FakeClient:
        async def run(self, request):
            return ProviderRunResult(
                provider_key="codex",
                model="gpt-5.6-sol",
                text="",
                structured={
                    "combinations": [
                        {
                            "hypothesis": "unknown feature",
                            "terms": [{"instance_id": "unknown.factor", "weight": 1.0}],
                        }
                    ]
                },
                duration_ms=1,
            )

        async def close(self):
            return None

    proposer = ResearchProviderFactorProposer(
        client_factory=lambda execution, capabilities: FakeClient()
    )

    with pytest.raises(FactorProposalError, match="allowlist"):
        resolve_factor_proposals(
            task_config(mode="auto"),
            CATALOG,
            provider_proposer=proposer,
        )


def test_auto_and_hybrid_modes_fail_closed_when_provider_fails() -> None:
    class FailingProposer:
        def propose(self, config, catalog):
            raise RuntimeError("provider unavailable")

    for mode in ("auto", "hybrid"):
        manual = (
            {
                "hypothesis": "manual should not become fallback",
                "expression": {"type": "factor", "instance_id": ADX},
            },
        ) if mode == "hybrid" else ()
        with pytest.raises(FactorProposalError, match="failed"):
            resolve_factor_proposals(
                task_config(mode=mode, manual_combinations=manual),
                CATALOG,
                provider_proposer=FailingProposer(),
            )


def test_manual_mode_requires_at_least_one_combination() -> None:
    with pytest.raises(ValueError, match="manual"):
        task_config(mode="manual")

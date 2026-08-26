"""Provider and manual factor-combination proposals behind one strict contract."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence

from app.factorlab.combinations import (
    FactorCombination,
    FactorCombinationError,
)
from app.factorlab.research_models import FactorResearchTaskConfig
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderExecutionConfig,
    ProviderRunRequest,
)


class FactorProposalError(ValueError):
    """Raised when a proposal cannot satisfy the task's finite factor contract."""


@dataclass(frozen=True)
class FactorProposal:
    hypothesis: str
    combination: FactorCombination
    source: str


class FactorProposalProvider(Protocol):
    def propose(
        self,
        config: FactorResearchTaskConfig,
        catalog: Sequence[Mapping[str, Any]],
    ) -> list[FactorProposal]: ...


PROPOSAL_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["combinations"],
    "properties": {
        "combinations": {
            "type": "array",
            "minItems": 1,
            "maxItems": 200,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["hypothesis", "terms"],
                "properties": {
                    "hypothesis": {"type": "string", "minLength": 1, "maxLength": 500},
                    "terms": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["instance_id", "weight"],
                            "properties": {
                                "instance_id": {"type": "string", "minLength": 1, "maxLength": 256},
                                "weight": {"type": "number", "minimum": -10.0, "maximum": 10.0},
                            },
                        },
                    },
                },
            },
        }
    },
}


class ResearchProviderFactorProposer:
    def __init__(self, *, client_factory: Callable[..., Any] | None = None):
        self._client_factory = client_factory

    def propose(
        self,
        config: FactorResearchTaskConfig,
        catalog: Sequence[Mapping[str, Any]],
    ) -> list[FactorProposal]:
        return asyncio.run(self._propose_async(config, catalog))

    async def _propose_async(
        self,
        config: FactorResearchTaskConfig,
        catalog: Sequence[Mapping[str, Any]],
    ) -> list[FactorProposal]:
        snapshot = dict(config.provider_snapshot)
        capabilities = ProviderCapabilities.model_validate(snapshot)
        execution = ProviderExecutionConfig(
            provider_key=config.provider_key,
            model=config.model,
            reasoning_effort=config.reasoning_effort,
            speed_mode=config.speed_mode,
            provider_config_revision=str(snapshot.get("provider_config_revision") or ""),
            capability_snapshot_hash=str(snapshot.get("capability_snapshot_hash") or ""),
        )
        if self._client_factory is None:
            from app.services.agent.providers import get_research_provider_client

            client = get_research_provider_client(
                execution,
                capabilities_override=capabilities,
            )
        else:
            client = self._client_factory(execution, capabilities)
        prompt = (
            "请从给定的连续因子目录提出可检验的加权组合。"
            "只能使用目录中的 instance_id；不得添加指标、代码、数据或执行动作。"
            "每个组合最多使用任务允许的叶子数，权重范围为 -10 到 10。\n"
            f"任务最大叶子数: {config.max_combination_leaves}\n"
            f"因子目录: {json.dumps(list(catalog), ensure_ascii=False, sort_keys=True)}"
        )
        try:
            result = await client.run(
                ProviderRunRequest(
                    messages=[
                        {"role": "system", "content": "你是因子研究假设生成器，只返回 Schema 要求的 JSON。"},
                        {"role": "user", "content": prompt},
                    ],
                    execution=execution,
                    response_schema=PROPOSAL_RESPONSE_SCHEMA,
                    max_output_tokens=4096,
                    timeout_sec=240,
                    max_retries=1,
                )
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                closed = close()
                if hasattr(closed, "__await__"):
                    await closed
        payload = getattr(result, "structured", None)
        if not isinstance(payload, Mapping) or not isinstance(payload.get("combinations"), list):
            raise FactorProposalError("Provider factor proposal is not structured")
        allowed = set(config.factor_instance_ids)
        proposals: list[FactorProposal] = []
        for item in payload["combinations"][: config.max_candidates]:
            if not isinstance(item, Mapping):
                raise FactorProposalError("Provider factor proposal item is invalid")
            hypothesis = str(item.get("hypothesis") or "").strip()
            terms = item.get("terms")
            if not hypothesis or not isinstance(terms, list):
                raise FactorProposalError("Provider factor proposal fields are invalid")
            expression = {
                "type": "weighted_sum",
                "terms": [
                    {
                        "weight": term.get("weight") if isinstance(term, Mapping) else None,
                        "node": {
                            "type": "factor",
                            "instance_id": term.get("instance_id") if isinstance(term, Mapping) else None,
                        },
                    }
                    for term in terms
                ],
            }
            try:
                combination = FactorCombination.from_payload(
                    expression,
                    allowed,
                    max_leaves=config.max_combination_leaves,
                )
            except FactorCombinationError as exc:
                raise FactorProposalError(str(exc)) from exc
            proposals.append(
                FactorProposal(
                    hypothesis=hypothesis,
                    combination=combination,
                    source="provider",
                )
            )
        if not proposals:
            raise FactorProposalError("Provider returned no factor combinations")
        return proposals


def _manual_proposals(config: FactorResearchTaskConfig) -> list[FactorProposal]:
    proposals: list[FactorProposal] = []
    for item in config.manual_combinations:
        hypothesis = str(item.get("hypothesis") or "").strip()
        expression = item.get("expression")
        if not hypothesis or not isinstance(expression, Mapping):
            raise FactorProposalError("manual factor proposal fields are invalid")
        try:
            combination = FactorCombination.from_payload(
                expression,
                set(config.factor_instance_ids),
                max_leaves=config.max_combination_leaves,
            )
        except FactorCombinationError as exc:
            raise FactorProposalError(str(exc)) from exc
        proposals.append(
            FactorProposal(
                hypothesis=hypothesis,
                combination=combination,
                source="manual",
            )
        )
    return proposals


def resolve_factor_proposals(
    config: FactorResearchTaskConfig,
    catalog: Sequence[Mapping[str, Any]],
    *,
    provider_proposer: FactorProposalProvider | None = None,
) -> list[FactorProposal]:
    catalog_ids = [str(item.get("instance_id") or "") for item in catalog]
    if len(catalog_ids) != len(set(catalog_ids)) or set(catalog_ids) != set(config.factor_instance_ids):
        raise FactorProposalError("factor catalog does not match the task allowlist")
    proposals = _manual_proposals(config) if config.mode in {"manual", "hybrid"} else []
    if config.mode in {"auto", "hybrid"}:
        if provider_proposer is None:
            raise FactorProposalError("Provider factor proposal failed")
        try:
            provider_results = provider_proposer.propose(config, catalog)
        except FactorProposalError:
            raise
        except Exception as exc:
            raise FactorProposalError("Provider factor proposal failed") from exc
        proposals.extend(provider_results)
    unique: list[FactorProposal] = []
    seen: set[str] = set()
    for proposal in proposals:
        if proposal.combination.semantic_hash in seen:
            continue
        seen.add(proposal.combination.semantic_hash)
        unique.append(proposal)
        if len(unique) >= config.max_candidates:
            break
    if not unique:
        raise FactorProposalError("factor proposal set is empty")
    return unique

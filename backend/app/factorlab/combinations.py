"""Safe, canonical FactorLab combination AST without dynamic code execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping


class FactorCombinationError(ValueError):
    """Raised when a combination leaves the finite audited AST."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _finite_number(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FactorCombinationError(f"{field_name} must be numeric")
    normalized = float(value)
    if not isfinite(normalized):
        raise FactorCombinationError(f"{field_name} must be finite")
    return normalized


def _exact_keys(node: Mapping[str, Any], expected: set[str], *, node_type: str) -> None:
    if set(node) != expected:
        raise FactorCombinationError(f"{node_type} node fields are invalid")


def _canonicalize_node(
    raw: Any,
    *,
    allowed_instance_ids: frozenset[str],
) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(raw, Mapping):
        raise FactorCombinationError("combination node must be an object")
    node_type = str(raw.get("type") or "")
    if node_type == "factor":
        _exact_keys(raw, {"type", "instance_id"}, node_type=node_type)
        instance_id = str(raw.get("instance_id") or "").strip()
        if instance_id not in allowed_instance_ids:
            raise FactorCombinationError("factor instance is outside the task allowlist")
        return {"type": "factor", "instance_id": instance_id}, [instance_id]

    if node_type == "weighted_sum":
        _exact_keys(raw, {"type", "terms"}, node_type=node_type)
        terms = raw.get("terms")
        if not isinstance(terms, list) or not terms:
            raise FactorCombinationError("weighted_sum terms must be a non-empty list")
        canonical_terms: list[dict[str, Any]] = []
        leaves: list[str] = []
        for term in terms:
            if not isinstance(term, Mapping):
                raise FactorCombinationError("weighted_sum term must be an object")
            _exact_keys(term, {"weight", "node"}, node_type="weighted_sum term")
            child, child_leaves = _canonicalize_node(
                term["node"],
                allowed_instance_ids=allowed_instance_ids,
            )
            canonical_terms.append(
                {
                    "weight": _finite_number(term["weight"], field_name="weight"),
                    "node": child,
                }
            )
            leaves.extend(child_leaves)
        canonical_terms.sort(key=_json)
        return {"type": "weighted_sum", "terms": canonical_terms}, leaves

    if node_type == "family_average":
        _exact_keys(raw, {"type", "nodes"}, node_type=node_type)
        nodes = raw.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise FactorCombinationError("family_average nodes must be a non-empty list")
        canonical_nodes: list[dict[str, Any]] = []
        leaves: list[str] = []
        for item in nodes:
            child, child_leaves = _canonicalize_node(
                item,
                allowed_instance_ids=allowed_instance_ids,
            )
            canonical_nodes.append(child)
            leaves.extend(child_leaves)
        canonical_nodes.sort(key=_json)
        return {"type": "family_average", "nodes": canonical_nodes}, leaves

    if node_type == "clip":
        _exact_keys(raw, {"type", "minimum", "maximum", "node"}, node_type=node_type)
        minimum = _finite_number(raw["minimum"], field_name="minimum")
        maximum = _finite_number(raw["maximum"], field_name="maximum")
        if minimum > maximum:
            raise FactorCombinationError("clip minimum cannot exceed maximum")
        child, leaves = _canonicalize_node(
            raw["node"],
            allowed_instance_ids=allowed_instance_ids,
        )
        return {
            "type": "clip",
            "minimum": minimum,
            "maximum": maximum,
            "node": child,
        }, leaves

    if node_type == "condition":
        _exact_keys(
            raw,
            {"type", "factor", "operator", "threshold", "if_true", "if_false"},
            node_type=node_type,
        )
        operator = str(raw.get("operator") or "")
        if operator not in {"gt", "gte", "lt", "lte"}:
            raise FactorCombinationError("condition operator is not allowlisted")
        factor, factor_leaves = _canonicalize_node(
            raw["factor"],
            allowed_instance_ids=allowed_instance_ids,
        )
        if factor["type"] != "factor":
            raise FactorCombinationError("condition factor must be a factor leaf")
        if_true, true_leaves = _canonicalize_node(
            raw["if_true"],
            allowed_instance_ids=allowed_instance_ids,
        )
        if_false, false_leaves = _canonicalize_node(
            raw["if_false"],
            allowed_instance_ids=allowed_instance_ids,
        )
        return {
            "type": "condition",
            "factor": factor,
            "operator": operator,
            "threshold": _finite_number(raw["threshold"], field_name="threshold"),
            "if_true": if_true,
            "if_false": if_false,
        }, [*factor_leaves, *true_leaves, *false_leaves]

    raise FactorCombinationError(f"combination node type is not allowlisted: {node_type!r}")


def _evaluate(node: Mapping[str, Any], values: Mapping[str, Any]) -> float | None:
    node_type = node["type"]
    if node_type == "factor":
        raw = values.get(node["instance_id"])
        if raw is None:
            return None
        value = float(raw)
        return value if isfinite(value) else None
    if node_type == "weighted_sum":
        total = 0.0
        for term in node["terms"]:
            value = _evaluate(term["node"], values)
            if value is None:
                return None
            total += float(term["weight"]) * value
        return total
    if node_type == "family_average":
        evaluated = [_evaluate(child, values) for child in node["nodes"]]
        if any(value is None for value in evaluated):
            return None
        return sum(float(value) for value in evaluated) / len(evaluated)
    if node_type == "clip":
        value = _evaluate(node["node"], values)
        if value is None:
            return None
        return min(max(value, float(node["minimum"])), float(node["maximum"]))
    if node_type == "condition":
        value = _evaluate(node["factor"], values)
        if value is None:
            return None
        threshold = float(node["threshold"])
        matched = {
            "gt": value > threshold,
            "gte": value >= threshold,
            "lt": value < threshold,
            "lte": value <= threshold,
        }[node["operator"]]
        return _evaluate(node["if_true"] if matched else node["if_false"], values)
    raise FactorCombinationError(f"unsupported canonical node: {node_type}")


@dataclass(frozen=True)
class FactorCombination:
    canonical_payload: Mapping[str, Any]
    semantic_hash: str
    factor_instance_ids: tuple[str, ...]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        allowed_instance_ids: set[str] | frozenset[str],
        *,
        max_leaves: int = 8,
    ) -> "FactorCombination":
        allowed = frozenset(str(item) for item in allowed_instance_ids)
        canonical, leaves = _canonicalize_node(payload, allowed_instance_ids=allowed)
        if len(leaves) > int(max_leaves):
            raise FactorCombinationError("combination exceeds the maximum leaves budget")
        encoded = _json(canonical)
        return cls(
            canonical_payload=canonical,
            semantic_hash="sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            factor_instance_ids=tuple(sorted(set(leaves))),
        )

    def evaluate_row(self, values: Mapping[str, Any]) -> float | None:
        return _evaluate(self.canonical_payload, values)

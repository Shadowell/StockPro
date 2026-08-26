"""SQLite-backed immutable FactorLab registry."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import List

from app.db.local_db import LocalDatabase
from app.factorlab.builtins import builtin_factor_definitions
from app.factorlab.expressions import validate_factor_expression
from app.factorlab.kernels import get_factor_kernel
from app.factorlab.models import FactorDefinition, FactorInstance
from app.factorlab.parameters import normalize_parameters, required_bars_for


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class ImmutableFactorDefinitionError(ValueError):
    """Raised when an existing definition version would be overwritten."""


class InvalidFactorImplementationHashError(ValueError):
    """Raised when definition metadata does not match its kernel and AST."""


class FactorRegistry:
    def __init__(self, database: LocalDatabase):
        self.database = database

    def register_builtins(self) -> None:
        for definition in builtin_factor_definitions():
            self.register_definition(definition)

    def register_definition(self, definition: FactorDefinition) -> None:
        get_factor_kernel(definition.kernel_name)
        validate_factor_expression(
            definition.expression,
            allowed_parameters=set(definition.parameter_schema),
        )
        implementation_payload = _canonical_json(
            {
                "kernel_name": definition.kernel_name,
                "expression": definition.expression,
            }
        )
        expected_hash = hashlib.sha256(implementation_payload.encode("utf-8")).hexdigest()
        if definition.implementation_hash != expected_hash:
            raise InvalidFactorImplementationHashError(
                f"factor implementation_hash mismatch: {definition.definition_id}"
            )
        existing_row = self.database.get_connection().execute(
            """
            SELECT * FROM factor_definitions
            WHERE definition_id = ? AND definition_version = ?
            """,
            (definition.definition_id, definition.definition_version),
        ).fetchone()
        if existing_row is not None:
            if self._definition_from_row(existing_row) != definition:
                raise ImmutableFactorDefinitionError(
                    "factor definition versions are immutable: "
                    f"{definition.definition_id}@{definition.definition_version}"
                )
            return

        now = datetime.now(timezone.utc).isoformat()
        self.database.get_connection().execute(
            """
            INSERT INTO factor_definitions (
                definition_id, definition_version, display_name, family, role,
                description, kernel_name, expression_json, inputs_json,
                parameter_schema_json, lookback_bars, availability, orientation,
                missing_policy, valid_min, valid_max, implementation_hash, status,
                metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                definition.definition_id,
                definition.definition_version,
                definition.display_name,
                definition.family,
                definition.role,
                definition.description,
                definition.kernel_name,
                _canonical_json(definition.expression),
                _canonical_json(list(definition.inputs)),
                _canonical_json(definition.parameter_schema),
                definition.lookback_bars,
                definition.availability,
                definition.orientation,
                definition.missing_policy,
                definition.valid_min,
                definition.valid_max,
                definition.implementation_hash,
                definition.status,
                _canonical_json(definition.metadata),
                now,
            ),
        )
        self.database.get_connection().commit()

    def list_definitions(self) -> List[FactorDefinition]:
        rows = self.database.get_connection().execute(
            """
            SELECT * FROM factor_definitions
            ORDER BY definition_id, definition_version
            """
        ).fetchall()
        return [self._definition_from_row(row) for row in rows]

    def get_definition(self, definition_id: str, definition_version: int) -> FactorDefinition:
        row = self.database.get_connection().execute(
            """
            SELECT * FROM factor_definitions
            WHERE definition_id = ? AND definition_version = ?
            """,
            (definition_id, definition_version),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown factor definition: {definition_id}@{definition_version}")
        return self._definition_from_row(row)

    def create_instance(
        self,
        definition_id: str,
        definition_version: int,
        parameters,
    ) -> FactorInstance:
        definition = self.get_definition(definition_id, definition_version)
        normalized = normalize_parameters(definition, parameters)
        parameters_json = _canonical_json(normalized)
        parameter_hash = hashlib.sha256(parameters_json.encode("utf-8")).hexdigest()
        identity = f"{definition_id}@{definition_version}:{parameters_json}"
        identity_hash = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        instance_id = f"{definition_id}@{definition_version}:{identity_hash}"
        required_bars = required_bars_for(definition.kernel_name, normalized)
        self.database.get_connection().execute(
            """
            INSERT OR IGNORE INTO factor_instances (
                instance_id, definition_id, definition_version, parameters_json,
                parameter_hash, required_bars, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                definition_id,
                definition_version,
                parameters_json,
                parameter_hash,
                required_bars,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.database.get_connection().commit()
        return self.get_instance(instance_id)

    def get_instance(self, instance_id: str) -> FactorInstance:
        row = self.database.get_connection().execute(
            "SELECT * FROM factor_instances WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"unknown factor instance: {instance_id}")
        values = dict(row)
        return FactorInstance(
            instance_id=values["instance_id"],
            definition_id=values["definition_id"],
            definition_version=int(values["definition_version"]),
            parameters=json.loads(values["parameters_json"]),
            parameter_hash=values["parameter_hash"],
            required_bars=int(values["required_bars"]),
        )

    @staticmethod
    def _definition_from_row(row) -> FactorDefinition:
        values = dict(row)
        return FactorDefinition(
            definition_id=values["definition_id"],
            definition_version=int(values["definition_version"]),
            display_name=values["display_name"],
            family=values["family"],
            role=values["role"],
            description=values["description"],
            kernel_name=values["kernel_name"],
            expression=json.loads(values["expression_json"]),
            inputs=tuple(json.loads(values["inputs_json"])),
            parameter_schema=json.loads(values["parameter_schema_json"]),
            lookback_bars=int(values["lookback_bars"]),
            availability=values["availability"],
            orientation=values["orientation"],
            missing_policy=values["missing_policy"],
            valid_min=values["valid_min"],
            valid_max=values["valid_max"],
            implementation_hash=values["implementation_hash"],
            status=values["status"],
            metadata=json.loads(values["metadata_json"]),
        )

import hashlib
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.agent.providers.contracts import (  # noqa: E402
    PROVIDER_CAPABILITY_V1,
    ProviderCapabilities,
    ProviderExecutionError,
    ProviderExecutionConfig,
    capability_hash_payload,
    capability_snapshot_hash,
    validate_provider_selection,
)
from app.services.agent.schemas import _provider_capability_hash, migrate_provider_snapshot  # noqa: E402


def _snapshot_capabilities() -> ProviderCapabilities:
    return ProviderCapabilities(
        provider_key="cursor",
        display_name="Cursor",
        transport_type="cursor_cli",
        credential_mode="managed_login",
        credential_source="cursor-profile",
        models=["gpt-5.6-sol", "gpt-5.6-terra"],
        reasoning_efforts=["medium", "high"],
        speed_modes=["standard", "fast"],
        supports_tools=True,
        supports_structured_output=True,
        supports_resume=True,
        configured=True,
        healthy=True,
        command_available=True,
        login_verified=True,
        status_detail="CLI 已发现，登录已验证",
        config_revision="sha256:revision-1",
        probed_at="2026-08-22T00:00:00Z",
    )


def test_capability_hash_payload_excludes_volatile_runtime_status_but_tracks_contract():
    capabilities = _snapshot_capabilities()
    original = _provider_capability_hash(capabilities)

    changed_runtime = capabilities.model_copy(
        update={
            "configured": False,
            "healthy": False,
            "command_available": False,
            "login_verified": False,
            "status_detail": "CLI 未发现",
            "probed_at": "2026-08-23T00:00:00Z",
            "error_code": "provider_probe_failed",
        }
    )
    assert _provider_capability_hash(changed_runtime) == original
    payload = capability_hash_payload(capabilities)
    assert all(
        field not in payload
        for field in (
            "configured",
            "healthy",
            "command_available",
            "login_verified",
            "status_detail",
            "probed_at",
            "error_code",
        )
    )

    for field, value in (
        ("provider_key", "cursor-alt"),
        ("display_name", "Cursor Next"),
        ("models", ["gpt-5.6-sol"]),
        ("transport_type", "xai_api"),
        ("credential_mode", "none"),
        ("credential_source", "none"),
        ("reasoning_efforts", ["high"]),
        ("speed_modes", ["standard"]),
        ("supports_tools", False),
        ("supports_structured_output", False),
        ("supports_resume", False),
        ("config_revision", "sha256:revision-2"),
        ("schema_version", PROVIDER_CAPABILITY_V1),
    ):
        changed = capabilities.model_copy(update={field: value})
        assert _provider_capability_hash(changed) != original, field


def _legacy_v1_snapshot(capabilities: ProviderCapabilities, *, include_runtime_fields: bool) -> dict:
    snapshot = capabilities.model_copy(update={"schema_version": PROVIDER_CAPABILITY_V1}).model_dump(mode="json")
    if not include_runtime_fields:
        snapshot.pop("command_available")
        snapshot.pop("login_verified")
    legacy_hash = "sha256:" + hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    snapshot.update(
        {
            "default_model": "gpt-5.6-terra",
            "provider_config_revision": capabilities.config_revision,
            "capability_snapshot_hash": legacy_hash,
        }
    )
    return snapshot


@pytest.mark.parametrize("include_runtime_fields", [False, True])
def test_legacy_v1_provider_snapshot_migrates_without_repinning_selection(include_runtime_fields):
    capabilities = _snapshot_capabilities()
    legacy = _legacy_v1_snapshot(capabilities, include_runtime_fields=include_runtime_fields)
    legacy["api_key"] = "must-not-persist"

    migrated = migrate_provider_snapshot(
        provider_key="cursor",
        model="gpt-5.6-terra",
        reasoning_effort="high",
        speed_mode="fast",
        snapshot=legacy,
    )

    assert migrated["schema_version"] == "provider-capability-v2"
    assert migrated["provider_key"] == "cursor"
    assert migrated["default_model"] == "gpt-5.6-terra"
    assert migrated["capability_snapshot_hash"] == _provider_capability_hash(
        ProviderCapabilities.model_validate(migrated)
    )
    assert "api_key" not in migrated
    assert migrate_provider_snapshot(
        provider_key="cursor",
        model="gpt-5.6-terra",
        reasoning_effort="high",
        speed_mode="fast",
        snapshot=migrated,
    ) == migrated


@pytest.mark.parametrize("schema_version", [0, False, "", " ", None, 1, "provider-capability-v3"])
def test_present_invalid_schema_version_is_rejected(schema_version):
    capabilities = _snapshot_capabilities()
    snapshot = capabilities.model_dump(mode="json")
    snapshot["schema_version"] = schema_version
    snapshot.update(
        {
            "default_model": "gpt-5.6-sol",
            "provider_config_revision": capabilities.config_revision,
            "capability_snapshot_hash": _provider_capability_hash(capabilities),
        }
    )

    with pytest.raises(ProviderExecutionError) as exc_info:
        migrate_provider_snapshot(
            provider_key="cursor",
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            speed_mode="standard",
            snapshot=snapshot,
        )
    assert exc_info.value.error_code == "provider_snapshot_invalid"


def test_missing_schema_version_defaults_to_v1_only_when_legacy_hash_matches():
    capabilities = _snapshot_capabilities()
    snapshot = _legacy_v1_snapshot(capabilities, include_runtime_fields=False)
    snapshot.pop("schema_version")

    migrated = migrate_provider_snapshot(
        provider_key="cursor",
        model="gpt-5.6-terra",
        reasoning_effort="high",
        speed_mode="fast",
        snapshot=snapshot,
    )
    assert migrated["schema_version"] == "provider-capability-v2"


def test_v1_hash_variant_does_not_accept_mixed_runtime_shape():
    capabilities = _snapshot_capabilities()
    snapshot = _legacy_v1_snapshot(capabilities, include_runtime_fields=False)
    snapshot.update({"command_available": False, "login_verified": None})

    with pytest.raises(ProviderExecutionError) as exc_info:
        migrate_provider_snapshot(
            provider_key="cursor",
            model="gpt-5.6-terra",
            reasoning_effort="high",
            speed_mode="fast",
            snapshot=snapshot,
        )
    assert exc_info.value.error_code == "provider_snapshot_invalid"


@pytest.mark.parametrize(
    "default_model",
    ["", "not a valid model", "gpt-5.6-unknown"],
)
def test_provider_snapshot_rejects_invalid_default_model(default_model):
    capabilities = _snapshot_capabilities()
    snapshot = capabilities.model_dump(mode="json")
    snapshot.update(
        {
            "default_model": default_model,
            "provider_config_revision": capabilities.config_revision,
            "capability_snapshot_hash": _provider_capability_hash(capabilities),
        }
    )

    with pytest.raises(ProviderExecutionError) as exc_info:
        migrate_provider_snapshot(
            provider_key="cursor",
            model="gpt-5.6-sol",
            reasoning_effort="medium",
            speed_mode="standard",
            snapshot=snapshot,
        )
    assert exc_info.value.error_code == "provider_snapshot_invalid"


def test_provider_selection_rejects_unsupported_reasoning_and_speed():
    capabilities = ProviderCapabilities(
        provider_key="cursor",
        display_name="Cursor",
        transport_type="cursor_cli",
        credential_mode="managed_login",
        credential_source="cursor-profile",
        models=["gpt-5.6-sol"],
        reasoning_efforts=["medium", "high"],
        speed_modes=["standard"],
        supports_tools=True,
        supports_structured_output=True,
        supports_resume=False,
        configured=True,
        healthy=True,
        config_revision="sha256:test",
    )

    config = ProviderExecutionConfig(
        provider_key="cursor",
        model="gpt-5.6-sol",
        reasoning_effort="xhigh",
        speed_mode="fast",
    )

    with pytest.raises(ValueError, match="思考深度"):
        validate_provider_selection(capabilities, config)


def test_provider_selection_rejects_unsupported_speed_independently():
    capabilities = ProviderCapabilities(
        provider_key="cursor",
        display_name="Cursor",
        transport_type="cursor_cli",
        credential_mode="managed_login",
        credential_source="cursor-profile",
        models=["gpt-5.6-sol"],
        reasoning_efforts=["medium", "high"],
        speed_modes=["standard"],
        supports_tools=True,
        supports_structured_output=True,
        supports_resume=False,
        configured=True,
        healthy=True,
        config_revision="sha256:test",
    )
    config = ProviderExecutionConfig(
        provider_key="cursor",
        model="gpt-5.6-sol",
        reasoning_effort="medium",
        speed_mode="fast",
    )

    with pytest.raises(ValueError, match="速度"):
        validate_provider_selection(capabilities, config)


def test_provider_execution_config_rejects_unknown_values():
    with pytest.raises(ValidationError):
        ProviderExecutionConfig(
            provider_key="cursor",
            model="gpt-5.6-sol",
            reasoning_effort="unbounded",
            speed_mode="turbo",
        )

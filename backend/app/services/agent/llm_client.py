"""
通义千问 LLM 客户端封装
兼容 OpenAI Chat Completions API 格式

修复: 复用 httpx.AsyncClient 避免文件描述符泄漏 (Too many open files)
"""
import json
import logging
import asyncio
import os
import re
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Optional, List

import fcntl

import httpx

from app.core.config import settings
from app.services.agent.providers.contracts import (
    ProviderCapabilities,
    ProviderError,
    ProviderExecutionConfig,
)

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:/+-]{2,128}$")
_PROVIDER_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")
_PROVIDER_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,96}$")
_DEFAULT_PROVIDER_KEY = "dashscope"
_BUILTIN_PROVIDER_KEYS = frozenset({"dashscope", "codex", "cursor", "grok"})
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_MODEL_CONFIG_PATH = _PROJECT_ROOT / "data" / "ai_lab_model_config.json"
_MODEL_CONFIG_THREAD_LOCK = threading.RLock()
_MODEL_CONFIG_LOCK_STATE = threading.local()
_DEFAULT_MODEL_CHOICES = (
    "qwen3.6-plus",
    "qwen3.6-max",
    "qwen-plus",
    "qwen-max",
)
_DASHSCOPE_FREE_TIER_MODEL_CHOICES = (
    "qwen3.6-flash-2026-04-16",
    "qwen3.6-35b-a3b",
    "qwen3.5-35b-a3b",
    "qwen3.5-122b-a10b",
    "qwen3.5-plus",
    "qwen3.5-plus-2026-02-15",
)


def _get_dashscope_api_key() -> Optional[str]:
    return settings.DASHSCOPE_API_KEY or settings.QWEN_API_KEY


def _get_dashscope_api_key_source() -> Optional[str]:
    if settings.DASHSCOPE_API_KEY:
        return "DASHSCOPE_API_KEY"
    if settings.QWEN_API_KEY:
        return "QWEN_API_KEY"
    return None


def _get_dashscope_default_model_name() -> str:
    return (settings.AI_AGENT_MODEL or settings.QWEN_MODEL or "qwen3.6-plus").strip()


def _dedupe_models(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        model = str(raw or "").strip()
        if model and _MODEL_NAME_RE.fullmatch(model) and model not in out:
            out.append(model)
    return out


def _read_model_config_file() -> Dict[str, Any]:
    if not _MODEL_CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(_MODEL_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("大模型配置读取失败: %s", _MODEL_CONFIG_PATH)
        return {}
    return data if isinstance(data, dict) else {}


def _model_config_lock_path() -> Path:
    return _MODEL_CONFIG_PATH.parent / f".{_MODEL_CONFIG_PATH.name}.lock"


@contextmanager
def _model_config_file_lock():
    """Serialize model-config read/modify/write transactions across processes."""

    _MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    depth = int(getattr(_MODEL_CONFIG_LOCK_STATE, "depth", 0))
    if depth:
        _MODEL_CONFIG_LOCK_STATE.depth = depth + 1
        try:
            yield
        finally:
            _MODEL_CONFIG_LOCK_STATE.depth = depth
        return

    lock_path = _model_config_lock_path()
    with _MODEL_CONFIG_THREAD_LOCK:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with os.fdopen(lock_fd, "a+") as lock_file:
                _MODEL_CONFIG_LOCK_STATE.depth = 1
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    _MODEL_CONFIG_LOCK_STATE.depth = 0
        except Exception:
            # fdopen owns and closes lock_fd once entered; before that point,
            # close it here so an exceptional mkdir/open path cannot leak it.
            try:
                os.close(lock_fd)
            except OSError:
                pass
            raise


def _write_model_config_file_unlocked(data: Dict[str, Any]) -> None:
    _MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=_MODEL_CONFIG_PATH.parent,
            prefix=f".{_MODEL_CONFIG_PATH.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(payload)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, _MODEL_CONFIG_PATH)
        temp_path = None
        try:
            directory_fd = os.open(str(_MODEL_CONFIG_PATH.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            # The file replacement itself is atomic.  Some filesystems do not
            # support fsync on directory descriptors, so keep that portability
            # failure from turning a successful write into an application error.
            logger.debug("模型配置目录 fsync 不可用: %s", _MODEL_CONFIG_PATH.parent)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass


def _write_model_config_file(data: Dict[str, Any]) -> None:
    with _model_config_file_lock():
        _write_model_config_file_unlocked(data)


@contextmanager
def _model_config_transaction():
    """Yield the latest config under an exclusive lock, then atomically commit it."""

    with _model_config_file_lock():
        data = _read_model_config_file()
        yield data
        _write_model_config_file_unlocked(data)


def _get_removed_model_names(data: Optional[Dict[str, Any]] = None) -> List[str]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    removed = source.get("removed_models") if isinstance(source.get("removed_models"), list) else []
    return _dedupe_models([str(model) for model in removed])


def _filter_removed_models(
    models: List[str],
    data: Optional[Dict[str, Any]] = None,
    keep: Optional[List[str]] = None,
) -> List[str]:
    removed = set(_get_removed_model_names(data))
    keep_set = set(_dedupe_models(keep or []))
    return [model for model in _dedupe_models(models) if model not in removed or model in keep_set]


def _read_model_override(data: Optional[Dict[str, Any]] = None) -> Optional[str]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    model = str(source.get("model") or "").strip()
    if model and _MODEL_NAME_RE.fullmatch(model):
        return model
    return None


def _normalize_provider_lookup_key(provider_key: str) -> str:
    normalized = (provider_key or "").strip().lower().replace(" ", "-")
    if normalized in _BUILTIN_PROVIDER_KEYS:
        return normalized
    return _validate_provider_key(normalized)


def _read_active_provider_key(data: Optional[Dict[str, Any]] = None) -> str:
    source = data if isinstance(data, dict) else _read_model_config_file()
    raw = str(source.get("provider_key") or source.get("providerKey") or source.get("provider") or "").strip()
    if not raw:
        return _DEFAULT_PROVIDER_KEY
    try:
        return _normalize_provider_lookup_key(raw)
    except ValueError:
        logger.warning("无效当前大模型 Provider: %s", raw)
        return _DEFAULT_PROVIDER_KEY


def _get_env_var_value(env_var: str) -> Optional[str]:
    normalized = (env_var or "").strip()
    if not normalized:
        return None

    configured_value = getattr(settings, normalized, None)
    if configured_value:
        return str(configured_value)

    value = os.getenv(normalized)
    if value:
        return value

    for env_file in (_PROJECT_ROOT / ".env", _PROJECT_ROOT / "backend" / ".env"):
        if not env_file.exists():
            continue
        try:
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                key, env_value = line.split("=", 1)
                if key.strip() == normalized:
                    parsed = env_value.strip().strip("\"'")
                    if parsed:
                        return parsed
        except Exception:
            logger.warning("读取环境变量文件失败: %s", env_file, exc_info=True)
    return None


def _env_var_configured(env_var: str) -> bool:
    return bool(_get_env_var_value(env_var))


def _get_dashscope_model_choices(
    data: Optional[Dict[str, Any]] = None,
    *,
    default_model: Optional[str] = None,
    configured_models: Optional[List[str]] = None,
    include_current: bool = True,
) -> List[str]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    configured = configured_models if isinstance(configured_models, list) else (
        source.get("models") if isinstance(source.get("models"), list) else []
    )
    default = str(default_model or _get_dashscope_default_model_name()).strip()
    current = (_read_model_override(source) if include_current else None) or default
    return _filter_removed_models([
        default,
        *_DEFAULT_MODEL_CHOICES,
        *configured,
        *_DASHSCOPE_FREE_TIER_MODEL_CHOICES,
        current,
    ], data=source, keep=[default, current])


def _load_custom_provider_configs(data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    raw_providers = source.get("providers") if isinstance(source.get("providers"), list) else []
    providers: List[Dict[str, Any]] = []
    seen = {_DEFAULT_PROVIDER_KEY}
    for raw in raw_providers:
        if not isinstance(raw, dict):
            continue
        raw_key = str(raw.get("provider_key") or raw.get("providerKey") or "").strip().lower().replace(" ", "-")
        if raw_key in _BUILTIN_PROVIDER_KEYS:
            continue
        try:
            provider = _normalize_custom_provider_config(raw, validate_endpoint=False)
        except ValueError as e:
            logger.warning("跳过无效大模型 Provider 配置: %s", e)
            continue
        if provider["provider_key"] in seen:
            continue
        seen.add(provider["provider_key"])
        providers.append(provider)
    return providers


def _dashscope_provider_config(
    data: Optional[Dict[str, Any]] = None,
    active_key: Optional[str] = None,
) -> Dict[str, Any]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    resolved_active_key = active_key or _read_active_provider_key(source)
    # The top-level flag belongs to DashScope itself, not to whichever
    # Provider happens to be selected.  Otherwise a custom active Provider can
    # hide a disabled DashScope until after a switch mutates the config.
    enabled = True
    if isinstance(source.get("enabled"), bool):
        enabled = source["enabled"]
    raw_providers = source.get("providers") if isinstance(source.get("providers"), list) else []
    legacy_default = source.get("dashscope_default_model")
    legacy_models = source.get("dashscope_models")
    if not isinstance(legacy_default, str) or not legacy_default.strip():
        legacy_default = _get_dashscope_default_model_name()
    if not isinstance(legacy_models, list):
        legacy_models = None
    for raw in raw_providers:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("provider_key") or raw.get("providerKey") or "").strip().lower().replace(" ", "-")
        if key == _DEFAULT_PROVIDER_KEY and isinstance(raw.get("enabled"), bool):
            enabled = raw["enabled"]
        if key == _DEFAULT_PROVIDER_KEY:
            if isinstance(raw.get("default_model"), str) and raw["default_model"].strip():
                legacy_default = raw["default_model"].strip()
            if isinstance(raw.get("models"), list):
                legacy_models = [str(model) for model in raw["models"]]
    models = _get_dashscope_model_choices(
        source,
        default_model=str(legacy_default),
        configured_models=legacy_models,
        include_current=resolved_active_key == _DEFAULT_PROVIDER_KEY,
    )
    return {
        "provider_key": _DEFAULT_PROVIDER_KEY,
        "name": "DashScope / Qwen",
        "api_key_env": _get_dashscope_api_key_source() or "DASHSCOPE_API_KEY",
        "base_url": settings.QWEN_BASE_URL.rstrip("/"),
        "default_model": str(legacy_default),
        "models": models,
        "transport_type": "openai_chat",
        "credential_mode": "env",
        # ``auto`` means use the existing AI_AGENT_ENABLE_THINKING and budget
        # settings; it is the only unified effort that can be truthful without
        # inventing a separate DashScope policy.
        "reasoning_efforts": ["auto"],
        "speed_modes": ["standard"],
        "enabled": enabled,
        "local_provider": False,
        "supports_tools": True,
        "supports_structured_output": True,
        "supports_resume": False,
        "api_key_configured": bool(_get_dashscope_api_key()),
        "builtin": True,
        "active": resolved_active_key == _DEFAULT_PROVIDER_KEY and enabled,
    }


def get_llm_provider_configs(data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    data = data if isinstance(data, dict) else _read_model_config_file()
    active_key = _read_active_provider_key(data)
    custom_providers = _load_custom_provider_configs(data)
    known_keys = {
        *_BUILTIN_PROVIDER_KEYS,
        *[provider["provider_key"] for provider in custom_providers],
    }
    if active_key not in known_keys:
        active_key = _DEFAULT_PROVIDER_KEY

    providers = [_dashscope_provider_config(data, active_key)]
    for provider in custom_providers:
        providers.append({
            **provider,
            "api_key_configured": _env_var_configured(provider["api_key_env"]),
            "builtin": False,
            "active": provider["provider_key"] == active_key and bool(provider.get("enabled", True)),
        })

    from app.services.agent.providers.registry import ProviderRegistry

    provider_registry = ProviderRegistry()
    for definition in provider_registry.list_definitions():
        if definition.provider_key == _DEFAULT_PROVIDER_KEY or not definition.builtin:
            continue
        capability = provider_registry.get_capabilities(definition.provider_key)
        providers.append({
            "provider_key": definition.provider_key,
            "name": definition.display_name,
            "api_key_env": definition.api_key_env,
            "base_url": definition.base_url,
            "default_model": definition.default_model,
            "models": list(definition.models),
            "transport_type": definition.transport_type,
            "credential_mode": definition.credential_mode,
            "reasoning_efforts": list(definition.reasoning_efforts),
            "speed_modes": list(definition.speed_modes),
            "enabled": definition.enabled,
            "local_provider": definition.local_provider,
            "supports_tools": definition.supports_tools,
            "supports_structured_output": definition.supports_structured_output,
            "supports_resume": definition.supports_resume,
            "api_key_configured": capability.configured,
            "builtin": definition.builtin,
            "active": definition.provider_key == active_key and bool(definition.enabled),
            "config_revision": capability.config_revision,
            "status_detail": capability.status_detail,
            "error_code": capability.error_code,
        })

    return providers


def _has_running_provider_reference(provider_key: str) -> bool:
    """Return whether an in-memory research task pins the selected Provider.

    Task-level Provider fields are introduced by the AgentTask migration after
    this settings API.  Reading them defensively here keeps this mutation guard
    compatible with both old task objects and the migrated objects, without
    importing the orchestrator during module initialization.
    """

    normalized = (provider_key or "").strip().lower().replace(" ", "-")
    if not normalized:
        return False
    try:
        from app.services.agent.orchestrator import orchestrator
    except Exception as exc:
        raise ProviderError(
            "无法确认运行中任务的 Provider 引用，拒绝停用",
            error_code="provider_reference_check_unavailable",
            provider_key=normalized,
            status_code=503,
        ) from exc

    try:
        tasks = getattr(orchestrator, "tasks")
        values = tasks.values() if hasattr(tasks, "values") else tasks
        iterator = iter(values)
        for task in iterator:
            if isinstance(task, dict):
                status = str(task.get("status") or "").strip().lower()
                task_provider = task.get("llm_provider") or task.get("provider_key") or task.get("providerKey")
                snapshot_marker = object()
                snapshot = task.get("llm_provider_snapshot", snapshot_marker)
                if snapshot is snapshot_marker:
                    snapshot = task.get("provider_snapshot", snapshot_marker)
            else:
                status = str(getattr(task, "status", "") or "").strip().lower()
                task_provider = (
                    getattr(task, "llm_provider", None)
                    or getattr(task, "provider_key", None)
                    or getattr(task, "providerKey", None)
                )
                snapshot_marker = object()
                snapshot = getattr(task, "llm_provider_snapshot", snapshot_marker)
                if snapshot is snapshot_marker:
                    snapshot = getattr(task, "provider_snapshot", snapshot_marker)
            if status not in {"pending", "running"}:
                continue
            candidate = str(task_provider or "").strip().lower().replace(" ", "-")
            snapshot_provider = ""
            if snapshot is not snapshot_marker:
                if isinstance(snapshot, str):
                    try:
                        snapshot = json.loads(snapshot)
                    except (TypeError, ValueError, json.JSONDecodeError):
                        raise ValueError("Provider snapshot 格式无效")
                if not isinstance(snapshot, dict):
                    raise ValueError("Provider snapshot 必须是对象")
                raw_snapshot_provider = snapshot.get("provider_key", snapshot.get("providerKey"))
                if not isinstance(raw_snapshot_provider, str) or not raw_snapshot_provider.strip():
                    raise ValueError("Provider snapshot 缺少有效 provider_key")
                snapshot_provider = raw_snapshot_provider.strip().lower().replace(" ", "-")
                if snapshot_provider not in _BUILTIN_PROVIDER_KEYS:
                    try:
                        snapshot_provider = _validate_provider_key(snapshot_provider)
                    except ValueError as exc:
                        raise ValueError("Provider snapshot provider_key 无效") from exc
            if candidate == normalized or snapshot_provider == normalized:
                return True
        return False
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(
            "无法确认运行中任务的 Provider 引用，拒绝停用",
            error_code="provider_reference_check_unavailable",
            provider_key=normalized,
            status_code=503,
        ) from exc


def _get_provider_config(
    provider_key: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    selected_key = _normalize_provider_lookup_key(provider_key) if provider_key else _read_active_provider_key(source)
    providers = get_llm_provider_configs(source)
    for provider in providers:
        if provider["provider_key"] == selected_key:
            return provider
    if provider_key:
        raise ValueError(f"模型厂商不存在: {provider_key}")
    return _dashscope_provider_config(source, _DEFAULT_PROVIDER_KEY)


def _get_provider_api_key(provider: Dict[str, Any]) -> Optional[str]:
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return _get_dashscope_api_key()
    return _get_env_var_value(str(provider.get("api_key_env") or ""))


def _get_provider_api_key_source(provider: Dict[str, Any]) -> Optional[str]:
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return _get_dashscope_api_key_source()
    return str(provider.get("api_key_env") or "").strip() or None


def get_agent_api_key() -> Optional[str]:
    return _get_provider_api_key(_get_provider_config())


def get_agent_api_key_source() -> Optional[str]:
    return _get_provider_api_key_source(_get_provider_config())


def has_agent_api_key() -> bool:
    return bool(get_agent_api_key())


def get_agent_default_model_name() -> str:
    provider = _get_provider_config()
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return str(provider.get("default_model") or _get_dashscope_default_model_name()).strip()
    return str(provider.get("default_model") or "").strip()


def get_agent_model_name() -> str:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    override = _read_model_override(data)
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        models = _dedupe_models([str(model) for model in provider.get("models", [])])
        return override if override in models else str(provider.get("default_model") or models[0]).strip()

    models = _dedupe_models([str(model) for model in provider.get("models", [])])
    if override and override in models:
        return override
    return str(provider.get("default_model") or models[0]).strip()


def get_llm_model_choices() -> List[str]:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return _dedupe_models([str(model) for model in provider.get("models", [])])
    return _dedupe_models([str(model) for model in provider.get("models", [])])


def get_dashscope_free_tier_model_choices() -> List[str]:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    if provider["provider_key"] != _DEFAULT_PROVIDER_KEY:
        return []
    return _filter_removed_models(list(_DASHSCOPE_FREE_TIER_MODEL_CHOICES), data=data)


def get_llm_fallback_model_choices(primary: Optional[str] = None) -> List[str]:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    current = get_agent_model_name()
    default = get_agent_default_model_name()
    if provider["provider_key"] != _DEFAULT_PROVIDER_KEY:
        return _dedupe_models([primary or "", current, *provider.get("models", []), default])

    configured = data.get("models") if isinstance(data.get("models"), list) else []
    return _filter_removed_models([
        primary or "",
        *_DASHSCOPE_FREE_TIER_MODEL_CHOICES,
        *configured,
        current,
        default,
        *_DEFAULT_MODEL_CHOICES,
    ], data=data, keep=[primary or "", current, default])


def _get_all_known_model_choices(data: Optional[Dict[str, Any]] = None) -> List[str]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    provider = _get_provider_config(data=source)
    if provider["provider_key"] != _DEFAULT_PROVIDER_KEY:
        return _dedupe_models([*provider.get("models", []), str(provider.get("default_model") or ""), get_agent_model_name()])

    configured = source.get("models") if isinstance(source.get("models"), list) else []
    return _dedupe_models([
        _get_dashscope_default_model_name(),
        *_DEFAULT_MODEL_CHOICES,
        *configured,
        *_DASHSCOPE_FREE_TIER_MODEL_CHOICES,
        get_agent_model_name(),
    ])


def _validate_provider_key(provider_key: str) -> str:
    normalized = (provider_key or "").strip().lower().replace(" ", "-")
    if not normalized:
        raise ValueError("provider_key 不能为空")
    if normalized in _BUILTIN_PROVIDER_KEYS:
        raise ValueError(f"{normalized} 为内置 Provider，不能作为自定义厂商标识")
    if not _PROVIDER_KEY_RE.fullmatch(normalized):
        raise ValueError("provider_key 只能包含小写字母、数字、下划线或中划线，且必须以字母开头")
    return normalized


def _validate_provider_name(name: str) -> str:
    normalized = (name or "").strip()
    if len(normalized) < 2 or len(normalized) > 80:
        raise ValueError("厂商名称长度必须为 2~80")
    return normalized


def _validate_provider_env(api_key_env: str) -> str:
    normalized = (api_key_env or "").strip().upper()
    if not _PROVIDER_ENV_RE.fullmatch(normalized):
        raise ValueError("API Key 环境变量只能包含大写字母、数字和下划线，且必须以字母开头")
    return normalized


def _validate_provider_base_url(
    base_url: str,
    *,
    local_provider: bool = False,
    resolve: bool = True,
) -> str:
    from app.services.agent.providers.registry import validate_http_provider_endpoint

    return validate_http_provider_endpoint(base_url, local_provider=local_provider, resolve=resolve)


def _normalize_custom_provider_config(
    raw: Dict[str, Any],
    *,
    validate_endpoint: bool = True,
) -> Dict[str, Any]:
    name = _validate_provider_name(str(raw.get("name") or ""))
    provider_key = _validate_provider_key(str(raw.get("provider_key") or raw.get("providerKey") or ""))
    transport_type = str(raw.get("transport_type") or raw.get("transportType") or "openai_chat").strip().lower()
    if transport_type not in {"openai_chat", "xai_api", "codex_cli", "cursor_cli"}:
        raise ValueError("不支持的 Provider transport_type")

    credential_mode = str(raw.get("credential_mode") or raw.get("credentialMode") or "env").strip().lower()
    if credential_mode not in {"env", "managed_login", "none"}:
        raise ValueError("不支持的 Provider credential_mode")

    raw_api_key_env = str(raw.get("api_key_env") or raw.get("apiKeyEnv") or "").strip()
    api_key_env = _validate_provider_env(raw_api_key_env) if raw_api_key_env else ""
    if credential_mode == "env" and not api_key_env:
        raise ValueError("env credential_mode 必须配置 API Key 环境变量")

    local_provider = bool(raw.get("local_provider", raw.get("localProvider", False)))
    raw_base_url = str(raw.get("base_url") or raw.get("baseUrl") or "").strip()
    if transport_type in {"openai_chat", "xai_api"}:
        base_url = _validate_provider_base_url(
            raw_base_url,
            local_provider=local_provider,
            resolve=validate_endpoint,
        )
    elif raw_base_url:
        raise ValueError("CLI Provider 不需要 Base URL")
    else:
        base_url = ""

    default_model = _validate_model_name(str(raw.get("default_model") or raw.get("defaultModel") or ""))
    raw_models = raw.get("models") if isinstance(raw.get("models"), list) else []
    models = _dedupe_models([default_model, *[str(model) for model in raw_models]])
    if not models:
        raise ValueError("模型列表不能为空")

    raw_reasoning = raw.get("reasoning_efforts")
    if raw_reasoning is None:
        raw_reasoning = raw.get("reasoningEfforts")
    reasoning_efforts = [str(value).strip() for value in raw_reasoning] if isinstance(raw_reasoning, list) else []
    allowed_reasoning = {"auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    if any(value not in allowed_reasoning for value in reasoning_efforts):
        raise ValueError("reasoning_efforts 包含不支持的值")

    raw_speed = raw.get("speed_modes")
    if raw_speed is None:
        raw_speed = raw.get("speedModes")
    speed_modes = [str(value).strip() for value in raw_speed] if isinstance(raw_speed, list) else ["standard"]
    if not speed_modes:
        speed_modes = ["standard"]
    if any(value not in {"standard", "fast"} for value in speed_modes):
        raise ValueError("speed_modes 包含不支持的值")

    return {
        "provider_key": provider_key,
        "name": name,
        "api_key_env": api_key_env,
        "base_url": base_url,
        "default_model": default_model,
        "models": models,
        "transport_type": transport_type,
        "credential_mode": credential_mode,
        "reasoning_efforts": list(dict.fromkeys(reasoning_efforts)),
        "speed_modes": list(dict.fromkeys(speed_modes)),
        "enabled": bool(raw.get("enabled", True)),
        "local_provider": local_provider,
        "supports_tools": bool(raw.get("supports_tools", False)),
        "supports_structured_output": bool(raw.get("supports_structured_output", False)),
        "supports_resume": bool(raw.get("supports_resume", False)),
    }


def get_llm_model_config() -> Dict[str, Any]:
    provider = _get_provider_config()
    from app.services.agent.providers.registry import ProviderRegistry

    provider_registry = ProviderRegistry()
    provider_migrations = provider_registry.get_migration_status()
    provider_capabilities = _get_provider_capability_snapshots(provider_registry)
    return {
        "provider_key": provider["provider_key"],
        "provider_name": provider["name"],
        "model": get_agent_model_name(),
        "default_model": get_agent_default_model_name(),
        "models": get_llm_model_choices(),
        "free_tier_models": get_dashscope_free_tier_model_choices(),
        "model_fallback_enabled": True,
        "base_url": provider["base_url"],
        "enable_thinking": settings.AI_AGENT_ENABLE_THINKING,
        "request_timeout": settings.AI_AGENT_REQUEST_TIMEOUT,
        "api_key_configured": has_agent_api_key(),
        "api_key_source": get_agent_api_key_source(),
        "enabled": bool(provider.get("enabled", True)),
        "providers": get_llm_provider_configs(),
        "provider_capabilities": provider_capabilities,
        "provider_migrations": provider_migrations,
    }


def _get_provider_capability_snapshots(provider_registry: Any = None) -> List[Dict[str, Any]]:
    """Build the settings-facing capability view without credential material."""

    if provider_registry is None:
        from app.services.agent.providers.registry import ProviderRegistry

        provider_registry = ProviderRegistry()
    active_key = _read_active_provider_key()
    snapshots: List[Dict[str, Any]] = []
    for capability in provider_registry.list_capabilities():
        definition = provider_registry.get_definition(capability.provider_key)
        payload = capability.model_dump(mode="json")
        payload.update(
            {
                "default_model": definition.default_model,
                "enabled": bool(definition.enabled),
                "active": capability.provider_key == active_key and bool(definition.enabled),
            }
        )
        snapshots.append(payload)
    return snapshots


def get_llm_provider_capabilities(provider_key: Optional[str] = None) -> Dict[str, Any] | List[Dict[str, Any]]:
    """Return one or all Provider capability snapshots for settings consumers."""

    from app.services.agent.providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    snapshots = _get_provider_capability_snapshots(registry)
    if provider_key is None:
        return snapshots
    normalized = (provider_key or "").strip().lower().replace(" ", "-")
    for snapshot in snapshots:
        if snapshot["provider_key"] == normalized:
            return snapshot
    raise ValueError("所选 Provider 不存在或不受支持")


def _validate_model_name(model: str) -> str:
    normalized = (model or "").strip()
    if not normalized:
        raise ValueError("模型名称不能为空")
    if not _MODEL_NAME_RE.fullmatch(normalized):
        raise ValueError("模型名称只能包含字母、数字、点、下划线、中划线、加号、冒号或斜杠，长度 2~128")
    return normalized


def validate_llm_model_name(model: str) -> str:
    """Validate a DashScope-compatible model name without changing global config."""
    return _validate_model_name(model)


def _update_model_config(mutator) -> Any:
    """Apply a read/modify/write update while holding the process/file lock."""

    with _model_config_transaction() as data:
        return mutator(data)


async def set_llm_model_name(model: str) -> Dict[str, Any]:
    normalized = _validate_model_name(model)
    def mutate(data: Dict[str, Any]) -> None:
        provider = _get_provider_config(data=data)
        data["model"] = normalized
        data["removed_models"] = [name for name in _get_removed_model_names(data) if name != normalized]

        if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
            data["models"] = _dedupe_models([*_get_dashscope_model_choices(data), normalized])
        else:
            providers: List[Dict[str, Any]] = []
            for existing in _load_custom_provider_configs(data):
                if existing["provider_key"] == provider["provider_key"]:
                    existing["models"] = _dedupe_models([*existing["models"], normalized])
                providers.append(existing)
            data["providers"] = providers

    _update_model_config(mutate)
    await reset_qwen_client()
    return get_llm_model_config()


async def add_llm_model_name(model: str) -> Dict[str, Any]:
    """Add a model choice and select it for subsequent global LLM calls."""
    return await set_llm_model_name(model)


async def delete_llm_model_name(model: str) -> Dict[str, Any]:
    """Remove a model choice from the operator-facing candidate list."""
    normalized = _validate_model_name(model)
    current = get_agent_model_name()
    default = get_agent_default_model_name()
    if normalized == current:
        raise ValueError("当前模型不可删除，请先切换到其他模型")
    if normalized == default:
        raise ValueError("默认模型不可删除")

    def mutate(data: Dict[str, Any]) -> None:
        known_models = _get_all_known_model_choices(data)
        if normalized not in known_models:
            raise ValueError("模型不存在或已删除")

        provider = _get_provider_config(data=data)
        if provider["provider_key"] != _DEFAULT_PROVIDER_KEY:
            providers: List[Dict[str, Any]] = []
            removed = False
            for existing in _load_custom_provider_configs(data):
                if existing["provider_key"] == provider["provider_key"]:
                    next_models = [name for name in existing["models"] if name != normalized]
                    if len(next_models) != len(existing["models"]):
                        removed = True
                    existing["models"] = next_models
                providers.append(existing)
            if not removed:
                raise ValueError("模型不存在或已删除")
            data["providers"] = providers
            return

        configured = data.get("models") if isinstance(data.get("models"), list) else []
        data["models"] = [name for name in _dedupe_models([str(item) for item in configured]) if name != normalized]
        data["removed_models"] = _dedupe_models([
            *[name for name in _get_removed_model_names(data) if name not in {current, default}],
            normalized,
        ])

    _update_model_config(mutate)
    return get_llm_model_config()


async def set_llm_provider_key(provider_key: str) -> Dict[str, Any]:
    """Select the active OpenAI-compatible Provider used by shared LLM calls."""
    try:
        normalized = _normalize_provider_lookup_key(provider_key)
    except ValueError as exc:
        raise ProviderError(
            "所选 Provider 不存在或不受支持",
            error_code="provider_unsupported",
        ) from exc

    def mutate(data: Dict[str, Any]) -> None:
        try:
            provider = _get_provider_config(provider_key=normalized, data=data)
        except ValueError as exc:
            raise ProviderError(
                "所选 Provider 不存在或不受支持",
                error_code="provider_unsupported",
                provider_key=normalized,
            ) from exc
        if not bool(provider.get("enabled", True)):
            raise ProviderError(
                "Provider 已停用，请先启用后再选择",
                error_code="provider_disabled",
                provider_key=normalized,
            )
        if provider.get("transport_type", "openai_chat") not in {"openai_chat", "xai_api"}:
            raise ProviderError(
                "当前兼容入口不支持 CLI Provider，请使用统一 Provider 工厂",
                error_code="provider_unsupported",
                provider_key=normalized,
            )
        api_key_source = _get_provider_api_key_source(provider) or "API Key"
        if not _get_provider_api_key(provider):
            raise ProviderError(
                f"{api_key_source} 未配置，请先在服务器环境变量中设置并重启服务",
                error_code="provider_not_configured",
                provider_key=normalized,
            )

        data["provider_key"] = normalized
        current = _read_model_override(data)
        if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
            choices = _dedupe_models([str(model) for model in provider.get("models", [])])
            data["model"] = current if current in choices else str(provider.get("default_model") or choices[0]).strip()
        else:
            models = _dedupe_models([str(model) for model in provider.get("models", [])])
            data["model"] = current if current in models else str(provider.get("default_model") or models[0]).strip()
            data["providers"] = _load_custom_provider_configs(data)

    _update_model_config(mutate)
    await reset_qwen_client()
    return get_llm_model_config()


async def add_llm_provider_config(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update a model Provider without persisting API Key secrets."""
    normalized = _normalize_custom_provider_config(provider)
    def mutate(data: Dict[str, Any]) -> None:
        raw_providers = data.get("providers") if isinstance(data.get("providers"), list) else []
        providers: List[Dict[str, Any]] = []
        replaced = False

        for raw in raw_providers:
            if not isinstance(raw, dict):
                continue
            try:
                existing = _normalize_custom_provider_config(raw, validate_endpoint=False)
            except ValueError:
                continue
            if existing["provider_key"] == normalized["provider_key"]:
                providers.append(normalized)
                replaced = True
            else:
                providers.append(existing)

        if not replaced:
            providers.append(normalized)

        data["providers"] = providers
        if _read_active_provider_key(data) == normalized["provider_key"]:
            current = _read_model_override(data)
            data["model"] = current if current in normalized["models"] else normalized["default_model"]

    _update_model_config(mutate)
    await reset_qwen_client()
    return get_llm_model_config()


def _provider_update_values(
    provider_key: str,
    updates: Dict[str, Any],
    definition: Any,
) -> Dict[str, Any]:
    """Validate a partial Provider metadata update against its current definition."""

    allowed_reasoning = {"auto", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}
    allowed_speed = {"standard", "fast"}
    current_models = _dedupe_models([str(model) for model in definition.models])
    current_default = _validate_model_name(str(definition.default_model or current_models[0]))
    current_reasoning = list(dict.fromkeys(str(value) for value in definition.reasoning_efforts))
    current_speed = list(dict.fromkeys(str(value) for value in definition.speed_modes)) or ["standard"]

    if "default_model" in updates:
        default_model = _validate_model_name(str(updates.get("default_model") or ""))
    else:
        default_model = current_default

    if "models" in updates:
        raw_models = updates.get("models")
        if not isinstance(raw_models, list):
            raise ValueError("models 必须是列表")
        models = _dedupe_models([str(model) for model in raw_models])
        if not models:
            raise ValueError("模型列表不能为空")
        if "default_model" not in updates and current_default not in models:
            default_model = models[0]
    else:
        models = current_models
    if default_model not in models:
        models.insert(0, default_model)

    if "reasoning_efforts" in updates:
        raw_reasoning = updates.get("reasoning_efforts")
        if not isinstance(raw_reasoning, list):
            raise ValueError("reasoning_efforts 必须是列表")
        reasoning_efforts = [str(value).strip() for value in raw_reasoning]
        if any(value not in allowed_reasoning for value in reasoning_efforts):
            raise ValueError("reasoning_efforts 包含不支持的值")
        reasoning_efforts = list(dict.fromkeys(reasoning_efforts))
    else:
        reasoning_efforts = current_reasoning

    if "speed_modes" in updates:
        raw_speed = updates.get("speed_modes")
        if not isinstance(raw_speed, list):
            raise ValueError("speed_modes 必须是列表")
        speed_modes = [str(value).strip() for value in raw_speed]
        if not speed_modes or any(value not in allowed_speed for value in speed_modes):
            raise ValueError("speed_modes 包含不支持的值")
        speed_modes = list(dict.fromkeys(speed_modes))
    else:
        speed_modes = current_speed

    if "enabled" in updates and not isinstance(updates.get("enabled"), bool):
        raise ValueError("enabled 必须是布尔值")

    return {
        "provider_key": provider_key,
        "default_model": default_model,
        "models": models,
        "reasoning_efforts": reasoning_efforts,
        "speed_modes": speed_modes,
        "enabled": bool(updates.get("enabled", definition.enabled)),
    }


def _provider_snapshot_for_key(provider_key: str) -> Dict[str, Any]:
    from app.services.agent.providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    try:
        definition = registry.get_definition(provider_key)
        capability = registry.get_capabilities(provider_key)
    except ValueError as exc:
        raise ProviderError(
            "所选 Provider 不存在或不受支持",
            error_code="provider_unsupported",
            provider_key=provider_key,
        ) from exc
    payload = capability.model_dump(mode="json")
    payload.update(
        {
            "default_model": definition.default_model,
            "enabled": bool(definition.enabled),
            "active": _read_active_provider_key() == definition.provider_key and bool(definition.enabled),
        }
    )
    return payload


async def update_llm_provider_config(provider_key: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """Edit safe Provider metadata or disable it without deleting history."""

    normalized_input = (provider_key or "").strip().lower().replace(" ", "-")
    try:
        normalized_key = (
            normalized_input
            if normalized_input in _BUILTIN_PROVIDER_KEYS
            else _validate_provider_key(normalized_input)
        )
    except ValueError as exc:
        raise ProviderError(
            "所选 Provider 不存在或不受支持",
            error_code="provider_unsupported",
        ) from exc

    patch = dict(updates or {})

    def mutate(data: Dict[str, Any]) -> None:
        from app.services.agent.providers.registry import ProviderRegistry

        try:
            definition = ProviderRegistry().get_definition(normalized_key)
        except ValueError as exc:
            raise ProviderError(
                "所选 Provider 不存在或不受支持",
                error_code="provider_unsupported",
                provider_key=normalized_key,
            ) from exc

        current_enabled = bool(definition.enabled)
        if patch.get("enabled") is False and current_enabled:
            active_key = _read_active_provider_key(data)
            if active_key == normalized_key:
                raise ValueError("当前 Provider 正在作为全局 Provider 使用，无法停用")
            try:
                has_running_reference = _has_running_provider_reference(normalized_key)
            except ProviderError:
                raise
            except Exception as exc:
                raise ProviderError(
                    "无法确认运行中任务的 Provider 引用，拒绝停用",
                    error_code="provider_reference_check_unavailable",
                    provider_key=normalized_key,
                    status_code=503,
                ) from exc
            if not isinstance(has_running_reference, bool):
                raise ProviderError(
                    "无法确认运行中任务的 Provider 引用，拒绝停用",
                    error_code="provider_reference_check_unavailable",
                    provider_key=normalized_key,
                    status_code=503,
                )
            if has_running_reference:
                raise ValueError("Provider 正在被运行中任务引用，无法停用")

        values = _provider_update_values(normalized_key, patch, definition)
        raw_providers = data.get("providers") if isinstance(data.get("providers"), list) else []
        providers: List[Any] = []
        replaced = False
        existing_custom: Dict[str, Any] | None = None
        for existing in _load_custom_provider_configs(data):
            if existing["provider_key"] == normalized_key:
                existing_custom = existing
                break

        # Built-in rows contain only editable capability metadata.  Identity,
        # transport and credentials continue to come from the registry.
        if definition.builtin:
            next_provider = {
                "provider_key": normalized_key,
                "default_model": values["default_model"],
                "models": values["models"],
                "reasoning_efforts": values["reasoning_efforts"],
                "speed_modes": values["speed_modes"],
                "enabled": values["enabled"],
            }
        else:
            if existing_custom is None:
                raise ProviderError(
                    "所选 Provider 不存在或不受支持",
                    error_code="provider_unsupported",
                    provider_key=normalized_key,
                )
            next_provider = {
                **existing_custom,
                "default_model": values["default_model"],
                "models": values["models"],
                "reasoning_efforts": values["reasoning_efforts"],
                "speed_modes": values["speed_modes"],
                "enabled": values["enabled"],
            }

        for raw in raw_providers:
            if not isinstance(raw, dict):
                providers.append(raw)
                continue
            raw_key = str(raw.get("provider_key") or raw.get("providerKey") or "").strip().lower().replace(" ", "-")
            if raw_key == normalized_key:
                if not replaced:
                    providers.append(next_provider)
                    replaced = True
                continue
            if raw_key in _BUILTIN_PROVIDER_KEYS:
                # Preserve unrelated built-in metadata rows, but never copy
                # their identity/credential fields into the updated row.
                providers.append(raw)
                continue
            try:
                providers.append(_normalize_custom_provider_config(raw, validate_endpoint=False))
            except ValueError:
                # A PATCH to one Provider must not erase unrelated legacy rows
                # merely because their metadata cannot be normalized today.
                providers.append(raw)
        if not replaced:
            providers.append(next_provider)
        data["providers"] = providers

        is_active = _read_active_provider_key(data) == normalized_key
        if normalized_key == _DEFAULT_PROVIDER_KEY:
            # DashScope's enabled flag is independent metadata even while a
            # different HTTP Provider is active.  The shared model/candidate
            # fields, however, belong only to the active Provider.
            data["enabled"] = values["enabled"]
            # Keep a per-DashScope copy in the legacy top-level config.  The
            # historical shared ``model``/``models`` keys remain untouched
            # while another Provider is active and are restored on switch.
            data["dashscope_default_model"] = values["default_model"]
            data["dashscope_models"] = list(values["models"])
        if is_active and normalized_key == _DEFAULT_PROVIDER_KEY:
            current = _read_model_override(data)
            data["model"] = current if current in values["models"] else values["default_model"]
            data["models"] = list(values["models"])
        elif is_active:
            current = _read_model_override(data)
            data["model"] = current if current in values["models"] else values["default_model"]

    _update_model_config(mutate)
    await reset_qwen_client()
    return _provider_snapshot_for_key(normalized_key)


class _PinnedAsyncNetworkBackend:
    """Connect to the addresses captured by endpoint validation, never re-resolve."""

    def __init__(self, addresses: tuple[str, ...]):
        import httpcore

        self._backend = httpcore.AnyIOBackend()
        self._addresses = tuple(addresses)

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        errors = []
        for address in self._addresses:
            try:
                return await self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except Exception as exc:  # pragma: no cover - exercised by network failures
                errors.append(exc)
        if errors:
            raise errors[-1]
        raise RuntimeError("Provider endpoint 没有可用的已校验地址")

    async def connect_unix_socket(self, path: str, timeout: float | None = None, socket_options=None):
        return await self._backend.connect_unix_socket(path, timeout=timeout, socket_options=socket_options)

    async def sleep(self, seconds: float):
        return await self._backend.sleep(seconds)


class QwenClient:
    """OpenAI Chat Completions 兼容大模型客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        provider_key: str = _DEFAULT_PROVIDER_KEY,
        api_key_source: Optional[str] = None,
        endpoint_resolution: Any = None,
        local_provider: bool = False,
    ):
        self.provider_key = provider_key
        self.api_key_source = api_key_source or get_agent_api_key_source() or "API Key"
        self.api_key = api_key or get_agent_api_key()
        self.model = model or get_agent_model_name()
        self.base_url = (base_url or settings.QWEN_BASE_URL).rstrip("/")
        self.endpoint_resolution = endpoint_resolution
        self.local_provider = local_provider
        if not self.api_key:
            raise ProviderError(
                f"{self.api_key_source} 未配置，请在服务器环境变量中设置",
                error_code="provider_not_configured",
                provider_key=self.provider_key,
            )
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            if self.endpoint_resolution is None:
                from app.services.agent.providers.registry import resolve_http_provider_endpoint

                self.endpoint_resolution = resolve_http_provider_endpoint(
                    self.base_url,
                    local_provider=self.local_provider,
                )
            else:
                from app.services.agent.providers.registry import validate_resolved_http_provider_endpoint

                self.endpoint_resolution = validate_resolved_http_provider_endpoint(
                    self.endpoint_resolution,
                    self.base_url,
                    local_provider=self.local_provider,
                )
            transport = None
            transport = httpx.AsyncHTTPTransport(trust_env=False)
            # httpx does not expose a public DNS resolver hook. Replace the
            # transport pool's backend before its first connection so TLS
            # still uses the original hostname/SNI while TCP dials only the
            # addresses captured by endpoint validation.
            transport._pool._network_backend = _PinnedAsyncNetworkBackend(  # type: ignore[attr-defined]
                tuple(self.endpoint_resolution.addresses)
            )
            self._client = httpx.AsyncClient(
                timeout=max(10, int(settings.AI_AGENT_REQUEST_TIMEOUT)),
                trust_env=False,
                transport=transport,
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 16384,
        response_format: Optional[Dict[str, str]] = None,
        max_retries: int = _MAX_RETRIES,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # DashScope accepts these OpenAI-compatible extension fields as
        # top-level JSON fields. Other Providers may reject them, so keep their
        # payloads on the portable Chat Completions contract.
        if self.provider_key == _DEFAULT_PROVIDER_KEY:
            body["enable_thinking"] = bool(settings.AI_AGENT_ENABLE_THINKING)
            if settings.AI_AGENT_ENABLE_THINKING:
                body["thinking_budget"] = max(1, int(settings.AI_AGENT_THINKING_BUDGET))
        if response_format:
            body["response_format"] = response_format

        retry_count = max(1, int(max_retries))
        last_error_message = ""
        for attempt in range(1, retry_count + 1):
            try:
                client = await self._get_client()
                resp = await client.post(url, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return content
            except httpx.HTTPStatusError as e:
                last_error_message = describe_qwen_exception(e)
                logger.warning(
                    "Qwen API HTTP %s (attempt %d/%d): %s",
                    e.response.status_code, attempt, retry_count, e.response.text[:300],
                )
                if e.response.status_code == 429 or e.response.status_code >= 500:
                    await asyncio.sleep(_RETRY_DELAY * attempt)
                    continue
                raise RuntimeError(last_error_message) from e
            except (httpx.RequestError, KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
                last_error_message = describe_qwen_exception(e)
                logger.warning("Qwen API error (attempt %d/%d): %s", attempt, retry_count, last_error_message)
                # 连接错误时重置 client
                await self.close()
                await asyncio.sleep(_RETRY_DELAY * attempt)

        raise RuntimeError(f"Qwen API failed after {retry_count} retries: {last_error_message or '未知错误'}")

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 16384,
    ) -> Dict[str, Any]:
        raw = await self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        text = raw.strip()
        if text.startswith("```"):
            first_nl = text.index("\n")
            text = text[first_nl + 1:]
            if text.endswith("```"):
                text = text[:-3].strip()
        return json.loads(text)


def describe_qwen_exception(error: Exception) -> str:
    if isinstance(error, httpx.HTTPStatusError):
        body = error.response.text.strip()
        if len(body) > 500:
            body = body[:500] + "..."
        return f"HTTP {error.response.status_code}: {body or error.response.reason_phrase}"
    if isinstance(error, httpx.TimeoutException):
        return (
            f"{error.__class__.__name__}: 请求模型接口超时，"
            f"当前超时 {settings.AI_AGENT_REQUEST_TIMEOUT}s；请检查网络、模型名或稍后重试"
        )
    if isinstance(error, httpx.ConnectError):
        try:
            base_url = get_llm_model_config().get("base_url") or settings.QWEN_BASE_URL
        except Exception:
            base_url = settings.QWEN_BASE_URL
        return f"ConnectError: 无法连接模型接口 ({base_url})，请检查服务器网络/DNS/防火墙"
    if isinstance(error, httpx.RequestError):
        detail = str(error).strip()
        return f"{error.__class__.__name__}: {detail or '请求模型接口失败'}"
    if isinstance(error, KeyError):
        return f"响应缺少字段: {error}"
    detail = str(error).strip()
    return detail or error.__class__.__name__


def is_dashscope_free_tier_exhausted(error: object) -> bool:
    if isinstance(error, Exception):
        detail = describe_qwen_exception(error)
    else:
        detail = str(error or "")
    normalized = detail.lower()
    if "allocationquota.freetieronly" in normalized or "freetieronly" in normalized:
        return True
    if "free tier" in normalized and ("quota" in normalized or "allocation" in normalized):
        return True
    if "免费额度" in detail and any(token in detail for token in ("用完", "耗尽", "不足", "用尽")):
        return True
    return False


qwen_client: Optional[QwenClient] = None
qwen_client_signature: Optional[tuple[str, str, str, str, tuple[str, ...]]] = None
qwen_clients: Dict[tuple[str, str, str, str, tuple[str, ...]], QwenClient] = {}


def get_qwen_client(model: Optional[str] = None, provider_key: Optional[str] = None) -> QwenClient:
    global qwen_client, qwen_client_signature
    try:
        provider = _get_provider_config(provider_key=provider_key)
    except ValueError as exc:
        raise ProviderError(
            "所选 Provider 不存在或不受支持",
            error_code="provider_unsupported",
            provider_key=provider_key,
        ) from exc
    if not bool(provider.get("enabled", True)):
        raise ProviderError(
            "Provider 已停用，请先启用后再运行",
            error_code="provider_disabled",
            provider_key=provider["provider_key"],
        )
    if provider.get("transport_type", "openai_chat") not in {"openai_chat", "xai_api"}:
        raise ProviderError(
            "当前兼容入口不支持 CLI Provider，请使用统一 Provider 工厂",
            error_code="provider_unsupported",
            provider_key=provider["provider_key"],
        )
    api_key = _get_provider_api_key(provider)
    if not api_key:
        api_key_source = _get_provider_api_key_source(provider) or "API Key"
        raise ProviderError(
            f"{api_key_source} 未配置，请在服务器环境变量中设置",
            error_code="provider_not_configured",
            provider_key=provider["provider_key"],
        )
    from app.services.agent.providers.registry import resolve_http_provider_endpoint

    base_url = str(provider.get("base_url") or settings.QWEN_BASE_URL).rstrip("/")
    endpoint_resolution = resolve_http_provider_endpoint(
        base_url,
        local_provider=bool(provider.get("local_provider", False)),
    )
    if model:
        selected_model = _validate_model_name(model)
    elif provider_key and not provider.get("active"):
        selected_model = str(provider.get("default_model") or "").strip()
    else:
        selected_model = get_agent_model_name()
    signature = (
        provider["provider_key"],
        api_key or "",
        selected_model,
        base_url,
        endpoint_resolution.addresses,
    )
    if signature not in qwen_clients:
        qwen_clients[signature] = QwenClient(
            api_key=api_key,
            model=selected_model,
            base_url=base_url,
            provider_key=provider["provider_key"],
            api_key_source=_get_provider_api_key_source(provider),
            endpoint_resolution=endpoint_resolution,
            local_provider=bool(provider.get("local_provider", False)),
        )
    qwen_client = qwen_clients[signature]
    qwen_client_signature = signature
    return qwen_client


async def reset_qwen_client() -> None:
    global qwen_client, qwen_client_signature
    clients = list(qwen_clients.values())
    qwen_clients.clear()
    qwen_client = None
    qwen_client_signature = None
    for client in clients:
        await client.close()


def get_research_provider_client(
    execution: ProviderExecutionConfig,
    *,
    capabilities_override: ProviderCapabilities | None = None,
):
    """Compatibility import for the new Provider factory.

    Existing callers keep using ``get_qwen_client``/``QwenClient``.  New
    research paths can opt into the unified factory without migrating those
    compatibility callers in one step.
    """

    from app.services.agent.providers import get_research_provider_client as factory

    if capabilities_override is None:
        return factory(execution)
    return factory(execution, capabilities_override=capabilities_override)

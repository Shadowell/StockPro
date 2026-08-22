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
from pathlib import Path
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._:/+-]{2,128}$")
_PROVIDER_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,48}$")
_PROVIDER_ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,96}$")
_DEFAULT_PROVIDER_KEY = "dashscope"
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_MODEL_CONFIG_PATH = _PROJECT_ROOT / "data" / "ai_lab_model_config.json"
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


def _write_model_config_file(data: Dict[str, Any]) -> None:
    _MODEL_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MODEL_CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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
    if normalized == _DEFAULT_PROVIDER_KEY:
        return _DEFAULT_PROVIDER_KEY
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


def _get_dashscope_model_choices(data: Optional[Dict[str, Any]] = None) -> List[str]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    configured = source.get("models") if isinstance(source.get("models"), list) else []
    default = _get_dashscope_default_model_name()
    current = _read_model_override(source) or default
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
        try:
            provider = _normalize_custom_provider_config(raw)
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
    return {
        "provider_key": _DEFAULT_PROVIDER_KEY,
        "name": "DashScope / Qwen",
        "api_key_env": _get_dashscope_api_key_source() or "DASHSCOPE_API_KEY",
        "base_url": settings.QWEN_BASE_URL.rstrip("/"),
        "default_model": _get_dashscope_default_model_name(),
        "models": _get_dashscope_model_choices(source),
        "api_key_configured": bool(_get_dashscope_api_key()),
        "builtin": True,
        "active": resolved_active_key == _DEFAULT_PROVIDER_KEY,
    }


def get_llm_provider_configs() -> List[Dict[str, Any]]:
    data = _read_model_config_file()
    active_key = _read_active_provider_key(data)
    custom_providers = _load_custom_provider_configs(data)
    known_keys = {_DEFAULT_PROVIDER_KEY, *[provider["provider_key"] for provider in custom_providers]}
    if active_key not in known_keys:
        active_key = _DEFAULT_PROVIDER_KEY

    providers = [_dashscope_provider_config(data, active_key)]
    for provider in custom_providers:
        providers.append({
            **provider,
            "api_key_configured": _env_var_configured(provider["api_key_env"]),
            "builtin": False,
            "active": provider["provider_key"] == active_key,
        })

    return providers


def _get_provider_config(
    provider_key: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source = data if isinstance(data, dict) else _read_model_config_file()
    selected_key = _normalize_provider_lookup_key(provider_key) if provider_key else _read_active_provider_key(source)
    providers = get_llm_provider_configs() if data is None else [
        _dashscope_provider_config(source, selected_key),
        *[
            {
                **provider,
                "api_key_configured": _env_var_configured(provider["api_key_env"]),
                "builtin": False,
                "active": provider["provider_key"] == selected_key,
            }
            for provider in _load_custom_provider_configs(source)
        ],
    ]
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
        return _get_dashscope_default_model_name()
    return str(provider.get("default_model") or "").strip()


def get_agent_model_name() -> str:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    override = _read_model_override(data)
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return override or _get_dashscope_default_model_name()

    models = _dedupe_models([str(model) for model in provider.get("models", [])])
    if override and override in models:
        return override
    return str(provider.get("default_model") or models[0]).strip()


def get_llm_model_choices() -> List[str]:
    data = _read_model_config_file()
    provider = _get_provider_config(data=data)
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        return _get_dashscope_model_choices(data)
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
    if normalized == _DEFAULT_PROVIDER_KEY:
        raise ValueError("dashscope 为内置 Provider，不能作为自定义厂商标识")
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


def _validate_provider_base_url(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 必须是有效的 http(s) 地址")
    return normalized


def _normalize_custom_provider_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    name = _validate_provider_name(str(raw.get("name") or ""))
    provider_key = _validate_provider_key(str(raw.get("provider_key") or raw.get("providerKey") or ""))
    api_key_env = _validate_provider_env(str(raw.get("api_key_env") or raw.get("apiKeyEnv") or ""))
    base_url = _validate_provider_base_url(str(raw.get("base_url") or raw.get("baseUrl") or ""))
    default_model = _validate_model_name(str(raw.get("default_model") or raw.get("defaultModel") or ""))
    raw_models = raw.get("models") if isinstance(raw.get("models"), list) else []
    models = _dedupe_models([default_model, *[str(model) for model in raw_models]])
    if not models:
        raise ValueError("模型列表不能为空")
    return {
        "provider_key": provider_key,
        "name": name,
        "api_key_env": api_key_env,
        "base_url": base_url,
        "default_model": default_model,
        "models": models,
    }


def get_llm_model_config() -> Dict[str, Any]:
    provider = _get_provider_config()
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
        "providers": get_llm_provider_configs(),
    }


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


async def set_llm_model_name(model: str) -> Dict[str, Any]:
    normalized = _validate_model_name(model)
    data = _read_model_config_file()
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

    _write_model_config_file(data)
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

    data = _read_model_config_file()
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
        _write_model_config_file(data)
        return get_llm_model_config()

    configured = data.get("models") if isinstance(data.get("models"), list) else []
    data["models"] = [name for name in _dedupe_models([str(item) for item in configured]) if name != normalized]
    data["removed_models"] = _dedupe_models([
        *[name for name in _get_removed_model_names(data) if name not in {current, default}],
        normalized,
    ])
    _write_model_config_file(data)
    return get_llm_model_config()


async def set_llm_provider_key(provider_key: str) -> Dict[str, Any]:
    """Select the active OpenAI-compatible Provider used by shared LLM calls."""
    normalized = _normalize_provider_lookup_key(provider_key)
    data = _read_model_config_file()
    provider = _get_provider_config(provider_key=normalized, data=data)
    api_key_source = _get_provider_api_key_source(provider) or "API Key"
    if not _get_provider_api_key(provider):
        raise ValueError(f"{api_key_source} 未配置，请先在服务器环境变量中设置并重启服务")

    data["provider_key"] = normalized
    current = _read_model_override(data)
    if provider["provider_key"] == _DEFAULT_PROVIDER_KEY:
        choices = _get_dashscope_model_choices(data)
        data["model"] = current if current in choices else _get_dashscope_default_model_name()
    else:
        models = _dedupe_models([str(model) for model in provider.get("models", [])])
        data["model"] = current if current in models else str(provider.get("default_model") or models[0]).strip()
        data["providers"] = _load_custom_provider_configs(data)

    _write_model_config_file(data)
    await reset_qwen_client()
    return get_llm_model_config()


async def add_llm_provider_config(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Add or update a model Provider without persisting API Key secrets."""
    normalized = _normalize_custom_provider_config(provider)
    data = _read_model_config_file()
    raw_providers = data.get("providers") if isinstance(data.get("providers"), list) else []
    providers: List[Dict[str, Any]] = []
    replaced = False

    for raw in raw_providers:
        if not isinstance(raw, dict):
            continue
        try:
            existing = _normalize_custom_provider_config(raw)
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
    _write_model_config_file(data)
    await reset_qwen_client()
    return get_llm_model_config()


class QwenClient:
    """OpenAI Chat Completions 兼容大模型客户端。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        provider_key: str = _DEFAULT_PROVIDER_KEY,
        api_key_source: Optional[str] = None,
    ):
        self.provider_key = provider_key
        self.api_key_source = api_key_source or get_agent_api_key_source() or "API Key"
        self.api_key = api_key or get_agent_api_key()
        self.model = model or get_agent_model_name()
        self.base_url = (base_url or settings.QWEN_BASE_URL).rstrip("/")
        if not self.api_key:
            raise ValueError(f"{self.api_key_source} 未配置，请在服务器环境变量中设置")
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=max(10, int(settings.AI_AGENT_REQUEST_TIMEOUT)),
                trust_env=False,
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
        max_tokens: int = 4096,
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
        max_tokens: int = 4096,
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
qwen_client_signature: Optional[tuple[str, str, str, str]] = None
qwen_clients: Dict[tuple[str, str, str, str], QwenClient] = {}


def get_qwen_client(model: Optional[str] = None, provider_key: Optional[str] = None) -> QwenClient:
    global qwen_client, qwen_client_signature
    provider = _get_provider_config(provider_key=provider_key)
    api_key = _get_provider_api_key(provider)
    if model:
        selected_model = _validate_model_name(model)
    elif provider_key and not provider.get("active"):
        selected_model = str(provider.get("default_model") or "").strip()
    else:
        selected_model = get_agent_model_name()
    base_url = str(provider.get("base_url") or settings.QWEN_BASE_URL).rstrip("/")
    signature = (provider["provider_key"], api_key or "", selected_model, base_url)
    if signature not in qwen_clients:
        qwen_clients[signature] = QwenClient(
            api_key=api_key,
            model=selected_model,
            base_url=base_url,
            provider_key=provider["provider_key"],
            api_key_source=_get_provider_api_key_source(provider),
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

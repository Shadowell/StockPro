"""Operations settings service: KV-backed notify/webhook/LLM config + MCP tokens.

All secrets are stored either as SHA-256 hashes (agent tokens) or as
operator-managed environment variables; the plaintext is returned exactly once
at creation time and never persisted.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

import psycopg2.extras

TOKEN_HEADER_DEFAULT = "X-StockPro-MCP-Token"


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return url[:6] + "…" + url[-4:]
    return url[:20] + "…"


def _mask_token(token: str) -> str:
    if not token:
        return ""
    return f"{token[:8]}…{token[-4:]}" if len(token) > 16 else token[:4] + "…"


class SettingsApplicationService:
    def __init__(self, database, settings: Any):
        self.database = database
        self.settings = settings

    # ------------------------------------------------------------------
    # KV plumbing
    # ------------------------------------------------------------------
    def _kv_get(self, cursor, key: str) -> Optional[Dict[str, Any]]:
        cursor.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
        row = cursor.fetchone()
        return dict(row["value"]) if row else None

    def _kv_set(self, cursor, key: str, value: Mapping[str, Any], actor: str) -> None:
        cursor.execute(
            """
            INSERT INTO app_settings(key, value, updated_by, updated_at)
            VALUES (%s, %s, %s, NOW())
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            (key, psycopg2.extras.Json(dict(value)), actor),
        )

    def _webhook_config(self) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                stored = self._kv_get(cursor, "notify") or {}
        webhook_url = str(stored.get("feishu_webhook_url") or "").strip()
        env_configured = bool(str(getattr(self.settings, "FEISHU_WEBHOOK_URL", "") or "").strip())
        return {
            "enabled": bool(stored.get("enabled", False)),
            "feishu_webhook_url": webhook_url,
            "webhookConfigured": bool(webhook_url or env_configured),
        }

    # ------------------------------------------------------------------
    # Notify / Feishu
    # ------------------------------------------------------------------
    def get_notify(self) -> Dict[str, Any]:
        config = self._webhook_config()
        return {"enabled": config["enabled"], "webhookConfigured": config["webhookConfigured"]}

    def set_notify(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        enabled = bool(payload.get("enabled"))
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                stored = self._kv_get(cursor, "notify") or {}
                stored["enabled"] = enabled
                self._kv_set(cursor, "notify", stored, actor)
        return self.get_notify()

    def get_feishu_webhook(self) -> Dict[str, Any]:
        config = self._webhook_config()
        masked = _mask_url(config["feishu_webhook_url"]) if config["feishu_webhook_url"] else None
        return {"webhookConfigured": config["webhookConfigured"], "maskedWebhookUrl": masked}

    def set_feishu_webhook(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        webhook_url = str(payload.get("webhookUrl") or "").strip()
        if webhook_url and not webhook_url.startswith(("https://open.feishu.cn/", "https://open.larksuite.com/")):
            raise ValueError("飞书 webhook 必须是 open.feishu.cn 或 open.larksuite.com 地址")
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                stored = self._kv_get(cursor, "notify") or {}
                if webhook_url or payload.get("clear"):
                    stored["feishu_webhook_url"] = webhook_url
                self._kv_set(cursor, "notify", stored, actor)
        return self.get_feishu_webhook()

    # ------------------------------------------------------------------
    # LLM model settings
    # ------------------------------------------------------------------
    def _llm_state(self) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                stored = self._kv_get(cursor, "llm") or {}
        api_key = str(
            getattr(self.settings, "DASHSCOPE_API_KEY", None)
            or getattr(self.settings, "QWEN_API_KEY", None)
            or ""
        ).strip()
        default_model = str(getattr(self.settings, "AI_AGENT_MODEL", "qwen3.6-plus") or "qwen3.6-plus")
        models: List[str] = list(stored.get("models") or [default_model])
        active_model = str(stored.get("model") or default_model)
        providers: List[Dict[str, Any]] = [
            {
                "key": "dashscope",
                "label": "DashScope / 通义千问",
                "apiKeyEnv": "DASHSCOPE_API_KEY",
                "baseUrl": str(getattr(self.settings, "QWEN_BASE_URL", "") or "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                "defaultModel": default_model,
                "models": models,
            }
        ]
        active_provider = str(stored.get("provider") or "dashscope")
        return {
            "apiKeyConfigured": bool(api_key),
            "providerKey": active_provider,
            "model": active_model,
            "models": sorted(set(models)),
            "providers": providers,
        }

    def get_llm_model(self) -> Dict[str, Any]:
        state = self._llm_state()
        provider = next((p for p in state["providers"] if p["key"] == state["providerKey"]), state["providers"][0])
        return {
            "apiKeyConfigured": state["apiKeyConfigured"],
            "providerKey": state["providerKey"],
            "model": state["model"],
            "baseUrl": provider["baseUrl"],
            "models": provider["models"],
            "providers": [
                {**p, "active": p["key"] == state["providerKey"]} for p in state["providers"]
            ],
        }

    def set_llm_model(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        model = str(payload.get("model") or "").strip()
        if not model:
            raise ValueError("model 不能为空")
        state = self._llm_state()
        models = sorted(set(state["models"]) | {model})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._kv_set(cursor, "llm", {**state, "model": model, "models": models}, actor)
        return self.get_llm_model()

    def add_llm_model(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        model = str(payload.get("model") or "").strip()
        if not model:
            raise ValueError("model 不能为空")
        state = self._llm_state()
        models = sorted(set(state["models"]) | {model})
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._kv_set(cursor, "llm", {**state, "models": models}, actor)
        return self.get_llm_model()

    def delete_llm_model(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        model = str(payload.get("model") or "").strip()
        state = self._llm_state()
        remaining = [item for item in state["models"] if item != model]
        if not remaining:
            raise ValueError("至少保留一个可用模型")
        patch = {**state, "models": remaining}
        if state["model"] == model:
            patch["model"] = remaining[0]
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._kv_set(cursor, "llm", patch, actor)
        return self.get_llm_model()

    def add_llm_provider(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        # Only DashScope/Qwen is contracted in the current product; custom
        # providers are acknowledged but pinned to the dashscope key.
        return self.get_llm_model()

    def set_llm_provider(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        provider_key = str(payload.get("providerKey") or "dashscope").strip()
        if provider_key != "dashscope":
            raise ValueError("当前产品合同只支持 dashscope Provider")
        state = self._llm_state()
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                self._kv_set(cursor, "llm", {**state, "provider": provider_key}, actor)
        return self.get_llm_model()

    def test_llm_model(self) -> Dict[str, Any]:
        import httpx

        state = self._llm_model_runtime()
        if not state["api_key"]:
            raise ValueError("未配置 DASHSCOPE_API_KEY，不能发起模型测试")
        body = {
            "model": state["model"],
            "messages": [{"role": "user", "content": "回复两个字：就绪"}],
            "max_tokens": 16,
        }
        try:
            response = httpx.post(
                f"{state['base_url'].rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {state['api_key']}"},
                json=body,
                timeout=30,
            )
            response.raise_for_status()
            reply = (response.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
        except Exception as exc:
            raise ValueError(f"模型测试失败：{exc}") from exc
        return {"ok": True, "model": state["model"], "baseUrl": state["base_url"], "reply": str(reply).strip()[:120]}

    def _llm_model_runtime(self) -> Dict[str, Any]:
        state = self._llm_state()
        provider = next((p for p in state["providers"] if p["key"] == state["providerKey"]), state["providers"][0])
        api_key = str(
            getattr(self.settings, "DASHSCOPE_API_KEY", None)
            or getattr(self.settings, "QWEN_API_KEY", None)
            or ""
        ).strip()
        return {
            "api_key": api_key,
            "model": state["model"],
            "base_url": provider["baseUrl"],
        }

    # ------------------------------------------------------------------
    # MCP static token view
    # ------------------------------------------------------------------
    def get_mcp_token(self) -> Dict[str, Any]:
        env_token = str(
            getattr(self.settings, "STOCKPRO_MCP_TOKEN", "")
            or getattr(self.settings, "MCP_STATIC_TOKEN", "")
            or ""
        ).strip()
        remote_enabled = bool(getattr(self.settings, "BITPRO_REMOTE_MCP_ENABLED", False))
        remote_path = str(getattr(self.settings, "BITPRO_REMOTE_MCP_PATH", "/api/mcp"))
        return {
            "configured": bool(env_token) or self._has_active_agent_tokens(),
            "source": "env" if env_token else ("generated" if self._has_active_agent_tokens() else "none"),
            "maskedToken": _mask_token(env_token) if env_token else None,
            "authHeader": TOKEN_HEADER_DEFAULT,
            "tokenEnv": "STOCKPRO_MCP_TOKEN",
            "remoteEnabled": remote_enabled,
            "remotePath": remote_path,
            "requireToken": True,
        }

    def generate_mcp_token(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        created = self.create_agent_token({"name": payload.get("note") or "legacy-mcp-token"}, actor)
        item = created["item"]
        return {
            **self.get_mcp_token(),
            "token": created["token"],
            "maskedToken": item["maskedToken"],
            "createdAt": item["createdAt"],
        }

    # ------------------------------------------------------------------
    # MCP agent tokens
    # ------------------------------------------------------------------
    def _has_active_agent_tokens(self) -> bool:
        with self.database.get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM mcp_agent_tokens WHERE revoked_at IS NULL LIMIT 1")
                return cursor.fetchone() is not None

    def list_agent_tokens(self) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT id, name, token_prefix, scopes, tool_groups, rate_limit_per_min,
                           expires_at, created_by, created_at, last_used_at, revoked_at
                    FROM mcp_agent_tokens
                    WHERE revoked_at IS NULL
                    ORDER BY created_at DESC
                    """
                )
                rows = [dict(row) for row in cursor.fetchall()]
        items = []
        for row in rows:
            items.append(
                {
                    "id": int(row["id"]),
                    "name": row["name"],
                    "tokenPrefix": row["token_prefix"],
                    "maskedToken": f"{row['token_prefix']}…",
                    "scopes": row["scopes"] or ["read"],
                    "toolGroups": row["tool_groups"] or [],
                    "rateLimitPerMin": int(row["rate_limit_per_min"]),
                    "expiresAt": row["expires_at"].isoformat() if row["expires_at"] else None,
                    "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
                    "createdBy": row["created_by"],
                    "lastUsedAt": row["last_used_at"].isoformat() if row["last_used_at"] else None,
                    "revokedAt": None,
                }
            )
        static_env_token = str(getattr(self.settings, "STOCKPRO_MCP_TOKEN", "") or "").strip()
        return {
            "items": items,
            "policy": {
                "plaintextReturnedOnce": True,
                "staticTokenEnv": "STOCKPRO_MCP_TOKEN",
                "authHeaderDefault": TOKEN_HEADER_DEFAULT,
                "tokenManagement": {"hash": "sha256"},
            },
            "status": {
                "configured": bool(static_env_token) or bool(items),
                "envTokenConfigured": bool(static_env_token),
                "activeTokenCount": len(items),
            },
        }

    def create_agent_token(self, payload: Mapping[str, Any], actor: str) -> Dict[str, Any]:
        name = str(payload.get("name") or "").strip() or f"agent-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        expires_in_days = max(1, min(365, int(payload.get("expiresInDays") or 90)))
        rate_limit = max(1, min(600, int(payload.get("rateLimitPerMin") or 60)))
        tool_groups = [str(g) for g in (payload.get("toolGroups") or [])]
        raw_token = f"sp_mcp_{secrets.token_hex(24)}"
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        prefix = raw_token[:12]
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    INSERT INTO mcp_agent_tokens
                    (name, token_prefix, token_hash, scopes, tool_groups,
                     rate_limit_per_min, expires_at, created_by)
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                    RETURNING id, created_at
                    """,
                    (
                        name,
                        prefix,
                        token_hash,
                        json.dumps(["read"]),
                        json.dumps(tool_groups),
                        rate_limit,
                        expires_at,
                        actor,
                    ),
                )
                row = cursor.fetchone()
        item = {
            "id": int(row["id"]),
            "name": name,
            "tokenPrefix": prefix,
            "maskedToken": f"{prefix}…",
            "scopes": ["read"],
            "toolGroups": tool_groups,
            "rateLimitPerMin": rate_limit,
            "expiresAt": expires_at.isoformat(),
            "createdAt": row["created_at"].isoformat(),
            "createdBy": actor,
            "lastUsedAt": None,
            "revokedAt": None,
        }
        return {"token": raw_token, "item": item}

    def revoke_agent_token(self, token_id: int, actor: str) -> Dict[str, Any]:
        with self.database.get_connection() as connection:
            with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(
                    """
                    UPDATE mcp_agent_tokens SET revoked_at = NOW()
                    WHERE id = %s AND revoked_at IS NULL
                    RETURNING revoked_at
                    """,
                    (int(token_id),),
                )
                row = cursor.fetchone()
        if not row:
            raise ValueError("Token 不存在或已撤销")
        return {"id": int(token_id), "revokedAt": row["revoked_at"].isoformat()}

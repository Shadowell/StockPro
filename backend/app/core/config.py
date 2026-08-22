"""StockPro rebuild-safe configuration defaults."""
from __future__ import annotations

import json
from typing import List, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "StockPro"
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:4444",
        "http://127.0.0.1:4444",
    ]
    LOG_LEVEL: str = "INFO"

    DATABASE_BACKEND: str = "postgresql"
    DATABASE_URL: Optional[str] = None
    ENABLE_PRIVATE_EXCHANGE_API: bool = False
    ENABLE_CRYPTO_BACKGROUND_JOBS: bool = False
    ENABLE_LIVE_TRADING: bool = False

    BITPRO_AUTH_ENABLED: bool = False
    BITPRO_ADMIN_USERNAME: Optional[str] = None
    BITPRO_ADMIN_PASSWORD_HASH: Optional[str] = None
    BITPRO_AUTH_COOKIE_NAME: str = "stockpro_session"
    BITPRO_AUTH_COOKIE_SECURE: bool = False
    BITPRO_REMOTE_MCP_ENABLED: bool = False
    BITPRO_REMOTE_MCP_PATH: str = "/api/mcp"

    DASHSCOPE_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    AI_AGENT_MODEL: str = "qwen3.6-plus"
    QWEN_MODEL: str = "qwen3.6-plus"
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, value):
        if isinstance(value, str):
            if value.startswith("["):
                return json.loads(value)
            return [item.strip() for item in value.split(",")]
        return value


settings = Settings()

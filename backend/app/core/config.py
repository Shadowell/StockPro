"""StockPro rebuild-safe configuration defaults."""
from __future__ import annotations

import json
from typing import Annotated, List, Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "StockPro"
    BACKEND_CORS_ORIGINS: Annotated[List[str], NoDecode] = [
        "http://localhost:4444",
        "http://127.0.0.1:4444",
    ]
    LOG_LEVEL: str = "INFO"

    DATABASE_BACKEND: Literal["postgresql"] = "postgresql"
    DATABASE_URL: str
    RUNTIME_MODE: Literal["ashare_paper"] = "ashare_paper"
    ENABLE_PROVIDER_FETCH: bool = False
    ENABLE_SCHEDULER: bool = False
    ENABLE_PAPER_RECOVERY: bool = False
    ENABLE_PRIVATE_EXCHANGE_API: bool = False
    ENABLE_CRYPTO_BACKGROUND_JOBS: bool = False
    ENABLE_LIVE_TRADING: bool = False

    AUTH_ENABLED: bool = True
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: Optional[str] = None
    ADMIN_TOKEN_SECRET: Optional[str] = None
    AUTH_TOKEN_TTL_SECONDS: int = 86_400
    AUTH_COOKIE_NAME: str = "stockpro_session"
    AUTH_COOKIE_SECURE: bool = False

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
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    value = value.removeprefix("[").removesuffix("]")
            return [item.strip() for item in value.split(",")]
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("StockPro rebuild requires PostgreSQL")
        return value


settings = Settings()

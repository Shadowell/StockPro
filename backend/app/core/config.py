import json
from typing import List, Union

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    API_PREFIX: str = "/api"
    PROJECT_NAME: str = "Stock Analysis App"

    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    QWEN_API_KEY: str = ""
    QWEN_STOCK_MODEL: str = "qwen-plus"

    TUSHARE_TOKEN: str = ""
    TUSHARE_REALTIME_SOURCE: str = "dc"
    ENABLE_TUSHARE: bool = True
    AKSHARE_TIMEOUT: int = 30
    RUN_STARTUP_DATA_SYNC: bool = False
    ENABLE_SCHEDULER: bool = True
    ENABLE_REALTIME_SYNC: bool = False
    ENABLE_STRATEGY_EXECUTION: bool = True
    ENABLE_EXTERNAL_MARKET_FETCH: bool = True

    ENFORCE_OPERATION_ALLOWLIST: bool = False
    OPERATION_ALLOWLIST: List[str] = []

    @field_validator("OPERATION_ALLOWLIST", mode="before")
    def assemble_operation_allowlist(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        if isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = ""
    ADMIN_TOKEN_SECRET: str = ""
    ADMIN_TOKEN_TTL_SECONDS: int = 60 * 60 * 12

    DATABASE_URL: str = "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        enable_decoding=False,
        extra="ignore",
    )


settings = Settings()

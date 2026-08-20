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
    QWEN_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    LIVE_TRADING_ENABLED: bool = False
    LIVE_MINIQMT_ENABLED: bool = False
    LIVE_PTRADE_ENABLED: bool = False
    LIVE_MAX_SINGLE_ORDER_VALUE: float = 200_000.0
    LIVE_MAX_POSITION_WEIGHT: float = 0.3
    LIVE_MAX_DAILY_LOSS_RATIO: float = 0.05

    TUSHARE_TOKEN: str = ""
    TUSHARE_CREDIT_TIER: int = 5000
    TUSHARE_REALTIME_SOURCE: str = "dc"
    ENABLE_TUSHARE: bool = True
    AKSHARE_TIMEOUT: int = 30
    AKSHARE_SUBPROCESS_FALLBACK: bool = True
    RUN_STARTUP_DATA_SYNC: bool = False
    RUN_MIGRATIONS_ON_STARTUP: bool = False
    RUN_BOOTSTRAP_ON_STARTUP: bool = False
    RUN_PAPER_RECOVERY_ON_STARTUP: bool = False
    ENABLE_SCHEDULER: bool = False
    ENABLE_LOCAL_PG_BACKUP: bool = True
    LOCAL_PG_BACKUP_CRON: str = "30 2 * * *"
    ENABLE_REALTIME_SYNC: bool = False
    ENABLE_STRATEGY_EXECUTION: bool = False
    ENABLE_EXTERNAL_MARKET_FETCH: bool = False

    ENFORCE_OPERATION_ALLOWLIST: bool = False
    OPERATION_ALLOWLIST: List[str] = []
    EXTENSION_HTTP_ALLOWED_HOSTS: List[str] = []

    @field_validator("OPERATION_ALLOWLIST", "EXTENSION_HTTP_ALLOWED_HOSTS", mode="before")
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

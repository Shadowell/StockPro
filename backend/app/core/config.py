import json
from typing import List, Union
from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Stock Analysis App"
    
    # CORS
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = []

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # AI
    QWEN_API_KEY: str = ""
    QWEN_STOCK_MODEL: str = "qwen-plus"
    
    # Akshare
    AKSHARE_TIMEOUT: int = 30
    RUN_STARTUP_DATA_SYNC: bool = False
    START_REALTIME_SYNC_SERVICE: bool = False

    # Operation allowlist
    ENFORCE_OPERATION_ALLOWLIST: bool = False
    OPERATION_ALLOWLIST: List[str] = []

    @field_validator("OPERATION_ALLOWLIST", mode="before")
    def assemble_operation_allowlist(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and v.startswith("["):
            return json.loads(v)
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)
    
    # Database mode: V1 core uses PostgreSQL. SQLite remains legacy-only and is
    # not used unless DB_MODE is explicitly set to "local".
    DB_MODE: str = "postgres"
    DATABASE_URL: str = "postgresql://stockpro:stockpro@127.0.0.1:55432/stockpro"
    LOCAL_DB_PATH: Union[str, None] = None
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        enable_decoding=False,
        extra="ignore"
    )

settings = Settings()

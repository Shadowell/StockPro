"""Active PostgreSQL settings domain."""

from app.domain.settings.service import PostgresSettingsService, postgres_settings_service

__all__ = ["PostgresSettingsService", "postgres_settings_service"]

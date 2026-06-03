from app.core.config import settings

supabase = None


def get_database():
    if settings.DB_MODE == "local":
        from app.db.local_db import db_instance

        return db_instance
    if settings.DB_MODE == "supabase":
        from supabase import create_client

        url: str = settings.SUPABASE_URL
        key: str = settings.SUPABASE_SERVICE_KEY if settings.SUPABASE_SERVICE_KEY else settings.SUPABASE_KEY
        return create_client(url, key)
    if settings.DB_MODE == "postgres":
        raise RuntimeError("Use Postgres repositories or migrations for DB_MODE=postgres")
    raise RuntimeError(f"Unsupported DB_MODE: {settings.DB_MODE}")

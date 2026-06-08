from app.db.postgres_db import PostgresDatabase


db_instance = PostgresDatabase()


def get_database() -> PostgresDatabase:
    return db_instance

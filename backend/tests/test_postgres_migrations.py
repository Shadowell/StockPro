import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.db.postgres_migrations import apply_migrations, load_migrations


class PostgresMigrationTests(unittest.TestCase):
    def test_load_migrations_returns_sorted_sql_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "202606030002_second.sql").write_text("select 2;", encoding="utf-8")
            (root / "notes.txt").write_text("ignore me", encoding="utf-8")
            (root / "202606030001_first.sql").write_text("select 1;", encoding="utf-8")

            migrations = load_migrations(root)

        self.assertEqual(
            [migration.version for migration in migrations],
            ["202606030001_first", "202606030002_second"],
        )
        self.assertEqual(migrations[0].sql, "select 1;")

    def test_apply_migrations_runs_only_pending_files_and_records_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "202606030001_existing.sql").write_text("select 1;", encoding="utf-8")
            (root / "202606030002_pending.sql").write_text("select 2;", encoding="utf-8")

            cursor = MagicMock()
            cursor.fetchall.return_value = [("202606030001_existing",)]
            connection = MagicMock()
            connection.cursor.return_value.__enter__.return_value = cursor

            with patch("app.db.postgres_migrations.psycopg.connect") as connect:
                connect.return_value.__enter__.return_value = connection
                applied = apply_migrations("postgresql://example", migrations_dir=root)

        self.assertEqual(applied, ["202606030002_pending"])
        executed_sql = [call.args[0] for call in cursor.execute.call_args_list]
        self.assertIn("select 2;", executed_sql)
        self.assertNotIn("select 1;", executed_sql)
        cursor.execute.assert_any_call(
            "INSERT INTO schema_migrations (version) VALUES (%s)",
            ("202606030002_pending",),
        )
        connection.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()

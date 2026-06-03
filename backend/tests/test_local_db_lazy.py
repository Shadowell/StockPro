import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


class LocalDatabaseLazyImportTests(unittest.TestCase):
    def test_importing_local_db_does_not_create_sqlite_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "stock_data.db"
            previous_path = os.environ.get("LOCAL_DB_PATH")
            os.environ["LOCAL_DB_PATH"] = str(db_path)
            sys.modules.pop("app.db.local_db", None)

            try:
                local_db = importlib.import_module("app.db.local_db")
                importlib.reload(local_db)
            finally:
                if previous_path is None:
                    os.environ.pop("LOCAL_DB_PATH", None)
                else:
                    os.environ["LOCAL_DB_PATH"] = previous_path

            self.assertFalse(db_path.exists())


if __name__ == "__main__":
    unittest.main()

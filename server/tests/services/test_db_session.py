"""Regression tests for resilient ad-hoc database session access."""

import os
import sys
import tempfile
import unittest
from importlib import import_module
from pathlib import Path

from sqlalchemy import inspect

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

config_module = import_module("app.config")
db_session_module = import_module("app.db.session")


class ManagedSessionTestCase(unittest.TestCase):
    """Ensure ad-hoc sessions recreate required tables after DB resets."""

    def setUp(self) -> None:
        """Point runtime settings at one isolated SQLite file."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "pivot.db"
        self.original_database_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{self.db_path}"
        config_module.get_settings.cache_clear()

    def tearDown(self) -> None:
        """Restore the previous database URL after each test."""
        if self.original_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.original_database_url
        config_module.get_settings.cache_clear()
        self.temp_dir.cleanup()

    def test_managed_session_recreates_required_tables_after_file_reset(self) -> None:
        """Opening a managed session should rebuild schema after DB deletion."""
        with db_session_module.managed_session():
            self.assertTrue(self.db_path.exists())

        self.db_path.unlink(missing_ok=True)

        with db_session_module.managed_session() as session:
            table_names = set(inspect(session.get_bind()).get_table_names())

        self.assertIn("agentchannelbinding", table_names)
        self.assertIn("fileasset", table_names)


if __name__ == "__main__":
    unittest.main()

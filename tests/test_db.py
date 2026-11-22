import os
import unittest
from unittest.mock import MagicMock, patch

from azul_ai.core import db
from azul_ai.core.config import get_required


class DatabaseConnectionTests(unittest.TestCase):
    def test_requires_database_url(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Set DATABASE_URL"):
                db.connect_to_database()

    def test_rejects_non_postgresql_database_url(self):
        with patch.dict(os.environ, {"DATABASE_URL": "mysql://user:pass@host/db"}):
            with self.assertRaisesRegex(ValueError, "PostgreSQL URL"):
                db.connect_to_database()

    @patch("azul_ai.core.db.psycopg.connect")
    def test_connects_using_url_and_environment_overrides(self, connect):
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://url-user:url-pass@db/url-db?sslmode=require",
                "POSTGRES_HOST": "database.internal",
                "POSTGRES_DB": "override-db",
                "POSTGRES_USER": "override-user",
                "POSTGRES_PASSWORD": "override-pass",
            },
            clear=True,
        ):
            db.connect_to_database()

        connect.assert_called_once_with(
            dbname="override-db",
            user="override-user",
            password="override-pass",
            host="database.internal",
            port=5432,
            sslmode="require",
        )

    @patch("azul_ai.core.db.psycopg.connect")
    def test_uses_localhost_for_compose_database_hostname(self, connect):
        with patch.dict(
            os.environ,
            {"DATABASE_URL": "postgres://user:pass@db/name"},
            clear=True,
        ):
            db.connect_to_database()

        self.assertEqual(connect.call_args.kwargs["host"], "localhost")


class DatabaseOperationTests(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()

    def test_rejects_missing_participant_identity(self):
        with self.assertRaisesRegex(ValueError, "platform and stable user ID"):
            db.record_session_participant(self.connection, "session", "", "user")
        self.connection.execute.assert_not_called()

    def test_rejects_invalid_session_retention_days(self):
        for days in (0, -1, True):
            with self.subTest(days=days), self.assertRaisesRegex(
                ValueError, "positive integer"
            ):
                db.delete_stale_sessions(self.connection, days, "slack", "user")
        self.connection.execute.assert_not_called()

    def test_rejects_missing_preserved_participant(self):
        with self.assertRaisesRegex(ValueError, "platform and stable user ID"):
            db.delete_stale_sessions(self.connection, 30, "slack", "")
        self.connection.execute.assert_not_called()

    def test_deletes_sessions_and_returns_count(self):
        self.connection.execute.return_value.rowcount = 3

        deleted_count = db.delete_stale_sessions(
            self.connection, 30, "slack", "user"
        )

        self.assertEqual(deleted_count, 3)
        self.connection.execute.assert_called_once()
        self.assertEqual(
            self.connection.execute.call_args.args[1],
            (30, "slack", "user"),
        )

    def test_loads_messages_in_database_order(self):
        messages = [{"role": "system"}, {"role": "user"}]
        self.connection.execute.return_value.fetchall.return_value = [
            (message,) for message in messages
        ]

        self.assertEqual(db.load_messages(self.connection, "session"), messages)


class ConfigurationTests(unittest.TestCase):
    def test_requires_configured_value(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Set REQUIRED_KEY"):
                get_required("REQUIRED_KEY")

    def test_returns_configured_value(self):
        with patch.dict(os.environ, {"REQUIRED_KEY": "value"}):
            self.assertEqual(get_required("REQUIRED_KEY"), "value")


if __name__ == "__main__":
    unittest.main()

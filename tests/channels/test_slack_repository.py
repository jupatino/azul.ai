import unittest
from unittest.mock import MagicMock, patch

from azul_ai.channels.slack import repository


class SlackRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()

    @patch("azul_ai.channels.slack.repository.initialize_session_tables")
    def test_initializes_session_and_slack_tables(self, initialize_session_tables):
        repository.initialize_slack_tables(self.connection)

        initialize_session_tables.assert_called_once_with(self.connection)
        self.assertEqual(self.connection.execute.call_count, 2)

    @patch("azul_ai.channels.slack.repository.uuid4", return_value="new-session")
    @patch("azul_ai.channels.slack.repository.save_message")
    def test_creates_thread_session_when_missing(self, save_message, uuid4):
        self.connection.execute.return_value.fetchone.return_value = None

        session_id = repository.get_or_create_thread_session(
            self.connection, "team", "channel", "thread"
        )

        self.assertEqual(session_id, "new-session")
        uuid4.assert_called_once_with()
        save_message.assert_called_once()
        self.assertEqual(self.connection.execute.call_count, 4)

    def test_returns_existing_thread_session(self):
        self.connection.execute.return_value.fetchone.return_value = ("existing",)

        session_id = repository.get_or_create_thread_session(
            self.connection, "team", "channel", "thread"
        )

        self.assertEqual(session_id, "existing")
        self.assertEqual(self.connection.execute.call_count, 2)

    def test_gets_existing_channel_command_session(self):
        self.connection.execute.return_value.fetchone.return_value = (
            "thread",
            "session",
        )

        result = repository.get_command_session(self.connection, "team", "channel")

        self.assertEqual(result, ("thread", "session"))

    def test_gets_existing_direct_message_command_session(self):
        self.connection.execute.return_value.fetchone.return_value = (
            "direct-message",
            "session",
        )

        result = repository.get_command_session(self.connection, "team", "D123")

        self.assertEqual(result, ("direct-message", "session"))
        self.assertIn("thread_ts = %s", self.connection.execute.call_args.args[0])

    def test_requires_existing_session_for_channel_command(self):
        self.connection.execute.return_value.fetchone.return_value = None

        with self.assertRaisesRegex(ValueError, "no agent session"):
            repository.get_command_session(self.connection, "team", "channel")

    @patch("azul_ai.channels.slack.repository.uuid4", return_value="new-session")
    @patch("azul_ai.channels.slack.repository.save_message")
    def test_creates_initial_direct_message_command_session(self, save_message, uuid4):
        self.connection.execute.return_value.fetchone.return_value = None

        result = repository.get_command_session(self.connection, "team", "D123")

        self.assertEqual(result, ("direct-message", "new-session"))
        uuid4.assert_called_once_with()
        save_message.assert_called_once()
        self.assertEqual(self.connection.execute.call_count, 4)

    @patch("azul_ai.channels.slack.repository.uuid4", return_value="new-session")
    @patch("azul_ai.channels.slack.repository.save_message")
    def test_replaces_session_for_new_conversation(self, save_message, uuid4):
        self.connection.execute.return_value.rowcount = 1

        result = repository.create_new_session(
            self.connection, "team", "channel", "thread", "old-session"
        )

        self.assertEqual(result, "new-session")
        uuid4.assert_called_once_with()
        save_message.assert_called_once()
        self.assertEqual(
            self.connection.execute.call_args.args[1],
            ("new-session", "team", "channel", "thread", "old-session"),
        )

    @patch("azul_ai.channels.slack.repository.save_message")
    def test_fails_when_session_cannot_be_replaced(self, save_message):
        self.connection.execute.return_value.rowcount = 0

        with self.assertRaisesRegex(RuntimeError, "Unable to switch"):
            repository.create_new_session(
                self.connection, "team", "channel", "thread", "old-session"
            )

        save_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()

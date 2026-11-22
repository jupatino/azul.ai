import unittest
from unittest.mock import MagicMock, patch

from azul_ai.channels.telegram import repository


class TelegramRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.connection = MagicMock()

    @patch("azul_ai.channels.telegram.repository.initialize_session_tables")
    def test_initializes_session_and_telegram_tables(self, initialize_session_tables):
        repository.initialize_telegram_tables(self.connection)

        initialize_session_tables.assert_called_once_with(self.connection)
        self.assertEqual(self.connection.execute.call_count, 2)

    @patch("azul_ai.channels.telegram.repository.uuid4", return_value="new-session")
    @patch("azul_ai.channels.telegram.repository.save_message")
    def test_creates_chat_session_when_missing(self, save_message, uuid4):
        self.connection.execute.return_value.fetchone.return_value = None

        session_id = repository.get_or_create_chat_session(self.connection, "chat")

        self.assertEqual(session_id, "new-session")
        uuid4.assert_called_once_with()
        save_message.assert_called_once_with(
            self.connection,
            "new-session",
            {"role": "system", "content": repository.SYSTEM_PROMPT},
        )
        self.assertEqual(self.connection.execute.call_count, 4)

    def test_returns_existing_chat_session(self):
        self.connection.execute.return_value.fetchone.return_value = ("existing",)

        session_id = repository.get_or_create_chat_session(self.connection, "chat")

        self.assertEqual(session_id, "existing")
        self.assertEqual(self.connection.execute.call_count, 2)

    @patch("azul_ai.channels.telegram.repository.uuid4", return_value="new-session")
    @patch("azul_ai.channels.telegram.repository.save_message")
    def test_switches_chat_to_new_session(self, save_message, uuid4):
        self.connection.execute.return_value.rowcount = 1

        session_id = repository.create_new_chat_session(
            self.connection, "chat", "old-session"
        )

        self.assertEqual(session_id, "new-session")
        uuid4.assert_called_once_with()
        save_message.assert_called_once_with(
            self.connection,
            "new-session",
            {"role": "system", "content": repository.SYSTEM_PROMPT},
        )
        self.connection.execute.assert_called()

    @patch("azul_ai.channels.telegram.repository.save_message")
    def test_fails_if_chat_session_cannot_be_switched(self, save_message):
        self.connection.execute.return_value.rowcount = 0

        with self.assertRaisesRegex(RuntimeError, "Unable to switch"):
            repository.create_new_chat_session(self.connection, "chat", "old-session")

        save_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()

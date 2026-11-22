import unittest
from unittest.mock import MagicMock, patch

from azul_ai.core.session import AgentSessionService


class AgentSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = AgentSessionService("system", ["schema"], {"tool": lambda: "ok"})
        self.connection = MagicMock()
        self.session_id = "session"

    @patch("azul_ai.core.session.create_session", return_value="created")
    def test_create_uses_configured_system_prompt(self, create_session):
        self.assertEqual(self.service.create(self.connection), "created")
        create_session.assert_called_once_with(self.connection, "system")

    @patch("azul_ai.core.session.save_message")
    def test_reset_deletes_history_and_restores_system_prompt(self, save_message):
        self.service.reset(self.connection, self.session_id)

        self.connection.execute.assert_called_once_with(
            "DELETE FROM agent_session_messages WHERE session_id = %s",
            (self.session_id,),
        )
        save_message.assert_called_once_with(
            self.connection,
            self.session_id,
            {"role": "system", "content": "system"},
        )

    def test_refresh_updates_existing_system_prompt(self):
        self.connection.execute.return_value.rowcount = 1

        self.service.refresh_system_prompt(self.connection, self.session_id)

        self.connection.execute.assert_called_once()

    def test_refresh_raises_when_system_prompt_is_missing(self):
        self.connection.execute.return_value.rowcount = 0

        with self.assertRaisesRegex(RuntimeError, "has no system prompt"):
            self.service.refresh_system_prompt(self.connection, self.session_id)

    @patch("azul_ai.core.session.run_agent", return_value="answer")
    @patch("azul_ai.core.session.load_messages", return_value=[{"role": "system"}])
    @patch("azul_ai.core.session.save_message")
    def test_process_appends_user_message_and_runs_agent(
        self, save_message, load_messages, run_agent
    ):
        result = self.service.process(self.connection, self.session_id, "question")

        self.assertEqual(result, "answer")
        save_message.assert_called_once_with(
            self.connection,
            self.session_id,
            {"role": "user", "content": "question"},
        )
        run_agent.assert_called_once_with(
            self.connection,
            self.session_id,
            [{"role": "system"}],
            ["schema"],
            self.service.tools,
            8,
        )

    @patch("azul_ai.core.session.run_agent", return_value="answer")
    @patch("azul_ai.core.session.load_messages", return_value=[])
    @patch("azul_ai.core.session.save_message")
    def test_process_can_skip_duplicate_user_message(
        self, save_message, load_messages, run_agent
    ):
        self.service.process(
            self.connection,
            self.session_id,
            "question",
            append_user_message=False,
        )

        save_message.assert_not_called()
        run_agent.assert_called_once()

    @patch("azul_ai.core.session.load_messages", return_value=[{"role": "system"}])
    def test_compact_rejects_empty_conversation(self, load_messages):
        with self.assertRaisesRegex(ValueError, "no conversation history"):
            self.service.compact(self.connection, self.session_id)

    @patch("azul_ai.core.session.get_client")
    @patch("azul_ai.core.session.load_messages")
    @patch("azul_ai.core.session.save_message")
    def test_compact_summarizes_history_and_replaces_it(
        self, save_message, load_messages, get_client
    ):
        load_messages.return_value = [
            {"role": "system", "content": "old"},
            {"role": "user", "content": "question"},
        ]
        get_client.return_value.chat.completions.create.return_value.choices[
            0
        ].message.content = "summary"

        result = self.service.compact(self.connection, self.session_id)

        self.assertEqual(result, "summary")
        self.connection.execute.assert_called_once()
        save_message.assert_called_once_with(
            self.connection,
            self.session_id,
            {"role": "assistant", "content": "Conversation summary for continuity:\nsummary"},
        )

    @patch("azul_ai.core.session.load_messages")
    def test_compact_rejects_more_than_allowed_chunks(self, load_messages):
        load_messages.return_value = [
            {"role": "user", "content": "first"},
            {"role": "user", "content": "second"},
        ]

        with self.assertRaisesRegex(ValueError, "too large to compact"):
            self.service.compact(
                self.connection,
                self.session_id,
                max_message_chars=100,
                max_chunk_chars=1,
                max_chunks=1,
            )

    @patch("azul_ai.core.session.get_client")
    @patch("azul_ai.core.session.load_messages", return_value=[{"role": "user", "content": "x"}])
    def test_compact_rejects_empty_model_summary(self, load_messages, get_client):
        get_client.return_value.chat.completions.create.return_value.choices[
            0
        ].message.content = None

        with self.assertRaisesRegex(RuntimeError, "empty summary"):
            self.service.compact(self.connection, self.session_id)


if __name__ == "__main__":
    unittest.main()

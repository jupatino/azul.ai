import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from azul_ai.core import agent


def make_completion(content=None, tool_calls=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
        model_dump=lambda **kwargs: {"role": "assistant", "content": content},
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class AgentToolTests(unittest.TestCase):
    def test_runs_registered_tool_and_stringifies_result(self):
        tool = SimpleNamespace(
            function=SimpleNamespace(name="echo", arguments='{"value": 42}')
        )

        self.assertEqual(agent.run_tool(tool, {"echo": lambda value: value}), "42")

    def test_rejects_unregistered_tool(self):
        tool = SimpleNamespace(
            function=SimpleNamespace(name="unknown", arguments="{}")
        )

        self.assertIn("unsupported tool", agent.run_tool(tool, {}))

    def test_reports_invalid_arguments_and_tool_errors(self):
        invalid_json = SimpleNamespace(
            function=SimpleNamespace(name="echo", arguments="{")
        )
        failing_tool = SimpleNamespace(
            function=SimpleNamespace(name="fail", arguments="{}")
        )

        self.assertIn("Error running tool", agent.run_tool(invalid_json, {"echo": str}))
        self.assertIn(
            "Error running tool",
            agent.run_tool(failing_tool, {"fail": lambda: 1 / 0}),
        )


class RunAgentTests(unittest.TestCase):
    def setUp(self):
        self.connection = Mock()
        self.session_id = "session"

    @patch("azul_ai.core.agent.get_client")
    @patch("azul_ai.core.db.save_message")
    def test_returns_assistant_text(self, save_message, get_client):
        get_client.return_value.chat.completions.create.return_value = make_completion("done")

        result = agent.run_agent(self.connection, self.session_id, [], [], {})

        self.assertEqual(result, "done")
        save_message.assert_called_once_with(
            self.connection,
            self.session_id,
            {"role": "assistant", "content": "done"},
        )

    @patch("azul_ai.core.agent.get_client")
    @patch("azul_ai.core.db.load_messages", return_value=[])
    @patch("azul_ai.core.db.save_message")
    def test_runs_tool_then_returns_final_answer(self, save_message, load_messages, get_client):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="echo", arguments='{"value":"result"}'),
        )
        get_client.return_value.chat.completions.create.side_effect = [
            make_completion(tool_calls=[tool_call]),
            make_completion("finished"),
        ]

        result = agent.run_agent(
            self.connection,
            self.session_id,
            [],
            ["schema"],
            {"echo": lambda value: value},
        )

        self.assertEqual(result, "finished")
        self.assertEqual(save_message.call_count, 3)
        self.assertEqual(load_messages.call_count, 1)

    @patch("azul_ai.core.agent.get_client")
    @patch("azul_ai.core.db.save_message")
    def test_uses_fallback_for_empty_assistant_text(self, save_message, get_client):
        get_client.return_value.chat.completions.create.return_value = make_completion("")

        result = agent.run_agent(self.connection, self.session_id, [], [], {})

        self.assertEqual(result, "I couldn't generate a text response.")

    @patch("azul_ai.core.agent.get_client")
    @patch("azul_ai.core.db.load_messages", return_value=[])
    @patch("azul_ai.core.db.save_message")
    def test_raises_when_tool_round_limit_is_exceeded(self, save_message, load_messages, get_client):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="echo", arguments="{}"),
        )
        get_client.return_value.chat.completions.create.return_value = make_completion(
            tool_calls=[tool_call]
        )

        with self.assertRaisesRegex(RuntimeError, "exceeded 1 tool-call rounds"):
            agent.run_agent(
                self.connection,
                self.session_id,
                [],
                [],
                {"echo": lambda: "ok"},
                max_rounds=1,
            )

    @patch("azul_ai.core.agent.OpenAI")
    @patch("azul_ai.core.agent.get_required", return_value="key")
    def test_get_client_caches_initialized_client(self, get_required, openai):
        original_client = agent.client
        self.addCleanup(setattr, agent, "client", original_client)
        agent.client = None

        first = agent.get_client()
        second = agent.get_client()

        self.assertIs(first, second)
        openai.assert_called_once_with(
            api_key="key",
            base_url="https://openrouter.ai/api/v1",
            max_retries=5,
        )
        get_required.assert_called_once_with("OPENROUTER_API_KEY")


if __name__ == "__main__":
    unittest.main()

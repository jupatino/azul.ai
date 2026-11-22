import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

with (
    patch.dict(
        os.environ,
        {
            "SLACK_BOT_TOKEN": "xoxb-test-token",
            "SLACK_SIGNING_SECRET": "test-signing-secret",
            "SLACK_ALLOWED_USER_IDS": "U123",
        },
    ),
    patch("azul_ai.channels.slack.repository.initialize_slack_tables"),
    patch("azul_ai.core.db.connect_to_database"),
):
    slack_app = importlib.import_module("azul_ai.channels.slack.app")


class SlackMessageTestCase(unittest.TestCase):
    def test_normalizes_mention_and_uses_event_team_fallback(self):
        message = slack_app.normalize_slack_message(
            {"event_id": "event"},
            {
                "user": "U123",
                "text": "<@UBOT>  hello <@U456>",
                "team": "team",
                "channel": "channel",
                "channel_type": "im",
                "ts": "message-ts",
            },
        )

        self.assertEqual(
            (
                message.channel,
                message.sender_id,
                message.conversation_id,
                message.thread_id,
                message.event_id,
                message.text,
            ),
            ("slack", "U123", "team:channel", "direct-message", "event", "hello"),
        )

    def test_uses_thread_timestamp_when_present(self):
        message = slack_app.normalize_slack_message(
            {"team_id": "team", "event_id": "event"},
            {
                "user": "U123",
                "text": "hello",
                "channel": "channel",
                "thread_ts": "thread",
                "ts": "message-ts",
            },
        )

        self.assertEqual(message.thread_id, "thread")

    def test_rejects_event_missing_required_identifiers(self):
        with self.assertRaisesRegex(ValueError, "missing required identifiers"):
            slack_app.normalize_slack_message({}, {"user": "U123", "text": "hello"})

    def test_ignores_non_allowlisted_user_and_empty_message(self):
        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database") as connect,
        ):
            unauthorized = slack_app.process_slack_message(
                {"team_id": "team", "event_id": "event"},
                {
                    "user": "U999",
                    "text": "hello",
                    "channel": "channel",
                    "ts": "ts",
                },
            )
            empty = slack_app.process_slack_message(
                {"team_id": "team", "event_id": "event"},
                {
                    "user": "U123",
                    "text": "<@UBOT>",
                    "channel": "channel",
                    "ts": "ts",
                },
            )

        self.assertIsNone(unauthorized)
        self.assertIsNone(empty)
        connect.assert_not_called()

    @patch("azul_ai.channels.slack.app.record_session_participant")
    @patch("azul_ai.channels.slack.app.get_or_create_thread_session", return_value="session")
    def test_processes_new_event_and_marks_it_completed(
        self, get_or_create_thread_session, record_session_participant
    ):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("event",)
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()
        service.process.return_value = "answer"

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "record_session_participant", record_session_participant),
            patch.object(
                slack_app,
                "get_or_create_thread_session",
                get_or_create_thread_session,
            ),
        ):
            result = slack_app.process_slack_message(
                {"team_id": "team", "event_id": "event"},
                {
                    "user": "U123",
                    "text": "hello",
                    "channel": "channel",
                    "ts": "thread",
                },
            )

        self.assertEqual(result, "answer")
        get_or_create_thread_session.assert_called_once_with(
            connection, "team", "channel", "thread"
        )
        record_session_participant.assert_called_once_with(
            connection, "session", "slack", "U123"
        )
        service.refresh_system_prompt.assert_called_once_with(connection, "session")
        service.process.assert_called_once_with(
            connection, "session", "hello", append_user_message=True
        )
        self.assertIn("status = 'completed'", connection.execute.call_args.args[0])

    def test_ignores_already_processed_nonfailed_event(self):
        connection = MagicMock()
        connection.execute.side_effect = [
            _cursor(None),
            _cursor(("session", "completed")),
        ]
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
        ):
            result = slack_app.process_slack_message(
                {"team_id": "team", "event_id": "event"},
                {
                    "user": "U123",
                    "text": "hello",
                    "channel": "channel",
                    "ts": "thread",
                },
            )

        self.assertIsNone(result)
        service.process.assert_not_called()

    def test_retries_failed_event_without_appending_user_message_again(self):
        connection = MagicMock()
        connection.execute.side_effect = lambda query, *_: (
            _cursor(None)
            if "INSERT INTO slack_processed_events" in query
            else _cursor(("session", "failed"))
            if "SELECT session_id, status" in query
            else MagicMock()
        )
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()
        service.process.return_value = "answer"

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "record_session_participant"),
        ):
            result = slack_app.process_slack_message(
                {"team_id": "team", "event_id": "event"},
                {
                    "user": "U123",
                    "text": "hello",
                    "channel": "channel",
                    "ts": "thread",
                },
            )

        self.assertEqual(result, "answer")
        service.process.assert_called_once_with(
            connection, "session", "hello", append_user_message=False
        )

    def test_marks_event_failed_and_reraises_processing_error(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("event",)
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()
        service.process.side_effect = RuntimeError("model failed")

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "get_or_create_thread_session", return_value="session"),
        ):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                slack_app.process_slack_message(
                    {"team_id": "team", "event_id": "event"},
                    {
                        "user": "U123",
                        "text": "hello",
                        "channel": "channel",
                        "ts": "thread",
                    },
                )

        self.assertTrue(
            any(
                "status = 'failed'" in call.args[0]
                for call in connection.execute.call_args_list
            )
        )


class SlackHandlerTestCase(unittest.TestCase):
    def test_ignores_non_private_direct_messages_and_bot_events(self):
        say = MagicMock()

        for event in (
            {"channel_type": "channel"},
            {"channel_type": "im", "subtype": "message_changed"},
            {"channel_type": "im", "bot_id": "B123"},
        ):
            with self.subTest(event=event):
                slack_app.handle_message_event({}, event, say, direct_message=True)

        say.assert_not_called()

    def test_replies_to_mentions_in_the_original_thread(self):
        say = MagicMock()

        with patch.object(slack_app, "process_slack_message", return_value="answer"):
            slack_app.handle_message_event(
                {"event_id": "event"},
                {"ts": "thread"},
                say,
            )

        say.assert_called_once_with(text="answer", thread_ts="thread")

    def test_replies_to_direct_message_without_forcing_a_thread(self):
        say = MagicMock()

        with patch.object(slack_app, "process_slack_message", return_value="answer"):
            slack_app.handle_message_event(
                {"event_id": "event"},
                {"channel_type": "im", "ts": "message"},
                say,
                direct_message=True,
            )

        say.assert_called_once_with(text="answer")

    def test_reports_message_processing_failure(self):
        say = MagicMock()

        with (
            patch.object(slack_app, "process_slack_message", side_effect=RuntimeError),
            patch.object(slack_app.logger, "exception"),
        ):
            slack_app.handle_message_event(
                {"event_id": "event"},
                {"ts": "thread"},
                say,
            )

        say.assert_called_once_with(
            text="I couldn't process that request.",
            thread_ts="thread",
        )

    def test_session_command_rejects_unauthorized_user(self):
        respond = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database") as connect,
        ):
            slack_app.run_session_command(
                {"user_id": "U999"}, respond, "reset"
            )

        connect.assert_not_called()
        respond.assert_called_once()
        self.assertEqual(respond.call_args.kwargs["response_type"], "ephemeral")

    def test_session_command_requires_team_and_channel(self):
        respond = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database") as connect,
        ):
            slack_app.run_session_command({"user_id": "U123"}, respond, "reset")

        connect.assert_not_called()
        self.assertIn("did not provide", respond.call_args.kwargs["text"])

    def test_session_command_resets_session_and_replies(self):
        respond = MagicMock()
        connection = MagicMock()
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "get_command_session", return_value=("thread", "session")),
            patch.object(slack_app, "record_session_participant"),
        ):
            slack_app.run_session_command(
                {"user_id": "U123", "team_id": "team", "channel_id": "channel"},
                respond,
                "reset",
            )

        service.reset.assert_called_once_with(connection, "session")
        self.assertEqual(respond.call_args.kwargs["text"], "Session history cleared.")

    def test_session_command_starts_new_session_and_tracks_participant(self):
        respond = MagicMock()
        connection = MagicMock()
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()
        record_participant = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "get_command_session", return_value=("thread", "old")),
            patch.object(slack_app, "create_new_session", return_value="new"),
            patch.object(slack_app, "record_session_participant", record_participant),
        ):
            slack_app.run_session_command(
                {"user_id": "U123", "team_id": "team", "channel_id": "channel"},
                respond,
                "new",
            )

        self.assertEqual(record_participant.call_count, 2)
        self.assertEqual(respond.call_args.kwargs["text"], "Started a new session.")

    def test_session_command_compacts_session(self):
        respond = MagicMock()
        connection = MagicMock()
        connect = MagicMock()
        connect.return_value.__enter__.return_value = connection
        service = MagicMock()

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app, "session_service", service),
            patch.object(slack_app, "get_command_session", return_value=("thread", "session")),
            patch.object(slack_app, "record_session_participant"),
        ):
            slack_app.run_session_command(
                {"user_id": "U123", "team_id": "team", "channel_id": "channel"},
                respond,
                "compact",
            )

        service.compact.assert_called_once_with(connection, "session")
        self.assertIn("compacted", respond.call_args.kwargs["text"])

    def test_session_command_reports_operation_failure(self):
        respond = MagicMock()
        connect = MagicMock(side_effect=RuntimeError("database down"))

        with (
            patch.object(slack_app, "allowed_user_ids", {"U123"}),
            patch.object(slack_app, "connect_to_database", connect),
            patch.object(slack_app.logger, "exception"),
        ):
            slack_app.run_session_command(
                {"user_id": "U123", "team_id": "team", "channel_id": "channel"},
                respond,
                "reset",
            )

        self.assertIn("Couldn't reset", respond.call_args.kwargs["text"])

    def test_command_wrappers_acknowledge_before_running_operation(self):
        for handler, operation in (
            (slack_app.handle_agent_reset, "reset"),
            (slack_app.handle_agent_new, "new"),
            (slack_app.handle_agent_compact, "compact"),
        ):
            with self.subTest(operation=operation):
                ack = MagicMock()
                body = {"user_id": "U123"}
                respond = MagicMock()
                with patch.object(slack_app, "run_session_command") as run_command:
                    handler(ack, body, respond)

                ack.assert_called_once_with()
                run_command.assert_called_once_with(body, respond, operation)

    def test_health_and_slack_event_routes(self):
        client = slack_app.flask_app.test_client()

        health = client.get("/healthz")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json, {"status": "ok"})

        with patch.object(slack_app.request_handler, "handle", return_value="handled") as handle:
            response = client.post("/slack/events", data="payload")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "handled")
        handle.assert_called_once()


def _cursor(value):
    cursor = MagicMock()
    cursor.fetchone.return_value = value
    return cursor


if __name__ == "__main__":
    unittest.main()

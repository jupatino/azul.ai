import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from azul_ai.channels.telegram import app as telegram_app
from azul_ai.channels.telegram.app import (
    build_application,
    configured_user_ids,
    normalize_telegram_message,
    process_delete_command,
    reply_in_parts,
    split_reply,
)
from azul_ai.core.agent_runtime import build_session_service


class TelegramConfigurationTests(unittest.TestCase):
    def test_configured_user_ids_are_trimmed_and_deduplicated(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "123, 456,123"}):
            self.assertEqual(configured_user_ids(), {"123", "456"})

    def test_configured_user_ids_reject_non_numeric_values(self):
        with patch.dict(os.environ, {"TELEGRAM_ALLOWED_USER_IDS": "123,not-an-id"}):
            with self.assertRaisesRegex(ValueError, "must contain numeric"):
                configured_user_ids()


class TelegramMessageTests(unittest.TestCase):
    def test_normalizes_private_message(self):
        update = SimpleNamespace(
            effective_message=SimpleNamespace(text="  hello  "),
            effective_user=SimpleNamespace(id=123),
            effective_chat=SimpleNamespace(id=456, type="private"),
            update_id=789,
        )

        result = normalize_telegram_message(update)

        self.assertEqual(
            (
                result.channel,
                result.sender_id,
                result.conversation_id,
                result.thread_id,
                result.event_id,
                result.text,
            ),
            ("telegram", "123", "456", "456", "789", "hello"),
        )

    def test_normalize_rejects_group_chat(self):
        update = SimpleNamespace(
            effective_message=SimpleNamespace(text="hello"),
            effective_user=SimpleNamespace(id=123),
            effective_chat=SimpleNamespace(id=456, type="group"),
            update_id=789,
        )

        with self.assertRaisesRegex(ValueError, "Only private"):
            normalize_telegram_message(update)


class TelegramReplyTests(unittest.TestCase):
    def test_split_reply_respects_limit_and_preserves_content(self):
        text = ("word " * 1200).strip()

        parts = split_reply(text, limit=100)

        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(part) <= 100 for part in parts))
        self.assertEqual(" ".join(parts), text)

    def test_split_reply_splits_unbroken_long_text(self):
        self.assertEqual(
            split_reply("x" * 25, limit=10),
            ["x" * 10, "x" * 10, "x" * 5],
        )

    def test_reply_in_parts_sends_each_chunk(self):
        message = SimpleNamespace(reply_text=AsyncMock())
        parts = ["first", "second"]
        with patch.object(telegram_app, "split_reply", return_value=parts) as split:
            asyncio.run(reply_in_parts(message, "a" * 12))

        split.assert_called_once_with("a" * 12)
        self.assertEqual(
            [call.args[0] for call in message.reply_text.await_args_list],
            parts,
        )


class TelegramDeleteCommandTests(unittest.TestCase):
    def setUp(self):
        self.delete_file = Mock(return_value="Deleted notes.txt.")
        self.session_service = SimpleNamespace(tools={"delete_file": self.delete_file})

    def test_authorized_user_deletes_requested_file(self):
        result = process_delete_command("123", "notes.txt", {"123"}, self.session_service)

        self.assertEqual(result, "Deleted notes.txt.")
        self.delete_file.assert_called_once_with("notes.txt")

    def test_unauthorized_user_cannot_delete_file(self):
        result = process_delete_command("456", "notes.txt", {"123"}, self.session_service)

        self.assertIn("not authorized", result)
        self.delete_file.assert_not_called()

    def test_missing_path_returns_usage_without_deleting(self):
        result = process_delete_command("123", "", {"123"}, self.session_service)

        self.assertIn("Usage:", result)
        self.delete_file.assert_not_called()

    def test_delete_command_is_registered_for_private_chats(self):
        application = build_application("123456:placeholder", {"123"}, build_session_service())
        handlers = [
            handler
            for group in application.handlers.values()
            for handler in group
        ]
        delete_handlers = [
            handler for handler in handlers
            if "delete" in getattr(handler, "commands", set())
        ]

        self.assertEqual(len(delete_handlers), 1)


if __name__ == "__main__":
    unittest.main()

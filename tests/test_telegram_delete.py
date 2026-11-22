import unittest
from unittest.mock import Mock

from azul_ai.channels.telegram.app import process_delete_command


class TelegramDeleteCommandTests(unittest.TestCase):
    def setUp(self):
        self.delete_file = Mock(return_value="Deleted notes.txt.")
        self.session_service = Mock(tools={"delete_file": self.delete_file})

    def test_authorized_user_deletes_requested_file(self):
        result = process_delete_command(
            "123",
            "notes.txt",
            {"123"},
            self.session_service,
        )

        self.assertEqual(result, "Deleted notes.txt.")
        self.delete_file.assert_called_once_with("notes.txt")

    def test_unauthorized_user_cannot_delete_file(self):
        result = process_delete_command(
            "456",
            "notes.txt",
            {"123"},
            self.session_service,
        )

        self.assertIn("not authorized", result)
        self.delete_file.assert_not_called()

    def test_missing_path_returns_usage_without_deleting(self):
        result = process_delete_command(
            "123",
            "",
            {"123"},
            self.session_service,
        )

        self.assertIn("Usage:", result)
        self.delete_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()

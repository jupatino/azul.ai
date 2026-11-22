import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from azul_ai.tools.skills import MAX_FILE_BYTES, SkillsTools


class SkillsToolsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.skills_dir = Path(self.temporary_directory.name) / "skills"
        self.tools = SkillsTools(self.skills_dir)

    def test_creates_skills_directory(self):
        self.assertTrue(self.skills_dir.is_dir())

    def test_lists_files_and_directories_in_sorted_order(self):
        (self.skills_dir / "z.txt").write_text("z", encoding="utf-8")
        (self.skills_dir / "folder").mkdir()
        (self.skills_dir / "a.txt").write_text("a", encoding="utf-8")

        self.assertEqual(self.tools.list_files(), "a.txt\nfolder (dir)\nz.txt")

    def test_lists_empty_directory(self):
        self.assertEqual(self.tools.list_files(), "(empty directory)")

    def test_list_skips_symbolic_links(self):
        target = self.skills_dir / "target.txt"
        target.write_text("data", encoding="utf-8")
        (self.skills_dir / "link.txt").symlink_to(target)

        self.assertEqual(self.tools.list_files(), "target.txt")

    def test_write_file_creates_parents_and_read_file_returns_content(self):
        result = self.tools.write_file("nested/note.txt", "hello")

        self.assertEqual(result, "Saved nested/note.txt (5 characters written).")
        self.assertEqual(self.tools.read_file("nested/note.txt"), "hello")

    def test_write_rejects_content_over_size_limit(self):
        with self.assertRaisesRegex(ValueError, "cannot be written"):
            self.tools.write_file("large.txt", "x" * (MAX_FILE_BYTES + 1))

        self.assertFalse((self.skills_dir / "large.txt").exists())

    def test_read_rejects_file_over_size_limit(self):
        target = self.skills_dir / "large.txt"
        target.write_text("x" * (MAX_FILE_BYTES + 1), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "cannot be read"):
            self.tools.read_file("large.txt")

    def test_file_tools_reject_paths_outside_skills_directory(self):
        outside = Path(self.temporary_directory.name) / "outside.txt"
        outside.write_text("keep", encoding="utf-8")

        for operation in (
            lambda: self.tools.list_files(".."),
            lambda: self.tools.read_file("../outside.txt"),
            lambda: self.tools.write_file("../outside.txt", "overwrite"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "only access paths inside"):
                    operation()

        self.assertEqual(outside.read_text(encoding="utf-8"), "keep")

    def test_run_command_allows_only_pwd_and_ls(self):
        with patch("azul_ai.tools.skills.subprocess.run") as run:
            run.return_value.stdout = "/skills"
            run.return_value.stderr = ""
            run.return_value.returncode = 0

            self.assertEqual(self.tools.run_command("pwd"), "/skills")
            run.assert_called_once_with(
                ["pwd"],
                cwd=self.tools.skills_dir,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        with self.assertRaisesRegex(ValueError, "Command is not allowed"):
            self.tools.run_command("rm -rf .")

    def test_run_command_truncates_large_output(self):
        with patch("azul_ai.tools.skills.subprocess.run") as run:
            run.return_value.stdout = "x" * 10_001
            run.return_value.stderr = ""
            run.return_value.returncode = 0

            output = self.tools.run_command("ls")

        self.assertEqual(len(output.split("\n... output truncated")[0]), 10_000)
        self.assertTrue(output.endswith("... output truncated"))


if __name__ == "__main__":
    unittest.main()

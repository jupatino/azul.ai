import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from azul_ai.tools.skills import MAX_FILE_BYTES, SkillsTools


class SkillsDirectoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.skills_dir = self.root / "skills"
        self.tools = SkillsTools(self.skills_dir)


class SkillsFileOperationsTests(SkillsDirectoryTestCase):
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
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")
        operations = (
            self.tools.list_files,
            self.tools.read_file,
            lambda path: self.tools.write_file(path, "overwrite"),
        )

        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, "only access paths inside"):
                    operation("../outside.txt")

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

        truncated_output, marker, _ = output.partition("\n... output truncated")
        self.assertTrue(marker)
        self.assertEqual(len(truncated_output), 10_000)


class SkillsFileDeletionTests(SkillsDirectoryTestCase):
    def test_deletes_regular_file_inside_skills_directory(self):
        target = self.skills_dir / "notes" / "draft.txt"
        target.parent.mkdir()
        target.write_text("temporary", encoding="utf-8")

        result = self.tools.delete_file("notes/draft.txt")

        self.assertEqual(result, "Deleted notes/draft.txt.")
        self.assertFalse(target.exists())

    def test_rejects_path_outside_skills_directory(self):
        outside = self.root / "outside.txt"
        outside.write_text("keep", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "only access paths inside"):
            self.tools.delete_file("../outside.txt")

        self.assertTrue(outside.exists())

    def test_rejects_directory(self):
        directory = self.skills_dir / "folder"
        directory.mkdir()

        with self.assertRaisesRegex(ValueError, "not a file"):
            self.tools.delete_file("folder")

        self.assertTrue(directory.is_dir())

    def test_rejects_symbolic_link_without_deleting_target(self):
        target = self.skills_dir / "keep.txt"
        target.write_text("keep", encoding="utf-8")
        link = self.skills_dir / "link.txt"
        link.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "Symbolic links"):
            self.tools.delete_file("link.txt")

        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())

    def test_rejects_symlinked_parent_that_escapes_skills_directory(self):
        outside = self.root / "outside"
        outside.mkdir()
        target = outside / "keep.txt"
        target.write_text("keep", encoding="utf-8")
        (self.skills_dir / "external").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "only access paths inside"):
            self.tools.delete_file("external/keep.txt")

        self.assertTrue(target.exists())

    def test_rejects_missing_file(self):
        with self.assertRaisesRegex(ValueError, "not a file"):
            self.tools.delete_file("missing.txt")


if __name__ == "__main__":
    unittest.main()

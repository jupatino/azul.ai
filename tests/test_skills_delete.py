import tempfile
import unittest
from pathlib import Path

from azul_ai.tools.skills import SkillsTools


class SkillsDeleteFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.skills_dir = Path(self.temporary_directory.name) / "skills"
        self.skills_dir.mkdir()
        self.tools = SkillsTools(self.skills_dir)

    def test_deletes_regular_file_inside_skills_directory(self):
        target = self.skills_dir / "notes" / "draft.txt"
        target.parent.mkdir()
        target.write_text("temporary", encoding="utf-8")

        result = self.tools.delete_file("notes/draft.txt")

        self.assertEqual(result, "Deleted notes/draft.txt.")
        self.assertFalse(target.exists())

    def test_rejects_path_outside_skills_directory(self):
        outside = Path(self.temporary_directory.name) / "outside.txt"
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
        outside = Path(self.temporary_directory.name) / "outside"
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

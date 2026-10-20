"""Tests for project search, labels, and shortcut-only behavior."""

import tempfile
import unittest
from pathlib import Path

from project_catalog import (
    add_project_shortcut,
    filter_projects,
    project_folder_available,
    remove_label,
    remove_project_shortcut,
    rename_label,
    set_project_labels,
)


class ProjectCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.web_path = self.root / "web app"
        self.api_path = self.root / "api"
        self.web_path.mkdir()
        self.api_path.mkdir()
        self.projects = [
            {"name": "Website", "path": str(self.web_path), "category": "Frontend", "tags": ["react", "client"]},
            {"name": "API", "path": str(self.api_path), "category": "Backend", "tags": ["python"]},
        ]

    def test_search_matches_name_path_category_and_tags_with_filters(self):
        self.assertEqual(filter_projects(self.projects, "web"), [self.projects[0]])
        self.assertEqual(filter_projects(self.projects, "PYTHON"), [self.projects[1]])
        self.assertEqual(filter_projects(self.projects, category="Frontend", tag="react"), [self.projects[0]])
        self.assertEqual(filter_projects(self.projects, category="Frontend", tag="python"), [])

    def test_add_and_remove_shortcut_never_removes_folder(self):
        added = add_project_shortcut(self.projects, " Tools ", str(self.root))
        self.assertEqual(added["name"], "Tools")
        self.assertEqual(added["category"], "")
        with self.assertRaisesRegex(ValueError, "already"):
            add_project_shortcut(self.projects + [added], "Duplicate", str(self.web_path))
        remaining = remove_project_shortcut(self.projects + [added], str(self.web_path))
        self.assertNotIn(self.projects[0], remaining)
        self.assertTrue(self.web_path.is_dir())

    def test_metadata_updates_and_category_tag_rename_remove(self):
        project = self.projects[0]
        set_project_labels(project, "Frontend", ["react", "client", "  demo ", "REACT", ""])
        self.assertEqual(project["category"], "Frontend")
        self.assertEqual(project["tags"], ["react", "client", "demo"])
        categories = rename_label(self.projects, ["Frontend", "Backend"], "Frontend", "Web", "category")
        self.assertEqual(categories, ["Web", "Backend"])
        self.assertEqual(project["category"], "Web")
        tags = rename_label(self.projects, ["react", "client", "python"], "client", "browser", "tags")
        self.assertEqual(tags, ["react", "browser", "python"])
        self.assertIn("browser", project["tags"])
        self.assertEqual(remove_label(self.projects, tags, "browser", "tags"), ["react", "python"])
        self.assertNotIn("browser", project["tags"])

    def test_missing_project_folder_is_reported_without_throwing(self):
        missing = {"name": "Moved", "path": str(self.root / "gone")}
        self.assertFalse(project_folder_available(missing))
        self.assertTrue(project_folder_available(self.projects[0]))

    def test_malformed_saved_paths_do_not_break_add_or_remove(self):
        malformed = [{"name": "Bad", "path": "bad\0path"}]
        added = add_project_shortcut(malformed, "New", str(self.root))
        self.assertEqual(added["name"], "New")
        self.assertEqual(remove_project_shortcut(malformed, "bad\0path"), malformed)


if __name__ == "__main__":
    unittest.main()

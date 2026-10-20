"""UI coordination tests for creation/publishing choices and project saving."""

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from tkinter import ttk
from unittest.mock import Mock, patch

import app
from project_creation import ProjectCreationResult


class ProjectCreationGuiTests(unittest.TestCase):
    def test_cancel_in_creation_dialog_does_not_call_creation_service(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Tk display is unavailable: {exc}")
        root.withdraw()
        try:
            with patch("app.load_preferences", return_value=({
                "theme": "light", "window_geometry": "1120x760", "categories": [], "tags": []
            }, [])), patch("app.load_projects", return_value=[]), patch("app.create_project") as create:
                launchpad = app.DeveloperLaunchpad(root)
                launchpad.open_create_project_dialog()
                root.update()
                dialogs = [widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel)]
                self.assertEqual(len(dialogs), 1)

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                cancel = next(widget for widget in descendants(dialogs[0])
                              if isinstance(widget, ttk.Button) and widget.cget("text") == "Cancel")
                cancel.invoke()
                root.update()
                create.assert_not_called()
                self.assertEqual(launchpad.projects, [])
        finally:
            root.destroy()

    def test_no_or_decide_later_never_starts_github_work(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        instance._check_github_auth = Mock()
        instance._offer_open_created_project = Mock()
        result = ProjectCreationResult("sample", Path("sample"), (), True, None)
        for answer in (False, None):
            with self.subTest(answer=answer), patch.object(app.messagebox, "askyesnocancel", return_value=answer):
                instance._ask_about_publishing(result)
        instance._check_github_auth.assert_not_called()
        self.assertEqual(instance._offer_open_created_project.call_count, 2)

    def test_yes_starts_auth_check_before_any_publish_dialog(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        instance._check_github_auth = Mock()
        instance._offer_open_created_project = Mock()
        result = ProjectCreationResult("sample", Path("sample"), (), True, None)
        with patch.object(app.messagebox, "askyesnocancel", return_value=True):
            instance._ask_about_publishing(result)
        instance._check_github_auth.assert_called_once_with(result)
        instance._offer_open_created_project.assert_not_called()

    def test_register_created_project_persists_selects_and_avoids_duplicates(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        instance.projects = []
        instance._persist_projects = Mock(return_value=True)
        instance.refresh_projects = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Created Project"
            folder.mkdir()
            self.assertTrue(instance._register_created_project("Created Project", folder))
            instance._persist_projects.assert_called_once()
            instance.refresh_projects.assert_called_once_with(select_path=str(folder.resolve()))
            self.assertEqual(len(instance.projects), 1)
            self.assertTrue(instance._register_created_project("Duplicate", folder))
            self.assertEqual(len(instance.projects), 1)
            self.assertEqual(instance.refresh_projects.call_count, 2)

    def test_register_rolls_back_memory_if_persistence_fails(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        instance.projects = []
        instance._persist_projects = Mock(return_value=False)
        instance.refresh_projects = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "Created"
            folder.mkdir()
            self.assertFalse(instance._register_created_project("Created", folder))
        self.assertEqual(instance.projects, [])
        instance.refresh_projects.assert_not_called()


if __name__ == "__main__":
    unittest.main()

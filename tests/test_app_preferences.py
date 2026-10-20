"""Focused tests for UI callbacks that do not require interactive clicking."""

import unittest
from unittest.mock import Mock, patch

import app
import main
from app import DeveloperLaunchpad


class ApplicationCallbackTests(unittest.TestCase):
    def setUp(self):
        self.launchpad = DeveloperLaunchpad.__new__(DeveloperLaunchpad)
        self.launchpad.root = Mock()
        self.launchpad.command_status = Mock()
        self.launchpad._save_window_preferences = Mock()
        self.launchpad._command_running = False

    def test_close_saves_window_preferences_and_destroys_root(self):
        self.launchpad.on_close()
        self.launchpad._save_window_preferences.assert_called_once()
        self.launchpad.root.destroy.assert_called_once()

    def test_close_prompts_before_stopping_a_running_command(self):
        self.launchpad._command_running = True
        self.launchpad.stop_running_command = Mock()
        with patch.object(app.messagebox, "askyesno", return_value=False) as confirm:
            self.launchpad.on_close()
        confirm.assert_called_once()
        self.launchpad._save_window_preferences.assert_not_called()
        self.launchpad.root.destroy.assert_not_called()

        with patch.object(app.messagebox, "askyesno", return_value=True):
            self.launchpad.on_close()
        self.launchpad._save_window_preferences.assert_called_once()
        self.launchpad.stop_running_command.assert_called_once()
        self.assertTrue(self.launchpad._closing)

    def test_navigation_shortcut_selects_the_requested_workspace(self):
        self.launchpad.workspace_tabs = Mock()
        result = self.launchpad._navigate_shortcut(2)
        self.launchpad.workspace_tabs.select.assert_called_once_with(2)
        self.assertEqual(result, "break")

    def test_main_entrypoint_creates_window_and_runs_event_loop(self):
        root = Mock()
        with patch.object(main.tk, "Tk", return_value=root), patch.object(main, "DeveloperLaunchpad") as window, patch.object(main, "configure_logging"):
            main.main()
        window.assert_called_once_with(root)
        root.mainloop.assert_called_once()


if __name__ == "__main__":
    unittest.main()

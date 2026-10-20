"""Tests for preference migration, fallback, and local diagnostic logging."""

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
from diagnostics import LOGGER, configure_logging, install_tk_exception_handler, log_error


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "user data"
        self.preferences_path = self.folder / "preferences.json"
        self.patches = [
            patch.object(storage, "APP_DIR", self.folder),
            patch.object(storage, "PREFERENCES_FILE", self.preferences_path),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def test_defaults_older_preferences_and_unknown_keys_are_preserved(self):
        prefs, warnings = storage.load_preferences()
        self.assertEqual(warnings, [])
        self.assertEqual(prefs["theme"], "light")
        prefs["categories"].append("local-only")
        fresh_defaults, _ = storage.load_preferences()
        self.assertEqual(fresh_defaults["categories"], [])
        self.preferences_path.write_text(json.dumps({"theme": "dark", "custom": 12}), encoding="utf-8")
        prefs, warnings = storage.load_preferences()
        self.assertEqual(warnings, [])
        self.assertEqual(prefs["theme"], "dark")
        self.assertEqual(prefs["categories"], [])
        storage.save_preferences(prefs)
        self.assertEqual(json.loads(self.preferences_path.read_text(encoding="utf-8"))["custom"], 12)

    def test_invalid_preferences_use_defaults_and_keep_a_backup_on_save(self):
        self.preferences_path.parent.mkdir(parents=True)
        self.preferences_path.write_text("{broken", encoding="utf-8")
        prefs, warnings = storage.load_preferences()
        self.assertTrue(warnings)
        self.assertEqual(prefs["theme"], "light")
        prefs["theme"] = "dark"
        storage.save_preferences(prefs)
        self.assertEqual(storage.load_preferences()[0]["theme"], "dark")
        backups = list(self.folder.glob("preferences.invalid-*.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")

    def test_invalid_theme_geometry_and_label_shapes_fall_back(self):
        self.folder.mkdir(parents=True)
        self.preferences_path.write_text(json.dumps({"theme": "neon", "window_geometry": "garbage", "tags": "bad"}), encoding="utf-8")
        prefs, warnings = storage.load_preferences()
        self.assertEqual(prefs["theme"], "light")
        self.assertEqual(prefs["window_geometry"], "1120x760")
        self.assertEqual(prefs["tags"], [])
        self.assertEqual(len(warnings), 3)

    def test_log_file_is_local_and_does_not_write_command_output(self):
        log_path = self.folder / "developer_launchpad.log"
        old_handlers = list(LOGGER.handlers)
        for handler in old_handlers:
            LOGGER.removeHandler(handler)
            handler.close()

        def close_test_handlers():
            for handler in list(LOGGER.handlers):
                LOGGER.removeHandler(handler)
                handler.close()

        self.addCleanup(close_test_handlers)
        configure_logging(log_path)
        log_error("Test operation", RuntimeError("test failure"))
        for handler in LOGGER.handlers:
            handler.flush()
        contents = log_path.read_text(encoding="utf-8")
        self.assertIn("Test operation", contents)
        self.assertNotIn("command output", contents)

    def test_unexpected_tk_callback_error_has_one_user_message(self):
        from types import SimpleNamespace

        root = SimpleNamespace()
        install_tk_exception_handler(root)
        with patch("diagnostics.LOGGER.error"), patch("diagnostics.messagebox.showerror") as show_error:
            root.report_callback_exception(ValueError, ValueError("sample failure"), None)
        show_error.assert_called_once()
        self.assertIn("Settings", show_error.call_args.args[1])

    def test_project_metadata_and_malformed_records_survive_saves(self):
        projects_path = self.folder / "projects.json"
        projects = [
            {"name": "Tagged", "path": str(self.folder), "category": "Frontend", "tags": ["react"]},
            "malformed legacy row",
        ]
        with patch.object(storage, "PROJECTS_FILE", projects_path), patch.object(storage.messagebox, "showwarning"):
            storage.save_projects(projects)
            loaded = storage.load_projects()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["category"], "Frontend")
            self.assertEqual(loaded[0]["tags"], ["react"])
            loaded[0]["tags"].append("dashboard")
            storage.save_projects(loaded)
            raw = json.loads(projects_path.read_text(encoding="utf-8"))
        self.assertEqual(raw[0]["tags"], ["react", "dashboard"])
        self.assertEqual(raw[1], "malformed legacy row")


if __name__ == "__main__":
    unittest.main()

"""Tests for saved command profiles and the subprocess runner."""

import queue
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app
import storage
from command_profiles import CommandProfile, create_profile, resolve_working_directory
from command_runner import CommandEvent, CommandExecutionError, run_command


class CommandProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.settings_dir = Path(self.temp.name) / "settings"
        self.projects_file = self.settings_dir / "projects.json"
        self.patches = [
            patch.object(storage, "APP_DIR", self.settings_dir),
            patch.object(storage, "PROJECTS_FILE", self.projects_file),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)
        self.project_root = Path(self.temp.name) / "sample project"
        self.project_root.mkdir()
        self.project = {"name": "Sample", "path": str(self.project_root), "custom": "preserve"}

    def test_create_edit_delete_profiles_and_persist(self):
        first = create_profile("Tests", sys.executable, "-c\nprint('ok')", ".", description="Run checks")
        storage.save_command_profiles(self.project, [first])
        storage.save_projects([self.project])

        loaded = storage.load_projects()[0]
        profiles, warnings = storage.load_command_profiles(loaded)
        self.assertFalse(warnings)
        self.assertEqual(profiles, [first])

        edited = create_profile("Unit tests", sys.executable, "-m\nunittest", "tests", profile_id=first.profile_id)
        storage.save_command_profiles(loaded, [edited])
        storage.save_projects([loaded])
        reloaded = storage.load_projects()[0]
        profiles, _ = storage.load_command_profiles(reloaded)
        self.assertEqual(profiles[0].name, "Unit tests")
        self.assertEqual(profiles[0].profile_id, first.profile_id)

        storage.save_command_profiles(reloaded, [])
        storage.save_projects([reloaded])
        self.assertEqual(storage.load_command_profiles(storage.load_projects()[0])[0], [])

    def test_old_project_configuration_and_unrelated_fields_are_preserved(self):
        old_project = {"name": "Old", "path": str(self.project_root), "legacy": 17}
        storage.save_projects([old_project])
        loaded = storage.load_projects()[0]
        profiles, warnings = storage.load_command_profiles(loaded)
        self.assertEqual(profiles, [])
        self.assertEqual(warnings, [])
        profile = create_profile("Run", sys.executable)
        storage.save_command_profiles(loaded, [profile])
        storage.save_projects([loaded])
        result = storage.load_projects()[0]
        self.assertEqual(result["legacy"], 17)
        self.assertEqual(result["path"], str(self.project_root))
        self.assertEqual(storage.load_command_profiles(result)[0], [profile])

    def test_malformed_profiles_are_reported_and_preserved(self):
        malformed = {"name": "broken", "arguments": "not a list"}
        self.project["commands"] = [malformed]
        profiles, warnings = storage.load_command_profiles(self.project)
        self.assertFalse(profiles)
        self.assertIn("skipped", warnings[0])
        valid = create_profile("Safe", sys.executable)
        storage.save_command_profiles(self.project, [valid])
        self.assertEqual(self.project["commands"][0], valid.to_dict())
        self.assertEqual(self.project["commands"][1], malformed)

        self.project["commands"] = {"unexpected": True}
        self.assertTrue(storage.load_command_profiles(self.project)[1])
        storage.save_command_profiles(self.project, [valid])
        self.assertEqual(self.project["commands_invalid_backup"], {"unexpected": True})

    def test_working_directory_must_exist_and_stay_inside_project(self):
        (self.project_root / "scripts").mkdir()
        self.assertEqual(resolve_working_directory(self.project_root, "scripts"), self.project_root / "scripts")
        with self.assertRaisesRegex(ValueError, "relative"):
            resolve_working_directory(self.project_root, str(self.project_root))
        with self.assertRaisesRegex(ValueError, "stay inside"):
            resolve_working_directory(self.project_root, "..")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            resolve_working_directory(self.project_root, "missing")

    def test_profile_validation_rejects_malformed_values(self):
        with self.assertRaisesRegex(ValueError, "arguments"):
            CommandProfile.from_dict({"profile_id": "x", "name": "x", "executable": "python", "arguments": "-V"})
        with self.assertRaisesRegex(ValueError, "NUL"):
            create_profile("bad\0name", "python")


class CommandRunnerTests(unittest.TestCase):
    def run_profile(self, profile, stop_event=None, timeout=8):
        events = queue.Queue()
        stop_event = stop_event or threading.Event()
        results = []
        errors = []

        def worker():
            try:
                results.append(run_command(profile, Path.cwd(), events, stop_event))
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout)
        self.assertFalse(thread.is_alive(), "command worker did not finish")
        captured = []
        while not events.empty():
            captured.append(events.get_nowait())
        return results, errors, captured

    def test_short_command_streams_stdout_and_stderr(self):
        profile = create_profile("print", sys.executable, "-u\n-c\nimport sys; print('hello'); print('problem', file=sys.stderr)")
        results, errors, events = self.run_profile(profile)
        self.assertFalse(errors)
        self.assertEqual(results[0].returncode, 0)
        self.assertTrue(any(event.stream == "stdout" and "hello" in event.text for event in events))
        self.assertTrue(any(event.stream == "stderr" and "problem" in event.text for event in events))
        self.assertTrue(any(event.kind == "finished" and event.returncode == 0 for event in events))

    def test_nonzero_exit_code_is_reported(self):
        profile = create_profile("fail", sys.executable, "-c\nraise SystemExit(7)")
        results, errors, events = self.run_profile(profile)
        self.assertFalse(errors)
        self.assertEqual(results[0].returncode, 7)
        self.assertEqual(next(event for event in events if event.kind == "finished").returncode, 7)

    def test_invalid_output_encoding_is_replaced_instead_of_crashing(self):
        profile = create_profile("bytes", sys.executable, "-c\nimport sys; sys.stdout.buffer.write(b'\\xff')")
        results, errors, events = self.run_profile(profile)
        self.assertFalse(errors)
        self.assertEqual(results[0].returncode, 0)
        output = "".join(event.text for event in events if event.stream == "stdout")
        self.assertIn("�", output)

    def test_missing_executable_and_invalid_working_directory_fail_cleanly(self):
        profile = create_profile("missing", "launchpad-command-that-does-not-exist-9000")
        with self.assertRaisesRegex(CommandExecutionError, "PATH"):
            run_command(profile, Path.cwd(), queue.Queue(), threading.Event())
        invalid = Path.cwd() / "this-directory-should-not-exist-launchpad"
        profile = create_profile("bad cwd", sys.executable)
        with self.assertRaisesRegex(CommandExecutionError, "Working directory"):
            run_command(profile, invalid, queue.Queue(), threading.Event())

    def test_stop_terminates_a_running_command(self):
        profile = create_profile("long", sys.executable, "-u\n-c\nimport time; print('ready', flush=True); time.sleep(60)", long_running=True)
        events = queue.Queue()
        stop_event = threading.Event()
        results = []
        worker = threading.Thread(target=lambda: results.append(run_command(profile, Path.cwd(), events, stop_event)))
        worker.start()
        deadline = time.monotonic() + 5
        ready = False
        while time.monotonic() < deadline and not ready:
            try:
                event = events.get(timeout=0.1)
                ready = event.kind == "output" and "ready" in event.text
            except queue.Empty:
                continue
        self.assertTrue(ready, "command did not become ready")
        stop_event.set()
        worker.join(8)
        self.assertFalse(worker.is_alive(), "stopped process worker did not finish")
        self.assertTrue(results[0].stopped)
        self.assertTrue(any(event.kind == "finished" and event.stopped for event in list(events.queue)))

    def test_start_error_event_can_be_sent_by_gui_worker(self):
        profile = create_profile("missing", "launchpad-command-does-not-exist-9010")
        events = queue.Queue()
        with self.assertRaises(CommandExecutionError) as raised:
            run_command(profile, Path.cwd(), events, threading.Event())
        self.assertIn("PATH", str(raised.exception))
        self.assertEqual(events.get_nowait().kind, "status")


class CommandGuiCoordinationTests(unittest.TestCase):
    class FakeList:
        def __init__(self):
            self.values = []
            self.selection = []

        def delete(self, *_args):
            self.values.clear()

        def insert(self, _index, value):
            self.values.append(value)

        def selection_set(self, index):
            self.selection = [index]

        def curselection(self):
            return tuple(self.selection)

    class FakeLabel:
        def config(self, **kwargs):
            self.value = kwargs.get("text", "")

    def test_command_output_widgets_are_updated_by_queue_consumer_thread(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        instance._command_events = queue.Queue()
        instance._closing = False
        instance._command_running = False
        instance.command_status = self.FakeLabel()
        update_threads = []
        instance._append_command_output = lambda *_args, **_kwargs: update_threads.append(threading.get_ident())
        instance._finish_command = Mock()
        main_thread = threading.get_ident()

        producer = threading.Thread(target=lambda: instance._command_events.put(CommandEvent("output", text="queued\n")))
        producer.start()
        producer.join()
        instance._poll_command_events()
        self.assertEqual(update_threads, [main_thread])

    def test_selecting_a_project_does_not_run_its_saved_command(self):
        instance = app.DeveloperLaunchpad.__new__(app.DeveloperLaunchpad)
        project = {"name": "Test", "path": str(Path.cwd()), "commands": [create_profile("Safe", sys.executable).to_dict()]}
        instance.projects = [project]
        instance._command_running = False
        instance.project_list = self.FakeList()
        instance.project_list.selection = [0]
        instance.project_title = self.FakeLabel()
        instance.project_path_label = self.FakeLabel()
        instance.command_status = self.FakeLabel()
        instance.command_list = self.FakeList()
        instance.command_details_label = self.FakeLabel()
        instance.write_output = Mock()
        instance.refresh_git = Mock()
        with patch.object(app, "run_command") as runner:
            instance.on_select()
        runner.assert_not_called()
        self.assertEqual(instance.command_list.values, ["Safe  [task]"])


if __name__ == "__main__":
    unittest.main()


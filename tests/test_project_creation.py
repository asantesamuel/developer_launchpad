"""Temporary-directory tests for safe new-project creation and initial commits."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import storage
from integrations import run_git
from project_catalog import add_project_shortcut
from project_creation import (
    ProjectCreationError,
    create_initial_commit,
    create_project,
    preview_project_path,
    validate_project_name,
)


class ProjectNameValidationTests(unittest.TestCase):
    def test_valid_names_and_windows_restrictions(self):
        for name in ("Website", "my-project_2", "café app", "project.v2"):
            self.assertEqual(validate_project_name(name), name)
        for name in ("", "   ", ".", "...", " leading", "trailing ", "trailing.", "a/b", "a:b", "a\\b", "a?b", "CON", "NUL.txt", "COM1", "LPT9.log", "bad\x01name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_project_name(name)

    def test_parent_must_exist_and_collision_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "Parent directory"):
                preview_project_path(root / "missing", "sample")
            destination = root / "existing"
            destination.mkdir()
            marker = destination / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                create_project("existing", root)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_racing_destination_creation_is_not_claimed_as_created_by_launchpad(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temporary:
            parent = Path(temporary)
            real_mkdir = Path.mkdir
            def collision(path, *args, **kwargs):
                real_mkdir(path, *args, **kwargs)
                raise FileExistsError("created by another process")
            with patch("project_creation.Path.mkdir", autospec=True, side_effect=collision):
                with self.assertRaises(ProjectCreationError) as raised:
                    create_project("race", parent, initial_commit=False)
            self.assertFalse(raised.exception.folder_created)


class ProjectCreationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.safe_git = patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        })
        self.safe_git.start()
        self.addCleanup(self.safe_git.stop)

    def git_with_test_identity(self, folder, args, timeout=20):
        output = run_git(folder, args, timeout=timeout)
        if args == ["init"]:
            run_git(folder, ["config", "user.name", "Launchpad Test"])
            run_git(folder, ["config", "user.email", "launchpad@example.invalid"])
        return output

    def test_create_starter_files_local_git_and_initial_commit(self):
        progress = []
        result = create_project(
            "new app", self.root, progress=progress.append, git_runner=self.git_with_test_identity
        )
        self.assertTrue(result.git_initialized)
        self.assertTrue(result.initial_commit_hash)
        self.assertEqual(result.generated_files, ("README.md", ".gitignore"))
        self.assertIn("# new app", (result.path / "README.md").read_text(encoding="utf-8"))
        self.assertIn(".env", (result.path / ".gitignore").read_text(encoding="utf-8"))
        self.assertIn("Local Git repository initialized and verified.", progress)
        committed = run_git(result.path, ["show", "--format=", "--name-only", "HEAD"]).splitlines()
        self.assertEqual(committed, [".gitignore", "README.md"])

    def test_create_empty_local_repository_without_commit(self):
        result = create_project(
            "empty", self.root, create_readme=False, create_gitignore=False,
            initial_commit=False, git_runner=self.git_with_test_identity,
        )
        self.assertEqual(result.generated_files, ())
        self.assertIsNone(result.initial_commit_hash)
        self.assertEqual(run_git(result.path, ["rev-parse", "--is-inside-work-tree"]), "true")
        with self.assertRaises(RuntimeError):
            run_git(result.path, ["rev-parse", "--verify", "HEAD"])

    def test_readme_only_and_gitignore_only_are_supported(self):
        readme = create_project("readme-only", self.root, create_gitignore=False, initial_commit=False,
                                git_runner=self.git_with_test_identity)
        ignored = create_project("ignore-only", self.root, create_readme=False, initial_commit=False,
                                 git_runner=self.git_with_test_identity)
        self.assertEqual(readme.generated_files, ("README.md",))
        self.assertEqual(ignored.generated_files, (".gitignore",))

    def test_missing_git_leaves_recoverable_folder_and_reports_exact_state(self):
        def missing_git(folder, args, timeout=20):
            raise RuntimeError("Git was not found")
        with self.assertRaises(ProjectCreationError) as raised:
            create_project("recoverable", self.root, git_runner=missing_git)
        error = raised.exception
        self.assertTrue(error.path.is_dir())
        self.assertTrue(error.folder_created)
        self.assertTrue((error.path / "README.md").is_file())
        self.assertFalse(error.git_initialized)
        self.assertIn("Nothing was automatically deleted", str(error))

    def test_git_init_failure_does_not_remove_created_content(self):
        def fail_init(folder, args, timeout=20):
            if args == ["init"]:
                raise RuntimeError("simulated init error")
            return run_git(folder, args, timeout=timeout)
        with self.assertRaises(ProjectCreationError) as raised:
            create_project("init-failure", self.root, git_runner=fail_init)
        self.assertIn("simulated init error", str(raised.exception))
        self.assertTrue(raised.exception.folder_created)
        self.assertTrue((raised.exception.path / "README.md").exists())
        self.assertIsNone(raised.exception.git_initialized)
        self.assertIn("unknown; Git init failed before verification", str(raised.exception))

    def test_commit_failure_mentions_git_identity_and_preserves_repo(self):
        def fail_commit(folder, args, timeout=20):
            if args and args[0] == "commit":
                raise RuntimeError("Author identity unknown; set user.name and user.email")
            if args == ["init"]:
                output = run_git(folder, args, timeout=timeout)
                return output
            return run_git(folder, args, timeout=timeout)
        with self.assertRaises(ProjectCreationError) as raised:
            create_project("identity-failure", self.root, git_runner=fail_commit)
        self.assertTrue(raised.exception.git_initialized)
        self.assertIn("git config --global user.name", str(raised.exception))
        self.assertTrue((raised.exception.path / ".git").exists())

    def test_initial_commit_commits_only_generated_paths(self):
        project = self.root / "explicit-files"
        project.mkdir()
        run_git(project, ["init"])
        run_git(project, ["config", "user.name", "Launchpad Test"])
        run_git(project, ["config", "user.email", "launchpad@example.invalid"])
        (project / "README.md").write_text("starter\n", encoding="utf-8")
        (project / "private-not-authorized.txt").write_text("not part of initial commit\n", encoding="utf-8")
        run_git(project, ["add", "--", "private-not-authorized.txt"])
        commit_hash = create_initial_commit(project, ["README.md"])
        self.assertTrue(commit_hash)
        committed = run_git(project, ["show", "--format=", "--name-only", "HEAD"]).splitlines()
        self.assertEqual(committed, ["README.md"])
        self.assertEqual(run_git(project, ["diff", "--cached", "--name-only"]), "private-not-authorized.txt")

    def test_created_folder_can_be_saved_without_duplicate_and_old_data_is_kept(self):
        result = create_project("saved", self.root, initial_commit=False, git_runner=self.git_with_test_identity)
        settings = self.root / "user data"
        projects_file = settings / "projects.json"
        old = {"name": "Old", "path": str(self.root / "old"), "legacy": 7}
        old_path = Path(old["path"])
        old_path.mkdir()
        with patch.object(storage, "APP_DIR", settings), patch.object(storage, "PROJECTS_FILE", projects_file):
            first = add_project_shortcut([old], result.name, str(result.path))
            storage.save_projects([old, first])
            with self.assertRaisesRegex(ValueError, "already"):
                add_project_shortcut(storage.load_projects(), result.name, str(result.path))
            saved = storage.load_projects()
        self.assertEqual(saved[0]["legacy"], 7)
        self.assertEqual(saved[1]["path"], str(result.path.resolve()))


if __name__ == "__main__":
    unittest.main()

"""Integration tests for Git workflows using disposable local repositories."""

import subprocess
import tempfile
import unittest
import os
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import integrations
from git_operations import GitOperations


class GitRepositoryTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        safe_directory = patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        })
        safe_directory.start()
        self.addCleanup(safe_directory.stop)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project with spaces"
        self.repo.mkdir()
        self.git(self.repo, "init", "-b", "main")
        self.git(self.repo, "config", "user.name", "Launchpad Test")
        self.git(self.repo, "config", "user.email", "launchpad@example.invalid")
        self.ops = GitOperations(self.repo)

    @staticmethod
    def git(folder, *args, check=True):
        result = subprocess.run(
            ["git", "-C", str(folder), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if check and result.returncode:
            raise AssertionError(result.stderr or result.stdout)
        return result

    def commit_files(self, *paths):
        self.git(self.repo, "add", "--", *paths)
        self.git(self.repo, "commit", "-m", "initial test commit")

    def test_clean_repository_reports_branch_and_clean_tree(self):
        (self.repo / "readme.txt").write_text("hello\n", encoding="utf-8")
        self.commit_files("readme.txt")

        status = self.ops.status()

        self.assertEqual(status.branch, "main")
        self.assertEqual(status.changes, ())
        self.assertEqual(status.summary, "Working tree clean.")

    def test_unborn_and_detached_heads_have_clear_branch_labels(self):
        self.assertEqual(self.ops.status().branch, "main")
        self.assertEqual(self.ops.branches()[1], "main")
        (self.repo / "first.txt").write_text("first\n", encoding="utf-8")
        self.commit_files("first.txt")
        head = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()
        self.git(self.repo, "checkout", "--detach", head)
        self.assertEqual(self.ops.status().branch, "(detached HEAD)")
        self.assertEqual(self.ops.branches()[1], "(detached HEAD)")

    def test_status_categorizes_staged_unstaged_untracked_deleted_and_renamed(self):
        (self.repo / "tracked.txt").write_text("original\n", encoding="utf-8")
        (self.repo / "delete-me.txt").write_text("delete\n", encoding="utf-8")
        (self.repo / "old-name.txt").write_text("rename\n", encoding="utf-8")
        self.commit_files("tracked.txt", "delete-me.txt", "old-name.txt")

        (self.repo / "tracked.txt").write_text("staged version\n", encoding="utf-8")
        self.git(self.repo, "add", "--", "tracked.txt")
        (self.repo / "tracked.txt").write_text("unstaged version\n", encoding="utf-8")
        (self.repo / "delete-me.txt").unlink()
        unusual_path = "odd name ' quote cafe.txt"
        (self.repo / unusual_path).write_text("untracked\n", encoding="utf-8")
        (self.repo / "old-name.txt").rename(self.repo / "new-name.txt")
        self.git(self.repo, "add", "--all", "--", "delete-me.txt", "old-name.txt", "new-name.txt")
        (self.repo / "tracked.txt").write_text("unstaged after the staging pass\n", encoding="utf-8")

        changes = {change.path: change for change in self.ops.status().changes}

        self.assertTrue(changes["tracked.txt"].staged)
        self.assertTrue(changes["tracked.txt"].unstaged)
        self.assertIn("delete-me.txt", changes)
        self.assertIn("deleted", changes["delete-me.txt"].display_status)
        self.assertTrue(changes[unusual_path].untracked)
        self.assertEqual(changes["new-name.txt"].original_path, "old-name.txt")
        self.assertIn("renamed", changes["new-name.txt"].display_status)

    def test_stage_and_unstage_only_selected_path_with_unusual_name(self):
        tracked = "tracked ' file.txt"
        (self.repo / tracked).write_text("original\n", encoding="utf-8")
        self.commit_files(tracked)
        (self.repo / tracked).write_text("modified\n", encoding="utf-8")
        self.ops.stage([tracked])
        self.assertTrue(next(change for change in self.ops.status().changes if change.path == tracked).staged)
        self.ops.unstage([tracked])
        self.assertTrue(next(change for change in self.ops.status().changes if change.path == tracked).unstaged)

        name = "file with spaces ' quotes cafe.txt"
        (self.repo / name).write_text("content\n", encoding="utf-8")
        (self.repo / "leave-untracked.txt").write_text("keep untracked\n", encoding="utf-8")

        self.ops.stage([name])
        status = {change.path: change for change in self.ops.status().changes}
        self.assertTrue(status[name].staged)
        self.assertTrue(status["leave-untracked.txt"].untracked)

        self.ops.unstage([name])
        status = {change.path: change for change in self.ops.status().changes}
        self.assertTrue(status[name].untracked)
        self.assertTrue(status["leave-untracked.txt"].untracked)

    def test_diff_for_staged_unstaged_and_untracked_files(self):
        (self.repo / "tracked.txt").write_text("before\n", encoding="utf-8")
        self.commit_files("tracked.txt")
        (self.repo / "tracked.txt").write_text("unstaged after\n", encoding="utf-8")
        change = next(change for change in self.ops.status().changes if change.path == "tracked.txt")
        self.assertIn("unstaged after", self.ops.diff(change))

        self.ops.stage(["tracked.txt"])
        staged_change = next(change for change in self.ops.status().changes if change.path == "tracked.txt")
        self.assertIn("unstaged after", self.ops.diff(staged_change, staged=True))

        unusual = "not tracked ' cafe.txt"
        (self.repo / unusual).write_text("new text\n", encoding="utf-8")
        untracked = next(change for change in self.ops.status().changes if change.path == unusual)
        self.assertIn(unusual, self.ops.diff(untracked))
        self.assertIn("new text", self.ops.diff(untracked))

    def test_binary_untracked_diff_has_clear_message(self):
        name = "image.bin"
        (self.repo / name).write_bytes(b"\x00\x01\x02")
        change = next(change for change in self.ops.status().changes if change.path == name)
        self.assertIn("binary", self.ops.diff(change).lower())

    def test_unicode_path_is_preserved_by_status_and_stage_arguments(self):
        unicode_path = "caf\u00e9 ' file.txt"
        calls = []

        def fake_runner(folder, args, timeout=20):
            calls.append(args)
            if args[0] == "status":
                return f"## main\0 M {unicode_path}\0"
            return ""

        operations = GitOperations(self.repo, runner=fake_runner)
        self.assertEqual(operations.status().changes[0].path, unicode_path)
        operations.stage([unicode_path])
        self.assertEqual(calls[1], ["add", "--", unicode_path])

    def test_commit_includes_only_staged_files(self):
        for name in ("staged.txt", "unstaged.txt"):
            (self.repo / name).write_text("base\n", encoding="utf-8")
        self.commit_files("staged.txt", "unstaged.txt")

        (self.repo / "staged.txt").write_text("commit this\n", encoding="utf-8")
        (self.repo / "unstaged.txt").write_text("leave this unstaged\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("leave untracked\n", encoding="utf-8")
        self.ops.stage(["staged.txt"])

        commit_hash = self.ops.commit("only staged file")

        self.assertRegex(commit_hash, r"^[0-9a-f]+$")
        committed = self.git(self.repo, "show", "--format=", "--name-only", "HEAD").stdout.splitlines()
        self.assertEqual(committed, ["staged.txt"])
        remaining = {change.path: change for change in self.ops.status().changes}
        self.assertTrue(remaining["unstaged.txt"].unstaged)
        self.assertTrue(remaining["untracked.txt"].untracked)

    def test_commit_requires_message_and_staged_changes(self):
        with self.assertRaisesRegex(RuntimeError, "non-empty"):
            self.ops.commit("  ")
        with self.assertRaisesRegex(RuntimeError, "no staged changes"):
            self.ops.commit("nothing staged")

    def test_branch_listing_creation_and_switching(self):
        (self.repo / "file.txt").write_text("base\n", encoding="utf-8")
        self.commit_files("file.txt")

        self.assertEqual(self.ops.branches(), (["main"], "main"))
        self.ops.create_branch("feature/v2-workflow")
        branches, current = self.ops.branches()
        self.assertIn("feature/v2-workflow", branches)
        self.assertEqual(current, "feature/v2-workflow")
        self.ops.switch_branch("main")
        self.assertEqual(self.ops.branches()[1], "main")

    def test_invalid_branch_name_and_conflicting_switch_fail_safely(self):
        (self.repo / "file.txt").write_text("base\n", encoding="utf-8")
        self.commit_files("file.txt")
        self.ops.create_branch("other")
        self.ops.switch_branch("main")
        self.git(self.repo, "switch", "other")
        (self.repo / "file.txt").write_text("other branch content\n", encoding="utf-8")
        self.git(self.repo, "add", "--", "file.txt")
        self.git(self.repo, "commit", "-m", "other version")
        self.git(self.repo, "switch", "main")
        (self.repo / "file.txt").write_text("local uncommitted content\n", encoding="utf-8")

        with self.assertRaises(RuntimeError):
            self.ops.switch_branch("other")
        self.assertEqual((self.repo / "file.txt").read_text(encoding="utf-8"), "local uncommitted content\n")
        with self.assertRaises(RuntimeError):
            self.ops.create_branch("not a valid branch name")

    def test_fetch_uses_remote_and_reports_tracking_counts_without_integrating(self):
        commands = []

        def fake_runner(folder, args, timeout=20):
            commands.append((args, timeout))
            if args == ["remote"]:
                return "origin"
            if args == ["fetch", "origin"]:
                return ""
            if args == ["status", "--porcelain=v1", "-z", "--branch", "--untracked-files=all"]:
                return "## main...origin/main [behind 2]\0"
            raise AssertionError(f"Unexpected Git command: {args}")

        message = GitOperations(self.repo, runner=fake_runner).fetch()

        self.assertIn("without merging", message)
        self.assertIn("0 ahead and 2 behind", message)
        self.assertEqual(commands[1], ((["fetch", "origin"], 90)))
        self.assertFalse(any(args[0] in ("pull", "merge", "rebase", "push") for args, _ in commands))

    def test_missing_remote_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, "No Git remotes"):
            self.ops.fetch()

    def test_fetch_authentication_or_network_failure_is_reported(self):
        def failing_runner(folder, args, timeout=20):
            if args == ["remote"]:
                return "origin"
            if args == ["fetch", "origin"]:
                raise RuntimeError("fatal: authentication failed")
            raise AssertionError(f"Unexpected Git command: {args}")

        with self.assertRaisesRegex(RuntimeError, "authentication failed"):
            GitOperations(self.repo, runner=failing_runner).fetch()

    def test_missing_upstream_is_not_reported_as_zero_ahead_and_behind(self):
        parsed = GitOperations._parse_branch_header("## main...origin/main [gone]")
        self.assertEqual(parsed, ("main", "origin/main (gone)", None, None))

    def test_non_repository_and_missing_git_are_reported(self):
        other = self.root / "not a repository"
        other.mkdir()
        with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root)}):
            with self.assertRaises(RuntimeError):
                GitOperations(other).status()

        with patch("integrations.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "Git was not found"):
                self.ops.status()

    def test_failed_command_and_timeout_are_propagated(self):
        with self.assertRaises(RuntimeError):
            self.ops.switch_branch("branch-that-does-not-exist")

        with patch("integrations.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 0.01)):
            with self.assertRaises(subprocess.TimeoutExpired):
                integrations.run_git(self.repo, ["status"], timeout=0.01)

    def test_git_error_credentials_are_redacted(self):
        result = SimpleNamespace(
            returncode=128,
            stderr="fatal: unable to access https://user:secret-token@example.invalid/repo: denied",
            stdout="",
        )
        with patch("integrations.shutil.which", return_value="git.exe"), patch(
            "integrations.subprocess.run", return_value=result
        ):
            with self.assertRaises(RuntimeError) as raised:
                integrations.run_git(self.repo, ["fetch", "origin"])
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertIn("credentials redacted", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

"""Offline tests for GitHub CLI publishing and partial-state reporting."""

import subprocess
import tempfile
import unittest
import os
from pathlib import Path
from unittest.mock import patch

from github_publishing import (
    GitHubCLIError,
    GitHubPublisher,
    PublishError,
    validate_description,
    validate_repository_name,
)
from integrations import run_git


class GitHubPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.safe_git = patch.dict(os.environ, {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
        })
        self.safe_git.start()
        self.addCleanup(self.safe_git.stop)
        self.folder = Path(self.temp.name) / "project"
        self.folder.mkdir()
        run_git(self.folder, ["init", "-b", "main"])
        run_git(self.folder, ["config", "user.name", "Launchpad Test"])
        run_git(self.folder, ["config", "user.email", "launchpad@example.invalid"])
        (self.folder / "README.md").write_text("hello\n", encoding="utf-8")
        run_git(self.folder, ["add", "--", "README.md"])
        run_git(self.folder, ["commit", "-m", "initial"])
        self.local_sha = run_git(self.folder, ["rev-parse", "HEAD"])
        self.url = "https://github.com/test-owner/new-project"
        self.gh_calls = []

    def gh_ok(self, folder, argv, timeout):
        self.gh_calls.append(argv)
        args = argv[1:]
        if args[:2] == ["api", "user"]:
            return subprocess.CompletedProcess(argv, 0, "test-owner\n", "")
        if args[:2] == ["repo", "view"]:
            return subprocess.CompletedProcess(argv, 0, self.url + "\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def successful_git_runner(self):
        remotes = []

        def runner(folder, args, timeout=20):
            if args == ["remote"]:
                return "\n".join(remotes)
            if args[:2] == ["rev-parse", "HEAD"]:
                return self.local_sha
            if args == ["branch", "--show-current"]:
                return "main"
            if args[:2] == ["remote", "add"]:
                remotes.append(args[2])
                return ""
            if args == ["push", "--set-upstream", "origin", "main"]:
                return ""
            if args == ["remote", "get-url", "origin"]:
                return self.url
            if args == ["ls-remote", "--heads", "origin", "refs/heads/main"]:
                return f"{self.local_sha}\trefs/heads/main"
            raise AssertionError(f"Unexpected Git command: {args}")

        return runner

    def publisher(self, gh_runner=None, git_runner=None, which=None):
        return GitHubPublisher(
            gh_runner=gh_runner or self.gh_ok,
            git_runner=git_runner or self.successful_git_runner(),
            which=which or (lambda _name: "gh.exe"),
        )

    def test_name_and_description_validation(self):
        self.assertEqual(validate_repository_name("sample_repo-2"), "sample_repo-2")
        for value in ("", "with space", "a/b", ".", "x" * 101):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_repository_name(value)
        self.assertEqual(validate_description("  sample  "), "sample")
        with self.assertRaises(ValueError):
            validate_description("x" * 351)

    def test_missing_cli_and_unauthenticated_cli_give_guidance_without_leaking_output(self):
        missing = GitHubPublisher(which=lambda _name: None)
        with self.assertRaisesRegex(GitHubCLIError, "cli.github.com"):
            missing.check_authentication(self.folder)

        def not_authenticated(folder, argv, timeout):
            return subprocess.CompletedProcess(argv, 1, "gho_super_secret\n", "not logged in")
        publisher = self.publisher(gh_runner=not_authenticated)
        with self.assertRaises(GitHubCLIError) as raised:
            publisher.check_authentication(self.folder)
        self.assertIn("gh auth login", str(raised.exception))
        self.assertNotIn("gho_super_secret", str(raised.exception))

    def test_successful_private_public_publish_uses_safe_commands_and_verifies_hash(self):
        for visibility in ("private", "public"):
            with self.subTest(visibility=visibility):
                self.gh_calls.clear()
                publisher = self.publisher()
                result = publisher.publish(
                    self.folder, "new-project", "A project", visibility
                )
                self.assertTrue(result.verified)
                self.assertEqual(result.url, self.url)
                create_call = next(call for call in self.gh_calls if call[1:3] == ["repo", "create"])
                self.assertIn(f"--{visibility}", create_call)
                self.assertNotIn("--public", create_call) if visibility == "private" else self.assertIn("--public", create_call)

    def test_existing_origin_stops_before_github_cli_and_does_not_replace_it(self):
        calls = []
        def git_runner(folder, args, timeout=20):
            if args == ["remote"]:
                return "origin"
            raise AssertionError(args)
        publisher = self.publisher(gh_runner=lambda *args: calls.append(args), git_runner=git_runner)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertFalse(raised.exception.state.remote_created)
        self.assertEqual(calls, [])

    def test_missing_initial_commit_stops_before_auth_or_remote_creation(self):
        calls = []
        def git_runner(folder, args, timeout=20):
            if args == ["remote"]:
                return ""
            if args == ["rev-parse", "HEAD"]:
                raise RuntimeError("Needed a single revision")
            raise AssertionError(args)
        publisher = self.publisher(gh_runner=lambda *args: calls.append(args), git_runner=git_runner)
        with self.assertRaisesRegex(PublishError, "no commit yet"):
            publisher.publish(self.folder, "new-project")
        self.assertEqual(calls, [])

    def test_failed_create_reports_no_remote_and_existing_repo_error(self):
        def gh_runner(folder, argv, timeout):
            if argv[1:3] == ["repo", "create"]:
                return subprocess.CompletedProcess(argv, 1, "", "repository already exists")
            return subprocess.CompletedProcess(argv, 0, "", "")
        publisher = self.publisher(gh_runner=gh_runner)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertFalse(raised.exception.state.remote_created)
        self.assertFalse(raised.exception.state.remote_configured)
        self.assertFalse(raised.exception.state.push_succeeded)
        self.assertIn("already exists", str(raised.exception))

    def test_failure_after_remote_creation_reports_partial_state(self):
        def gh_runner(folder, argv, timeout):
            if argv[1:3] == ["api", "user"]:
                return subprocess.CompletedProcess(argv, 0, "test-owner", "")
            if argv[1:3] == ["repo", "view"]:
                return subprocess.CompletedProcess(argv, 0, self.url, "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        def git_runner(folder, args, timeout=20):
            if args == ["remote"]:
                return ""
            if args == ["rev-parse", "HEAD"]:
                return self.local_sha
            if args == ["branch", "--show-current"]:
                return "main"
            if args[:2] == ["remote", "add"]:
                raise RuntimeError("simulated remote add failure")
            raise AssertionError(args)
        publisher = self.publisher(gh_runner=gh_runner, git_runner=git_runner)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertTrue(raised.exception.state.remote_created)
        self.assertFalse(raised.exception.state.remote_configured)
        self.assertFalse(raised.exception.state.push_succeeded)
        self.assertEqual(raised.exception.state.url, self.url)

    def test_push_failure_reports_remote_and_origin_without_claiming_success(self):
        remotes = []
        def git_runner(folder, args, timeout=20):
            if args == ["remote"]:
                return "\n".join(remotes)
            if args == ["rev-parse", "HEAD"]:
                return self.local_sha
            if args == ["branch", "--show-current"]:
                return "main"
            if args[:2] == ["remote", "add"]:
                remotes.append("origin")
                return ""
            if args[0] == "push":
                raise RuntimeError("authentication failed")
            raise AssertionError(args)
        publisher = self.publisher(git_runner=git_runner)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertTrue(raised.exception.state.remote_created)
        self.assertTrue(raised.exception.state.remote_configured)
        self.assertFalse(raised.exception.state.push_succeeded)
        self.assertFalse(raised.exception.state.verified)

    def test_remote_commit_mismatch_is_not_reported_as_verified(self):
        runner = self.successful_git_runner()
        def mismatched_git(folder, args, timeout=20):
            if args[:2] == ["ls-remote", "--heads"]:
                return f"{'f' * 40}\trefs/heads/main"
            return runner(folder, args, timeout)
        publisher = self.publisher(git_runner=mismatched_git)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertTrue(raised.exception.state.push_succeeded)
        self.assertFalse(raised.exception.state.verified)

    def test_cli_timeout_marks_remote_creation_unknown(self):
        def timed_out(folder, argv, timeout):
            if argv[1:3] == ["repo", "create"]:
                raise subprocess.TimeoutExpired(argv, timeout)
            return subprocess.CompletedProcess(argv, 0, "", "")
        publisher = self.publisher(gh_runner=timed_out)
        with self.assertRaises(PublishError) as raised:
            publisher.publish(self.folder, "new-project")
        self.assertIsNone(raised.exception.state.remote_created)
        self.assertFalse(raised.exception.state.remote_configured)


if __name__ == "__main__":
    unittest.main()

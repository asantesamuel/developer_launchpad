"""Safe, verifiable GitHub publishing through the official ``gh`` CLI."""

from dataclasses import dataclass
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from integrations import _redact_git_error, run_git


GITHUB_CLI_URL = "https://cli.github.com/"


class GitHubCLIError(RuntimeError):
    """The GitHub CLI is missing, unauthenticated, or could not be queried."""

    def __init__(self, message, uncertain=False):
        super().__init__(message)
        self.uncertain = uncertain


@dataclass(frozen=True)
class PublishState:
    """What is known about a publish attempt, including partial progress."""

    # None means the corresponding external command failed ambiguously, for
    # example by timing out after the server may already have accepted it.
    remote_created: bool | None = False
    remote_configured: bool | None = False
    push_succeeded: bool | None = False
    verified: bool = False
    url: str | None = None


class PublishError(RuntimeError):
    """A publishing failure carrying an accurate partial-state snapshot."""

    def __init__(self, message, state):
        super().__init__(message)
        self.state = state


def validate_repository_name(name):
    """Accept GitHub repository names that are safe as one CLI argument."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Enter a GitHub repository name.")
    if name != name.strip():
        raise ValueError("Repository names cannot start or end with whitespace.")
    if len(name) > 100 or not re.fullmatch(r"[A-Za-z0-9._-]+", name) or name in (".", ".."):
        raise ValueError("Use 1–100 letters, numbers, periods, underscores, or hyphens for the repository name.")
    return name


def validate_description(description):
    """Validate an optional GitHub description without interpreting it."""
    if not isinstance(description, str):
        raise ValueError("Repository description must be text.")
    if len(description) > 350 or any(ord(char) < 32 and char not in "\t\n\r" for char in description):
        raise ValueError("Repository descriptions must be at most 350 characters and contain no control characters.")
    return description.strip()


class GitHubPublisher:
    """Publish one local commit with ``gh``, then verify the remote ref.

    ``gh_runner`` and ``git_runner`` are injectable to keep tests offline and
    deterministic. They receive an argument list; neither uses a shell.
    """

    def __init__(self, gh_runner=None, git_runner=None, which=None):
        self._gh_runner = gh_runner
        self._git_runner = git_runner or run_git
        self._which = which or shutil.which

    def _run_gh(self, folder, args, timeout=30):
        executable = self._which("gh")
        if not executable:
            raise GitHubCLIError(
                f"GitHub CLI (gh) is not installed or not on PATH. Install it from {GITHUB_CLI_URL}."
            )
        try:
            if self._gh_runner:
                result = self._gh_runner(folder, [executable, *args], timeout)
            else:
                result = subprocess.run(
                    [executable, *args],
                    cwd=str(folder),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
        except FileNotFoundError as exc:
            raise GitHubCLIError(f"GitHub CLI was not found. Install it from {GITHUB_CLI_URL}.") from exc
        except subprocess.TimeoutExpired as exc:
            raise GitHubCLIError(f"GitHub CLI timed out while running 'gh {args[0]}'.", uncertain=True) from exc
        except OSError as exc:
            raise GitHubCLIError(f"Could not start GitHub CLI: {exc}") from exc
        if result.returncode != 0:
            detail = _redact_cli_detail((result.stderr or result.stdout or "").strip())
            # Never show raw authentication-status output; gh may mention account details.
            if args[:2] == ["auth", "status"]:
                detail = ""
            reason = f": {detail[:500]}" if detail else ""
            known_collision = bool(re.search(r"already exists|already taken|name is unavailable", detail, re.IGNORECASE))
            uncertain = args[:2] == ["repo", "create"] and not known_collision
            raise GitHubCLIError(
                f"'gh {' '.join(args[:2])}' failed with exit code {result.returncode}{reason}",
                uncertain=uncertain,
            )
        return (result.stdout or "").strip()

    def check_authentication(self, folder):
        """Check CLI presence and auth state without exposing CLI output."""
        try:
            self._run_gh(folder, ["auth", "status", "--hostname", "github.com"], timeout=20)
        except GitHubCLIError as exc:
            if "not installed" in str(exc).lower() or "install it" in str(exc).lower():
                raise
            if exc.uncertain:
                raise GitHubCLIError(
                    "GitHub CLI authentication check timed out. Check your network, then run `gh auth status`; "
                    "if needed, authenticate with `gh auth login`. Credentials stay in GitHub CLI, not this app.",
                    uncertain=True,
                ) from exc
            raise GitHubCLIError(
                "GitHub CLI is installed, but authentication could not be confirmed. "
                "Run `gh auth login` in PowerShell, then try publishing again. "
                "Developer Launchpad does not collect or store GitHub credentials."
            ) from exc
        return True

    def publish(self, folder, repository_name, description="", visibility="private", progress=None):
        """Create a new remote, add origin, push one branch, and verify its SHA."""
        folder = Path(folder).resolve()
        repository_name = validate_repository_name(repository_name)
        description = validate_description(description)
        if visibility not in ("private", "public"):
            raise ValueError("Visibility must be private or public.")
        state = PublishState()

        def report(message):
            if progress:
                progress(message)

        def fail(message, cause=None):
            error = PublishError(message, state)
            if cause:
                raise error from cause
            raise error

        try:
            if not folder.is_dir():
                fail(f"Local project folder is unavailable: {folder}")
            remotes = self._git_runner(folder, ["remote"], timeout=20).splitlines()
            if "origin" in remotes:
                fail("This new project already has an 'origin' remote. No remote was created or replaced; inspect Git → Branches & Fetch and resolve the conflict manually.")
            try:
                local_sha = self._git_runner(folder, ["rev-parse", "HEAD"], timeout=20)
            except RuntimeError as exc:
                fail("This repository has no commit yet. Create an explicitly authorized initial commit before publishing.", exc)
            branch = self._git_runner(folder, ["branch", "--show-current"], timeout=20)
            if not branch:
                fail("The repository is in detached HEAD state. Switch to a named local branch before publishing.")
            report("Checking GitHub CLI authentication…")
            self.check_authentication(folder)

            report(f"Creating a {visibility} GitHub repository…")
            args = ["repo", "create", repository_name, f"--{visibility}"]
            if description:
                args.extend(["--description", description])
            # A timeout may occur after GitHub created the repo but before gh
            # returned, so represent this operation as uncertain until verified.
            state = PublishState(remote_created=None)
            try:
                self._run_gh(folder, args, timeout=90)
            except GitHubCLIError as exc:
                state = PublishState(remote_created=None if exc.uncertain else False)
                fail(str(exc), exc)
            state = PublishState(remote_created=True)

            report("Resolving the authenticated GitHub account and repository URL…")
            owner = self._run_gh(folder, ["api", "user", "--jq", ".login"], timeout=30)
            if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
                fail("GitHub created the repository, but the authenticated account name could not be validated. The remote was not configured locally.")
            full_name = f"{owner}/{repository_name}"
            url = self._run_gh(folder, ["repo", "view", full_name, "--json", "url", "--jq", ".url"], timeout=30)
            parsed_url = urlparse(url)
            url_parts = parsed_url.path.strip("/").split("/")
            if (
                parsed_url.scheme != "https"
                or parsed_url.hostname != "github.com"
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.query
                or parsed_url.fragment
                or len(url_parts) != 2
                or url_parts[0].casefold() != owner.casefold()
                or url_parts[1].casefold() != repository_name.casefold()
            ):
                fail("GitHub created the repository, but returned an unexpected URL. The remote was not configured locally.")
            state = PublishState(remote_created=True, url=url)

            # Check again immediately before adding in case another local action
            # changed remotes while the remote repository was being created.
            remotes = self._git_runner(folder, ["remote"], timeout=20).splitlines()
            if "origin" in remotes:
                fail("The GitHub repository was created, but an 'origin' remote appeared locally before configuration. It was not replaced and no push was attempted.")
            report("Adding the origin remote…")
            state = PublishState(remote_created=True, remote_configured=None, url=url)
            try:
                self._git_runner(folder, ["remote", "add", "origin", url], timeout=20)
            except subprocess.TimeoutExpired as exc:
                fail(f"Adding the origin remote timed out; check `git remote -v` before retrying. {exc}", exc)
            except Exception as exc:
                state = PublishState(remote_created=True, remote_configured=False, url=url)
                fail(f"Could not configure the local origin remote: {exc}", exc)
            state = PublishState(remote_created=True, remote_configured=True, url=url)

            report(f"Pushing branch '{branch}' without force…")
            state = PublishState(remote_created=True, remote_configured=True, push_succeeded=None, url=url)
            try:
                self._git_runner(folder, ["push", "--set-upstream", "origin", branch], timeout=120)
            except subprocess.TimeoutExpired as exc:
                fail(f"Push timed out; inspect the remote branch before retrying. {exc}", exc)
            except Exception as exc:
                state = PublishState(remote_created=True, remote_configured=True, push_succeeded=False, url=url)
                fail(f"Git could not push the branch: {exc}", exc)
            state = PublishState(remote_created=True, remote_configured=True, push_succeeded=True, url=url)

            report("Verifying the published branch…")
            configured_url = self._git_runner(folder, ["remote", "get-url", "origin"], timeout=20)
            if _normalized_github_url(configured_url) != _normalized_github_url(url):
                fail("The push command completed, but the configured origin does not match the new GitHub repository. Publication could not be verified.")
            remote_ref = self._git_runner(folder, ["ls-remote", "--heads", "origin", f"refs/heads/{branch}"], timeout=30)
            remote_sha = remote_ref.split(None, 1)[0] if remote_ref.strip() else ""
            if not remote_sha or remote_sha != local_sha:
                fail("The remote branch did not report the expected commit hash. The push may have completed, but publication could not be verified.")
            state = PublishState(remote_created=True, remote_configured=True, push_succeeded=True, verified=True, url=url)
            report("GitHub repository and pushed branch verified.")
            return state
        except PublishError:
            raise
        except Exception as exc:
            fail(f"Publishing stopped: {_redact_cli_detail(str(exc))}. No force push or remote replacement was attempted.", exc)


def _normalized_github_url(url):
    """Normalize HTTPS and SSH GitHub URLs for a safe origin comparison."""
    value = url.strip()
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return (parsed.hostname or "").lower(), path.lower()


def _redact_cli_detail(message):
    """Mask common GitHub token formats before CLI errors reach logs or UI."""
    message = _redact_git_error(message)
    return re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b",
        "[credential redacted]",
        message,
    )

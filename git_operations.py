"""Testable Git workflows used by the Developer Launchpad interface."""

from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from integrations import run_git


@dataclass(frozen=True)
class FileChange:
    """One path reported by Git, including both index and worktree state."""

    path: str
    index_status: str
    worktree_status: str
    original_path: str | None = None

    @property
    def untracked(self):
        return self.index_status == "?" and self.worktree_status == "?"

    @property
    def staged(self):
        return self.index_status not in (" ", "?")

    @property
    def unstaged(self):
        return self.worktree_status not in (" ", "?")

    @property
    def display_status(self):
        if self.untracked:
            return "UNTRACKED"
        pieces = []
        if self.staged:
            pieces.append(f"staged {self._describe(self.index_status)}")
        if self.unstaged:
            pieces.append(f"unstaged {self._describe(self.worktree_status)}")
        if self.original_path:
            pieces.append(f"from {self.original_path}")
        return ", ".join(pieces) or "changed"

    @staticmethod
    def _describe(code):
        return {
            "A": "added", "M": "modified", "D": "deleted", "R": "renamed",
            "C": "copied", "T": "type changed", "U": "conflict",
        }.get(code, f"status {code}")


@dataclass(frozen=True)
class RepositoryStatus:
    """A parsed snapshot of branch and working-tree state."""

    branch: str
    upstream: str | None
    ahead: int | None
    behind: int | None
    changes: tuple[FileChange, ...]

    @property
    def summary(self):
        if not self.changes:
            return "Working tree clean."
        staged = sum(change.staged for change in self.changes)
        unstaged = sum(change.unstaged for change in self.changes)
        untracked = sum(change.untracked for change in self.changes)
        return f"{staged} staged, {unstaged} unstaged, {untracked} untracked file(s)."


class GitOperations:
    """Git operations scoped to one project folder.

    The optional runner makes command behavior replaceable in focused unit tests.
    """

    def __init__(self, folder, runner=None):
        self.folder = Path(folder)
        self._runner = runner or run_git

    def _run(self, args, timeout=20):
        if not self.folder.is_dir():
            raise RuntimeError(f"Project folder not found: {self.folder}")
        return self._runner(self.folder, args, timeout=timeout)

    def status(self):
        """Return the branch, upstream tracking state, and changed paths."""
        output = self._run(["status", "--porcelain=v1", "-z", "--branch", "--untracked-files=all"])
        fields = output.split("\0")
        header = fields[0] if fields else ""
        branch, upstream, ahead, behind = self._parse_branch_header(header)
        changes = []
        index = 1
        while index < len(fields):
            entry = fields[index]
            index += 1
            if not entry:
                continue
            code, separator, path = entry[:2], entry[2:3], entry[3:]
            if len(code) != 2 or separator != " ":
                continue
            original_path = None
            if "R" in code or "C" in code:
                if index < len(fields):
                    original_path = fields[index]
                    index += 1
            changes.append(FileChange(path, code[0], code[1], original_path))
        return RepositoryStatus(branch, upstream, ahead, behind, tuple(changes))

    @staticmethod
    def _parse_branch_header(header):
        if not header.startswith("## "):
            raise RuntimeError("Git returned an unexpected status response.")
        detail = header[3:]
        branch_part, _, tracking = detail.partition("...")
        if branch_part.startswith("No commits yet on "):
            branch = branch_part.removeprefix("No commits yet on ")
        else:
            branch = "(detached HEAD)" if branch_part == "HEAD (no branch)" else branch_part
        upstream = None
        ahead = behind = None
        if tracking:
            upstream_part = tracking.split(" [", 1)[0]
            upstream = upstream_part or None
        if tracking.endswith(" [gone]") and upstream:
            upstream += " (gone)"
        if " [" in detail and detail.endswith("]"):
            counts = detail.rsplit(" [", 1)[1][:-1]
            if counts != "gone":
                ahead = behind = 0
                for part in counts.split(", "):
                    if part.startswith("ahead "):
                        ahead = int(part[6:])
                    elif part.startswith("behind "):
                        behind = int(part[7:])
        return branch, upstream, ahead, behind

    def diff(self, change, staged=False, max_bytes=1_000_000):
        """Return a readable diff, or an explanation when content is unavailable."""
        path = change.path
        if change.untracked:
            if staged:
                return "This untracked file has no staged diff. Stage it first to review the staged version."
            file_path = self.folder / Path(path)
            try:
                content = file_path.read_bytes()
            except OSError as exc:
                return f"Diff unavailable: could not read this untracked file ({exc})."
            if len(content) > max_bytes:
                return "Diff unavailable: this untracked file is larger than the 1 MB preview limit."
            if b"\0" in content:
                return "Diff unavailable: Git identifies this untracked file as binary."
            text = content.decode("utf-8", errors="replace")
            lines = text.splitlines(keepends=True)
            return "".join(unified_diff([], lines, fromfile="/dev/null", tofile=path)) or "Untracked file is empty."

        args = ["diff", "--no-ext-diff", "--no-color"]
        if staged:
            args.append("--cached")
        args.extend(["--find-renames", "--", path])
        output = self._run(args)
        if not output:
            return "No difference is available for this file in the selected staged/unstaged view."
        if "Binary files " in output and " differ" in output:
            return "Diff unavailable: Git reports that this file is binary."
        if len(output.encode("utf-8", errors="replace")) > max_bytes:
            return "Diff unavailable: this diff is larger than the 1 MB preview limit."
        return output

    def stage(self, paths):
        """Stage only the supplied paths; never stage the entire repository."""
        selected = list(dict.fromkeys(paths))
        if not selected:
            raise RuntimeError("Select one or more changed files to stage.")
        self._run(["add", "--", *selected])

    def unstage(self, paths):
        """Remove only the supplied paths from the index, preserving worktree files."""
        selected = list(dict.fromkeys(paths))
        if not selected:
            raise RuntimeError("Select one or more staged files to unstage.")
        current = {change.path: change for change in self.status().changes}
        new_files = [path for path in selected if current.get(path) and current[path].index_status == "A"]
        tracked_files = [path for path in selected if path not in new_files]
        if new_files:
            # There is no HEAD version to restore for newly added files. Removing
            # only their index entries leaves their worktree contents untouched.
            self._run(["rm", "--cached", "--", *new_files])
        if tracked_files:
            self._run(["restore", "--staged", "--", *tracked_files])

    def branches(self):
        """Return local branches and the current branch name (or detached HEAD)."""
        names = self._run(["for-each-ref", "--format=%(refname:short)", "refs/heads"])
        try:
            branch = self._run(["symbolic-ref", "--quiet", "--short", "HEAD"])
        except RuntimeError:
            branch = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
            if branch == "HEAD":
                branch = "(detached HEAD)"
        return names.splitlines(), branch

    def recent_commits(self):
        """Return the five most recent commits in compact form."""
        return self._run(["log", "-5", "--oneline", "--decorate"])

    def create_branch(self, name):
        """Create and switch to a new branch after Git validates its name."""
        if not name or not name.strip():
            raise RuntimeError("Enter a branch name.")
        name = name.strip()
        self._run(["check-ref-format", "--branch", name])
        self._run(["switch", "-c", name])

    def switch_branch(self, name):
        """Switch without force; Git refuses if local changes cannot be preserved."""
        if not name:
            raise RuntimeError("Choose a local branch to switch to.")
        self._run(["switch", "--", name])

    def fetch(self, remote=None):
        """Fetch from one configured remote without integrating its changes."""
        remotes = self._run(["remote"]).splitlines()
        if not remotes:
            raise RuntimeError("No Git remotes are configured for this repository.")
        selected_remote = remote or ("origin" if "origin" in remotes else remotes[0])
        if selected_remote not in remotes:
            raise RuntimeError(f"Remote '{selected_remote}' is not configured in this repository.")
        self._run(["fetch", selected_remote], timeout=90)
        status = self.status()
        if status.upstream is None:
            return f"Fetched '{selected_remote}'. This branch has no upstream, so ahead/behind counts are unavailable."
        if status.upstream.endswith(" (gone)"):
            return f"Fetched '{selected_remote}', but upstream {status.upstream[:-7]} is unavailable. No ahead/behind count is available."
        ahead = status.ahead or 0
        behind = status.behind or 0
        return f"Fetched '{selected_remote}' without merging. Local branch is {ahead} ahead and {behind} behind {status.upstream}."

    def staged_paths(self):
        """Return paths with staged changes, preserving spaces and Unicode."""
        return [change.path for change in self.status().changes if change.staged]

    def commit(self, message):
        """Commit the index only; unstaged and untracked files are not added."""
        if not message or not message.strip():
            raise RuntimeError("Enter a non-empty commit message.")
        staged = self.staged_paths()
        if not staged:
            raise RuntimeError("There are no staged changes. Select files and choose Stage selected first.")
        self._run(["commit", "-m", message.strip()])
        return self._run(["rev-parse", "--short", "HEAD"])

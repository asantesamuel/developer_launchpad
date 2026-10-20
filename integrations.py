"""Helpers for locating and launching external development tools."""

import os
import re
import shutil
import subprocess
from pathlib import Path


def _redact_git_error(message):
    """Remove common credentials from Git error text before showing it in the UI."""
    message = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@", r"\1[credentials redacted]@", message)
    message = re.sub(
        r"(?i)(authorization:\s*(?:basic|bearer)\s+)[^\s]+",
        r"\1[credentials redacted]",
        message,
    )
    return re.sub(
        r"(?i)([?&](?:token|access_token|password|key)=)[^&\s]+",
        r"\1[credentials redacted]",
        message,
    )


def find_vscode():
    """Find the VS Code command, checking PATH and common Windows locations."""
    found = shutil.which("code")
    if found:
        return found

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/bin/code.cmd",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Microsoft VS Code/Code.exe",
        Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Microsoft VS Code/Code.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def run_git(folder, args, timeout=20):
    """Run Git in *folder* and return its output, or raise a useful error."""
    git = shutil.which("git")
    if not git:
        raise RuntimeError("Git was not found. Install Git for Windows and reopen the app.")

    result = subprocess.run(
        [git, "-C", str(folder), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(_redact_git_error(detail) or f"Git command failed: {args[0]}")
    return result.stdout.strip()


def open_vscode(folder, vscode):
    """Launch VS Code for a folder using its discovered executable."""
    if vscode.lower().endswith(".cmd"):
        # Windows command scripts need a shell; quote both paths for spaces.
        subprocess.Popen(f'"{vscode}" "{folder}"', shell=True)
    else:
        subprocess.Popen([vscode, str(folder)])


def open_terminal(folder):
    """Open PowerShell in a folder, escaping embedded single quotes."""
    quoted_folder = str(folder).replace("'", "''")
    command = f"Set-Location -LiteralPath '{quoted_folder}'"
    subprocess.Popen(["powershell.exe", "-NoExit", "-Command", command])


def open_explorer(folder):
    """Open a folder in Windows File Explorer."""
    os.startfile(str(folder))

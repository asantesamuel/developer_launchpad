"""Read and write Developer Launchpad's saved project shortcuts."""

import json
from pathlib import Path
from tkinter import messagebox

from command_profiles import CommandProfile


APP_DIR = Path.home() / ".developer_launchpad"
PROJECTS_FILE = APP_DIR / "projects.json"


def ensure_app_dir():
    """Create the per-user settings directory when it is missing."""
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_projects():
    """Load project shortcuts, showing a warning if saved data is unreadable."""
    ensure_app_dir()
    if not PROJECTS_FILE.exists():
        return []

    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        messagebox.showwarning(
            "Project list",
            f"Could not read the saved project list:\n{PROJECTS_FILE}\n\n"
            "The app will start with an empty list. Your original file has not been deleted.",
        )
        return []


def save_projects(projects):
    """Save project shortcuts using a temporary file to avoid partial writes."""
    ensure_app_dir()
    temp_file = PROJECTS_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(projects, indent=2), encoding="utf-8")
    temp_file.replace(PROJECTS_FILE)


def load_command_profiles(project):
    """Return valid profiles and warnings while preserving malformed saved data."""
    raw_profiles = project.get("commands", [])
    if not isinstance(raw_profiles, list):
        return [], ["Saved command configuration is not a list; it was left untouched."]

    profiles = []
    warnings = []
    for index, raw_profile in enumerate(raw_profiles, start=1):
        try:
            profiles.append(CommandProfile.from_dict(raw_profile))
        except ValueError as exc:
            warnings.append(f"Command profile {index} was skipped ({exc}); its saved data was preserved.")
    return profiles, warnings


def save_command_profiles(project, profiles):
    """Save valid profiles while retaining any malformed records for recovery."""
    raw_profiles = project.get("commands", [])
    malformed_profiles = []
    if isinstance(raw_profiles, list):
        for raw_profile in raw_profiles:
            try:
                CommandProfile.from_dict(raw_profile)
            except ValueError:
                malformed_profiles.append(raw_profile)
    elif "commands" in project:
        # Keep the original malformed value under a backup key instead of
        # silently replacing it when the user creates their first valid profile.
        project.setdefault("commands_invalid_backup", raw_profiles)

    project["commands"] = [profile.to_dict() for profile in profiles] + malformed_profiles

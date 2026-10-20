"""Read and write Developer Launchpad's saved project shortcuts."""

import json
import re
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

from command_profiles import CommandProfile
from project_catalog import clean_labels


APP_DIR = Path.home() / ".developer_launchpad"
PROJECTS_FILE = APP_DIR / "projects.json"
PREFERENCES_FILE = APP_DIR / "preferences.json"

DEFAULT_PREFERENCES = {
    "theme": "light",
    "window_geometry": "1120x760",
    "categories": [],
    "tags": [],
}


def ensure_app_dir():
    """Create the per-user settings directory when it is missing."""
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_projects():
    """Load project shortcuts, showing a warning if saved data is unreadable."""
    try:
        ensure_app_dir()
    except OSError as exc:
        messagebox.showwarning("Project list", f"The project settings folder is unavailable:\n{exc}")
        return []
    if not PROJECTS_FILE.exists():
        return []

    try:
        data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("saved project data must be a JSON list")
        projects = [
            item for item in data
            if isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("path"), str)
        ]
        invalid_count = len(data) - len(projects)
        if invalid_count:
            messagebox.showwarning(
                "Project list",
                f"Skipped {invalid_count} malformed project record(s). Their saved data will be preserved if you save.",
            )
        return projects
    except (json.JSONDecodeError, OSError, ValueError):
        messagebox.showwarning(
            "Project list",
            f"Could not read the saved project list:\n{PROJECTS_FILE}\n\n"
            "The app will start with an empty list. Your original file has not been deleted.",
        )
        return []


def save_projects(projects):
    """Save project shortcuts using a temporary file to avoid partial writes."""
    ensure_app_dir()
    invalid_records = []
    if PROJECTS_FILE.exists():
        try:
            existing = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                invalid_records = [
                    item for item in existing
                    if not isinstance(item, dict)
                    or not isinstance(item.get("name"), str)
                    or not isinstance(item.get("path"), str)
                ]
            else:
                raise ValueError("saved project data must be a JSON list")
        except (json.JSONDecodeError, OSError, ValueError):
            backup = PROJECTS_FILE.with_name(
                f"projects.invalid-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            if not backup.exists():
                backup.write_bytes(PROJECTS_FILE.read_bytes())
    temp_file = PROJECTS_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps([*projects, *invalid_records], indent=2), encoding="utf-8")
    temp_file.replace(PROJECTS_FILE)


def load_preferences():
    """Load user preferences, falling back field by field to safe defaults."""
    preferences = {
        key: value.copy() if isinstance(value, list) else value
        for key, value in DEFAULT_PREFERENCES.items()
    }
    warnings = []
    try:
        ensure_app_dir()
    except OSError as exc:
        warnings.append(f"Preferences folder is unavailable ({exc}); defaults are in use.")
        return preferences, warnings
    if not PREFERENCES_FILE.exists():
        return preferences, warnings
    try:
        data = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("preferences must contain a JSON object")
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        warnings.append(f"Preferences could not be loaded ({exc}); defaults are in use.")
        return preferences, warnings

    preferences.update(data)  # Retain unknown keys for forward compatibility.
    if preferences.get("theme") not in ("light", "dark"):
        preferences["theme"] = DEFAULT_PREFERENCES["theme"]
        warnings.append("Unknown theme preference; using light theme.")
    geometry = preferences.get("window_geometry")
    if not isinstance(geometry, str) or not re.fullmatch(r"\d{3,5}x\d{3,5}(?:[+-]\d+){0,2}", geometry):
        preferences["window_geometry"] = DEFAULT_PREFERENCES["window_geometry"]
        warnings.append("Invalid window size preference; using the default size.")
    for key in ("categories", "tags"):
        if not isinstance(preferences.get(key), list):
            preferences[key] = []
            warnings.append(f"Invalid {key} preference; using an empty list.")
        else:
            preferences[key] = clean_labels(preferences[key])
    return preferences, warnings


def save_preferences(preferences):
    """Atomically save preferences and back up malformed existing JSON."""
    ensure_app_dir()
    if PREFERENCES_FILE.exists():
        try:
            existing = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                existing.update(preferences)
                preferences = existing
            else:
                raise ValueError("preferences must contain a JSON object")
        except (json.JSONDecodeError, OSError, ValueError):
            backup = PREFERENCES_FILE.with_name(
                f"preferences.invalid-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
            )
            if not backup.exists():
                backup.write_bytes(PREFERENCES_FILE.read_bytes())
    temp_file = PREFERENCES_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(preferences, indent=2), encoding="utf-8")
    temp_file.replace(PREFERENCES_FILE)


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

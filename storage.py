"""Read and write Developer Launchpad's saved project shortcuts."""

import json
from pathlib import Path
from tkinter import messagebox


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

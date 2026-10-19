# Developer Launchpad

Developer Launchpad is a small Windows desktop helper for managing project shortcuts and opening development tools.

## Features

- Save project folder shortcuts in your user profile.
- Open a selected project in VS Code, PowerShell, or File Explorer.
- View Git branch/status and the five most recent commits.
- Review changed file names and confirm before staging all changes and creating a commit.

## Requirements

- Python 3.10 or newer is recommended.
- Tkinter is included with most Windows Python installations.
- Git for Windows and VS Code are optional; install them to use their respective features.
- There are no third-party Python packages, so no `requirements.txt` or `pip install` step is needed.

## Run

In PowerShell, change to this folder and run:

```powershell
cd "D:\Projects\Automations-Python Script\developer_launchpad"
python main.py
```

You can also open the folder in VS Code and run `main.py`, or continue using the old command `python developer_launchpad.py` (it forwards to the same entry point). If your Python Launcher is configured, `py main.py` works too.

The saved project list is stored at `%USERPROFILE%\.developer_launchpad\projects.json`. Removing a project in the app removes only its shortcut. The Git commit action stages all changes only after showing the current file list and asking for confirmation.

## Project layout

- `main.py` starts Tkinter and the application.
- `app.py` builds the window and handles button actions.
- `storage.py` reads and writes the saved project shortcuts.
- `integrations.py` locates VS Code and runs Git or Windows launch commands.
- `developer_launchpad.py` remains as a compatibility launcher for the original filename.

## Add an automation

Put tool-specific work in `integrations.py` (or a focused new module if it grows), then add a clearly named method to `DeveloperLaunchpad` in `app.py` that checks the selected project, calls that helper, and reports the result. Add a button in `_build_ui()` to connect the method to the interface. Keep UI prompts and messages in `app.py`; keep file persistence in `storage.py`.

## Troubleshooting

- **`No module named tkinter`**: install Python from python.org with the Tcl/Tk option enabled, then retry.
- **Git is not found**: install Git for Windows and restart Developer Launchpad so `PATH` is refreshed.
- **VS Code is not found**: install VS Code or add its `code` command to `PATH`.
- **A project folder is missing**: use the app to remove its stale shortcut and add the folder again when available.
- **The saved list cannot be read**: the app warns and starts with an empty in-memory list; the original JSON is left in place. Back it up before repairing it manually.
- **A commit fails after staging**: inspect Git status before retrying, because staging may have completed even though the commit did not.

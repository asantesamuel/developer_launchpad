# Developer Launchpad

Developer Launchpad is a small Windows desktop helper for managing project shortcuts and opening development tools.

## Features

- Save project folder shortcuts in your user profile.
- Open a selected project in VS Code, PowerShell, or File Explorer.
- View the current branch, upstream, ahead/behind counts, and working-tree summary.
- Review staged, unstaged, untracked, deleted, and renamed files and inspect staged or unstaged diffs.
- Stage or unstage only the selected files.
- Create and switch local branches with a local-change warning.
- Fetch from a configured remote without pulling, merging, rebasing, or pushing.
- Commit staged changes only.

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

The saved project list is stored at `%USERPROFILE%\.developer_launchpad\projects.json`. Removing a project in the app removes only its shortcut.

## Project layout

- `main.py` starts Tkinter and the application.
- `app.py` builds the window and handles button actions.
- `storage.py` reads and writes the saved project shortcuts.
- `integrations.py` locates VS Code and runs Git or Windows launch commands.
- `git_operations.py` contains testable Git status, diff, staging, branch, fetch, and commit operations.
- `tests/test_git_operations.py` exercises Git workflows in disposable local repositories.
- `developer_launchpad.py` remains as a compatibility launcher for the original filename.

## Add an automation

Put a Git workflow in `git_operations.py` so it can be tested without starting the GUI. Add a clearly named handler in `DeveloperLaunchpad` in `app.py`, connect it to a button in `_build_ui()`, and use `_submit_git()` for work that may take time. Keep UI prompts and messages in `app.py`; keep file persistence in `storage.py`.

## Git workflow

1. Select a project and open **Overview**. The app shows its branch, upstream tracking state, and counts for staged, unstaged, and untracked files. Use **Refresh** to update it.
2. Open **Changes & Commit**. Select one or more file rows; use **Unstaged** or **Staged** to inspect the corresponding diff. **Stage selected** and **Unstage selected** affect only selected paths.
3. Review the staged-file list, enter a commit message, and choose **Commit staged changes**. Unstaged and untracked files are not automatically added.
4. Open **Branches & Fetch** to create a branch, switch to a local branch, or fetch from the configured `origin` remote (or the first configured remote when there is no `origin`). Fetch updates remote-tracking information only; it does not integrate changes.

The app warns before attempting a branch switch when the working tree has local changes. A normal `git switch` is used without force; Git can carry compatible changes and refuses a conflicting switch. No reset, clean, forced switch, push, merge, or rebase command is used.

Run the automated checks with:

```powershell
python -m unittest discover -s tests -v
```

## Troubleshooting

- **`No module named tkinter`**: install Python from python.org with the Tcl/Tk option enabled, then retry.
- **Git is not found**: install Git for Windows and restart Developer Launchpad so `PATH` is refreshed.
- **VS Code is not found**: install VS Code or add its `code` command to `PATH`.
- **A project folder is missing**: use the app to remove its stale shortcut and add the folder again when available.
- **The saved list cannot be read**: the app warns and starts with an empty in-memory list; the original JSON is left in place. Back it up before repairing it manually.
- **A commit fails after staging**: inspect Git status before retrying, because staging may have completed even though the commit did not.
- **No upstream is shown**: configure an upstream for that branch in Git; the app does not change remote or upstream configuration.
- **Fetch fails**: verify the remote exists, network access works, and your Git credentials are available. Fetch never merges the fetched changes.

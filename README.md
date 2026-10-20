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
- Save independent development command profiles for each project, stream their output, and stop long-running processes.

## Requirements

- Python 3.10 or newer is recommended.
- Tkinter is included with most Windows Python installations.
- Git for Windows and VS Code are optional; install them to use their respective features.
- There are no third-party Python packages, so no `requirements.txt` or `pip install` step is needed.
- Install the tools used by the commands you configure (for example Node.js/npm, Python, or the .NET SDK). Launchpad does not install them for you.

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
- `command_profiles.py` validates saved command profiles and resolves safe project-relative working directories.
- `command_runner.py` runs an explicitly requested command off the GUI thread, streams stdout/stderr, and stops the process tree.
- `tests/test_command_automation.py` tests profile persistence, input validation, command output, exit codes, cancellation, and GUI queue handling.
- `tests/test_git_operations.py` exercises Git workflows in disposable local repositories.
- `developer_launchpad.py` remains as a compatibility launcher for the original filename.

## Add an automation

Put a Git workflow in `git_operations.py` so it can be tested without starting the GUI. Add a clearly named handler in `DeveloperLaunchpad` in `app.py`, connect it to a button in `_build_ui()`, and use `_submit_git()` for work that may take time. For a development command, model its saved settings in `command_profiles.py`, keep process execution in `command_runner.py`, and let `app.py` collect runner events from a queue on Tkinter's main thread. Keep profile persistence in `storage.py`.

## Development commands

1. Select a project and open **Dev Commands**. Add a profile with a display name, executable, arguments, a project-relative working folder, and an optional description. Mark servers or watchers as **Long-running** to distinguish them from tasks.
2. Enter arguments one per line. Each line is passed as one separate argument to the executable. For example, for a Python test profile use executable `python` and arguments `-m` then `pytest`. For `dotnet test`, use executable `dotnet` and argument `test`.
3. For Node projects on Windows, npm is commonly installed as `npm.cmd`, which is a shell script and may not be directly launchable with the app's safe no-shell mode. To run it without enabling a shell, set the executable to `node.exe` and pass the path to that installation's `node_modules/npm/bin/npm-cli.js` as the first argument, followed by npm arguments such as `run` and `dev`. For example, a standard Node.js installation often places the CLI at `C:\Program Files\nodejs\node_modules\npm\bin\npm-cli.js`; check your own installation path. This same pattern supports `install` when you explicitly choose to run it. The existing PowerShell button is another option for commands that require shell syntax.
4. Check the displayed effective working directory and command details, then press **Run** when you are ready. Saved commands never run when the app starts or when a project is selected. Output streams into the panel; stderr is colored separately. **Stop** terminates the process and its child-process tree. **Clear output** only clears the display.
5. A normal task finishes with an exit code; code 0 means success and any other code means failure. A user stop is labeled separately, even when the killed process has a nonzero code.

Command profiles are stored in the existing `%USERPROFILE%\.developer_launchpad\projects.json` file as an additional `commands` field on each project record. Existing `{name, path}` project records remain valid. Invalid profile entries are skipped with a warning and retained in the saved data for recovery. Working directories must exist inside the selected project folder; absolute paths and paths that escape the project are rejected. Environment-variable overrides and shell mode are not supported.

**Safety:** a configured command can execute arbitrary code with your Windows account's permissions. Add commands only for projects you trust, inspect the executable, arguments, and working directory before running, and do not store credentials in profiles. Launchpad never runs profiles automatically, requests administrator privileges, installs dependencies, or runs deployment/database tasks on your behalf.

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

The command-runner tests use harmless invocations of the current Python interpreter and temporary folders. They do not contact remotes or run commands in your saved projects.

## Troubleshooting

- **`No module named tkinter`**: install Python from python.org with the Tcl/Tk option enabled, then retry.
- **Git is not found**: install Git for Windows and restart Developer Launchpad so `PATH` is refreshed.
- **VS Code is not found**: install VS Code or add its `code` command to `PATH`.
- **A project folder is missing**: use the app to remove its stale shortcut and add the folder again when available.
- **The saved list cannot be read**: the app warns and starts with an empty in-memory list; the original JSON is left in place. Back it up before repairing it manually.
- **A commit fails after staging**: inspect Git status before retrying, because staging may have completed even though the commit did not.
- **No upstream is shown**: configure an upstream for that branch in Git; the app does not change remote or upstream configuration.
- **Fetch fails**: verify the remote exists, network access works, and your Git credentials are available. Fetch never merges the fetched changes.
- **A development command cannot start**: verify its executable is installed and on `PATH`, and check the displayed project-relative working directory. Arguments must be entered one per line; shell expressions such as pipes and redirection are intentionally not interpreted.
- **A command returns a nonzero exit code**: read the stderr and stdout output, correct the command or project configuration, and run it again manually.
- **Stop does not appear to finish**: the app requests termination of the process tree and reports the resulting code. If Windows security software prevents `taskkill`, close the child process from its own terminal or Task Manager; do not force-close Launchpad until you understand which work is running.

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
- Search saved projects by name or path and filter them by categories and tags.
- View a project dashboard, switch between Git and command workspaces, and choose a light or dark theme.
- Use keyboard shortcuts, persistent window sizing, and a local diagnostic log.
- Create a brand-new project folder without overwriting existing folders, generate optional starter files, and initialize a local Git repository.
- Optionally create an explicit initial commit and publish a new private-by-default GitHub repository through GitHub CLI, with push verification and partial-failure reporting.

## Requirements

- Python 3.10 or newer is recommended.
- Tkinter is included with most Windows Python installations.
- Git for Windows and VS Code are optional; install them to use their respective features.
- GitHub CLI (`gh`) is optional and is required only when you choose to publish a project to GitHub. Install it from [cli.github.com](https://cli.github.com/) and authenticate with `gh auth login`.
- There are no third-party Python packages, so no `requirements.txt` or `pip install` step is needed.
- Install the tools used by the commands you configure (for example Node.js/npm, Python, or the .NET SDK). Launchpad does not install them for you.

## Run

In PowerShell, change to this folder and run:

```powershell
cd "D:\Projects\Automations-Python Script\developer_launchpad"
python main.py
```

You can also open the folder in VS Code and run `main.py`, or continue using the old command `python developer_launchpad.py` (it forwards to the same entry point). If your Python Launcher is configured, `py main.py` works too.

Project shortcuts, categories, tags, and command profiles are stored at `%USERPROFILE%\.developer_launchpad\projects.json`. Preferences such as theme and window size are stored separately in `%USERPROFILE%\.developer_launchpad\preferences.json`. Diagnostics stay local at `%USERPROFILE%\.developer_launchpad\developer_launchpad.log`. Removing a project in the app removes only its shortcut, never its folder.

## Project layout

- `main.py` starts Tkinter and the application.
- `app.py` builds the window and handles button actions.
- `storage.py` reads and writes the saved project shortcuts.
- `integrations.py` locates VS Code and runs Git or Windows launch commands.
- `git_operations.py` contains testable Git status, diff, staging, branch, fetch, and commit operations.
- `command_profiles.py` validates saved command profiles and resolves safe project-relative working directories.
- `command_runner.py` runs an explicitly requested command off the GUI thread, streams stdout/stderr, and stops the process tree.
- `project_catalog.py` contains independent project search, filter, category/tag, and shortcut operations.
- `project_creation.py` validates Windows project names, creates starter files and a local repository, and commits only generated paths.
- `github_publishing.py` checks GitHub CLI authentication, creates a new remote, pushes without force, verifies the branch commit, and reports partial state.
- `diagnostics.py` configures local error logging and the Tkinter callback error handler.
- `tests/test_project_catalog.py`, `tests/test_preferences.py`, and `tests/test_app_preferences.py` cover project discovery, settings, labels, diagnostics, and important window callbacks.
- `tests/test_command_automation.py` tests profile persistence, input validation, command output, exit codes, cancellation, and GUI queue handling.
- `tests/test_git_operations.py` exercises Git workflows in disposable local repositories.
- `tests/test_project_creation.py` uses temporary folders and local Git repositories to test name validation, collisions, initial files/commits, and recovery.
- `tests/test_github_publishing.py` uses fake CLI/Git responses; it does not contact GitHub.
- `tests/test_project_creation_gui.py` checks that user choices control whether authentication/publishing starts and that created projects are saved once.
- `developer_launchpad.py` remains as a compatibility launcher for the original filename.

## Add an automation

Put a Git workflow in `git_operations.py` so it can be tested without starting the GUI. Add a clearly named handler in `DeveloperLaunchpad` in `app.py`, connect it to a button in `_build_ui()`, and use `_submit_git()` for work that may take time. For a development command, model its saved settings in `command_profiles.py`, keep process execution in `command_runner.py`, and let `app.py` collect runner events from a queue on Tkinter's main thread. Keep profile persistence in `storage.py`.

## Projects, navigation, and preferences

The left sidebar searches project name, path, category, and tags as you type. Use the category and tag dropdowns to narrow the list. **Labels** edits the selected project's category and comma-separated tags; **Manage categories and tags…** lets you add, rename, or remove catalog labels. Removing a label clears that assignment from projects; it never removes project files. The workspace tabs are **Dashboard**, **Git**, **Dev Commands**, and **Settings**. The dashboard shows the selected project's Git snapshot; use **Refresh status** (or F5) when you want an up-to-date read. Recent commits are loaded only on request.

The theme defaults to **light** and can be changed in Settings. Window geometry is saved on close. The UI uses ttk focus behavior, labeled controls, keyboard-focusable buttons, and scrolling lists/output panels. Shortcuts are listed in Settings and in the Projects/Actions menus. Shortcuts that could interfere with normal typing are ignored while an entry or text editor has focus.

`projects.json` remains a JSON list of project objects. New project objects add optional `category` and `tags` fields; older `{name, path}` records continue to work. Preferences use a separate JSON object so theme and window settings do not depend on the installation folder. Unknown preference keys are retained for forward compatibility. Malformed preferences fall back to defaults and are backed up if the user saves new settings. Malformed project rows are skipped when loaded and retained if the list is saved.

Diagnostics are local only. Settings → **View diagnostic log** opens the log in the user profile. Captured development-command output and environment variables are not written to this log.

## Create a project and optionally publish it

Choose **Projects → Create New Project…** (or the **Create New Project…** button in the sidebar). Enter a Windows-safe folder name and choose an existing parent folder. The destination preview updates as you edit the fields. A destination that already exists is refused; the application never merges into it or overwrites it.

Choose whether to generate `README.md` and `.gitignore`. The README contains a heading using the project name and the sentence `Project created with Developer Launchpad.` The default `.gitignore` contains:

```gitignore
# Local secrets and environment settings
.env
.env.*
!.env.example
*.pem
*.key

# Python generated files and virtual environments
__pycache__/
*.py[cod]
.venv/
venv/

# Node generated dependencies and build output
node_modules/
dist/
build/

# Common operating-system metadata
.DS_Store
Thumbs.db
```

Review this file before adding project-specific files with those names. Source files, dependency lock files, and editor configuration are not excluded by this template. The README and `.gitignore` can be edited normally after creation. You may also create an empty local project with neither file. No framework template or dependency installation is run.

Before creation starts, the app shows the destination and asks for confirmation. It creates a new folder using an exclusive directory-creation operation, generates only the selected files, runs `git init`, and verifies the Git repository root. If requested, it stages and commits only the generated paths. The command uses `git add -- <generated paths>` followed by `git commit --only -m "Initial commit" -- <generated paths>`; it does not use `git add .`. If Git identity is missing, configure it yourself in PowerShell, for example `git config --global user.name "Your Name"` and `git config --global user.email "you@example.com"`. Developer Launchpad does not change global Git configuration. The new project is saved in the Launchpad after the folder exists so partial work remains discoverable; failures state whether Git initialization was verified and the folder is never deleted automatically.

After successful local creation, the app asks whether to publish. **No** keeps it local and performs no network operation. **Cancel** means decide later and also keeps the project local. Choosing **Yes** checks for `gh` and an authenticated GitHub account; the app never asks for or stores credentials. If needed, install GitHub CLI from [cli.github.com](https://cli.github.com/) and run `gh auth login` in PowerShell.

Before remote creation, review the repository name, optional description, visibility, and local path. Visibility defaults to **Private**. Public repositories can be viewed by other people; private repositories follow GitHub's access rules. The app asks for a final confirmation. Publishing runs the equivalent of `gh repo create <name> --private` (or `--public`), gets the authenticated owner using `gh api user --jq .login`, and obtains the URL using `gh repo view <owner>/<name> --json url --jq .url`. It configures `origin` only if no origin exists, pushes the current branch with `git push --set-upstream origin <branch>` (never force), and checks `git remote get-url origin` plus `git ls-remote --heads origin refs/heads/<branch>` to verify the remote branch points to the local commit. It does not modify an existing remote or overwrite a remote repository with the same name; GitHub CLI reports a name collision and the app stops.

If publishing stops after some steps, the error report identifies whether remote creation, local `origin` setup, push, and verification succeeded. A timeout is shown as **unknown** when the remote may have accepted an operation before the timeout. Inspect the provided URL, `git remote -v`, the GitHub repository, and its branch before retrying. The app never automatically repeats repository creation, force-pushes, changes visibility, or deletes remote resources. For an empty project without generated files, create and commit files through the existing Git workflow before publishing. A private or public GitHub account and network access are required for live publishing; automated tests use mocks and do not verify access to a real account.

## Optional Windows executable

The source application has no third-party runtime dependencies. To build an optional one-file Windows executable, install PyInstaller in a project-local virtual environment and run:

```powershell
cd "D:\Projects\Automations-Python Script\developer_launchpad"
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name DeveloperLaunchpad main.py
```

The executable is written to `dist\DeveloperLaunchpad.exe`. Launch it as a normal user. On the target Windows PC, verify the window opens, preferences remain under `%USERPROFILE%\.developer_launchpad`, and Git/VS Code/development tools can be found through that user's PATH. User project data and credentials are not bundled. PyInstaller is optional and is not a runtime dependency. Packaging was **not run in this environment** because PyInstaller is not installed. Unsigned executables may trigger Microsoft Defender or SmartScreen warnings. If a one-file build causes slow starts or antivirus friction, use one-folder mode by omitting `--onefile`.

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
- **A saved project folder is unavailable**: its shortcut remains visible but the dashboard marks it unavailable. Add the moved folder again with its current path, then remove the stale shortcut; removing it only affects Launchpad.
- **Preferences are malformed**: Launchpad uses defaults and reports the issue. When you next save preferences, the unreadable file is kept as `preferences.invalid-<timestamp>.json` for recovery.
- **A setting cannot be saved**: check that `%USERPROFILE%\.developer_launchpad` is writable and inspect Settings → View diagnostic log.
- **A commit fails after staging**: inspect Git status before retrying, because staging may have completed even though the commit did not.
- **No upstream is shown**: configure an upstream for that branch in Git; the app does not change remote or upstream configuration.
- **Fetch fails**: verify the remote exists, network access works, and your Git credentials are available. Fetch never merges the fetched changes.
- **A development command cannot start**: verify its executable is installed and on `PATH`, and check the displayed project-relative working directory. Arguments must be entered one per line; shell expressions such as pipes and redirection are intentionally not interpreted.
- **A command returns a nonzero exit code**: read the stderr and stdout output, correct the command or project configuration, and run it again manually.
- **Stop does not appear to finish**: the app requests termination of the process tree and reports the resulting code. If Windows security software prevents `taskkill`, close the child process from its own terminal or Task Manager; do not force-close Launchpad until you understand which work is running.
- **The test suite reports a temporary-folder `WinError 32`**: Windows may briefly hold a disposable test repository open after Git exits. Close Explorer/VS Code windows inside the printed `tmp...` path and rerun `python -m unittest discover -s tests -v`; these folders are generated test data, not saved projects.
- **The executable is blocked or warns**: the optional PyInstaller output is unsigned. Build from source in a trusted local environment, review Windows Defender/SmartScreen details, and consider code signing for distribution.

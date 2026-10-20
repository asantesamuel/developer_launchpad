"""Tkinter interface and user actions for Developer Launchpad."""

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from git_operations import GitOperations
from integrations import find_vscode, open_explorer, open_terminal, open_vscode
from storage import PROJECTS_FILE, load_projects, save_projects


class DeveloperLaunchpad:
    """Main application window and its project-management actions."""

    def __init__(self, root):
        self.root = root
        self.root.title("Developer Launchpad")
        self.root.geometry("1120x800")
        self.root.minsize(900, 650)
        self.projects = load_projects()

        self.selected_path = None
        self._worker_results = queue.Queue()
        self._git_busy = False
        self._visible_changes = []
        self._git_buttons = []
        self._project_controls = []
        self.diff_mode = tk.StringVar(value="unstaged")
        self._build_ui()
        self.refresh_projects()
        self.root.after(100, self._poll_worker_results)

    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass

        header = ttk.Frame(self.root, padding=(18, 16))
        header.pack(fill="x")
        ttk.Label(header, text="Developer Launchpad", font=("Segoe UI", 19, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text="Open projects, inspect Git, and get to work faster.",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(self.root, padding=(18, 0, 18, 12))
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, width=280)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        ttk.Label(left, text="YOUR PROJECTS", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 8))

        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True)
        self.project_list = tk.Listbox(
            list_frame, font=("Segoe UI", 10), activestyle="dotbox",
            selectmode=tk.SINGLE, exportselection=False
        )
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.project_list.yview)
        self.project_list.configure(yscrollcommand=scrollbar.set)
        self.project_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.project_list.bind("<<ListboxSelect>>", self.on_select)
        self._project_controls.append(self.project_list)

        project_buttons = ttk.Frame(left)
        project_buttons.pack(fill="x", pady=(10, 0))
        add_button = ttk.Button(project_buttons, text="Add project", command=self.add_project)
        add_button.pack(side="left", fill="x", expand=True)
        remove_button = ttk.Button(project_buttons, text="Remove", command=self.remove_project)
        remove_button.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self._project_controls.extend([add_button, remove_button])

        right = ttk.Frame(body, padding=(20, 0, 0, 0))
        right.pack(side="left", fill="both", expand=True)

        self.project_title = ttk.Label(right, text="Select a project", font=("Segoe UI", 14, "bold"))
        self.project_title.pack(anchor="w")
        self.project_path_label = ttk.Label(right, text="Add an existing folder to get started.", wraplength=520)
        self.project_path_label.pack(anchor="w", pady=(4, 12))

        actions = ttk.LabelFrame(right, text="Open", padding=10)
        actions.pack(fill="x", pady=(0, 12))
        ttk.Button(actions, text="Open in VS Code", command=self.open_vscode).pack(fill="x", pady=3)
        ttk.Button(actions, text="Open PowerShell here", command=self.open_terminal).pack(fill="x", pady=3)
        ttk.Button(actions, text="Open in File Explorer", command=self.open_explorer).pack(fill="x", pady=3)

        git_tabs = ttk.Notebook(right)
        git_tabs.pack(fill="both", expand=True)

        overview = ttk.Frame(git_tabs, padding=10)
        git_tabs.add(overview, text="Overview")
        overview_controls = ttk.Frame(overview)
        overview_controls.pack(fill="x")
        self.git_status_label = ttk.Label(overview, text="Select a project to inspect its Git repository.", wraplength=620)
        self.git_status_label.pack(side="left", fill="x", expand=True, anchor="w")
        self.refresh_git_button = ttk.Button(overview_controls, text="Refresh", command=self.refresh_git)
        self.refresh_git_button.pack(side="right")
        self._git_buttons.append(self.refresh_git_button)
        ttk.Label(overview, text="Recent commits", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(14, 4))
        self.recent_commits = tk.Text(overview, height=7, wrap="word", font=("Consolas", 9), state="disabled")
        self.recent_commits.pack(fill="both", expand=True)
        recent_button = ttk.Button(overview, text="Load recent commits", command=self.show_recent_commits)
        recent_button.pack(anchor="e", pady=(6, 0))
        self._git_buttons.append(recent_button)

        changes_tab = ttk.Frame(git_tabs, padding=8)
        git_tabs.add(changes_tab, text="Changes & Commit")
        changes_tab.columnconfigure(0, weight=1)
        changes_tab.columnconfigure(1, weight=2)
        changes_tab.rowconfigure(0, weight=1)
        file_frame = ttk.LabelFrame(changes_tab, text="Changed files (Ctrl-click for multiple)", padding=6)
        file_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.changed_files = tk.Listbox(file_frame, selectmode=tk.EXTENDED, exportselection=False, font=("Segoe UI", 9))
        file_scroll = ttk.Scrollbar(file_frame, orient="vertical", command=self.changed_files.yview)
        self.changed_files.configure(yscrollcommand=file_scroll.set)
        self.changed_files.pack(side="left", fill="both", expand=True)
        file_scroll.pack(side="right", fill="y")
        self.changed_files.bind("<<ListboxSelect>>", self.show_selected_diff)

        diff_frame = ttk.LabelFrame(changes_tab, text="Selected file diff", padding=6)
        diff_frame.grid(row=0, column=1, sticky="nsew")
        diff_modes = ttk.Frame(diff_frame)
        diff_modes.pack(fill="x")
        ttk.Radiobutton(diff_modes, text="Unstaged", variable=self.diff_mode, value="unstaged", command=self.show_selected_diff).pack(side="left")
        ttk.Radiobutton(diff_modes, text="Staged", variable=self.diff_mode, value="staged", command=self.show_selected_diff).pack(side="left", padx=(8, 0))
        self.diff_text = tk.Text(diff_frame, wrap="none", font=("Consolas", 9), state="disabled")
        diff_y = ttk.Scrollbar(diff_frame, orient="vertical", command=self.diff_text.yview)
        diff_x = ttk.Scrollbar(diff_frame, orient="horizontal", command=self.diff_text.xview)
        self.diff_text.configure(yscrollcommand=diff_y.set, xscrollcommand=diff_x.set)
        self.diff_text.pack(side="left", fill="both", expand=True, pady=(5, 0))
        diff_y.pack(side="right", fill="y", pady=(5, 0))
        diff_x.pack(side="bottom", fill="x")

        change_controls = ttk.Frame(changes_tab)
        change_controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        for title, callback in (("Stage selected", self.stage_selected), ("Unstage selected", self.unstage_selected), ("Refresh files", self.refresh_git)):
            button = ttk.Button(change_controls, text=title, command=callback)
            button.pack(side="left", padx=(0, 6))
            self._git_buttons.append(button)
        self.staged_summary = ttk.Label(changes_tab, text="Staged files: none", wraplength=600, justify="left")
        self.staged_summary.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 2))
        commit_frame = ttk.Frame(changes_tab)
        commit_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.commit_message = ttk.Entry(commit_frame)
        self.commit_message.pack(side="left", fill="x", expand=True)
        commit_button = ttk.Button(commit_frame, text="Commit staged changes", command=self.commit_staged)
        commit_button.pack(side="left", padx=(8, 0))
        self._git_buttons.append(commit_button)

        branches_tab = ttk.Frame(git_tabs, padding=10)
        git_tabs.add(branches_tab, text="Branches & Fetch")
        ttk.Label(branches_tab, text="Local branches").grid(row=0, column=0, sticky="w")
        self.branch_choice = ttk.Combobox(branches_tab, state="readonly", width=36)
        self.branch_choice.grid(row=1, column=0, sticky="ew", pady=(4, 8))
        switch_button = ttk.Button(branches_tab, text="Switch branch", command=self.request_branch_switch)
        switch_button.grid(row=1, column=1, padx=(8, 0), pady=(4, 8))
        self._git_buttons.append(switch_button)
        ttk.Label(branches_tab, text="Create and switch to a new branch").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.new_branch_name = ttk.Entry(branches_tab)
        self.new_branch_name.grid(row=3, column=0, sticky="ew", pady=(4, 8))
        create_button = ttk.Button(branches_tab, text="Create branch", command=self.create_branch)
        create_button.grid(row=3, column=1, padx=(8, 0), pady=(4, 8))
        self._git_buttons.append(create_button)
        ttk.Label(branches_tab, text="Fetch updates only. This does not merge, rebase, or change branches.", wraplength=560).grid(row=4, column=0, columnspan=2, sticky="w", pady=(14, 4))
        fetch_button = ttk.Button(branches_tab, text="Fetch configured remote", command=self.fetch_remote)
        fetch_button.grid(row=5, column=0, sticky="w")
        self._git_buttons.append(fetch_button)

        self.output = tk.Text(right, height=3, wrap="word", font=("Consolas", 9), state="disabled")
        self.output.pack(fill="x", pady=(8, 0))

        footer = ttk.Label(
            self.root,
            text=f"Project list saved locally at: {PROJECTS_FILE}",
            padding=(18, 5),
            font=("Segoe UI", 8),
        )
        footer.pack(fill="x")

    def write_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def refresh_projects(self, select_path=None):
        self.project_list.delete(0, "end")
        for project in self.projects:
            self.project_list.insert("end", project["name"])
        if self.projects:
            index = 0
            if select_path:
                for i, project in enumerate(self.projects):
                    if project["path"] == select_path:
                        index = i
                        break
            self.project_list.selection_set(index)
            self.project_list.activate(index)
            self.on_select()
        else:
            self.selected_path = None
            self.project_title.config(text="Select a project")
            self.project_path_label.config(text="Add an existing folder to get started.")
            self.write_output("Welcome!\n\nClick “Add project” to save a folder you work in.")

    def selected_project(self):
        selection = self.project_list.curselection()
        if not selection:
            messagebox.showinfo("Select a project", "Please select a project first.")
            return None
        project = self.projects[selection[0]]
        folder = Path(project["path"])
        if not folder.is_dir():
            messagebox.showerror("Folder not found", f"This project folder no longer exists:\n{folder}")
            return None
        return folder

    def on_select(self, _event=None):
        selection = self.project_list.curselection()
        if not selection:
            return
        project = self.projects[selection[0]]
        self.selected_path = project["path"]
        self.project_title.config(text=project["name"])
        self.project_path_label.config(text=project["path"])
        self.write_output(f"Selected project: {project['name']}\n\nChoose an action above.")
        self.refresh_git()

    def add_project(self):
        folder = filedialog.askdirectory(title="Choose a project folder")
        if not folder:
            return
        path = str(Path(folder).resolve())
        for project in self.projects:
            if os.path.normcase(project["path"]) == os.path.normcase(path):
                messagebox.showinfo("Already added", "That folder is already in your project list.")
                self.refresh_projects(select_path=project["path"])
                return
        suggested_name = Path(path).name or path
        name = simpledialog.askstring("Project name", "Give this project a short name:", initialvalue=suggested_name)
        if name is None:
            return
        name = name.strip() or suggested_name
        self.projects.append({"name": name, "path": path})
        save_projects(self.projects)
        self.refresh_projects(select_path=path)

    def remove_project(self):
        selection = self.project_list.curselection()
        if not selection:
            messagebox.showinfo("Select a project", "Choose a project to remove.")
            return
        project = self.projects[selection[0]]
        if not messagebox.askyesno(
            "Remove project",
            f"Remove “{project['name']}” from this app?\n\n"
            "This only removes the saved shortcut. It does not delete your project files.",
        ):
            return
        self.projects.pop(selection[0])
        save_projects(self.projects)
        self.refresh_projects()

    def open_vscode(self):
        folder = self.selected_project()
        if not folder:
            return
        vscode = find_vscode()
        if not vscode:
            messagebox.showerror(
                "VS Code not found",
                "Could not find the VS Code command or installation.\n\n"
                "Open VS Code, run “Shell Command: Install 'code' command in PATH” if available, "
                "or install VS Code and restart this app.",
            )
            return
        try:
            open_vscode(folder, vscode)
            self.write_output(f"Opening in VS Code:\n{folder}")
        except OSError as exc:
            messagebox.showerror("Could not open VS Code", str(exc))

    def open_terminal(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            open_terminal(folder)
            self.write_output(f"Opened PowerShell in:\n{folder}")
        except OSError as exc:
            messagebox.showerror("Could not open PowerShell", str(exc))

    def open_explorer(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            open_explorer(folder)
        except OSError as exc:
            messagebox.showerror("Could not open folder", str(exc))

    def _set_text(self, widget, value):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _submit_git(self, operation, on_success, on_error=None):
        """Run a Git operation off the GUI thread and return its result on the UI thread."""
        if self._git_busy:
            return
        self._git_busy = True
        for button in self._git_buttons + self._project_controls:
            button.configure(state="disabled")

        def worker():
            try:
                self._worker_results.put((on_success, operation(), on_error, None))
            except Exception as exc:
                self._worker_results.put((on_success, None, on_error, exc))

        threading.Thread(target=worker, name="launchpad-git", daemon=True).start()

    def _poll_worker_results(self):
        try:
            while True:
                on_success, result, on_error, error = self._worker_results.get_nowait()
                self._git_busy = False
                for button in self._git_buttons + self._project_controls:
                    button.configure(state="normal")
                if error is not None:
                    if on_error:
                        on_error(error)
                    else:
                        self.write_output(f"Git operation failed: {error}")
                        messagebox.showerror("Git operation failed", str(error))
                else:
                    on_success(result)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_worker_results)

    def refresh_git(self):
        folder = self.selected_project()
        if not folder:
            return
        operations = GitOperations(folder)

        def load():
            return operations.status(), operations.branches()

        self._submit_git(load, self._apply_repository_status, self._show_repository_error)

    def _show_repository_error(self, error):
        self.git_status_label.config(text=f"Repository unavailable: {error}")
        self._visible_changes = []
        self.changed_files.delete(0, "end")
        self.branch_choice.configure(values=[])
        self.staged_summary.config(text="Staged files: unavailable")
        self._set_text(self.diff_text, "Select a valid Git repository to inspect file changes.")

    def _apply_repository_status(self, result):
        status, (branches, current_branch) = result
        upstream = status.upstream or "no upstream configured"
        if status.upstream and status.upstream.endswith(" (gone)"):
            upstream += " · tracking branch unavailable"
        elif status.upstream is not None:
            upstream += f" · {status.ahead or 0} ahead, {status.behind or 0} behind"
        self.git_status_label.config(
            text=f"Branch: {status.branch}\nUpstream: {upstream}\n{status.summary}"
        )
        self._visible_changes = list(status.changes)
        self.changed_files.delete(0, "end")
        for change in self._visible_changes:
            self.changed_files.insert("end", f"[{change.display_status}]  {change.path}")
        staged_paths = [change.path for change in status.changes if change.staged]
        staged_text = "\n".join(staged_paths) if staged_paths else "none"
        self.staged_summary.config(text=f"Staged files:\n{staged_text}")
        values = list(branches)
        self.branch_choice.configure(values=values)
        if current_branch in values:
            self.branch_choice.set(current_branch)
        else:
            self.branch_choice.set("")
        self._set_text(self.diff_text, "Select a changed file to inspect its staged or unstaged diff.")

    def show_selected_diff(self, _event=None):
        if self._git_busy:
            return
        selection = self.changed_files.curselection()
        if not selection:
            return
        folder = self.selected_project()
        if not folder:
            return
        change = self._visible_changes[selection[0]]
        staged = self.diff_mode.get() == "staged"
        self._set_text(self.diff_text, "Loading diff…")
        operations = GitOperations(folder)
        self._submit_git(
            lambda: operations.diff(change, staged=staged),
            lambda diff: self._set_text(self.diff_text, diff),
            lambda error: self._set_text(self.diff_text, f"Diff unavailable: {error}"),
        )

    def _selected_change_paths(self, staged_only=False):
        selection = self.changed_files.curselection()
        changes = [self._visible_changes[index] for index in selection]
        if staged_only:
            changes = [change for change in changes if change.staged]
        return [change.path for change in changes]

    def stage_selected(self):
        folder = self.selected_project()
        paths = self._selected_change_paths()
        if not folder:
            return
        if not paths:
            messagebox.showinfo("Select files", "Select one or more changed files to stage.")
            return
        operations = GitOperations(folder)
        self._submit_git(lambda: operations.stage(paths), lambda _: self._after_git_change(f"Staged {len(paths)} selected file(s)."))

    def unstage_selected(self):
        folder = self.selected_project()
        paths = self._selected_change_paths(staged_only=True)
        if not folder:
            return
        if not paths:
            messagebox.showinfo("Select staged files", "Select one or more files that have staged changes.")
            return
        operations = GitOperations(folder)
        self._submit_git(lambda: operations.unstage(paths), lambda _: self._after_git_change(f"Unstaged {len(paths)} selected file(s)."))

    def show_recent_commits(self):
        folder = self.selected_project()
        if not folder:
            return
        operations = GitOperations(folder)
        self._submit_git(
            operations.recent_commits,
            lambda commits: self._set_text(self.recent_commits, commits or "No commits found."),
        )

    def create_branch(self):
        folder = self.selected_project()
        name = self.new_branch_name.get().strip()
        if not folder:
            return
        operations = GitOperations(folder)
        self._submit_git(
            lambda: operations.create_branch(name),
            lambda _: self._after_git_change(f"Created and switched to branch '{name}'."),
        )

    def request_branch_switch(self):
        folder = self.selected_project()
        target = self.branch_choice.get()
        if not folder:
            return
        operations = GitOperations(folder)

        def check_local_changes(status):
            current = status.branch
            if target == current:
                self.write_output(f"Already on branch '{target}'.")
                return
            if status.changes:
                confirmed = messagebox.askyesno(
                    "Local changes detected",
                    "This repository has staged, unstaged, or untracked files. Git may carry compatible changes "
                    "to the target branch, or refuse the switch if files would conflict. Nothing will be forced or discarded.\n\n"
                    "Attempt the normal, safe branch switch?",
                )
                if not confirmed:
                    self.write_output("Branch switch cancelled. Local files were not changed.")
                    return
            self._do_branch_switch(operations, target)

        self._submit_git(operations.status, check_local_changes)

    def _do_branch_switch(self, operations, target):
        self._submit_git(
            lambda: operations.switch_branch(target),
            lambda _: self._after_git_change(f"Switched to branch '{target}'."),
        )

    def fetch_remote(self):
        folder = self.selected_project()
        if not folder:
            return
        operations = GitOperations(folder)
        self._submit_git(
            operations.fetch,
            lambda message: self._after_git_change(message),
        )

    def commit_staged(self):
        folder = self.selected_project()
        message = self.commit_message.get().strip()
        if not folder:
            return
        operations = GitOperations(folder)
        self._submit_git(
            lambda: operations.commit(message),
            lambda commit_hash: self._after_git_change(f"Commit created: {commit_hash}"),
        )

    def _after_git_change(self, message):
        self.write_output(message)
        self.refresh_git()

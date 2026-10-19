"""Tkinter interface and user actions for Developer Launchpad."""

import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from integrations import find_vscode, open_explorer, open_terminal, open_vscode, run_git
from storage import PROJECTS_FILE, load_projects, save_projects


class DeveloperLaunchpad:
    """Main application window and its project-management actions."""

    def __init__(self, root):
        self.root = root
        self.root.title("Developer Launchpad")
        self.root.geometry("900x590")
        self.root.minsize(760, 500)
        self.projects = load_projects()

        self.selected_path = None
        self._build_ui()
        self.refresh_projects()

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

        project_buttons = ttk.Frame(left)
        project_buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(project_buttons, text="Add project", command=self.add_project).pack(side="left", fill="x", expand=True)
        ttk.Button(project_buttons, text="Remove", command=self.remove_project).pack(side="left", fill="x", expand=True, padx=(6, 0))

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

        git_actions = ttk.LabelFrame(right, text="Git tools", padding=10)
        git_actions.pack(fill="x", pady=(0, 12))
        ttk.Button(git_actions, text="Refresh Git status", command=self.show_git_status).pack(fill="x", pady=3)
        ttk.Button(git_actions, text="View recent commits", command=self.show_recent_commits).pack(fill="x", pady=3)
        ttk.Button(git_actions, text="Stage all changes and commit…", command=self.commit_changes).pack(fill="x", pady=3)

        output_frame = ttk.LabelFrame(right, text="Output", padding=8)
        output_frame.pack(fill="both", expand=True)
        self.output = tk.Text(output_frame, height=8, wrap="word", font=("Consolas", 9), state="disabled")
        output_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=output_scroll.set)
        output_scroll.pack(side="right", fill="y")
        self.output.pack(side="left", fill="both", expand=True)

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

    def show_git_status(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            branch = run_git(folder, ["branch", "--show-current"]) or "(detached HEAD)"
            status = run_git(folder, ["status", "--short", "--branch"])
            self.write_output(f"Git status — {folder.name}\nBranch: {branch}\n\n{status or 'Working tree clean.'}")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror("Git status failed", str(exc))

    def show_recent_commits(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            commits = run_git(folder, ["log", "-5", "--oneline", "--decorate"])
            self.write_output(f"Recent commits — {folder.name}\n\n{commits or 'No commits found.'}")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror("Could not read commits", str(exc))

    def commit_changes(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            status = run_git(folder, ["status", "--short"])
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror("Git status failed", str(exc))
            return

        if not status:
            messagebox.showinfo("Nothing to commit", "Git reports no changed or untracked files.")
            self.write_output("Working tree clean. Nothing to commit.")
            return

        confirm = messagebox.askyesno(
            "Review before staging",
            "The following files are changed or untracked:\n\n"
            f"{status}\n\n"
            "Continue to stage ALL changes in this repository?\n\n"
            "Check carefully for secrets, .env files, credentials, generated files, or unrelated work.",
        )
        if not confirm:
            self.write_output("Commit cancelled. No files were staged.")
            return

        message = simpledialog.askstring("Commit message", "Enter a clear Git commit message:")
        if not message or not message.strip():
            self.write_output("Commit cancelled. No commit message was provided.")
            return

        try:
            run_git(folder, ["add", "--all"])
            run_git(folder, ["commit", "-m", message.strip()])
            new_status = run_git(folder, ["status", "--short", "--branch"])
            latest_commit = run_git(folder, ["log", "-1", "--oneline"])
            self.write_output(f"Commit created successfully.\n\n{latest_commit}\n\n{new_status}")
        except (RuntimeError, subprocess.TimeoutExpired) as exc:
            messagebox.showerror(
                "Commit failed",
                f"{exc}\n\nIf staging succeeded but committing failed, check Git status before trying again.",
            )
            try:
                current_status = run_git(folder, ["status", "--short", "--branch"])
                self.write_output("Commit attempt failed.\n\nCurrent Git status:\n" + current_status)
            except Exception:
                # Keep the original commit error visible if the follow-up status also fails.
                pass

"""Tkinter interface and user actions for Developer Launchpad."""

import json
import queue
import threading
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from command_profiles import create_profile, resolve_working_directory
from command_runner import CommandEvent, CommandExecutionError, run_command
from diagnostics import install_tk_exception_handler, log_error
from git_operations import GitOperations
from integrations import find_vscode, open_explorer, open_terminal, open_vscode
from project_catalog import (
    ALL_CATEGORIES,
    ALL_TAGS,
    add_project_shortcut,
    filter_projects,
    project_folder_available,
    remove_label,
    remove_project_shortcut,
    rename_label,
    set_project_labels,
)
from storage import (
    PROJECTS_FILE,
    load_command_profiles,
    load_projects,
    load_preferences,
    save_command_profiles,
    save_preferences,
    save_projects,
)


class DeveloperLaunchpad:
    """Main application window and its project-management actions."""

    def __init__(self, root):
        self.root = root
        self.root.title("Developer Launchpad")
        self.preferences, preference_warnings = load_preferences()
        self.root.geometry(self.preferences.get("window_geometry", "1120x760"))
        self.root.minsize(760, 540)
        install_tk_exception_handler(self.root)
        self.projects = load_projects()
        self._visible_projects = []
        self._preferences_warning = "\n".join(preference_warnings)

        self.selected_path = None
        self._worker_results = queue.Queue()
        self._git_busy = False
        self._visible_changes = []
        self._git_buttons = []
        self._project_controls = []
        self._command_buttons = []
        self._command_profiles = []
        self._command_events = queue.Queue()
        self._command_running = False
        self._command_stop_requested = False
        self._command_stop_event = None
        self._command_thread = None
        self._closing = False
        self.diff_mode = tk.StringVar(value="unstaged")
        self.search_var = tk.StringVar()
        self.category_filter_var = tk.StringVar(value=ALL_CATEGORIES)
        self.tag_filter_var = tk.StringVar(value=ALL_TAGS)
        self.theme_var = tk.StringVar(value=self.preferences.get("theme", "light"))
        self._build_ui()
        self._apply_theme(self.theme_var.get())
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._bind_shortcuts()
        self.refresh_projects()
        if self._preferences_warning:
            self.write_output(f"Some preferences could not be used:\n{self._preferences_warning}")
        self.root.after(100, self._poll_worker_results)

    def _build_ui(self):
        """Build a resizable project workspace with persistent feature navigation."""
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        menu = tk.Menu(self.root)
        project_menu = tk.Menu(menu, tearoff=False)
        project_menu.add_command(label="Add project…", accelerator="Ctrl+N", command=self.add_project)
        project_menu.add_command(label="Edit project labels…", command=self.edit_project_labels)
        project_menu.add_command(label="Remove project shortcut…", command=self.remove_project)
        project_menu.add_separator()
        project_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self.on_close)
        menu.add_cascade(label="Projects", menu=project_menu)
        actions_menu = tk.Menu(menu, tearoff=False)
        actions_menu.add_command(label="Refresh Git status", accelerator="F5", command=self.refresh_git)
        actions_menu.add_command(label="Open in VS Code", accelerator="Ctrl+Shift+O", command=self.open_vscode)
        actions_menu.add_command(label="Open PowerShell", accelerator="Ctrl+Shift+T", command=self.open_terminal)
        menu.add_cascade(label="Actions", menu=actions_menu)
        self.root.configure(menu=menu)

        header = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        header.pack(fill="x")
        ttk.Label(header, text="Developer Launchpad", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Projects · Git · Development commands", style="Muted.TLabel").pack(side="left", padx=(14, 0), pady=(6, 0))

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True, padx=14, pady=(0, 8))
        left = ttk.Frame(body, padding=10, width=265)
        left.columnconfigure(0, weight=1)
        body.add(left, weight=0)
        right = ttk.Frame(body, padding=(14, 4, 4, 4))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        body.add(right, weight=1)

        ttk.Label(left, text="PROJECTS", style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 7))
        ttk.Label(left, text="Search name or path").grid(row=1, column=0, sticky="w")
        self.search_entry = ttk.Entry(left, textvariable=self.search_var)
        self.search_entry.grid(row=2, column=0, sticky="ew", pady=(2, 7))
        self.search_entry.insert(0, "")
        self.search_entry.bind("<KeyRelease>", self.filter_project_list)
        self.search_entry.bind("<Return>", self._select_first_project)
        ttk.Label(left, text="Category").grid(row=3, column=0, sticky="w")
        self.category_filter = ttk.Combobox(left, textvariable=self.category_filter_var, state="readonly")
        self.category_filter.grid(row=4, column=0, sticky="ew", pady=(2, 6))
        self.category_filter.bind("<<ComboboxSelected>>", self.filter_project_list)
        ttk.Label(left, text="Tag").grid(row=5, column=0, sticky="w")
        self.tag_filter = ttk.Combobox(left, textvariable=self.tag_filter_var, state="readonly")
        self.tag_filter.grid(row=6, column=0, sticky="ew", pady=(2, 8))
        self.tag_filter.bind("<<ComboboxSelected>>", self.filter_project_list)

        project_list_frame = ttk.Frame(left)
        project_list_frame.grid(row=7, column=0, sticky="nsew")
        left.rowconfigure(7, weight=1)
        self.project_list = tk.Listbox(
            project_list_frame, selectmode=tk.SINGLE, exportselection=False,
            activestyle="dotbox", height=12, borderwidth=1, relief="solid",
        )
        list_scroll = ttk.Scrollbar(project_list_frame, orient="vertical", command=self.project_list.yview)
        self.project_list.configure(yscrollcommand=list_scroll.set)
        self.project_list.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")
        self.project_list.bind("<<ListboxSelect>>", self.on_select)
        self.project_list.bind("<Double-Button-1>", lambda _event: self.open_vscode())
        self._project_controls.extend([self.project_list, self.search_entry, self.category_filter, self.tag_filter])

        self.empty_projects_label = ttk.Label(left, text="No projects match these filters.", style="Muted.TLabel", wraplength=230)
        self.empty_projects_label.grid(row=8, column=0, sticky="w", pady=(5, 0))
        project_buttons = ttk.Frame(left)
        project_buttons.grid(row=9, column=0, sticky="ew", pady=(8, 0))
        self.add_project_button = ttk.Button(project_buttons, text="Add", command=self.add_project)
        self.add_project_button.pack(side="left", fill="x", expand=True)
        self.edit_labels_button = ttk.Button(project_buttons, text="Labels", command=self.edit_project_labels)
        self.edit_labels_button.pack(side="left", fill="x", expand=True, padx=4)
        self.remove_project_button = ttk.Button(project_buttons, text="Remove", command=self.remove_project)
        self.remove_project_button.pack(side="left", fill="x", expand=True)
        self.manage_labels_button = ttk.Button(left, text="Manage categories and tags…", command=self.manage_labels)
        self.manage_labels_button.grid(row=10, column=0, sticky="ew", pady=(6, 0))
        self._project_controls.extend([self.add_project_button, self.edit_labels_button, self.remove_project_button, self.manage_labels_button])

        heading = ttk.Frame(right)
        heading.grid(row=0, column=0, sticky="ew")
        heading.columnconfigure(0, weight=1)
        self.project_title = ttk.Label(heading, text="Select a project", style="ProjectTitle.TLabel")
        self.project_title.grid(row=0, column=0, sticky="w")
        self.project_path_label = ttk.Label(heading, text="Add an existing folder or search your saved projects.", style="Muted.TLabel", wraplength=650)
        self.project_path_label.grid(row=1, column=0, sticky="ew", pady=(2, 7))
        open_actions = ttk.Frame(heading)
        open_actions.grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Button(open_actions, text="Open in VS Code", command=self.open_vscode).pack(side="left")
        ttk.Button(open_actions, text="PowerShell", command=self.open_terminal).pack(side="left", padx=5)
        ttk.Button(open_actions, text="File Explorer", command=self.open_explorer).pack(side="left")

        self.workspace_tabs = ttk.Notebook(right)
        self.workspace_tabs.grid(row=2, column=0, sticky="nsew")
        dashboard = ttk.Frame(self.workspace_tabs, padding=14)
        self.workspace_tabs.add(dashboard, text="Dashboard")
        dashboard.columnconfigure(0, weight=1)
        ttk.Label(dashboard, text="Project overview", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(dashboard, text="Refresh Git status when you want an up-to-date snapshot. Recent commits remain on-demand.", style="Muted.TLabel", wraplength=700).grid(row=1, column=0, sticky="w", pady=(4, 12))
        summary = ttk.LabelFrame(dashboard, text="Repository status", padding=10)
        summary.grid(row=2, column=0, sticky="ew")
        summary.columnconfigure(0, weight=1)
        self.dashboard_git_label = ttk.Label(summary, text="Select a project to load repository status.", justify="left", wraplength=700)
        self.dashboard_git_label.grid(row=0, column=0, sticky="ew")
        self.dashboard_refresh_button = ttk.Button(summary, text="Refresh status (F5)", command=self.refresh_git)
        self.dashboard_refresh_button.grid(row=1, column=0, sticky="w", pady=(8, 0))
        self._git_buttons.append(self.dashboard_refresh_button)
        self.dashboard_commands_label = ttk.Label(dashboard, text="Configured commands: 0", style="Muted.TLabel")
        self.dashboard_commands_label.grid(row=3, column=0, sticky="w", pady=(12, 0))
        ttk.Label(dashboard, text="Choose Git or Dev Commands above for detailed workflows.", style="Muted.TLabel").grid(row=4, column=0, sticky="w", pady=(7, 0))

        git_page = ttk.Frame(self.workspace_tabs, padding=4)
        self.workspace_tabs.add(git_page, text="Git")
        git_tabs = ttk.Notebook(git_page)
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
        ttk.Label(overview, text="Recent commits", style="Section.TLabel").pack(anchor="w", pady=(14, 4))
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
        diff_y.pack(side="right", fill="y")
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

        self._build_command_page()
        self._build_settings_page()
        self.output = tk.Text(right, height=2, wrap="word", font=("Consolas", 9), state="disabled")
        self.output.grid(row=3, column=0, sticky="ew", pady=(7, 0))
        ttk.Label(self.root, text=f"Project data: {PROJECTS_FILE}", padding=(14, 4), style="Muted.TLabel").pack(fill="x")

    def _build_command_page(self):
        commands_tab = ttk.Frame(self.workspace_tabs, padding=10)
        self.workspace_tabs.add(commands_tab, text="Dev Commands")
        commands_tab.columnconfigure(0, weight=1)
        commands_tab.columnconfigure(1, weight=2)
        commands_tab.rowconfigure(1, weight=1)
        commands_tab.rowconfigure(2, weight=2)
        ttk.Label(commands_tab, text="Commands run only when you press Run. Configure commands only for projects you trust.", style="Muted.TLabel", wraplength=720).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        command_list_frame = ttk.LabelFrame(commands_tab, text="Project commands", padding=6)
        command_list_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        self.command_list = tk.Listbox(command_list_frame, exportselection=False, font=("Segoe UI", 9))
        command_scroll = ttk.Scrollbar(command_list_frame, orient="vertical", command=self.command_list.yview)
        self.command_list.configure(yscrollcommand=command_scroll.set)
        self.command_list.pack(side="left", fill="both", expand=True)
        command_scroll.pack(side="right", fill="y")
        self.command_list.bind("<<ListboxSelect>>", self.on_command_select)
        command_details = ttk.LabelFrame(commands_tab, text="Command details", padding=8)
        command_details.grid(row=1, column=1, sticky="nsew")
        self.command_details_label = ttk.Label(command_details, text="Select or add a command profile.", wraplength=620, justify="left")
        self.command_details_label.pack(fill="x", anchor="nw")
        command_actions = ttk.Frame(command_details)
        command_actions.pack(fill="x", pady=(8, 6))
        for title, callback in (("Add", self.add_command_profile), ("Edit", self.edit_command_profile), ("Delete", self.delete_command_profile), ("Run", self.run_selected_command)):
            button = ttk.Button(command_actions, text=title, command=callback)
            button.pack(side="left", padx=(0, 5))
            self._command_buttons.append(button)
        self.command_status = ttk.Label(command_details, text="No command is running.", wraplength=620)
        self.command_status.pack(fill="x", anchor="w", pady=(3, 5))
        output_controls = ttk.Frame(command_details)
        output_controls.pack(fill="x")
        self.stop_command_button = ttk.Button(output_controls, text="Stop", command=self.stop_running_command, state="disabled")
        self.stop_command_button.pack(side="left")
        ttk.Button(output_controls, text="Clear output", command=self.clear_command_output).pack(side="left", padx=(6, 0))
        output_frame = ttk.LabelFrame(commands_tab, text="Command output", padding=6)
        output_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(8, 0))
        output_frame.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        self.command_output = tk.Text(output_frame, height=9, wrap="word", font=("Consolas", 9), state="disabled")
        output_scroll = ttk.Scrollbar(output_frame, orient="vertical", command=self.command_output.yview)
        self.command_output.configure(yscrollcommand=output_scroll.set)
        self.command_output.grid(row=0, column=0, sticky="nsew")
        output_scroll.grid(row=0, column=1, sticky="ns")
        self.command_output.tag_configure("stderr", foreground="#a1260d")

    def _build_settings_page(self):
        settings = ttk.Frame(self.workspace_tabs, padding=16)
        self.workspace_tabs.add(settings, text="Settings")
        settings.columnconfigure(1, weight=1)
        ttk.Label(settings, text="Application preferences", style="Section.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(settings, text="Theme").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=5)
        theme_choice = ttk.Combobox(settings, textvariable=self.theme_var, values=("light", "dark"), state="readonly", width=18)
        theme_choice.grid(row=1, column=1, sticky="w", pady=5)
        ttk.Button(settings, text="Apply and save", command=self.save_theme_preference).grid(row=2, column=1, sticky="w", pady=(4, 12))
        ttk.Label(settings, text="Preferences and project shortcuts are stored separately in your user profile. No credentials are stored.", style="Muted.TLabel", wraplength=720).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(settings, text="Keyboard shortcuts", style="Section.TLabel").grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 5))
        shortcuts = "Ctrl+K  Search projects    Ctrl+N  Add project    F5  Refresh Git status\nCtrl+Shift+O  Open in VS Code    Ctrl+Shift+T  Open PowerShell    Ctrl+1–4  Navigate    Ctrl+Q  Close"
        ttk.Label(settings, text=shortcuts, justify="left", wraplength=760).grid(row=5, column=0, columnspan=2, sticky="w")
        ttk.Label(settings, text="About and diagnostics", style="Section.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(18, 5))
        ttk.Label(settings, text="Developer Launchpad · Version 4 · Python + Tkinter · local-only diagnostics", style="Muted.TLabel").grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Button(settings, text="View diagnostic log", command=self.show_diagnostics).grid(row=8, column=0, sticky="w")
        ttk.Label(settings, text="Log file: " + str(Path.home() / ".developer_launchpad" / "developer_launchpad.log"), style="Muted.TLabel", wraplength=720).grid(row=9, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def write_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")

    def refresh_projects(self, select_path=None):
        if select_path:
            self.selected_path = select_path
        project_categories = [
            project.get("category") for project in self.projects
            if isinstance(project.get("category"), str) and project.get("category").strip()
        ]
        categories = list(dict.fromkeys([*self.preferences.get("categories", []), *project_categories]))
        tags = list(dict.fromkeys([*self.preferences.get("tags", []), *[
            tag for project in self.projects
            for tag in (project.get("tags", []) if isinstance(project.get("tags", []), list) else [])
            if isinstance(tag, str)
        ]]))
        category_values = [ALL_CATEGORIES, *categories]
        tag_values = [ALL_TAGS, *tags]
        self.category_filter.configure(values=category_values)
        self.tag_filter.configure(values=tag_values)
        if self.category_filter_var.get() not in category_values:
            self.category_filter_var.set(ALL_CATEGORIES)
        if self.tag_filter_var.get() not in tag_values:
            self.tag_filter_var.set(ALL_TAGS)
        self.filter_project_list()

    def filter_project_list(self, _event=None):
        """Refresh visible shortcuts without rerunning Git for an unchanged selection."""
        previous_path = self.selected_path
        self._visible_projects = filter_projects(
            self.projects,
            self.search_var.get(),
            self.category_filter_var.get(),
            self.tag_filter_var.get(),
        )
        self.project_list.delete(0, "end")
        for project in self._visible_projects:
            category = project.get("category")
            suffix = f"  · {category}" if category else ""
            self.project_list.insert("end", f"{project.get('name', 'Unnamed project')}{suffix}")
        self.empty_projects_label.config(
            text="No projects have been added yet. Choose Add to save a folder shortcut."
            if not self.projects else "No projects match these search and label filters."
        )
        if not self._visible_projects:
            self.selected_path = None
            self._show_no_project_selected()
            return
        selected_index = next(
            (index for index, project in enumerate(self._visible_projects) if project.get("path") == previous_path),
            0,
        )
        self.project_list.selection_clear(0, "end")
        self.project_list.selection_set(selected_index)
        self.project_list.activate(selected_index)
        selected = self._visible_projects[selected_index]
        self._update_project_path_label(selected)
        if selected.get("path") != previous_path:
            self.on_select()

    def _select_first_project(self, _event=None):
        if self._visible_projects:
            self.project_list.selection_clear(0, "end")
            self.project_list.selection_set(0)
            self.project_list.activate(0)
            self.on_select()
        return "break"

    def _show_no_project_selected(self):
        self.project_title.config(text="No project selected")
        self.project_path_label.config(text="Add a folder or adjust the search and filters.")
        self.dashboard_git_label.config(text="Repository status is unavailable until you select a project.")
        self.dashboard_commands_label.config(text="Configured commands: —")
        self.git_status_label.config(text="Select a project to inspect its Git repository.")
        self._visible_changes = []
        self.changed_files.delete(0, "end")
        self.branch_choice.configure(values=[])
        self.branch_choice.set("")
        self.staged_summary.config(text="Staged files: none")
        self._set_text(self.diff_text, "Select a project to inspect Git changes.")
        self._set_text(self.recent_commits, "Select a project to load recent commits.")
        self.refresh_command_profiles(None)
        self.command_status.config(text="No command is running.")
        self.write_output("No project selected.")

    def selected_project(self):
        project = self._selected_project_record()
        if not project:
            messagebox.showinfo("Select a project", "Please select a project first.")
            return None
        folder = Path(project["path"])
        if not project_folder_available(project):
            messagebox.showerror("Folder not found", f"This project folder no longer exists:\n{folder}")
            log_error("Project folder unavailable", FileNotFoundError(folder))
            return None
        return folder

    def on_select(self, _event=None):
        selection = self.project_list.curselection()
        if not selection:
            return
        project = self._visible_projects[selection[0]]
        self.selected_path = project["path"]
        self.project_title.config(text=project["name"])
        self._update_project_path_label(project)
        exists = project_folder_available(project)
        self.write_output(f"Selected project: {project['name']}\n\nChoose a workspace section above.")
        self.refresh_command_profiles(project)
        self.dashboard_commands_label.config(text=f"Configured commands: {len(self._command_profiles)}")
        if exists:
            self.dashboard_git_label.config(text="Loading repository status…")
            self.refresh_git()
        else:
            missing = "Project folder is unavailable. Update its path or remove this shortcut."
            self.git_status_label.config(text=missing)
            self.dashboard_git_label.config(text=missing)
            self._visible_changes = []
            self.changed_files.delete(0, "end")
            self.branch_choice.configure(values=[])
            self.staged_summary.config(text="Staged files: unavailable")
            self._set_text(self.diff_text, missing)

    def _update_project_path_label(self, project):
        labels = []
        category = project.get("category")
        if isinstance(category, str) and category.strip():
            labels.append(category.strip())
        tags = project.get("tags", [])
        if isinstance(tags, list):
            labels.extend(tag for tag in tags if isinstance(tag, str))
        label_text = f"\nLabels: {', '.join(labels)}" if labels else ""
        self.project_path_label.config(text=f"{project.get('path', '(no path)')}{label_text}")

    def add_project(self):
        folder = filedialog.askdirectory(title="Choose a project folder")
        if not folder:
            return
        path = str(Path(folder).resolve())
        suggested_name = Path(path).name or path
        name = simpledialog.askstring("Project name", "Give this project a short name:", initialvalue=suggested_name)
        if name is None:
            return
        try:
            project = add_project_shortcut(self.projects, name, path)
        except ValueError as exc:
            messagebox.showinfo("Project not added", str(exc))
            return
        self.projects.append(project)
        if not self._persist_projects():
            self.projects.remove(project)
            return
        self.refresh_projects(select_path=path)

    def remove_project(self):
        project = self._selected_project_record()
        if not project:
            messagebox.showinfo("Select a project", "Choose a project to remove.")
            return
        if not messagebox.askyesno(
            "Remove project",
            f"Remove “{project['name']}” from this app?\n\n"
            "This only removes the saved shortcut. It does not delete your project files.",
        ):
            return
        previous = self.projects
        self.projects = remove_project_shortcut(self.projects, project["path"])
        if not self._persist_projects():
            self.projects = previous
            return
        self.selected_path = None
        self.refresh_projects()

    def _persist_projects(self):
        try:
            save_projects(self.projects)
            return True
        except OSError as exc:
            log_error("Saving project shortcuts", exc)
            messagebox.showerror("Could not save projects", f"Project changes could not be saved.\n\n{exc}")
            return False

    def _persist_preferences(self):
        try:
            save_preferences(self.preferences)
            return True
        except OSError as exc:
            log_error("Saving application preferences", exc)
            messagebox.showerror("Could not save preferences", f"Preference changes could not be saved.\n\n{exc}")
            return False

    def edit_project_labels(self):
        """Edit optional category/tags without changing the underlying folder."""
        project = self._selected_project_record()
        if project is None:
            messagebox.showinfo("Select a project", "Select a project before editing its labels.")
            return
        category = simpledialog.askstring(
            "Project category",
            "Category (leave blank for uncategorized):",
            initialvalue=project.get("category", ""),
            parent=self.root,
        )
        if category is None:
            return
        raw_tags = simpledialog.askstring(
            "Project tags",
            "Tags separated by commas (leave blank for none):",
            initialvalue=", ".join(project.get("tags", [])) if isinstance(project.get("tags", []), list) else "",
            parent=self.root,
        )
        if raw_tags is None:
            return
        tags = [part.strip() for part in raw_tags.split(",")]
        set_project_labels(project, category, tags)
        for value, key in ((project["category"], "categories"), *[(tag, "tags") for tag in project["tags"]]):
            if value and value.casefold() not in {label.casefold() for label in self.preferences.get(key, [])}:
                self.preferences.setdefault(key, []).append(value)
        if self._persist_projects() and self._persist_preferences():
            self.refresh_projects(select_path=project["path"])

    def manage_labels(self):
        """Create, rename, or remove shared categories and tags."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Manage categories and tags")
        dialog.geometry("430x410")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(2, weight=1)
        kind = tk.StringVar(dialog, value="categories")
        ttk.Label(dialog, text="Choose which labels to manage:").grid(row=0, column=0, sticky="w", padx=12, pady=(12, 4))
        choices = ttk.Frame(dialog)
        choices.grid(row=1, column=0, sticky="ew", padx=12)
        label_list = tk.Listbox(dialog, exportselection=False)
        label_list.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        self._apply_native_widget_theme(label_list)
        editor = ttk.Entry(dialog)
        editor.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))

        def labels_for_kind():
            return self.preferences.setdefault(kind.get(), [])

        def redraw():
            label_list.delete(0, "end")
            for label in labels_for_kind():
                label_list.insert("end", label)

        def add_label():
            value = editor.get().strip()
            if not value:
                return
            labels = labels_for_kind()
            if value.casefold() in {label.casefold() for label in labels}:
                messagebox.showinfo("Already exists", "That label is already available.", parent=dialog)
                return
            labels.append(value)
            editor.delete(0, "end")
            self._persist_preferences()
            self.refresh_projects()
            redraw()

        def rename_selected():
            selection = label_list.curselection()
            new_value = editor.get().strip()
            if not selection or not new_value:
                messagebox.showinfo("Rename label", "Select a label and enter its new name.", parent=dialog)
                return
            old_value = labels_for_kind()[selection[0]]
            field = "category" if kind.get() == "categories" else "tags"
            try:
                labels = rename_label(self.projects, labels_for_kind(), old_value, new_value, field)
            except ValueError as exc:
                messagebox.showerror("Could not rename label", str(exc), parent=dialog)
                return
            self.preferences[kind.get()] = labels
            self._persist_preferences()
            self._persist_projects()
            self.refresh_projects()
            redraw()

        def delete_selected():
            selection = label_list.curselection()
            if not selection:
                return
            old_value = labels_for_kind()[selection[0]]
            if not messagebox.askyesno("Remove label", f"Remove label '{old_value}' from the catalog and matching projects?", parent=dialog):
                return
            field = "category" if kind.get() == "categories" else "tags"
            self.preferences[kind.get()] = remove_label(self.projects, labels_for_kind(), old_value, field)
            self._persist_preferences()
            self._persist_projects()
            self.refresh_projects()
            redraw()

        ttk.Radiobutton(choices, text="Categories", variable=kind, value="categories", command=redraw).pack(side="left")
        ttk.Radiobutton(choices, text="Tags", variable=kind, value="tags", command=redraw).pack(side="left", padx=10)
        actions = ttk.Frame(dialog)
        actions.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 12))
        ttk.Button(actions, text="Add", command=add_label).pack(side="left")
        ttk.Button(actions, text="Rename to text above", command=rename_selected).pack(side="left", padx=5)
        ttk.Button(actions, text="Remove selected", command=delete_selected).pack(side="left")
        ttk.Button(actions, text="Done", command=dialog.destroy).pack(side="right")
        def select_label(_event=None):
            selection = label_list.curselection()
            if selection:
                editor.delete(0, "end")
                editor.insert(0, label_list.get(selection[0]))

        label_list.bind("<<ListboxSelect>>", select_label)
        redraw()

    def save_theme_preference(self):
        theme = self.theme_var.get()
        if theme not in ("light", "dark"):
            messagebox.showerror("Invalid theme", "Choose light or dark.")
            return
        self._apply_theme(theme)
        self.preferences["theme"] = theme
        if self._persist_preferences():
            self.write_output(f"Saved {theme} theme preference.")

    def _apply_theme(self, theme):
        """Apply a restrained palette while keeping native Tk focus behavior."""
        style = ttk.Style(self.root)
        style.theme_use("clam")
        if theme == "dark":
            colors = {"background": "#20242b", "surface": "#292f38", "text": "#e7eaf0", "muted": "#aab3c0", "field": "#171a20", "accent": "#4d8bd8", "select": "#315f95"}
        else:
            colors = {"background": "#f3f5f8", "surface": "#ffffff", "text": "#202938", "muted": "#5e6b7c", "field": "#ffffff", "accent": "#2864a8", "select": "#c9def5"}
        self._theme_colors = colors
        style.configure(".", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 9), focuscolor=colors["accent"])
        style.configure("TFrame", background=colors["background"])
        style.configure("TLabelframe", background=colors["background"], foreground=colors["text"])
        style.configure("TLabelframe.Label", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 9, "bold"))
        style.configure("TLabel", background=colors["background"], foreground=colors["text"])
        style.configure("Muted.TLabel", background=colors["background"], foreground=colors["muted"])
        style.configure("Title.TLabel", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 17, "bold"))
        style.configure("ProjectTitle.TLabel", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 13, "bold"))
        style.configure("Section.TLabel", background=colors["background"], foreground=colors["text"], font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=(9, 5), focuscolor=colors["accent"])
        style.map("TButton", foreground=[("disabled", colors["muted"])])
        style.configure("TNotebook", background=colors["background"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(11, 7), background=colors["surface"], foreground=colors["text"])
        style.map("TNotebook.Tab", background=[("selected", colors["background"])], foreground=[("selected", colors["accent"])])
        style.configure("TEntry", fieldbackground=colors["field"], foreground=colors["text"])
        style.configure("TCombobox", fieldbackground=colors["field"], foreground=colors["text"])
        self.root.configure(background=colors["background"])
        for widget in (self.project_list, self.changed_files, self.diff_text, self.recent_commits, self.command_list, self.command_output, self.output):
            self._apply_native_widget_theme(widget)
        self.command_output.tag_configure("stderr", foreground="#ff9b85" if theme == "dark" else "#a1260d")

    def _apply_native_widget_theme(self, widget):
        """Style classic Tk text/list controls to match the selected ttk palette."""
        colors = getattr(self, "_theme_colors", None)
        if not colors:
            return
        try:
            widget.configure(
                background=colors["field"], foreground=colors["text"],
                insertbackground=colors["text"], selectbackground=colors["select"],
                selectforeground=colors["text"], highlightthickness=1,
                highlightbackground=colors["muted"], highlightcolor=colors["accent"],
            )
        except tk.TclError:
            pass

    def _bind_shortcuts(self):
        self.root.bind_all("<Control-k>", self._shortcut_search)
        self.root.bind_all("<Control-n>", self._shortcut_add_project)
        self.root.bind_all("<F5>", self._shortcut_refresh)
        self.root.bind_all("<Control-Shift-o>", self._shortcut_vscode)
        self.root.bind_all("<Control-Shift-t>", self._shortcut_terminal)
        self.root.bind_all("<Control-q>", self._shortcut_close)
        for number in range(1, 5):
            self.root.bind_all(f"<Control-Key-{number}>", lambda event, index=number - 1: self._navigate_shortcut(index, event))

    @staticmethod
    def _is_editing_widget(widget):
        return isinstance(widget, (tk.Entry, tk.Text, ttk.Entry, ttk.Combobox, ttk.Spinbox))

    def _shortcut_search(self, event):
        if self._is_editing_widget(event.widget):
            return
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")
        return "break"

    def _shortcut_add_project(self, event):
        if self._is_editing_widget(event.widget):
            return
        self.add_project()
        return "break"

    def _shortcut_refresh(self, _event):
        self.refresh_git()
        return "break"

    def _shortcut_vscode(self, event):
        if self._is_editing_widget(event.widget):
            return
        self.open_vscode()
        return "break"

    def _shortcut_terminal(self, event):
        if self._is_editing_widget(event.widget):
            return
        self.open_terminal()
        return "break"

    def _shortcut_close(self, event):
        if self._is_editing_widget(event.widget):
            return
        self.on_close()
        return "break"

    def _navigate_shortcut(self, index, event=None):
        if event and self._is_editing_widget(event.widget):
            return
        self.workspace_tabs.select(index)
        return "break"

    def show_diagnostics(self):
        log_path = Path.home() / ".developer_launchpad" / "developer_launchpad.log"
        try:
            contents = log_path.read_text(encoding="utf-8") if log_path.exists() else "No diagnostic entries have been recorded."
        except OSError as exc:
            log_error("Reading diagnostic log", exc)
            contents = f"Could not read local diagnostic log: {exc}"
        window = tk.Toplevel(self.root)
        window.title("Developer Launchpad diagnostics")
        window.geometry("760x440")
        viewer = tk.Text(window, wrap="word", font=("Consolas", 9))
        self._apply_native_widget_theme(viewer)
        scroll = ttk.Scrollbar(window, orient="vertical", command=viewer.yview)
        viewer.configure(yscrollcommand=scroll.set)
        viewer.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", padx=(0, 10), pady=10)
        viewer.insert("1.0", contents)
        viewer.configure(state="disabled")

    def _save_window_preferences(self):
        try:
            self.preferences["window_geometry"] = self.root.geometry()
            save_preferences(self.preferences)
        except OSError as exc:
            log_error("Saving window preferences", exc)

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
            log_error("Opening project in VS Code", exc)
            messagebox.showerror("Could not open VS Code", str(exc))

    def open_terminal(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            open_terminal(folder)
            self.write_output(f"Opened PowerShell in:\n{folder}")
        except OSError as exc:
            log_error("Opening project terminal", exc)
            messagebox.showerror("Could not open PowerShell", str(exc))

    def open_explorer(self):
        folder = self.selected_project()
        if not folder:
            return
        try:
            open_explorer(folder)
        except OSError as exc:
            log_error("Opening project in File Explorer", exc)
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
        self._sync_busy_controls()

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
                self._sync_busy_controls()
                if error is not None:
                    log_error("Git operation failed", error)
                    if on_error:
                        on_error(error)
                    else:
                        self.write_output(f"Git operation failed: {error}")
                        messagebox.showerror("Git operation failed", str(error))
                else:
                    on_success(result)
        except queue.Empty:
            pass
        self._poll_command_events()
        self.root.after(100, self._poll_worker_results)

    def _sync_busy_controls(self):
        project_locked = self._git_busy or self._command_running
        for control in self._project_controls:
            control.configure(state="disabled" if project_locked else "normal")
        for button in self._git_buttons:
            button.configure(state="disabled" if self._git_busy else "normal")
        for button in self._command_buttons:
            button.configure(state="disabled" if self._command_running else "normal")
        self.stop_command_button.configure(
            state="normal" if self._command_running and not self._command_stop_requested else "disabled"
        )
        if self._git_busy:
            for button in self._command_buttons:
                button.configure(state="disabled")

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
        self.dashboard_git_label.config(text=f"Repository unavailable: {error}")
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
        self.dashboard_git_label.config(
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

    def refresh_command_profiles(self, project=None):
        """Load the selected project's saved profiles without running any."""
        if project is None:
            selection = self.project_list.curselection()
            if not selection:
                self._command_profiles = []
                self.command_list.delete(0, "end")
                self.command_details_label.config(text="Select a project to manage its commands.")
                return
            project = self.projects[selection[0]]

        self._command_profiles, warnings = load_command_profiles(project)
        self.command_list.delete(0, "end")
        for profile in self._command_profiles:
            kind = "long-running" if profile.long_running else "task"
            self.command_list.insert("end", f"{profile.name}  [{kind}]")
        if warnings:
            self.command_status.config(text=f"{len(warnings)} invalid saved profile(s) skipped; original data preserved.")
        elif not self._command_running:
            self.command_status.config(text="No command is running.")
        if self._command_profiles:
            self.command_list.selection_set(0)
            self.on_command_select()
        else:
            self.command_details_label.config(text="No command profiles configured for this project.")

    def on_command_select(self, _event=None):
        selection = self.command_list.curselection()
        if not selection:
            return
        profile = self._command_profiles[selection[0]]
        project = self._selected_project_record()
        if not project:
            return
        try:
            effective_directory = resolve_working_directory(project["path"], profile.working_directory)
        except ValueError as exc:
            effective_directory = f"Invalid: {exc}"
        arguments = json.dumps(list(profile.arguments), ensure_ascii=False)
        kind = "Long-running process" if profile.long_running else "Task"
        self.command_details_label.config(
            text=(
                f"{kind}: {profile.name}\n"
                f"Executable: {profile.executable}\n"
                f"Arguments: {arguments}\n"
                f"Working directory: {effective_directory}\n"
                f"Description: {profile.description or '(none)'}"
            )
        )

    def _selected_command_profile(self):
        selection = self.command_list.curselection()
        if not selection:
            messagebox.showinfo("Select a command", "Select a command profile first.")
            return None
        return self._command_profiles[selection[0]]

    def _selected_project_record(self):
        for project in self.projects:
            if project.get("path") == self.selected_path:
                return project
        return None

    def _save_current_command_profiles(self):
        project = self._selected_project_record()
        if project is None:
            messagebox.showerror("Project unavailable", "Select a saved project before editing command profiles.")
            return False
        missing = object()
        old_commands = deepcopy(project["commands"]) if "commands" in project else missing
        old_backup = deepcopy(project["commands_invalid_backup"]) if "commands_invalid_backup" in project else missing
        try:
            save_command_profiles(project, self._command_profiles)
            save_projects(self.projects)
        except OSError as exc:
            if old_commands is missing:
                project.pop("commands", None)
            else:
                project["commands"] = old_commands
            if old_backup is missing:
                project.pop("commands_invalid_backup", None)
            else:
                project["commands_invalid_backup"] = old_backup
            log_error("Saving development command profiles", exc)
            messagebox.showerror("Could not save command profiles", str(exc))
            return False
        self.refresh_command_profiles(project)
        return True

    def _command_profile_dialog(self, initial=None):
        """Show the editor; argument lines become separate argv entries."""
        project = self._selected_project_record()
        if project is None:
            messagebox.showinfo("Select a project", "Select a project before configuring commands.")
            return None
        project_root = Path(project["path"]).resolve()
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit command profile" if initial else "Add command profile")
        dialog.geometry("680x570")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        result = []

        def add_label(row, text):
            ttk.Label(dialog, text=text).grid(row=row, column=0, sticky="nw", padx=(12, 10), pady=6)

        add_label(0, "Display name")
        name_entry = ttk.Entry(dialog)
        name_entry.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=6)
        name_entry.insert(0, initial.name if initial else "")

        add_label(1, "Executable")
        executable_entry = ttk.Entry(dialog)
        executable_entry.grid(row=1, column=1, sticky="ew", padx=(0, 12), pady=6)
        executable_entry.insert(0, initial.executable if initial else "")

        add_label(2, "Arguments (one per line)")
        argument_frame = ttk.Frame(dialog)
        argument_frame.grid(row=2, column=1, sticky="nsew", padx=(0, 12), pady=6)
        arguments_text = tk.Text(argument_frame, height=7, wrap="word")
        self._apply_native_widget_theme(arguments_text)
        argument_scroll = ttk.Scrollbar(argument_frame, orient="vertical", command=arguments_text.yview)
        arguments_text.configure(yscrollcommand=argument_scroll.set)
        arguments_text.pack(side="left", fill="both", expand=True)
        argument_scroll.pack(side="right", fill="y")
        if initial:
            arguments_text.insert("1.0", "\n".join(initial.arguments))

        add_label(3, "Working directory")
        directory_frame = ttk.Frame(dialog)
        directory_frame.grid(row=3, column=1, sticky="ew", padx=(0, 12), pady=6)
        directory_entry = ttk.Entry(directory_frame)
        directory_entry.pack(side="left", fill="x", expand=True)
        directory_entry.insert(0, initial.working_directory if initial else ".")

        def browse_directory():
            try:
                start = resolve_working_directory(project_root, directory_entry.get())
            except ValueError:
                start = project_root
            selected = filedialog.askdirectory(parent=dialog, initialdir=str(start), title="Choose project working directory")
            if not selected:
                return
            try:
                relative = Path(selected).resolve().relative_to(project_root)
            except ValueError:
                messagebox.showerror("Outside project", "Choose a working directory inside the selected project.", parent=dialog)
                return
            directory_entry.delete(0, "end")
            directory_entry.insert(0, relative.as_posix() if relative.parts else ".")

        ttk.Button(directory_frame, text="Browse…", command=browse_directory).pack(side="left", padx=(6, 0))

        add_label(4, "Description")
        description_entry = ttk.Entry(dialog)
        description_entry.grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=6)
        description_entry.insert(0, initial.description if initial else "")

        long_running_var = tk.BooleanVar(dialog, value=initial.long_running if initial else False)
        ttk.Checkbutton(dialog, text="Long-running process (for example, a development server)", variable=long_running_var).grid(
            row=5, column=1, sticky="w", padx=(0, 12), pady=6
        )
        ttk.Label(
            dialog,
            text="Arguments are passed directly to the executable without a shell. Each non-empty line is one argument.",
            wraplength=620,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=(8, 4))

        def save_dialog():
            try:
                profile = create_profile(
                    name_entry.get(),
                    executable_entry.get(),
                    arguments_text.get("1.0", "end-1c"),
                    directory_entry.get(),
                    long_running_var.get(),
                    description_entry.get(),
                    initial.profile_id if initial else None,
                )
                resolve_working_directory(project_root, profile.working_directory)
            except ValueError as exc:
                messagebox.showerror("Invalid command profile", str(exc), parent=dialog)
                return
            result.append(profile)
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=7, column=0, columnspan=2, sticky="e", padx=12, pady=12)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Save profile", command=save_dialog).pack(side="right")
        name_entry.focus_set()
        self.root.wait_window(dialog)
        return result[0] if result else None

    def _has_duplicate_command_name(self, candidate, excluding_id=None):
        return any(
            profile.profile_id != excluding_id and profile.name.casefold() == candidate.name.casefold()
            for profile in self._command_profiles
        )

    def add_command_profile(self):
        if self._command_running:
            return
        profile = self._command_profile_dialog()
        if profile is None:
            return
        if self._has_duplicate_command_name(profile):
            messagebox.showerror("Name already used", "Choose a unique command name for this project.")
            return
        self._command_profiles.append(profile)
        if not self._save_current_command_profiles():
            self._command_profiles.remove(profile)
            return
        self.write_output(f"Saved command profile: {profile.name}. It will run only when you press Run.")

    def edit_command_profile(self):
        if self._command_running:
            return
        initial = self._selected_command_profile()
        if initial is None:
            return
        profile = self._command_profile_dialog(initial)
        if profile is None:
            return
        if self._has_duplicate_command_name(profile, excluding_id=initial.profile_id):
            messagebox.showerror("Name already used", "Choose a unique command name for this project.")
            return
        previous_profiles = self._command_profiles
        self._command_profiles = [
            profile if existing.profile_id == initial.profile_id else existing
            for existing in self._command_profiles
        ]
        if not self._save_current_command_profiles():
            self._command_profiles = previous_profiles
            return
        self.write_output(f"Updated command profile: {profile.name}.")

    def delete_command_profile(self):
        if self._command_running:
            return
        profile = self._selected_command_profile()
        if profile is None:
            return
        if not messagebox.askyesno("Delete command profile", f"Remove '{profile.name}' from this project? The command will not be run."):
            return
        previous_profiles = self._command_profiles
        self._command_profiles = [item for item in self._command_profiles if item.profile_id != profile.profile_id]
        if not self._save_current_command_profiles():
            self._command_profiles = previous_profiles
            return
        self.write_output(f"Deleted command profile: {profile.name}.")

    def run_selected_command(self):
        if self._command_running:
            return
        profile = self._selected_command_profile()
        project = self._selected_project_record()
        if profile is None or project is None:
            return
        try:
            working_directory = resolve_working_directory(project["path"], profile.working_directory)
        except ValueError as exc:
            messagebox.showerror("Invalid working directory", str(exc))
            return

        arguments = json.dumps(list(profile.arguments), ensure_ascii=False)
        self._append_command_output(
            f"\n--- Run requested ---\nExecutable: {profile.executable}\nArguments: {arguments}\n"
            f"Working directory: {working_directory}\n"
        )
        self.command_status.config(text=f"Starting: {profile.name}…")
        self._command_running = True
        self._command_stop_requested = False
        self._command_stop_event = threading.Event()
        stop_event = self._command_stop_event
        events = self._command_events
        self._sync_busy_controls()

        def worker():
            try:
                run_command(profile, working_directory, events, stop_event)
            except CommandExecutionError as exc:
                log_error("Starting development command", exc)
                events.put(CommandEvent("error", text=str(exc)))
            except Exception as exc:
                log_error("Development command runner", exc)
                events.put(CommandEvent("error", text=f"Command runner failed: {exc}"))

        self._command_thread = threading.Thread(target=worker, name="launchpad-command", daemon=True)
        self._command_thread.start()

    def _poll_command_events(self):
        try:
            while True:
                event = self._command_events.get_nowait()
                if event.kind == "status":
                    self.command_status.config(text=event.text)
                elif event.kind == "started":
                    self.command_status.config(text=f"Running (process ID {event.pid})")
                elif event.kind == "output":
                    self._append_command_output(event.text, stream=event.stream)
                elif event.kind == "error":
                    self.command_status.config(text="Failed to start")
                    self._append_command_output(f"\nError: {event.text}\n", stream="stderr")
                    messagebox.showerror("Command could not start", event.text)
                    self._finish_command()
                elif event.kind == "finished":
                    if event.stopped:
                        code = "unavailable" if event.returncode is None else str(event.returncode)
                        self.command_status.config(text=f"Stopped by user (exit code {code})")
                    elif event.returncode == 0:
                        self.command_status.config(text="Completed successfully (exit code 0)")
                    else:
                        self.command_status.config(text=f"Failed (exit code {event.returncode})")
                    self._append_command_output(f"\n--- {self.command_status.cget('text')} ---\n")
                    self._finish_command()
        except queue.Empty:
            pass

    def _finish_command(self):
        self._command_running = False
        self._command_stop_requested = False
        self._command_stop_event = None
        self._command_thread = None
        self._sync_busy_controls()
        if self._closing:
            self.root.destroy()

    def _append_command_output(self, text, stream=None):
        self.command_output.configure(state="normal")
        tag = stream if stream == "stderr" else ()
        self.command_output.insert("end", text, tag)
        self.command_output.see("end")
        self.command_output.configure(state="disabled")

    def clear_command_output(self):
        self._set_text(self.command_output, "")

    def stop_running_command(self):
        if not self._command_running or self._command_stop_event is None or self._command_stop_requested:
            return
        self._command_stop_requested = True
        self.command_status.config(text="Stop requested; terminating the process tree…")
        self._command_stop_event.set()
        self._sync_busy_controls()

    def on_close(self):
        if not self._command_running:
            self._save_window_preferences()
            self._closing = True
            self.root.destroy()
            return
        if not messagebox.askyesno(
            "Command still running",
            "Stop the running command and its child processes before closing Developer Launchpad?",
        ):
            return
        self._closing = True
        self._save_window_preferences()
        self.stop_running_command()
        self.command_status.config(text="Stopping command before closing…")

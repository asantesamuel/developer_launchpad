"""Create a new project folder and initialize a local Git repository."""

from dataclasses import dataclass
import re
from pathlib import Path

from integrations import run_git


README_TEMPLATE = """# {name}\n\nProject created with Developer Launchpad.\n"""

# Ignore common generated output and secrets, but preserve source files,
# dependency lock files, and project/editor configuration by default.
GITIGNORE_TEMPLATE = """# Local secrets and environment settings\n.env\n.env.*\n!.env.example\n*.pem\n*.key\n\n# Python generated files and virtual environments\n__pycache__/\n*.py[cod]\n.venv/\nvenv/\n\n# Node generated dependencies and build output\nnode_modules/\ndist/\nbuild/\n\n# Common operating-system metadata\n.DS_Store\nThumbs.db\n"""

_INVALID_WINDOWS_CHARACTERS = re.compile(r'[<>:"/\\|?*]')
_RESERVED_WINDOWS_NAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])$", re.IGNORECASE
)


class ProjectCreationError(RuntimeError):
    """A creation failure with the on-disk state needed for safe recovery."""

    def __init__(self, message, path, created_files=(), git_initialized=False, folder_created=False):
        super().__init__(message)
        self.path = Path(path)
        self.created_files = tuple(created_files)
        self.git_initialized = git_initialized
        self.folder_created = folder_created


@dataclass(frozen=True)
class ProjectCreationResult:
    """The verified local state after a successful project creation."""

    name: str
    path: Path
    generated_files: tuple[str, ...]
    git_initialized: bool
    initial_commit_hash: str | None


def validate_project_name(name):
    """Validate a directory name against Windows naming restrictions."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Enter a project name.")
    if name != name.strip():
        raise ValueError("Project names cannot start or end with whitespace. Remove the extra spaces.")
    if name in (".", "..") or not name.strip(" ."):
        raise ValueError("Project names cannot consist only of spaces or dots.")
    if name.endswith((" ", ".")):
        raise ValueError("Windows folder names cannot end with a space or dot.")
    if _INVALID_WINDOWS_CHARACTERS.search(name) or any(ord(char) < 32 for char in name):
        raise ValueError('Project name contains a character Windows does not allow: < > : " / \\ | ? *')
    try:
        windows_length = len(name.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise ValueError("Project name contains an invalid Unicode character for a Windows folder.") from exc
    if windows_length > 255:
        raise ValueError("Windows folder names cannot exceed 255 UTF-16 characters.")
    device_stem = name.split(".", 1)[0].rstrip(" .")
    if _RESERVED_WINDOWS_NAME.fullmatch(device_stem):
        raise ValueError(f"'{name}' is a reserved Windows device name. Choose another name.")
    return name


def preview_project_path(parent_directory, name):
    """Return the normalized destination without creating it."""
    validate_project_name(name)
    parent = Path(parent_directory).expanduser()
    if not parent.is_dir():
        raise ValueError(f"Parent directory does not exist or is not a folder: {parent}")
    return parent.resolve() / name


def create_project(
    name,
    parent_directory,
    *,
    create_readme=True,
    create_gitignore=True,
    initial_commit=True,
    progress=None,
    git_runner=None,
):
    """Create only in a new folder, write chosen starter files, and run git init.

    The optional progress callback should enqueue messages for the GUI thread;
    this function itself never accesses Tkinter.
    """
    destination = preview_project_path(parent_directory, name)
    generated = []
    if initial_commit and not (create_readme or create_gitignore):
        raise ValueError(
            "An initial commit needs at least one generated file. Select README or .gitignore, or turn off the commit option."
        )
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"The destination already exists and will not be overwritten: {destination}")

    try:
        # exist_ok=False makes the final collision check atomic at directory creation.
        destination.mkdir(exist_ok=False)
    except OSError as exc:
        raise ProjectCreationError(
            f"Could not create project folder: {exc}. No existing folder was changed.", destination
        ) from exc

    def report(message):
        if progress:
            progress(message)

    git_initialized = False
    git_init_attempted = False
    try:
        if create_readme:
            (destination / "README.md").write_text(
                README_TEMPLATE.format(name=name), encoding="utf-8", newline="\n"
            )
            generated.append("README.md")
            report("Created README.md")
        if create_gitignore:
            (destination / ".gitignore").write_text(
                GITIGNORE_TEMPLATE, encoding="utf-8", newline="\n"
            )
            generated.append(".gitignore")
            report("Created .gitignore")

        report("Initializing local Git repository…")
        runner = git_runner or run_git
        git_init_attempted = True
        runner(destination, ["init"], timeout=30)
        top_level = runner(destination, ["rev-parse", "--show-toplevel"], timeout=20)
        if Path(top_level).resolve() != destination.resolve():
            raise RuntimeError("Git reported a repository root different from the new project folder.")
        git_initialized = True
        report("Local Git repository initialized and verified.")

        commit_hash = None
        if initial_commit:
            report("Creating the authorized initial commit from generated files…")
            commit_hash = _commit_only_paths(destination, generated, runner)
        return ProjectCreationResult(name, destination, tuple(generated), git_initialized, commit_hash)
    except Exception as exc:
        detail = _explain_git_identity(exc)
        details = ", ".join(generated) if generated else "no starter files"
        if git_initialized:
            git_state = "verified initialized"
            git_state_value = True
        elif not git_init_attempted:
            git_state = "not attempted"
            git_state_value = False
        elif "Git was not found" in detail:
            git_state = "not initialized (Git unavailable)"
            git_state_value = False
        else:
            git_state = "unknown; Git init failed before verification"
            git_state_value = None
        raise ProjectCreationError(
            f"Project creation stopped: {detail}\n\nThe new folder remains at {destination}; generated content: {details}; Git status: {git_state}. Nothing was automatically deleted.",
            destination,
            generated,
            git_state_value,
            folder_created=True,
        ) from exc


def create_initial_commit(project_path, generated_files, git_runner=None):
    """Commit only known starter files in a newly created Launchpad project."""
    folder = Path(project_path).resolve()
    paths = list(dict.fromkeys(generated_files))
    if not paths:
        raise ValueError(
            "There are no generated starter files to commit. Create and stage a file using the Git tools first."
        )
    runner = git_runner or run_git
    try:
        try:
            existing = runner(folder, ["rev-parse", "--short", "HEAD"], timeout=20)
            if existing:
                return existing
        except RuntimeError:
            # An unborn branch has no HEAD yet; that is the expected case.
            pass
        return _commit_only_paths(folder, paths, runner)
    except Exception as exc:
        detail = _explain_git_identity(exc)
        raise ProjectCreationError(
            f"Could not create the initial commit: {detail}\n\nThe repository remains at {folder}. Only generated starter paths were passed to Git; no other files were intentionally staged.",
            folder,
            paths,
            True,
            folder_created=True,
        ) from exc


def _commit_only_paths(folder, paths, runner):
    """Stage and commit explicit generated paths, never the whole directory."""
    if not paths:
        raise ValueError("There are no generated files to include in an initial commit.")
    runner(folder, ["add", "--", *paths], timeout=20)
    # --only with pathspecs prevents unrelated index entries from entering this commit.
    runner(folder, ["commit", "--only", "-m", "Initial commit", "--", *paths], timeout=30)
    commit_hash = runner(folder, ["rev-parse", "--short", "HEAD"], timeout=20)
    if not commit_hash:
        raise RuntimeError("Git did not return a commit hash after the initial commit.")
    return commit_hash


def _explain_git_identity(error):
    """Add safe, manual Git identity guidance when Git reports it is missing."""
    detail = str(error)
    if "user.name" in detail or "user.email" in detail or "Author identity unknown" in detail:
        detail += (
            " Configure Git identity yourself with `git config --global user.name` and "
            "`git config --global user.email`; Developer Launchpad does not change global Git settings."
        )
    return detail

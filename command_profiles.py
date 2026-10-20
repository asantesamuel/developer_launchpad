"""Validated, project-specific development command profiles."""

from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class CommandProfile:
    """A command saved as an executable plus separate argv entries."""

    profile_id: str
    name: str
    executable: str
    arguments: tuple[str, ...] = ()
    working_directory: str = "."
    long_running: bool = False
    description: str = ""

    def to_dict(self):
        """Return a JSON-ready mapping."""
        value = asdict(self)
        value["arguments"] = list(self.arguments)
        return value

    @classmethod
    def from_dict(cls, value):
        """Load and validate a saved profile without trusting its JSON shape."""
        if not isinstance(value, dict):
            raise ValueError("profile must be an object")

        name = value.get("name")
        executable = value.get("executable")
        profile_id = value.get("profile_id")
        arguments = value.get("arguments", [])
        working_directory = value.get("working_directory", ".")
        long_running = value.get("long_running", False)
        description = value.get("description", "")

        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ValueError("profile ID is missing")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("display name is missing")
        if not isinstance(executable, str) or not executable.strip():
            raise ValueError("executable is missing")
        if not isinstance(arguments, list) or any(not isinstance(arg, str) for arg in arguments):
            raise ValueError("arguments must be a list of strings")
        if not isinstance(working_directory, str) or not working_directory.strip():
            raise ValueError("working directory must be a non-empty relative path")
        if type(long_running) is not bool:
            raise ValueError("long-running setting must be true or false")
        if not isinstance(description, str):
            raise ValueError("description must be text")
        if any("\0" in item for item in [name, executable, working_directory, description, *arguments]):
            raise ValueError("profile fields cannot contain NUL characters")

        return cls(
            profile_id=profile_id.strip(),
            name=name.strip(),
            executable=executable.strip(),
            arguments=tuple(arguments),
            working_directory=working_directory.strip(),
            long_running=long_running,
            description=description.strip(),
        )


def create_profile(name, executable, arguments_text="", working_directory=".", long_running=False, description="", profile_id=None):
    """Validate dialog fields and create a profile with a stable identifier."""
    arguments = tuple(line for line in arguments_text.splitlines() if line != "")
    return CommandProfile.from_dict({
        "profile_id": profile_id or uuid4().hex,
        "name": name,
        "executable": executable,
        "arguments": list(arguments),
        "working_directory": working_directory or ".",
        "long_running": long_running,
        "description": description,
    })


def resolve_working_directory(project_root, configured_path):
    """Resolve a project-relative folder and reject paths outside the project."""
    root = Path(project_root).resolve()
    relative = Path(configured_path or ".")
    if relative.is_absolute():
        raise ValueError("Working directory must be relative to the project folder.")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("Working directory must stay inside the project folder.") from exc
    if not resolved.is_dir():
        raise ValueError(f"Working directory does not exist: {resolved}")
    return resolved

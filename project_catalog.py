"""Small, testable operations for saved project shortcuts and labels."""

import os
from pathlib import Path


ALL_CATEGORIES = "All categories"
ALL_TAGS = "All tags"


def _normalized_path(path):
    """Return a case-normalized resolved path, or None for malformed values."""
    if not isinstance(path, str) or not path.strip():
        return None
    try:
        return os.path.normcase(str(Path(path).expanduser().resolve()))
    except (OSError, RuntimeError, ValueError):
        return None


def project_folder_available(project):
    """Whether a saved path currently points to a directory."""
    path = project.get("path")
    if not isinstance(path, str) or not path.strip():
        return False
    try:
        return Path(path).expanduser().is_dir()
    except (OSError, ValueError):
        return False


def filter_projects(projects, query="", category=ALL_CATEGORIES, tag=ALL_TAGS):
    """Filter saved project records by name/path text and optional labels."""
    search = query.strip().casefold()
    matching = []
    for project in projects:
        tags = project.get("tags", [])
        if not isinstance(tags, list):
            tags = []
        category_value = project.get("category", "")
        searchable = " ".join([str(project.get("name", "")), str(project.get("path", "")), str(category_value), *map(str, tags)])
        if search and search not in searchable.casefold():
            continue
        if category not in ("", ALL_CATEGORIES) and category_value != category:
            continue
        if tag not in ("", ALL_TAGS) and tag not in tags:
            continue
        matching.append(project)
    return matching


def add_project_shortcut(projects, name, path):
    """Return a saved shortcut for an existing folder; never copies or deletes it."""
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Project folder does not exist or is not a folder: {folder}")
    normalized_folder = _normalized_path(str(folder))
    if any(_normalized_path(item.get("path")) == normalized_folder for item in projects):
        raise ValueError("That folder is already in your project list.")
    clean_name = name.strip() or folder.name or str(folder)
    return {"name": clean_name, "path": str(folder), "category": "", "tags": []}


def remove_project_shortcut(projects, path):
    """Return shortcuts other than *path*; project files on disk are untouched."""
    target = _normalized_path(str(path))
    if target is None:
        return list(projects)
    return [item for item in projects if _normalized_path(item.get("path")) != target]


def clean_labels(values):
    """Return unique, trimmed label strings in their original order."""
    result = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        label = value.strip()
        folded = label.casefold()
        if label and folded not in seen:
            result.append(label)
            seen.add(folded)
    return result


def set_project_labels(project, category, tags):
    """Update user-supplied labels without replacing other project metadata."""
    project["category"] = category.strip() if isinstance(category, str) else ""
    project["tags"] = clean_labels(tags)


def rename_label(projects, labels, old_name, new_name, field=None):
    """Rename a category/tag in its catalog and project assignments."""
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("Label names cannot be empty.")
    if any(item.casefold() == new_name.casefold() and item.casefold() != old_name.casefold() for item in labels):
        raise ValueError("That label already exists.")
    updated = [new_name if item == old_name else item for item in labels]
    if field == "category":
        for project in projects:
            if project.get("category") == old_name:
                project["category"] = new_name
    elif field == "tags":
        for project in projects:
            current = project.get("tags", [])
            if isinstance(current, list) and old_name in current:
                project["tags"] = clean_labels([new_name if item == old_name else item for item in current])
    return clean_labels(updated)


def remove_label(projects, labels, name, field=None):
    """Remove a category/tag assignment while retaining all project folders."""
    if field == "category":
        for project in projects:
            if project.get("category") == name:
                project["category"] = ""
    elif field == "tags":
        for project in projects:
            current = project.get("tags", [])
            if isinstance(current, list):
                project["tags"] = [item for item in current if item != name]
    return [item for item in labels if item != name]

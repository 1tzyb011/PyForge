"""Read and write the portable .forproj project format."""

import json
from pathlib import Path, PureWindowsPath

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


class ProjectFormatError(ValueError):
    """Raised when a .forproj manifest is invalid or unreadable."""


def _toml_string(value):
    return json.dumps(str(value), ensure_ascii=False)


def serialize_project_manifest(metadata):
    project = {
        "format_version": int(metadata.get("format_version", 1)),
        "name": metadata.get("name", "PythonProject"),
        "template": metadata.get("template", "python.basic_application"),
        "language": metadata.get("language", "python"),
    }
    python_config = {
        "entry_point": metadata.get("entry_point", "main.py"),
        "interpreter": metadata.get("interpreter", ""),
        "dependencies": metadata.get("dependencies", []),
    }
    environment = metadata.get("environment", {})
    environment_config = {
        "enabled": bool(environment.get("enabled", False)),
        "path": environment.get("path") or "",
        "status": environment.get("status", "disabled"),
    }
    lines = [
        "[project]",
        f"format_version = {project['format_version']}",
        f"name = {_toml_string(project['name'])}",
        f"template = {_toml_string(project['template'])}",
        f"language = {_toml_string(project['language'])}",
        "",
        "[python]",
        f"entry_point = {_toml_string(python_config['entry_point'])}",
        f"interpreter = {_toml_string(python_config['interpreter'])}",
        "dependencies = " + json.dumps(python_config["dependencies"], ensure_ascii=False),
        "",
        "[environment]",
        f"enabled = {'true' if environment_config['enabled'] else 'false'}",
        f"path = {_toml_string(environment_config['path'])}",
        f"status = {_toml_string(environment_config['status'])}",
        "",
    ]
    return "\n".join(lines)


def write_project_manifest(path, metadata, overwrite=False):
    path = Path(path)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8", newline="\n") as file:
        file.write(serialize_project_manifest(metadata))


def _fallback_toml_loads(source):
    """Parse the simple TOML subset emitted by this module on Python < 3.11."""
    document = {}
    current = document
    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            if not section or "." in section:
                raise ProjectFormatError("Unsupported TOML section.")
            current = document.setdefault(section, {})
            continue
        if "=" not in line:
            raise ProjectFormatError(f"Invalid TOML line: {raw_line}")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not key:
            raise ProjectFormatError("A TOML key is empty.")
        try:
            value = json.loads(raw_value)
        except json.JSONDecodeError:
            if raw_value == "true":
                value = True
            elif raw_value == "false":
                value = False
            else:
                raise ProjectFormatError(f"Unsupported TOML value for {key}: {raw_value}")
        current[key] = value
    return document


def _normalize_manifest(document):
    if not isinstance(document, dict):
        raise ProjectFormatError("The project manifest must contain an object.")
    if "project" not in document:
        metadata = document  # Legacy pyforge.json
    else:
        project = document.get("project", {})
        python_config = document.get("python", {})
        environment_config = document.get("environment", {})
        metadata = {
            "format_version": project.get("format_version", 1),
            "name": project.get("name", ""),
            "template": project.get("template", "python.basic_application"),
            "language": project.get("language", "python"),
            "entry_point": python_config.get("entry_point", "main.py"),
            "interpreter": python_config.get("interpreter", ""),
            "dependencies": python_config.get("dependencies", []),
            "environment": {
                "enabled": environment_config.get("enabled", False),
                "path": environment_config.get("path") or None,
                "status": environment_config.get("status", "unknown"),
            },
        }

    if metadata.get("format_version", 1) != 1:
        raise ProjectFormatError(
            f"Unsupported .forproj format version: {metadata.get('format_version')!r}"
        )
    name = metadata.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ProjectFormatError("The project manifest has no valid project name.")

    entry_point = metadata.get("entry_point", "main.py")
    if not isinstance(entry_point, str) or not entry_point.strip():
        raise ProjectFormatError("The project entry_point must be a relative path.")
    native_path = Path(entry_point)
    windows_path = PureWindowsPath(entry_point)
    if (
        native_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in native_path.parts
        or ".." in windows_path.parts
    ):
        raise ProjectFormatError(
            "The project entry_point must stay inside the project directory."
        )

    dependencies = metadata.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise ProjectFormatError("Project dependencies must be a list of strings.")
    environment = metadata.get("environment", {})
    if not isinstance(environment, dict):
        raise ProjectFormatError("The project environment settings are invalid.")

    normalized = dict(metadata)
    normalized["entry_point"] = entry_point
    normalized["interpreter"] = str(metadata.get("interpreter") or "")
    normalized["dependencies"] = dependencies
    normalized["environment"] = {
        "enabled": bool(environment.get("enabled", False)),
        "path": environment.get("path") or None,
        "status": str(environment.get("status", "unknown")),
    }
    return normalized


def load_project_manifest(path):
    path = Path(path)
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProjectFormatError(f"Could not read project file:\n{exc}") from exc
    try:
        if path.suffix.lower() == ".json" or path.name.lower() == "pyforge.json":
            document = json.loads(source)
        elif tomllib is not None:
            document = tomllib.loads(source)
        else:
            document = _fallback_toml_loads(source)
    except (ValueError, TypeError) as exc:
        raise ProjectFormatError(f"Could not parse project file {path.name}:\n{exc}") from exc
    return _normalize_manifest(document)


def find_project_manifest(project_root):
    root = Path(project_root)
    preferred = root / f"{root.name}.forproj"
    if preferred.is_file():
        return preferred
    candidates = sorted(root.glob("*.forproj"))
    if candidates:
        return candidates[0]
    legacy = root / "pyforge.json"
    return legacy if legacy.is_file() else None

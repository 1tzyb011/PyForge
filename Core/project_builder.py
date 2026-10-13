import subprocess
from pathlib import Path

from Core.project_format import write_project_manifest


class ProjectCreationError(Exception):
    """Raised when project files cannot be created safely."""


def build_project(destination, project_name, interpreter, create_venv=False):
    """Create a basic Python project and its canonical .forproj manifest."""
    destination = Path(destination).expanduser().resolve()
    if not interpreter or not Path(interpreter).is_file():
        raise ProjectCreationError("The selected Python interpreter is unavailable.")
    if not project_name or project_name.strip() != project_name:
        raise ProjectCreationError("Enter a project name without leading or trailing spaces.")
    if (
        project_name in {".", ".."}
        or any(char in project_name for char in '<>:"/\\|?*')
        or any(ord(char) < 32 for char in project_name)
    ):
        raise ProjectCreationError("The project name contains invalid characters.")
    if destination.exists() and not destination.is_dir():
        raise ProjectCreationError("The destination exists but is not a directory.")
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectCreationError(f"Could not create the project directory:\n{exc}") from exc

    starter_files = {
        "main.py": (
            "def main():\n"
            f'    print("Hello from {project_name}!")\n'
            "\n\n"
            'if __name__ == "__main__":\n'
            "    main()\n"
        ),
        "README.md": (
            f"# {project_name}\n\n"
            "A Python project created with pyForge.\n\n"
            "## Getting started\n\n"
            "Run main.py with your Python interpreter.\n"
        ),
        ".gitignore": ".venv/\n__pycache__/\n*.py[cod]\n.idea/\n.vscode/\n",
        "requirements.txt": (
            "# Add your project dependencies here.\n"
            "# Just write the exact package names and versions in correct cases and spellings\n"
        ),
    }
    metadata_path = destination / f"{project_name}.forproj"
    metadata = {
        "format_version": 1,
        "name": project_name,
        "template": "python.basic_application",
        "language": "python",
        "entry_point": "main.py",
        "interpreter": str(Path(interpreter).resolve()),
        "dependencies": [],
        "environment": {
            "enabled": bool(create_venv),
            "path": ".venv" if create_venv else None,
            "status": "pending" if create_venv else "disabled",
        },
    }

    created_files, skipped_files = [], []
    environment_status = "pending" if create_venv else "disabled"
    environment_error = None
    try:
        for filename, content in starter_files.items():
            path = destination / filename
            if path.exists():
                skipped_files.append(filename)
                continue
            with path.open("x", encoding="utf-8", newline="\n") as file:
                file.write(content)
            created_files.append(filename)

        if metadata_path.exists():
            skipped_files.append(metadata_path.name)
        else:
            write_project_manifest(metadata_path, metadata)
            created_files.append(metadata_path.name)
    except OSError as exc:
        raise ProjectCreationError(
            "Project creation stopped while writing files.\n"
            f"Location: {destination}\nError: {exc}\n\n"
            "Any files already created have been kept. Inspect the directory and try again."
        ) from exc

    if create_venv:
        venv_path = destination / ".venv"
        if venv_path.exists():
            environment_status = "already_exists"
            environment_error = ".venv already exists. It was not modified."
        else:
            try:
                subprocess.run(
                    [str(Path(interpreter).resolve()), "-m", "venv", str(venv_path)],
                    check=True, capture_output=True, text=True, timeout=180,
                )
                environment_status = "created"
            except subprocess.TimeoutExpired:
                environment_status = "failed"
                environment_error = (
                    "Creating the virtual environment timed out. "
                    "The source files are still available."
                )
            except (OSError, subprocess.SubprocessError) as exc:
                environment_status = "failed"
                details = getattr(exc, "stderr", None)
                environment_error = (
                    "Could not create the virtual environment.\n"
                    f"{details or exc}\nThe source files are still available."
                )

        if metadata_path.name in created_files:
            metadata["environment"]["status"] = environment_status
            try:
                write_project_manifest(metadata_path, metadata, overwrite=True)
            except OSError as exc:
                environment_error = (
                    (environment_error + "\n\n") if environment_error else ""
                ) + f"The environment status could not be saved to {metadata_path.name}: {exc}"

    return {
        "destination": str(destination),
        "project_file": str(metadata_path),
        "created_files": created_files,
        "skipped_files": skipped_files,
        "environment_status": environment_status,
        "environment_error": environment_error,
    }

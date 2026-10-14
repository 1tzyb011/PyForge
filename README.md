# PyForge

PyForge is a lightweight Python IDE built with Python and PySide6. It is in alpha, so features and internal APIs may change.

## Run from source

1. Install Python 3.11 or newer.
2. Install the dependency:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the application from the repository root:

   ```bash
   python PyForge.py
   ```

To open a standalone script or a PyForge project directly, pass its path:

```bash
python PyForge.py path/to/script.py
python PyForge.py path/to/project.forproj
```

## Repository layout

- `PyForge.py`: application entry point.
- `Project_Creator.py`, `Project_Editor.py`, `Script_editor.py`, `Interpreter_Manager.py`: main application windows and workflows.
- `Core/`: shared project-format, project-building, diagnostics, window-lifecycle, and action-icon helpers.
- `UI/`: Qt Designer `.ui` files loaded at runtime.
- `Assets/LOGOS/`: PyForge branding and retained logo source files.
- `packaging/linux/`: Linux project-file association helpers.

The Qt Designer files are loaded at runtime, so keep their filenames in sync with the paths used by the Python modules.

## Contributing

Found a bug or have an idea? Open an issue or send a pull request.

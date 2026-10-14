"""PyForge application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from Core.diagnostics import (
    install_diagnostics,
    log_event,
    log_exception,
    start_ui_freeze_watchdog,
)
from Core.window_registry import retain_window


BASE_DIR = Path(__file__).resolve().parent


def _apply_stylesheet(app):
    """Load dark.qss from the application root or Assets directory."""
    candidates = (
        BASE_DIR / "dark.qss",
        BASE_DIR / "Assets" / "dark.qss",
    )

    for stylesheet_path in candidates:
        if not stylesheet_path.is_file():
            continue

        try:
            app.setStyleSheet(stylesheet_path.read_text(encoding="utf-8"))
            log_event(f"Loaded stylesheet: {stylesheet_path}")
            return
        except (OSError, UnicodeError) as error:
            log_exception(f"Could not load stylesheet {stylesheet_path}", error)
            break

    log_event("No readable dark.qss found; using the Qt default stylesheet.")


def main():
    log_path = install_diagnostics()
    log_event("Entering PyForge main()")

    app = QApplication([sys.argv[0]])
    _apply_stylesheet(app)
    start_ui_freeze_watchdog(app)

    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    log_event(
        f"Launch target: {str(target) if target is not None else '<empty>'}"
    )

    try:
        # Import after QApplication exists so import/startup failures can be
        # reported in a GUI dialog instead of silently terminating the app.
        from Project_Editor import ProjectEditor
        from Script_editor import ScriptEditor

        if target is not None and target.suffix.lower() == ".forproj":
            controller = ProjectEditor(project_path=target.resolve())
        elif target is not None and target.name.lower() == "pyforge.json":
            controller = ProjectEditor(project_path=target.resolve())
        elif target is not None and target.suffix.lower() == ".py":
            controller = ScriptEditor(file_path=str(target.resolve()))
        elif target is not None and target.is_dir():
            controller = ProjectEditor(project_path=target.resolve())
        else:
            controller = ScriptEditor()

        # Register before showing the window to keep its controller alive and
        # ensure Qt deletes the top-level widget when it closes.
        retain_window(controller)
        app._pyforge_controller = controller
        controller.show()

    except Exception as exc:
        log_exception("Application startup failed", exc)
        QMessageBox.critical(
            None,
            "PyForge Could Not Open the File",
            f"{type(exc).__name__}: {exc}\n\nCrash log: {log_path}",
        )
        return 1

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

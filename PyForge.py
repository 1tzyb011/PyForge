"""PyForge application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from Core.diagnostics import install_diagnostics, log_event
from Core.window_registry import retain_window


def main():
    log_path = install_diagnostics()
    log_event("Entering PyForge main()")
    from Project_Creator import ProjectCreator
    from Project_Editor import ProjectEditor
    from Script_editor import ScriptEditor

    app = QApplication([sys.argv[0]])
    app_dir = Path(__file__).resolve().parent
    qss_path = app_dir / "dark.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    log_event(f"Launch target: {str(target) if target is not None else '<empty>'}")
    controller = None
    try:
        if target is not None and target.suffix.lower() == ".forproj":
            controller = ProjectEditor(project_path=target.resolve())
            controller.show()
        elif target is not None and target.name.lower() == "pyforge.json":
            controller = ProjectEditor(project_path=target.resolve())
            controller.show()
        elif target is not None and target.suffix.lower() == ".py":
            controller = ScriptEditor(file_path=str(target.resolve()))
            controller.show()
        elif target is not None and target.is_dir():
            controller = ProjectEditor(project_path=target.resolve())
            controller.show()
        else:
            controller = ScriptEditor()
            controller.show()
    except Exception as exc:
        from Core.diagnostics import log_exception
        log_exception("Application startup failed", exc)
        QMessageBox.critical(
            None,
            "PyForge Could Not Open the File",
            f"{exc}\n\nCrash log: {log_path}",
        )
        return 1

    retain_window(controller)
    app._pyforge_controller = controller
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

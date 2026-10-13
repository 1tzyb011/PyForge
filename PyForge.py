"""PyForge application entry point."""

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from Project_Creator import ProjectCreator
from Project_Editor import ProjectEditor
from Script_editor import ScriptEditor
from Core.window_registry import retain_window


def main():
    app = QApplication([sys.argv[0]])
    app_dir = Path(__file__).resolve().parent
    qss_path = app_dir / "dark.qss"
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    target = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
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
            controller = ProjectCreator()
            controller.show()
    except Exception as exc:
        QMessageBox.critical(None, "PyForge Could Not Open the File", str(exc))
        return 1

    retain_window(controller)
    app._pyforge_controller = controller
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

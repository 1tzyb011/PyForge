
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from Script_editor import ScriptEditor
from Interpreter_Manager import InterpreterManager


def main():
    app = QApplication(sys.argv)

    qss_path = Path(__file__).resolve().parent / "dark.qss"

    with open(qss_path, "r", encoding="utf-8") as file:
        app.setStyleSheet(file.read())

    editor = InterpreterManager()
    editor.window.show()

    sys.exit(app.exec())



if __name__ == "__main__":
    main()

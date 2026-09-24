
import sys

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QFile

from Project_Editor import ProjectEditor

def load_stylesheet(path):
    file = QFile(path)

    if not file.open(QFile.OpenModeFlag.ReadOnly):
        print(f"Failed to open stylesheet: {path}")
        return ""

    stylesheet = file.readAll().data().decode("utf-8")
    file.close()

    return stylesheet

def main():
    app = QApplication(sys.argv)
    stylesheet = load_stylesheet("dark.qss")
    app.setStyleSheet(stylesheet)

    window = ProjectEditor()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
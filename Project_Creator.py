
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QFile, QObject
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMessageBox,
    QComboBox,
)
from PySide6.QtUiTools import QUiLoader


class ProjectCreator(QObject):
    def __init__(self):
        super().__init__()

        self.window = self.load_ui("Project_Creator.ui")

        if self.window is None:
            raise RuntimeError("Could not load Project_Creator.ui")

        self.connect_actions()
        self.populate_interpreters()

    def load_ui(self, path):
        ui_file = QFile(path)

        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            return None

        loader = QUiLoader()
        window = loader.load(ui_file)
        ui_file.close()

        return window

    def connect_actions(self):
        self.window.BrowseButton.clicked.connect(
            self.browse_location
        )

        self.window.cancelBut.clicked.connect(
            self.window.reject
        )

        self.window.createBut.clicked.connect(
            self.create_project
        )

        self.window.ManageEnvButton.clicked.connect(
            self.manage_environment
        )

    def browse_location(self):
        folder = QFileDialog.getExistingDirectory(
            self.window,
            "Choose Project Location",
            self.window.LocationEdit.text()
            or os.path.expanduser("~"),
        )

        if folder:
            self.window.LocationEdit.setText(folder)

    def populate_interpreters(self):
        combo = self.window.InterpreterComboBox
        combo.clear()

        candidates = []

        for command in ("python", "python3", "py"):
            path = shutil.which(command)

            if path and path not in candidates:
                candidates.append(path)

        # Discover Python installations using the Windows launcher.
        launcher = shutil.which("py")

        if launcher:
            try:
                result = subprocess.run(
                    [launcher, "-0p"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                for line in result.stdout.splitlines():
                    parts = line.strip().split(None, 2)

                    if len(parts) == 3:
                        path = parts[-1].strip()

                        if os.path.isfile(path):
                            if path not in candidates:
                                candidates.append(path)

            except (OSError, subprocess.SubprocessError):
                pass

        for path in candidates:
            try:
                result = subprocess.run(
                    [
                        path,
                        "-c",
                        "import sys; "
                        "print(sys.version.split()[0]); "
                        "print(sys.executable)",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )

                if result.returncode != 0:
                    continue

                lines = result.stdout.strip().splitlines()

                if len(lines) < 2:
                    continue

                version, executable = lines[:2]

                combo.addItem(
                    f"Python {version} ({executable})",
                    executable,
                )

            except (OSError, subprocess.SubprocessError):
                continue

        if combo.count() == 0:
            combo.addItem("No Python interpreter found", None)

    def manage_environment(self):
        QMessageBox.information(
            self.window,
            "Interpreter Manager",
            "We'll connect the Interpreter Manager next.",
        )

    def create_project(self):
        QMessageBox.information(
            self.window,
            "Project Creator",
            "The project creation logic is our next step.",
        )

    def show(self):
        self.window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    creator = ProjectCreator()
    creator.window.exec()

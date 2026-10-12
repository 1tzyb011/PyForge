

import os
import shutil
import subprocess
import sys
from pathlib import Path

from Interpreter_Manager import InterpreterManager
from Project_Editor import ProjectEditor

from PySide6.QtCore import QFile, QObject
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QLineEdit,
    QMessageBox,
    QComboBox,
)

from PySide6.QtUiTools import QUiLoader

from Core.project_builder import (
    build_project,
    ProjectCreationError,
)


APP_DIR = Path(__file__).resolve().parent


class ProjectCreator(QObject):
    def __init__(self):
        super().__init__()

        self.window = self.load_ui()

        if self.window is None:
            raise RuntimeError(
                "Could not load Project_Creator.ui"
            )

        self.project_name_edit = self.find_widget(
            QLineEdit,
            "ProjectNameEdit",
            "ProjectNameLineEdit",
            "NameEdit",
            "ProjectEdit",
        )

        self.venv_checkbox = self.find_widget(
            QCheckBox,
            "CreateVenvCheckBox",
            "VirtualEnvCheckBox",
            "VenvCheckBox",
        )

        if self.project_name_edit is None:
            raise RuntimeError(
                "Add a QLineEdit named ProjectNameEdit "
                "to Project_Creator.ui."
            )

        if self.venv_checkbox is None:
            raise RuntimeError(
                "Add a QCheckBox named CreateVenvCheckBox "
                "to Project_Creator.ui."
            )

        self.connect_actions()
        self.populate_interpreters()

    def load_ui(self):
        candidates = [
            APP_DIR / "UI" / "Project_Creator.ui",
            APP_DIR / "Project_Creator.ui",
        ]

        ui_path = next(
            (path for path in candidates if path.is_file()),
            None,
        )

        if ui_path is None:
            return None

        ui_file = QFile(str(ui_path))

        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            return None

        try:
            loader = QUiLoader()
            return loader.load(ui_file)
        finally:
            ui_file.close()

    def find_widget(self, widget_type, *names):
        for name in names:
            widget = self.window.findChild(widget_type, name)

            if widget is not None:
                return widget

        return None

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
        current_location = (
            self.window.LocationEdit.text().strip()
            or str(Path.home())
        )

        folder = QFileDialog.getExistingDirectory(
            self.window,
            "Choose Project Parent Folder",
            current_location,
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
                        path = parts[-1].strip().strip('"')

                        if (
                            os.path.isfile(path)
                            and path not in candidates
                        ):
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
            combo.addItem(
                "No Python interpreter found",
                None,
            )

    def manage_environment(self):
        manager = InterpreterManager()

        if manager.window.exec():
            interpreter = manager.get_selected_interpreter()

            if interpreter:
                combo = self.window.InterpreterComboBox
                path = interpreter["path"]

                # Refresh the list so the selected interpreter is available.
                self.populate_interpreters()

                for index in range(combo.count()):
                    if combo.itemData(index) == path:
                        combo.setCurrentIndex(index)
                        break
                else:
                    # Include interpreters selected manually by the user.
                    combo.addItem(
                        f"Python {interpreter['version_text']} ({path})",
                        path,
                    )
                    combo.setCurrentIndex(combo.count() - 1)

    def create_project(self):
        project_name = self.project_name_edit.text().strip()
        parent_text = self.window.LocationEdit.text().strip()
        combo = self.window.InterpreterComboBox
        interpreter = combo.currentData()
        create_venv = self.venv_checkbox.isChecked()

        if not project_name:
            QMessageBox.warning(
                self.window,
                "Project Name Required",
                "Enter a name for your project.",
            )
            self.project_name_edit.setFocus()
            return

        if not parent_text:
            QMessageBox.warning(
                self.window,
                "Location Required",
                "Choose a parent folder for your project.",
            )
            return

        if not interpreter:
            QMessageBox.warning(
                self.window,
                "Python Not Found",
                "Select a valid Python interpreter first.",
            )
            return

        parent = Path(parent_text).expanduser()

        if not parent.is_dir():
            QMessageBox.warning(
                self.window,
                "Invalid Location",
                "The selected parent folder does not exist. "
                "Choose an existing folder.",
            )
            return

        destination = parent / project_name

        # Ask before placing anything in an existing project folder.
        if destination.exists():
            if not destination.is_dir():
                QMessageBox.warning(
                    self.window,
                    "Invalid Destination",
                    "A file with the project name already exists.",
                )
                return

            answer = QMessageBox.question(
                self.window,
                "Directory Already Exists",
                f"The following directory already exists:\n\n"
                f"{destination}\n\n"
                "Continue by adding missing project files? "
                "Existing files will not be overwritten.",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )

            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            result = build_project(
                destination=destination,
                project_name=project_name,
                interpreter=interpreter,
                create_venv=create_venv,
            )

        except ProjectCreationError as exc:
            QMessageBox.critical(
                self.window,
                "Project Creation Error",
                str(exc),
            )
            return

        except Exception as exc:
            QMessageBox.critical(
                self.window,
                "Unexpected Error",
                f"An unexpected error occurred:\n{exc}\n\n"
                "Check the project directory for files that "
                "may already have been created.",
            )
            return

        lines = [
            "Your project files have been created.",
            "",
            f"Location: {result['destination']}",
            "",
            "Created: "
            + (
                ", ".join(result["created_files"])
                or "No new files"
            ),
        ]

        if result["skipped_files"]:
            lines.extend([
                "",
                "Existing files preserved: "
                + ", ".join(result["skipped_files"]),
            ])

        environment_status = result["environment_status"]

        if environment_status == "created":
            lines.extend([
                "",
                "Virtual environment: Created successfully.",
            ])
        elif environment_status == "disabled":
            lines.extend([
                "",
                "Virtual environment: Not requested.",
            ])
        elif environment_status == "already_exists":
            lines.extend([
                "",
                "Virtual environment: An existing .venv was preserved.",
            ])
        else:
            lines.extend([
                "",
                "Virtual environment: Creation did not complete.",
            ])

        if result["environment_error"]:
            lines.extend([
                "",
                "Recovery information:",
                result["environment_error"],
            ])

        if result["environment_status"] in {
            "failed",
            "pending",
        }:
            QMessageBox.warning(
                self.window,
                "Project Created With Warnings",
                "\n".join(lines),
            )
        else:
            QMessageBox.information(
                self.window,
                "Project Created",
                "\n".join(lines),
            )
                # Open the newly created project.
        self.project_editor = ProjectEditor(
            project_path=result["destination"]
        )
        self.project_editor.show()

        # Close the creator after opening the editor.
        self.window.close()    

    def show(self):
        self.window.show()


if __name__ == "__main__":
    app = QApplication(sys.argv)

    creator = ProjectCreator()
    creator.window.exec()

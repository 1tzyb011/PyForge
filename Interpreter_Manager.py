
import json
import os
import sys
import shutil
import subprocess
import urllib.request
from pathlib import Path

from PySide6.QtCore import (
    QFile,
    QObject,
    Qt,
)
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)
from PySide6.QtUiTools import QUiLoader


PYTHON_RELEASES_URL = (
    "https://peps.python.org/api/python-releases.json"
)


class InterpreterManager(QObject):
    def __init__(self):
        super().__init__()

        self.window = self.load_ui(
            "Interpreter_Manager.ui"
        )

        if self.window is None:
            raise RuntimeError(
                "Failed to load Interpreter_Manager.ui"
            )

        self.selected_interpreter = None

        self.interpreters = []
        self.releases = []

        self.connect_actions()

        self.refresh_interpreters()

    # =========================================================
    # UI LOADING
    # =========================================================

    def load_ui(self, path):
        ui_file = QFile(path)

        if not ui_file.open(
            QFile.OpenModeFlag.ReadOnly
        ):
            print(
                f"Failed to open UI file: {path}"
            )
            return None

        loader = QUiLoader()

        window = loader.load(ui_file)

        ui_file.close()

        if window is None:
            print(
                f"Failed to load UI file: {path}"
            )

        return window

    # =========================================================
    # ACTIONS
    # =========================================================

    def connect_actions(self):
        self.window.cancelButton.clicked.connect(
            self.window.reject
        )

        self.window.selectButton.clicked.connect(
            self.select_interpreter
        )

        self.window.refreshButton.clicked.connect(
            self.refresh_interpreters
        )

    # =========================================================
    # REFRESH
    # =========================================================

    def refresh_interpreters(self):
        self.clear_interpreter_list()

        self.selected_interpreter = None

        # Find Python installations on this computer.
        self.interpreters = (
            self.find_interpreters()
        )

        # Fetch all available Python releases.
        self.releases = (
            self.fetch_python_releases()
        )

        # -----------------------------------------------------
        # Installed interpreters
        # -----------------------------------------------------

        for interpreter in self.interpreters:
            self.add_installed_interpreter(
                interpreter
            )

        # -----------------------------------------------------
        # Available Python releases
        # -----------------------------------------------------

        for release in self.releases:
            self.add_release(
                release
            )

        if (
            not self.interpreters
            and not self.releases
        ):
            self.add_message(
                "No Python interpreters or releases found."
            )

    # =========================================================
    # INSTALLED INTERPRETERS
    # =========================================================

    def find_interpreters(self):
        found = {}

        # -----------------------------------------------------
        # Windows Python Launcher
        # -----------------------------------------------------

        py_launcher = shutil.which("py")

        if py_launcher:
            try:
                result = subprocess.run(
                    [
                        py_launcher,
                        "-0p",
                    ],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )

                for line in result.stdout.splitlines():
                    line = line.strip()

                    if not line:
                        continue

                    parts = line.split(
                        None,
                        2,
                    )

                    if len(parts) < 3:
                        continue

                    path = parts[-1].strip()

                    if os.path.isfile(path):
                        found[
                            os.path.normcase(path)
                        ] = path

            except Exception:
                pass

        # -----------------------------------------------------
        # PATH: python
        # -----------------------------------------------------

        python_path = shutil.which(
            "python"
        )

        if python_path:
            self.add_path(
                found,
                python_path,
            )

        # -----------------------------------------------------
        # PATH: python3
        # -----------------------------------------------------

        python3_path = shutil.which(
            "python3"
        )

        if python3_path:
            self.add_path(
                found,
                python3_path,
            )

        # -----------------------------------------------------
        # Windows installation directories
        # -----------------------------------------------------

        if os.name == "nt":
            self.find_windows_python(
                found
            )

        interpreters = []

        for path in found.values():
            info = self.get_interpreter_info(
                path
            )

            if info is not None:
                interpreters.append(
                    info
                )

        interpreters.sort(
            key=lambda item: item["version"],
            reverse=True,
        )

        return interpreters

    def add_path(self, found, path):
        path = os.path.abspath(path)

        if os.path.isfile(path):
            found[
                os.path.normcase(path)
            ] = path

    def find_windows_python(self, found):
        locations = []

        local_app_data = os.environ.get(
            "LOCALAPPDATA"
        )

        program_files = os.environ.get(
            "ProgramFiles"
        )

        program_files_x86 = os.environ.get(
            "ProgramFiles(x86)"
        )

        if local_app_data:
            locations.append(
                Path(local_app_data)
                / "Programs"
                / "Python"
            )

        if program_files:
            locations.append(
                Path(program_files)
                / "Python"
            )

        if program_files_x86:
            locations.append(
                Path(program_files_x86)
                / "Python"
            )

        for root in locations:
            if not root.exists():
                continue

            try:
                for python_exe in root.rglob(
                    "python.exe"
                ):
                    self.add_path(
                        found,
                        str(python_exe),
                    )

            except Exception:
                pass

    def get_interpreter_info(self, path):
        try:
            result = subprocess.run(
                [
                    path,
                    "-c",
                    (
                        "import sys; "
                        "print(sys.version_info.major); "
                        "print(sys.version_info.minor); "
                        "print(sys.version_info.micro); "
                        "print(sys.executable)"
                    ),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3,
            )

            if result.returncode != 0:
                return None

            lines = [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            ]

            if len(lines) < 4:
                return None

            major = int(lines[0])
            minor = int(lines[1])
            micro = int(lines[2])

            executable = lines[3]

            return {
                "path": executable,
                "version": (
                    major,
                    minor,
                    micro,
                ),
                "version_text": (
                    f"Python "
                    f"{major}.{minor}.{micro}"
                ),
            }

        except (
            OSError,
            ValueError,
            subprocess.SubprocessError,
        ):
            return None

    # =========================================================
    # PYTHON RELEASE API
    # =========================================================

    def fetch_python_releases(self):
        try:
            request = urllib.request.Request(
                PYTHON_RELEASES_URL,
                headers={
                    "User-Agent": (
                        "pyForge Interpreter Manager"
                    )
                },
            )

            with urllib.request.urlopen(
                request,
                timeout=10,
            ) as response:
                raw_data = response.read()

            data = json.loads(
                raw_data.decode("utf-8")
            )

        except Exception as error:
            print(
                "Failed to fetch Python releases:",
                error,
            )

            return []

        releases = []

        release_data = data.get(
            "releases",
            {}
        )

        for feature_version, versions in (
            release_data.items()
        ):
            if not isinstance(
                versions,
                list,
            ):
                continue

            for release in versions:
                if not isinstance(
                    release,
                    dict,
                ):
                    continue

                stage = release.get(
                    "stage"
                )

                date = release.get(
                    "date"
                )

                state = release.get(
                    "state"
                )

                if not stage:
                    continue

                if state != "actual":
                    continue

                version = self.extract_version(
                    stage
                )

                if version is None:
                    continue

                releases.append({
                    "version": version,
                    "feature_version": (
                        feature_version
                    ),
                    "stage": stage,
                    "date": date or "",
                })

        releases.sort(
            key=self.release_sort_key,
            reverse=True,
        )

        return releases

    def extract_version(self, stage):
        parts = stage.split()

        if not parts:
            return None

        version = parts[0]

        numbers = version.split(".")

        if len(numbers) != 3:
            return None

        try:
            for number in numbers:
                int(number)

        except ValueError:
            return None

        return version

    def release_sort_key(self, release):
        try:
            version_parts = tuple(
                int(part)
                for part in release[
                    "version"
                ].split(".")
            )

            date = release.get(
                "date",
                "",
            )

            return (
                version_parts,
                date,
            )

        except Exception:
            return (
                (0, 0, 0),
                "",
            )

    # =========================================================
    # CLEAR LIST
    # =========================================================

    def clear_interpreter_list(self):
        layout = (
            self.window.verticalLayout_3
        )

        while layout.count():
            item = layout.takeAt(0)

            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

    # =========================================================
    # INSTALLED INTERPRETER CARD
    # =========================================================

    def add_installed_interpreter(
        self,
        interpreter,
    ):
        card = self.create_card()

        layout = QVBoxLayout(card)

        version_label = QLabel(
            interpreter["version_text"]
            + "  •  Installed"
        )

        version_font = QFont()
        version_font.setPointSize(11)
        version_font.setBold(True)

        version_label.setFont(
            version_font
        )

        path_label = QLabel(
            interpreter["path"]
        )

        path_label.setWordWrap(True)

        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        select_button = QPushButton(
            "Select"
        )

        select_button.clicked.connect(
            lambda checked=False,
            info=interpreter:
            self.select_specific_interpreter(
                info
            )
        )

        layout.addWidget(
            version_label
        )

        layout.addWidget(
            path_label
        )

        layout.addWidget(
            select_button
        )

        self.window.verticalLayout_3.addWidget(
            card
        )

    # =========================================================
    # PYTHON RELEASE CARD
    # =========================================================

    def add_release(self, release):
        card = self.create_card()

        layout = QVBoxLayout(card)

        version_label = QLabel(
            f"Python {release['version']}"
        )

        version_font = QFont()
        version_font.setPointSize(11)
        version_font.setBold(True)

        version_label.setFont(
            version_font
        )

        date_label = QLabel(
            f"Released: {release['date']}"
        )

        stage_label = QLabel(
            release["stage"]
        )

        download_button = QPushButton(
            "Download"
        )

        # Download functionality will be
        # implemented next.
        download_button.setEnabled(
            False
        )

        layout.addWidget(
            version_label
        )

        layout.addWidget(
            date_label
        )

        layout.addWidget(
            stage_label
        )

        layout.addWidget(
            download_button
        )

        self.window.verticalLayout_3.addWidget(
            card
        )

    # =========================================================
    # CARD CREATION
    # =========================================================

    def create_card(self):
        card = QFrame()

        card.setObjectName(
            "InterpreterCard"
        )

        card.setFrameShape(
            QFrame.Shape.StyledPanel
        )

        card.setFrameShadow(
            QFrame.Shadow.Raised
        )

        return card

    def add_message(self, message):
        label = QLabel(message)

        label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.window.verticalLayout_3.addWidget(
            label
        )

    # =========================================================
    # SELECTION
    # =========================================================

    def select_specific_interpreter(
        self,
        interpreter,
    ):
        self.selected_interpreter = (
            interpreter
        )

        self.window.accept()

    def select_interpreter(self):
        if self.selected_interpreter is None:
            return

        self.window.accept()

    def get_selected_interpreter(self):
        return self.selected_interpreter

    # =========================================================
    # WINDOW
    # =========================================================

    def show(self):
        self.window.show()


# =============================================================
# DIRECT TEST
# =============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)

    manager = InterpreterManager()

    manager.window.exec()

    selected = (
        manager.get_selected_interpreter()
    )

    if selected:
        print(
            "Selected interpreter:"
        )

        print(
            selected["path"]
        )

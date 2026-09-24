
import os
import sys
import tempfile

from PySide6.QtCore import (
    QFile,
    QObject,
    QProcess,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from python_parser import PythonParser


class ProjectEditor(QObject):
    def __init__(self):
        super().__init__()

        self.window = self.load_ui("ProjectWindow.ui")

        if self.window is None:
            raise RuntimeError(
                "Failed to load ProjectWindow.ui"
            )

        self.parser = PythonParser()

        self.process = None
        self.temp_file = None

        self.connect_actions()

        self.write_terminal(
            "pyForge Project Editor started."
        )

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

    def load_ui(self, path):
        ui_file = QFile(path)

        if not ui_file.open(
            QFile.OpenModeFlag.ReadOnly
        ):
            print(f"Failed to open UI file: {path}")
            return None

        loader = QUiLoader()
        loader.registerCustomWidget(
            PythonCodeEditor
        )

        window = loader.load(ui_file)

        ui_file.close()

        if window is None:
            print(f"Failed to load UI file: {path}")

        return window

    # --------------------------------------------------
    # Actions
    # --------------------------------------------------

    def connect_actions(self):
        self.window.actionRun.triggered.connect(
            self.run_current_editor
        )

        self.window.actionStop.triggered.connect(
            self.stop_process
        )

    # --------------------------------------------------
    # Current editor
    # --------------------------------------------------

    def get_current_editor(self):
        tabs = self.window.MainEditorTabs

        current_tab = tabs.currentWidget()

        if current_tab is None:
            return None

        return current_tab.findChild(
            PythonCodeEditor
        )

    # --------------------------------------------------
    # Run
    # --------------------------------------------------

    def run_current_editor(self):
        editor = self.get_current_editor()

        if editor is None:
            self.write_terminal(
                "No editor is currently selected."
            )
            return

        source = editor.toPlainText()

        if not source.strip():
            self.write_terminal(
                "Nothing to run."
            )
            return

        # Don't allow multiple processes
        if self.process is not None:
            if self.process.state() != (
                QProcess.ProcessState.NotRunning
            ):
                self.write_terminal(
                    "A process is already running."
                )
                return

        # Parse ONLY when Run is pressed
        result = self.parser.parse(source)

        if not result["success"]:
            self.show_problem(
                result["error"]
            )

            self.write_terminal(
                "Run cancelled because the script "
                "contains syntax errors."
            )

            return

        # Clear previous Problems only after
        # successfully beginning a new run.
        self.clear_problems()

        # --------------------------------------------------
        # Create temporary Python file
        # --------------------------------------------------

        try:
            temp = tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                encoding="utf-8",
            )

            temp.write(source)
            temp.close()

            self.temp_file = temp.name

        except Exception as error:
            self.show_problem({
                "message": str(error),
                "line": None,
                "column": None,
            })

            return

        # --------------------------------------------------
        # Prepare console
        # --------------------------------------------------

        self.window.Console.clear()

        self.write_terminal(
            f"Running {os.path.basename(self.temp_file)}..."
        )

        # --------------------------------------------------
        # Create QProcess
        # --------------------------------------------------

        self.process = QProcess(self)

        self.process.setProgram(
            sys.executable
        )

        self.process.setArguments([
            self.temp_file
        ])

        self.process.setWorkingDirectory(
            os.path.dirname(self.temp_file)
        )

        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

        self.process.readyReadStandardOutput.connect(
            self.read_stdout
        )

        self.process.readyReadStandardError.connect(
            self.read_stderr
        )

        self.process.finished.connect(
            self.process_finished
        )

        self.process.errorOccurred.connect(
            self.process_error
        )

        self.process.start()

    # --------------------------------------------------
    # Standard output → Console
    # --------------------------------------------------

    def read_stdout(self):
        if self.process is None:
            return

        data = self.process.readAllStandardOutput()

        text = bytes(data).decode(
            "utf-8",
            errors="replace",
        )

        if text:
            self.write_console(text)

    # --------------------------------------------------
    # Standard error → Problems
    # --------------------------------------------------

    def read_stderr(self):
        if self.process is None:
            return

        data = self.process.readAllStandardError()

        text = bytes(data).decode(
            "utf-8",
            errors="replace",
        )

        if text:
            self.write_problem_text(text)

    # --------------------------------------------------
    # Process finished
    # --------------------------------------------------

    def process_finished(
        self,
        exit_code,
        exit_status,
    ):
        if exit_status == (
            QProcess.ExitStatus.NormalExit
        ):
            if exit_code == 0:
                self.write_terminal(
                    "Process finished successfully."
                )
            else:
                self.write_terminal(
                    f"Process exited with code "
                    f"{exit_code}."
                )
        else:
            self.write_terminal(
                "Process crashed."
            )

        self.cleanup_process()

    # --------------------------------------------------
    # Process errors
    # --------------------------------------------------

    def process_error(self, error):
        if self.process is None:
            return

        if error == (
            QProcess.ProcessError.FailedToStart
        ):
            self.write_problem_text(
                self.process.errorString()
            )

            self.write_terminal(
                "Failed to start Python process."
            )

    # --------------------------------------------------
    # Console
    # --------------------------------------------------

    def write_console(self, text):
        console = self.window.Console

        cursor = console.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        console.setTextCursor(cursor)
        console.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        console.setTextCursor(cursor)

    # --------------------------------------------------
    # Problems
    # --------------------------------------------------

    def clear_problems(self):
        self.window.problems.clear()

    def show_problem(self, error):
        problems = self.window.problems

        problems.clear()

        message = error["message"]
        line = error["line"]
        column = error["column"]

        if line is not None:
            if column is not None:
                problems.appendPlainText(
                    f"Line {line}, Column {column}: "
                    f"{message}"
                )
            else:
                problems.appendPlainText(
                    f"Line {line}: {message}"
                )
        else:
            problems.appendPlainText(
                message
            )

        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ProblemsTab
        )

    def write_problem_text(self, text):
        problems = self.window.problems

        cursor = problems.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        problems.setTextCursor(cursor)
        problems.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        problems.setTextCursor(cursor)

        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ProblemsTab
        )

    # --------------------------------------------------
    # Terminal
    # --------------------------------------------------

    def write_terminal(self, message):
        self.window.Terminal.appendPlainText(
            message.rstrip("\n")
        )

    # --------------------------------------------------
    # Stop
    # --------------------------------------------------

    def stop_process(self):
        if self.process is None:
            return

        if self.process.state() == (
            QProcess.ProcessState.NotRunning
        ):
            return

        self.process.kill()

        self.write_terminal(
            "Process stopped."
        )

    # --------------------------------------------------
    # Cleanup
    # --------------------------------------------------

    def cleanup_process(self):
        if self.process is not None:
            self.process.deleteLater()
            self.process = None

        if self.temp_file is not None:
            try:
                if os.path.exists(
                    self.temp_file
                ):
                    os.remove(
                        self.temp_file
                    )
            except OSError:
                pass

            self.temp_file = None

    # --------------------------------------------------
    # Window
    # --------------------------------------------------

    def show(self):
        self.window.show()

import os
import sys
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QProcess,
    QEvent,
    Qt,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from python_parser import PythonParser


class ScriptEditor(QObject):
    def __init__(self):
        super().__init__()

        # =========================================================
        # Load UI
        # =========================================================

        loader = QUiLoader()
        loader.registerCustomWidget(PythonCodeEditor)

        ui_path = (
            Path(__file__).resolve().parent
            / "Script_Editor.ui"
        )

        self.window = loader.load(str(ui_path))

        if self.window is None:
            raise RuntimeError(
                "Failed to load Script_Editor.ui"
            )

        # =========================================================
        # Widgets
        # =========================================================

        self.editor = self.window.findChild(
            PythonCodeEditor,
            "CodeEditor"
        )

        self.console = self.window.findChild(
            type(self.window.Console),
            "Console"
        )

        self.terminal = self.window.findChild(
            type(self.window.Terminal),
            "Terminal"
        )

        self.problems = self.window.findChild(
            type(self.window.problems),
            "problems"
        )

        if self.editor is None:
            raise RuntimeError(
                "Could not find CodeEditor in Script_Editor.ui"
            )

        if self.console is None:
            raise RuntimeError(
                "Could not find Console in Script_Editor.ui"
            )

        if self.terminal is None:
            raise RuntimeError(
                "Could not find Terminal in Script_Editor.ui"
            )

        if self.problems is None:
            raise RuntimeError(
                "Could not find problems in Script_Editor.ui"
            )

        # =========================================================
        # State
        # =========================================================

        # Currently opened Python file.
        self.current_file = None

        # Process running the user's Python script.
        self.process = None

        # Persistent shell used by the Terminal.
        self.terminal_process = None

        # ---------------------------------------------------------
        # Console input boundary
        # ---------------------------------------------------------

        # Everything before this position is program output.
        self.input_start = 0

        # ---------------------------------------------------------
        # Terminal input boundary
        # ---------------------------------------------------------

        # Everything before this position is shell output.
        self.terminal_input_start = 0

        # =========================================================
        # Parser
        # =========================================================

        self.parser = PythonParser()

        # =========================================================
        # Menu actions
        # =========================================================

        self.window.actionSave.triggered.connect(
            self.save_file
        )

        self.window.actionSave_As.triggered.connect(
            self.save_as
        )

        self.window.actionOpen.triggered.connect(
            self.open_file
        )

        self.window.actionRun.triggered.connect(
            self.run_script
        )

        self.window.actionStop.triggered.connect(
            self.stop_script
        )

        # =========================================================
        # Editor
        # =========================================================

        self.editor.document().modificationChanged.connect(
            self.document_modified
        )

        # =========================================================
        # Console
        # =========================================================

        self.console.installEventFilter(self)

        # =========================================================
        # Terminal
        # =========================================================

        self.terminal.installEventFilter(self)

        # Start the shell.
        self.start_terminal()

        self.update_window_title()

    # =============================================================
    # Window
    # =============================================================

    def update_window_title(self):
        if self.current_file:
            filename = Path(
                self.current_file
            ).name
        else:
            filename = "Untitled"

        if self.editor.document().isModified():
            filename += "*"

        self.window.setWindowTitle(
            f"{filename} - Script Editor"
        )

    def document_modified(self, modified):
        self.update_window_title()

    # =============================================================
    # Save
    # =============================================================

    def save_file(self):
        if self.current_file is None:
            return self.save_as()

        try:
            Path(self.current_file).write_text(
                self.editor.toPlainText(),
                encoding="utf-8"
            )

            self.editor.document().setModified(False)

            self.update_window_title()

            return True

        except Exception as error:
            self.problems.appendPlainText(
                f"Save error: {error}"
            )

            self.window.TerminalTabWidget.setCurrentWidget(
                self.window.ProblemsTab
            )

            return False

    # =============================================================
    # Save As
    # =============================================================

    def save_as(self):
        default_name = "script.py"

        if self.current_file:
            default_name = Path(
                self.current_file
            ).name

        file_path, _ = QFileDialog.getSaveFileName(
            self.window,
            "Save Python Script",
            default_name,
            "Python Files (*.py);;All Files (*)"
        )

        if not file_path:
            return False

        if not Path(file_path).suffix:
            file_path += ".py"

        self.current_file = Path(file_path)

        return self.save_file()

    # =============================================================
    # Open
    # =============================================================

    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open Python Script",
            "",
            "Python Files (*.py);;All Files (*)"
        )

        if not file_path:
            return False

        try:
            source = Path(file_path).read_text(
                encoding="utf-8"
            )

            self.editor.setPlainText(source)

            self.current_file = Path(file_path)

            self.editor.document().setModified(False)

            self.problems.clear()
            self.console.clear()

            self.input_start = 0

            self.update_window_title()

            return True

        except Exception as error:
            self.problems.setPlainText(
                f"Open error:\n{error}"
            )

            self.window.TerminalTabWidget.setCurrentWidget(
                self.window.ProblemsTab
            )

            return False

    # =============================================================
    # Parser
    # =============================================================

    def parse_script(self):
        self.problems.clear()

        source = self.editor.toPlainText()

        result = self.parser.parse(source)

        if result["success"]:
            return True

        error = result["error"]

        line = error.get("line")
        column = error.get("column")
        message = error.get("message")

        self.problems.appendPlainText(
            f"SyntaxError: {message}"
        )

        if line is not None:
            self.problems.appendPlainText(
                f"Line: {line}, Column: {column}"
            )

        if error.get("text"):
            self.problems.appendPlainText(
                error["text"].rstrip()
            )

        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ProblemsTab
        )

        return False

    # =============================================================
    # Run Script
    # =============================================================

    def run_script(self):
        # ---------------------------------------------------------
        # Save first
        # ---------------------------------------------------------

        if not self.save_file():
            return

        # ---------------------------------------------------------
        # Parse
        # ---------------------------------------------------------

        if not self.parse_script():
            return

        # ---------------------------------------------------------
        # Stop previous script
        # ---------------------------------------------------------

        if self.process is not None:

            if self.process.state() != (
                QProcess.ProcessState.NotRunning
            ):
                self.process.kill()
                self.process.waitForFinished()

            self.process.deleteLater()
            self.process = None

        # ---------------------------------------------------------
        # Reset output
        # ---------------------------------------------------------

        self.console.clear()
        self.problems.clear()

        self.input_start = 0

        # =========================================================
        # Create Python process
        # =========================================================

        self.process = QProcess(self)

        self.process.setProgram(
            sys.executable
        )

        # -u gives us unbuffered stdout/stderr,
        # which makes print() and input() behave much
        # better inside the IDE.
        self.process.setArguments([
            "-u",
            str(self.current_file)
        ])

        self.process.setWorkingDirectory(
            str(Path(self.current_file).parent)
        )

        self.process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

        # ---------------------------------------------------------
        # Signals
        # ---------------------------------------------------------

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

        # ---------------------------------------------------------
        # Start
        # ---------------------------------------------------------

        self.process.start()

        # Switch to Console automatically.
        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ConsoleTab
        )

    # =============================================================
    # Stop Script
    # =============================================================

    def stop_script(self):
        if self.process is None:
            return

        if self.process.state() == (
            QProcess.ProcessState.NotRunning
        ):
            return

        self.process.kill()

        self.process.waitForFinished()

        self.write_terminal(
            "Python process stopped."
        )

    # =============================================================
    # Python stdout -> Console
    # =============================================================

    def read_stdout(self):
        if self.process is None:
            return

        data = self.process.readAllStandardOutput()

        text = bytes(data).decode(
            "utf-8",
            errors="replace"
        )

        if not text:
            return

        self.write_console(text)

        # Program output ends here.
        self.input_start = len(
            self.console.toPlainText()
        )

        self.console.ensureCursorVisible()

    # =============================================================
    # Python stderr -> Problems
    # =============================================================

    def read_stderr(self):
        if self.process is None:
            return

        data = self.process.readAllStandardError()

        text = bytes(data).decode(
            "utf-8",
            errors="replace"
        )

        if not text:
            return

        self.write_problem_text(text)

    # =============================================================
    # Python Process Finished
    # =============================================================

    def process_finished(
        self,
        exit_code,
        exit_status
    ):
        if exit_status == (
            QProcess.ExitStatus.NormalExit
        ):

            if exit_code == 0:
                self.write_terminal_output(
                    "Python process finished successfully."
                )

            else:
                self.write_terminal_output(
                    f"Python process exited with "
                    f"code {exit_code}."
                )

        else:
            self.write_terminal_output(
                "Python process crashed."
            )

        self.input_start = len(
            self.console.toPlainText()
        )

        if self.process is not None:
            self.process.deleteLater()
            self.process = None

    # =============================================================
    # Python Process Errors
    # =============================================================

    def process_error(self, error):
        if self.process is None:
            return

        if error == (
            QProcess.ProcessError.FailedToStart
        ):
            message = self.process.errorString()

            self.write_problem_text(
                message
            )

            self.write_terminal(
                "Failed to start Python process."
            )

    # =============================================================
    # Console Output
    # =============================================================

    def write_console(self, text):
        cursor = self.console.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.console.setTextCursor(cursor)

        self.console.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.console.setTextCursor(cursor)

    # =============================================================
    # Console Input
    # =============================================================

    def send_console_input(self):
        if self.process is None:
            return

        if self.process.state() != (
            QProcess.ProcessState.Running
        ):
            return

        # Always send from the end.
        cursor = self.console.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.console.setTextCursor(cursor)

        document = self.console.toPlainText()

        # Only text typed AFTER program output.
        user_input = document[
            self.input_start:
        ]

        self.process.write(
            (user_input + "\n").encode(
                "utf-8"
            )
        )

        # Show the submitted newline.
        self.console.insertPlainText(
            "\n"
        )

        self.input_start = len(
            self.console.toPlainText()
        )

        self.console.ensureCursorVisible()

    # =============================================================
    # Console Event Filter
    # =============================================================

    def handle_console_key(self, event):
        key = event.key()

        cursor = self.console.textCursor()

        # ---------------------------------------------------------
        # Enter
        # ---------------------------------------------------------

        if key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.send_console_input()
            return True

        # ---------------------------------------------------------
        # Backspace
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Backspace:

            if cursor.position() <= self.input_start:
                return True

        # ---------------------------------------------------------
        # Left
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Left:

            if cursor.position() <= self.input_start:
                return True

        # ---------------------------------------------------------
        # Home
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Home:

            cursor.setPosition(
                self.input_start
            )

            self.console.setTextCursor(
                cursor
            )

            return True

        # ---------------------------------------------------------
        # Delete
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Delete:

            if cursor.position() < self.input_start:
                return True

        return False

    # =============================================================
    # Terminal
    # =============================================================

    def start_terminal(self):
        """
        Start a persistent shell for the IDE Terminal.
        """

        if self.terminal_process is not None:
            return

        self.terminal.clear()

        self.terminal_process = QProcess(self)

        # ---------------------------------------------------------
        # Select shell
        # ---------------------------------------------------------

        if os.name == "nt":

            self.terminal_process.setProgram(
                os.environ.get(
                    "COMSPEC",
                    "cmd.exe"
                )
            )

            self.terminal_process.setArguments([
                "/Q"
            ])

        else:

            shell = os.environ.get(
                "SHELL",
                "/bin/bash"
            )

            self.terminal_process.setProgram(
                shell
            )

        self.terminal_process.setWorkingDirectory(
            str(Path.home())
        )

        self.terminal_process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

        # ---------------------------------------------------------
        # Signals
        # ---------------------------------------------------------

        self.terminal_process.readyReadStandardOutput.connect(
            self.read_terminal_stdout
        )

        self.terminal_process.readyReadStandardError.connect(
            self.read_terminal_stderr
        )

        self.terminal_process.finished.connect(
            self.terminal_finished
        )

        self.terminal_process.errorOccurred.connect(
            self.terminal_error
        )

        self.terminal_process.start()

    # =============================================================
    # Terminal stdout
    # =============================================================

    def read_terminal_stdout(self):
        if self.terminal_process is None:
            return

        data = (
            self.terminal_process
            .readAllStandardOutput()
        )

        text = bytes(data).decode(
            "utf-8",
            errors="replace"
        )

        if not text:
            return

        self.write_terminal_output(text)

        # Shell output ends here.
        self.terminal_input_start = len(
            self.terminal.toPlainText()
        )

        self.terminal.ensureCursorVisible()

    # =============================================================
    # Terminal stderr
    # =============================================================

    def read_terminal_stderr(self):
        if self.terminal_process is None:
            return

        data = (
            self.terminal_process
            .readAllStandardError()
        )

        text = bytes(data).decode(
            "utf-8",
            errors="replace"
        )

        if not text:
            return

        self.write_terminal_output(text)

        self.terminal_input_start = len(
            self.terminal.toPlainText()
        )

        self.terminal.ensureCursorVisible()
    
    
    # =============================================================
    # Terminal Process Finished
    # =============================================================

    def terminal_finished(
        self,
        exit_code,
        exit_status
    ):
        if exit_status == (
            QProcess.ExitStatus.NormalExit
        ):
            self.write_terminal_output(
                f"\nTerminal process exited "
                f"with code {exit_code}.\n"
            )
        else:
            self.write_terminal_output(
                "\nTerminal process crashed.\n"
            )

        self.terminal_process = None

    # =============================================================
    # Terminal Process Error
    # =============================================================

    def terminal_error(self, error):
        if self.terminal_process is None:
            return

        if error == (
            QProcess.ProcessError.FailedToStart
        ):
            self.write_terminal_output(
                "\nFailed to start terminal: "
                f"{self.terminal_process.errorString()}\n"
            )
    # =============================================================
    # Terminal Output
    # =============================================================

    def write_terminal_output(self, text):
        cursor = self.terminal.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.terminal.setTextCursor(cursor)

        self.terminal.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.terminal.setTextCursor(cursor)

    # =============================================================
    # Terminal Input
    # =============================================================

    def send_terminal_input(self):
        if self.terminal_process is None:
            return

        if self.terminal_process.state() != (
            QProcess.ProcessState.Running
        ):
            return

        # Always operate at the end.
        cursor = self.terminal.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.terminal.setTextCursor(cursor)

        document = self.terminal.toPlainText()

        # Only take text entered after shell output.
        command = document[
            self.terminal_input_start:
        ]

        self.terminal_process.write(
            (command + "\n").encode(
                "utf-8"
            )
        )

        # Visually submit the command.
        self.terminal.insertPlainText(
            "\n"
        )

        self.terminal_input_start = len(
            self.terminal.toPlainText()
        )

        self.terminal.ensureCursorVisible()

    # =============================================================
    # Terminal Event Filter
    # =============================================================

    def handle_terminal_key(self, event):
        key = event.key()

        cursor = self.terminal.textCursor()

        # ---------------------------------------------------------
        # Enter
        # ---------------------------------------------------------

        if key in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.send_terminal_input()
            return True

        # ---------------------------------------------------------
        # Backspace
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Backspace:

            if cursor.position() <= (
                self.terminal_input_start
            ):
                return True

        # ---------------------------------------------------------
        # Left
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Left:

            if cursor.position() <= (
                self.terminal_input_start
            ):
                return True

        # ---------------------------------------------------------
        # Home
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Home:

            cursor.setPosition(
                self.terminal_input_start
            )

            self.terminal.setTextCursor(
                cursor
            )

            return True

        # ---------------------------------------------------------
        # Delete
        # ---------------------------------------------------------

        if key == Qt.Key.Key_Delete:

            if cursor.position() < (
                self.terminal_input_start
            ):
                return True

        return False

    # =============================================================
    # Unified Event Filter
    # =============================================================

    def eventFilter(self, watched, event):

        if event.type() == QEvent.Type.KeyPress:

            # Console
            if watched is self.console:

                if self.handle_console_key(event):
                    return True

            # Terminal
            if watched is self.terminal:

                if self.handle_terminal_key(event):
                    return True

        return super().eventFilter(
            watched,
            event
        )

    # =============================================================
    # Problems
    # =============================================================

    def clear_problems(self):
        self.problems.clear()

    def write_problem_text(self, text):
        cursor = self.problems.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.problems.setTextCursor(cursor)

        self.problems.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        self.problems.setTextCursor(cursor)

        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ProblemsTab
        )

    # =============================================================
    # Stop / Cleanup
    # =============================================================

    def close_terminal(self):
        if self.terminal_process is None:
            return

        if self.terminal_process.state() != (
            QProcess.ProcessState.NotRunning
        ):
            self.terminal_process.kill()
            self.terminal_process.waitForFinished()

        self.terminal_process.deleteLater()
        self.terminal_process = None

    # =============================================================
    # Window
    # =============================================================

    def show(self):
        self.window.show()


# =================================================================
# Standalone Launch
# =================================================================

def main():
    app = QApplication(sys.argv)

    editor = ScriptEditor()
    editor.window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
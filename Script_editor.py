import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QObject, QEvent, QProcess, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QInputDialog, QMessageBox, QPlainTextEdit,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from python_parser import PythonParser

APP_DIR = Path(__file__).resolve().parent


class ScriptEditor(QObject):
    """Single-file editor for scripts opened outside a project."""

    def __init__(self, file_path=None):
        super().__init__()
        ui_path = APP_DIR / "Script_editor.ui"
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Could not open UI file: {ui_path}")
        try:
            loader = QUiLoader()
            loader.registerCustomWidget(PythonCodeEditor)
            self.window = loader.load(ui_file)
        finally:
            ui_file.close()
        if self.window is None:
            raise RuntimeError("Could not load Script_Editor.ui")

        self.editor = self.window.findChild(PythonCodeEditor, "CodeEditor")
        self.console = self.window.findChild(QPlainTextEdit, "Console")
        self.terminal = self.window.findChild(QPlainTextEdit, "Terminal")
        self.problems = self.window.findChild(QPlainTextEdit, "problems")
        self.parser = PythonParser()
        self.current_file = None
        self.standalone_editors = []  # child standalone windows launched from this one
        self.process = None
        self.terminal_process = None
        self.input_start = 0
        self.terminal_input_start = 0
        if not all((self.editor, self.console, self.terminal, self.problems)):
            raise RuntimeError("Script_Editor.ui is missing CodeEditor, Console, Terminal, or problems widgets")

        self.window.actionSave.triggered.connect(self.save_file)
        self.window.actionSave_As.triggered.connect(self.save_as)
        self.window.actionNewPS.triggered.connect(self.new_python_script)
        self.window.actionPython_Script.triggered.connect(self.open_file_dialog)
        self.window.actionPython_Project.triggered.connect(self.open_project_dialog)
        self.window.actionRun.triggered.connect(self.run_script)
        self.window.actionStop.triggered.connect(self.stop_script)
        self.window.actionUndo.triggered.connect(self.editor.undo)
        self.window.actionRedo.triggered.connect(self.editor.redo)
        self.editor.document().modificationChanged.connect(lambda _modified: self.update_title())
        self.console.installEventFilter(self)
        self.terminal.installEventFilter(self)
        self._start_terminal()

        if file_path:
            self.open_file(file_path)
        else:
            self.update_title()

    def update_title(self):
        name = self.current_file.name if self.current_file else "Untitled"
        if self.editor.document().isModified():
            name += " *"
        self.window.setWindowTitle(f"{name} - Script Editor")

    def new_python_script(self):
        """Create a standalone .py file at a chosen location and open it in a new window."""
        name, accepted = QInputDialog.getText(
            self.window,
            "New Python Script",
            "Script filename (e.g. script.py):",
        )
        if not accepted or not name.strip():
            return

        name = name.strip()
        if not name.lower().endswith(".py"):
            name += ".py"
        if Path(name).name != name or name in {".", "..", ".py"}:
            QMessageBox.warning(
                self.window,
                "Invalid Filename",
                "Enter a filename only, not a folder path.",
            )
            return

        folder = QFileDialog.getExistingDirectory(
            self.window,
            "Choose Where to Create the Python Script",
            str(Path.home()),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not folder:
            return

        path = (Path(folder).expanduser() / name).resolve()
        if path.exists():
            answer = QMessageBox.question(
                self.window,
                "File Already Exists",
                f"{path} already exists. Open it in a new Script Editor window?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                path.touch(exist_ok=False)
            except OSError as error:
                QMessageBox.critical(self.window, "Create Failed", str(error))
                return

        try:
            editor = ScriptEditor(file_path=path)
            self.standalone_editors.append(editor)
            editor.show()
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Script Editor Failed to Open",
                f"The script is at:\n{path}\n\nBut the editor could not open it:\n{error}",
            )

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self.window, "Open Python Script", str(Path.home()), "Python Files (*.py);;All Files (*)")
        if path:
            self.open_file(path)

    def open_file(self, path):
        target = Path(path).expanduser().resolve()
        try:
            source = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(self.window, "Open Failed", str(error))
            return False
        if self.editor.document().isModified():
            answer = QMessageBox.question(
                self.window, "Unsaved Changes", "Save changes to the current script first?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save and not self.save_file():
                return False
        self.current_file = target
        self.editor.setPlainText(source)
        self.editor.document().setModified(False)
        self.console.clear()
        self.problems.clear()
        self.input_start = 0
        self.update_title()
        return True

    def save_file(self):
        if self.current_file is None:
            return self.save_as()
        try:
            self.current_file.write_text(self.editor.toPlainText(), encoding="utf-8")
            self.editor.document().setModified(False)
            self.update_title()
            self.write_terminal(f"Saved {self.current_file}\n")
            return True
        except OSError as error:
            QMessageBox.critical(self.window, "Save Failed", str(error))
            return False

    def save_as(self):
        default = str(self.current_file or (Path.home() / "script.py"))
        path, _ = QFileDialog.getSaveFileName(self.window, "Save Python Script As", default, "Python Files (*.py);;All Files (*)")
        if not path:
            return False
        target = Path(path).expanduser()
        if not target.suffix:
            target = target.with_suffix(".py")
        self.current_file = target.resolve()
        return self.save_file()

    def open_project_dialog(self):
        folder = QFileDialog.getExistingDirectory(self.window, "Open Python Project", str(Path.home()))
        if not folder:
            return
        try:
            from Project_Editor import ProjectEditor
            self.project_editor = ProjectEditor(project_path=folder)
            self.project_editor.show()
        except Exception as error:
            QMessageBox.critical(self.window, "Open Project Failed", str(error))

    def run_script(self):
        if not self.save_file():
            return
        result = self.parser.parse(self.editor.toPlainText())
        if not result.get("success", False):
            error = result.get("error", {})
            self.problems.setPlainText(
                f"Syntax error at line {error.get('line')}, column {error.get('column')}: {error.get('message', 'Invalid syntax')}"
            )
            self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)
            return
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        self.console.clear()
        self.problems.clear()
        self.input_start = 0
        self.process = QProcess(self)
        self.process.setProgram(sys.executable)
        self.process.setArguments(["-u", str(self.current_file)])
        self.process.setWorkingDirectory(str(self.current_file.parent))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.start()
        self.window.TerminalTabWidget.setCurrentWidget(self.window.ConsoleTab)

    def stop_script(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.write_terminal("Python process stopped.\n")

    def _read_stdout(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            if text:
                self._append(self.console, text)
                self.input_start = len(self.console.toPlainText())

    def _read_stderr(self):
        if self.process:
            text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            if text:
                self._append(self.problems, text)
                self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    def _process_finished(self, code, status):
        label = "finished" if status == QProcess.ExitStatus.NormalExit else "crashed"
        self.write_terminal(f"Python process {label} (exit code {code}).\n")
        if self.process:
            self.process.deleteLater()
            self.process = None

    def _process_error(self, _error):
        if self.process:
            self._append(self.problems, self.process.errorString() + "\n")
            self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    @staticmethod
    def _append(widget, text):
        cursor = widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        widget.setTextCursor(cursor)
        widget.insertPlainText(text)
        widget.ensureCursorVisible()

    def write_terminal(self, text):
        self._append(self.terminal, text)
        self.terminal_input_start = len(self.terminal.toPlainText())

    def _start_terminal(self):
        self.terminal.clear()
        self.terminal_process = QProcess(self)
        if os.name == "nt":
            self.terminal_process.setProgram(os.environ.get("COMSPEC", "cmd.exe"))
            self.terminal_process.setArguments(["/Q"])
        else:
            self.terminal_process.setProgram(os.environ.get("SHELL", "/bin/bash"))
            self.terminal_process.setArguments(["-i"])
        self.terminal_process.setWorkingDirectory(str(self.current_file.parent if self.current_file else Path.home()))
        self.terminal_process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.terminal_process.readyReadStandardOutput.connect(self._read_terminal)
        self.terminal_process.readyReadStandardError.connect(self._read_terminal)
        self.terminal_process.start()

    def _read_terminal(self):
        if self.terminal_process:
            data = self.terminal_process.readAllStandardOutput() + self.terminal_process.readAllStandardError()
            text = bytes(data).decode("utf-8", errors="replace")
            if text:
                self.write_terminal(text)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched is self.console:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._send_console_input()
                    return True
                if event.key() == Qt.Key.Key_Backspace and self.console.textCursor().position() <= self.input_start:
                    return True
                if event.key() == Qt.Key.Key_Home:
                    cursor = self.console.textCursor(); cursor.setPosition(self.input_start); self.console.setTextCursor(cursor)
                    return True
            if watched is self.terminal:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._send_terminal_input()
                    return True
                if event.key() == Qt.Key.Key_Backspace and self.terminal.textCursor().position() <= self.terminal_input_start:
                    return True
                if event.key() == Qt.Key.Key_Home:
                    cursor = self.terminal.textCursor(); cursor.setPosition(self.terminal_input_start); self.terminal.setTextCursor(cursor)
                    return True
        return super().eventFilter(watched, event)

    def _send_console_input(self):
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return
        cursor = self.console.textCursor(); cursor.movePosition(cursor.MoveOperation.End); self.console.setTextCursor(cursor)
        text = self.console.toPlainText()[self.input_start:]
        self.console.insertPlainText("\n")
        self.process.write((text + "\n").encode("utf-8"))
        self.input_start = len(self.console.toPlainText())

    def _send_terminal_input(self):
        if not self.terminal_process or self.terminal_process.state() != QProcess.ProcessState.Running:
            return
        cursor = self.terminal.textCursor(); cursor.movePosition(cursor.MoveOperation.End); self.terminal.setTextCursor(cursor)
        command = self.terminal.toPlainText()[self.terminal_input_start:]
        self.terminal.insertPlainText("\n")
        self.terminal_process.write((command + "\n").encode("utf-8"))
        self.terminal_input_start = len(self.terminal.toPlainText())

    def show(self):
        self.window.show()

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        if self.terminal_process and self.terminal_process.state() != QProcess.ProcessState.NotRunning:
            self.terminal_process.kill()
        event.accept()


def main():
    app = QApplication(sys.argv)
    editor = ScriptEditor()
    editor.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

"""PyForge standalone Python script editor."""

import ast
import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QEvent, QObject, QProcess, Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox, QPlainTextEdit, QTabWidget, QWidget
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from Core.window_registry import retain_window, switch_window

BASE_DIR = Path(__file__).resolve().parent


def _load_script_ui():
    # Linux paths are case-sensitive. Support both historical spellings.
    candidates = (BASE_DIR / "Script_editor.ui", BASE_DIR / "Script_Editor.ui")
    ui_path = next((path for path in candidates if path.is_file()), None)
    if ui_path is None:
        raise FileNotFoundError(
            "Could not find Script_editor.ui or Script_Editor.ui beside Script_editor.py"
        )
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"Cannot open UI file: {ui_path}")
    try:
        loader = QUiLoader()
        loader.registerCustomWidget(PythonCodeEditor)
        window = loader.load(ui_file)
        if window is None:
            raise RuntimeError(f"Qt could not load UI file: {ui_path}")
        # QUiLoader returns a QObject tree, not a generated Ui_MainWindow.
        # Attach named children so the rest of this class can access them safely.
        for child in window.findChildren(QObject):
            name = child.objectName()
            if name and not hasattr(window, name):
                setattr(window, name, child)
        return window
    finally:
        ui_file.close()


def _connect_if_present(window, names, callback):
    """Connect all matching UI action aliases, avoiding duplicate connections."""
    connected = []
    seen = set()
    for name in names:
        action = getattr(window, name, None)
        if action is not None and id(action) not in seen:
            action.triggered.connect(callback)
            connected.append(action)
            seen.add(id(action))
    return connected[0] if connected else None


class ScriptEditor(QObject):
    def __init__(self, file_path=None):
        super().__init__()

        # Script Editor is for standalone Python files, not project manifests.
        validated_path = None
        if file_path is not None:
            validated_path = Path(file_path).expanduser().resolve()
            if validated_path.suffix.lower() != ".py":
                raise ValueError(
                    "Script Editor only opens standalone Python (.py) files. "
                    "Open project manifests and project folders in Project Editor."
                )
            if not validated_path.exists():
                raise FileNotFoundError(
                    f"The Python script does not exist:\n{validated_path}"
                )
            if not validated_path.is_file():
                raise IsADirectoryError(
                    f"Expected a Python script file, not a directory:\n{validated_path}"
                )

        self.window = _load_script_ui()
        self.window.installEventFilter(self)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.editor = self.window.findChild(PythonCodeEditor, "CodeEditor")
        if self.editor is None:
            raise RuntimeError("Could not find CodeEditor in Script_editor.ui")

        # Resolve child widgets by Qt object name instead of dynamic attributes.
        self.console = self.window.findChild(QPlainTextEdit, "Console")
        self.terminal = self.window.findChild(QPlainTextEdit, "Terminal")
        self.problems = self.window.findChild(QPlainTextEdit, "problems")
        self.statusbar = self.window.statusBar()
        self.terminal_tabs = self.window.findChild(QTabWidget, "TerminalTabWidget")
        self.problems_tab = self.window.findChild(QWidget, "ProblemsTab")
        self.console_tab = self.window.findChild(QWidget, "ConsoleTab")
        if any(widget is None for widget in (self.console, self.terminal, self.problems, self.terminal_tabs, self.problems_tab, self.console_tab)):
            raise RuntimeError("Script_editor.ui is missing a required console, terminal, or tab widget.")

        self.current_file = None
        self._dirty = False
        self._loading = False
        self._child_windows = []
        self.process = None
        self.terminal_process = None
        self._console_input_start = 0
        self._terminal_input_start = 0

        _connect_if_present(self.window, ("actionSave",), self.save_file)
        _connect_if_present(self.window, ("actionSave_As",), self.save_as)
        _connect_if_present(self.window, ("actionOpen", "actionPython_Script"), self.open_file_dialog)
        _connect_if_present(self.window, ("actionRun",), self.run_script)
        _connect_if_present(self.window, ("actionStop",), self.stop_script)
        _connect_if_present(self.window, ("actionNewPS",), self.new_standalone_script)
        _connect_if_present(self.window, ("actionNew_PA", "actionNewProject", "actionNewPythonApplication", "actionNewPythonProject"), self.new_python_application)
        _connect_if_present(self.window, ("actionPython_Project", "actionPython_Projet"), self.open_project_dialog)
        _connect_if_present(self.window, ("actionUndo",), self.editor.undo)
        _connect_if_present(self.window, ("actionRedo",), self.editor.redo)

        self.editor.textChanged.connect(self._mark_dirty)
        self.console.installEventFilter(self)
        self.terminal.installEventFilter(self)
        self.window.destroyed.connect(self._cleanup_processes)

        if validated_path is not None and not self.load_file(validated_path):
            raise OSError(f"Could not load standalone script: {validated_path}")
        self._start_terminal()
        self._update_title()

    # ----- title / dirty state --------------------------------------------
    def _mark_dirty(self):
        if not self._loading:
            self._dirty = True
            self._update_title()

    def _update_title(self):
        name = self.current_file.name if self.current_file else "Untitled.py"
        marker = " *" if self._dirty else ""
        self.window.setWindowTitle(f"{name}{marker} - PyForge Script Editor")

    # ----- file operations -------------------------------------------------
    def load_file(self, file_path):
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self.window, "Open Failed", f"File does not exist:\n{path}")
            return False
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(self.window, "Open Failed", str(error))
            return False
        self._loading = True
        self.editor.setPlainText(content)
        self.editor.document().setModified(False)
        self._loading = False
        self.current_file = path
        self._dirty = False
        self._update_title()
        self.statusbar.showMessage(f"Opened {path}", 4000)
        return True

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Open Python Script", str(self.current_file.parent if self.current_file else Path.home()),
            "Python Files (*.py)",
        )
        if path:
            if self._confirm_discard_or_save() and self.load_file(path):
                return

    def save_file(self):
        if self.current_file is None:
            return self.save_as()
        return self._write_file(self.current_file)

    def save_as(self):
        start = str(self.current_file) if self.current_file else str(Path.home() / "untitled.py")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Save Python Script As", start,
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return False
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".py":
            target = target.with_suffix(".py")
        return self._write_file(target)

    def _write_file(self, path):
        path = Path(path).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self.window, "Save Failed", str(error))
            return False
        self.current_file = path
        self._dirty = False
        self.editor.document().setModified(False)
        self._update_title()
        self.statusbar.showMessage(f"Saved {path}", 4000)
        return True

    def _confirm_discard_or_save(self):
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self.window, "Unsaved Changes", "Save changes before continuing?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_file()
        return True

    def new_standalone_script(self):
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Create Standalone Python Script", str(Path.home() / "untitled.py"),
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".py":
            target = target.with_suffix(".py")
        if target.exists():
            answer = QMessageBox.question(
                self.window, "File Exists", f"{target.name} already exists. Open it?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.touch(exist_ok=False)
            except OSError as error:
                QMessageBox.critical(self.window, "Create Failed", str(error))
                return
        self._open_child_script_editor(target)

    def _open_child_script_editor(self, path):
        try:
            child = ScriptEditor(file_path=str(path))
            self._child_windows.append(child)
            retain_window(child)
            child.window.destroyed.connect(
                lambda *_args, obj=child: self._forget_child(obj)
            )
            if not switch_window(self, child):
                return None
            return child
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Could Not Open Python Script",
                f"PyForge could not open the standalone script editor.\n\n{error}",
            )
            return None

    def new_python_application(self):
        # Import locally to avoid the ProjectCreator/ProjectEditor import cycle.
        from Project_Creator import ProjectCreator
        try:
            creator = ProjectCreator()
            self._child_windows.append(creator)
            retain_window(creator)
            creator.window.destroyed.connect(
                lambda *_args, obj=creator: self._forget_child(obj)
            )
            if not switch_window(self, creator):
                return
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Project Creator Failed",
                f"Could not open the project creation window.\n\n{error}",
            )

    def _forget_child(self, child):
        try:
            self._child_windows.remove(child)
        except ValueError:
            pass

    def open_project_dialog(self):
        project_path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open PyForge Project",
            str(self.current_file.parent if self.current_file else Path.home()),
            "PyForge Projects (*.forproj);;Legacy Project Metadata (*.json);;All Files (*)",
        )
        if not project_path:
            return
        from Project_Editor import ProjectEditor
        from Core.diagnostics import log_event, log_exception
        try:
            log_event(f"Creating Project Editor for {project_path}")
            child = ProjectEditor(project_path)
            retain_window(child)
            if not hasattr(self, "_project_windows"):
                self._project_windows = []
            self._project_windows.append(child)
            child.window.destroyed.connect(lambda *_args, obj=child: self._forget_project(obj))
            if not switch_window(self, child):
                return
        except Exception as error:
            log_exception(f"Could not open project {project_path}", error)
            QMessageBox.critical(self.window, "Open Project Failed", str(error))
            return

    def _forget_project(self, child):
        try:
            self._project_windows.remove(child)
        except (AttributeError, ValueError):
            pass

    # ----- run / stop ------------------------------------------------------
    def _python_executable(self):
        if self.current_file:
            for parent in (self.current_file.parent, *self.current_file.parents):
                for candidate in (
                    parent / ".venv" / "Scripts" / "python.exe",
                    parent / ".venv" / "bin" / "python",
                    parent / "venv" / "Scripts" / "python.exe",
                    parent / "venv" / "bin" / "python",
                ):
                    if candidate.is_file():
                        return str(candidate)
        return sys.executable

    def run_script(self):
        if not self.save_file():
            return
        try:
            ast.parse(self.editor.toPlainText(), filename=str(self.current_file))
        except SyntaxError as error:
            self.problems.setPlainText(f"Line {error.lineno}, column {error.offset}: {error.msg}")
            self.terminal_tabs.setCurrentWidget(self.problems_tab)
            return
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self._terminal_write("A script is already running. Stop it first.\n")
            return
        self.console.clear()
        self._console_input_start = 0
        self.terminal_tabs.setCurrentWidget(self.console_tab)
        process = QProcess(self)
        self.process = process
        process.setProgram(self._python_executable())
        process.setArguments(["-u", str(self.current_file)])
        process.setWorkingDirectory(str(self.current_file.parent))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self._terminal_write(f"Running {self.current_file.name}...\n")
        process.start()

    def _read_stdout(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            if text:
                self._console_write(text)

    def _read_stderr(self):
        if self.process:
            text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            if text:
                self.problems.appendPlainText(text.rstrip("\n"))
                self.terminal_tabs.setCurrentWidget(self.problems_tab)

    def _process_finished(self, exit_code, exit_status):
        message = f"Process finished with exit code {exit_code}.\n" if exit_status == QProcess.ExitStatus.NormalExit else "Process crashed.\n"
        self._terminal_write(message)
        process, self.process = self.process, None
        if process:
            process.deleteLater()

    def _process_error(self, error):
        if self.process and error == QProcess.ProcessError.FailedToStart:
            QMessageBox.critical(self.window, "Run Failed", self.process.errorString())

    def stop_script(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
            self._terminal_write("Script stopped.\n")

    # ----- console / terminal ---------------------------------------------
    def _console_write(self, text):
        cursor = self.console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.console.setTextCursor(cursor)
        self.console.insertPlainText(text)
        self.console.ensureCursorVisible()
        self._console_input_start = len(self.console.toPlainText())

    def _terminal_write(self, text):
        cursor = self.terminal.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.terminal.setTextCursor(cursor)
        self.terminal.insertPlainText(text)
        self.terminal.ensureCursorVisible()
        self._terminal_input_start = len(self.terminal.toPlainText())

    def _start_terminal(self):
        shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else os.environ.get("SHELL", "/bin/bash")
        process = QProcess(self)
        self.terminal_process = process
        process.setProgram(shell)
        if os.name == "nt":
            process.setArguments(["/Q"])
        elif Path(shell).name == "bash":
            # Do not load arbitrary interactive shell plugins during startup.
            # Slow prompt managers or shell hooks can make the editor appear frozen.
            process.setArguments(["--noprofile", "--norc", "-i"])
        else:
            process.setArguments(["-i"])
        process.setWorkingDirectory(str(self.current_file.parent if self.current_file else Path.home()))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_terminal_output)
        process.readyReadStandardError.connect(self._read_terminal_output)
        process.errorOccurred.connect(self._terminal_error)
        process.start()

    def _read_terminal_output(self):
        if not self.terminal_process:
            return
        process = self.terminal_process
        data = bytes(process.readAllStandardOutput()) + bytes(process.readAllStandardError())
        if data:
            self._terminal_write(data.decode("utf-8", errors="replace"))

    def _terminal_error(self, error):
        if error == QProcess.ProcessError.FailedToStart and self.terminal_process:
            self._terminal_write(f"Could not start terminal: {self.terminal_process.errorString()}\n")

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() == QEvent.Type.Close:
            if not self._confirm_discard_or_save():
                event.ignore()
                return True
            self._cleanup_processes()
            return False

        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if watched is self.console and self.process and self.process.state() == QProcess.ProcessState.Running:
                cursor = self.console.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.console.setTextCursor(cursor)
                value = self.console.toPlainText()[self._console_input_start:]
                self.console.insertPlainText("\n")
                self._console_input_start = len(self.console.toPlainText())
                self.process.write((value + "\n").encode("utf-8"))
                return True
            if watched is self.terminal and self.terminal_process and self.terminal_process.state() == QProcess.ProcessState.Running:
                cursor = self.terminal.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.terminal.setTextCursor(cursor)
                value = self.terminal.toPlainText()[self._terminal_input_start:]
                self.terminal.insertPlainText("\n")
                self._terminal_input_start = len(self.terminal.toPlainText())
                self.terminal_process.write((value + "\n").encode("utf-8"))
                return True
        return super().eventFilter(watched, event)

    # ----- lifecycle -------------------------------------------------------
    def show(self):
        self.window.show()

    def _cleanup_processes(self, *_args):
        for process in (self.process, self.terminal_process):
            if process and process.state() != QProcess.ProcessState.NotRunning:
                process.kill()



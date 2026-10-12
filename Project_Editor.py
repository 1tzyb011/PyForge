import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QObject, QDir, QEvent, QProcess, Qt
from PySide6.QtWidgets import (
    QFileDialog, QFileSystemModel, QInputDialog, QMessageBox,
    QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from python_parser import PythonParser
from Script_editor import ScriptEditor

APP_DIR = Path(__file__).resolve().parent


class ProjectEditor(QObject):
    """Project-aware editor for a PyForge project directory."""

    def __init__(self, project_path=None):
        super().__init__()
        self.project_root = Path(project_path or Path.cwd()).expanduser().resolve()
        if not self.project_root.is_dir():
            raise NotADirectoryError(f"Project folder does not exist: {self.project_root}")

        self.window = self._load_ui(APP_DIR / "ProjectWindow.ui")
        if self.window is None:
            raise RuntimeError("Could not load ProjectWindow.ui")

        self.parser = PythonParser()
        self.file_model = None
        self.open_files = {}  # resolved path -> editor widget
        self.standalone_editors = []  # keep standalone windows alive
        self.process = None
        self.terminal_process = None
        self.input_start = 0
        self.terminal_input_start = 0

        self._connect_actions()
        self._setup_project_tree()
        self._setup_tabs()
        self.window.Console.installEventFilter(self)
        self.window.Terminal.installEventFilter(self)
        self._start_terminal()
        self.window.setWindowTitle(f"{self.project_root.name} - PyForge Project Editor")

        main_file = self.project_root / "main.py"
        if main_file.is_file():
            self.open_file(main_file)
        else:
            self._new_untitled_tab()
        self.write_terminal_output(f"Project: {self.project_root}\n")

    @staticmethod
    def _load_ui(path):
        ui_file = QFile(str(path))
        if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
            return None
        try:
            loader = QUiLoader()
            loader.registerCustomWidget(PythonCodeEditor)
            return loader.load(ui_file)
        finally:
            ui_file.close()

    def _connect_actions(self):
        self.window.actionRun.triggered.connect(self.run_current_file)
        self.window.actionStop.triggered.connect(self.stop_process)
        self.window.actionSave.triggered.connect(self.save_current_file)
        self.window.actionSave_As.triggered.connect(self.save_file_as)
        self.window.actionNewPS.triggered.connect(self.new_python_script)
        self.window.actionPython_Script.triggered.connect(self.open_file_dialog)
        self.window.actionPython_Projet.triggered.connect(self.open_project_dialog)
        self.window.actionUndo.triggered.connect(self.undo_current_editor)
        self.window.actionRedo.triggered.connect(self.redo_current_editor)
        self.window.treeView.doubleClicked.connect(self.open_tree_item)

    def _setup_project_tree(self):
        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(
            QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot
        )
        self.file_model.setRootPath(str(self.project_root))
        tree = self.window.treeView
        tree.setModel(self.file_model)
        tree.setRootIndex(self.file_model.index(str(self.project_root)))
        for column in range(1, self.file_model.columnCount()):
            tree.hideColumn(column)

    def _setup_tabs(self):
        tabs = self.window.MainEditorTabs
        while tabs.count():
            widget = tabs.widget(0)
            tabs.removeTab(0)
            widget.deleteLater()
        tabs.setTabsClosable(True)
        tabs.tabCloseRequested.connect(self.close_editor_tab)

    def _new_untitled_tab(self):
        self._create_tab(None, "")

    def _create_tab(self, path=None, source=""):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        editor = PythonCodeEditor(container)
        editor.setPlainText(source)
        editor.document().setModified(False)
        layout.addWidget(editor)
        container.setProperty("file_path", str(path) if path else "")
        editor.document().modificationChanged.connect(
            lambda _modified, tab=container: self._update_tab_title(tab)
        )
        title = Path(path).name if path else "Untitled"
        index = self.window.MainEditorTabs.addTab(container, title)
        self.window.MainEditorTabs.setCurrentIndex(index)
        if path:
            self.open_files[Path(path).resolve()] = editor
        return editor

    def _update_tab_title(self, tab):
        tabs = self.window.MainEditorTabs
        index = tabs.indexOf(tab)
        if index < 0:
            return
        path_text = tab.property("file_path")
        title = Path(path_text).name if path_text else "Untitled"
        editor = tab.findChild(PythonCodeEditor)
        if editor and editor.document().isModified():
            title += " *"
        tabs.setTabText(index, title)

    def get_current_tab(self):
        return self.window.MainEditorTabs.currentWidget()

    def get_current_editor(self):
        tab = self.get_current_tab()
        return tab.findChild(PythonCodeEditor) if tab else None

    def _current_path(self):
        tab = self.get_current_tab()
        value = tab.property("file_path") if tab else ""
        return Path(value).resolve() if value else None

    def open_file_dialog(self):
        """Open a selected standalone Python file in its own Script Editor window."""
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open Python Script",
            str(Path.home()),
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return

        target = Path(path).expanduser().resolve()
        if not target.is_file():
            QMessageBox.warning(
                self.window, "File Not Found", f"Cannot open:\n{target}"
            )
            return

        # If this file already has a standalone window, focus that one instead
        # of creating duplicate windows for the same file.
        for editor in self.standalone_editors:
            if editor.current_file and editor.current_file.resolve() == target:
                editor.show()
                editor.window.raise_()
                editor.window.activateWindow()
                return

        try:
            editor = ScriptEditor(file_path=target)
            self.standalone_editors.append(editor)  # keep the QObject alive
            editor.show()
            editor.window.raise_()
            editor.window.activateWindow()
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Script Editor Failed to Open",
                f"Could not open the selected script in Script Editor:\n\n"
                f"{target}\n\n{error}",
            )

    def open_file(self, path):
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self.window, "File Not Found", f"Cannot open:\n{path}")
            return False
        existing = self.open_files.get(path)
        if existing is not None:
            for i in range(self.window.MainEditorTabs.count()):
                tab = self.window.MainEditorTabs.widget(i)
                if tab.findChild(PythonCodeEditor) is existing:
                    self.window.MainEditorTabs.setCurrentIndex(i)
                    return True
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(self.window, "Open Failed", str(error))
            return False
        editor = self._create_tab(path, source)
        editor.document().setModified(False)
        self._update_tab_title(editor.parentWidget())
        return True

    def open_tree_item(self, index):
        path = Path(self.file_model.filePath(index))
        if path.is_file() and path.suffix.lower() == ".py":
            self.open_file(path)

    def new_python_script(self):
        """Create a standalone script at a user-selected location and open it separately."""
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
                f"{path} already exists. Open it in the standalone Script Editor?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        else:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch(exist_ok=False)
            except OSError as error:
                QMessageBox.critical(self.window, "Create Failed", str(error))
                return

        try:
            editor = ScriptEditor(file_path=path)
            self.standalone_editors.append(editor)
            editor.show()
            self.write_terminal_output(f"Created standalone script: {path}\n")
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Script Editor Failed to Open",
                f"The script was created at:\n{path}\n\nBut the standalone editor could not open it:\n{error}",
            )

    def save_current_file(self):
        tab = self.get_current_tab()
        editor = self.get_current_editor()
        if tab is None or editor is None:
            return False
        path = self._current_path()
        if path is None:
            return self.save_file_as()
        return self._save_editor(tab, editor, path)

    def save_file_as(self):
        editor = self.get_current_editor()
        tab = self.get_current_tab()
        if editor is None or tab is None:
            return False
        current = self._current_path()
        default = str(current or (self.project_root / "script.py"))
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Save Python Script As", default,
            "Python Files (*.py);;All Files (*)"
        )
        if not path:
            return False
        target = Path(path).expanduser().resolve()
        if not target.suffix:
            target = target.with_suffix(".py")
        other = self.open_files.get(target)
        if other is not None and other is not editor:
            QMessageBox.warning(self.window, "Already Open", "That file is already open in another tab.")
            return False
        old = self._current_path()
        if old:
            self.open_files.pop(old, None)
        tab.setProperty("file_path", str(target))
        self.open_files[target] = editor
        result = self._save_editor(tab, editor, target)
        if result:
            self.file_model.setRootPath(str(self.project_root))
        return result

    def _save_editor(self, tab, editor, path):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(editor.toPlainText(), encoding="utf-8")
            editor.document().setModified(False)
            self._update_tab_title(tab)
            self.write_terminal_output(f"Saved {path}\n")
            return True
        except OSError as error:
            QMessageBox.critical(self.window, "Save Failed", str(error))
            return False

    def close_editor_tab(self, index):
        tabs = self.window.MainEditorTabs
        tab = tabs.widget(index)
        editor = tab.findChild(PythonCodeEditor) if tab else None
        if editor and editor.document().isModified():
            answer = QMessageBox.question(
                self.window, "Unsaved Changes", f"Save changes to {tabs.tabText(index).rstrip(' *')}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                tabs.setCurrentIndex(index)
                if not self.save_current_file():
                    return
        path_text = tab.property("file_path") if tab else ""
        if path_text:
            self.open_files.pop(Path(path_text).resolve(), None)
        tabs.removeTab(index)
        tab.deleteLater()
        if tabs.count() == 0:
            self._new_untitled_tab()

    def undo_current_editor(self):
        editor = self.get_current_editor()
        if editor:
            editor.undo()

    def redo_current_editor(self):
        editor = self.get_current_editor()
        if editor:
            editor.redo()

    def open_project_dialog(self):
        folder = QFileDialog.getExistingDirectory(self.window, "Open Python Project", str(self.project_root))
        if folder:
            try:
                self.project_editor = ProjectEditor(folder)
                self.project_editor.show()
            except Exception as error:
                QMessageBox.critical(self.window, "Open Project Failed", str(error))

    def _python_executable(self):
        candidates = [
            self.project_root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
            self.project_root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return sys.executable

    def run_current_file(self):
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.write_terminal_output("A Python process is already running. Stop it first.\n")
            return
        if not self.save_current_file():
            return
        path = self._current_path()
        editor = self.get_current_editor()
        if path is None or editor is None:
            return
        result = self.parser.parse(editor.toPlainText())
        if not result.get("success", False):
            self.show_problem(result.get("error", {"message": "Syntax error", "line": None, "column": None}))
            return
        self.window.Console.clear()
        self.input_start = 0
        self.window.TerminalTabWidget.setCurrentWidget(self.window.ConsoleTab)
        self.write_terminal_output(f"Running {path.name}...\n")
        self.process = QProcess(self)
        self.process.setProgram(self._python_executable())
        self.process.setArguments(["-u", str(path)])
        self.process.setWorkingDirectory(str(self.project_root))
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self._read_stdout)
        self.process.readyReadStandardError.connect(self._read_stderr)
        self.process.finished.connect(self._process_finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.start()

    def stop_process(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.write_terminal_output("Stopped Python process.\n")

    def _read_stdout(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            if text:
                self._append(self.window.Console, text)
                self.input_start = len(self.window.Console.toPlainText())

    def _read_stderr(self):
        if self.process:
            text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            if text:
                self._append(self.window.problems, text)
                self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    def _process_finished(self, exit_code, exit_status):
        status = "finished" if exit_status == QProcess.ExitStatus.NormalExit else "crashed"
        self.write_terminal_output(f"Python process {status} (exit code {exit_code}).\n")
        if self.process:
            self.process.deleteLater()
            self.process = None

    def _process_error(self, _error):
        if self.process:
            self._append(self.window.problems, self.process.errorString() + "\n")
            self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    def show_problem(self, error):
        line = error.get("line")
        column = error.get("column")
        message = error.get("message", "Syntax error")
        location = f"Line {line}, column {column}: " if line is not None else ""
        self.window.problems.setPlainText(location + str(message))
        self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    @staticmethod
    def _append(widget, text):
        cursor = widget.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        widget.setTextCursor(cursor)
        widget.insertPlainText(text)
        widget.ensureCursorVisible()

    def write_terminal_output(self, text):
        self._append(self.window.Terminal, text)
        self.terminal_input_start = len(self.window.Terminal.toPlainText())

    def _start_terminal(self):
        self.window.Terminal.clear()
        self.terminal_process = QProcess(self)
        if os.name == "nt":
            self.terminal_process.setProgram(os.environ.get("COMSPEC", "cmd.exe"))
            self.terminal_process.setArguments(["/Q"])
        else:
            self.terminal_process.setProgram(os.environ.get("SHELL", "/bin/bash"))
            self.terminal_process.setArguments(["-i"])
        self.terminal_process.setWorkingDirectory(str(self.project_root))
        self.terminal_process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.terminal_process.readyReadStandardOutput.connect(self._read_terminal_output)
        self.terminal_process.readyReadStandardError.connect(self._read_terminal_output)
        self.terminal_process.start()

    def _read_terminal_output(self):
        if self.terminal_process:
            data = self.terminal_process.readAllStandardOutput() + self.terminal_process.readAllStandardError()
            text = bytes(data).decode("utf-8", errors="replace")
            if text:
                self.write_terminal_output(text)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.KeyPress:
            if watched is self.window.Console:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._send_console_input()
                    return True
                if event.key() == Qt.Key.Key_Backspace and self.window.Console.textCursor().position() <= self.input_start:
                    return True
                if event.key() == Qt.Key.Key_Home:
                    cursor = self.window.Console.textCursor()
                    cursor.setPosition(self.input_start)
                    self.window.Console.setTextCursor(cursor)
                    return True
            elif watched is self.window.Terminal:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self._send_terminal_input()
                    return True
                if event.key() == Qt.Key.Key_Backspace and self.window.Terminal.textCursor().position() <= self.terminal_input_start:
                    return True
                if event.key() == Qt.Key.Key_Home:
                    cursor = self.window.Terminal.textCursor()
                    cursor.setPosition(self.terminal_input_start)
                    self.window.Terminal.setTextCursor(cursor)
                    return True
        return super().eventFilter(watched, event)

    def _send_console_input(self):
        if not self.process or self.process.state() != QProcess.ProcessState.Running:
            return
        console = self.window.Console
        cursor = console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        console.setTextCursor(cursor)
        text = console.toPlainText()[self.input_start:]
        console.insertPlainText("\n")
        self.process.write((text + "\n").encode("utf-8"))
        self.input_start = len(console.toPlainText())

    def _send_terminal_input(self):
        if not self.terminal_process or self.terminal_process.state() != QProcess.ProcessState.Running:
            return
        terminal = self.window.Terminal
        cursor = terminal.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        terminal.setTextCursor(cursor)
        command = terminal.toPlainText()[self.terminal_input_start:]
        terminal.insertPlainText("\n")
        self.terminal_process.write((command + "\n").encode("utf-8"))
        self.terminal_input_start = len(terminal.toPlainText())

    def closeEvent(self, event):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        if self.terminal_process and self.terminal_process.state() != QProcess.ProcessState.NotRunning:
            self.terminal_process.kill()
        event.accept()

    def show(self):
        self.window.show()

"""PyForge project editor.

Supports project tabs, project-tree navigation, standalone Script Editor windows,
saving, and running the selected project script.
"""

import ast
import os
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QDir, QEvent, QObject, QProcess, Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from Core.project_format import (
    ProjectFormatError,
    find_project_manifest,
    load_project_manifest,
)
from Core.window_registry import retain_window


BASE_DIR = Path(__file__).resolve().parent


def load_ui(ui_path: Path):
    ui_file = QFile(str(ui_path))
    if not ui_file.open(QFile.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"Cannot open UI file: {ui_path}")
    try:
        loader = QUiLoader()
        loader.registerCustomWidget(PythonCodeEditor)
        window = loader.load(ui_file)
        if window is None:
            raise RuntimeError(f"Qt could not load UI file: {ui_path}")
        # QUiLoader widgets are retrieved through findChild by default.
        # Expose named children as attributes for the editor code below.
        for child in window.findChildren(QObject):
            name = child.objectName()
            if name and not hasattr(window, name):
                setattr(window, name, child)
        return window
    finally:
        ui_file.close()


def connect_if_present(window, names, callback):
    """Connect every available QAction alias without connecting one action twice."""
    connected = []
    seen = set()
    for name in names:
        action = getattr(window, name, None)
        if action is not None and id(action) not in seen:
            action.triggered.connect(callback)
            connected.append(action)
            seen.add(id(action))
    return connected[0] if connected else None


class ProjectEditor(QObject):
    def __init__(self, project_path=None):
        super().__init__()
        requested_path = Path(project_path or Path.cwd()).expanduser().resolve()
        self.project_file = None
        self.project_config = {}

        if not requested_path.exists():
            raise FileNotFoundError(f"Project path does not exist: {requested_path}")
        if requested_path.is_file():
            if requested_path.suffix.lower() != ".forproj" and requested_path.name.lower() != "pyforge.json":
                raise ValueError("Open a .forproj project file or a legacy pyforge.json manifest.")
            self.project_file = requested_path
            self.project_config = load_project_manifest(requested_path)
            root = requested_path.parent
        elif requested_path.is_dir():
            root = requested_path
            self.project_file = find_project_manifest(root)
            if self.project_file is not None:
                self.project_config = load_project_manifest(self.project_file)
        else:
            raise ValueError(f"Unsupported project path: {requested_path}")

        self.project_root = root
        self.entry_point = self.project_config.get("entry_point", "main.py")
        self.configured_interpreter = self.project_config.get("interpreter", "")
        self.open_files = {}              # resolved path string -> tab widget
        self.script_windows = []          # keep standalone windows alive
        self.process = None
        self.terminal_process = None
        self._terminal_input_start = 0
        self._console_input_start = 0
        self._closing = False

        self.window = load_ui(BASE_DIR / "ProjectWindow.ui")
        self.window.installEventFilter(self)
        self.window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        project_name = self.project_config.get("name", self.project_root.name)
        self.window.setWindowTitle(f"PyForge Project - {project_name}")

        self._connect_actions()
        self._setup_project_tree()
        self._setup_tabs()
        self.window.Console.installEventFilter(self)
        self.window.Terminal.installEventFilter(self)
        self._start_terminal()

        main_file = (self.project_root / self.entry_point).resolve()
        try:
            main_file.relative_to(self.project_root.resolve())
        except ValueError as exc:
            raise ProjectFormatError("The configured entry point escapes the project directory.") from exc
        if main_file.is_file():
            self.open_project_file(main_file)
        else:
            self._create_tab(None, "")
        self._terminal_write(f"PyForge project opened: {self.project_root}\n")

    # ----- actions / setup -------------------------------------------------
    def _connect_actions(self):
        connect_if_present(self.window, ("actionRun",), self.run_current_file)
        connect_if_present(self.window, ("actionStop",), self.stop_process)
        connect_if_present(self.window, ("actionSave",), self.save_current_file)
        connect_if_present(self.window, ("actionSave_As",), self.save_as)
        connect_if_present(self.window, ("actionOpen", "actionPython_Script"), self.open_standalone_dialog)
        connect_if_present(self.window, ("actionPython_Projet", "actionPython_Project"), self.open_project_dialog)
        connect_if_present(self.window, ("actionNewPS",), self.new_standalone_script)
        connect_if_present(self.window, ("actionNew_PA", "actionNewProject", "actionNewPythonApplication", "actionNewPythonProject"), self.new_python_application)
        connect_if_present(self.window, ("actionUndo",), self.undo)
        connect_if_present(self.window, ("actionRedo",), self.redo)

    def _setup_project_tree(self):
        self.file_model = QFileSystemModel(self)
        self.file_model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.file_model.setRootPath(str(self.project_root))
        tree = self.window.treeView
        tree.setModel(self.file_model)
        tree.setRootIndex(self.file_model.index(str(self.project_root)))
        for column in range(1, self.file_model.columnCount()):
            tree.hideColumn(column)
        tree.doubleClicked.connect(self._on_tree_double_click)

    def _setup_tabs(self):
        tabs = self.window.MainEditorTabs
        while tabs.count():
            old = tabs.widget(0)
            tabs.removeTab(0)
            old.deleteLater()
        tabs.setTabsClosable(True)
        tabs.tabCloseRequested.connect(self.close_tab)

    # ----- tab and file handling -----------------------------------------
    def current_tab(self):
        return self.window.MainEditorTabs.currentWidget()

    def current_editor(self):
        tab = self.current_tab()
        return tab.findChild(PythonCodeEditor) if tab else None

    def _create_tab(self, file_path=None, content=""):
        path = Path(file_path).expanduser().resolve() if file_path else None
        tabs = self.window.MainEditorTabs
        if path is not None:
            existing = self.open_files.get(str(path))
            if existing is not None:
                index = tabs.indexOf(existing)
                if index >= 0:
                    tabs.setCurrentIndex(index)
                    return existing

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        editor = PythonCodeEditor(tab)
        editor.setPlainText(content)
        layout.addWidget(editor)
        tab.setProperty("file_path", str(path) if path else "")
        tab.setProperty("dirty", False)
        title = path.name if path else "Untitled.py"
        index = tabs.addTab(tab, title)
        tabs.setCurrentIndex(index)
        if path is not None:
            self.open_files[str(path)] = tab
        editor.textChanged.connect(lambda t=tab: self._mark_dirty(t))
        return tab

    def _mark_dirty(self, tab):
        if not tab or tab.property("dirty"):
            return
        tab.setProperty("dirty", True)
        index = self.window.MainEditorTabs.indexOf(tab)
        if index >= 0:
            title = self.window.MainEditorTabs.tabText(index)
            if not title.endswith("*"):
                self.window.MainEditorTabs.setTabText(index, title + "*")

    def _mark_saved(self, tab, file_path):
        old_path = tab.property("file_path")
        if old_path:
            self.open_files.pop(old_path, None)
        path = Path(file_path).expanduser().resolve()
        tab.setProperty("file_path", str(path))
        tab.setProperty("dirty", False)
        self.open_files[str(path)] = tab
        index = self.window.MainEditorTabs.indexOf(tab)
        if index >= 0:
            self.window.MainEditorTabs.setTabText(index, path.name)

    def open_project_file(self, file_path):
        path = Path(file_path).expanduser().resolve()
        if not path.is_file():
            return
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(self.window, "Open Failed", str(error))
            return
        self._create_tab(path, content)

    def _on_tree_double_click(self, index):
        path = Path(self.file_model.filePath(index))
        if path.is_file() and path.suffix.lower() == ".py":
            self.open_project_file(path)

    def open_standalone_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window, "Open Python Script", str(self.project_root),
            "Python Files (*.py);;All Files (*)",
        )
        if path:
            self._launch_standalone(Path(path))

    def _launch_standalone(self, path=None):
        # Import here to avoid circular imports at module initialization.
        from Script_editor import ScriptEditor
        try:
            editor = ScriptEditor(file_path=str(path) if path else None)
            self.script_windows.append(editor)
            retain_window(editor)
            editor.window.destroyed.connect(
                lambda *_args, obj=editor: self._forget_script_window(obj)
            )
            editor.show()
            return editor
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Could Not Open Python Script",
                f"PyForge could not open the standalone script editor.\n\n{error}",
            )
            return None

    def new_python_application(self):
        # Import locally because Project_Creator imports ProjectEditor itself.
        from Project_Creator import ProjectCreator
        try:
            creator = ProjectCreator()
            if not hasattr(self, "project_creators"):
                self.project_creators = []
            self.project_creators.append(creator)
            retain_window(creator)
            creator.window.destroyed.connect(
                lambda *_args, obj=creator: self._forget_project_creator(obj)
            )
            creator.show()
        except Exception as error:
            QMessageBox.critical(
                self.window,
                "Project Creator Failed",
                f"Could not open the project creation window.\n\n{error}",
            )

    def _forget_script_window(self, editor):
        try:
            self.script_windows.remove(editor)
        except ValueError:
            pass

    def _forget_project_creator(self, creator):
        try:
            self.project_creators.remove(creator)
        except (AttributeError, ValueError):
            pass

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
        self._launch_standalone(target)

    def open_project_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open PyForge Project",
            str(self.project_root),
            "PyForge Projects (*.forproj);;Legacy Project Metadata (*.json);;All Files (*)",
        )
        if not path:
            return
        try:
            editor = ProjectEditor(path)
        except Exception as error:
            QMessageBox.critical(self.window, "Open Project Failed", str(error))
            return
        # Hold the Python wrapper alive for as long as its window is open.
        if not hasattr(self, "project_windows"):
            self.project_windows = []
        self.project_windows.append(editor)
        retain_window(editor)
        editor.window.destroyed.connect(lambda *_args, obj=editor: self._forget_project_window(obj))
        editor.show()

    def _forget_project_window(self, editor):
        try:
            self.project_windows.remove(editor)
        except (AttributeError, ValueError):
            pass

    def save_current_file(self):
        tab, editor = self.current_tab(), self.current_editor()
        if tab is None or editor is None:
            return False
        file_path = tab.property("file_path")
        if not file_path:
            return self.save_as()
        return self._write_tab(tab, editor, file_path)

    def save_as(self):
        tab, editor = self.current_tab(), self.current_editor()
        if tab is None or editor is None:
            return False
        old_path = tab.property("file_path") or str(self.project_root / "untitled.py")
        path, _ = QFileDialog.getSaveFileName(
            self.window, "Save Python Script As", old_path,
            "Python Files (*.py);;All Files (*)",
        )
        if not path:
            return False
        target = Path(path).expanduser().resolve()
        if target.suffix.lower() != ".py" and not target.name.endswith("."):
            target = target.with_suffix(".py")
        return self._write_tab(tab, editor, target)

    def _write_tab(self, tab, editor, file_path):
        path = Path(file_path).expanduser().resolve()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(editor.toPlainText(), encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self.window, "Save Failed", str(error))
            return False
        self._mark_saved(tab, path)
        self.window.statusbar.showMessage(f"Saved {path}", 4000)
        return True

    def close_tab(self, index):
        tabs = self.window.MainEditorTabs
        tab = tabs.widget(index)
        if tab is None:
            return
        if tab.property("dirty"):
            name = tabs.tabText(index).rstrip("*")
            answer = QMessageBox.question(
                self.window, "Unsaved Changes", f"Save changes to {name}?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save:
                tabs.setCurrentIndex(index)
                if not self.save_current_file():
                    return
        path = tab.property("file_path")
        if path:
            self.open_files.pop(path, None)
        tabs.removeTab(index)
        tab.deleteLater()
        if tabs.count() == 0 and not self._closing:
            self._create_tab()

    def undo(self):
        editor = self.current_editor()
        if editor:
            editor.undo()

    def redo(self):
        editor = self.current_editor()
        if editor:
            editor.redo()

    # ----- running project scripts ---------------------------------------
    def _python_executable(self):
        candidates = [
            self.project_root / ".venv" / "Scripts" / "python.exe",
            self.project_root / ".venv" / "bin" / "python",
            self.project_root / "venv" / "Scripts" / "python.exe",
            self.project_root / "venv" / "bin" / "python",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        configured = Path(self.configured_interpreter).expanduser() if self.configured_interpreter else None
        if configured is not None and configured.is_file():
            return str(configured.resolve())
        return sys.executable

    def run_current_file(self):
        tab, editor = self.current_tab(), self.current_editor()
        if tab is None or editor is None:
            self._terminal_write("No script is selected.\n")
            return
        if not self.save_current_file():
            self._terminal_write("Run cancelled because the script was not saved.\n")
            return
        path = Path(tab.property("file_path")).resolve()
        try:
            ast.parse(editor.toPlainText(), filename=str(path))
        except SyntaxError as error:
            self.window.problems.setPlainText(
                f"Line {error.lineno}, column {error.offset}: {error.msg}"
            )
            self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)
            return
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self._terminal_write("A Python process is already running. Stop it first.\n")
            return
        self.window.Console.clear()
        self._console_input_start = 0
        self.window.TerminalTabWidget.setCurrentWidget(self.window.ConsoleTab)
        process = QProcess(self)
        self.process = process
        process.setProgram(self._python_executable())
        process.setArguments(["-u", str(path)])
        process.setWorkingDirectory(str(self.project_root))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_process_stdout)
        process.readyReadStandardError.connect(self._read_process_stderr)
        process.finished.connect(self._process_finished)
        process.errorOccurred.connect(self._process_error)
        self._terminal_write(f"Running {path.name}...\n")
        process.start()

    def _read_process_stdout(self):
        if self.process:
            text = bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
            if text:
                self._console_write(text)

    def _read_process_stderr(self):
        if self.process:
            text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
            if text:
                self.window.problems.appendPlainText(text.rstrip("\n"))
                self.window.TerminalTabWidget.setCurrentWidget(self.window.ProblemsTab)

    def _process_finished(self, exit_code, exit_status):
        self._terminal_write(
            f"Process finished with exit code {exit_code}.\n"
            if exit_status == QProcess.ExitStatus.NormalExit
            else "Process crashed.\n"
        )
        process, self.process = self.process, None
        if process:
            process.deleteLater()

    def _process_error(self, error):
        if self.process and error == QProcess.ProcessError.FailedToStart:
            QMessageBox.critical(self.window, "Run Failed", self.process.errorString())

    def stop_process(self):
        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1000)
            self._terminal_write("Python process stopped.\n")

    # ----- console and terminal -------------------------------------------
    def _console_write(self, text):
        console = self.window.Console
        cursor = console.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        console.setTextCursor(cursor)
        console.insertPlainText(text)
        console.ensureCursorVisible()
        self._console_input_start = len(console.toPlainText())

    def _terminal_write(self, text):
        terminal = self.window.Terminal
        cursor = terminal.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        terminal.setTextCursor(cursor)
        terminal.insertPlainText(text)
        terminal.ensureCursorVisible()
        self._terminal_input_start = len(terminal.toPlainText())

    def _start_terminal(self):
        if self.terminal_process and self.terminal_process.state() != QProcess.ProcessState.NotRunning:
            return
        shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else os.environ.get("SHELL", "/bin/bash")
        process = QProcess(self)
        self.terminal_process = process
        process.setProgram(shell)
        process.setArguments(["/Q"] if os.name == "nt" else ["-i"])
        process.setWorkingDirectory(str(self.project_root))
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
            self._closing = True
            tabs = self.window.MainEditorTabs
            for index in reversed(range(tabs.count())):
                tab = tabs.widget(index)
                self.close_tab(index)
                if tabs.indexOf(tab) != -1:
                    self._closing = False
                    event.ignore()
                    return True
            for process in (self.process, self.terminal_process):
                if process and process.state() != QProcess.ProcessState.NotRunning:
                    process.kill()
            return False

        if event.type() == QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if watched is self.window.Console:
                if self.process and self.process.state() == QProcess.ProcessState.Running:
                    cursor = self.window.Console.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    self.window.Console.setTextCursor(cursor)
                    text = self.window.Console.toPlainText()[self._console_input_start:]
                    self.window.Console.insertPlainText("\n")
                    self._console_input_start = len(self.window.Console.toPlainText())
                    self.process.write((text + "\n").encode("utf-8"))
                    return True
            elif watched is self.window.Terminal:
                if self.terminal_process and self.terminal_process.state() == QProcess.ProcessState.Running:
                    cursor = self.window.Terminal.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    self.window.Terminal.setTextCursor(cursor)
                    text = self.window.Terminal.toPlainText()[self._terminal_input_start:]
                    self.window.Terminal.insertPlainText("\n")
                    self._terminal_input_start = len(self.window.Terminal.toPlainText())
                    self.terminal_process.write((text + "\n").encode("utf-8"))
                    return True
        return super().eventFilter(watched, event)

    # ----- lifecycle -------------------------------------------------------
    def show(self):
        self.window.show()



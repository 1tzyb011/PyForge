
import os
import sys
import tempfile

from PySide6.QtCore import (
    QFile,
    QObject,
    QProcess,
    QEvent,
    Qt,
    QDir
)
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QFileSystemModel,
    QMessageBox,
    QInputDialog,
    QWidget,
    QVBoxLayout,
)
from PySide6.QtUiTools import QUiLoader

from python_code_editor import PythonCodeEditor
from python_parser import PythonParser


class ProjectEditor(QObject):
    def __init__(self, project_path=None):
        super().__init__()

        self.project_root = Path(
            project_path or Path.cwd()
        ).expanduser().resolve()

        self.open_files = {}
        self._closing_tabs = False

        self.window = self.load_ui(
            Path(__file__).resolve().parent
            / "ProjectWindow.ui"
        )

        if self.window is None:
            raise RuntimeError(
                "Failed to load ProjectWindow.ui"
            )

        self.parser = PythonParser()

        # Python program process
        self.process = None

        # Persistent editor terminal process
        self.terminal_process = None

        # Temporary file used by the current editor
        self.temp_file = None

        # Input boundaries
        self.input_start = 0
        self.terminal_input_start = 0

        self.connect_actions()

        self.setup_project_tree()
        self.setup_editor_tabs()

        # Console input
        self.window.Console.installEventFilter(
            self
        )

        # Terminal input
        self.window.Terminal.installEventFilter(
            self
        )

        self.start_terminal()

        self.write_terminal_output(
            "pyForge Project Editor started."
        )

    # --------------------------------------------------
    # UI
    # --------------------------------------------------

        def load_ui(self, path):
            ui_file = QFile(str(path))

            if not ui_file.open(
                QFile.OpenModeFlag.ReadOnly
            ):
                print(f"Failed to open UI file: {path}")
                return None

            try:
                loader = QUiLoader()
                loader.registerCustomWidget(PythonCodeEditor)
                return loader.load(ui_file)
            finally:
                ui_file.close()
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

        self.window.actionSave.triggered.connect(
            self.save_current_file
        )
        self.window.actionSave_As.triggered.connect(
            self.save_file_as
        )
        self.window.actionOpen.triggered.connect(
            self.open_file_dialog
        )
        self.window.actionNewPS.triggered.connect(
            self.new_python_script
        )

        self.window.actionUndo.triggered.connect(
            lambda: self.get_current_editor()
            and self.get_current_editor().undo()
        )
        self.window.actionRedo.triggered.connect(
            lambda: self.get_current_editor()
            and self.get_current_editor().redo()
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
            self.write_terminal_output(
                "No editor is currently selected."
            )
            return

        source = editor.toPlainText()

        if not source.strip():
            self.write_terminal_output(
                "Nothing to run."
            )
            return

            if not self.save_current_file():
                self.write_terminal_output(
                    "Run cancelled: save the script first."
                )
                return

        tab = self.get_current_tab()
        script_path = Path(tab.property("file_path"))

        # Don't allow multiple Python processes
        if self.process is not None:
            if self.process.state() != (
                QProcess.ProcessState.NotRunning
            ):
                self.write_terminal_output(
                    "A process is already running."
                )
                return

        # Parse only when Run is pressed
        result = self.parser.parse(source)

        if not result["success"]:
            self.show_problem(
                result["error"]
            )

            self.write_terminal_output(
                "Run cancelled because the script "
                "contains syntax errors."
            )

            return

        self.clear_problems()

        # --------------------------------------------------
        # Create temporary Python file
        # --------------------------------------------------

        try:
            self.window.Console.clear()
            self.input_start = 0

            self.window.TerminalTabWidget.setCurrentWidget(
                self.window.ConsoleTab
            )

            self.write_terminal_output(
                f"Running {script_path.name}..."
            )

            self.process = QProcess(self)
            self.process.setProgram(sys.executable)
            self.process.setArguments([
                "-u",
                str(script_path),
            ])
            self.process.setWorkingDirectory(
                str(self.project_root)
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

        self.input_start = 0

        self.window.TerminalTabWidget.setCurrentWidget(
            self.window.ConsoleTab
        )

        self.write_terminal_output(
            f"Running "
            f"{os.path.basename(self.temp_file)}..."
        )

        # --------------------------------------------------
        # Create Python QProcess
        # --------------------------------------------------

        self.process = QProcess(self)

        self.process.setProgram(
            sys.executable
        )

        self.process.setArguments([
            "-u",
            self.temp_file,
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
                self.write_terminal_output(
                    "Process finished successfully."
                )
            else:
                self.write_terminal_output(
                    f"Process exited with code "
                    f"{exit_code}."
                )
        else:
            self.write_terminal_output(
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

            self.write_terminal_output(
                "Failed to start Python process."
            )

    # --------------------------------------------------
    # Console input
    # --------------------------------------------------

    def handle_console_key(self, event):
        console = self.window.Console

        # Enter
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            cursor = console.textCursor()

            cursor.movePosition(
                cursor.MoveOperation.End
            )

            console.setTextCursor(cursor)

            current_text = console.toPlainText()

            user_input = current_text[
                self.input_start:
            ]

            console.insertPlainText("\n")

            self.input_start = (
                len(console.toPlainText())
            )

            if self.process is not None:
                if self.process.state() != (
                    QProcess.ProcessState.NotRunning
                ):
                    self.process.write(
                        (
                            user_input + "\n"
                        ).encode("utf-8")
                    )

            return True

        # Backspace
        if event.key() == Qt.Key.Key_Backspace:
            cursor = console.textCursor()

            if cursor.position() <= self.input_start:
                return True

            if cursor.hasSelection():
                if cursor.selectionStart() < (
                    self.input_start
                ):
                    return True

            return False

        # Left arrow
        if event.key() == Qt.Key.Key_Left:
            cursor = console.textCursor()

            if cursor.position() <= self.input_start:
                return True

            return False

        # Home
        if event.key() == Qt.Key.Key_Home:
            cursor = console.textCursor()

            cursor.setPosition(
                self.input_start
            )

            console.setTextCursor(cursor)

            return True

        return False

    # --------------------------------------------------
    # Terminal
    # --------------------------------------------------

    def start_terminal(self):
        if self.terminal_process is not None:
            if self.terminal_process.state() != (
                QProcess.ProcessState.NotRunning
            ):
                return

        self.window.Terminal.clear()

        self.terminal_input_start = 0

        self.terminal_process = QProcess(
            self
        )

        if os.name == "nt":
            shell = os.environ.get(
                "COMSPEC",
                "cmd.exe",
            )

            self.terminal_process.setProgram(
                shell
            )

            self.terminal_process.setArguments([
                "/Q",
            ])

        else:
            shell = os.environ.get(
                "SHELL",
                "/bin/bash",
            )

            self.terminal_process.setProgram(
                shell
            )

            self.terminal_process.setArguments([
                "-i",
            ])

        self.terminal_process.setWorkingDirectory(
            os.getcwd()
        )

        self.terminal_process.setProcessChannelMode(
            QProcess.ProcessChannelMode.SeparateChannels
        )

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

    # --------------------------------------------------
    # Terminal stdout
    # --------------------------------------------------

    def read_terminal_stdout(self):
        if self.terminal_process is None:
            return

        data = (
            self.terminal_process
            .readAllStandardOutput()
        )

        text = bytes(data).decode(
            "utf-8",
            errors="replace",
        )

        if text:
            self.write_terminal_output(
                text
            )

    # --------------------------------------------------
    # Terminal stderr
    # --------------------------------------------------

    def read_terminal_stderr(self):
        if self.terminal_process is None:
            return

        data = (
            self.terminal_process
            .readAllStandardError()
        )

        text = bytes(data).decode(
            "utf-8",
            errors="replace",
        )

        if text:
            self.write_terminal_output(
                text
            )

    # --------------------------------------------------
    # Terminal output
    # --------------------------------------------------

    def write_terminal_output(self, text):
        terminal = self.window.Terminal

        cursor = terminal.textCursor()

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        terminal.setTextCursor(cursor)

        terminal.insertPlainText(text)

        cursor.movePosition(
            cursor.MoveOperation.End
        )

        terminal.setTextCursor(cursor)

        self.terminal_input_start = (
            len(terminal.toPlainText())
        )

    # --------------------------------------------------
    # Terminal input
    # --------------------------------------------------

    def handle_terminal_key(self, event):
        terminal = self.window.Terminal

        # Enter
        if event.key() in (
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            cursor = terminal.textCursor()

            cursor.movePosition(
                cursor.MoveOperation.End
            )

            terminal.setTextCursor(cursor)

            current_text = (
                terminal.toPlainText()
            )

            command = current_text[
                self.terminal_input_start:
            ]

            terminal.insertPlainText("\n")

            self.terminal_input_start = (
                len(terminal.toPlainText())
            )

            if self.terminal_process is not None:
                if self.terminal_process.state() != (
                    QProcess.ProcessState.NotRunning
                ):
                    self.terminal_process.write(
                        (
                            command + "\n"
                        ).encode("utf-8")
                    )

            return True

        # Backspace
        if event.key() == Qt.Key.Key_Backspace:
            cursor = terminal.textCursor()

            if cursor.position() <= (
                self.terminal_input_start
            ):
                return True

            if cursor.hasSelection():
                if cursor.selectionStart() < (
                    self.terminal_input_start
                ):
                    return True

            return False

        # Left arrow
        if event.key() == Qt.Key.Key_Left:
            cursor = terminal.textCursor()

            if cursor.position() <= (
                self.terminal_input_start
            ):
                return True

            return False

        # Home
        if event.key() == Qt.Key.Key_Home:
            cursor = terminal.textCursor()

            cursor.setPosition(
                self.terminal_input_start
            )

            terminal.setTextCursor(cursor)

            return True

        return False

    # --------------------------------------------------
    # Event filter
    # --------------------------------------------------

    def eventFilter(self, watched, event):
        if event.type() == (
            QEvent.Type.KeyPress
        ):
            if watched == self.window.Console:
                if self.handle_console_key(
                    event
                ):
                    return True

            if watched == self.window.Terminal:
                if self.handle_terminal_key(
                    event
                ):
                    return True

        return super().eventFilter(
            watched,
            event,
        )

    # --------------------------------------------------
    # Terminal process finished
    # --------------------------------------------------

    def terminal_finished(
        self,
        exit_code,
        exit_status,
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

        process = self.terminal_process

        self.terminal_process = None

        if process is not None:
            process.deleteLater()

    # --------------------------------------------------
    # Terminal process errors
    # --------------------------------------------------

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

        self.input_start = (
            len(console.toPlainText())
        )

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
    # Stop Python process
    # --------------------------------------------------

    def stop_process(self):
        if self.process is None:
            return

        if self.process.state() == (
            QProcess.ProcessState.NotRunning
        ):
            return

        self.process.kill()

        self.write_terminal_output(
            "Process stopped."
        )

    # --------------------------------------------------
    # Cleanup Python process
    # --------------------------------------------------

    def cleanup_process(self):
        if self.process is not None:
            process = self.process

            self.process = None

            process.deleteLater()

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
    # Close terminal
    # --------------------------------------------------

    def close_terminal(self):
        if self.terminal_process is None:
            return

        if self.terminal_process.state() != (
            QProcess.ProcessState.NotRunning
        ):
            self.terminal_process.kill()

        process = self.terminal_process

        self.terminal_process = None

        process.deleteLater()

    def show(self):
        self.window.show()

        def setup_project_tree(self):
            self.file_model = QFileSystemModel(self)
            self.file_model.setFilter(
                QDir.Filter.AllEntries
                | QDir.Filter.NoDotAndDotDot
            )

            self.file_model.setRootPath(str(self.project_root))

            tree = self.window.treeView
            tree.setModel(self.file_model)
            tree.setRootIndex(
                self.file_model.index(str(self.project_root))
            )

            # Keep the explorer compact.
            for column in range(1, 4):
                tree.hideColumn(column)

            tree.doubleClicked.connect(
                self.open_tree_item
            )

    def setup_editor_tabs(self):
        tabs = self.window.MainEditorTabs

        # Remove the two placeholder tabs from Qt Designer.
        while tabs.count():
            widget = tabs.widget(0)
            tabs.removeTab(0)
            widget.deleteLater()

        tabs.setTabsClosable(True)
        tabs.tabCloseRequested.connect(
            self.close_editor_tab
        )

    def get_current_editor(self):
        tab = self.window.MainEditorTabs.currentWidget()

        if tab is None:
            return None

        return tab.findChild(PythonCodeEditor)

    def get_current_tab(self):
        return self.window.MainEditorTabs.currentWidget()

    def create_editor_tab(self, file_path=None, content=""):
        tabs = self.window.MainEditorTabs

        path = Path(file_path).resolve() if file_path else None

        # Don't open the same file in multiple tabs.
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

        editor = PythonCodeEditor()
        editor.setPlainText(content)
        layout.addWidget(editor)

        tab.setProperty(
            "file_path",
            str(path) if path else ""
        )
        tab.setProperty("dirty", False)

        title = path.name if path else "Untitled.py"
        index = tabs.addTab(tab, title)
        tabs.setCurrentIndex(index)

        if path is not None:
            self.open_files[str(path)] = tab

        editor.textChanged.connect(
            lambda tab=tab: self.mark_tab_dirty(tab)
        )

        return tab

    def mark_tab_dirty(self, tab):
        if tab is None:
            return

        if not tab.property("dirty"):
            tab.setProperty("dirty", True)

            index = self.window.MainEditorTabs.indexOf(tab)
            if index >= 0:
                title = self.window.MainEditorTabs.tabText(index)
                if not title.endswith("*"):
                    self.window.MainEditorTabs.setTabText(
                        index, title + "*"
                    )

    def update_tab_saved(self, tab, path):
        old_path = tab.property("file_path")

        if old_path:
            self.open_files.pop(old_path, None)

        path = Path(path).resolve()
        tab.setProperty("file_path", str(path))
        tab.setProperty("dirty", False)

        self.open_files[str(path)] = tab

        index = self.window.MainEditorTabs.indexOf(tab)
        if index >= 0:
            self.window.MainEditorTabs.setTabText(
                index, path.name
            )
        def open_tree_item(self, index):
            path = Path(self.file_model.filePath(index))

            if path.is_file():
                self.open_file(path)

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.window,
            "Open File",
            str(self.project_root),
            "All Files (*);;Python Files (*.py)"
        )

        if path:
            self.open_file(path)

    def open_file(self, file_path):
        path = Path(file_path).resolve()

        if not path.is_file():
            return

        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            QMessageBox.critical(
                self.window,
                "Open Failed",
                str(error)
            )
            return

        self.create_editor_tab(path, content)

    def save_current_file(self):
        tab = self.get_current_tab()
        editor = self.get_current_editor()

        if tab is None or editor is None:
            return False

        file_path = tab.property("file_path")

        if not file_path:
            return self.save_file_as()

        try:
            Path(file_path).write_text(
                editor.toPlainText(),
                encoding="utf-8"
            )
        except OSError as error:
            QMessageBox.critical(
                self.window,
                "Save Failed",
                str(error)
            )
            return False

        self.update_tab_saved(tab, file_path)
        return True

    def save_file_as(self):
        tab = self.get_current_tab()
        editor = self.get_current_editor()

        if tab is None or editor is None:
            return False

        path, _ = QFileDialog.getSaveFileName(
            self.window,
            "Save File",
            str(self.project_root / "untitled.py"),
            "Python Files (*.py);;All Files (*)"
        )

        if not path:
            return False

        try:
            Path(path).write_text(
                editor.toPlainText(),
                encoding="utf-8"
            )
        except OSError as error:
            QMessageBox.critical(
                self.window,
                "Save Failed",
                str(error)
            )
            return False

        self.update_tab_saved(tab, path)
        return True

    def new_python_script(self):
        name, accepted = QInputDialog.getText(
            self.window,
            "New Python Script",
            "Script filename:",
        )

        if not accepted or not name.strip():
            return

        name = name.strip()

        if not name.endswith(".py"):
            name += ".py"

        path = (self.project_root / name).resolve()

        # Don't allow a filename to escape the project directory.
        if not path.is_relative_to(self.project_root):
            QMessageBox.warning(
                self.window,
                "Invalid Filename",
                "Create scripts inside the project directory."
            )
            return

        if path.exists():
            QMessageBox.warning(
                self.window,
                "File Exists",
                f"{path.name} already exists."
            )
            return

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(
                self.window,
                "Creation Failed",
                str(error)
            )
            return

        self.file_model.setRootPath(str(self.project_root))
        self.open_file(path)

    def close_editor_tab(self, index):
        tabs = self.window.MainEditorTabs
        tab = tabs.widget(index)

        if tab is None:
            return

        if tab.property("dirty"):
            answer = QMessageBox.question(
                self.window,
                "Unsaved Changes",
                f"Save changes to {tabs.tabText(index).rstrip('*')}?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )

            if answer == QMessageBox.StandardButton.Cancel:
                return

            if answer == QMessageBox.StandardButton.Save:
                tabs.setCurrentIndex(index)
                if not self.save_current_file():
                    return

        file_path = tab.property("file_path")
        if file_path:
            self.open_files.pop(file_path, None)

        tabs.removeTab(index)
        tab.deleteLater()        
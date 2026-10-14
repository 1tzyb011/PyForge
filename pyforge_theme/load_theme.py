import os

try:
    from PyQt6.QtCore import QDir, QSize, Qt
    from PyQt6.QtGui import QIcon
    from PyQt6.QtWidgets import QApplication, QMenu, QTabBar, QToolBar
    _TEXT_BESIDE = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
except ImportError:
    try:
        from PySide6.QtCore import QDir, QSize, Qt
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMenu, QTabBar, QToolBar
        _TEXT_BESIDE = Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    except ImportError:
        from PyQt5.QtCore import QDir, QSize, Qt
        from PyQt5.QtGui import QIcon
        from PyQt5.QtWidgets import QApplication, QMenu, QTabBar, QToolBar
        _TEXT_BESIDE = Qt.ToolButtonTextBesideIcon

_DIR = os.path.dirname(os.path.abspath(__file__))
_ICONS = os.path.join(_DIR, "icons").replace("\\", "/")

# keyword in action / tab text  ->  icon file
_ICON_MAP = [
    ("run", "run"), ("debug", "debug"), ("stop", "stop"),
    ("new", "new_file"), ("open", "open_folder"), ("save", "save"),
    ("undo", "undo"), ("redo", "redo"),
    ("find", "search"), ("search", "search"),
    ("settings", "settings"), ("preferences", "settings"),
    ("refresh", "refresh"), ("reload", "refresh"), ("add", "plus"),
    ("terminal", "terminal"), ("console", "console"),
    ("problems", "warning"), ("errors", "warning"),
]


def _icon_for(text):
    t = text.replace("&", "").replace("...", "").strip().lower()
    if t.endswith(".py"):
        return QIcon(f"{_ICONS}/python_file.svg")
    for key, name in _ICON_MAP:
        if t == key or t.startswith(key + " "):
            return QIcon(f"{_ICONS}/{name}.svg")
    return None


def apply_theme(app):
    """Call once, right after creating QApplication."""
    QDir.addSearchPath("icons", _ICONS)
    with open(os.path.join(_DIR, "dark.qss"), encoding="utf-8") as f:
        app.setStyleSheet(f.read().replace("@ICONS@", _ICONS))


def apply_icons(target=None):
    """Pass your main window (or the QApplication, once the window exists).
    Call again after adding new tabs/actions at runtime."""
    if target is None or isinstance(target, QApplication):
        roots = (target or QApplication.instance()).topLevelWidgets()
    else:
        roots = [target]

    for root in roots:
        actions = set()
        for tb in root.findChildren(QToolBar):
            tb.setIconSize(QSize(16, 16))
            tb.setToolButtonStyle(_TEXT_BESIDE)
            actions.update(tb.actions())
        for menu in root.findChildren(QMenu):
            actions.update(menu.actions())
        for a in actions:
            if a.icon().isNull():
                ic = _icon_for(a.text())
                if ic:
                    a.setIcon(ic)
        for bar in root.findChildren(QTabBar):
            bar.setIconSize(QSize(14, 14))
            for i in range(bar.count()):
                ic = _icon_for(bar.tabText(i))
                if ic:
                    bar.setTabIcon(i, ic)

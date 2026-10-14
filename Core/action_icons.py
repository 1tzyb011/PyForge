"""Assign consistent, platform-native icons to PyForge QAction objects.

The icons are provided by Qt's active style, so PyForge does not need to ship
separate image files for common editor actions.
"""

from PySide6.QtWidgets import QApplication, QStyle
from PySide6.QtGui import QAction


ACTION_ICONS = {
    "actionRun": QStyle.StandardPixmap.SP_MediaPlay,
    "actionDebug": QStyle.StandardPixmap.SP_ComputerIcon,
    "actionStop": QStyle.StandardPixmap.SP_MediaStop,
    "actionSave": QStyle.StandardPixmap.SP_DialogSaveButton,
    "actionSave_As": QStyle.StandardPixmap.SP_DialogSaveButton,
    "actionNew_PA": QStyle.StandardPixmap.SP_DirIcon,
    "actionNewPS": QStyle.StandardPixmap.SP_FileIcon,
    "actionPython_Script": QStyle.StandardPixmap.SP_DialogOpenButton,
    "actionPython_Project": QStyle.StandardPixmap.SP_DirOpenIcon,
    "actionPython_Projet": QStyle.StandardPixmap.SP_DirOpenIcon,
    "actionUndo": QStyle.StandardPixmap.SP_ArrowBack,
    "actionRedo": QStyle.StandardPixmap.SP_ArrowForward,
    "actionPreferences": QStyle.StandardPixmap.SP_FileDialogContentsView,
}


def apply_action_icons(window):
    """Set icons on matching actions in a QUiLoader-created window."""
    app = QApplication.instance()
    if app is None:
        return

    style = app.style()
    for object_name, standard_pixmap in ACTION_ICONS.items():
        action = window.findChild(QAction, object_name)
        if action is not None:
            action.setIcon(style.standardIcon(standard_pixmap))

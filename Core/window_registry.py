"""Keep Qt window controllers alive for as long as their windows exist."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


def retain_window(controller):
    """Register a controller with QApplication to prevent premature GC.

    QUiLoader creates top-level Qt windows, while their Python controller is
    often created inside a menu callback. Keeping controllers on QApplication
    prevents child editor/project windows disappearing when the creator window
    closes or a local variable goes out of scope.
    """
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("Create QApplication before opening PyForge windows.")

    registry = getattr(app, "_pyforge_window_controllers", None)
    if registry is None:
        registry = []
        app._pyforge_window_controllers = registry

    if controller not in registry:
        registry.append(controller)

    window = getattr(controller, "window", None)
    if window is None:
        raise TypeError("A PyForge window controller must expose a .window widget.")

    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

    def release_controller(*_args):
        try:
            registry.remove(controller)
        except ValueError:
            pass

    # Avoid connecting the same release callback more than once.
    if not getattr(controller, "_pyforge_window_registered", False):
        window.destroyed.connect(release_controller)
        controller._pyforge_window_registered = True

    return controller

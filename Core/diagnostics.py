"""Crash and startup diagnostics for PyForge.

Logs live at ~/.local/share/PyForge/crash.log. faulthandler also writes native
fatal-signal traces there when Python can capture them.
"""

import faulthandler
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_LOG_HANDLE = None
_INSTALLED = False
_PREVIOUS_EXCEPTHOOK = None


def _log_path():
    return Path.home() / ".local" / "share" / "PyForge" / "crash.log"


def log_event(message):
    """Append a timestamped diagnostic event without interrupting the app."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{datetime.now().astimezone().isoformat()}] {message}\n")
    except Exception:
        # Diagnostics must never become the reason the IDE fails to launch.
        pass


def log_exception(context, exception):
    """Write a handled exception and its traceback to the diagnostic log."""
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"\n[{datetime.now().astimezone().isoformat()}] {context}\n")
            traceback.print_exception(
                type(exception), exception, exception.__traceback__, file=stream
            )
    except Exception:
        pass


def install_diagnostics():
    """Install process-wide Python and native-crash logging once per process."""
    global _LOG_HANDLE, _INSTALLED, _PREVIOUS_EXCEPTHOOK
    if _INSTALLED:
        return _log_path()
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _LOG_HANDLE = path.open("a", encoding="utf-8", buffering=1)
        _LOG_HANDLE.write(
            f"\n[{datetime.now().astimezone().isoformat()}] "
            f"PyForge started (pid={os.getpid()}, python={sys.version.split()[0]})\n"
        )
        faulthandler.enable(file=_LOG_HANDLE, all_threads=True)
    except Exception as error:
        log_event(f"Could not enable fatal-crash logging: {error!r}")

    _PREVIOUS_EXCEPTHOOK = sys.excepthook

    def handle_exception(exc_type, exc_value, exc_tb):
        try:
            log_exception("Uncaught Python exception", exc_value)
        finally:
            if _PREVIOUS_EXCEPTHOOK:
                _PREVIOUS_EXCEPTHOOK(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception

    if hasattr(threading, "excepthook"):
        def handle_thread_exception(args):
            log_exception(
                f"Uncaught exception in thread {args.thread.name!r}", args.exc_value
            )
            threading.__excepthook__(args)
        threading.excepthook = handle_thread_exception

    _INSTALLED = True
    log_event("Crash diagnostics enabled")
    return _log_path()

from __future__ import annotations

import faulthandler
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
import traceback
from types import TracebackType
from pathlib import Path

from PySide6 import QtCore, QtWidgets

from .ui.main_window import MainWindow


_LOGGING_CONFIGURED = False
_FAULT_HANDLER_FILE: object | None = None


def _log_path() -> Path:
    cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "shelldeck" / "shelldeck.log"


def _configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    log_file = _log_path()
    log_dir = log_file.parent
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        _LOGGING_CONFIGURED = True
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if os.environ.get("SHELLDECK_DEBUG") == "1":
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        root.addHandler(stderr_handler)

    _LOGGING_CONFIGURED = True


def _install_exception_hooks() -> None:
    logger = logging.getLogger(__name__)

    def _unhandled_exception(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        logger.error(
            "Uncaught exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc, tb)),
        )

    def _thread_exception(args: threading.ExceptHookArgs) -> None:
        logger.error(
            "Uncaught thread exception in %s:\n%s",
            getattr(args.thread, "name", "unknown"),
            "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
        )

    sys.excepthook = _unhandled_exception
    threading.excepthook = _thread_exception


def _install_qt_message_handler() -> None:
    logger = logging.getLogger("shelldeck.qt")

    def _qt_message_handler(
        msg_type: QtCore.QtMsgType,
        context: QtCore.QMessageLogContext,
        message: str,
    ) -> None:
        location = ""
        if context.file and context.line:
            location = f" ({context.file}:{context.line})"
        if context.function:
            location += f" [{context.function}]"

        if msg_type == QtCore.QtMsgType.QtDebugMsg:
            logger.debug("QtDebug%s: %s", location, message)
        elif msg_type == QtCore.QtMsgType.QtInfoMsg:
            logger.info("QtInfo%s: %s", location, message)
        elif msg_type == QtCore.QtMsgType.QtWarningMsg:
            logger.warning("QtWarning%s: %s", location, message)
        elif msg_type == QtCore.QtMsgType.QtCriticalMsg:
            logger.error("QtCritical%s: %s", location, message)
        else:
            logger.critical("QtFatal%s: %s", location, message)

    QtCore.qInstallMessageHandler(_qt_message_handler)


def _enable_fault_handler() -> None:
    global _FAULT_HANDLER_FILE
    logger = logging.getLogger(__name__)
    try:
        _FAULT_HANDLER_FILE = _log_path().open("a", encoding="utf-8")
        faulthandler.enable(file=_FAULT_HANDLER_FILE, all_threads=True)
        if os.environ.get("SHELLDECK_DEBUG") == "1":
            faulthandler.dump_traceback_later(15, repeat=True, file=_FAULT_HANDLER_FILE)
    except Exception:
        logger.exception("Failed to enable faulthandler")


def _log_startup() -> None:
    logging.getLogger(__name__).info(
        "starting shelldeck executable=%s version=%s argv=%s cwd=%s SHELLDECK_DEBUG=%s SHELLDECK_TERM_BACKEND=%s",
        sys.executable,
        sys.version,
        sys.argv,
        os.getcwd(),
        os.environ.get("SHELLDECK_DEBUG", ""),
        os.environ.get("SHELLDECK_TERM_BACKEND", ""),
    )


def main() -> None:
    _configure_logging()
    _install_exception_hooks()
    _install_qt_message_handler()
    _enable_fault_handler()
    _log_startup()
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("ShellDeck")
    app.setOrganizationName("ShellDeck")
    app.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    window = MainWindow(app)
    window.show()
    try:
        raise SystemExit(app.exec())
    finally:
        if os.environ.get("SHELLDECK_DEBUG") == "1":
            try:
                faulthandler.cancel_dump_traceback_later()
            except Exception:
                logging.getLogger(__name__).debug("Failed to cancel faulthandler timer")

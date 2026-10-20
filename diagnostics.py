"""Local-only diagnostic logging and Tkinter callback error handling."""

import logging
from pathlib import Path
from tkinter import messagebox


LOGGER = logging.getLogger("developer_launchpad")


def configure_logging(log_path):
    """Write concise diagnostics to the per-user data folder, never command output."""
    LOGGER.setLevel(logging.INFO)
    if any(isinstance(handler, logging.FileHandler) for handler in LOGGER.handlers):
        return LOGGER
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
    except OSError:
        LOGGER.addHandler(logging.NullHandler())
    return LOGGER


def log_error(context, error):
    """Log the operation and error text without captured output or environment."""
    LOGGER.error("%s: %s: %s", context, type(error).__name__, error)


def install_tk_exception_handler(root):
    """Show one useful message when a Tkinter callback raises unexpectedly."""
    def report_callback_exception(error_type, error, _traceback):
        LOGGER.error("Unexpected GUI callback error: %s: %s", error_type.__name__, error)
        messagebox.showerror(
            "Unexpected application error",
            "Developer Launchpad encountered an unexpected error.\n\n"
            f"Details: {error}\n\nSee Settings → Diagnostics for the local log.",
            parent=root,
        )

    root.report_callback_exception = report_callback_exception

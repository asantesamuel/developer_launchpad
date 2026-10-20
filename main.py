"""Application entry point for Developer Launchpad."""

import tkinter as tk

from app import DeveloperLaunchpad
from diagnostics import configure_logging
from storage import APP_DIR


def main():
    """Create the main window and start Tkinter's event loop."""
    configure_logging(APP_DIR / "developer_launchpad.log")
    root = tk.Tk()
    DeveloperLaunchpad(root)
    root.mainloop()


if __name__ == "__main__":
    main()

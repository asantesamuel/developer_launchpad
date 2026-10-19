"""Application entry point for Developer Launchpad."""

import tkinter as tk

from app import DeveloperLaunchpad


def main():
    """Create the main window and start Tkinter's event loop."""
    root = tk.Tk()
    DeveloperLaunchpad(root)
    root.mainloop()


if __name__ == "__main__":
    main()

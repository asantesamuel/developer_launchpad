"""Background-safe execution of explicitly selected project commands."""

import os
import shutil
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from command_profiles import CommandProfile


@dataclass(frozen=True)
class CommandEvent:
    """A message sent from the process worker to the Tkinter event loop."""

    kind: str
    stream: str = ""
    text: str = ""
    returncode: int | None = None
    stopped: bool = False
    pid: int | None = None


@dataclass(frozen=True)
class CommandResult:
    """The final result of a command process."""

    returncode: int | None
    stopped: bool


class CommandExecutionError(RuntimeError):
    """A command could not be started."""


def terminate_process_tree(process):
    """Stop a process and its descendants after an explicit Stop request."""
    if process.poll() is not None:
        return

    if os.name == "nt":
        taskkill = shutil.which("taskkill.exe")
        if not taskkill:
            system_root = os.environ.get("SYSTEMROOT", r"C:\Windows")
            candidate = Path(system_root) / "System32" / "taskkill.exe"
            taskkill = str(candidate) if candidate.is_file() else None
        if taskkill:
            try:
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=3)
            return
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass

    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        except OSError:
            pass


def run_command(profile, working_directory, events, stop_event, popen_factory=None):
    """Run one profile, streaming stdout and stderr as queue events.

    No shell parses the profile: the executable and arguments are passed as an
    argv list. The caller owns the worker thread and consumes *events* on its
    main thread.
    """
    if not isinstance(profile, CommandProfile):
        raise TypeError("profile must be a validated CommandProfile")
    if stop_event.is_set():
        result = CommandResult(None, True)
        events.put(CommandEvent("finished", text="Stopped before launch", stopped=True))
        return result

    directory = Path(working_directory)
    if not directory.is_dir():
        raise CommandExecutionError(f"Working directory does not exist or is not a folder: {directory}")

    argv = [profile.executable, *profile.arguments]
    events.put(CommandEvent("status", text="Starting command…"))
    popen = popen_factory or subprocess.Popen
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        process = popen(
            argv,
            cwd=str(directory),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=creationflags,
            start_new_session=os.name != "nt",
        )
    except FileNotFoundError as exc:
        raise CommandExecutionError(
            f"Executable {profile.executable!r} was not found. Install it or add it to PATH."
        ) from exc
    except OSError as exc:
        raise CommandExecutionError(f"Could not start {profile.executable!r}: {exc}") from exc

    events.put(CommandEvent("started", text="Running", pid=process.pid))

    def read_stream(stream_name, pipe):
        try:
            for line in iter(pipe.readline, ""):
                events.put(CommandEvent("output", stream=stream_name, text=line))
        except OSError as exc:
            events.put(CommandEvent("output", stream=stream_name, text=f"[output read error: {exc}]\n"))
        finally:
            pipe.close()

    readers = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()

    stopped = False
    while process.poll() is None:
        if stop_event.is_set() and not stopped:
            stopped = True
            events.put(CommandEvent("status", text="Stopping process and child processes…"))
            terminate_process_tree(process)
        time.sleep(0.05)

    returncode = process.wait()
    for reader in readers:
        reader.join(timeout=2)
    result = CommandResult(returncode, stopped)
    events.put(CommandEvent("finished", returncode=returncode, stopped=stopped))
    return result

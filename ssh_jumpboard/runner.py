"""Command execution helpers."""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import Optional

from .key_agent import AskpassContext


def run_chain_in_current_tty(
    jump_cmd: list[str],
    target_cmd: list[str],
    askpass: Optional[AskpassContext] = None,
) -> int:
    """Run the SSH hop chain in the current terminal."""
    env = os.environ.copy()
    askpass_ctx = askpass
    if askpass_ctx is not None:
        env.update(askpass_ctx.env)
    try:
        joined = " && ".join(shlex.join(cmd) for cmd in (jump_cmd, target_cmd))
        proc = subprocess.run(["/bin/sh", "-c", joined], env=env)
        return proc.returncode
    finally:
        if askpass_ctx is not None:
            askpass_ctx.cleanup()


def open_external_terminal(cmdline: str) -> int:
    """Attempt to open an external terminal and run the provided command line."""
    if os.name == "nt":
        return subprocess.call([
            "cmd.exe",
            "/c",
            "start",
            "ssh-jumpboard",
            "cmd.exe",
            "/k",
            cmdline,
        ])
    if sys.platform == "darwin":
        script = f'tell application "Terminal" to do script "{cmdline}"'
        return subprocess.call([
            "osascript",
            "-e",
            script,
        ])
    for candidate in ("gnome-terminal", "konsole", "xfce4-terminal", "xterm"):
        if shutil.which(candidate):
            return subprocess.call([candidate, "-e", cmdline])
    return subprocess.call(["/bin/sh", "-c", cmdline])

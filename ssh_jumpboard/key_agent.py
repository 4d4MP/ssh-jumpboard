"""SSH agent and passphrase helpers."""
from __future__ import annotations

from dataclasses import dataclass
import os
import stat
import subprocess
import tempfile
from typing import Callable, Optional

from .errors import AgentUnavailable


@dataclass
class AgentStatus:
    has_agent: bool
    has_loaded_keys: bool
    kind: str = "ssh-agent"


@dataclass
class AskpassContext:
    script_path: str
    env: dict[str, str]

    def cleanup(self) -> None:
        try:
            os.remove(self.script_path)
        except FileNotFoundError:
            pass


@dataclass
class EnsureResult:
    status: AgentStatus
    askpass: Optional[AskpassContext]


def detect_agent() -> AgentStatus:
    """Detect presence of an SSH agent and whether it has keys."""
    sock = os.environ.get("SSH_AUTH_SOCK")
    has_agent = bool(sock and os.path.exists(sock))
    has_loaded_keys = False
    kind = "ssh-agent"
    if has_agent:
        try:
            proc = subprocess.run(
                ["ssh-add", "-l"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError:
            return AgentStatus(False, False, "ssh-add-missing")
        if proc.returncode == 0 and "The agent has no identities" not in proc.stdout:
            has_loaded_keys = True
    else:
        kind = "none"
    return AgentStatus(has_agent, has_loaded_keys, kind)


def ensure_key_loaded(gui_prompt: Callable[[], Optional[str]]) -> EnsureResult:
    """Ensure a key is available, prompting for passphrase when needed."""
    status = detect_agent()
    if status.has_agent and status.has_loaded_keys:
        return EnsureResult(status=status, askpass=None)

    passphrase = gui_prompt()
    if passphrase is None:
        raise AgentUnavailable("User cancelled passphrase entry")

    try:
        if status.has_agent:
            proc = subprocess.run(
                ["ssh-add"],
                input=f"{passphrase}\n",
                text=True,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if proc.returncode != 0:
                raise AgentUnavailable(proc.stderr.strip() or "Failed to load key into agent")
            new_status = detect_agent()
            return EnsureResult(status=new_status, askpass=None)

        askpass = make_askpass_wrapper(passphrase)
        return EnsureResult(status=status, askpass=askpass)
    finally:
        passphrase = ""


def make_askpass_wrapper(passphrase: str) -> AskpassContext:
    """Create a temporary SSH_ASKPASS helper script."""
    fd, path = tempfile.mkstemp(prefix="ssh_jumpboard_askpass_", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n")
            fh.write("printf '%s' ")
            fh.write("\"" + passphrase.replace("\\", "\\\\").replace("\"", "\\\"") + "\"\n")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        env = {
            "SSH_ASKPASS": path,
            "SSH_ASKPASS_REQUIRE": "force",
        }
        return AskpassContext(script_path=path, env=env)
    except Exception:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise

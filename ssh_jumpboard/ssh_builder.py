"""Helpers for constructing ssh command invocations."""
from __future__ import annotations

from .config import Config


def build_jump_command(cfg: Config) -> list[str]:
    """Return the jump host SSH command."""
    return ["ssh", "-A", f"{cfg.jump_user}@{cfg.jump_ip}"]


def build_target_command(target_ip: str) -> list[str]:
    """Return the target SSH command."""
    return ["ssh", target_ip]


def preview_chain(cfg: Config, target_ip: str) -> str:
    """Return a human readable preview of the commands that will run."""
    return "\n".join(
        [
            f"ssh -A {cfg.jump_user}@{cfg.jump_ip}",
            f"ssh {target_ip}",
        ]
    )

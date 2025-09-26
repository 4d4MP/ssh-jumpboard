"""Configuration management for ssh-jumpboard."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from platformdirs import PlatformDirs

from .errors import ConfigNotInitialized, ValidationError

_HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")
_ALIAS_PATTERN = re.compile(r"^[a-z0-9._-]{1,32}$")


def _config_file_path() -> Path:
    dirs = PlatformDirs(appname="ssh-jumpboard")
    return Path(dirs.user_config_dir) / "config.json"


@dataclass
class Config:
    """Application configuration."""

    jump_user: str
    jump_ip: str
    history_limit: int = 10
    aliases: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    launch_external_terminal: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        return cls(
            jump_user=data["jump_user"],
            jump_ip=data["jump_ip"],
            history_limit=data.get("history_limit", 10),
            aliases=dict(data.get("aliases", {})),
            history=list(data.get("history", [])),
            launch_external_terminal=data.get("launch_external_terminal", False),
        )


def _validate_user(user: str) -> None:
    if not user:
        raise ValidationError("jump_user must be provided")


def _validate_host(host: str, label: str) -> None:
    if not host or not _HOST_PATTERN.match(host):
        raise ValidationError(f"{label} must be a valid hostname or IP address")


def load_config() -> Config:
    """Load configuration from disk."""
    path = _config_file_path()
    if not path.exists():
        raise ConfigNotInitialized("Configuration has not been initialised")
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    cfg = Config.from_dict(data)
    _validate_user(cfg.jump_user)
    _validate_host(cfg.jump_ip, "jump_ip")
    return cfg


def _ensure_config_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def save_config(cfg: Config) -> None:
    """Persist configuration atomically to disk."""
    path = _config_file_path()
    _ensure_config_dir(path)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp_file:
            json.dump(cfg.to_dict(), tmp_file, indent=2)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def init_config(jump_user: str, jump_ip: str) -> Config:
    """Create a new configuration object and persist it."""
    _validate_user(jump_user)
    _validate_host(jump_ip, "jump_ip")
    cfg = Config(jump_user=jump_user, jump_ip=jump_ip)
    save_config(cfg)
    return cfg


def set_alias(cfg: Config, name: str, ip: str) -> None:
    """Create or update an alias."""
    if not _ALIAS_PATTERN.match(name):
        raise ValidationError("Alias names must match ^[a-z0-9._-]{1,32}$")
    _validate_host(ip, "alias ip")
    cfg.aliases[name] = ip
    save_config(cfg)


def remove_alias(cfg: Config, name: str) -> None:
    """Remove an alias by name."""
    if name not in cfg.aliases:
        raise ValidationError(f"Alias '{name}' does not exist")
    del cfg.aliases[name]
    save_config(cfg)

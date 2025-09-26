"""Command line interface for ssh-jumpboard."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from getpass import getpass
from typing import Optional

from . import history
from .config import Config, init_config, load_config, remove_alias, set_alias
from .errors import AgentUnavailable, ConfigNotInitialized, ValidationError, SshNotFound
from .key_agent import ensure_key_loaded
from .runner import run_chain_in_current_tty
from .ssh_builder import build_jump_command, build_target_command, preview_chain

EXIT_SUCCESS = 0
EXIT_NO_CONFIG = 2
EXIT_INVALID_INPUT = 3
EXIT_SSH_MISSING = 4

_HOST_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def _require_ssh() -> None:
    if shutil.which("ssh") is None:
        raise SshNotFound("OpenSSH client not found in PATH")


def _load_config_or_exit() -> Config:
    try:
        return load_config()
    except ConfigNotInitialized as exc:
        print("Configuration not initialised. Run 'ssh-jumpboard init' first.", file=sys.stderr)
        raise SystemExit(EXIT_NO_CONFIG) from exc


def cmd_init(args: argparse.Namespace) -> int:
    try:
        init_config(args.user, args.jump_ip)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    print("Configuration saved.")
    return EXIT_SUCCESS


def _resolve_target(cfg: Config, target_or_alias: str) -> str:
    if target_or_alias in cfg.aliases:
        return cfg.aliases[target_or_alias]
    return target_or_alias


def _prompt_passphrase() -> Optional[str]:
    try:
        return getpass("SSH key passphrase: ")
    except (EOFError, KeyboardInterrupt):
        return None


def cmd_connect(args: argparse.Namespace) -> int:
    try:
        _require_ssh()
    except SshNotFound as exc:
        print("Install OpenSSH and retry.", file=sys.stderr)
        return EXIT_SSH_MISSING
    cfg = _load_config_or_exit()
    target = _resolve_target(cfg, args.target)
    if not _HOST_PATTERN.match(target):
        print("Invalid target hostname or IP", file=sys.stderr)
        return EXIT_INVALID_INPUT
    preview = preview_chain(cfg, target)
    print("Will run:\n" + preview)
    try:
        result = ensure_key_loaded(_prompt_passphrase)
    except AgentUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_INVALID_INPUT
    jump_cmd = build_jump_command(cfg)
    target_cmd = build_target_command(target)
    exit_code = run_chain_in_current_tty(jump_cmd, target_cmd, result.askpass)
    if exit_code == 0:
        history.record(cfg, target)
    else:
        print(f"Failed to connect to {target} (exit {exit_code}). See terminal output.", file=sys.stderr)
    return exit_code


def cmd_last(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    items = history.list_recent(cfg)
    if not items:
        print("No history yet.")
        return EXIT_SUCCESS
    now = datetime.now(timezone.utc)
    for idx, item in enumerate(items, start=1):
        delta = now - item.ts
        print(f"{idx}: {item.target_ip} ({_format_timedelta(delta)} ago)")
    return EXIT_SUCCESS


def cmd_again(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    index = args.index or 1
    items = history.list_recent(cfg)
    if index < 1 or index > len(items):
        print("Invalid history index", file=sys.stderr)
        return EXIT_INVALID_INPUT
    target = items[index - 1].target_ip
    return cmd_connect(argparse.Namespace(target=target))


def cmd_alias_set(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    try:
        set_alias(cfg, args.name, args.ip)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(f"Alias '{args.name}' saved.")
    return EXIT_SUCCESS


def cmd_alias_rm(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    try:
        remove_alias(cfg, args.name)
    except ValidationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return EXIT_INVALID_INPUT
    print(f"Alias '{args.name}' removed.")
    return EXIT_SUCCESS


def cmd_alias_list(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    if not cfg.aliases:
        print("No aliases defined.")
        return EXIT_SUCCESS
    for name, ip in sorted(cfg.aliases.items()):
        print(f"{name}: {ip}")
    return EXIT_SUCCESS


def cmd_history_clear(args: argparse.Namespace) -> int:
    cfg = _load_config_or_exit()
    history.clear(cfg)
    print("History cleared.")
    return EXIT_SUCCESS


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        _require_ssh()
    except SshNotFound as exc:
        print("Install OpenSSH and retry.", file=sys.stderr)
        return EXIT_SSH_MISSING
    try:
        load_config()
    except ConfigNotInitialized:
        print("Configuration not initialised.")
        return EXIT_NO_CONFIG
    print("All checks passed.")
    return EXIT_SUCCESS


def _format_timedelta(delta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ssh-jumpboard")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="Initialise jump settings")
    init_p.add_argument("--user", required=True)
    init_p.add_argument("--jump-ip", required=True)
    init_p.set_defaults(func=cmd_init)

    connect_p = sub.add_parser("connect", help="Connect to a target host")
    connect_p.add_argument("target")
    connect_p.set_defaults(func=cmd_connect)

    last_p = sub.add_parser("last", help="Show recent targets")
    last_p.set_defaults(func=cmd_last)

    again_p = sub.add_parser("again", help="Reconnect to a recent target")
    again_p.add_argument("index", nargs="?", type=int)
    again_p.set_defaults(func=cmd_again)

    alias_p = sub.add_parser("alias", help="Manage aliases")
    alias_sub = alias_p.add_subparsers(dest="alias_cmd", required=True)

    alias_set = alias_sub.add_parser("set", help="Create or update an alias")
    alias_set.add_argument("name")
    alias_set.add_argument("ip")
    alias_set.set_defaults(func=cmd_alias_set)

    alias_rm = alias_sub.add_parser("rm", help="Remove an alias")
    alias_rm.add_argument("name")
    alias_rm.set_defaults(func=cmd_alias_rm)

    alias_list = alias_sub.add_parser("list", help="List aliases")
    alias_list.set_defaults(func=cmd_alias_list)

    history_p = sub.add_parser("history", help="Manage history")
    history_p.add_argument("--clear", action="store_true")
    history_p.set_defaults(func=lambda args: cmd_history_clear(args) if args.clear else cmd_last(args))

    doctor_p = sub.add_parser("doctor", help="Check environment")
    doctor_p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

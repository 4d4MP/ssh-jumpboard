"""Connection history helpers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from .config import Config, save_config


@dataclass
class HistoryItem:
    target_ip: str
    ts: datetime


def _serialise(item: HistoryItem) -> dict[str, str]:
    return {"target_ip": item.target_ip, "ts": item.ts.isoformat()}


def _deserialise(entry: dict[str, str]) -> HistoryItem:
    ts_raw = entry.get("ts")
    ts = datetime.fromisoformat(ts_raw) if ts_raw else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return HistoryItem(target_ip=entry["target_ip"], ts=ts)


def record(cfg: Config, target_ip: str) -> None:
    """Record a new history entry, deduping immediate repeats."""
    now = datetime.now(timezone.utc)
    entries = cfg.history
    if entries and entries[0]["target_ip"] == target_ip:
        entries[0]["ts"] = now.isoformat()
    else:
        entries.insert(0, _serialise(HistoryItem(target_ip=target_ip, ts=now)))
    limit = max(cfg.history_limit, 0)
    if limit:
        del entries[limit:]
    save_config(cfg)


def list_recent(cfg: Config, limit: int | None = None) -> List[HistoryItem]:
    """Return recent history entries."""
    entries = cfg.history
    if limit is not None:
        entries = entries[:limit]
    return [_deserialise(item) for item in entries]


def clear(cfg: Config) -> None:
    """Clear history for the configuration."""
    cfg.history.clear()
    save_config(cfg)

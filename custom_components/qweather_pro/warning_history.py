"""Local, restart-safe history for normalized household warning sources."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any, Mapping


_RETENTION = timedelta(hours=24)
_LEVEL_RANK = {"blue": 1, "yellow": 2, "orange": 3, "red": 4}
_SOURCE_LEVELS = ("city", "district")


def _source_snapshot(contract: Mapping[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Index public source warnings by source level and stable hazard identity."""
    snapshot: dict[str, dict[str, dict[str, Any]]] = {}
    sources = contract.get("sources")
    if not isinstance(sources, Mapping):
        return snapshot
    for source_level in _SOURCE_LEVELS:
        source = sources.get(source_level)
        warnings = source.get("warnings") if isinstance(source, Mapping) else None
        if not isinstance(warnings, list):
            continue
        for warning in warnings:
            if isinstance(warning, Mapping) and isinstance(
                hazard_id := warning.get("hazard_id"), str
            ):
                snapshot.setdefault(source_level, {})[hazard_id] = dict(warning)
    return snapshot


def _event_action(previous: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> str:
    """Classify one normalized source transition without inspecting provider titles."""
    if previous is None:
        return "issued"
    if current is None:
        return "cleared"
    previous_level = previous.get("level")
    current_level = current.get("level")
    if (
        isinstance(previous_level, str)
        and isinstance(current_level, str)
        and previous_level != current_level
    ):
        return (
            "upgraded"
            if _LEVEL_RANK[current_level] > _LEVEL_RANK[previous_level]
            else "downgraded"
        )
    return "updated"


class WarningHistory:
    """Track source-level warning transitions and retain only their recent window."""

    def __init__(
        self,
        jurisdiction_key: str,
        *,
        events: list[dict[str, Any]] | None = None,
        source_snapshot: dict[str, dict[str, dict[str, Any]]] | None = None,
    ) -> None:
        self.jurisdiction_key = jurisdiction_key
        self._events = events or []
        self._source_snapshot = source_snapshot or {}

    @classmethod
    def from_storage(
        cls, payload: object, jurisdiction_key: str, now: datetime
    ) -> WarningHistory:
        """Restore a matching local history or reset it after a jurisdiction change."""
        if not isinstance(payload, Mapping) or payload.get("jurisdiction") != jurisdiction_key:
            return cls(jurisdiction_key)
        events = payload.get("events")
        source_snapshot = payload.get("source_snapshot")
        history = cls(
            jurisdiction_key,
            events=[dict(event) for event in events if isinstance(event, Mapping)]
            if isinstance(events, list)
            else [],
            source_snapshot=deepcopy(source_snapshot)
            if isinstance(source_snapshot, dict)
            else {},
        )
        history.prune(now)
        return history

    @property
    def events(self) -> list[dict[str, Any]]:
        """Return newest-first JSON-safe history nodes for the HA-facing contract."""
        return sorted(
            (deepcopy(event) for event in self._events),
            key=lambda event: str(event.get("occurred_at", "")),
            reverse=True,
        )

    def observe(self, contract: Mapping[str, Any], now: datetime) -> bool:
        """Record every source-level change in one newly successful contract snapshot."""
        current_snapshot = _source_snapshot(contract)
        changed = False
        for source_level in _SOURCE_LEVELS:
            previous = self._source_snapshot.get(source_level, {})
            current = current_snapshot.get(source_level, {})
            for hazard_id in previous.keys() | current.keys():
                before = previous.get(hazard_id)
                after = current.get(hazard_id)
                if before == after:
                    continue
                changed = True
                warning = after or before
                if warning is None:
                    continue
                self._events.append(
                    {
                        "hazard_id": hazard_id,
                        "hazard_name": warning.get("hazard_name"),
                        "source_level": source_level,
                        "action": _event_action(before, after),
                        "level": warning.get("level"),
                        "occurred_at": now.isoformat(),
                        "warning": deepcopy(warning),
                    }
                )
        self._source_snapshot = current_snapshot
        return self.prune(now) or changed

    def prune(self, now: datetime) -> bool:
        """Drop events outside the local 24-hour retention window."""
        cutoff = now - _RETENTION
        retained: list[dict[str, Any]] = []
        changed = False
        for event in self._events:
            occurred_at = event.get("occurred_at")
            try:
                timestamp = datetime.fromisoformat(str(occurred_at).replace("Z", "+00:00"))
            except ValueError:
                changed = True
                continue
            if timestamp.tzinfo is None or timestamp < cutoff:
                changed = True
                continue
            retained.append(event)
        if changed:
            self._events = retained
        return changed

    def as_storage(self) -> dict[str, object]:
        """Return only local HA storage data; callers must never log this payload."""
        return {
            "jurisdiction": self.jurisdiction_key,
            "events": deepcopy(self._events),
            "source_snapshot": deepcopy(self._source_snapshot),
        }

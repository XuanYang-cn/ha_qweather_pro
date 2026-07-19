"""Normalize provider alerts into one household-effective warning contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Mapping


_LEVELS = {"blue": 1, "yellow": 2, "orange": 3, "red": 4}
_LEVEL_ALIASES = {
    "minor": "blue",
    "moderate": "yellow",
    "severe": "orange",
    "extreme": "red",
    "amber": "orange",
}
_TITLE_LEVELS = (("红色", "red"), ("橙色", "orange"), ("黄色", "yellow"), ("蓝色", "blue"))
_CLEAR_STATUSES = {"cancelled", "canceled", "cleared", "expired", "ended", "resolved"}
_CLEAR_TITLE = re.compile(r"(?:解除|取消|撤销|终止)")


class WarningContractError(ValueError):
    """Raised when an applicable provider record cannot form a safe contract."""


@dataclass(frozen=True, slots=True)
class WarningJurisdiction:
    """The locally configured district and its structured parent city."""

    district_id: str
    district_name: str
    city_id: str
    city_name: str
    country: str
    longitude: str
    latitude: str

    @property
    def label(self) -> str:
        return " · ".join((self.district_name, self.city_name, self.country))


@dataclass(frozen=True, slots=True)
class _WarningEvent:
    source_level: str
    hazard_id: str
    hazard_name: str
    issued_at: datetime
    active_warning: dict[str, str] | None


def _required_text(value: object, field: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise WarningContractError(f"Warning record has no reliable {field}")


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _provider_time(value: object, field: str) -> tuple[str, datetime]:
    text = _required_text(value, field)
    try:
        timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise WarningContractError(f"Warning record has an invalid {field}") from error
    if timestamp.tzinfo is None:
        raise WarningContractError(f"Warning record has an invalid {field}")
    return text, timestamp


def _first_text(record: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = _optional_text(record.get(name))
        if value is not None:
            return value
    return None


def _event_type(record: Mapping[str, Any]) -> tuple[str, str]:
    event_type = record.get("eventType")
    if isinstance(event_type, Mapping):
        code = _first_text(event_type, "id", "code")
        name = _first_text(event_type, "name")
    else:
        code = None
        name = None
    code = code or _first_text(record, "eventCode", "typeCode", "type_id")
    name = name or _first_text(record, "typeName", "type")
    if name is None:
        raise WarningContractError("Warning record has no reliable hazard name")
    # A provider type name is a structured field.  It is a deterministic last
    # resort only when an otherwise usable record lacks a dedicated type code.
    return code or f"provider-name:{name.casefold()}", name


def _normal_level(value: object) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("code") or value.get("name")
    text = _optional_text(value)
    if text is None:
        return None
    normalized = text.casefold()
    return _LEVEL_ALIASES.get(normalized, normalized if normalized in _LEVELS else None)


def _warning_level(record: Mapping[str, Any], title: str) -> str:
    for field in ("severityColor", "levelColor", "color", "severity", "level", "levelCode"):
        level = _normal_level(record.get(field))
        if level is not None:
            return level
    for marker, level in _TITLE_LEVELS:
        if marker in title:
            return level
    raise WarningContractError("Warning record has no reliable level")


def _is_clear(record: Mapping[str, Any], title: str) -> bool:
    status = _optional_text(record.get("status") or record.get("warningStatus"))
    return (
        status is not None and status.casefold() in _CLEAR_STATUSES
    ) or bool(_CLEAR_TITLE.search(title))


def _normalize_event(
    record: Mapping[str, Any],
    *,
    source_level: str,
) -> _WarningEvent:
    hazard_id, hazard_name = _event_type(record)
    title = _required_text(record.get("headline") or record.get("title"), "title")
    issued, issued_at = _provider_time(
        record.get("issuedTime") or record.get("pubTime"), "issued time"
    )
    if _is_clear(record, title):
        return _WarningEvent(source_level, hazard_id, hazard_name, issued_at, None)

    effective, _ = _provider_time(
        record.get("effectiveTime") or record.get("startTime"), "effective time"
    )
    expires, _ = _provider_time(
        record.get("expireTime") or record.get("endTime"), "expiry time"
    )
    active_warning = {
        "hazard_id": hazard_id,
        "hazard_name": hazard_name,
        "level": _warning_level(record, title),
        "source_level": source_level,
        "issued": issued,
        "effective": effective,
        "expires": expires,
        "title": title,
        "text": _required_text(
            record.get("description") or record.get("text"), "text"
        ),
        "instruction": _required_text(
            record.get("instruction") or record.get("defense"), "instruction"
        ),
        "sender": _required_text(
            record.get("senderName") or record.get("sender"), "sender"
        ),
        "source": "QWeather",
    }
    return _WarningEvent(source_level, hazard_id, hazard_name, issued_at, active_warning)


def _current_source_warnings(
    alerts: object,
    *,
    source_level: str,
) -> dict[str, dict[str, str]]:
    if not isinstance(alerts, list):
        raise WarningContractError("Warning provider response has no alert list")
    latest: dict[str, tuple[datetime, int, _WarningEvent]] = {}
    for index, record in enumerate(alerts):
        if not isinstance(record, Mapping):
            raise WarningContractError("Warning provider response contains an invalid record")
        event = _normalize_event(record, source_level=source_level)
        candidate = (event.issued_at, index, event)
        if event.hazard_id not in latest or candidate[:2] > latest[event.hazard_id][:2]:
            latest[event.hazard_id] = candidate
    return {
        hazard_id: event.active_warning
        for hazard_id, (_, _, event) in latest.items()
        if event.active_warning is not None
    }


def _effective_warning(sources: list[dict[str, str]]) -> dict[str, str]:
    winner = sources[0]
    for candidate in sources[1:]:
        candidate_rank = _LEVELS[candidate["level"]]
        winner_rank = _LEVELS[winner["level"]]
        if candidate_rank > winner_rank or (
            candidate_rank == winner_rank and candidate["source_level"] == "city"
        ):
            winner = candidate
    return {**winner, "source_count": len(sources)}


def build_household_warning_contract(
    jurisdiction: WarningJurisdiction,
    *,
    city_alerts: object,
    district_alerts: object,
    now: datetime,
) -> dict[str, object]:
    """Return one atomic household-effective snapshot from both source scopes."""
    if now.tzinfo is None:
        raise ValueError("A household warning contract requires an aware clock")
    city = _current_source_warnings(city_alerts, source_level="city")
    district = _current_source_warnings(district_alerts, source_level="district")
    source_by_hazard: dict[str, list[dict[str, str]]] = {}
    for source_warnings in (city, district):
        for hazard_id, warning in source_warnings.items():
            source_by_hazard.setdefault(hazard_id, []).append(warning)

    effective = [
        _effective_warning(source_by_hazard[hazard_id])
        for hazard_id in sorted(source_by_hazard)
    ]
    recent_changes = {
        hazard_id: max(warning["issued"] for warning in warnings)
        for hazard_id, warnings in source_by_hazard.items()
    }
    return {
        "state": "active" if effective else "clear",
        "jurisdiction": jurisdiction.label,
        "effective_warnings": effective,
        "sources": source_by_hazard,
        "recent_changes": recent_changes,
        "published_at": now.isoformat(),
    }

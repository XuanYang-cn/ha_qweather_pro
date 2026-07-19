"""Normalize provider alerts into one household-effective warning contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any, Literal, Mapping


_LEVELS = {"blue": 1, "yellow": 2, "orange": 3, "red": 4}
_LEVEL_ALIASES = {
    "minor": "blue",
    "moderate": "yellow",
    "severe": "orange",
    "extreme": "red",
    "amber": "orange",
    "blue": "blue",
    "yellow": "yellow",
    "orange": "orange",
    "red": "red",
    "蓝": "blue",
    "蓝色": "blue",
    "黄": "yellow",
    "黄色": "yellow",
    "橙": "orange",
    "橙色": "orange",
    "红": "red",
    "红色": "red",
}
_TITLE_LEVELS = (("红色", "red"), ("橙色", "orange"), ("黄色", "yellow"), ("蓝色", "blue"))
_CLEAR_STATUSES = {
    "cancelled",
    "canceled",
    "cleared",
    "expired",
    "ended",
    "resolved",
    "revoked",
    "terminated",
    "解除",
    "取消",
    "撤销",
    "终止",
}
_CLEAR_TITLE = re.compile(r"(?:解除|取消|撤销|终止)")
WarningSourceLevel = Literal["city", "district"]
WarningScope = Literal["city", "district", "other"]

_SCOPE_ALIASES: dict[str, WarningScope] = {
    "municipal": "city",
    "city": "city",
    "district": "district",
    "county": "district",
    "other": "other",
}


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

    def label_for_source(self, source_level: WarningSourceLevel) -> str:
        """Return the configured administrative label for one provider source."""
        if source_level == "city":
            return " · ".join((self.city_name, self.country))
        if source_level == "district":
            return self.label
        raise ValueError(f"Unknown warning source level: {source_level}")


@dataclass(frozen=True, slots=True)
class _WarningEvent:
    """One latest provider event for a source-level and hazard pair."""

    source_level: WarningSourceLevel
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
    code = code or _first_text(record, "eventCode", "typeCode", "type_id", "type")
    name = name or _first_text(record, "typeName", "type")
    if name is None:
        raise WarningContractError("Warning record has no reliable hazard name")
    # A provider type name is a structured field. It is a deterministic last
    # resort only when an otherwise usable record lacks a dedicated type code.
    return code or f"provider-name:{name.casefold()}", name


def _normal_level(value: object) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("code") or value.get("name")
    text = _optional_text(value)
    if text is None:
        return None
    return _LEVEL_ALIASES.get(text.casefold())


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
    source_level: WarningSourceLevel,
    jurisdiction: WarningJurisdiction,
    now: datetime,
) -> _WarningEvent:
    hazard_id, hazard_name = _event_type(record)
    title = _optional_text(record.get("headline") or record.get("title"))
    issued, issued_at = _provider_time(
        record.get("issuedTime") or record.get("pubTime"), "issued time"
    )
    if _is_clear(record, title or ""):
        return _WarningEvent(source_level, hazard_id, hazard_name, issued_at, None)
    if title is None:
        raise WarningContractError("Warning record has no reliable title")

    effective, _ = _provider_time(
        record.get("effectiveTime") or record.get("startTime"), "effective time"
    )
    expires, expires_at = _provider_time(
        record.get("expireTime") or record.get("endTime"), "expiry time"
    )
    if expires_at <= now:
        return _WarningEvent(source_level, hazard_id, hazard_name, issued_at, None)
    active_warning = {
        "hazard_id": hazard_id,
        "hazard_name": hazard_name,
        "level": _warning_level(record, title),
        "source_level": source_level,
        "jurisdiction": jurisdiction.label_for_source(source_level),
        "issued": issued,
        "effective": effective,
        "expires": expires,
        "title": title,
        "text": _required_text(record.get("description") or record.get("text"), "text"),
        "instruction": _required_text(
            record.get("instruction") or record.get("defense"), "instruction"
        ),
        "sender": _required_text(record.get("senderName") or record.get("sender"), "sender"),
        "source": "QWeather",
    }
    return _WarningEvent(source_level, hazard_id, hazard_name, issued_at, active_warning)


def _current_source_warnings(
    alerts: object,
    *,
    source_level: WarningSourceLevel,
    jurisdiction: WarningJurisdiction,
    now: datetime,
) -> dict[str, dict[str, str]]:
    if not isinstance(alerts, list):
        raise WarningContractError("Warning provider response has no alert list")
    latest: dict[str, tuple[datetime, int, _WarningEvent]] = {}
    for index, record in enumerate(alerts):
        if not isinstance(record, Mapping):
            raise WarningContractError("Warning provider response contains an invalid record")
        event = _normalize_event(
            record,
            source_level=source_level,
            jurisdiction=jurisdiction,
            now=now,
        )
        candidate = (event.issued_at, index, event)
        if event.hazard_id not in latest or candidate[:2] > latest[event.hazard_id][:2]:
            latest[event.hazard_id] = candidate
    return {
        hazard_id: event.active_warning
        for hazard_id, (_, _, event) in latest.items()
        if event.active_warning is not None
    }


def _effective_warning(sources: list[dict[str, str]]) -> dict[str, str | int]:
    winner = sources[0]
    for candidate in sources[1:]:
        candidate_rank = _LEVELS[candidate["level"]]
        winner_rank = _LEVELS[winner["level"]]
        if candidate_rank > winner_rank or (
            candidate_rank == winner_rank and candidate["source_level"] == "city"
        ):
            winner = candidate
    return {**winner, "source_count": len(sources)}


def _location_mapping(record: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("location", "area", "administrativeArea"):
        value = record.get(key)
        if isinstance(value, Mapping):
            return value
    return {}


def _location_text(
    record: Mapping[str, Any],
    location: Mapping[str, Any],
    *names: str,
) -> str | None:
    return _first_text(location, *names) or _first_text(record, *names)


def _same_place(left: str | None, right: str) -> bool:
    return left is not None and left.casefold() == right.casefold()


def _published_scope(record: Mapping[str, Any]) -> WarningScope | None:
    scope = _optional_text(record.get("scope") or record.get("administrativeLevel"))
    if scope is None:
        location = _location_mapping(record)
        scope = _optional_text(location.get("scope") or location.get("level"))
    if scope is None:
        return None
    try:
        return _SCOPE_ALIASES[scope.casefold()]
    except KeyError as error:
        raise WarningContractError("Warning record has no reliable jurisdiction") from error


def _identified_scope(
    record: Mapping[str, Any], jurisdiction: WarningJurisdiction
) -> WarningScope | None:
    """Identify an alert's target using structured provider location fields."""
    location = _location_mapping(record)
    location_id = _location_text(record, location, "locationId", "areaId", "id")
    location_name = _location_text(record, location, "locationName", "areaName", "name")
    city_id = _location_text(record, location, "cityId", "parentId")
    city_name = _location_text(record, location, "cityName", "adm2")
    country = _location_text(record, location, "country", "countryName")

    if country is not None and not _same_place(country, jurisdiction.country):
        return "other"
    if _same_place(location_id, jurisdiction.district_id):
        if city_id is not None and not _same_place(city_id, jurisdiction.city_id):
            return "other"
        if city_name is not None and not _same_place(city_name, jurisdiction.city_name):
            return "other"
        return "district"
    if _same_place(location_id, jurisdiction.city_id):
        return "city"
    if location_id is None:
        if _same_place(location_name, jurisdiction.district_name):
            if city_name is not None and not _same_place(city_name, jurisdiction.city_name):
                return "other"
            return "district"
        if _same_place(location_name, jurisdiction.city_name):
            return "city"
    elif location_name is not None:
        return "other"
    if city_id is not None:
        return "city" if _same_place(city_id, jurisdiction.city_id) else "other"
    if city_name is not None:
        return "city" if _same_place(city_name, jurisdiction.city_name) else "other"
    return None


def _scope_for_record(
    record: Mapping[str, Any], jurisdiction: WarningJurisdiction
) -> WarningScope:
    """Classify a provider alert without using title or sender-name guesses."""
    declared_scope = _published_scope(record)
    identified_scope = _identified_scope(record, jurisdiction)
    if declared_scope == "other" or identified_scope == "other":
        return "other"
    if declared_scope is None and identified_scope is None:
        raise WarningContractError("Warning record has no reliable jurisdiction")
    if identified_scope is not None:
        if declared_scope is not None and declared_scope != identified_scope:
            raise WarningContractError("Warning record has conflicting jurisdiction")
        return identified_scope
    raise WarningContractError("Warning record has no reliable jurisdiction")


def split_household_alerts(
    alerts: object,
    jurisdiction: WarningJurisdiction,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Separate configured city/district records before normalization.

    Explicitly foreign districts are excluded. Any record whose applicability
    cannot be established from structured provider fields rejects the complete
    snapshot instead of publishing a partial warning set.
    """
    if not isinstance(alerts, list):
        raise WarningContractError("Warning provider response has no alert list")
    city: list[Mapping[str, Any]] = []
    district: list[Mapping[str, Any]] = []
    for record in alerts:
        if not isinstance(record, Mapping):
            raise WarningContractError("Warning provider response contains an invalid record")
        scope = _scope_for_record(record, jurisdiction)
        if scope == "city":
            city.append(record)
        elif scope == "district":
            district.append(record)
    return city, district


def alerts_for_configured_source(
    alerts: object,
    jurisdiction: WarningJurisdiction,
    expected_source: WarningSourceLevel,
) -> list[Mapping[str, Any]]:
    """Validate optional record jurisdiction against an explicitly scoped request.

    A city or district endpoint establishes the source for untagged provider
    records. If a record also declares a target, it must agree with that
    endpoint; explicitly foreign districts stay excluded.
    """
    if not isinstance(alerts, list):
        raise WarningContractError("Warning provider response has no alert list")
    accepted: list[Mapping[str, Any]] = []
    for record in alerts:
        if not isinstance(record, Mapping):
            raise WarningContractError("Warning provider response contains an invalid record")
        declared_scope = _published_scope(record)
        identified_scope = _identified_scope(record, jurisdiction)
        if declared_scope is None and identified_scope is None:
            accepted.append(record)
            continue
        scope = _scope_for_record(record, jurisdiction)
        if scope == "other":
            continue
        if scope != expected_source:
            raise WarningContractError("Warning record does not match its source request")
        accepted.append(record)
    return accepted


def _source_snapshot(warnings: dict[str, dict[str, str]]) -> dict[str, object]:
    ordered_warnings = [warnings[hazard_id] for hazard_id in sorted(warnings)]
    return {
        "state": "active" if ordered_warnings else "clear",
        "warnings": ordered_warnings,
    }


def _latest_issued(warnings: list[dict[str, str]]) -> str:
    """Return the chronologically latest already-validated provider issue time."""
    return max(
        warnings,
        key=lambda warning: datetime.fromisoformat(warning["issued"].replace("Z", "+00:00")),
    )["issued"]


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
    city = _current_source_warnings(
        city_alerts,
        source_level="city",
        jurisdiction=jurisdiction,
        now=now,
    )
    district = _current_source_warnings(
        district_alerts,
        source_level="district",
        jurisdiction=jurisdiction,
        now=now,
    )
    source_by_hazard: dict[str, list[dict[str, str]]] = {}
    for source_warnings in (city, district):
        for hazard_id, warning in source_warnings.items():
            source_by_hazard.setdefault(hazard_id, []).append(warning)

    effective = [
        _effective_warning(source_by_hazard[hazard_id])
        for hazard_id in sorted(source_by_hazard)
    ]
    recent_changes = {
        hazard_id: _latest_issued(warnings)
        for hazard_id, warnings in source_by_hazard.items()
    }
    return {
        "state": "active" if effective else "clear",
        "jurisdiction": jurisdiction.label,
        "effective_warnings": effective,
        "sources": {
            "city": _source_snapshot(city),
            "district": _source_snapshot(district),
        },
        "recent_changes": recent_changes,
        "history": [],
        "published_at": now.isoformat(),
    }

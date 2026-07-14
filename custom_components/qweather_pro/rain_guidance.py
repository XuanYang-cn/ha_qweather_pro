"""Conservative same-day rain guidance derived from hourly forecasts."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
RAIN_STATES = {"rain_expected", "no_rain_expected", "unconfirmed"}
RAIN_ICON_CODES = {str(code) for code in (*range(300, 319), 350, 351, 399)}


def _as_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result if result.tzinfo else None


def _has_rain_evidence(hour: Mapping[str, object]) -> bool:
    """Return true only for an explicit probability, amount, or rain code."""
    probability = hour.get("precipitation_probability")
    precipitation = hour.get("native_precipitation")
    condition = hour.get("condition")
    return (
        isinstance(probability, (int, float)) and probability >= 30
    ) or (
        isinstance(precipitation, (int, float)) and precipitation > 0
    ) or hour.get("icon") in RAIN_ICON_CODES or condition in {
        "rainy",
        "pouring",
        "lightning-rainy",
    }


def daily_rain_guidance(
    hourly: object,
    hourly_status: Mapping[str, object],
    now: datetime,
) -> dict[str, object]:
    """Return the only three allowed same-Shanghai-day rain states."""
    local_now = now.astimezone(SHANGHAI)
    end = local_now.replace(hour=23, minute=59, second=59, microsecond=999999)
    if not isinstance(hourly, list):
        return {"state": "unconfirmed", "window_end": end.isoformat()}
    candidates: list[tuple[datetime, Mapping[str, object]]] = []
    interpretable = True
    for item in hourly:
        if not isinstance(item, Mapping):
            interpretable = False
            continue
        timestamp = _as_datetime(item.get("datetime"))
        if timestamp is None:
            interpretable = False
            continue
        local_time = timestamp.astimezone(SHANGHAI)
        if local_now <= local_time <= end:
            candidates.append((local_time, item))
    if any(_has_rain_evidence(item) for _, item in candidates):
        return {"state": "rain_expected", "window_end": end.isoformat()}
    first_expected = (local_now + timedelta(hours=1)).replace(
        minute=0, second=0, microsecond=0
    )
    expected_hours = int((end.replace(minute=0, second=0, microsecond=0) - first_expected).total_seconds() // 3600) + 1
    complete = len({timestamp for timestamp, _ in candidates}) == max(expected_hours, 0)
    if (
        hourly_status.get("state") == "fresh"
        and complete
        and interpretable
        and all(item.get("icon") is not None for _, item in candidates)
    ):
        return {"state": "no_rain_expected", "window_end": end.isoformat()}
    return {"state": "unconfirmed", "window_end": end.isoformat()}

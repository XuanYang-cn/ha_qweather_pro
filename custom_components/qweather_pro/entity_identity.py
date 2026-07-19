"""Stable public entity identities and their registry migration."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


PUBLIC_ENTITY_IDS: Mapping[str, str] = {
    "weather": "weather.household_weather",
    "aqi": "sensor.household_weather_aqi",
    "today_temp_range": "sensor.household_weather_today_temperature_range",
    "warning_info": "sensor.household_weather_local_warning",
    "daily_rain_guidance": "sensor.household_weather_daily_rain_guidance",
    "precipitation_summary": "sensor.household_weather_precipitation_summary",
    "weather_summary": "sensor.household_weather_summary",
    "nationwide_warning_summary": "sensor.household_weather_nationwide_warning_summary",
    "nationwide_warning_details": "sensor.household_weather_nationwide_warning_details",
}


class EntityIdentityMigrationError(RuntimeError):
    """The registry cannot safely converge on the public entity contract."""


def public_entity_id(key: str) -> str:
    """Return the stable public entity ID for one integration-owned key."""
    try:
        return PUBLIC_ENTITY_IDS[key]
    except KeyError as error:
        raise ValueError("Unknown QWeather public entity key") from error


def _public_entries(registry: Any, config_entry_id: str) -> dict[str, Any]:
    """Find the integration's existing public entries by their stable unique IDs."""
    # Core loads the registry before config entries in production. The isolated
    # config-entry harness deliberately does not initialize global registries;
    # treating that empty registry as a first install preserves the same setup
    # behavior, and the entities below still propose canonical IDs.
    if not hasattr(registry, "entities"):
        return {}
    prefix = f"{config_entry_id}_"
    by_key: dict[str, list[Any]] = {key: [] for key in PUBLIC_ENTITY_IDS}
    for entry in er.async_entries_for_config_entry(registry, config_entry_id):
        unique_id = getattr(entry, "unique_id", None)
        if (
            getattr(entry, "platform", None) != DOMAIN
            or not isinstance(unique_id, str)
            or not unique_id.startswith(prefix)
        ):
            continue
        key = unique_id.removeprefix(prefix)
        if key in by_key:
            by_key[key].append(entry)

    result: dict[str, Any] = {}
    for key, entries in by_key.items():
        if len(entries) > 1:
            raise EntityIdentityMigrationError(
                "QWeather public entity registry is ambiguous"
            )
        if entries:
            result[key] = entries[0]
    return result


def migrate_public_entity_ids(registry: Any, config_entry_id: str) -> tuple[str, ...]:
    """Rename existing public entries without changing their unique identity.

    The caller runs this before platform setup. New entries are then created with
    the same IDs, while existing entries retain their history, device link, and
    config-entry ownership through an entity-registry rename.
    """
    entries = _public_entries(registry, config_entry_id)
    planned: list[tuple[str, str, str]] = []
    for key, target_entity_id in PUBLIC_ENTITY_IDS.items():
        entry = entries.get(key)
        if entry is None:
            continue
        current_entity_id = getattr(entry, "entity_id", None)
        if not isinstance(current_entity_id, str):
            raise EntityIdentityMigrationError("QWeather public entity has no ID")
        expected_domain = target_entity_id.split(".", 1)[0]
        if current_entity_id.split(".", 1)[0] != expected_domain:
            raise EntityIdentityMigrationError(
                "QWeather public entity has the wrong domain"
            )
        registered_target = registry.async_get(target_entity_id)
        if registered_target is not None and registered_target is not entry:
            raise EntityIdentityMigrationError(
                "QWeather public entity ID is already in use"
            )
        if current_entity_id != target_entity_id:
            planned.append((key, current_entity_id, target_entity_id))

    completed: list[tuple[str, str, str]] = []
    try:
        for migration in planned:
            _, current_entity_id, target_entity_id = migration
            registry.async_update_entity(
                current_entity_id, new_entity_id=target_entity_id
            )
            completed.append(migration)
    except Exception as error:
        for _, current_entity_id, target_entity_id in reversed(completed):
            try:
                registry.async_update_entity(
                    target_entity_id, new_entity_id=current_entity_id
                )
            except Exception:
                pass
        raise EntityIdentityMigrationError(
            "QWeather public entity migration did not complete"
        ) from error
    return tuple(key for key, _, _ in planned)

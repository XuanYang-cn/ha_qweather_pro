"""Public entity-identity migration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.qweather_pro.entity_identity import (
    EntityIdentityMigrationError,
    PUBLIC_ENTITY_IDS,
    migrate_public_entity_ids,
)


@dataclass
class _Entry:
    entity_id: str
    unique_id: str
    platform: str = "qweather_pro"
    config_entry_id: str = "synthetic-entry"
    device_id: str | None = "synthetic-device"


class _Entries:
    def __init__(self, entries: list[_Entry]) -> None:
        self._entries = entries

    def get_entries_for_config_entry_id(self, entry_id: str) -> list[_Entry]:
        return [entry for entry in self._entries if entry.config_entry_id == entry_id]


class _Registry:
    def __init__(
        self, entries: list[_Entry], *, fail_on: str | None = None
    ) -> None:
        self._entries = entries
        self.entities = _Entries(entries)
        self.fail_on = fail_on

    def async_get(self, entity_id: str) -> _Entry | None:
        return next((entry for entry in self._entries if entry.entity_id == entity_id), None)

    def async_update_entity(self, entity_id: str, *, new_entity_id: str) -> _Entry:
        if entity_id == self.fail_on:
            raise RuntimeError("synthetic registry write failure")
        entry = self.async_get(entity_id)
        if entry is None:
            raise ValueError("entity disappeared during migration")
        entry.entity_id = new_entity_id
        return entry


def _legacy_entity_id(key: str, canonical: str) -> str:
    domain, _ = canonical.split(".", 1)
    return f"{domain}.legacy_place_{key}"


def _public_entries(*, canonical: bool = False) -> list[_Entry]:
    return [
        _Entry(
            entity_id=entity_id if canonical else _legacy_entity_id(key, entity_id),
            unique_id=f"synthetic-entry_{key}",
        )
        for key, entity_id in PUBLIC_ENTITY_IDS.items()
    ]


def _entity_ids(registry: _Registry) -> dict[str, str]:
    return {entry.unique_id: entry.entity_id for entry in registry._entries}


def test_migrates_one_legacy_public_entity_set_without_changing_identity() -> None:
    registry = _Registry(_public_entries())
    original_device_ids = {entry.unique_id: entry.device_id for entry in registry._entries}

    changed = migrate_public_entity_ids(registry, "synthetic-entry")

    assert changed == tuple(PUBLIC_ENTITY_IDS)
    assert _entity_ids(registry) == {
        f"synthetic-entry_{key}": entity_id
        for key, entity_id in PUBLIC_ENTITY_IDS.items()
    }
    assert len({entry.entity_id for entry in registry._entries}) == len(PUBLIC_ENTITY_IDS)
    assert {entry.unique_id: entry.device_id for entry in registry._entries} == original_device_ids


async def test_migrates_a_real_home_assistant_legacy_registry(hass) -> None:
    """The supported registry API retains one entry per stable unique ID."""
    entry = SimpleNamespace(
        entry_id="synthetic-entry",
        disabled_by=None,
        pref_disable_new_entities=False,
        subentries={},
    )
    hass.config_entries.async_get_entry = lambda entry_id: (
        entry if entry_id == entry.entry_id else None
    )
    dr.async_setup(hass)
    registry = er.async_get(hass)
    await dr.async_load(hass, load_empty=True)
    await registry.async_load(load_empty=True)
    for key, entity_id in PUBLIC_ENTITY_IDS.items():
        domain, _ = entity_id.split(".", 1)
        registry.async_get_or_create(
            domain,
            "qweather_pro",
            f"{entry.entry_id}_{key}",
            config_entry=entry,
            suggested_object_id=f"legacy_place_{key}",
        )

    assert migrate_public_entity_ids(registry, entry.entry_id) == tuple(PUBLIC_ENTITY_IDS)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)

    assert {item.unique_id: item.entity_id for item in entries} == {
        f"{entry.entry_id}_{key}": entity_id
        for key, entity_id in PUBLIC_ENTITY_IDS.items()
    }


def test_migrates_a_partial_registry_without_creating_a_second_set() -> None:
    entries = _public_entries()[:2]
    registry = _Registry(entries)

    changed = migrate_public_entity_ids(registry, "synthetic-entry")

    assert changed == tuple(PUBLIC_ENTITY_IDS)[:2]
    assert _entity_ids(registry) == {
        f"synthetic-entry_{key}": entity_id
        for key, entity_id in list(PUBLIC_ENTITY_IDS.items())[:2]
    }


def test_repeated_migration_is_a_noop_and_remains_readable_by_unique_id() -> None:
    registry = _Registry(_public_entries(canonical=True))

    assert migrate_public_entity_ids(registry, "synthetic-entry") == ()
    assert migrate_public_entity_ids(registry, "synthetic-entry") == ()
    assert _entity_ids(registry) == {
        f"synthetic-entry_{key}": entity_id
        for key, entity_id in PUBLIC_ENTITY_IDS.items()
    }


def test_rejects_a_wrong_domain_without_mutating_the_registry() -> None:
    registry = _Registry(_public_entries())
    registry._entries[0].entity_id = "sensor.wrong_domain"
    original = _entity_ids(registry)

    with pytest.raises(EntityIdentityMigrationError, match="wrong domain"):
        migrate_public_entity_ids(registry, "synthetic-entry")

    assert _entity_ids(registry) == original


def test_rejects_a_canonical_duplicate_without_mutating_the_registry() -> None:
    entries = _public_entries()
    entries.append(
        _Entry(
            entity_id=PUBLIC_ENTITY_IDS["weather"],
            unique_id="other-entry_weather",
            config_entry_id="other-entry",
        )
    )
    registry = _Registry(entries)
    original = _entity_ids(registry)

    with pytest.raises(EntityIdentityMigrationError, match="already in use"):
        migrate_public_entity_ids(registry, "synthetic-entry")

    assert _entity_ids(registry) == original


def test_restores_prior_ids_if_a_registry_write_fails_mid_migration() -> None:
    entries = _public_entries()
    registry = _Registry(entries, fail_on=entries[2].entity_id)
    original = _entity_ids(registry)

    with pytest.raises(EntityIdentityMigrationError, match="did not complete"):
        migrate_public_entity_ids(registry, "synthetic-entry")

    assert _entity_ids(registry) == original

"""First-version config-flow policy tests."""

from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key
from homeassistant.const import CONF_API_KEY, CONF_HOST

import custom_components.qweather_pro.config_flow as config_flow
from custom_components.qweather_pro.config_flow import (
    QWeatherConfigFlow,
    first_version_auth_data,
    first_version_options,
    first_version_reconfigure_data,
    private_key_for_flow,
    private_key_selector,
)
from custom_components.qweather_pro.const import (
    CONF_CUSTOM_UI,
    CONF_DAILYSTEPS,
    CONF_GIRD,
    CONF_HOURLYSTEPS,
    CONF_LOCATION_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USE_TOKEN,
    CONF_WARNING_CITY_ID,
    CONF_WARNING_LOCATION_COORDINATES,
    CONF_WARNING_LOCATION_ID,
    CONF_WARNING_LOCATION_QUERY,
)


def test_first_version_options_disable_grid_and_upstream_ui() -> None:
    options = first_version_options(
        {
            CONF_UPDATE_INTERVAL: 5,
            CONF_DAILYSTEPS: "3",
            CONF_HOURLYSTEPS: "72",
            CONF_GIRD: True,
            CONF_CUSTOM_UI: True,
        }
    )

    assert options == {
        CONF_UPDATE_INTERVAL: 10,
        CONF_DAILYSTEPS: "7",
        CONF_HOURLYSTEPS: "24",
        CONF_GIRD: False,
        CONF_CUSTOM_UI: False,
    }


def test_first_version_configuration_requires_jwt_and_discards_api_keys() -> None:
    data = first_version_auth_data(
        {
            CONF_HOST: "weather-api.example.invalid",
            CONF_LOCATION_ID: "121.45,31.25",
            CONF_API_KEY: "synthetic-api-key",
            CONF_USE_TOKEN: False,
        }
    )

    assert data[CONF_USE_TOKEN] is True
    assert CONF_API_KEY not in data


def test_reconfigure_removes_api_key_inherited_from_an_existing_entry() -> None:
    data = first_version_reconfigure_data(
        {
            CONF_HOST: "old-host.example.invalid",
            CONF_LOCATION_ID: "121.47,31.23",
            CONF_API_KEY: "legacy-api-key",
            CONF_USE_TOKEN: False,
        },
        {
            CONF_HOST: "new-host.example.invalid",
            CONF_LOCATION_ID: "121.45,31.25",
        },
    )

    assert data[CONF_HOST] == "new-host.example.invalid"
    assert data[CONF_LOCATION_ID] == "121.45,31.25"
    assert data[CONF_USE_TOKEN] is True
    assert CONF_API_KEY not in data


def test_private_key_for_flow_uses_only_a_valid_provisioned_ed25519_pem() -> None:
    generated = "generated-private-key"
    provisioned = (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("utf-8")
    )

    assert private_key_for_flow(generated, {}) == generated
    assert (
        private_key_for_flow(generated, {"private_key": provisioned})
        == provisioned.strip()
    )
    with pytest.raises(ValueError, match="invalid"):
        private_key_for_flow(
            generated,
            {
                "private_key": "-----BEGIN PRIVATE KEY-----\ninvalid\n-----END PRIVATE KEY-----"
            },
        )
    rsa_private_key = (
        generate_private_key(public_exponent=65537, key_size=2048)
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("utf-8")
    )
    with pytest.raises(ValueError, match="not Ed25519"):
        private_key_for_flow(generated, {"private_key": rsa_private_key})


def test_private_key_selector_accepts_multiline_pem_input() -> None:
    selector_config = private_key_selector().config

    assert selector_config["multiline"] is True
    assert selector_config["type"] == "password"


class FakeWarningLocationLookup:
    """Return controlled search and parent-city responses for a reconfigure flow."""

    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.queries: list[str] = []

    async def city_lookup(self, query: str, lang: str) -> dict:
        self.queries.append(query)
        assert lang == "zh"
        return self.responses.pop(0)


def _reconfigure_flow(hass, entry) -> QWeatherConfigFlow:
    flow = QWeatherConfigFlow()
    flow.hass = hass
    flow.handler = "qweather_pro"
    flow.flow_id = "synthetic-reconfigure-flow"
    flow.context = {"source": "reconfigure", "entry_id": "synthetic-entry"}
    flow._get_reconfigure_entry = lambda: entry
    return flow


async def test_reconfigure_searches_a_district_then_saves_only_warning_jurisdiction(
    hass,
    monkeypatch,
) -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.004",
        "lat": "30.004",
    }
    city = {
        "id": "synthetic-city",
        "name": "Synthetic City",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }
    lookup = FakeWarningLocationLookup(
        [
            {"code": "200", "location": [city, district]},
            {"code": "200", "location": [city]},
            {"code": "200", "location": [district]},
        ]
    )
    entry = SimpleNamespace(data={CONF_LOCATION_ID: "120.55,30.55"})
    flow = _reconfigure_flow(hass, entry)
    captured: dict[str, object] = {}

    def capture_update(updated_entry, *, data):
        captured["entry"] = updated_entry
        captured["data"] = data
        return {"type": "abort", "reason": "reconfigure_successful"}

    monkeypatch.setattr(config_flow, "create_qweather_client", lambda *_args: lookup)
    monkeypatch.setattr(flow, "async_update_reload_and_abort", capture_update)

    form = await flow.async_step_reconfigure(
        {CONF_WARNING_LOCATION_QUERY: "Synthetic District"}
    )

    assert form["step_id"] == "select_warning_location"
    assert flow._warning_location_candidates == [district]
    assert flow._warning_location_label(district) == (
        "Synthetic District · Synthetic City · Synthetic Country"
    )

    result = await flow.async_step_select_warning_location(
        {"location_index": "synthetic-district"}
    )

    assert result == {"type": "abort", "reason": "reconfigure_successful"}
    assert captured["entry"] is entry
    assert lookup.queries == [
        "Synthetic District",
        "Synthetic City",
        "120.00,30.00",
    ]
    data = captured["data"]
    assert data[CONF_LOCATION_ID] == "120.55,30.55"
    assert data[CONF_WARNING_LOCATION_ID] == "synthetic-district"
    assert data[CONF_WARNING_CITY_ID] == "synthetic-city"
    assert data[CONF_WARNING_LOCATION_COORDINATES] == "120.00,30.00"


async def test_reconfigure_rejects_an_ambiguous_parent_city(hass, monkeypatch) -> None:
    district = {
        "id": "synthetic-district",
        "name": "Synthetic District",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }
    city = {
        "id": "synthetic-city",
        "name": "Synthetic City",
        "adm1": "Synthetic Province",
        "adm2": "Synthetic City",
        "country": "Synthetic Country",
        "lon": "120.00",
        "lat": "30.00",
    }
    lookup = FakeWarningLocationLookup(
        [
            {"code": "200", "location": [district]},
            {"code": "200", "location": [city, city]},
        ]
    )
    flow = _reconfigure_flow(hass, SimpleNamespace(data={CONF_LOCATION_ID: "120.55,30.55"}))
    monkeypatch.setattr(config_flow, "create_qweather_client", lambda *_args: lookup)

    await flow.async_step_reconfigure({CONF_WARNING_LOCATION_QUERY: "Synthetic District"})
    result = await flow.async_step_select_warning_location(
        {"location_index": "synthetic-district"}
    )

    assert result["reason"] == "warning_location_not_found"


async def test_reconfigure_keeps_the_existing_weather_connection_path(
    hass,
    monkeypatch,
) -> None:
    entry = SimpleNamespace(
        data={
            CONF_HOST: "old-host.example.invalid",
            CONF_LOCATION_ID: "120.00,30.00",
            CONF_API_KEY: "legacy-key",
        }
    )
    flow = _reconfigure_flow(hass, entry)
    captured: dict[str, object] = {}

    async def capture_jwt_setup():
        captured["data"] = flow._temp_data
        return {"type": "form", "step_id": "jwt_setup"}

    monkeypatch.setattr(flow, "async_step_jwt_setup", capture_jwt_setup)

    form = await flow.async_step_reconfigure(
        {"reconfigure_target": "weather_connection"}
    )
    assert form["step_id"] == "reconfigure_connection"

    result = await flow.async_step_reconfigure_connection(
        {
            CONF_HOST: "new-host.example.invalid",
            CONF_LOCATION_ID: "120.50,30.50",
        }
    )

    assert result == {"type": "form", "step_id": "jwt_setup"}
    assert captured["data"] == {
        CONF_HOST: "new-host.example.invalid",
        CONF_LOCATION_ID: "120.50,30.50",
        CONF_USE_TOKEN: True,
    }

"""First-version config-flow policy tests."""

from homeassistant.const import CONF_API_KEY, CONF_HOST

from custom_components.qweather_pro.config_flow import (
    first_version_auth_data,
    first_version_options,
    first_version_reconfigure_data,
)
from custom_components.qweather_pro.const import (
    CONF_CUSTOM_UI,
    CONF_DAILYSTEPS,
    CONF_GIRD,
    CONF_HOURLYSTEPS,
    CONF_LOCATION_ID,
    CONF_UPDATE_INTERVAL,
    CONF_USE_TOKEN,
)


def test_first_version_options_disable_grid_and_upstream_ui() -> None:
    options = first_version_options(
        {
            CONF_UPDATE_INTERVAL: 10,
            CONF_DAILYSTEPS: "7",
            CONF_HOURLYSTEPS: "24",
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

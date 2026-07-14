"""First-version config-flow policy tests."""

from custom_components.qweather_pro.config_flow import first_version_options
from custom_components.qweather_pro.const import (
    CONF_CUSTOM_UI,
    CONF_DAILYSTEPS,
    CONF_GIRD,
    CONF_HOURLYSTEPS,
    CONF_UPDATE_INTERVAL,
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

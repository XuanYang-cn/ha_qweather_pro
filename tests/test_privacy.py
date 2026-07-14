"""Credential and private-host logging tests."""

import logging
from types import SimpleNamespace

import pytest

from homeassistant.const import CONF_HOST

from custom_components.qweather_pro.api import QWeatherAPI, _log_retry_exhaustion
from custom_components.qweather_pro.clients import (
    JWTConfigurationError,
    create_qweather_client,
)
from custom_components.qweather_pro.const import CONF_USE_TOKEN


class FakeErrorResponse:
    status = 403

    async def json(self) -> dict:
        return {"error": {"title": "Synthetic denial"}}


class FakeSession:
    async def get(self, *_args, **_kwargs) -> FakeErrorResponse:
        return FakeErrorResponse()


async def test_personal_api_host_is_not_written_to_logs(caplog, monkeypatch) -> None:
    private_host = "account-specific-host.example.invalid"
    client = QWeatherAPI(
        session=FakeSession(),
        host=private_host,
    )
    monkeypatch.setattr(client, "_generate_jwt", lambda: "synthetic.jwt")

    with caplog.at_level(logging.ERROR):
        response = await client.request("v7", "weather/now", {})

    assert response["code"] == "403"
    assert private_host not in caplog.text


def test_legacy_api_key_configuration_is_refused_before_client_creation() -> None:
    with pytest.raises(JWTConfigurationError, match="JWT/Ed25519"):
        create_qweather_client(
            None,
            {
                CONF_HOST: "account-specific-host.example.invalid",
                CONF_USE_TOKEN: False,
            },
        )


def test_retry_exhaustion_does_not_log_exception_details(caplog) -> None:
    private_host = "account-specific-host.example.invalid"
    retry_state = SimpleNamespace(
        attempt_number=3,
        outcome=SimpleNamespace(
            exception=lambda: RuntimeError(f"Cannot connect to {private_host}")
        ),
    )

    with caplog.at_level(logging.ERROR):
        _log_retry_exhaustion(retry_state)

    assert private_host not in caplog.text
    assert "RuntimeError" in caplog.text

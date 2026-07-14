"""Shared Home Assistant test fixtures."""

from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest_asyncio

from homeassistant.core import HomeAssistant


@pytest_asyncio.fixture
async def hass() -> Generator[HomeAssistant]:
    """Create a real Home Assistant core object without starting live services."""
    repository_root = Path(__file__).resolve().parents[1]
    instance = HomeAssistant(str(repository_root))
    instance.config.language = "zh-Hans"
    instance.config_entries = SimpleNamespace(
        async_forward_entry_setups=AsyncMock(),
        async_reload=AsyncMock(),
        async_unload_platforms=AsyncMock(return_value=True),
    )
    yield instance
    instance.import_executor.shutdown(wait=True)

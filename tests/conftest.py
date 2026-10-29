"""Home Assistant fixtures for this custom integration."""

import pytest


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations):
    """Allow the integration loader to discover this repository."""

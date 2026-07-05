import pytest

from argus.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Clear the settings cache around each test so monkeypatched env vars take effect
    and never leak between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()

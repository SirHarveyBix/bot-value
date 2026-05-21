import pytest
from freezegun import freeze_time


@pytest.fixture(scope="session")
def vcr_config():
    return {
        "record_mode": "none",
        "cassette_library_dir": "tests/cassettes",
    }


@pytest.fixture
def frozen_wednesday():
    """Mercredi 2025-01-15 15:00 UTC = 10h00 ET (heure de marché NYSE)."""
    with freeze_time("2025-01-15 15:00:00"):
        yield

import sys

import pytest
from freezegun import freeze_time
from loguru import logger


@pytest.fixture(autouse=True, scope="session")
def isolate_test_logs(tmp_path_factory):
    """Redirige loguru vers /tmp pendant les tests — évite de polluer data/logs/ production."""
    logger.remove()
    tmp = tmp_path_factory.mktemp("logs")
    logger.add(str(tmp / "test.log"), level="DEBUG")
    logger.add(sys.stderr, level="WARNING", format="{level} | {name}:{function}:{line} - {message}")
    yield


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

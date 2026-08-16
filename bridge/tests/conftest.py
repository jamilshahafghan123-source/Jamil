from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Configure before app import: Settings is read once and cached.
os.environ.update(
    {
        "API_KEYS": "test-key-one,test-key-two",
        "ALLOW_INSECURE_HTTP": "true",
        "ALLOW_LIVE_TRADING": "false",
        "MAX_VOLUME": "2.0",
        "MT5_CONNECT_ON_STARTUP": "true",
        "SSL_CERTFILE": "",
        "SSL_KEYFILE": "",
        "DEFAULT_MAGIC": "999001",
    }
)

import tests.fake_mt5 as fake_mt5  # noqa: E402

sys.modules["MetaTrader5"] = fake_mt5

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

API_KEY = "test-key-one"
AUTH = {"X-API-Key": API_KEY}


@pytest.fixture(autouse=True)
def _clean_state():
    fake_mt5.reset()
    get_settings.cache_clear()
    yield
    fake_mt5.reset()


@pytest.fixture
def mt5():
    return fake_mt5


@pytest.fixture
def client():
    with TestClient(create_app(get_settings())) as test_client:
        yield test_client

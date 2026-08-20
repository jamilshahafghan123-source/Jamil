"""Test bootstrap.

Sets throwaway values for the required settings so `pytest` runs with no
environment setup. These never reach a real database or broker — the tests
here are pure-function tests of the risk engine, indicators, and validation.
"""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-secret-value-at-least-32-characters")
os.environ.setdefault("MT5_BRIDGE_TOKEN", "test-bridge-token")
os.environ.setdefault("ENV", "dev")


import pytest


@pytest.fixture(autouse=True)
def _reset_maintenance():
    """Keep maintenance mode from leaking between tests.

    A failed restore deliberately *stays* in maintenance — section 4 forbids
    resuming execution against a database nobody has verified. That is the
    right behaviour and the wrong thing to carry into the next test, since
    module state is process-wide.
    """
    from app.services import maintenance

    maintenance.reset()
    yield
    maintenance.reset()

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

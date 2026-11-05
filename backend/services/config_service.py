"""
Configuration Service for Environment & Test/Demo Mode Management.
Enforces strict separation between Development/Test Mode and Production Mode.
"""

import os

# Default to test/demo mode in development, or configured via TEST_MODE / APP_ENV
_TEST_MODE_ENV = os.getenv("TEST_MODE", "").strip()
_APP_ENV = os.getenv("APP_ENV", "development").lower()

# Deliberately strict: only the exact value 1 enables demo shortcuts (master OTP,
# dev auto-login, synthetic photo/location captures). Anything else is production.
_IS_TEST_MODE = _TEST_MODE_ENV == '1'


def is_test_mode() -> bool:
    """Return True if TEST / DEMO mode is enabled for development/testing."""
    return _IS_TEST_MODE


def set_test_mode(enabled: bool) -> None:
    """Explicitly set test mode state for unit testing or configuration."""
    global _IS_TEST_MODE
    _IS_TEST_MODE = enabled


def get_app_environment() -> str:
    """Return current environment descriptor ('production' or 'development')."""
    return "production" if not _IS_TEST_MODE else "development"

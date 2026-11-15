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


def get_secure_uploads_root() -> str:
    """Return the absolute path for persistent secure uploads.
    Respects SECURE_UPLOADS_DIR, DATA_DIR, or the parent directory of FIR_DB_PATH if configured.
    Falls back to project's data/secure_uploads.
    """
    if os.environ.get('SECURE_UPLOADS_DIR'):
        path = os.path.abspath(os.environ['SECURE_UPLOADS_DIR'])
    elif os.environ.get('DATA_DIR'):
        path = os.path.abspath(os.path.join(os.environ['DATA_DIR'], 'secure_uploads'))
    elif os.environ.get('FIR_DB_PATH'):
        db_dir = os.path.dirname(os.path.abspath(os.environ['FIR_DB_PATH']))
        path = os.path.abspath(os.path.join(db_dir, 'secure_uploads'))
    else:
        path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads'))
    os.makedirs(path, exist_ok=True)
    return path


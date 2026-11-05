"""
Police officer account provisioning.

A deployed instance starts from an empty SQLite ledger, so staff accounts have to
be created during boot rather than inserted by hand into one machine's database
file. The usernames and password come from the environment and the existing
PBKDF2 hashing path stores them, which keeps every credential out of source
control.

    SEED_OFFICER_USERNAMES=person1,person2,person3
    SEED_OFFICER_PASSWORD=<shared password for the seeded accounts>

Without SEED_OFFICER_PASSWORD nothing is created: there is no default, guessed or
hard-coded fallback password.
"""

import os
from typing import Dict, List

from backend.services.auth_service import register_user
from backend.services.db import get_db_connection

DEFAULT_EMAIL_DOMAIN = 'eksp.gov.in'


def _requested_usernames() -> List[str]:
    """Read the operator-supplied officer usernames, de-duplicated and lower-cased."""
    raw = os.environ.get('SEED_OFFICER_USERNAMES', '')
    usernames: List[str] = []
    for part in raw.split(','):
        clean = part.strip().lower()
        if clean and clean not in usernames:
            usernames.append(clean)
    return usernames


def _email_for(username: str) -> str:
    domain = (os.environ.get('SEED_OFFICER_EMAIL_DOMAIN') or DEFAULT_EMAIL_DOMAIN).strip().lstrip('@')
    return f"{username}@{domain.lower()}"


def _account_exists(username: str, email: str) -> bool:
    """Report whether this officer is already provisioned, by email or badge number."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT 1 FROM users WHERE LOWER(email) = ? OR LOWER(COALESCE(badge_number, '')) = ? LIMIT 1",
            (email, username)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


def ensure_seed_officer_accounts() -> Dict[str, List[str]]:
    """
    Create the officer accounts named by SEED_OFFICER_USERNAMES.

    Idempotent: an account that already exists is left exactly as it is, so
    re-running the seed on every boot never duplicates or overwrites an officer.
    Returns the usernames grouped as created / existing / skipped.
    """
    outcome: Dict[str, List[str]] = {'created': [], 'existing': [], 'skipped': []}
    usernames = _requested_usernames()
    password = os.environ.get('SEED_OFFICER_PASSWORD') or ''

    if not usernames:
        return outcome
    if not password:
        outcome['skipped'] = usernames
        return outcome

    for username in usernames:
        email = _email_for(username)
        if _account_exists(username, email):
            outcome['existing'].append(username)
            continue

        register_user(
            name=f"Officer {username[0].upper()}{username[1:]}",
            email=email,
            # users.phone is NOT NULL and seeded staff accounts hold no mobile
            # number, so the address of record is mirrored into it.
            phone=email,
            password=password,
            role='OFFICER',
            badge_number=username,
            rank='Police Officer',
            status='ACTIVE',
        )
        outcome['created'].append(username)

    return outcome

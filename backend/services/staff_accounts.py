"""
Staff sign-in provisioning: the Verification Desk, the Police workspace and the
Main Authorized Officer console.

A deployed instance starts from an empty SQLite ledger, so staff accounts have to
be created during boot rather than inserted by hand into one machine's database
file. Usernames and the password come from the environment and are hashed by the
existing PBKDF2 path, which keeps every credential out of source control.

    SEED_VERIFICATION_OFFICER_USERNAMES=Person 1
    SEED_POLICE_OFFICER_USERNAMES=Person 1
    SEED_MAIN_AUTHORIZED_OFFICER_USERNAMES=Person 1
    SEED_OFFICER_PASSWORD=<shared password for the seeded accounts>

The same username is intentionally reusable across portals because every staff
login authenticates with its role attached; one row per role, never one row with
several roles. Each row gets its own email, badge number and password salt.

Without SEED_OFFICER_PASSWORD nothing is created: there is no default, guessed or
hard-coded fallback password.
"""

import os
import re
from typing import Dict, List, Tuple

from backend.services.auth_service import register_user
from backend.services.db import get_db_connection

DEFAULT_EMAIL_DOMAIN = 'eksp.gov.in'

# portal key, the role its login page authenticates against, display rank, env var.
# The Main Authorized Officer console signs in through the ADMIN login page; the
# integrity portal at /authorized-officer/* authorises the same role, because
# users.role has no separate AUTHORIZED_OFFICER value.
PORTALS: Tuple[Tuple[str, str, str, str], ...] = (
    ('verification', 'VERIFICATION_OFFICER', 'Verification Officer',
     'SEED_VERIFICATION_OFFICER_USERNAMES'),
    ('police', 'OFFICER', 'Police Officer', 'SEED_POLICE_OFFICER_USERNAMES'),
    ('main-officer', 'ADMIN', 'Main Authorized Officer',
     'SEED_MAIN_AUTHORIZED_OFFICER_USERNAMES'),
)

# The variable that provisioned plain police officers before the portals were
# standardised; still honoured so an existing deployment keeps working.
LEGACY_OFFICER_ENV = 'SEED_OFFICER_USERNAMES'


def _slug(username: str) -> str:
    """Turn any username into the lower-case identifier used for emails and badges."""
    return re.sub(r'[^a-z0-9]+', '-', username.lower()).strip('-')


def _identifiers_from_env(env_var: str) -> List[str]:
    """Read a comma-separated username list, preserving the operator's capitalisation."""
    raw = os.environ.get(env_var, '')
    usernames: List[str] = []
    for part in raw.split(','):
        clean = part.strip().strip('\'"')
        if clean and clean.lower() not in [existing.lower() for existing in usernames]:
            usernames.append(clean)
    return usernames


def _email_for(username: str, portal: str) -> str:
    domain = (os.environ.get('SEED_OFFICER_EMAIL_DOMAIN') or DEFAULT_EMAIL_DOMAIN).strip().lstrip('@')
    return f"{_slug(username)}-{portal}@{domain.lower()}"


def _resolve_existing(cursor, username: str, email: str, role: str):
    """
    Find the account this username already resolves to for this role.

    Matches the same columns the login lookup uses, so a re-run recognises an
    account provisioned earlier — including one whose email follows a previous
    naming scheme — and leaves it alone instead of duplicating it. A row that only
    blocks the email is reported too, since users.email is UNIQUE.
    """
    clean = username.strip().lower()
    cursor.execute(
        """
        SELECT id, email FROM users
        WHERE role = ?
          AND (LOWER(email) = ? OR LOWER(phone) = ? OR LOWER(name) = ?
               OR LOWER(COALESCE(badge_number, '')) = ?)
        ORDER BY created_at
        LIMIT 1
        """,
        (role, email, clean, clean, clean)
    )
    row = cursor.fetchone()
    if row:
        return dict(row)

    cursor.execute("SELECT id, email, role FROM users WHERE LOWER(email) = ?", (email,))
    clash = cursor.fetchone()
    return dict(clash) if clash else None


def ensure_seed_staff_accounts() -> Dict[str, List[str]]:
    """
    Create the staff accounts named by the portal environment variables.

    Idempotent and additive: an account that already resolves for that role keeps
    its row, its id and its password hash untouched, so re-running the seed on
    every boot never duplicates or overwrites a staff member. Usernames are
    labelled 'ROLE:username' and grouped as created / existing / skipped.
    """
    outcome: Dict[str, List[str]] = {'created': [], 'existing': [], 'skipped': []}
    password = os.environ.get('SEED_OFFICER_PASSWORD') or ''

    requests: List[Tuple[str, str, str, str]] = []
    for portal, role, title, env_var in PORTALS:
        for username in _identifiers_from_env(env_var):
            requests.append((username, role, portal, title))
    for username in _identifiers_from_env(LEGACY_OFFICER_ENV):
        requests.append((username, 'OFFICER', 'police', 'Police Officer'))

    if not requests:
        return outcome
    if not password:
        outcome['skipped'] = [f"{role}:{username}" for username, role, _p, _t in requests]
        return outcome

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        for username, role, portal, title in requests:
            label = f"{role}:{username}"
            email = _email_for(username, portal)
            if _resolve_existing(cursor, username, email, role):
                outcome['existing'].append(label)
                continue

            register_user(
                name=username,
                email=email,
                # users.phone is NOT NULL and seeded staff accounts hold no mobile
                # number, so the address of record is mirrored into it.
                phone=email,
                password=password,
                role=role,
                badge_number=f"{_slug(username)}-{portal}",
                rank=title,
                status='ACTIVE',
            )
            outcome['created'].append(label)
    finally:
        conn.close()

    return outcome

"""
Authentication and Role-Based Access Control (RBAC) Service.
Enforces:
- Password hashing and verification
- User registration and login
- Active user session state
- Role and resource-level authorization
- Strict audit visibility rules (Citizen = Notification only, Unauthorized Officer = 403 Forbidden, Authorized Officer = Full Audit)
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.config_service import is_test_mode
from backend.services.crypto_service import hash_password, verify_password
from backend.services.db import get_db_connection

# In-memory session tracking for active user context
_active_sessions: Dict[str, Dict[str, Any]] = {}
_current_user_context: Optional[Dict[str, Any]] = None


def register_user(
    name: str,
    email: str,
    phone: str,
    password: str,
    role: str = "CITIZEN",
    badge_number: Optional[str] = None,
    station: Optional[str] = None,
    rank: Optional[str] = None,
    district: Optional[str] = None,
    address: Optional[str] = None,
    gov_id: Optional[str] = None,
    status: str = "ACTIVE"
) -> Dict[str, Any]:
    """Register a new user in the system with secure PBKDF2 password hashing."""
    conn = get_db_connection()
    cursor = conn.cursor()

    email_clean = email.strip().lower()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email_clean,))
    if cursor.fetchone():
        conn.close()
        raise ValueError(f"User with email '{email_clean}' already exists.")

    password_hash, salt = hash_password(password)
    user_id = f"usr-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    gov_id_masked = None
    if gov_id:
        clean_id = gov_id.strip()
        if len(clean_id) >= 4:
            gov_id_masked = f"XXXX-XXXX-{clean_id[-4:]}"
        else:
            gov_id_masked = "XXXX-XXXX-XXXX"

    cursor.execute("""
        INSERT INTO users (
            id, name, email, phone, password_hash, salt, role, status,
            badge_number, station, rank, district, address, gov_id_masked,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, name.strip(), email_clean, phone.strip(), password_hash, salt,
        role.upper(), status.upper(), badge_number, station, rank, district, address,
        gov_id_masked, now, now
    ))

    conn.commit()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(cursor.fetchone())
    conn.close()

    user.pop("password_hash", None)
    user.pop("salt", None)
    return user


def get_citizen_access_issue(user: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return the reason a citizen must not enter the protected portal, if any.

    Access requires the account itself to be ACTIVE *and*, when a registration
    application exists, that application to be APPROVED. Staff roles are not
    affected by this check.
    """
    if not user or user.get("role") != "CITIZEN":
        return None

    # Lazy import avoids a circular dependency at module load time.
    from backend.services.citizen_registration_service import get_application_by_citizen

    application = get_application_by_citizen(user.get("id"))
    if application and (application.get("status") or "").upper() != "APPROVED":
        app_status = (application.get("status") or "").upper()
        if app_status == "ADDITIONAL_INFO_REQUIRED":
            return "Additional information is required before your account can be approved."
        if app_status == "REJECTED":
            return "Your citizen registration was rejected. Contact the Verification Desk for assistance."
        return "Your citizen registration is still under verification."

    status = (user.get("status") or "ACTIVE").upper()
    if status == "SUSPENDED":
        return "This citizen account is suspended. Contact the Verification Desk for assistance."
    if status != "ACTIVE":
        return "Your citizen registration is awaiting Verification Officer approval."
    return None


def assert_active_citizen(user: Optional[Dict[str, Any]]) -> None:
    """Raise PermissionError unless the citizen is fully verified and approved."""
    if not user or user.get("role") != "CITIZEN":
        raise PermissionError("An approved citizen account is required for this action.")
    issue = get_citizen_access_issue(user)
    if issue:
        raise PermissionError(issue)


def get_dev_auto_login_user() -> Optional[Dict[str, Any]]:
    """Return the configured demo citizen only when TEST_MODE=1.

    Development convenience for the citizen portal. Any other TEST_MODE value
    (including unset) returns None, so credential checks and the verification
    gate stay fully enforced in production.
    """
    if not is_test_mode():
        return None

    identifier = (os.getenv("DEV_AUTO_LOGIN_USER") or "Person 1").strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM users
        WHERE role = 'CITIZEN' AND status = 'ACTIVE'
          AND (LOWER(name) = ? OR LOWER(email) = ? OR LOWER(phone) = ?)
        ORDER BY created_at ASC
        LIMIT 1
    """, (identifier, identifier, identifier))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    user = dict(row)
    if get_citizen_access_issue(user):
        return None
    user.pop("password_hash", None)
    user.pop("salt", None)
    return user


def _credentials_match(
    identifier: str, password: str, required_role: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Load a user and verify their password, without mutating session state.

    Identifiers are case-insensitive and may be the account username (display
    name), email address, phone number, or staff badge number. An optional role
    narrows the lookup so identical display names across roles cannot collide.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    clean = (identifier or "").strip().lower()
    query = """
        SELECT * FROM users
        WHERE LOWER(email) = ? OR LOWER(phone) = ? OR LOWER(name) = ?
           OR LOWER(COALESCE(badge_number, '')) = ?
    """
    params: List[Any] = [clean, clean, clean, clean]
    if required_role:
        query += " AND role = ?"
        params.append(required_role.upper())
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    user = dict(row)
    if not verify_password(password, user.get("password_hash", ""), user.get("salt", "")):
        return None
    return user


def citizen_login_denial_reason(identifier: str, password: str) -> Optional[str]:
    """Explain why a *valid* citizen credential pair is refused, if it is.

    Returns None when the credentials are invalid or the account may log in.
    Checking the password first prevents account enumeration by unauthenticated
    callers.
    """
    user = _credentials_match(identifier, password, required_role="CITIZEN")
    if not user:
        return None
    return get_citizen_access_issue(user)


def authenticate_user(email_or_phone_or_badge: str, password: str, required_role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Authenticate user credentials against PBKDF2 hash.

    Citizen accounts are only issued a session after Verification Officer
    approval; unverified, additional-info, and rejected accounts are refused.
    """
    user = _credentials_match(email_or_phone_or_badge, password, required_role=required_role)
    if not user:
        return None

    if user.get("status") == "SUSPENDED":
        return None

    if required_role and user.get("role") != required_role.upper():
        return None

    if get_citizen_access_issue(user):
        return None

    user.pop("password_hash", None)
    user.pop("salt", None)
    return user


def _session_storage():
    """Return the per-browser NiceGUI storage, or None outside a UI request context."""
    try:
        from nicegui import app
        return app.storage.user
    except Exception:
        return None


def set_current_user(user: Optional[Dict[str, Any]]) -> None:
    """Set the active user context for the current browser session."""
    global _current_user_context
    _current_user_context = user
    storage = _session_storage()
    if storage is not None:
        storage['current_user'] = user


def get_current_user() -> Optional[Dict[str, Any]]:
    """Retrieve the active user for the current browser session.

    When called inside a UI request the per-session storage is authoritative, so
    two browsers signed in as different roles never share a login. Outside a UI
    request (unit tests, scripts) the in-memory context is used instead.
    """
    global _current_user_context
    storage = _session_storage()
    if storage is not None:
        return storage.get('current_user')
    return _current_user_context


def get_session_user_strict() -> Optional[Dict[str, Any]]:
    """Session-only user lookup for protected media endpoints (never uses global fallback)."""
    storage = _session_storage()
    if storage is None:
        return None
    return storage.get('current_user')


def delete_unverified_citizen(user_id: str) -> None:
    """Remove a freshly created citizen if their verification application could not be saved."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM users WHERE id = ? AND role = 'CITIZEN' AND status = 'PENDING_VERIFICATION'",
        (user_id,)
    )
    conn.commit()
    conn.close()


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve user dictionary by ID without password credentials."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        u = dict(row)
        u.pop("password_hash", None)
        u.pop("salt", None)
        return u
    return None


def get_all_officers() -> List[Dict[str, Any]]:
    """Retrieve list of all active police officers."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, name, email, phone, badge_number, rank, station, district, status, role "
        "FROM users WHERE role = 'OFFICER' AND status = 'ACTIVE' ORDER BY name"
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def update_staff_profile(user_id: str, **fields: Any) -> Dict[str, Any]:
    """Update permitted staff contact fields without exposing authentication data."""
    allowed = {'phone', 'station', 'address', 'district'}
    updates = {
        key: str(value).strip()
        for key, value in fields.items()
        if key in allowed and value is not None
    }
    if not updates:
        raise ValueError('No permitted profile fields were provided.')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    if not row or row['role'] not in ('VERIFICATION_OFFICER', 'ADMIN', 'OFFICER'):
        conn.close()
        raise PermissionError('This profile cannot be updated through the staff portal.')

    now = datetime.now(timezone.utc).isoformat()
    assignments = ', '.join(f"{key} = ?" for key in updates)
    cursor.execute(
        f"UPDATE users SET {assignments}, updated_at = ? WHERE id = ?",
        tuple(updates.values()) + (now, user_id),
    )
    conn.commit()
    conn.close()
    return get_user_by_id(user_id) or {}


def get_all_citizens() -> List[Dict[str, Any]]:
    """Retrieve list of all citizens."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, phone, district, address, status, gov_id_masked, created_at FROM users WHERE role = 'CITIZEN'")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ==========================================
# RESOURCE-LEVEL AUTHORIZATION ENFORCERS
# ==========================================
def can_user_access_fir(user: Dict[str, Any], fir: Dict[str, Any]) -> bool:
    """
    Check if a user is authorized to view basic FIR case info:
    - CITIZEN: Only if citizen_id matches user.id
    - OFFICER: If assigned to FIR or in the department
    - ADMIN: All FIRs
    """
    if not user or not fir:
        return False

    role = user.get("role")
    user_id = user.get("id")

    if role in ("ADMIN", "VERIFICATION_OFFICER"):
        return True
    elif role == "OFFICER":
        return can_user_access_fir_audit(user, fir)
    elif role == "CITIZEN":
        return (fir.get("citizen_id") == user_id) or (fir.get("citizenId") == user_id)
    
    return False


def can_user_access_fir_audit(user: Dict[str, Any], fir: Dict[str, Any]) -> bool:
    """
    Strict Authorization Rule for Detailed FIR Change Audit Trail:
    - CITIZEN: CANNOT access detailed audit (Notification Only). Returns False.
    - UNAUTHORIZED OFFICER: If not assigned to this FIR and not supervisor, Returns False.
    - AUTHORIZED OFFICER: Assigned officer (assigned_officer_id == user.id) or station lead, Returns True.
    - VERIFICATION OFFICER / ADMIN: Authorized supervisor or verification officer, Returns True.
    """
    if not user or not fir:
        return False

    role = user.get("role")
    user_id = user.get("id")

    if role == "CITIZEN":
        # Citizens MUST NOT see detailed audit, old vs new, or officer diffs
        return False

    if role in ("ADMIN", "VERIFICATION_OFFICER"):
        return True

    if role == "OFFICER":
        # Check if officer is explicitly assigned to this FIR
        assigned_id = fir.get("assigned_officer_id") or fir.get("assignedOfficerId")
        if assigned_id and assigned_id == user_id:
            return True
        
        # Or if officer is station in-charge of that police station
        if fir.get("police_station") == user.get("station") and user.get("rank") in ("Police Inspector", "Circle Inspector", "Station House Officer (SHO)"):
            return True

        return False

    return False


def can_user_modify_fir(user: Dict[str, Any], fir: Dict[str, Any]) -> bool:
    """
    Check if a user is authorized to modify an FIR:
    - CITIZEN: CANNOT modify once submitted.
    - UNAUTHORIZED OFFICER: CANNOT modify unassigned FIR.
    - AUTHORIZED OFFICER: Only if assigned officer or station lead.
    - VERIFICATION OFFICER / ADMIN: Can update, format, verify, or assign.
    """
    if not user or not fir:
        return False

    role = user.get("role")
    if role in ("ADMIN", "VERIFICATION_OFFICER"):
        return True
    if role == "OFFICER":
        return can_user_access_fir_audit(user, fir)
    
    return False

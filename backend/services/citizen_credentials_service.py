"""
Citizen Credential Issuance, Activation and Notification Delivery.

Runs when a Verification Officer approves a registration application:

- mints one unique login handle per approved citizen
- records the verification outcome on the account
- issues a single-use, expiring activation token (only its SHA-256 hash is stored)
- delivers the credentials over a real provider when one is configured and
  records exactly what that provider answered
- lets the citizen set their own permanent password through the activation link
- supports password reset and re-delivery without ever storing or echoing a
  plaintext password

Delivery reporting follows the same rule as the registration OTP: a channel is
only marked SENT when the provider accepts it. When nothing is configured the
record says NOT_CONFIGURED, and the UI says so too.
"""

import hashlib
import json
import os
import re
import smtplib
import secrets
import sqlite3
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple

from backend.services.db import get_db_connection
from backend.services.realtime_events import publish

ACTIVATION = 'ACCOUNT_ACTIVATION'
PASSWORD_RESET = 'PASSWORD_RESET'

MIN_PASSWORD_LENGTH = 8
USERNAME_ATTEMPTS = 12

SENT = 'SENT'
FAILED = 'FAILED'
NOT_CONFIGURED = 'NOT_CONFIGURED'


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse_iso(value: str) -> datetime:
    moment = datetime.fromisoformat(value)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _env(name: str, default: str = '') -> str:
    return (os.getenv(name) or default).strip()


def token_ttl_hours() -> int:
    try:
        return max(1, int(_env('ACTIVATION_LINK_TTL_HOURS', '72')))
    except ValueError:
        return 72


def max_token_attempts() -> int:
    try:
        return max(1, int(_env('ACTIVATION_MAX_ATTEMPTS', '5')))
    except ValueError:
        return 5


def portal_base_url() -> str:
    """Public origin used to build activation links, so links work off-box."""
    return (_env('PUBLIC_BASE_URL') or 'http://localhost:8081').rstrip('/')


def hash_token(raw_token: str) -> str:
    """Activation tokens are high-entropy one-time values, so a plain digest is
    enough to verify them without keeping anything that unlocks an account."""
    return hashlib.sha256((raw_token or '').encode('utf-8')).hexdigest()


# ==========================================
# 1. USERNAME ISSUE
# ==========================================

def _slug(text: str, fallback: str = 'citizen') -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    return slug[:24] or fallback


def _handle_taken(cursor, candidate: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM users WHERE LOWER(username) = ? LIMIT 1", (candidate.lower(),)
    )
    if cursor.fetchone():
        return True
    cursor.execute(
        "SELECT 1 FROM citizen_credentials WHERE LOWER(username) = ? LIMIT 1", (candidate.lower(),)
    )
    return bool(cursor.fetchone())


def _generate_username(cursor, full_name: str, email: str) -> str:
    """A readable prefix from the applicant's name plus an unguessable tail, so
    the handle never reproduces the email or mobile the citizen registered with."""
    parts = [part for part in re.split(r'[^A-Za-z]+', (full_name or '').strip()) if part]
    if len(parts) > 1:
        base = _slug(f"{parts[0]}-{parts[-1]}")
    elif parts:
        base = _slug(parts[0])
    else:
        base = 'citizen'
    for _ in range(USERNAME_ATTEMPTS):
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not _handle_taken(cursor, candidate):
            return candidate
    raise RuntimeError('Could not allocate a unique citizen username.')


# ==========================================
# 2. TOKENS
# ==========================================

def _supersede_live_tokens(cursor, citizen_id: str, purpose: str, now: str) -> None:
    """A new link invalidates the previous one, so only the newest can be used."""
    cursor.execute(
        """
        UPDATE citizen_activation_tokens SET superseded_at = ?
        WHERE citizen_id = ? AND purpose = ? AND used_at IS NULL AND superseded_at IS NULL
        """,
        (now, citizen_id, purpose),
    )


def mint_token(citizen_id: str, purpose: str = ACTIVATION, issued_by: Optional[str] = None) -> str:
    """Create a fresh single-use link and return the only copy of the secret."""
    if purpose not in (ACTIVATION, PASSWORD_RESET):
        raise ValueError('Unknown token purpose.')
    now = _now()
    raw_token = secrets.token_urlsafe(24)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _supersede_live_tokens(cursor, citizen_id, purpose, _iso(now))
        cursor.execute(
            """
            INSERT INTO citizen_activation_tokens (
                id, citizen_id, purpose, token_hash, issued_by,
                issued_at, expires_at, attempts, max_attempts
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                f"act-{uuid.uuid4().hex[:12]}", citizen_id, purpose, hash_token(raw_token),
                issued_by, _iso(now), _iso(now + timedelta(hours=token_ttl_hours())),
                max_token_attempts(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return raw_token


def activation_link(raw_token: str, purpose: str = ACTIVATION) -> str:
    path = 'activate' if purpose == ACTIVATION else 'reset-password'
    return f"{portal_base_url()}/{path}/{raw_token}"


def _load_token(cursor, raw_token: str, purpose: str) -> Optional[Dict[str, Any]]:
    cursor.execute(
        "SELECT * FROM citizen_activation_tokens WHERE token_hash = ? AND purpose = ?",
        (hash_token(raw_token), purpose),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def resolve_token(raw_token: str, purpose: str = ACTIVATION) -> Dict[str, Any]:
    """Validate a link and spend one of its attempts.

    Raises ValueError with the citizen-facing reason; the raw token is never
    echoed back.
    """
    raw_token = (raw_token or '').strip()
    if not raw_token:
        raise ValueError('This link is not valid. Please use the activation link you received.')

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        token = _load_token(cursor, raw_token, purpose)
        if not token:
            raise ValueError('This link is not valid. Please use the activation link you received.')

        cursor.execute(
            "UPDATE citizen_activation_tokens SET attempts = attempts + 1 WHERE id = ?",
            (token['id'],),
        )
        conn.commit()

        now = _now()
        if token['used_at']:
            raise ValueError('This link has already been used. Request a new one to continue.')
        if token['superseded_at']:
            raise ValueError('This link is no longer valid because a newer one was issued.')
        if int(token['attempts']) + 1 > int(token['max_attempts']):
            raise ValueError('Too many attempts were made with this link. Request a new one to continue.')
        if _parse_iso(token['expires_at']) < now:
            raise ValueError('This link has expired. Request a new one to continue.')

        token['attempts'] = int(token['attempts']) + 1
        return token
    finally:
        conn.close()


def _consume_token(cursor, token_id: str, now: str) -> None:
    cursor.execute(
        "UPDATE citizen_activation_tokens SET used_at = ? WHERE id = ? AND used_at IS NULL",
        (now, token_id),
    )


# ==========================================
# 3. MESSAGE + PROVIDER DELIVERY
# ==========================================

SUBJECT = 'Your Citizen Account Has Been Verified'


def credential_subject() -> str:
    return SUBJECT


def credential_body(username: str, link: Optional[str], first_name: str = 'Citizen') -> str:
    """The approved wording for the citizen notification. Never contains a
    password."""
    lines = [
        f"Dear {first_name or 'Citizen'},",
        '',
        'Your registration and identity verification have been successfully completed.',
        '',
        'Your Citizen Portal account is now ready for activation.',
        '',
        f'Your username: {username}',
        '',
        'Please use the secure account activation link to set your password and access '
        'your Citizen Dashboard.',
    ]
    if link:
        lines += ['', f'Activation link (single use, valid for {token_ttl_hours()} hours):', link]
    lines += ['', 'Thank you for using the Digital FIR Portal.']
    return '\n'.join(lines)


def sms_credentials_body(username: str, link: Optional[str]) -> str:
    if not link:
        return f'eKSP: Your citizen account is verified. Username: {username}. Use the activation option on the portal status page.'
    return (
        f'eKSP: Your citizen account is verified. Username: {username}. '
        f'Set your password here (single use, {token_ttl_hours()}h): {link}'
    )


def _dispatch_over_email(recipient: str, subject: str, body: str) -> Tuple[str, str]:
    """Send through SMTP and report only what the server answered.

    Provider credentials are read from the environment and are never logged or
    returned; failures are reduced to the exception class name.
    """
    host = _env('SMTP_HOST')
    if not host or not recipient:
        return NOT_CONFIGURED, 'Email delivery is not configured on this server (SMTP_HOST is unset).'

    mail_from = _env('SMTP_MAIL_FROM') or _env('SMTP_USERNAME')
    if not mail_from:
        return NOT_CONFIGURED, 'Email delivery is configured but no sender address is set (SMTP_MAIL_FROM).'

    mode = (_env('SMTP_USE_TLS') or 'starttls').lower()
    try:
        port = int(_env('SMTP_PORT') or ('465' if mode == 'ssl' else '587'))
    except ValueError:
        return FAILED, 'SMTP_PORT is not a valid port number.'

    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = mail_from
    message['To'] = recipient
    message.set_content(body)

    username = _env('SMTP_USERNAME')
    password = _env('SMTP_PASSWORD')
    try:
        if mode == 'ssl':
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            server.ehlo()
            if mode == 'starttls':
                server.starttls()
                server.ehlo()
            if username and password:
                server.login(username, password)
            refused = server.send_message(message)
        if refused:
            return FAILED, f'The email provider refused the message: {refused}'
        return SENT, f'Accepted by {host}:{port} for delivery to {recipient}.'
    except Exception as error:
        return FAILED, f'The email provider did not accept the message ({type(error).__name__}).'


def _dispatch_over_sms(recipient: str, body: str) -> Tuple[str, str]:
    endpoint = _env('SMS_GATEWAY_URL')
    api_key = _env('SMS_GATEWAY_API_KEY')
    if not endpoint or not api_key or not recipient:
        return NOT_CONFIGURED, 'SMS delivery is not configured on this server (SMS_GATEWAY_URL / SMS_GATEWAY_API_KEY are unset).'

    payload = json.dumps({
        'to': recipient,
        'sender': _env('SMS_GATEWAY_SENDER') or 'EKSP',
        'message': body,
    }).encode('utf-8')
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method='POST',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if 200 <= response.status < 300:
                return SENT, f'Accepted by the SMS gateway (HTTP {response.status}).'
        return FAILED, 'The SMS gateway returned an unsuccessful status.'
    except Exception as error:
        return FAILED, f'The SMS gateway could not accept the message ({type(error).__name__}).'


def _channels_for(citizen: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    """Return (channel, recipient, builder) candidates in priority order."""
    candidates: List[Tuple[str, str, str]] = []
    if _env('SMTP_HOST'):
        candidates.append(('EMAIL', citizen.get('email') or '', 'email'))
    if _env('SMS_GATEWAY_URL') and _env('SMS_GATEWAY_API_KEY'):
        candidates.append(('SMS', citizen.get('phone') or '', 'sms'))
    return candidates


def deliver_credentials(
    citizen_id: str,
    link: Optional[str] = None,
    actor_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Send the credential notice over a configured provider and persist the result.

    ``link`` is only ever the plaintext token held by the caller; the database
    keeps its hash.
    """
    citizen = _load_citizen(citizen_id)
    if not citizen:
        raise ValueError('Citizen account not found.')
    credentials = get_credentials(citizen_id)
    if not credentials:
        raise ValueError('No credentials have been issued for this citizen.')

    username = credentials['username']
    subject = credential_subject()
    body = credential_body(username, link, (citizen.get('name') or 'Citizen').split()[0])

    attempts = int(credentials['delivery_attempts'])
    outcomes: List[str] = []
    delivered: Optional[Tuple[str, str]] = None

    for channel, recipient, kind in _channels_for(citizen):
        if not recipient:
            outcomes.append(f'{channel}: no recipient address on file')
            continue
        if kind == 'email':
            status, detail = _dispatch_over_email(recipient, subject, body)
        else:
            status, detail = _dispatch_over_sms(recipient, sms_credentials_body(username, link))
        outcomes.append(f'{channel}: {status} — {detail}')
        if status == SENT:
            delivered = (channel, detail)
            break

    if delivered:
        channel, detail = delivered
        status = SENT
    elif any(NOT_CONFIGURED in outcome for outcome in outcomes) and not any(FAILED in outcome for outcome in outcomes):
        status, channel, detail = NOT_CONFIGURED, 'NONE', ' '.join(outcomes)
    elif outcomes:
        status, channel, detail = FAILED, 'NONE', ' '.join(outcomes)
    else:
        status, channel, detail = NOT_CONFIGURED, 'NONE', (
            'No email or SMS provider is configured on this server, so the credentials '
            'could not be sent out of band. The secure activation option on the '
            'registration status page is the available channel.'
        )

    now = _now()
    now_iso = _iso(now)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            UPDATE citizen_credentials
            SET delivery_channel = ?, delivery_status = ?, delivery_detail = ?,
                delivery_attempts = delivery_attempts + 1,
                delivered_at = ?, updated_at = ?
            WHERE citizen_id = ?
            """,
            (channel, status, detail[:900], now_iso if status == SENT else None, now_iso, citizen_id),
        )
        conn.commit()
    finally:
        conn.close()

    _record_in_app_notification(citizen_id, credentials, citizen, status, channel, actor_label)
    _audit(
        actor_id=citizen_id,
        actor_email=credentials['username'],
        actor_role='CITIZEN',
        action='CITIZEN_CREDENTIALS_DELIVERY',
        resource_id=credentials['id'],
        details=f'{status} via {channel}: {detail[:300]}',
        status='SUCCESS' if status == SENT else 'WARNING',
    )

    return {
        'citizen_id': citizen_id,
        'username': username,
        'delivery_status': status,
        'delivery_channel': channel,
        'delivery_detail': detail,
        'delivery_attempts': attempts + 1,
    }


def _record_in_app_notification(
    citizen_id: str,
    credentials: Dict[str, Any],
    citizen: Dict[str, Any],
    status: str,
    channel: str,
    actor_label: Optional[str],
) -> None:
    """Persistent, read-tracked in-app notice. Carries the username, never a
    password and never a live token."""
    from backend.services.notification_service import create_notification

    if status == SENT:
        closing = (
            f"Your username and activation instructions have been sent to your registered "
            f"{'email' if channel == 'EMAIL' else 'mobile'} address."
        )
    elif status == NOT_CONFIGURED:
        closing = (
            'No email or SMS provider is configured, so the instructions could not be sent '
            'out of band. Open your registration status page to use the secure activation option.'
        )
    else:
        closing = (
            'Credential notification delivery failed. Open your registration status page to '
            'use the secure activation option or contact support.'
        )

    create_notification(
        user_id=citizen_id,
        title='Your Citizen Account Has Been Verified',
        message=(
            f"Your registration has been verified. Your username: {credentials['username']}. {closing}"
        ),
        notification_type='CITIZEN_CREDENTIALS',
        severity='SUCCESS' if status == SENT else 'WARNING',
        event_id=f"citizen-credentials-{credentials['id']}-attempt-{credentials['delivery_attempts'] + 1}",
    )


# ==========================================
# 4. ISSUE ON APPROVAL
# ==========================================

def _load_citizen(citizen_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (citizen_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    citizen = dict(row)
    citizen.pop('password_hash', None)
    citizen.pop('salt', None)
    return citizen


def get_credentials(citizen_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM citizen_credentials WHERE citizen_id = ?", (citizen_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def issue_credentials(
    application: Dict[str, Any],
    actor_user: Dict[str, Any],
    deliver: bool = True,
) -> Dict[str, Any]:
    """Provision the login account for an approved citizen.

    Safe to call repeatedly: the first call writes the username and the audit
    trail, later calls return the same row without minting anything new, so a
    re-run of the approval can never produce a second account.
    """
    citizen_id = application.get('citizen_id')
    if not citizen_id:
        raise ValueError('This application is not linked to a citizen account.')

    actor_role = (actor_user or {}).get('role')
    if actor_role not in ('VERIFICATION_OFFICER', 'ADMIN'):
        raise PermissionError('Only a Verification Officer or Administrator may issue citizen credentials.')

    conn = get_db_connection()
    cursor = conn.cursor()
    now = _now()
    now_iso = _iso(now)
    created = False
    try:
        cursor.execute("SELECT * FROM citizen_credentials WHERE citizen_id = ?", (citizen_id,))
        existing = cursor.fetchone()
        if existing:
            credentials = dict(existing)
        else:
            username = _generate_username(cursor, application.get('full_name') or '', application.get('email') or '')
            credentials_id = f"ccred-{uuid.uuid4().hex[:12]}"
            cursor.execute(
                """
                INSERT INTO citizen_credentials (
                    id, citizen_id, application_id, reference, username, issued_at,
                    issued_by, issued_by_name, delivery_channel, delivery_status,
                    delivery_attempts, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'NONE', 'PENDING', 0, ?)
                """,
                (
                    credentials_id, citizen_id, application.get('id'), application.get('reference'),
                    username, now_iso, (actor_user or {}).get('id'),
                    (actor_user or {}).get('name') or 'Verification Officer', now_iso,
                ),
            )
            credentials = {
                'id': credentials_id, 'citizen_id': citizen_id, 'username': username,
                'application_id': application.get('id'), 'reference': application.get('reference'),
                'delivery_channel': 'NONE', 'delivery_status': 'PENDING', 'delivery_attempts': 0,
            }
            created = True

        # Mirror the handle onto the account so login can resolve it, and record
        # the verification outcome the officer just decided.
        cursor.execute(
            """
            UPDATE users
            SET username = COALESCE(username, ?), verification_status = 'VERIFIED',
                verified_at = ?, updated_at = ?
            WHERE id = ? AND role = 'CITIZEN'
            """,
            (credentials['username'], now_iso, now_iso, citizen_id),
        )
        if created:
            cursor.execute(
                """
                INSERT INTO citizen_application_events (
                    id, application_id, action, status_from, status_to, remarks,
                    actor_id, actor_name, actor_role, actor_badge, created_at
                ) VALUES (?, ?, 'CREDENTIALS_ISSUED', 'APPROVED', 'APPROVED', ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"cae-{uuid.uuid4().hex[:12]}", application.get('id'),
                    f"Login username {credentials['username']} issued for activation.",
                    (actor_user or {}).get('id'), (actor_user or {}).get('name') or 'Verification Officer',
                    actor_role, (actor_user or {}).get('badge_number'), now_iso,
                ),
            )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        cursor.execute("SELECT * FROM citizen_credentials WHERE citizen_id = ?", (citizen_id,))
        row = cursor.fetchone()
        if not row:
            raise
        credentials = dict(row)
    finally:
        conn.close()

    if created:
        _audit(
            actor_id=(actor_user or {}).get('id'),
            actor_email=(actor_user or {}).get('email'),
            actor_role=actor_role or 'VERIFICATION_OFFICER',
            action='CITIZEN_CREDENTIALS_ISSUED',
            resource_id=credentials['id'],
            details=(
                f"Citizen {application.get('reference')} approved; username "
                f"{credentials['username']} issued by {(actor_user or {}).get('name') or 'Verification Officer'}."
            ),
            status='SUCCESS',
        )

    result = dict(credentials)
    result['created'] = created
    result['delivery_status'] = result.get('delivery_status')

    if deliver:
        raw_token = mint_token(
            citizen_id, ACTIVATION,
            issued_by=(actor_user or {}).get('id') or 'VERIFICATION_OFFICER',
        )
        delivery = deliver_credentials(citizen_id, activation_link(raw_token, ACTIVATION),
                                       actor_label=(actor_user or {}).get('name'))
        result.update({
            'delivery_status': delivery['delivery_status'],
            'delivery_channel': delivery['delivery_channel'],
            'delivery_detail': delivery['delivery_detail'],
            'delivery_attempts': delivery['delivery_attempts'],
        })
    return result


def retry_delivery(citizen_id: str, actor_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Re-send the credential notice on a fresh single-use link."""
    credentials = get_credentials(citizen_id)
    if not credentials:
        raise ValueError('No credentials have been issued for this citizen yet.')
    raw_token = mint_token(
        citizen_id, ACTIVATION,
        issued_by=(actor_user or {}).get('id') or 'RETRY',
    )
    return deliver_credentials(
        citizen_id, activation_link(raw_token, ACTIVATION),
        actor_label=(actor_user or {}).get('name'),
    )


# ==========================================
# 5. ACTIVATION AND PASSWORD SETUP
# ==========================================

def validate_password(password: str) -> Optional[str]:
    """Same minimum as registration, plus a confirmation-friendly message."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f'Password must be at least {MIN_PASSWORD_LENGTH} characters.'
    if password != password.strip():
        return 'Password cannot start or end with a space.'
    return None


def complete_activation(raw_token: str, password: str, confirm_password: Optional[str] = None) -> Dict[str, Any]:
    """Turn an activation link into a working account with the citizen's own password."""
    token = resolve_token(raw_token, ACTIVATION)
    if confirm_password is not None and password != confirm_password:
        raise ValueError('The passwords do not match. Please re-enter them.')
    error = validate_password(password)
    if error:
        raise ValueError(error)

    from backend.services.auth_service import set_password

    citizen = _load_citizen(token['citizen_id'])
    if not citizen or citizen.get('role') != 'CITIZEN':
        raise ValueError('This activation link no longer matches a citizen account.')

    credentials = get_credentials(token['citizen_id'])
    if not credentials:
        raise ValueError('No credentials have been issued for this citizen.')

    now_iso = _iso(_now())
    set_password(token['citizen_id'], password)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _consume_token(cursor, token['id'], now_iso)
        cursor.execute(
            "UPDATE citizen_credentials SET activated_at = ?, password_set_at = ?, updated_at = ? WHERE citizen_id = ?",
            (now_iso, now_iso, now_iso, token['citizen_id']),
        )
        cursor.execute(
            "UPDATE users SET status = 'ACTIVE', updated_at = ? WHERE id = ? AND role = 'CITIZEN'",
            (now_iso, token['citizen_id']),
        )
        conn.commit()
    finally:
        conn.close()

    _audit(
        actor_id=token['citizen_id'],
        actor_email=credentials['username'],
        actor_role='CITIZEN',
        action='CITIZEN_ACCOUNT_ACTIVATED',
        resource_id=credentials['id'],
        details=f"Citizen account {credentials['username']} activated with a self-set password.",
        status='SUCCESS',
    )
    publish({
        'type': 'CITIZEN_ACCOUNT_ACTIVATED',
        'citizen_id': token['citizen_id'],
        'username': credentials['username'],
        'timestamp': now_iso,
    })

    return {
        'citizen_id': token['citizen_id'],
        'username': credentials['username'],
        'activated_at': now_iso,
    }


def request_password_reset(identifier: str) -> Dict[str, Any]:
    """Issue a reset link for a verified citizen, without confirming the
    identifier exists to the caller."""
    citizen = _find_citizen(identifier)
    generic = {'requested': True, 'delivery_status': 'NOT_CONFIGURED', 'detail': (
        'If that account is verified, a password reset link has been issued to the '
        'registered contact channel.'
    )}
    if not citizen:
        return generic

    credentials = get_credentials(citizen['id'])
    if not credentials:
        return generic

    raw_token = mint_token(citizen['id'], PASSWORD_RESET, issued_by='SELF_SERVICE')
    try:
        delivery = deliver_password_reset(citizen['id'], raw_token)
    except Exception as error:
        return {'requested': True, 'delivery_status': FAILED, 'detail': str(error)}
    return {
        'requested': True,
        'delivery_status': delivery['delivery_status'],
        'channel': delivery.get('delivery_channel'),
        'detail': delivery['delivery_detail'],
        'username_shown': citizen.get('username'),
    }


def deliver_password_reset(citizen_id: str, raw_token: str) -> Dict[str, Any]:
    """Reset links go out over the same providers, tracked on the credentials row."""
    return deliver_credentials(citizen_id, activation_link(raw_token, PASSWORD_RESET))


def complete_password_reset(raw_token: str, password: str, confirm_password: Optional[str] = None) -> Dict[str, Any]:
    token = resolve_token(raw_token, PASSWORD_RESET)
    if confirm_password is not None and password != confirm_password:
        raise ValueError('The passwords do not match. Please re-enter them.')
    error = validate_password(password)
    if error:
        raise ValueError(error)

    from backend.services.auth_service import set_password

    credentials = get_credentials(token['citizen_id'])
    if not credentials:
        raise ValueError('No credentials have been issued for this citizen.')

    set_password(token['citizen_id'], password)
    now_iso = _iso(_now())
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        _consume_token(cursor, token['id'], now_iso)
        cursor.execute(
            "UPDATE citizen_credentials SET password_set_at = ?, updated_at = ? WHERE citizen_id = ?",
            (now_iso, now_iso, token['citizen_id']),
        )
        conn.commit()
    finally:
        conn.close()

    _audit(
        actor_id=token['citizen_id'],
        actor_email=credentials['username'],
        actor_role='CITIZEN',
        action='CITIZEN_PASSWORD_RESET',
        resource_id=credentials['id'],
        details='Citizen password reset completed through a single-use reset link.',
        status='SUCCESS',
    )
    return {'citizen_id': token['citizen_id'], 'username': credentials['username'], 'reset_at': now_iso}


def _find_citizen(identifier: str) -> Optional[Dict[str, Any]]:
    clean = (identifier or '').strip().lower()
    if not clean:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM users
        WHERE role = 'CITIZEN'
          AND (LOWER(email) = ? OR LOWER(phone) = ? OR LOWER(username) = ?)
        """,
        (clean, clean, clean),
    )
    rows = cursor.fetchall()
    conn.close()
    if len(rows) != 1:
        return None
    citizen = dict(rows[0])
    citizen.pop('password_hash', None)
    citizen.pop('salt', None)
    return citizen


# ==========================================
# 6. STATUS FOR THE CITIZEN SCREEN
# ==========================================

def activation_summary(citizen_id: str) -> Optional[Dict[str, Any]]:
    """Everything the registration status page may show, and nothing secret."""
    credentials = get_credentials(citizen_id)
    if not credentials:
        return None

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT purpose, issued_at, expires_at, used_at, superseded_at
        FROM citizen_activation_tokens
        WHERE citizen_id = ? AND superseded_at IS NULL
        ORDER BY issued_at DESC LIMIT 1
        """,
        (citizen_id,),
    )
    token_row = cursor.fetchone()
    cursor.execute("SELECT status, verification_status, verified_at, username FROM users WHERE id = ?", (citizen_id,))
    user_row = cursor.fetchone()
    conn.close()

    summary: Dict[str, Any] = {
        'username': credentials['username'],
        'issued_at': credentials['issued_at'],
        'issued_by_name': credentials['issued_by_name'],
        'delivery_status': credentials['delivery_status'],
        'delivery_channel': credentials['delivery_channel'],
        'delivery_detail': credentials['delivery_detail'],
        'delivery_attempts': credentials['delivery_attempts'],
        'delivered_at': credentials['delivered_at'],
        'activated_at': credentials['activated_at'],
        'password_set_at': credentials['password_set_at'],
        'account_status': (dict(user_row).get('status') if user_row else None),
        'verified_at': (dict(user_row).get('verified_at') if user_row else None),
        'link_status': 'NONE',
        'link_expires_at': None,
    }
    if token_row:
        token = dict(token_row)
        summary['link_purpose'] = token['purpose']
        summary['link_expires_at'] = token['expires_at']
        if token['used_at']:
            summary['link_status'] = 'USED'
        elif _parse_iso(token['expires_at']) < _now():
            summary['link_status'] = 'EXPIRED'
        else:
            summary['link_status'] = 'AVAILABLE'
    return summary


def issue_self_service_link(citizen_id: str) -> Dict[str, Any]:
    """Mint a fresh single-use activation link for a citizen who proved identity
    on the status page, when out-of-band delivery was unavailable."""
    raw_token = mint_token(citizen_id, ACTIVATION, issued_by='SELF_SERVICE')
    return {
        'citizen_id': citizen_id,
        'link': activation_link(raw_token, ACTIVATION),
        'expires_in_hours': token_ttl_hours(),
    }


def _audit(actor_id: Optional[str], actor_email: Optional[str], actor_role: str,
           action: str, resource_id: Optional[str], details: str, status: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO system_audit_logs (
            id, timestamp, user_id, user_email, role, action,
            resource_type, resource_id, details, ip_address, status
        ) VALUES (?, ?, ?, ?, ?, ?, 'CITIZEN_CREDENTIALS', ?, ?, '127.0.0.1', ?)
        """,
        (
            f"aud-{uuid.uuid4().hex[:12]}", _iso(_now()), actor_id, actor_email,
            actor_role, action, resource_id, details[:900], status,
        ),
    )
    conn.commit()
    conn.close()

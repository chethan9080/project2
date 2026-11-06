"""
Citizen Registration Verification Service.

Handles the complete lifecycle of a citizen registration application:
- secure storage of the live photograph and government ID document
- a review queue for Verification Officers
- immutable verification history with officer identity and server timestamps
- atomic, duplicate-safe status transitions
- push notifications to open verification / citizen portals

Files are written outside the public web root and are only served through an
authenticated endpoint (see backend/api.py).
"""

import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection
from backend.services.realtime_events import publish

SECURE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads', 'citizen_applications'
))

ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
ALLOWED_PHOTO_EXTENSIONS = {'.png', '.jpg', '.jpeg'}

MEDIA_TYPES = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
}

STATUS_LABELS = {
    'PENDING': 'Pending Review',
    'UNDER_REVIEW': 'Under Review',
    'ADDITIONAL_INFO_REQUIRED': 'Additional Info Required',
    'APPROVED': 'Approved',
    'REJECTED': 'Rejected',
}

ACTION_LABELS = {
    'SUBMITTED': 'Application Submitted',
    'APPROVED': 'Application Approved',
    'REJECTED': 'Application Rejected',
    'ADDITIONAL_INFO_REQUESTED': 'Additional Information Requested',
    'ADDITIONAL_INFO_SUBMITTED': 'Additional Information Submitted',
    'REMARK': 'Internal Verification Remark',
}

REVIEWER_ROLES = ('VERIFICATION_OFFICER', 'ADMIN')
TERMINAL_STATUSES = ('APPROVED', 'REJECTED')
REVIEWABLE_STATUSES = ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED')


def status_label(status: Optional[str]) -> str:
    return STATUS_LABELS.get(status or '', status or 'Unknown')


def action_label(action: Optional[str]) -> str:
    return ACTION_LABELS.get(action or '', (action or '').replace('_', ' ').title())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_extension(filename: Optional[str], allowed: set) -> str:
    extension = os.path.splitext(filename or '')[1].lower()
    if extension not in allowed:
        raise ValueError('Unsupported file type. Allowed formats: ' + ', '.join(sorted(allowed)))
    return extension


def store_application_file(application_id: str, kind: str, content: bytes,
                           extension: str, original_name: Optional[str] = None) -> str:
    """Write a verification file to the private upload directory and return its relative path."""
    if kind not in ('photo', 'id_document'):
        raise ValueError('Unknown application file kind.')
    if not content:
        raise ValueError('The uploaded file is empty.')
    allowed = ALLOWED_PHOTO_EXTENSIONS if kind == 'photo' else ALLOWED_DOCUMENT_EXTENSIONS
    normalized = (extension or '').lower()
    if normalized and not normalized.startswith('.'):
        normalized = f'.{normalized}'
    try:
        normalized = _normalize_extension(normalized, allowed)
    except ValueError:
        normalized = _normalize_extension(original_name, allowed)

    folder = os.path.join(SECURE_ROOT, application_id)
    os.makedirs(folder, exist_ok=True)
    filename = f"{kind}{normalized}"
    absolute_path = os.path.join(folder, filename)
    with open(absolute_path, 'wb') as handle:
        handle.write(content)
    return f"{application_id}/{filename}"


def resolve_secure_file(relative_path: Optional[str]) -> Optional[str]:
    """Resolve a stored file path, refusing any path that escapes the private root."""
    if not relative_path:
        return None
    absolute_path = os.path.abspath(os.path.join(SECURE_ROOT, relative_path))
    if not absolute_path.startswith(SECURE_ROOT + os.sep):
        raise ValueError('Invalid document path.')
    return absolute_path if os.path.isfile(absolute_path) else None


def media_type_for(path: Optional[str]) -> str:
    return MEDIA_TYPES.get(os.path.splitext(path or '')[1].lower(), 'application/octet-stream')


def _generate_reference(cursor) -> str:
    for _ in range(10):
        reference = f"CVR-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        cursor.execute("SELECT 1 FROM citizen_applications WHERE reference = ?", (reference,))
        if not cursor.fetchone():
            return reference
    raise RuntimeError('Could not allocate a unique application reference.')


def create_citizen_application(
    *,
    citizen_id: str,
    full_name: str,
    date_of_birth: str,
    gender: Optional[str],
    mobile: str,
    email: str,
    address: str,
    state: str,
    district: str,
    username: str,
    gov_id_type: str,
    gov_id_masked: str,
    photo_bytes: bytes,
    photo_ext: str,
    document_bytes: bytes,
    document_ext: str,
    document_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one pending registration application and its secure files."""
    application_id = f"capp-{uuid.uuid4().hex[:12]}"
    reference = ''
    photo_path = None
    document_path = None

    try:
        photo_path = store_application_file(application_id, 'photo', photo_bytes, photo_ext, f'photo{photo_ext}')
        document_path = store_application_file(
            application_id, 'id_document', document_bytes, document_ext, document_name or f'document{document_ext}'
        )

        conn = get_db_connection()
        cursor = conn.cursor()
        reference = _generate_reference(cursor)
        now = _now()

        cursor.execute("""
            INSERT INTO citizen_applications (
                id, reference, citizen_id, full_name, date_of_birth, gender, mobile, email,
                address, state, district, username, gov_id_type, gov_id_masked,
                id_document_path, id_document_name, photo_path, status,
                submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """, (
            application_id, reference, citizen_id, full_name.strip(), date_of_birth, gender,
            mobile.strip(), email.strip().lower(), address.strip(), state.strip(), district.strip(),
            username.strip(), gov_id_type, gov_id_masked, document_path,
            document_name, photo_path, now, now
        ))

        cursor.execute("""
            INSERT INTO citizen_application_events (
                id, application_id, action, status_from, status_to, remarks,
                actor_id, actor_name, actor_role, actor_badge, created_at
            ) VALUES (?, ?, 'SUBMITTED', NULL, 'PENDING', ?, ?, ?, 'CITIZEN', NULL, ?)
        """, (
            f"cae-{uuid.uuid4().hex[:12]}", application_id,
            'Citizen registration application submitted for verification.',
            citizen_id, full_name.strip(), now
        ))

        cursor.execute("SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER' AND status = 'ACTIVE'")
        officer_ids = [row['id'] for row in cursor.fetchall()]
        for officer_id in officer_ids:
            cursor.execute("""
                INSERT INTO citizen_application_alerts (
                    id, application_id, recipient_id, title, message, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (
                f"cal-{uuid.uuid4().hex[:12]}", application_id, officer_id,
                'New Citizen Registration',
                f"{full_name.strip()} submitted registration application {reference}.",
                now
            ))

        conn.commit()
        cursor.execute("SELECT * FROM citizen_applications WHERE id = ?", (application_id,))
        application = dict(cursor.fetchone())
        conn.close()
    except Exception:
        shutil.rmtree(os.path.join(SECURE_ROOT, application_id), ignore_errors=True)
        raise

    publish({
        'type': 'CITIZEN_APPLICATION_SUBMITTED',
        'application_id': application_id,
        'reference': reference,
        'citizen_id': citizen_id,
        'full_name': full_name.strip(),
        'status': 'PENDING',
        'timestamp': application['submitted_at'],
    })
    _notify_verification_officers(application)
    return application


def _notify_verification_officers(application: Dict[str, Any], update: bool = False) -> None:
    """Deliver a real persistent notification to every active Verification Officer."""
    try:
        from backend.services.notification_service import create_notification
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER' AND status = 'ACTIVE'"
        )
        officer_ids = [row['id'] for row in cursor.fetchall()]
        conn.close()
        for officer_id in officer_ids:
            create_notification(
                user_id=officer_id,
                title=(
                    'Additional Information Received' if update else 'New Citizen Registration'
                ),
                message=(
                    f"{application.get('full_name')} "
                    + ('resubmitted information for' if update else 'submitted')
                    + f" registration application {application.get('reference')}."
                ),
                notification_type='CITIZEN_REGISTRATION',
                severity='INFO',
                event_id=(
                    f"citizen-registration-{application['id']}-{application.get('updated_at')}"
                ),
            )
    except Exception as exc:
        print(f"Citizen registration notification error: {exc}")


def get_citizen_application(application_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM citizen_applications WHERE id = ?", (application_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_application_by_citizen(citizen_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM citizen_applications WHERE citizen_id = ?", (citizen_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def find_application_for_status(reference: str, identifier: str) -> Optional[Dict[str, Any]]:
    """Public status lookup requiring both the application reference and registered email/mobile."""
    ref = (reference or '').strip().upper()
    ident = (identifier or '').strip().lower()
    if not ref or not ident:
        return None
    mobile_key = ident.replace(' ', '').replace('-', '')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM citizen_applications
        WHERE UPPER(reference) = ?
          AND (LOWER(email) = ? OR REPLACE(REPLACE(mobile, ' ', ''), '-', '') = ?)
    """, (ref, ident, mobile_key))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def resubmit_additional_information(
    application_id: str,
    *,
    reference: str,
    identifier: str,
    note: str,
    document_bytes: Optional[bytes] = None,
    document_ext: Optional[str] = None,
    document_name: Optional[str] = None,
    photo_bytes: Optional[bytes] = None,
    photo_ext: Optional[str] = None,
) -> Dict[str, Any]:
    """Accept requested additional information from a citizen and return the application to review."""
    note = (note or '').strip()
    if not note:
        raise ValueError('Please describe the additional information requested by the officer.')

    application = find_application_for_status(reference, identifier)
    if not application or application.get('id') != application_id:
        raise PermissionError('Application reference and registered email/mobile do not match.')

    if (application.get('status') or '').upper() != 'ADDITIONAL_INFO_REQUIRED':
        raise ValueError('This application is not currently awaiting additional information.')

    application_id = application['id']
    new_document_path = None
    new_photo_path = None
    if document_bytes:
        new_document_path = store_application_file(
            application_id, 'id_document', document_bytes, document_ext or '',
            document_name or f'document{document_ext or ""}'
        )
    if photo_bytes:
        new_photo_path = store_application_file(
            application_id, 'photo', photo_bytes, photo_ext or '', f'photo{photo_ext or ""}'
        )

    now = _now()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE citizen_applications
            SET status = 'UNDER_REVIEW', updated_at = ?
                {doc_clause}
                {photo_clause}
            WHERE id = ? AND status = 'ADDITIONAL_INFO_REQUIRED'
        """.format(
            doc_clause=", id_document_path = ?, id_document_name = ?" if new_document_path else "",
            photo_clause=", photo_path = ?" if new_photo_path else "",
        ), tuple(
            [now]
            + ([new_document_path, document_name or 'document'] if new_document_path else [])
            + ([new_photo_path] if new_photo_path else [])
            + [application_id]
        ))
        if cursor.rowcount != 1:
            raise ValueError('This application is no longer awaiting additional information.')

        cursor.execute("""
            INSERT INTO citizen_application_events (
                id, application_id, action, status_from, status_to, remarks,
                actor_id, actor_name, actor_role, actor_badge, created_at
            ) VALUES (?, ?, 'ADDITIONAL_INFO_SUBMITTED', 'ADDITIONAL_INFO_REQUIRED', 'UNDER_REVIEW',
                      ?, ?, ?, 'CITIZEN', NULL, ?)
        """, (
            f"cae-{uuid.uuid4().hex[:12]}", application_id, note,
            application['citizen_id'], application['full_name'], now
        ))

        cursor.execute("SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER' AND status = 'ACTIVE'")
        officer_ids = [row['id'] for row in cursor.fetchall()]
        for officer_id in officer_ids:
            cursor.execute("""
                INSERT INTO citizen_application_alerts (
                    id, application_id, recipient_id, title, message, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (
                f"cal-{uuid.uuid4().hex[:12]}", application_id, officer_id,
                'Additional Information Received',
                f"{application['full_name']} resubmitted information for application {application['reference']}.",
                now
            ))
        conn.commit()
        cursor.execute("SELECT * FROM citizen_applications WHERE id = ?", (application_id,))
        updated = dict(cursor.fetchone())
    finally:
        conn.close()

    for previous_path, new_path in (
        (application.get('id_document_path'), new_document_path),
        (application.get('photo_path'), new_photo_path),
    ):
        if new_path and previous_path and previous_path != new_path:
            old_file = resolve_secure_file(previous_path)
            if old_file:
                os.remove(old_file)

    publish({
        'type': 'CITIZEN_APPLICATION_UPDATED',
        'application_id': application_id,
        'reference': application['reference'],
        'citizen_id': application['citizen_id'],
        'status': 'UNDER_REVIEW',
        'action': 'ADDITIONAL_INFO_SUBMITTED',
        'remarks': note,
        'actor': 'Citizen',
        'timestamp': now,
    })
    _notify_verification_officers(updated, update=True)
    return updated


def get_citizen_applications() -> List[Dict[str, Any]]:
    """Return all applications, open ones first and newest first within each group."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM citizen_applications
        ORDER BY CASE
            WHEN status IN ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED') THEN 0
            ELSE 1
        END, submitted_at DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_application_events(application_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM citizen_application_events
        WHERE application_id = ?
        ORDER BY created_at ASC
    """, (application_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_application_stats() -> Dict[str, int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            SUM(CASE WHEN status IN ('PENDING', 'UNDER_REVIEW') THEN 1 ELSE 0 END) AS open_count,
            SUM(CASE WHEN status = 'ADDITIONAL_INFO_REQUIRED' THEN 1 ELSE 0 END) AS info_count,
            SUM(CASE WHEN status = 'APPROVED' THEN 1 ELSE 0 END) AS approved_count,
            SUM(CASE WHEN status = 'REJECTED' THEN 1 ELSE 0 END) AS rejected_count,
            COUNT(*) AS total_count
        FROM citizen_applications
    """)
    row = cursor.fetchone()
    conn.close()
    return {key: int(row[key] or 0) for key in row.keys()} if row else {}


def get_alerts(recipient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT a.*, c.reference, c.full_name, c.status AS application_status
        FROM citizen_application_alerts a
        LEFT JOIN citizen_applications c ON a.application_id = c.id
        WHERE a.recipient_id = ?
        ORDER BY a.created_at DESC
        LIMIT ?
    """, (recipient_id, limit))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_unread_alert_count(recipient_id: str) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS count FROM citizen_application_alerts WHERE recipient_id = ? AND is_read = 0",
        (recipient_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return int(row['count']) if row else 0


def mark_alerts_read(recipient_id: str) -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE citizen_application_alerts SET is_read = 1 WHERE recipient_id = ? AND is_read = 0",
        (recipient_id,)
    )
    conn.commit()
    conn.close()


def record_application_action(
    application_id: str,
    actor_user: Dict[str, Any],
    action: str,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a verification action atomically and push the new status to both portals."""
    actor_role = (actor_user or {}).get('role')
    if actor_role not in REVIEWER_ROLES:
        raise PermissionError('Only Verification Officers or Administrators may review citizen applications.')

    action = (action or '').upper()
    if action not in ('APPROVE', 'REJECT', 'REQUEST_INFO', 'REMARK'):
        raise ValueError('Unknown verification action.')

    remarks = (remarks or '').strip()
    if action in ('REJECT', 'REQUEST_INFO', 'REMARK') and not remarks:
        raise ValueError('Remarks are required for this action.')

    target_status = {
        'APPROVE': 'APPROVED',
        'REJECT': 'REJECTED',
        'REQUEST_INFO': 'ADDITIONAL_INFO_REQUIRED',
    }.get(action)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM citizen_applications WHERE id = ?", (application_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError('Citizen application not found.')

    application = dict(row)
    status_from = application['status']
    now = _now()
    reviewer_name = (actor_user.get('name') or 'Verification Officer')
    reviewer_badge = actor_user.get('badge_number') or 'N/A'

    try:
        if action == 'REMARK':
            cursor.execute("""
                UPDATE citizen_applications
                SET internal_remarks = ?, updated_at = ?
                WHERE id = ?
            """, (remarks, now, application_id))
            status_to = status_from
        else:
            if status_from in TERMINAL_STATUSES:
                raise ValueError(
                    f"This application is already {status_label(status_from).lower()} and cannot be changed."
                )
            cursor.execute("""
                UPDATE citizen_applications
                SET status = ?, internal_remarks = CASE WHEN ? <> '' THEN ? ELSE internal_remarks END,
                    updated_at = ?, reviewed_by = ?, reviewed_by_name = ?, reviewed_at = ?
                WHERE id = ? AND status IN ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED')
            """, (
                target_status, remarks, remarks, now,
                actor_user.get('id'), reviewer_name, now, application_id
            ))
            if cursor.rowcount != 1:
                raise ValueError('This application was already processed by another officer.')
            status_to = target_status

        event_action = {
            'APPROVE': 'APPROVED',
            'REJECT': 'REJECTED',
            'REQUEST_INFO': 'ADDITIONAL_INFO_REQUESTED',
            'REMARK': 'REMARK',
        }[action]

        cursor.execute("""
            INSERT INTO citizen_application_events (
                id, application_id, action, status_from, status_to, remarks,
                actor_id, actor_name, actor_role, actor_badge, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"cae-{uuid.uuid4().hex[:12]}", application_id, event_action,
            status_from, status_to, remarks or None,
            actor_user.get('id'), reviewer_name, actor_role, reviewer_badge, now
        ))

        if action == 'APPROVE':
            cursor.execute("UPDATE users SET status = 'ACTIVE', updated_at = ? WHERE id = ?", (now, application['citizen_id']))
        elif action == 'REJECT':
            cursor.execute("UPDATE users SET status = 'SUSPENDED', updated_at = ? WHERE id = ?", (now, application['citizen_id']))

        if action != 'REMARK':
            message = (
                f"Your registration application {application['reference']} has been {status_label(status_to).lower()}."
                + (f" Officer remarks: {remarks}" if remarks else '')
            )
            cursor.execute("""
                INSERT INTO citizen_application_alerts (
                    id, application_id, recipient_id, title, message, is_read, created_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (
                f"cal-{uuid.uuid4().hex[:12]}", application_id, application['citizen_id'],
                f"Registration {status_label(status_to)}", message, now
            ))

        conn.commit()
        cursor.execute("SELECT * FROM citizen_applications WHERE id = ?", (application_id,))
        updated = dict(cursor.fetchone())
    finally:
        conn.close()

    if action != 'REMARK':
        try:
            from backend.services.notification_service import create_notification
            create_notification(
                user_id=application['citizen_id'],
                title=f"Citizen Registration {status_label(status_to)}",
                message=(
                    f"Your registration application {application['reference']} has been "
                    f"{status_label(status_to).lower()}."
                    + (f" Officer remarks: {remarks}" if remarks else '')
                ),
                notification_type='CITIZEN_VERIFICATION',
                severity='SUCCESS' if action == 'APPROVE' else (
                    'ALERT' if action == 'REJECT' else 'WARNING'
                ),
                event_id=f"citizen-application-{event_action}-{application_id}-{now}",
            )
        except Exception as exc:
            print(f"Citizen application notification error: {exc}")

        publish({
            'type': 'CITIZEN_APPLICATION_UPDATED',
            'application_id': application_id,
            'reference': application['reference'],
            'citizen_id': application['citizen_id'],
            'status': status_to,
            'action': event_action,
            'remarks': remarks,
            'reviewer': reviewer_name,
            'timestamp': now,
        })

        if action == 'APPROVE':
            # Approval provisions the login account. Issuance is idempotent and
            # delivery reports the provider's own answer, so a second approval of
            # the same citizen can never mint a second set of credentials.
            try:
                from backend.services.citizen_credentials_service import issue_credentials
                credentials = issue_credentials(updated, actor_user)
                updated['credentials'] = {
                    'username': credentials['username'],
                    'delivery_status': credentials['delivery_status'],
                    'delivery_channel': credentials.get('delivery_channel'),
                    'delivery_detail': credentials.get('delivery_detail'),
                    'created': credentials.get('created', False),
                }
            except Exception as exc:
                updated['credentials_error'] = str(exc)
                print(f"Citizen credential issuance error: {exc}")
    else:
        publish({
            'type': 'CITIZEN_APPLICATION_REMARKED',
            'application_id': application_id,
            'citizen_id': application['citizen_id'],
            'timestamp': now,
        })

    return updated

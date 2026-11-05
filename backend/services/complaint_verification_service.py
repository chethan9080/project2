"""
Complaint Verification Service (Verification Officer Desk).

A complaint is filed by a citizen, then reviewed by the Verification Officer.
Only after verification can it be forwarded for official FIR registration and
police officer assignment. Every decision is append-only, records the officer
identity and server timestamp, notifies the citizen, and pushes a real-time
event to every open dashboard.

All figures and records are read directly from SQLite. Nothing is simulated.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection
from backend.services.realtime_events import publish

REVIEWER_ROLES = ('VERIFICATION_OFFICER', 'ADMIN')

VERIFICATION_LABELS = {
    'PENDING': 'Pending Verification',
    'UNDER_REVIEW': 'Under Verification',
    'VERIFIED': 'Verified',
    'ADDITIONAL_INFO_REQUIRED': 'Additional Information Required',
    'REJECTED': 'Rejected',
}

ACTION_LABELS = {
    'REVIEW_STARTED': 'Verification Started',
    'VERIFIED': 'Complaint Verified',
    'REJECTED': 'Complaint Rejected',
    'ADDITIONAL_INFO_REQUESTED': 'Additional Information Requested',
    'REMARK': 'Internal Verification Remark',
    'OFFICER_ASSIGNED': 'Investigating Officer Assigned',
}


def verification_label(status: Optional[str]) -> str:
    return VERIFICATION_LABELS.get(status or '', (status or 'Unknown').replace('_', ' ').title())


def action_label(action: Optional[str]) -> str:
    return ACTION_LABELS.get(action or '', (action or '').replace('_', ' ').title())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _complaint_rows(where: str = '', params: tuple = (), limit: Optional[int] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    query = f"""
        SELECT c.*,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name_from_user, o.badge_number AS officer_badge,
               o.rank AS officer_rank, o.station AS officer_station, o.phone AS officer_phone,
               f.fir_number AS fir_number, f.status AS fir_status
        FROM complaints c
        LEFT JOIN users u ON c.citizen_id = u.id
        LEFT JOIN users o ON c.assigned_officer_id = o.id
        LEFT JOIN firs f ON c.fir_id = f.id
        {where}
        ORDER BY c.submitted_at DESC
    """
    if limit:
        query += " LIMIT ?"
        params = tuple(params) + (limit,)
    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_verification_queue(search: Optional[str] = None) -> List[Dict[str, Any]]:
    """Complaints still awaiting a Verification Officer decision."""
    clauses = [
        "c.fir_id IS NULL",
        "c.status NOT IN ('REJECTED', 'CLOSED', 'RESOLVED')",
        "COALESCE(c.verification_status, 'PENDING') NOT IN ('VERIFIED', 'REJECTED')",
    ]
    params: List[Any] = []
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        clauses.append(
            "(LOWER(c.reference) LIKE ? OR LOWER(COALESCE(u.name, c.applicant_name, '')) LIKE ? "
            "OR LOWER(c.category) LIKE ? OR LOWER(c.location) LIKE ?)"
        )
        params.extend([needle, needle, needle, needle])
    return _complaint_rows("WHERE " + " AND ".join(clauses), tuple(params))


def get_complaints_ready_for_fir(search: Optional[str] = None) -> List[Dict[str, Any]]:
    """Verified complaints that have not yet been converted into an FIR."""
    clauses = ["c.fir_id IS NULL", "c.verification_status = 'VERIFIED'"]
    params: List[Any] = []
    if search and search.strip():
        needle = f"%{search.strip().lower()}%"
        clauses.append(
            "(LOWER(c.reference) LIKE ? OR LOWER(COALESCE(u.name, c.applicant_name, '')) LIKE ? "
            "OR LOWER(c.category) LIKE ?)"
        )
        params.extend([needle, needle, needle])
    rows = _complaint_rows("WHERE " + " AND ".join(clauses), tuple(params))
    return rows


def get_complaint_for_verification(complaint_id: str) -> Optional[Dict[str, Any]]:
    rows = _complaint_rows("WHERE c.id = ? OR c.reference = ?", (complaint_id, complaint_id), limit=1)
    return rows[0] if rows else None


def get_complaint_verification_events(complaint_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM complaint_verification_events
        WHERE complaint_id = ?
        ORDER BY created_at ASC
    """, (complaint_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def record_complaint_verification_action(
    complaint_id: str,
    actor_user: Dict[str, Any],
    action: str,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """Persist one verification decision atomically and notify the citizen."""
    role = (actor_user or {}).get('role')
    if role not in REVIEWER_ROLES:
        raise PermissionError('Only Verification Officers or Administrators may verify complaints.')

    action = (action or '').upper()
    if action not in ('START_REVIEW', 'VERIFY', 'REJECT', 'REQUEST_INFO', 'REMARK'):
        raise ValueError('Unknown complaint verification action.')

    remarks = (remarks or '').strip()
    if action in ('REJECT', 'REQUEST_INFO', 'REMARK') and not remarks:
        raise ValueError('Remarks are required for this action.')

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError('Complaint not found.')

    complaint = dict(row)
    status_from = complaint.get('status') or 'SUBMITTED'
    verification_from = complaint.get('verification_status') or 'PENDING'

    if complaint.get('fir_id') and action != 'REMARK':
        conn.close()
        raise ValueError('An FIR has already been registered for this complaint.')

    if status_from in ('REJECTED', 'CLOSED') and action != 'REMARK':
        conn.close()
        raise ValueError(f'This complaint is already {status_from.lower()} and cannot be changed.')

    status_to = status_from
    verification_to = verification_from
    if action == 'START_REVIEW':
        status_to, verification_to = 'UNDER_REVIEW', 'UNDER_REVIEW'
    elif action == 'VERIFY':
        status_to, verification_to = 'VERIFIED', 'VERIFIED'
    elif action == 'REJECT':
        status_to, verification_to = 'REJECTED', 'REJECTED'
    elif action == 'REQUEST_INFO':
        status_to, verification_to = 'ADDITIONAL_INFO_REQUIRED', 'ADDITIONAL_INFO_REQUIRED'

    actor_name = actor_user.get('name') or 'Verification Officer'
    actor_badge = actor_user.get('badge_number') or 'N/A'
    now = _now()

    if action == 'REMARK':
        cursor.execute("""
            UPDATE complaints
            SET verification_remarks = ?, updated_at = ?
            WHERE id = ?
        """, (remarks, now, complaint_id))
    else:
        cursor.execute("""
            UPDATE complaints
            SET status = ?, verification_status = ?, verification_remarks = ?,
                verified_by = ?, verified_by_name = ?, verified_at = ?,
                rejection_reason = CASE WHEN ? = 'REJECTED' THEN ? ELSE rejection_reason END,
                updated_at = ?
            WHERE id = ?
        """, (
            status_to, verification_to, remarks or complaint.get('verification_remarks'),
            actor_user.get('id'), actor_name, now,
            status_to, remarks or complaint.get('rejection_reason') or '',
            now, complaint_id,
        ))

    event_action = {
        'START_REVIEW': 'REVIEW_STARTED',
        'VERIFY': 'VERIFIED',
        'REJECT': 'REJECTED',
        'REQUEST_INFO': 'ADDITIONAL_INFO_REQUESTED',
        'REMARK': 'REMARK',
    }[action]
    cursor.execute("""
        INSERT INTO complaint_verification_events (
            id, complaint_id, action, status_from, status_to, remarks,
            actor_id, actor_name, actor_role, actor_badge, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        f"cve-{uuid.uuid4().hex[:12]}", complaint_id, event_action,
        status_from, status_to, remarks or None,
        actor_user.get('id'), actor_name, role, actor_badge, now,
    ))
    conn.commit()

    cursor.execute("""
        SELECT c.*, u.name AS citizen_name, u.phone AS citizen_phone,
               f.fir_number AS fir_number
        FROM complaints c
        LEFT JOIN users u ON c.citizen_id = u.id
        LEFT JOIN firs f ON c.fir_id = f.id
        WHERE c.id = ?
    """, (complaint_id,))
    updated = dict(cursor.fetchone())
    conn.close()

    if action != 'REMARK':
        _notify_citizen_complaint_action(updated, action, remarks, event_action, now)

    publish({
        'type': 'COMPLAINT_VERIFICATION_UPDATED',
        'complaint_id': complaint_id,
        'reference': complaint.get('reference'),
        'citizen_id': complaint.get('citizen_id'),
        'status': status_to,
        'verification_status': verification_to,
        'action': event_action,
        'timestamp': now,
    })
    publish({
        'type': 'COMPLAINT_UPDATED',
        'complaint_id': complaint_id,
        'citizen_id': complaint.get('citizen_id'),
        'status': status_to,
        'verification_status': verification_to,
    })
    return updated


def _notify_citizen_complaint_action(complaint: Dict[str, Any], action: str, remarks: str,
                                     event_action: str, now: str) -> None:
    from backend.services.notification_service import create_notification

    reference = complaint.get('reference') or complaint.get('id')
    messages = {
        'START_REVIEW': (
            'Complaint Under Verification',
            f"Your complaint {reference} is now under verification by the police department.",
            'COMPLAINT_UPDATE',
            'INFO',
        ),
        'VERIFY': (
            'Complaint Verified',
            f"Your complaint {reference} has been verified and forwarded for official FIR registration.",
            'COMPLAINT_VERIFIED',
            'SUCCESS',
        ),
        'REJECT': (
            'Complaint Rejected',
            f"Your complaint {reference} was rejected after verification. Reason: {remarks}",
            'COMPLAINT_REJECTED',
            'ALERT',
        ),
        'REQUEST_INFO': (
            'Additional Information Required',
            f"Additional information is required for complaint {reference}. Officer remarks: {remarks}",
            'ADDITIONAL_INFO',
            'WARNING',
        ),
    }
    title, message, notif_type, severity = messages[action]
    create_notification(
        user_id=complaint['citizen_id'],
        complaint_id=complaint['id'],
        title=title,
        message=message,
        notification_type=notif_type,
        severity=severity,
        event_id=f"complaint-{event_action.lower()}-{complaint['id']}-{now}",
    )


def get_dashboard_stats() -> Dict[str, int]:
    """Every dashboard figure is a direct aggregate of persisted records."""
    conn = get_db_connection()
    cursor = conn.cursor()

    def scalar(query: str, params: tuple = ()) -> int:
        cursor.execute(query, params)
        row = cursor.fetchone()
        return int(row[0] or 0) if row else 0

    stats = {
        'total_citizen_registrations': scalar(
            "SELECT COUNT(*) FROM users WHERE role = 'CITIZEN'"
        ),
        'pending_citizen_verifications': scalar("""
            SELECT COUNT(*) FROM citizen_applications
            WHERE status IN ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED')
        """),
        'verified_citizens': scalar(
            "SELECT COUNT(*) FROM users WHERE role = 'CITIZEN' AND status = 'ACTIVE'"
        ),
        'pending_fir_verifications': scalar("""
            SELECT COUNT(*) FROM complaints
            WHERE fir_id IS NULL
              AND status NOT IN ('REJECTED', 'CLOSED', 'RESOLVED')
              AND COALESCE(verification_status, 'PENDING') IN ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED')
        """),
        'verified_firs': scalar("SELECT COUNT(*) FROM firs WHERE status NOT IN ('REJECTED', 'NEEDS_CORRECTION')"),
        'cases_awaiting_assignment': scalar("""
            SELECT COUNT(*) FROM firs
            WHERE (assigned_officer_id IS NULL OR assigned_officer_id = '')
              AND status NOT IN ('CLOSED', 'REJECTED', 'NEEDS_CORRECTION')
        """),
        'recently_assigned_cases': scalar("""
            SELECT COUNT(DISTINCT oa.fir_id) FROM officer_assignments oa
            WHERE oa.status = 'ACTIVE'
        """),
        'awaiting_fir_registration': scalar(
            "SELECT COUNT(*) FROM complaints WHERE fir_id IS NULL AND verification_status = 'VERIFIED'"
        ),
        'fir_documents_generated': scalar(
            "SELECT COUNT(*) FROM fir_documents WHERE is_current = 1"
        ),
    }
    conn.close()
    return stats


def get_recent_assignments(limit: int = 5) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT oa.id, oa.fir_id, oa.officer_id, oa.assigned_at, oa.status AS assignment_status,
               f.fir_number, f.incident_type, f.police_station,
               u.name AS officer_name, u.rank AS officer_rank, u.station AS officer_station,
               u.badge_number AS officer_badge, c.reference AS complaint_reference
        FROM officer_assignments oa
        JOIN firs f ON oa.fir_id = f.id
        LEFT JOIN users u ON oa.officer_id = u.id
        LEFT JOIN complaints c ON f.complaint_id = c.id
        WHERE oa.assigned_at = (
            SELECT MAX(oa2.assigned_at) FROM officer_assignments oa2 WHERE oa2.fir_id = oa.fir_id
        )
        ORDER BY oa.assigned_at DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_recent_activity(limit: int = 8) -> List[Dict[str, Any]]:
    """Merge citizen application events, complaint verification events, and FIR activity."""
    conn = get_db_connection()
    cursor = conn.cursor()
    items: List[Dict[str, Any]] = []

    cursor.execute("""
        SELECT e.action, e.status_from, e.status_to, e.remarks, e.actor_name, e.actor_role,
               e.actor_badge, e.created_at, a.reference AS reference, a.full_name AS subject,
               a.id AS application_id
        FROM citizen_application_events e
        JOIN citizen_applications a ON e.application_id = a.id
        ORDER BY e.created_at DESC LIMIT ?
    """, (limit,))
    for row in cursor.fetchall():
        item = dict(row)
        item.update({
            'kind': 'CITIZEN_APPLICATION',
            'title': action_label(item['action']),
            'target': f"/verification/citizens/{item['application_id']}",
        })
        items.append(item)

    cursor.execute("""
        SELECT e.action, e.status_from, e.status_to, e.remarks, e.actor_name, e.actor_role,
               e.actor_badge, e.created_at, c.reference AS reference,
               COALESCE(u.name, c.applicant_name, 'Citizen') AS subject, c.id AS complaint_id
        FROM complaint_verification_events e
        JOIN complaints c ON e.complaint_id = c.id
        LEFT JOIN users u ON c.citizen_id = u.id
        ORDER BY e.created_at DESC LIMIT ?
    """, (limit,))
    for row in cursor.fetchall():
        item = dict(row)
        item.update({
            'kind': 'COMPLAINT',
            'title': action_label(item['action']),
            'target': f"/verification/complaint/{item['complaint_id']}",
        })
        items.append(item)

    cursor.execute("""
        SELECT action_type AS action, details AS remarks, user_name AS actor_name,
               user_role AS actor_role, timestamp AS created_at, fir_number AS reference,
               fir_number AS subject, fir_id
        FROM officer_activity_logs
        WHERE action_type IN ('FIR_REGISTERED', 'OFFICER_ASSIGNMENT', 'FIR_VERIFIED', 'FIR_DOCUMENT_GENERATED')
        ORDER BY timestamp DESC LIMIT ?
    """, (limit,))
    for row in cursor.fetchall():
        item = dict(row)
        item.update({
            'kind': 'FIR',
            'title': action_label(item['action']) if item['action'] in ACTION_LABELS else item['action'].replace('_', ' ').title(),
            'target': f"/verification/fir/{item['fir_id']}",
        })
        items.append(item)

    conn.close()
    items.sort(key=lambda entry: str(entry.get('created_at') or ''), reverse=True)
    return items[:limit]


def get_verification_history(limit: int = 200) -> List[Dict[str, Any]]:
    """Full append-only verification history across citizen and complaint desks."""
    conn = get_db_connection()
    cursor = conn.cursor()
    items: List[Dict[str, Any]] = []

    cursor.execute("""
        SELECT e.action, e.status_from, e.status_to, e.remarks, e.actor_name, e.actor_role,
               e.actor_badge, e.created_at, a.reference AS reference, a.full_name AS subject,
               a.id AS application_id, c.status AS current_status
        FROM citizen_application_events e
        JOIN citizen_applications a ON e.application_id = a.id
        LEFT JOIN citizen_applications c ON c.id = e.application_id
        ORDER BY e.created_at DESC LIMIT ?
    """, (limit,))
    for row in cursor.fetchall():
        item = dict(row)
        item.update({
            'verification_type': 'Citizen Registration',
            'decision': item['status_to'] or item['action'],
            'target': f"/verification/citizens/{item['application_id']}",
        })
        items.append(item)

    cursor.execute("""
        SELECT e.action, e.status_from, e.status_to, e.remarks, e.actor_name, e.actor_role,
               e.actor_badge, e.created_at, c.reference AS reference,
               COALESCE(u.name, c.applicant_name, 'Citizen') AS subject,
               c.id AS complaint_id, c.status AS current_status
        FROM complaint_verification_events e
        JOIN complaints c ON e.complaint_id = c.id
        LEFT JOIN users u ON c.citizen_id = u.id
        ORDER BY e.created_at DESC LIMIT ?
    """, (limit,))
    for row in cursor.fetchall():
        item = dict(row)
        item.update({
            'verification_type': 'Complaint Verification',
            'decision': item['status_to'] or item['action'],
            'target': f"/verification/complaint/{item['complaint_id']}",
        })
        items.append(item)

    conn.close()
    items.sort(key=lambda entry: str(entry.get('created_at') or ''), reverse=True)
    return items[:limit]


def get_officer_assignment_history(fir_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT oa.*, u.name AS officer_name, u.rank AS officer_rank,
               u.badge_number AS officer_badge, u.station AS officer_station,
               a.name AS assigned_by_name, a.role AS assigned_by_role
        FROM officer_assignments oa
        LEFT JOIN users u ON oa.officer_id = u.id
        LEFT JOIN users a ON oa.assigned_by = a.id
        WHERE oa.fir_id = ?
        ORDER BY oa.assigned_at ASC
    """, (fir_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_active_police_officers() -> List[Dict[str, Any]]:
    """Populate assignment dropdowns strictly from active OFFICER accounts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, email, phone, badge_number, rank, station, district
        FROM users
        WHERE role = 'OFFICER' AND status = 'ACTIVE'
        ORDER BY name ASC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

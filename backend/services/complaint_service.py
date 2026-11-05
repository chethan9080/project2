"""
Complaint Service — Database-backed citizen complaint management.
Complaints are stored in SQLite, not in-memory.

A complaint is the pre-FIR record created by the citizen filing wizard. It owns
its own reference number and becomes an official FIR only when authorized
police personnel register it through ``create_fir_from_complaint``.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection

COMPLAINT_CATEGORIES = [
    'Theft',
    'Missing Person',
    'Cybercrime',
    'Harassment',
    'Fraud',
    'Assault',
    'Property Dispute',
    'Other',
]

# Configurable placeholders until real station records are configured.
POLICE_STATION_OPTIONS = [
    'Police Station A',
    'Police Station B',
    'Police Station C',
    'Police Station D',
]

STATUS_LABELS = {
    'SUBMITTED': 'Pending Verification',
    'ASSIGNED': 'Under Review',
    'UNDER_REVIEW': 'Under Verification',
    'VERIFIED': 'Verified – Awaiting FIR Registration',
    'ADDITIONAL_INFO_REQUIRED': 'Additional Information Required',
    'INVESTIGATION': 'Under Investigation',
    'FIR_CREATED': 'FIR Registered',
    'RESOLVED': 'Completed',
    'CLOSED': 'Closed',
    'REJECTED': 'Rejected',
}

# Ordered citizen-facing buckets used by the My Complaints page.
STATUS_GROUPS = [
    ('pending', 'Pending Verification', ['SUBMITTED']),
    ('review', 'Under Review', ['ASSIGNED', 'UNDER_REVIEW']),
    ('verified', 'Verified – Awaiting FIR', ['VERIFIED']),
    ('info', 'Additional Information Required', ['ADDITIONAL_INFO_REQUIRED']),
    ('fir', 'FIR Registered', ['FIR_CREATED']),
    ('investigation', 'Under Investigation', ['INVESTIGATION']),
    ('closed', 'Completed / Closed', ['RESOLVED', 'CLOSED']),
    ('rejected', 'Rejected', ['REJECTED']),
]

_STATUS_GROUP_LOOKUP = {
    status: (key, label)
    for key, label, statuses in STATUS_GROUPS
    for status in statuses
}


def complaint_status_label(status: Optional[str]) -> str:
    return STATUS_LABELS.get(status or '', (status or 'Unknown').replace('_', ' ').title())


def complaint_status_group(status: Optional[str]) -> tuple[str, str]:
    return _STATUS_GROUP_LOOKUP.get(status or '', ('pending', 'Pending Verification'))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_evidence(evidence_files: Any) -> str:
    if evidence_files is None:
        return '[]'
    if isinstance(evidence_files, str):
        try:
            json.loads(evidence_files)
            return evidence_files
        except (ValueError, TypeError):
            return '[]'
    return json.dumps(evidence_files)


def _compose_location(data: Dict[str, Any]) -> str:
    explicit = (data.get('location') or '').strip()
    if explicit:
        return explicit
    parts = [data.get('area'), data.get('landmark'), data.get('district'), data.get('state')]
    return ', '.join(str(p).strip() for p in parts if p and str(p).strip())


def _notify_citizen(complaint: Dict[str, Any], title: str, message: str,
                    notification_type: str, severity: str, event_key: str) -> None:
    """Send a citizen notification tied to a real complaint database event."""
    try:
        from backend.services.notification_service import create_notification
        create_notification(
            user_id=complaint['citizen_id'],
            complaint_id=complaint.get('id'),
            title=title,
            message=message,
            notification_type=notification_type,
            severity=severity,
            event_id=f"{event_key}-{complaint.get('id')}",
        )
    except Exception as exc:  # notifications must never block the workflow
        print(f"Complaint notification error: {exc}")


def _publish_update(complaint: Dict[str, Any], status: str, extra: Optional[Dict] = None) -> None:
    try:
        from backend.services.realtime_events import publish
        event = {
            'type': 'COMPLAINT_UPDATED',
            'citizen_id': complaint.get('citizen_id'),
            'complaint_id': complaint.get('id'),
            'status': status,
        }
        if extra:
            event.update(extra)
        publish(event)
    except Exception:
        pass


def _generate_reference(complaint_id: str) -> str:
    """Generate a stable CMP-XXXXXXXX reference from the complaint UUID."""
    h = hashlib.sha256(complaint_id.encode()).hexdigest()[:8].upper()
    return f"CMP-{h}"


def create_complaint(citizen_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create and persist a new complaint to the database.
    Returns the created complaint dict including the stable reference number.
    """
    from backend.services.auth_service import assert_active_citizen, get_user_by_id
    citizen = get_user_by_id(citizen_id)
    assert_active_citizen(citizen)

    complaint_id = f"cmp-{uuid.uuid4().hex[:12]}"
    reference = _generate_reference(complaint_id)
    now = _now()

    category = (data.get('category') or 'Other').strip()
    title = (data.get('title') or '').strip() or f"{category} Complaint"
    description = (data.get('description') or '').strip()
    location = _compose_location(data)
    applicant_name = (data.get('applicant_name') or (citizen or {}).get('name') or '').strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO complaints (
            id, reference, citizen_id, applicant_name, category, title, description,
            location, landmark, area, district, state, police_station,
            incident_date, incident_time, evidence_files, submitted_at, updated_at, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED')
    """, (
        complaint_id, reference, citizen_id, applicant_name, category, title,
        description, location, data.get('landmark'), data.get('area'),
        data.get('district'), data.get('state'), data.get('police_station'),
        data.get('incident_date'), data.get('incident_time'),
        _normalize_evidence(data.get('evidence_files')), now, now,
    ))
    conn.commit()
    conn.close()

    complaint = get_complaint_by_id(complaint_id, citizen_id=citizen_id)
    if complaint:
        _notify_citizen(
            complaint,
            title="Complaint Submitted Successfully",
            message=(
                f"Your complaint has been recorded with reference {reference}. "
                "It is now pending verification by the police department."
            ),
            notification_type="COMPLAINT_SUBMISSION",
            severity="SUCCESS",
            event_key="complaint-submitted",
        )
        _notify_verification_officers(complaint)
        _publish_update(complaint, 'SUBMITTED')
    return complaint


def _notify_verification_officers(complaint: Dict[str, Any]) -> None:
    """Alert every active Verification Officer about a newly submitted complaint."""
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
                complaint_id=complaint.get('id'),
                title="New Complaint Awaiting Verification",
                message=(
                    f"{complaint.get('applicant_name') or complaint.get('citizen_name') or 'A citizen'} "
                    f"submitted complaint {complaint.get('reference')} "
                    f"({complaint.get('category')})."
                ),
                notification_type="COMPLAINT_SUBMITTED",
                severity="INFO",
                event_id=f"complaint-verification-{complaint.get('id')}",
            )
    except Exception as exc:
        print(f"Verification officer notification error: {exc}")


def get_complaint_by_id(complaint_id: str, citizen_id: Optional[str] = None, actor_user: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
    """Fetch a single complaint. Enforces ownership for citizens."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name_from_user, o.badge_number AS officer_badge,
               o.rank AS officer_rank, o.station AS officer_station, o.phone AS officer_phone,
               f.fir_number AS fir_number, f.status AS fir_status,
               f.assigned_officer_id AS fir_officer_id
        FROM complaints c
        LEFT JOIN users u ON c.citizen_id = u.id
        LEFT JOIN users o ON c.assigned_officer_id = o.id
        LEFT JOIN firs f ON c.fir_id = f.id
        WHERE c.id = ? OR c.reference = ?
    """, (complaint_id, complaint_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    # Authorization: citizen can only see their own
    if citizen_id and r.get('citizen_id') != citizen_id:
        return None
    if actor_user and actor_user.get('role') == 'CITIZEN' and r.get('citizen_id') != actor_user.get('id'):
        return None
    if actor_user and actor_user.get('role') == 'OFFICER' and actor_user.get('id') not in (
        r.get('assigned_officer_id'), r.get('fir_officer_id')
    ):
        return None
    # Internal verification remarks stay inside the verification bureau.
    r.pop('verification_remarks', None)
    return r


def get_complaints_for_citizen(citizen_id: str) -> List[Dict[str, Any]]:
    """Return all complaints for a specific citizen."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*,
               o.name AS officer_name_from_user, o.badge_number AS officer_badge,
               f.fir_number AS fir_number, f.status AS fir_status
        FROM complaints c
        LEFT JOIN users o ON c.assigned_officer_id = o.id
        LEFT JOIN firs f ON c.fir_id = f.id
        WHERE c.citizen_id = ?
        ORDER BY c.submitted_at DESC
    """, (citizen_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for row in rows:
        row.pop('verification_remarks', None)
    return rows


def get_complaints_for_officer(officer_id: str) -> List[Dict[str, Any]]:
    """Return all complaints assigned to this officer."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*,
               u.name AS citizen_name, u.phone AS citizen_phone,
               f.fir_number AS fir_number, f.status AS fir_status
        FROM complaints c
        LEFT JOIN users u ON c.citizen_id = u.id
        LEFT JOIN firs f ON c.fir_id = f.id
        WHERE c.assigned_officer_id = ?
        ORDER BY c.submitted_at DESC
    """, (officer_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_all_complaints(actor_user: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Return all complaints. For officers/admins only."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.*,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name_from_user, o.badge_number AS officer_badge,
               o.rank AS officer_rank, o.station AS officer_station, o.phone AS officer_phone,
               f.fir_number AS fir_number, f.status AS fir_status
        FROM complaints c
        LEFT JOIN users u ON c.citizen_id = u.id
        LEFT JOIN users o ON c.assigned_officer_id = o.id
        LEFT JOIN firs f ON c.fir_id = f.id
        ORDER BY c.submitted_at DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def attach_complaint_evidence(complaint_id: str, evidence_metadata: List[Dict[str, Any]]) -> None:
    """Persist evidence metadata after files have been moved into private storage."""
    if not evidence_metadata:
        return
    conn = get_db_connection()
    conn.execute(
        "UPDATE complaints SET evidence_files = ?, updated_at = ? WHERE id = ?",
        (json.dumps(evidence_metadata), _now(), complaint_id),
    )
    conn.commit()
    conn.close()


def assign_officer_to_complaint(complaint_id: str, officer_id: str, actor_user: Dict[str, Any]) -> bool:
    """
    Assign an officer to a complaint and persist to database.
    Only ADMIN or authorized OFFICER can assign.
    """
    if not actor_user or actor_user.get('role') not in ('ADMIN', 'OFFICER', 'VERIFICATION_OFFICER'):
        raise PermissionError('Only administrators and officers can assign officers to complaints.')

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get officer details
    cursor.execute(
        "SELECT id, name, badge_number, rank, station, phone FROM users "
        "WHERE id = ? AND role = 'OFFICER' AND status = 'ACTIVE'",
        (officer_id,),
    )
    officer = cursor.fetchone()
    if not officer:
        conn.close()
        return False

    now = _now()
    cursor.execute("""
        UPDATE complaints
        SET assigned_officer_id = ?,
            assigned_officer_name = ?,
            assigned_at = ?,
            status = CASE WHEN status IN ('VERIFIED', 'FIR_CREATED', 'INVESTIGATION') THEN status ELSE 'ASSIGNED' END,
            updated_at = ?
        WHERE id = ?
    """, (officer_id, officer['name'], now, now, complaint_id))

    cursor.execute("""
        INSERT INTO complaint_verification_events (
            id, complaint_id, action, status_from, status_to, remarks,
            actor_id, actor_name, actor_role, actor_badge, created_at
        ) VALUES (?, ?, 'OFFICER_ASSIGNED', NULL, NULL, ?, ?, ?, ?, ?, ?)
    """, (
        f"cve-{uuid.uuid4().hex[:12]}", complaint_id,
        f"Assigned {officer['rank'] or 'Officer'} {officer['name']} "
        f"({officer['badge_number'] or 'N/A'}, {officer['station'] or 'Station not recorded'}).",
        actor_user.get('id'), actor_user.get('name'), actor_user.get('role'),
        actor_user.get('badge_number') or 'N/A', now,
    ))
    conn.commit()
    conn.close()

    complaint = get_complaint_by_id(complaint_id)
    if complaint:
        _notify_citizen(
            complaint,
            title="Investigating Officer Assigned",
            message=(
                f"Officer {officer['name']} ({officer['rank'] or 'Investigating Officer'}, "
                f"{officer['station'] or 'Police Department'}) has been assigned to your complaint "
                f"{complaint.get('reference')}. Chat is now available for this case."
            ),
            notification_type="OFFICER_ASSIGNED",
            severity="SUCCESS",
            event_key=f"complaint-officer-assigned-{officer_id}",
        )
        try:
            from backend.services.notification_service import create_notification
            create_notification(
                user_id=officer_id,
                complaint_id=complaint_id,
                title="New Complaint Assigned",
                message=(
                    f"Complaint {complaint.get('reference')} "
                    f"({complaint.get('category')}) has been assigned to you. "
                    "Open your portal to review the case and contact the complainant."
                ),
                notification_type="OFFICER_ASSIGNMENT",
                severity="INFO",
                event_id=f"complaint-officer-assigned-to-officer-{complaint_id}-{officer_id}",
            )
        except Exception as exc:
            print(f"Officer assignment notification error: {exc}")
        _publish_update(complaint, complaint.get('status') or 'ASSIGNED', {'officer_id': officer_id})
    return True


def update_complaint_status(complaint_id: str, new_status: str, actor_user: Dict[str, Any],
                            reason: Optional[str] = None) -> bool:
    """Update complaint status. Officers/admins only. Notifies the owning citizen."""
    if not actor_user or actor_user.get('role') not in ('ADMIN', 'OFFICER', 'VERIFICATION_OFFICER'):
        raise PermissionError('Only officers and administrators can update complaint status.')
    valid = (
        'SUBMITTED', 'ASSIGNED', 'UNDER_REVIEW', 'VERIFIED', 'ADDITIONAL_INFO_REQUIRED',
        'INVESTIGATION', 'RESOLVED', 'CLOSED', 'FIR_CREATED', 'REJECTED',
    )
    if new_status not in valid:
        raise ValueError(f'Invalid status: {new_status}')

    complaint = get_complaint_by_id(complaint_id)
    if not complaint:
        return False

    conn = get_db_connection()
    now = _now()
    if new_status == 'REJECTED' and reason:
        conn.execute(
            "UPDATE complaints SET status = ?, rejection_reason = ?, updated_at = ? WHERE id = ?",
            (new_status, reason.strip(), now, complaint_id),
        )
    else:
        conn.execute(
            "UPDATE complaints SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, now, complaint_id),
        )
    conn.commit()
    conn.close()

    messages = {
        'UNDER_REVIEW': ("Complaint Under Review", "Your complaint is being reviewed by the police department.", "COMPLAINT_UPDATE", "INFO"),
        'ASSIGNED': ("Complaint Under Review", "An officer is now reviewing your complaint.", "COMPLAINT_UPDATE", "SUCCESS"),
        'VERIFIED': ("Complaint Verified", "Your complaint has been verified and forwarded for official FIR registration.", "COMPLAINT_UPDATE", "SUCCESS"),
        'ADDITIONAL_INFO_REQUIRED': ("Additional Information Required", "The police need more information about your complaint. Please check the case details.", "ADDITIONAL_INFO", "WARNING"),
        'INVESTIGATION': ("Investigation Started", "Investigation has started on your complaint.", "COMPLAINT_UPDATE", "INFO"),
        'RESOLVED': ("Complaint Resolved", "Your complaint has been marked resolved.", "COMPLAINT_UPDATE", "SUCCESS"),
        'CLOSED': ("Complaint Closed", "Your complaint has been closed.", "COMPLAINT_UPDATE", "INFO"),
        'REJECTED': ("Complaint Rejected", reason or "Your complaint was rejected after review.", "COMPLAINT_UPDATE", "ALERT"),
    }
    if new_status in messages:
        title, message, notif_type, severity = messages[new_status]
        _notify_citizen(
            complaint,
            title=title,
            message=message,
            notification_type=notif_type,
            severity=severity,
            event_key=f"complaint-status-{new_status}-{now}",
        )
    _publish_update(complaint, new_status)
    return True


def get_complaint_stage_progress(complaint: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Build a citizen-facing verification timeline for a complaint that has not
    yet become an FIR. Every completed stage uses a real database timestamp.
    """
    status = complaint.get('status', 'SUBMITTED')
    submitted_at = str(complaint.get('submitted_at') or '')[:19].replace('T', ' ')
    updated_at = str(complaint.get('updated_at') or '')[:19].replace('T', ' ')
    rejected = status == 'REJECTED'
    under_review = status in ('UNDER_REVIEW', 'ASSIGNED')
    verified = status in ('VERIFIED', 'ASSIGNED', 'FIR_CREATED', 'INVESTIGATION', 'RESOLVED', 'CLOSED')
    needs_info = status == 'ADDITIONAL_INFO_REQUIRED'

    return [
        {
            'number': 1,
            'label': 'Complaint Submitted',
            'description': 'Your complaint was securely recorded and a reference number was issued.',
            'state': 'COMPLETED',
            'timestamp': submitted_at,
        },
        {
            'number': 2,
            'label': 'Verification Pending',
            'description': (
                'Additional information is required before verification can continue.'
                if needs_info else
                'The police department is checking your complaint before registration.'
            ),
            'state': 'WARNING' if (rejected or needs_info) else ('COMPLETED' if verified or under_review else 'CURRENT'),
            'timestamp': updated_at if (rejected or needs_info or verified or under_review) else '',
        },
        {
            'number': 3,
            'label': 'Complaint Verified',
            'description': 'Your complaint was verified by authorized police personnel.',
            'state': 'COMPLETED' if verified else ('CURRENT' if under_review else 'UPCOMING'),
            'timestamp': updated_at if verified else '',
        },
        {
            'number': 4,
            'label': 'FIR Registered',
            'description': 'An official FIR number will be issued once registration is complete.',
            'state': 'COMPLETED' if complaint.get('fir_id') else 'UPCOMING',
            'timestamp': '',
        },
        {
            'number': 5,
            'label': 'Investigation & Resolution',
            'description': 'Investigating officer assignment and case progress will appear here.',
            'state': 'COMPLETED' if status in ('RESOLVED', 'CLOSED') else 'UPCOMING',
            'timestamp': updated_at if status in ('RESOLVED', 'CLOSED') else '',
        },
    ]


# Legacy compatibility shims (used by existing pages)
def get_complaints() -> List[Dict]:
    """Backward compat: return all complaints."""
    return get_all_complaints()


def get_complaint_by_id_legacy(complaint_id: str) -> Optional[Dict]:
    """Backward compat wrapper."""
    return get_complaint_by_id(complaint_id)


def filter_complaints(query: str = '', status: str = 'All', category: str = 'All', priority: str = 'All') -> List[Dict]:
    """Filter complaints — officers/admins only view."""
    records = get_all_complaints()
    query = query.lower().strip()
    return [
        r for r in records
        if (not query or query in ' '.join(str(v) for v in r.values()).lower())
        and (status == 'All' or r.get('status') == status)
        and (category == 'All' or r.get('category') == category)
    ]

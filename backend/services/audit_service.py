"""
Admin & Authorized Officer FIR Tampering & Audit Service.
Authorized access: ADMIN role OR senior police officers (Inspector and above).
All functions enforce role-based access at the service layer.
"""
import json
from typing import Any, Dict, List, Optional
from backend.services.db import get_db_connection

# Ranks allowed to access the tampering audit trail
AUTHORIZED_OFFICER_RANKS = (
    'police inspector',
    'inspector',
    'circle inspector',
    'station house officer',
    'sho',
    'inspector general',
    'deputy superintendent',
    'superintendent',
)


def is_authorized_for_audit(actor_user: Dict[str, Any]) -> bool:
    """Return True if user is ADMIN or a senior-ranked police officer."""
    if not actor_user:
        return False
    if actor_user.get('role') == 'ADMIN':
        return True
    if actor_user.get('role') == 'OFFICER':
        rank = (actor_user.get('rank') or '').lower()
        return any(r in rank for r in AUTHORIZED_OFFICER_RANKS)
    return False


def require_audit_access(actor_user: Dict[str, Any]) -> None:
    """Raise PermissionError if user is not authorized for audit trail."""
    if not is_authorized_for_audit(actor_user):
        raise PermissionError(
            'Forbidden: Only Administrators and authorized senior police officers '
            '(Inspector and above) can access the FIR Tampering Audit Trail.'
        )


def get_all_audit_events(
    actor_user: Dict[str, Any],
    search_fir: str = '',
    search_officer_id: str = '',
    search_officer_name: str = '',
    filter_action: str = '',
    filter_date_from: str = '',
    filter_date_to: str = '',
    sort_order: str = 'DESC'
) -> List[Dict[str, Any]]:
    """Get all FIR change audit events with citizen information. Authorized officers and admins only."""
    require_audit_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT e.*, 
               f.fir_number, f.incident_type, f.police_station, f.status AS fir_status, f.citizen_id,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
        FROM fir_change_events e
        LEFT JOIN firs f ON e.fir_id = f.id
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE 1=1
    """
    params = []

    if search_fir.strip():
        query += " AND (LOWER(f.fir_number) LIKE ? OR LOWER(e.fir_id) LIKE ?)"
        like = f"%{search_fir.strip().lower()}%"
        params.extend([like, like])

    if search_officer_id.strip():
        query += " AND LOWER(e.actor_badge) LIKE ?"
        params.append(f"%{search_officer_id.strip().lower()}%")

    if search_officer_name.strip():
        query += " AND LOWER(e.actor_name) LIKE ?"
        params.append(f"%{search_officer_name.strip().lower()}%")

    if filter_action.strip():
        query += " AND e.event_type = ?"
        params.append(filter_action.strip())

    if filter_date_from.strip():
        query += " AND e.timestamp >= ?"
        params.append(filter_date_from.strip())

    if filter_date_to.strip():
        query += " AND e.timestamp <= ?"
        params.append(filter_date_to.strip())

    order = 'DESC' if sort_order == 'DESC' else 'ASC'
    query += f" ORDER BY e.timestamp {order}"

    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        try:
            r['changed_fields'] = json.loads(r.get('changed_fields_json') or '[]')
            r['old_values'] = json.loads(r.get('old_values_json') or '{}')
            r['new_values'] = json.loads(r.get('new_values_json') or '{}')
        except Exception:
            r['changed_fields'] = []
            r['old_values'] = {}
            r['new_values'] = {}
    return rows


def get_audit_event_detail(event_id: str, actor_user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Get full detail of a single audit event including citizen information. Authorized officers and admins only."""
    require_audit_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, 
               f.fir_number, f.incident_type, f.police_station, f.status AS fir_status,
               f.incident_date, f.incident_location, f.citizen_id,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
        FROM fir_change_events e
        LEFT JOIN firs f ON e.fir_id = f.id
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE e.id = ? OR e.event_number = ?
    """, (event_id, event_id))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    r = dict(row)
    try:
        r['changed_fields'] = json.loads(r.get('changed_fields_json') or '[]')
        r['old_values'] = json.loads(r.get('old_values_json') or '{}')
        r['new_values'] = json.loads(r.get('new_values_json') or '{}')
    except Exception:
        r['changed_fields'] = []
        r['old_values'] = {}
        r['new_values'] = {}
    return r


def get_audit_events_for_fir(fir_id: str, actor_user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get all audit events for a specific FIR. Authorized officers and admins only."""
    require_audit_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, f.fir_number
        FROM fir_change_events e
        LEFT JOIN firs f ON e.fir_id = f.id
        WHERE e.fir_id = ? OR f.fir_number = ?
        ORDER BY e.timestamp ASC
    """, (fir_id, fir_id))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        try:
            r['changed_fields'] = json.loads(r.get('changed_fields_json') or '[]')
            r['old_values'] = json.loads(r.get('old_values_json') or '{}')
            r['new_values'] = json.loads(r.get('new_values_json') or '{}')
        except Exception:
            r['changed_fields'] = []
            r['old_values'] = {}
            r['new_values'] = {}
    return rows


def get_audit_dashboard_stats(actor_user: Dict[str, Any]) -> Dict[str, Any]:
    """Get stats for the audit dashboard card. Authorized officers and admins only."""
    require_audit_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS cnt FROM fir_change_events")
    total = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) AS cnt FROM fir_change_events WHERE timestamp >= datetime('now', '-1 day')")
    recent = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(DISTINCT actor_id) AS cnt FROM fir_change_events")
    officers_count = cursor.fetchone()['cnt']

    cursor.execute("""
        SELECT e.event_number, e.actor_name, e.actor_badge, e.timestamp, f.fir_number
        FROM fir_change_events e
        LEFT JOIN firs f ON e.fir_id = f.id
        ORDER BY e.timestamp DESC LIMIT 5
    """)
    recent_events = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        'total_events': total,
        'recent_24h': recent,
        'officers_count': officers_count,
        'recent_events': recent_events
    }

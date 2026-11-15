"""
Authorized Officer Data Access Layer
Handles FIR integrity monitoring, version comparison, audit logs, and officer management
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from backend.services.db import get_db_connection
from backend.services.crypto_service import calculate_sha256, canonical_json
import json
import uuid


def get_integrity_dashboard_stats() -> Dict[str, Any]:
    """
    Get dashboard statistics for FIR integrity monitoring.
    
    Returns:
        Dictionary with dashboard metrics
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Total FIRs monitored
    cursor.execute("SELECT COUNT(*) FROM firs")
    total_firs = cursor.fetchone()[0]
    
    # FIRs with multiple versions (changed)
    cursor.execute("""
        SELECT COUNT(DISTINCT fir_id) 
        FROM fir_versions 
        WHERE version_number > 1
    """)
    firs_with_changes = cursor.fetchone()[0]
    
    # FIRs with no changes
    firs_no_changes = total_firs - firs_with_changes
    
    # Recent change events (last 24 hours)
    cursor.execute("""
        SELECT COUNT(*) 
        FROM fir_change_events 
        WHERE datetime(timestamp) > datetime('now', '-1 day')
    """)
    recent_changes_24h = cursor.fetchone()[0]
    
    # Total versions across all FIRs
    cursor.execute("SELECT COUNT(*) FROM fir_versions")
    total_versions = cursor.fetchone()[0]
    
    # Recent officer actions (last 7 days)
    cursor.execute("""
        SELECT 
            u.name,
            u.role,
            u.badge_number,
            COUNT(e.id) as action_count
        FROM fir_change_events e
        JOIN users u ON e.actor_id = u.id
        WHERE datetime(e.timestamp) > datetime('now', '-7 days')
        GROUP BY e.actor_id
        ORDER BY action_count DESC
        LIMIT 10
    """)
    
    recent_officers = []
    for row in cursor.fetchall():
        recent_officers.append({
            'officer_name': row[0],
            'role': row[1],
            'badge_number': row[2],
            'action_count': row[3]
        })
    
    # Latest integrity checks
    cursor.execute("""
        SELECT 
            v.fir_id,
            f.fir_number,
            v.version_number,
            v.current_hash,
            v.created_at,
            u.name as officer_name,
            u.role
        FROM fir_versions v
        JOIN firs f ON v.fir_id = f.id
        JOIN users u ON v.created_by = u.id
        ORDER BY v.created_at DESC
        LIMIT 10
    """)
    
    recent_checks = []
    for row in cursor.fetchall():
        recent_checks.append({
            'fir_id': row[0],
            'fir_number': row[1],
            'version': row[2],
            'hash': row[3][:16] + '...',  # Abbreviated
            'timestamp': row[4],
            'officer_name': row[5],
            'role': row[6]
        })
    
    # Alerts requiring attention (integrity issues, suspicious patterns)
    cursor.execute("""
        SELECT 
            e.fir_id,
            f.fir_number,
            e.event_type,
            e.actor_name,
            e.actor_role,
            e.timestamp,
            e.reason
        FROM fir_change_events e
        JOIN firs f ON e.fir_id = f.id
        WHERE e.event_type IN ('UNAUTHORIZED_MODIFICATION', 'SUSPICIOUS_EDIT')
           OR datetime(e.timestamp) > datetime('now', '-1 hour')
        ORDER BY e.timestamp DESC
        LIMIT 5
    """)
    
    alerts = []
    for row in cursor.fetchall():
        alerts.append({
            'fir_id': row[0],
            'fir_number': row[1],
            'event_type': row[2],
            'actor_name': row[3],
            'actor_role': row[4],
            'timestamp': row[5],
            'reason': row[6]
        })
    
    conn.close()
    
    return {
        'total_firs_monitored': total_firs,
        'firs_with_changes': firs_with_changes,
        'firs_no_changes': firs_no_changes,
        'recent_changes_24h': recent_changes_24h,
        'total_versions': total_versions,
        'recent_officer_actions': recent_officers,
        'recent_integrity_checks': recent_checks,
        'alerts': alerts,
        'last_updated': datetime.now().isoformat()
    }


def get_fir_comparison(fir_id: str, version1: int, version2: int) -> Dict[str, Any]:
    """
    Compare two versions of an FIR showing field-by-field differences.
    
    Args:
        fir_id: FIR identifier
        version1: First version number (usually older)
        version2: Second version number (usually newer)
    
    Returns:
        Detailed comparison with original vs current values
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get version snapshots
    cursor.execute("""
        SELECT 
            v.version_number,
            v.snapshot_json,
            v.current_hash,
            v.previous_hash,
            v.created_by,
            u.name,
            u.role,
            u.badge_number,
            v.created_at,
            v.change_reason
        FROM fir_versions v
        JOIN users u ON v.created_by = u.id
        WHERE v.fir_id = ? AND v.version_number IN (?, ?)
        ORDER BY v.version_number ASC
    """, (fir_id, version1, version2))
    
    rows = cursor.fetchall()
    
    if len(rows) < 2:
        conn.close()
        return {
            'error': 'One or both versions not found',
            'fir_id': fir_id,
            'requested_versions': [version1, version2],
            'found_count': len(rows)
        }
    
    # Parse version data
    v1 = {
        'version_number': rows[0][0],
        'data': json.loads(rows[0][1]),
        'hash': rows[0][2],
        'previous_hash': rows[0][3],
        'officer_id': rows[0][4],
        'officer_name': rows[0][5],
        'officer_role': rows[0][6],
        'badge_number': rows[0][7],
        'created_at': rows[0][8],
        'change_reason': rows[0][9]
    }
    
    v2 = {
        'version_number': rows[1][0],
        'data': json.loads(rows[1][1]),
        'hash': rows[1][2],
        'previous_hash': rows[1][3],
        'officer_id': rows[1][4],
        'officer_name': rows[1][5],
        'officer_role': rows[1][6],
        'badge_number': rows[1][7],
        'created_at': rows[1][8],
        'change_reason': rows[1][9]
    }
    
    # Get change events between versions
    cursor.execute("""
        SELECT 
            id,
            actor_name,
            actor_role,
            actor_badge,
            event_type,
            changed_fields_json,
            old_values_json,
            new_values_json,
            reason,
            timestamp
        FROM fir_change_events
        WHERE fir_id = ? 
          AND new_version >= ? 
          AND new_version <= ?
        ORDER BY timestamp ASC
    """, (fir_id, version1, version2))
    
    change_events = []
    for row in cursor.fetchall():
        change_events.append({
            'event_id': row[0],
            'actor_name': row[1],
            'actor_role': row[2],
            'actor_badge': row[3],
            'event_type': row[4],
            'changed_fields': json.loads(row[5]) if row[5] else [],
            'old_values': json.loads(row[6]) if row[6] else {},
            'new_values': json.loads(row[7]) if row[7] else {},
            'reason': row[8],
            'timestamp': row[9]
        })
    
    conn.close()
    
    # Compare field by field
    all_fields = set(v1['data'].keys()) | set(v2['data'].keys())
    field_differences = []
    
    for field in sorted(all_fields):
        old_value = v1['data'].get(field, '(not set)')
        new_value = v2['data'].get(field, '(not set)')
        
        if old_value != new_value:
            field_differences.append({
                'field_name': field,
                'original_value': old_value,
                'current_value': new_value,
                'status': 'CHANGED'
            })
    
    return {
        'fir_id': fir_id,
        'original_version': {
            'version': v1['version_number'],
            'hash': v1['hash'],
            'created_by': v1['officer_name'],
            'role': v1['officer_role'],
            'badge': v1['badge_number'],
            'created_at': v1['created_at'],
            'reason': v1['change_reason']
        },
        'current_version': {
            'version': v2['version_number'],
            'hash': v2['hash'],
            'created_by': v2['officer_name'],
            'role': v2['officer_role'],
            'badge': v2['badge_number'],
            'created_at': v2['created_at'],
            'reason': v2['change_reason']
        },
        'field_differences': field_differences,
        'change_events': change_events,
        'total_changes': len(field_differences),
        'hash_comparison': {
            'original_hash': v1['hash'],
            'current_hash': v2['hash'],
            'hashes_match': v1['hash'] == v2['hash'],
            'integrity_status': 'VERIFIED' if v2['previous_hash'] == v1['hash'] else 'WARNING'
        }
    }


def get_complete_audit_log(
    fir_id: Optional[str] = None,
    officer_id: Optional[str] = None,
    role: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    action_type: Optional[str] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """
    Get complete audit log with filtering options.
    
    Args:
        fir_id: Filter by specific FIR
        officer_id: Filter by specific officer
        role: Filter by officer role
        date_from: Start date (ISO format)
        date_to: End date (ISO format)
        action_type: Filter by event type
        limit: Maximum number of records
    
    Returns:
        List of audit log entries
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 
            e.id,
            e.timestamp,
            e.fir_id,
            f.fir_number,
            e.actor_id,
            e.actor_name,
            e.actor_role,
            e.actor_badge,
            e.event_type,
            e.reason,
            e.new_version,
            e.changed_fields_json,
            e.blockchain_status,
            e.event_hash
        FROM fir_change_events e
        JOIN firs f ON e.fir_id = f.id
        WHERE 1=1
    """
    
    params = []
    
    if fir_id:
        query += " AND e.fir_id = ?"
        params.append(fir_id)
    
    if officer_id:
        query += " AND e.actor_id = ?"
        params.append(officer_id)
    
    if role:
        query += " AND e.actor_role = ?"
        params.append(role)
    
    if date_from:
        query += " AND datetime(e.timestamp) >= datetime(?)"
        params.append(date_from)
    
    if date_to:
        query += " AND datetime(e.timestamp) <= datetime(?)"
        params.append(date_to)
    
    if action_type:
        query += " AND e.event_type = ?"
        params.append(action_type)
    
    query += " ORDER BY e.timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    
    audit_logs = []
    for row in cursor.fetchall():
        changed_fields = json.loads(row[11]) if row[11] else []
        
        audit_logs.append({
            'id': row[0],
            'timestamp': row[1],
            'fir_id': row[2],
            'fir_number': row[3],
            'officer_id': row[4],
            'officer_name': row[5],
            'officer_role': row[6],
            'badge_number': row[7],
            'action': row[8],
            'reason': row[9],
            'version': row[10],
            'changed_fields': changed_fields,
            'blockchain_status': row[12],
            'event_hash': row[13][:16] + '...'  # Abbreviated
        })
    
    conn.close()
    
    return audit_logs


def get_fir_complete_timeline(fir_id: str) -> Dict[str, Any]:
    """
    Get complete chronological timeline for a specific FIR with all events.
    
    Args:
        fir_id: FIR identifier
    
    Returns:
        Complete timeline with all events and state changes
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get FIR details
    cursor.execute("""
        SELECT 
            id,
            fir_number,
            status,
            created_at,
            citizen_id,
            assigned_officer_id,
            police_station
        FROM firs
        WHERE id = ?
    """, (fir_id,))
    
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        return {'error': 'FIR not found'}
    
    fir_info = {
        'id': fir_row[0],
        'fir_number': fir_row[1],
        'status': fir_row[2],
        'created_at': fir_row[3],
        'citizen_id': fir_row[4],
        'assigned_officer_id': fir_row[5],
        'police_station': fir_row[6]
    }
    
    # Get all change events
    cursor.execute("""
        SELECT 
            e.id,
            e.timestamp,
            e.actor_name,
            e.actor_role,
            e.actor_badge,
            e.event_type,
            e.reason,
            e.previous_version,
            e.new_version,
            e.changed_fields_json,
            e.blockchain_status
        FROM fir_change_events e
        WHERE e.fir_id = ?
        ORDER BY e.timestamp ASC
    """, (fir_id,))
    
    events = []
    for row in cursor.fetchall():
        changed_fields = json.loads(row[9]) if row[9] else []
        
        events.append({
            'event_id': row[0],
            'timestamp': row[1],
            'actor_name': row[2],
            'actor_role': row[3],
            'badge': row[4],
            'event_type': row[5],
            'description': row[6],
            'from_version': row[7],
            'to_version': row[8],
            'changed_fields': changed_fields,
            'blockchain_status': row[10]
        })
    
    # Get officer assignments
    cursor.execute("""
        SELECT 
            oa.id,
            oa.assigned_at,
            oa.status,
            u1.name as officer_name,
            u1.role as officer_role,
            u1.badge_number,
            u2.name as assigned_by_name,
            u2.role as assigned_by_role
        FROM officer_assignments oa
        JOIN users u1 ON oa.officer_id = u1.id
        JOIN users u2 ON oa.assigned_by = u2.id
        WHERE oa.fir_id = ?
        ORDER BY oa.assigned_at ASC
    """, (fir_id,))
    
    assignments = []
    for row in cursor.fetchall():
        assignments.append({
            'assignment_id': row[0],
            'timestamp': row[1],
            'status': row[2],
            'officer_name': row[3],
            'officer_role': row[4],
            'badge': row[5],
            'assigned_by': row[6],
            'assigned_by_role': row[7]
        })
    
    conn.close()
    
    return {
        'fir_info': fir_info,
        'total_events': len(events),
        'total_assignments': len(assignments),
        'events': events,
        'assignments': assignments
    }


REASSIGNMENT_REASONS = (
    'Suspected tampering',
    'Unauthorized modification',
    'Security concern',
    'Administrative reassignment',
    'Investigation continuity',
)


def _now_iso() -> str:
    # Naive local timestamp, matching officer_assignments rows written elsewhere.
    return datetime.now().isoformat()


def _human_time(value: str) -> str:
    try:
        return datetime.fromisoformat(value).strftime('%d %b %Y %H:%M IST')
    except Exception:
        return value


def _insert_notification(
    cursor,
    *,
    user_id: str,
    fir_id: Optional[str],
    complaint_id: Optional[str],
    event_key: str,
    title: str,
    message: str,
    notification_type: str = 'OFFICER_REASSIGNMENT',
    severity: str = 'INFO',
) -> Optional[Dict[str, Any]]:
    """Queue one persistent notification inside the caller's transaction.

    The ``event_key`` makes the delivery idempotent: replaying the same
    reassignment never creates a second alert for the same user.
    """
    cursor.execute(
        "SELECT 1 FROM notifications WHERE user_id = ? AND event_id = ? LIMIT 1",
        (user_id, event_key),
    )
    if cursor.fetchone():
        return None
    notif_id = f"ntf-{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    cursor.execute("""
        INSERT INTO notifications (
            id, user_id, fir_id, complaint_id, event_id, type, title, message,
            is_read, severity, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
    """, (
        notif_id, user_id, fir_id or None, complaint_id or None, event_key,
        notification_type, title, message, severity, now,
    ))
    return {
        'id': notif_id,
        'user_id': user_id,
        'fir_id': fir_id,
        'complaint_id': complaint_id,
        'title': title,
        'message': message,
        'type': notification_type,
        'severity': severity,
        'is_read': 0,
        'created_at': now,
    }


def reassign_officer(
    fir_id: str,
    new_officer_id: str,
    authorized_officer_id: str,
    reason: str,
    remarks: str = ''
) -> Dict[str, Any]:
    """Change the investigating officer of an existing FIR atomically.

    The FIR number, document, evidence, versions, hashes, messages and every
    historical record stay untouched. Only the active assignment changes; the
    previous assignment row is closed with its revocation timestamp and the new
    assignment is created with the reason/remarks that justified it.

    Everything below - assignment, FIR row, complaint linkage, audit event and
    the notifications for every role - runs in one SQLite transaction, so a
    failure cannot leave a half-reassigned case behind.
    """
    reason = (reason or '').strip()
    remarks = (remarks or '').strip()
    if len(reason) < 10:
        raise ValueError('Select a reassignment reason (at least 10 characters).')

    conn = get_db_connection()
    cursor = conn.cursor()
    queued_notifications: List[Dict[str, Any]] = []
    try:
        conn.execute('BEGIN IMMEDIATE')

        cursor.execute("""
            SELECT f.*, cu.name AS citizen_name, cu.phone AS citizen_phone,
                   c.reference AS complaint_reference
            FROM firs f
            LEFT JOIN users cu ON f.citizen_id = cu.id
            LEFT JOIN complaints c ON f.complaint_id = c.id
            WHERE f.id = ?
        """, (fir_id,))
        fir_row = cursor.fetchone()
        if not fir_row:
            raise ValueError('FIR not found.')
        fir = dict(fir_row)

        cursor.execute(
            "SELECT * FROM users WHERE id = ? AND role = 'OFFICER' AND status = 'ACTIVE'",
            (new_officer_id,),
        )
        new_officer_row = cursor.fetchone()
        if not new_officer_row:
            raise ValueError('Select an active police officer for this FIR.')
        new_officer = dict(new_officer_row)

        cursor.execute(
            "SELECT id, name, role, badge_number FROM users WHERE id = ?",
            (authorized_officer_id,),
        )
        actor_row = cursor.fetchone()
        if not actor_row:
            raise ValueError('Authorized Officer account not found.')
        actor = dict(actor_row)
        if actor.get('role') not in ('ADMIN', 'AUTHORIZED_OFFICER'):
            raise PermissionError('Only an Authorized Officer may change the assigned officer.')

        cursor.execute("""
            SELECT oa.*, u.name AS officer_name, u.badge_number AS officer_badge,
                   u.rank AS officer_rank
            FROM officer_assignments oa
            JOIN users u ON oa.officer_id = u.id
            WHERE oa.fir_id = ? AND oa.status = 'ACTIVE'
            ORDER BY oa.assigned_at DESC LIMIT 1
        """, (fir_id,))
        current_row = cursor.fetchone()
        current_assignment = dict(current_row) if current_row else None

        old_officer_id = (
            current_assignment['officer_id'] if current_assignment
            else fir.get('assigned_officer_id')
        )
        old_officer_name = (
            current_assignment['officer_name'] if current_assignment
            else 'Not assigned'
        )
        old_officer_badge = current_assignment['officer_badge'] if current_assignment else None

        now = _now_iso()

        # Idempotent replay: the requested officer already owns the case.
        if old_officer_id == new_officer_id:
            conn.rollback()
            return {
                'success': True,
                'already_assigned': True,
                'message': f"{new_officer['name']} is already the active investigating officer.",
                'previous_officer': {
                    'id': old_officer_id,
                    'name': old_officer_name,
                    'badge': old_officer_badge,
                },
                'new_officer': {
                    'id': new_officer_id,
                    'name': new_officer['name'],
                    'badge': new_officer.get('badge_number'),
                },
                'authorized_by': {
                    'id': authorized_officer_id,
                    'name': actor['name'],
                    'role': actor['role'],
                },
                'timestamp': now,
                'reason': reason,
                'remarks': remarks,
                'fir_number': fir.get('fir_number'),
                'citizen': {'id': fir.get('citizen_id'), 'name': fir.get('citizen_name')},
                'complaint_reference': fir.get('complaint_reference'),
                'notifications': [],
            }

        # 1. Close the previous active assignment and record the exact revocation.
        cursor.execute("""
            UPDATE officer_assignments
            SET status = 'REASSIGNED',
                revoked_at = ?,
                reason = ?,
                remarks = ?
            WHERE fir_id = ? AND status = 'ACTIVE'
        """, (now, reason, remarks, fir_id))

        # 2. Create the new active assignment (fresh UUID - no timestamp collisions).
        assignment_id = f"asg-{uuid.uuid4().hex[:12]}"
        cursor.execute("""
            INSERT INTO officer_assignments (
                id, fir_id, officer_id, assigned_by, assigned_at, status, reason, remarks
            ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', ?, ?)
        """, (assignment_id, fir_id, new_officer_id, authorized_officer_id, now, reason, remarks))

        # 3. Point the FIR (and the originating complaint) at the new officer.
        cursor.execute(
            "UPDATE firs SET assigned_officer_id = ?, updated_at = ? WHERE id = ?",
            (new_officer_id, now, fir_id),
        )
        if fir.get('complaint_id'):
            cursor.execute("""
                UPDATE complaints
                SET assigned_officer_id = ?, assigned_officer_name = ?,
                    assigned_at = ?, updated_at = ?
                WHERE id = ?
            """, (
                new_officer_id, new_officer['name'], now, now, fir['complaint_id'],
            ))

        # 4. Immutable audit event. The FIR content hash is unchanged by a
        #    reassignment, so current_hash remains the trusted canonical proof.
        cursor.execute("""
            SELECT id, version_number, current_hash, previous_hash
            FROM fir_versions WHERE fir_id = ?
            ORDER BY version_number DESC LIMIT 1
        """, (fir_id,))
        version_row = cursor.fetchone()
        version_id = version_row['id'] if version_row else f"reassign-{fir_id}"
        version_number = int(version_row['version_number']) if version_row else int(fir.get('current_version') or 1)
        canonical_hash = (
            version_row['current_hash'] if version_row and version_row['current_hash']
            else fir.get('current_hash') or ''
        )
        previous_hash = canonical_hash

        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        event_number = f"REAS-{uuid.uuid4().hex[:10].upper()}"
        old_record = f"{old_officer_name} ({old_officer_badge or 'N/A'})"
        new_record = f"{new_officer['name']} ({new_officer.get('badge_number') or 'N/A'})"
        event_reason = reason + (f" - {remarks}" if remarks else '')
        event_hash = calculate_sha256(canonical_json({
            'event': 'OFFICER_REASSIGNMENT',
            'fir_id': fir_id,
            'previous_officer_id': old_officer_id,
            'new_officer_id': new_officer_id,
            'actor_id': authorized_officer_id,
            'reason': event_reason,
            'timestamp': now,
        }))

        tx_id = f"AUDIT-{event_id}"
        cursor.execute("""
            INSERT INTO fir_change_events (
                id, event_number, fir_id, version_id, previous_version, new_version,
                actor_id, actor_name, actor_badge, actor_role, event_type,
                changed_fields_json, old_values_json, new_values_json, reason,
                timestamp, timezone, previous_hash, new_hash, blockchain_tx_id,
                blockchain_status, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OFFICER_REASSIGNMENT',
                      ?, ?, ?, ?, ?, 'UTC', ?, ?, ?, 'AUDIT_ONLY', ?)
        """, (
            event_id, event_number, fir_id, version_id, version_number, version_number,
            authorized_officer_id, actor['name'], actor.get('badge_number'), actor['role'],
            json.dumps(['assigned_officer_id']),
            json.dumps({'assigned_officer_id': old_record}),
            json.dumps({
                'assigned_officer_id': new_record,
                'reassignment_reason': reason,
                'remarks': remarks,
            }),
            event_reason, now, previous_hash, canonical_hash, tx_id, event_hash,
        ))

        # 5. Notifications for every role, queued in the same transaction.
        complaint_reference = fir.get('complaint_reference') or 'Not recorded'
        display_time = _human_time(now)
        new_officer_notification = _insert_notification(
            cursor,
            user_id=new_officer_id,
            fir_id=fir_id,
            complaint_id=fir.get('complaint_id'),
            event_key=f'reassign-new-officer-{event_id}',
            title='New FIR Assigned to You',
            message=(
                'An existing FIR has been reassigned to you by the Authorized Officer. '
                'You are now responsible for continuing this investigation. Please review the FIR '
                'document, supporting evidence and previous investigation history.\n\n'
                f"FIR Number: {fir.get('fir_number')}\n"
                f"Citizen: {fir.get('citizen_name') or 'Citizen'}\n"
                f"Complaint Reference: {complaint_reference}\n"
                f"Assigned: {display_time}\n"
                f"Open case: /police/fir/{fir_id}"
            ),
            severity='INFO',
        )
        if new_officer_notification:
            queued_notifications.append(new_officer_notification)

        citizen_notification = _insert_notification(
            cursor,
            user_id=fir.get('citizen_id'),
            fir_id=fir_id,
            complaint_id=fir.get('complaint_id'),
            event_key=f'reassign-citizen-{event_id}',
            title='Your FIR has been assigned to a new Police Officer.',
            message=(
                f"Your FIR {fir.get('fir_number')} has been reassigned to Officer "
                f"{new_officer['name']}. The new officer will continue handling your investigation. "
                'Your existing FIR details and case history have been preserved. You can communicate '
                'with the newly assigned officer through your Citizen Dashboard.\n\n'
                f"FIR Number: {fir.get('fir_number')}\n"
                f"Reassigned: {display_time}\n"
                f"Track your case: /citizen/fir/{fir_id}/track\n"
                f"Chat with your officer: /citizen/chat/{fir_id}"
            ),
            severity='SUCCESS',
        )
        if citizen_notification:
            queued_notifications.append(citizen_notification)

        if old_officer_id and old_officer_id != new_officer_id:
            previous_notification = _insert_notification(
                cursor,
                user_id=old_officer_id,
                fir_id=None,
                complaint_id=None,
                event_key=f'reassign-previous-officer-{event_id}',
                title='FIR Reassigned to Another Officer',
                message=(
                    f"FIR {fir.get('fir_number')} has been reassigned by the Authorized Officer. "
                    f"Your active access to this case ended on {display_time}. Your prior notes, "
                    'evidence and messages remain preserved in the case history.'
                ),
                severity='WARNING',
            )
            if previous_notification:
                queued_notifications.append(previous_notification)

        actor_notification = _insert_notification(
            cursor,
            user_id=authorized_officer_id,
            fir_id=fir_id,
            complaint_id=fir.get('complaint_id'),
            event_key=f'reassign-actor-{event_id}',
            title='Officer Reassignment Recorded',
            message=(
                f"FIR {fir.get('fir_number')}: {old_officer_name} was replaced by "
                f"{new_officer['name']} ({new_officer.get('badge_number') or 'N/A'}). "
                f"Reason: {reason}. Recorded {display_time}.\n"
                f"Open case record: /admin/fir-cases/{fir_id}/full"
            ),
            notification_type='AUDIT_ALERT',
            severity='INFO',
        )
        if actor_notification:
            queued_notifications.append(actor_notification)

        cursor.execute(
            "SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER' AND status = 'ACTIVE'"
        )
        for row in cursor.fetchall():
            verification_notification = _insert_notification(
                cursor,
                user_id=row['id'],
                fir_id=fir_id,
                complaint_id=fir.get('complaint_id'),
                event_key=f"reassign-verification-{event_id}-{row['id']}",
                title='Investigating Officer Reassigned',
                message=(
                    f"FIR {fir.get('fir_number')} is now handled by {new_officer['name']} "
                    f"({new_officer.get('badge_number') or 'N/A'}), replacing {old_officer_name}. "
                    f"Reason: {reason}. Recorded {display_time}."
                ),
                notification_type='OFFICER_REASSIGNMENT',
                severity='INFO',
            )
            if verification_notification:
                queued_notifications.append(verification_notification)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 6. Realtime push happens only after the transaction is durable.
    try:
        from backend.services.realtime_events import publish
        for notification in queued_notifications:
            publish({
                'type': 'NOTIFICATION_CREATED',
                'user_id': notification['user_id'],
                'notification': notification,
            })
        publish({
            'type': 'FIR_UPDATED',
            'event': 'OFFICER_REASSIGNED',
            'fir_id': fir_id,
            'fir_number': fir.get('fir_number'),
            'citizen_id': fir.get('citizen_id'),
            'officer_id': new_officer_id,
            'previous_officer_id': old_officer_id,
        })
    except Exception:
        pass

    return {
        'success': True,
        'already_assigned': False,
        'message': f"Officer reassigned from {old_officer_name} to {new_officer['name']}.",
        'previous_officer': {
            'id': old_officer_id,
            'name': old_officer_name,
            'badge': old_officer_badge,
            'revoked_at': now,
        },
        'new_officer': {
            'id': new_officer_id,
            'name': new_officer['name'],
            'badge': new_officer.get('badge_number'),
            'rank': new_officer.get('rank'),
            'station': new_officer.get('station'),
        },
        'authorized_by': {
            'id': authorized_officer_id,
            'name': actor['name'],
            'role': actor['role'],
        },
        'timestamp': now,
        'reason': reason,
        'remarks': remarks,
        'fir_number': fir.get('fir_number'),
        'citizen': {'id': fir.get('citizen_id'), 'name': fir.get('citizen_name')},
        'complaint_reference': fir.get('complaint_reference'),
        'assignment_id': assignment_id,
        'event_id': event_id,
        'event_number': event_number,
        'notifications': [
            {'user_id': n['user_id'], 'title': n['title'], 'id': n['id']}
            for n in queued_notifications
        ],
    }

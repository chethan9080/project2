"""
Authorized Officer Data Access Layer
Handles FIR integrity monitoring, version comparison, audit logs, and officer management
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from backend.services.db import get_db_connection
import json


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


def reassign_officer(
    fir_id: str,
    new_officer_id: str,
    authorized_officer_id: str,
    reason: str
) -> Dict[str, Any]:
    """
    Reassign an officer to an FIR (Authorized Officers only).
    Creates audit trail for the reassignment.
    
    Args:
        fir_id: FIR identifier
        new_officer_id: New officer's user ID
        authorized_officer_id: Authorized officer making the change
        reason: Reason for reassignment
    
    Returns:
        Result of reassignment operation
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current assignment
    cursor.execute("""
        SELECT 
            officer_id,
            u.name,
            u.badge_number,
            u.role
        FROM officer_assignments oa
        JOIN users u ON oa.officer_id = u.id
        WHERE oa.fir_id = ? AND oa.status = 'ACTIVE'
    """, (fir_id,))
    
    current_assignment = cursor.fetchone()
    old_officer_id = current_assignment[0] if current_assignment else None
    old_officer_name = current_assignment[1] if current_assignment else "None"
    
    # Get new officer details
    cursor.execute("""
        SELECT name, badge_number, role
        FROM users
        WHERE id = ?
    """, (new_officer_id,))
    
    new_officer = cursor.fetchone()
    if not new_officer:
        conn.close()
        return {'success': False, 'error': 'New officer not found'}
    
    new_officer_name = new_officer[0]
    new_officer_badge = new_officer[1]
    
    # Get authorized officer details
    cursor.execute("""
        SELECT name, role, badge_number
        FROM users
        WHERE id = ?
    """, (authorized_officer_id,))
    
    auth_officer = cursor.fetchone()
    auth_officer_name = auth_officer[0] if auth_officer else "Unknown"
    auth_officer_role = auth_officer[1] if auth_officer else "UNKNOWN"
    
    now = datetime.now().isoformat()
    
    # Mark old assignment as REASSIGNED
    if old_officer_id:
        cursor.execute("""
            UPDATE officer_assignments
            SET status = 'REASSIGNED'
            WHERE fir_id = ? AND status = 'ACTIVE'
        """, (fir_id,))
    
    # Create new assignment
    assignment_id = f"ASSIGN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{fir_id[-4:]}"
    cursor.execute("""
        INSERT INTO officer_assignments
        (id, fir_id, officer_id, assigned_by, assigned_at, status)
        VALUES (?, ?, ?, ?, ?, 'ACTIVE')
    """, (assignment_id, fir_id, new_officer_id, authorized_officer_id, now))
    
    # Update FIR assigned_officer_id
    cursor.execute("""
        UPDATE firs
        SET assigned_officer_id = ?, updated_at = ?
        WHERE id = ?
    """, (new_officer_id, now, fir_id))
    
    # Create change event for audit trail
    event_id = f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    cursor.execute("""
        INSERT INTO fir_change_events
        (id, fir_id, version_id, actor_id, actor_name, actor_role, 
         event_type, changed_fields_json, old_values_json, new_values_json,
         reason, timestamp, blockchain_tx_id, event_hash, actor_badge)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        fir_id,
        'REASSIGNMENT',
        authorized_officer_id,
        auth_officer_name,
        auth_officer_role,
        'OFFICER_REASSIGNMENT',
        json.dumps(['assigned_officer_id']),
        json.dumps({'assigned_officer': old_officer_name}),
        json.dumps({'assigned_officer': new_officer_name}),
        reason,
        now,
        f"TX-REASSIGN-{event_id}",
        f"hash-{event_id}",
        auth_officer[2] if auth_officer else None
    ))
    
    conn.commit()
    conn.close()
    
    return {
        'success': True,
        'message': f'Officer reassigned from {old_officer_name} to {new_officer_name}',
        'previous_officer': {
            'id': old_officer_id,
            'name': old_officer_name
        },
        'new_officer': {
            'id': new_officer_id,
            'name': new_officer_name,
            'badge': new_officer_badge
        },
        'authorized_by': {
            'id': authorized_officer_id,
            'name': auth_officer_name,
            'role': auth_officer_role
        },
        'timestamp': now,
        'reason': reason,
        'assignment_id': assignment_id,
        'event_id': event_id
    }

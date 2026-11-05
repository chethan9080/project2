"""
Real-Time Update Service for FIR Workflow.
Provides mechanisms for polling and retrieving real-time updates across
Citizen → Verification Officer → Police Officer workflow.

This service enables:
1. Real-time notification polling
2. FIR status change detection
3. New FIR detection for verification officers
4. Case assignment detection for police officers
5. Cross-portal synchronization
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection
from backend.services.notification_service import get_user_notifications, get_unread_count


def get_user_realtime_updates(user_id: str, last_poll_time: Optional[str] = None) -> Dict[str, Any]:
    """
    Get all real-time updates for a user since the last poll time.
    Returns:
        - new_notifications: List of new notifications
        - unread_count: Total unread notification count
        - fir_updates: FIRs that have been updated
        - new_assignments: New cases assigned to the user
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    result = {
        "new_notifications": [],
        "unread_count": 0,
        "fir_updates": [],
        "new_assignments": [],
        "timestamp": datetime.now().isoformat()
    }
    
    # Get unread count
    result["unread_count"] = get_unread_count(user_id)
    
    # Get recent notifications (last 10 unread)
    if last_poll_time:
        cursor.execute("""
            SELECT n.*, f.fir_number
            FROM notifications n
            LEFT JOIN firs f ON n.fir_id = f.id
            WHERE n.user_id = ? AND n.created_at > ? AND n.is_read = 0
            ORDER BY n.created_at DESC
            LIMIT 10
        """, (user_id, last_poll_time))
    else:
        cursor.execute("""
            SELECT n.*, f.fir_number
            FROM notifications n
            LEFT JOIN firs f ON n.fir_id = f.id
            WHERE n.user_id = ? AND n.is_read = 0
            ORDER BY n.created_at DESC
            LIMIT 10
        """, (user_id,))
    
    result["new_notifications"] = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return result


def get_pending_firs_for_verification_realtime(last_poll_time: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get FIRs pending verification, optionally filtered by timestamp.
    Used by verification officers to detect newly submitted FIRs in real-time.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if last_poll_time:
        query = """
            SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            WHERE f.status IN ('PENDING_VERIFICATION', 'SUBMITTED', 'UNDER_REVIEW')
              AND f.created_at > ?
            ORDER BY f.created_at DESC
        """
        cursor.execute(query, (last_poll_time,))
    else:
        query = """
            SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            WHERE f.status IN ('PENDING_VERIFICATION', 'SUBMITTED', 'UNDER_REVIEW')
            ORDER BY f.created_at DESC
        """
        cursor.execute(query)
    
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_all_pending_firs_for_verification() -> List[Dict[str, Any]]:
    """
    Get all FIRs currently pending verification.
    Used for initial page load by verification officers.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE f.status IN ('PENDING_VERIFICATION', 'SUBMITTED', 'UNDER_REVIEW')
        ORDER BY f.created_at DESC
    """
    cursor.execute(query)
    
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_officer_assigned_firs_realtime(officer_id: str, last_poll_time: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get FIRs assigned to a police officer, optionally filtered by assignment time.
    Used by police officers to detect newly assigned cases in real-time.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if last_poll_time:
        query = """
            SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
                   oa.assigned_at
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            LEFT JOIN officer_assignments oa ON f.id = oa.fir_id AND oa.officer_id = ?
            WHERE f.assigned_officer_id = ? AND oa.assigned_at > ?
            ORDER BY oa.assigned_at DESC
        """
        cursor.execute(query, (officer_id, officer_id, last_poll_time))
    else:
        query = """
            SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            WHERE f.assigned_officer_id = ?
            ORDER BY f.updated_at DESC
        """
        cursor.execute(query, (officer_id,))
    
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_citizen_firs_status_updates(citizen_id: str, last_poll_time: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Get status updates for a citizen's FIRs.
    Used by citizens to detect when their FIRs are verified, assigned, or updated.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if last_poll_time:
        query = """
            SELECT f.*, u.name AS citizen_name, 
                   o.name AS officer_name, o.badge_number AS officer_badge, 
                   o.rank AS officer_rank, o.station AS officer_station
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            LEFT JOIN users o ON f.assigned_officer_id = o.id
            WHERE f.citizen_id = ? AND f.updated_at > ?
            ORDER BY f.updated_at DESC
        """
        cursor.execute(query, (citizen_id, last_poll_time))
    else:
        query = """
            SELECT f.*, u.name AS citizen_name,
                   o.name AS officer_name, o.badge_number AS officer_badge,
                   o.rank AS officer_rank, o.station AS officer_station
            FROM firs f
            LEFT JOIN users u ON f.citizen_id = u.id
            LEFT JOIN users o ON f.assigned_officer_id = o.id
            WHERE f.citizen_id = ?
            ORDER BY f.updated_at DESC
        """
        cursor.execute(query, (citizen_id,))
    
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def check_fir_status_change(fir_id: str, last_known_status: str) -> Optional[Dict[str, Any]]:
    """
    Check if a FIR's status has changed since the last known status.
    Returns the updated FIR data if status changed, None otherwise.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT f.*, u.name AS citizen_name,
               o.name AS officer_name, o.badge_number AS officer_badge,
               o.rank AS officer_rank, o.station AS officer_station
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE f.id = ?
    """, (fir_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    fir = dict(row)
    if fir.get("status") != last_known_status:
        return fir
    
    return None


def check_fir_assignment_change(fir_id: str, last_known_officer_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check if a FIR's assigned officer has changed.
    Returns the updated FIR data if officer changed, None otherwise.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT f.*, u.name AS citizen_name,
               o.name AS officer_name, o.badge_number AS officer_badge,
               o.rank AS officer_rank, o.station AS officer_station
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE f.id = ?
    """, (fir_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    fir = dict(row)
    current_officer = fir.get("assigned_officer_id")
    
    if current_officer != last_known_officer_id:
        return fir
    
    return None


def get_verification_queue_stats() -> Dict[str, Any]:
    """
    Get real-time statistics for the verification queue.
    Returns counts by status for verification officers.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_pending,
            SUM(CASE WHEN status = 'PENDING_VERIFICATION' THEN 1 ELSE 0 END) as pending_verification,
            SUM(CASE WHEN status = 'UNDER_REVIEW' THEN 1 ELSE 0 END) as under_review,
            SUM(CASE WHEN status = 'NEEDS_CORRECTION' THEN 1 ELSE 0 END) as needs_correction
        FROM firs
        WHERE status IN ('PENDING_VERIFICATION', 'UNDER_REVIEW', 'NEEDS_CORRECTION', 'SUBMITTED')
    """)
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    
    return {
        "total_pending": 0,
        "pending_verification": 0,
        "under_review": 0,
        "needs_correction": 0
    }


def get_officer_caseload_stats(officer_id: str) -> Dict[str, Any]:
    """
    Get real-time caseload statistics for a police officer.
    Returns counts by status for the assigned cases.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            COUNT(*) as total_cases,
            SUM(CASE WHEN status = 'VERIFIED' THEN 1 ELSE 0 END) as verified,
            SUM(CASE WHEN status = 'UNDER_INVESTIGATION' THEN 1 ELSE 0 END) as under_investigation,
            SUM(CASE WHEN status = 'CHARGESHEET_FILED' THEN 1 ELSE 0 END) as chargesheet_filed,
            SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) as resolved,
            SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) as closed
        FROM firs
        WHERE assigned_officer_id = ?
    """, (officer_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return dict(row)
    
    return {
        "total_cases": 0,
        "verified": 0,
        "under_investigation": 0,
        "chargesheet_filed": 0,
        "resolved": 0,
        "closed": 0
    }


def broadcast_fir_update_to_stakeholders(fir_id: str) -> Dict[str, List[str]]:
    """
    Internal function to identify all stakeholders who should be notified of a FIR update.
    Returns dict with user_ids categorized by role: citizen, officer, verification_officers.
    
    Used internally by other services to determine who needs notifications.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT citizen_id, assigned_officer_id FROM firs WHERE id = ?", (fir_id,))
    fir_row = cursor.fetchone()
    
    if not fir_row:
        conn.close()
        return {"citizen": [], "officer": [], "verification_officers": []}
    
    fir = dict(fir_row)
    stakeholders = {
        "citizen": [fir["citizen_id"]] if fir.get("citizen_id") else [],
        "officer": [fir["assigned_officer_id"]] if fir.get("assigned_officer_id") else [],
        "verification_officers": []
    }
    
    # Get all verification officers
    cursor.execute("SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER'")
    vo_rows = cursor.fetchall()
    stakeholders["verification_officers"] = [r["id"] for r in vo_rows]
    
    conn.close()
    return stakeholders

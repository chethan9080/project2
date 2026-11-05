"""
Authorized Officer Service Layer
Business logic for FIR integrity monitoring, version comparison, and audit management
Enforces strict role-based access control - AUTHORIZED_OFFICER role only
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from data.authorized_officer import (
    get_integrity_dashboard_stats,
    get_fir_comparison,
    get_complete_audit_log,
    get_fir_complete_timeline,
    reassign_officer
)
from data.integrity import (
    get_fir_hashes,
    get_hash_chain_status,
    compare_version_hashes
)
from backend.services.fir_service import get_fir_versions


def check_authorized_officer_access(user: Dict[str, Any]) -> bool:
    """
    Verify that user has AUTHORIZED_OFFICER role.
    
    Args:
        user: User dictionary with role information
    
    Returns:
        True if user is authorized, False otherwise
    
    Raises:
        PermissionError: If user is not an Authorized Officer
    """
    if not user:
        raise PermissionError("Authentication required")
    
    # Only ADMIN role has authorized officer privileges in current schema
    # We'll treat ADMIN as AUTHORIZED_OFFICER for this implementation
    if user.get('role') not in ('ADMIN', 'AUTHORIZED_OFFICER'):
        raise PermissionError(
            "Access denied. This section is restricted to Authorized Officers only. "
            "Verification Officers, Police Officers, and Citizens cannot access integrity monitoring."
        )
    
    return True


def get_dashboard_data(user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get integrity dashboard statistics (Authorized Officers only).
    
    Args:
        user: Authenticated user
    
    Returns:
        Dashboard data with FIR integrity metrics
    """
    check_authorized_officer_access(user)
    
    stats = get_integrity_dashboard_stats()
    
    return {
        'dashboard': stats,
        'access_granted_to': {
            'name': user.get('name'),
            'role': user.get('role'),
            'badge': user.get('badge_number'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


from backend.services.auth_service import can_user_access_fir_audit

def compare_fir_versions(
    fir_id: str,
    version1: int,
    version2: int,
    user: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Compare two versions of an FIR showing detailed differences (Authorized Officers only).
    
    Args:
        fir_id: FIR identifier
        version1: First version number (typically older/original)
        version2: Second version number (typically newer/current)
        user: Authenticated user
    
    Returns:
        Detailed comparison with field-level changes and hash verification
    """
    if not user:
        raise PermissionError("Authentication required")
        
    # Get the FIR to check authorization
    from backend.services.fir_service import get_fir_by_id
    fir = get_fir_by_id(fir_id)
    if not fir:
        raise ValueError(f"FIR {fir_id} not found.")
        
    # Strictly enforce FIR-level authorization
    if not can_user_access_fir_audit(user, fir):
        raise PermissionError(
            "Forbidden: You are not authorized to view this FIR comparison. "
            "Only the assigned officer or an authorized supervisor can access this information."
        )
    
    # Get detailed comparison
    comparison = get_fir_comparison(fir_id, version1, version2)
    
    # Add hash chain verification
    hash_comparison = compare_version_hashes(fir_id, version1, version2)
    
    return {
        'comparison': comparison,
        'hash_verification': hash_comparison,
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


def get_fir_version_history(fir_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get complete version history with hash verification (Authorized Officers only).
    
    Args:
        fir_id: FIR identifier
        user: Authenticated user
    
    Returns:
        Complete version history with hash chain status
    """
    check_authorized_officer_access(user)
    
    # Get all versions
    versions = get_fir_versions(fir_id, actor_user=user)
    
    # Get hash information
    hashes = get_fir_hashes(fir_id)
    
    # Get hash chain integrity status
    chain_status = get_hash_chain_status(fir_id)
    
    return {
        'fir_id': fir_id,
        'versions': versions.get('versions', []),
        'hashes': hashes,
        'integrity_status': chain_status,
        'total_versions': len(versions.get('versions', [])),
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


def get_audit_logs(
    user: Dict[str, Any],
    fir_id: Optional[str] = None,
    officer_id: Optional[str] = None,
    role: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    action_type: Optional[str] = None,
    limit: int = 100
) -> Dict[str, Any]:
    """
    Get filtered audit logs (Authorized Officers only).
    
    Args:
        user: Authenticated user
        fir_id: Filter by FIR
        officer_id: Filter by officer
        role: Filter by role
        date_from: Start date
        date_to: End date
        action_type: Filter by action type
        limit: Maximum records
    
    Returns:
        Filtered audit log entries
    """
    check_authorized_officer_access(user)
    
    logs = get_complete_audit_log(
        fir_id=fir_id,
        officer_id=officer_id,
        role=role,
        date_from=date_from,
        date_to=date_to,
        action_type=action_type,
        limit=limit
    )
    
    return {
        'audit_logs': logs,
        'total_records': len(logs),
        'filters_applied': {
            'fir_id': fir_id,
            'officer_id': officer_id,
            'role': role,
            'date_from': date_from,
            'date_to': date_to,
            'action_type': action_type
        },
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


def get_fir_timeline(fir_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Get complete FIR timeline with all events (Authorized Officers only).
    
    Args:
        fir_id: FIR identifier
        user: Authenticated user
    
    Returns:
        Complete chronological timeline
    """
    check_authorized_officer_access(user)
    
    timeline = get_fir_complete_timeline(fir_id)
    
    return {
        'timeline': timeline,
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


def reassign_fir_officer(
    fir_id: str,
    new_officer_id: str,
    reason: str,
    user: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Reassign an officer to an FIR (Authorized Officers only).
    
    Args:
        fir_id: FIR identifier
        new_officer_id: New officer's user ID
        reason: Reason for reassignment
        user: Authenticated user (must be Authorized Officer)
    
    Returns:
        Reassignment result with audit trail
    """
    check_authorized_officer_access(user)
    
    if not reason or len(reason.strip()) < 10:
        raise ValueError("Reassignment reason must be at least 10 characters")
    
    result = reassign_officer(
        fir_id=fir_id,
        new_officer_id=new_officer_id,
        authorized_officer_id=user.get('id'),
        reason=reason
    )
    
    return result


def get_officer_activity_report(
    officer_id: str,
    user: Dict[str, Any],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get activity report for a specific officer (Authorized Officers only).
    
    Args:
        officer_id: Officer's user ID
        user: Authenticated user
        date_from: Start date
        date_to: End date
    
    Returns:
        Officer activity report with statistics
    """
    check_authorized_officer_access(user)
    
    logs = get_complete_audit_log(
        officer_id=officer_id,
        date_from=date_from,
        date_to=date_to,
        limit=500
    )
    
    # Calculate statistics
    event_types = {}
    firs_touched = set()
    
    for log in logs:
        event_type = log.get('action', 'UNKNOWN')
        event_types[event_type] = event_types.get(event_type, 0) + 1
        firs_touched.add(log.get('fir_id'))
    
    return {
        'officer_id': officer_id,
        'total_actions': len(logs),
        'unique_firs': len(firs_touched),
        'event_type_breakdown': event_types,
        'actions': logs,
        'date_range': {
            'from': date_from,
            'to': date_to
        },
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }


def get_integrity_alerts(user: Dict[str, Any], limit: int = 50) -> Dict[str, Any]:
    """
    Get FIR integrity alerts requiring attention (Authorized Officers only).
    
    Args:
        user: Authenticated user
        limit: Maximum number of alerts
    
    Returns:
        List of integrity alerts and suspicious activities
    """
    check_authorized_officer_access(user)
    
    # Get recent suspicious activities
    logs = get_complete_audit_log(
        action_type=None,  # Get all types
        limit=limit
    )
    
    # Filter for potential issues
    alerts = []
    for log in logs:
        # Flag rapid successive changes
        # Flag changes outside business hours
        # Flag unusual patterns
        # This is a simplified version - can be enhanced with ML/rules
        
        alert_level = 'INFO'
        alert_message = ''
        
        if log.get('action') in ['SUSPICIOUS_EDIT', 'UNAUTHORIZED_MODIFICATION']:
            alert_level = 'CRITICAL'
            alert_message = 'Suspicious modification detected'
        elif log.get('blockchain_status') != 'CONFIRMED':
            alert_level = 'WARNING'
            alert_message = 'Blockchain confirmation pending'
        
        if alert_message:
            alerts.append({
                **log,
                'alert_level': alert_level,
                'alert_message': alert_message
            })
    
    return {
        'alerts': alerts[:limit],
        'total_alerts': len(alerts),
        'critical_count': len([a for a in alerts if a['alert_level'] == 'CRITICAL']),
        'warning_count': len([a for a in alerts if a['alert_level'] == 'WARNING']),
        'requested_by': {
            'name': user.get('name'),
            'role': user.get('role'),
            'user_id': user.get('id')
        },
        'timestamp': datetime.now().isoformat()
    }

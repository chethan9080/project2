"""
Case Tracking Service
Manages 10-stage FIR progression, cryptographic security monitoring, and audit history.
Provides real-time state synchronization between Citizen and Main Officer portals.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services.db import get_db_connection
from backend.services.notification_service import create_notification
from backend.services.blockchain_service import verify_fir_integrity

# 10 Official Case Stages in Sequential Order
CASE_STAGES = [
    'COMPLAINT_SUBMITTED',
    'FIR_CREATED',
    'FIR_VERIFIED',
    'OFFICER_ASSIGNED',
    'INVESTIGATION_STARTED',
    'EVIDENCE_COLLECTION',
    'WITNESS_STATEMENTS',
    'INVESTIGATION_IN_PROGRESS',
    'INVESTIGATION_COMPLETED',
    'CHARGESHEET_PREPARED',
    'SUBMITTED_TO_COURT',
    'CASE_CLOSED'
]

STAGE_LABELS = {
    'COMPLAINT_SUBMITTED': 'Complaint Submitted',
    'FIR_CREATED': 'FIR Created',
    'FIR_VERIFIED': 'FIR Verified',
    'OFFICER_ASSIGNED': 'Officer Assigned',
    'INVESTIGATION_STARTED': 'Investigation Started',
    'EVIDENCE_COLLECTION': 'Evidence Collection',
    'WITNESS_STATEMENTS': 'Witness Statements Recorded',
    'INVESTIGATION_IN_PROGRESS': 'Investigation in Progress',
    'INVESTIGATION_COMPLETED': 'Investigation Completed',
    'CHARGESHEET_PREPARED': 'Charge Sheet Prepared',
    'SUBMITTED_TO_COURT': 'Submitted to Court',
    'CASE_CLOSED': 'Final Case Closure',
    # Backward compatibility aliases
    'COMPLAINT_REGISTERED': 'Complaint Submitted',
    'FIR_REGISTERED': 'FIR Created',
    'UNDER_INVESTIGATION': 'Investigation Started',
    'CASE_SUBMITTED_TO_COURT': 'Submitted to Court'
}

STAGE_DESCRIPTIONS = {
    'COMPLAINT_SUBMITTED': 'Complaint securely submitted online and recorded in police registry.',
    'FIR_CREATED': 'Official FIR record generated with unique FIR number and cryptographic hash.',
    'FIR_VERIFIED': 'FIR verified and authenticated by authorized police verification officer.',
    'OFFICER_ASSIGNED': 'Investigating officer assigned by Main Officer to lead case inquiries.',
    'INVESTIGATION_STARTED': 'Investigating officer actively working on the case and conducting field inquiry.',
    'EVIDENCE_COLLECTION': 'Physical and digital evidence being gathered and catalogued.',
    'WITNESS_STATEMENTS': 'Statements of witnesses recorded, where applicable to the case.',
    'INVESTIGATION_IN_PROGRESS': 'Investigating officer analysing evidence and pursuing case inquiries.',
    'INVESTIGATION_COMPLETED': 'Comprehensive police investigation concluded with official findings documented.',
    'CHARGESHEET_PREPARED': 'Statutory charge sheet and formal case report prepared under legal provisions.',
    'SUBMITTED_TO_COURT': 'Charge sheet and evidentiary dossier formally submitted to the competent court.',
    'CASE_CLOSED': 'Judicial proceedings and statutory case closure finalized.'
}

STAGE_ICONS = {
    'COMPLAINT_SUBMITTED': 'assignment',
    'FIR_CREATED': 'description',
    'FIR_VERIFIED': 'verified',
    'OFFICER_ASSIGNED': 'badge',
    'INVESTIGATION_STARTED': 'manage_search',
    'EVIDENCE_COLLECTION': 'inventory_2',
    'WITNESS_STATEMENTS': 'record_voice_over',
    'INVESTIGATION_IN_PROGRESS': 'pending_actions',
    'INVESTIGATION_COMPLETED': 'fact_check',
    'CHARGESHEET_PREPARED': 'gavel',
    'SUBMITTED_TO_COURT': 'account_balance',
    'CASE_CLOSED': 'task_alt'
}

STAGE_ALIASES = {
    'COMPLAINT_REGISTERED': 'COMPLAINT_SUBMITTED',
    'FIR_REGISTERED': 'FIR_CREATED',
    'UNDER_INVESTIGATION': 'INVESTIGATION_STARTED',
    'CASE_SUBMITTED_TO_COURT': 'SUBMITTED_TO_COURT',
}


def normalize_stage(stage: Optional[str]) -> Optional[str]:
    """Normalize stage name to canonical 10-stage key."""
    if not stage:
        return None
    st = stage.strip().upper()
    return STAGE_ALIASES.get(st, st)


def init_case_tracking_table():
    """Create case_tracking and security_alerts tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_tracking (
            id TEXT PRIMARY KEY,
            track_id TEXT UNIQUE NOT NULL,
            fir_id TEXT NOT NULL,
            previous_stage TEXT,
            new_stage TEXT NOT NULL,
            updated_by_officer_id TEXT NOT NULL,
            updated_by_officer_name TEXT NOT NULL,
            updated_by_officer_badge TEXT NOT NULL,
            remarks TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (fir_id) REFERENCES firs(id),
            FOREIGN KEY (updated_by_officer_id) REFERENCES users(id)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_tracking_fir ON case_tracking(fir_id, timestamp)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_case_tracking_track_id ON case_tracking(track_id)
    """)

    columns = {row[1] for row in cursor.execute("PRAGMA table_info(case_tracking)").fetchall()}
    if 'action' not in columns:
        # STARTED / PROGRESS / COMPLETED; legacy rows (NULL) are treated as STARTED.
        cursor.execute("ALTER TABLE case_tracking ADD COLUMN action TEXT")
    if 'public_note' not in columns:
        # Citizen-visible update text; ``remarks`` stays internal to police and administrators.
        cursor.execute("ALTER TABLE case_tracking ADD COLUMN public_note TEXT")
    
    # security_alerts table is created by init_database() in db.py with the full schema.
    # Redeclare here so init_case_tracking_table() is self-contained when called before
    # init_database() (e.g. at module import time during tests).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_alerts (
            id TEXT PRIMARY KEY,
            alert_id TEXT UNIQUE NOT NULL,
            fir_id TEXT NOT NULL,
            fir_number TEXT NOT NULL,
            stage TEXT,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            responsible_account TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            resolved_at TEXT,
            resolved_by_id TEXT,
            resolved_by_name TEXT,
            resolved_by_badge TEXT,
            resolution_notes TEXT,
            FOREIGN KEY (fir_id) REFERENCES firs(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_security_alerts_fir ON security_alerts(fir_id, status)
    """)
    
    conn.commit()
    conn.close()


def get_current_case_stage(fir_id: str) -> Optional[str]:
    """Get the current case stage for a FIR."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT new_stage 
        FROM case_tracking 
        WHERE fir_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 1
    """, (fir_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return row['new_stage']
    return None


def get_case_tracking_history(fir_id: str) -> List[Dict[str, Any]]:
    """Get complete case tracking history for a FIR."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * 
        FROM case_tracking 
        WHERE fir_id = ? 
        ORDER BY timestamp ASC
    """, (fir_id,))
    
    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        d['normalized_previous_stage'] = normalize_stage(d.get('previous_stage'))
        d['normalized_new_stage'] = normalize_stage(d.get('new_stage'))
        rows.append(d)
        
    conn.close()
    return rows


# ==============================================================================
# SECURITY MONITORING AND ALERTS
# ==============================================================================

def create_security_alert(
    fir_id: str,
    reason: str,
    stage: Optional[str] = None,
    severity: str = 'CRITICAL',
    responsible_account: Optional[str] = None,
    actor_user: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Log a genuine security alert or mischievous activity alert.
    Severity: 'CRITICAL' (Red), 'WARNING' (Orange), 'INFO'
    Status: 'PENDING_INVESTIGATION'
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT fir_number, citizen_id FROM firs WHERE id = ?", (fir_id,))
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        raise ValueError(f"FIR not found: {fir_id}")
        
    fir_number = fir_row['fir_number']
    citizen_id = fir_row['citizen_id']
    
    alert_pk = f"alt-{uuid.uuid4().hex[:12]}"
    alert_code = f"SEC-ALERT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    norm_stage = normalize_stage(stage) or get_current_case_stage(fir_id) or 'INVESTIGATION_STARTED'
    
    cursor.execute("""
        INSERT INTO security_alerts (
            id, alert_id, fir_id, fir_number, stage, alert_type,
            severity, reason, responsible_account, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        alert_pk, alert_code, fir_id, fir_number, norm_stage,
        'SUSPICIOUS_ACTIVITY' if severity == 'WARNING' else 'SECURITY_BREACH_ALERT',
        severity.upper(), reason.strip(),
        responsible_account or (actor_user.get('name') if actor_user else 'Unknown Account'),
        'PENDING_INVESTIGATION', now_iso
    ))
    
    conn.commit()
    conn.close()
    
    # Notify citizen
    create_notification(
        user_id=citizen_id,
        fir_id=fir_id,
        title=f"🚨 Security Alert: FIR {fir_number}",
        message=f"A security monitoring alert has been registered for your case: {reason}",
        notification_type='SECURITY_ALERT',
        event_id=alert_pk,
        severity='ALERT' if severity == 'CRITICAL' else 'WARNING'
    )
    
    return {
        'id': alert_pk,
        'alert_id': alert_code,
        'fir_id': fir_id,
        'fir_number': fir_number,
        'stage': norm_stage,
        'severity': severity.upper(),
        'reason': reason,
        'responsible_account': responsible_account,
        'status': 'PENDING_INVESTIGATION',
        'created_at': now_iso
    }


def resolve_security_alert(
    alert_id: str,
    officer_user: Dict[str, Any],
    resolution_notes: str
) -> Dict[str, Any]:
    """
    Main Officer resolves an existing security alert with investigation findings.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM security_alerts WHERE id = ? OR alert_id = ?", (alert_id, alert_id))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise ValueError(f"Security alert {alert_id} not found.")
        
    alert = dict(row)
    now_iso = datetime.now(timezone.utc).isoformat()
    
    cursor.execute("""
        UPDATE security_alerts
        SET status = 'RESOLVED',
            resolved_at = ?,
            resolved_by_id = ?,
            resolved_by_name = ?,
            resolved_by_badge = ?,
            resolution_notes = ?
        WHERE id = ?
    """, (
        now_iso,
        officer_user.get('id'),
        officer_user.get('name', 'Main Officer'),
        officer_user.get('badge_number') or 'N/A',
        resolution_notes.strip(),
        alert['id']
    ))
    
    conn.commit()
    conn.close()
    
    return {
        'id': alert['id'],
        'status': 'RESOLVED',
        'resolved_at': now_iso,
        'resolved_by': officer_user.get('name'),
        'resolution_notes': resolution_notes
    }


def get_security_alerts_for_fir(fir_id: str) -> List[Dict[str, Any]]:
    """Get all security alerts for a given FIR."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM security_alerts
        WHERE fir_id = ?
        ORDER BY created_at DESC
    """, (fir_id,))
    alerts = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return alerts


def get_security_monitoring_status(fir_id: str) -> Dict[str, Any]:
    """
    Evaluate overall security and integrity health for an FIR:
    - Green: Normal and verified status.
    - Red: Suspicious activity, verified unauthorized modification, or security threat.
    - Orange: Investigation warning or action required.
    - Grey: Security status unknown or not verified.
    """
    integrity = verify_fir_integrity(fir_id)
    alerts = get_security_alerts_for_fir(fir_id)
    
    active_critical = [a for a in alerts if a.get('status') == 'PENDING_INVESTIGATION' and a.get('severity') == 'CRITICAL']
    active_warning = [a for a in alerts if a.get('status') == 'PENDING_INVESTIGATION' and a.get('severity') == 'WARNING']
    
    # 1. Cryptographic tampering or critical unresolved alert => RED
    if integrity.get('status') == 'TAMPER_DETECTED' or not integrity.get('is_valid', True) or active_critical:
        reason = "Cryptographic tampering or unauthorized data discrepancy detected."
        if active_critical:
            reason = active_critical[0].get('reason', reason)
        elif integrity.get('message'):
            reason = integrity.get('message')
            
        return {
            'status': 'SECURITY_THREAT',
            'color': 'red',
            'badge_text': 'SECURITY ALERT: THREAT / SUSPICIOUS ACTIVITY',
            'summary': reason,
            'is_secure': False,
            'alerts': alerts,
            'integrity': integrity
        }
        
    # 2. Warning alerts => ORANGE
    if active_warning:
        return {
            'status': 'ACTION_REQUIRED',
            'color': 'orange',
            'badge_text': 'SECURITY WARNING: ACTION REQUIRED',
            'summary': active_warning[0].get('reason', 'Security inspection pending.'),
            'is_secure': False,
            'alerts': alerts,
            'integrity': integrity
        }
        
    # 3. Verified Cryptographically and no pending threat => GREEN
    if integrity.get('status') == 'VERIFIED' and integrity.get('is_valid') is True:
        return {
            'status': 'NORMAL_VERIFIED',
            'color': 'green',
            'badge_text': 'VERIFIED & IMMUTABLE (SHA-256 SECURED)',
            'summary': 'All cryptographic hashes verified. No unauthorized changes or security threats detected.',
            'is_secure': True,
            'alerts': alerts,
            'integrity': integrity
        }
        
    # 4. Fallback => GREY
    return {
        'status': 'UNKNOWN',
        'color': 'grey',
        'badge_text': 'SECURITY STATUS PENDING',
        'summary': 'Verification in progress or record pending verification.',
        'is_secure': True,
        'alerts': alerts,
        'integrity': integrity
    }


# ==============================================================================
# COMPREHENSIVE 10-STAGE FIR TIMELINE PROGRESSION
# ==============================================================================

FIR_STATUS_FOR_STAGE = {
    'COMPLAINT_SUBMITTED': 'SUBMITTED',
    'FIR_CREATED': 'SUBMITTED',
    'OFFICER_ASSIGNED': 'UNDER_INVESTIGATION',
    'INVESTIGATION_STARTED': 'UNDER_INVESTIGATION',
    'EVIDENCE_COLLECTION': 'UNDER_INVESTIGATION',
    'WITNESS_STATEMENTS': 'UNDER_INVESTIGATION',
    'INVESTIGATION_IN_PROGRESS': 'UNDER_INVESTIGATION',
    'INVESTIGATION_COMPLETED': 'UNDER_INVESTIGATION',
    'CHARGESHEET_PREPARED': 'CHARGESHEET_FILED',
    'SUBMITTED_TO_COURT': 'CHARGESHEET_FILED',
    'CASE_CLOSED': 'CLOSED',
}


def sync_fir_status_for_stage(
    fir: Dict[str, Any],
    canonical_stage: str,
    officer_user: Dict[str, Any],
    reason: str,
    now_iso: str,
    assigned_officer_id: Optional[str] = None,
) -> Optional[str]:
    """Move the FIR record status to match a stage, versioned and recorded on the ledger."""
    if canonical_stage == 'FIR_VERIFIED':
        sync_status = 'VERIFIED' if fir.get('status') == 'PENDING_VERIFICATION' else fir.get('status')
    else:
        sync_status = FIR_STATUS_FOR_STAGE.get(canonical_stage)
    if not sync_status or sync_status == fir.get('status'):
        return None

    fir_id = fir['id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        import json
        from backend.services.crypto_service import calculate_sha256
        from backend.services.blockchain_service import extract_canonical_fir_data, record_fir_change

        updated_fir = dict(fir)
        updated_fir["status"] = sync_status
        if assigned_officer_id:
            updated_fir["assigned_officer_id"] = assigned_officer_id
        new_version = fir.get("current_version", 1) + 1
        updated_fir["current_version"] = new_version
        updated_fir["updated_at"] = now_iso

        new_hash = calculate_sha256(extract_canonical_fir_data(updated_fir))
        record_fir_change(
            fir_id=fir_id,
            version=new_version,
            previous_hash=fir.get("current_hash"),
            new_hash=new_hash,
            actor_id=officer_user.get("id", "officer"),
            event_hash=new_hash,
            reason=reason,
            timestamp=now_iso,
        )
        cursor.execute("""
            INSERT INTO fir_versions (
                id, fir_id, version_number, snapshot_json, previous_hash,
                current_hash, created_by, created_at, change_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            f"ver-{uuid.uuid4().hex[:12]}", fir_id, new_version, json.dumps(updated_fir),
            fir.get("current_hash"), new_hash, officer_user.get("id", "system"), now_iso, reason,
        ))
        cursor.execute(
            "UPDATE firs SET status = ?, current_version = ?, current_hash = ?, updated_at = ? WHERE id = ?",
            (sync_status, new_version, new_hash, now_iso, fir_id),
        )
        conn.commit()
    except Exception as ex:
        import logging
        logging.error(f"Error in blockchain/version update for FIR {fir_id}: {ex}")
        cursor.execute("UPDATE firs SET status = ?, updated_at = ? WHERE id = ?", (sync_status, now_iso, fir_id))
        conn.commit()
    finally:
        conn.close()
    return sync_status


def update_case_stage(
    fir_id: str,
    new_stage: str,
    officer_user: Dict[str, Any],
    remarks: str = '',
    assigned_officer_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main Officer / Authorized Officer updates the FIR case stage.
    Saves to case_tracking table, updates FIR table status, records notifications,
    and updates database permanently.
    """
    canonical_stage = normalize_stage(new_stage)
    if canonical_stage not in CASE_STAGES:
        raise ValueError(f"Invalid stage: {new_stage}. Valid stages are: {', '.join(CASE_STAGES)}")
    
    current_stage = get_current_case_stage(fir_id)
    if current_stage == new_stage or (current_stage and normalize_stage(current_stage) == canonical_stage):
        raise ValueError(f"Case is already in stage: {STAGE_LABELS.get(canonical_stage, canonical_stage)}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE f.id = ?
    """, (fir_id,))
    
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        raise ValueError(f"FIR not found: {fir_id}")
    fir = dict(fir_row)
    
    track_id = f"TRK-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    tracking_id = f"trk-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # Insert tracking history row (save new_stage as passed so tests and callers get exact key)
    cursor.execute("""
        INSERT INTO case_tracking (
            id, track_id, fir_id, previous_stage, new_stage,
            updated_by_officer_id, updated_by_officer_name, updated_by_officer_badge,
            remarks, timestamp, action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'STARTED')
    """, (
        tracking_id,
        track_id,
        fir_id,
        current_stage,
        new_stage,
        officer_user.get('id', 'system'),
        officer_user.get('name', 'Main Officer'),
        officer_user.get('badge_number') or 'N/A',
        remarks.strip() or f"Stage updated to {STAGE_LABELS.get(canonical_stage, canonical_stage)}",
        now_iso
    ))
    conn.commit()
    
    conn.close()

    sync_fir_status_for_stage(
        fir, canonical_stage, officer_user,
        remarks.strip() or f"Stage updated to {STAGE_LABELS.get(canonical_stage, canonical_stage)}",
        now_iso, assigned_officer_id=assigned_officer_id,
    )
    
    # Notify Citizen
    stage_label = STAGE_LABELS.get(canonical_stage, canonical_stage)
    citizen_message = f"Your FIR {fir['fir_number']} has advanced to Stage: {stage_label}."
    # Officer remarks are internal investigation notes; only the curated stage
    # wording is public-safe enough to reach a citizen.
    try:
        from backend.services.investigation_service import PUBLIC_STAGE_TEXT
    except Exception:
        PUBLIC_STAGE_TEXT = {}
    public_line = PUBLIC_STAGE_TEXT.get(canonical_stage)
    if public_line:
        citizen_message += f"\n\n{public_line}"
        
    create_notification(
        user_id=fir['citizen_id'],
        fir_id=fir_id,
        title=f"📋 FIR Status Update: {stage_label}",
        message=citizen_message,
        notification_type='CASE_STAGE_UPDATE',
        event_id=tracking_id,
        severity='INFO'
    )

    try:
        from backend.services.realtime_events import publish
        publish({
            "type": "CASE_STAGE_UPDATED",
            "citizen_id": fir['citizen_id'],
            "officer_id": fir.get('assigned_officer_id'),
            "fir_id": fir_id,
            "stage": canonical_stage,
        })
    except Exception:
        pass

    return {
        'track_id': track_id,
        'fir_id': fir_id,
        'fir_number': fir['fir_number'],
        'citizen_name': fir.get('citizen_name', '—'),
        'previous_stage': current_stage,
        'new_stage': new_stage,
        'officer_name': officer_user.get('name', 'Main Officer'),
        'officer_badge': officer_user.get('badge_number') or 'N/A',
        'remarks': remarks,
        'timestamp': now_iso
    }

def initialize_case_tracking(
    fir_id: str,
    officer_user: Optional[Dict[str, Any]] = None,
    initial_stage: str = 'FIR_CREATED'
) -> Dict[str, Any]:
    """
    Initialize tracking history for a FIR if not already initialized.
    """
    canonical_stage = normalize_stage(initial_stage) or 'FIR_CREATED'
    current_stage = get_current_case_stage(fir_id)
    if current_stage:
        return {
            'fir_id': fir_id,
            'stage': current_stage,
            'status': 'ALREADY_INITIALIZED'
        }
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    track_id = f"TRK-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    tracking_id = f"trk-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    officer_name = officer_user.get('name', 'System') if officer_user else 'System Automated'
    officer_id = officer_user.get('id', 'system') if officer_user else 'system'
    officer_badge = (officer_user.get('badge_number') or 'N/A') if officer_user else 'N/A'
    
    cursor.execute("""
        INSERT INTO case_tracking (
            id, track_id, fir_id, previous_stage, new_stage,
            updated_by_officer_id, updated_by_officer_name, updated_by_officer_badge,
            remarks, timestamp, action
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED')
    """, (
        tracking_id, track_id, fir_id, None, canonical_stage,
        officer_id, officer_name, officer_badge,
        f"Case tracking initialized at {STAGE_LABELS.get(canonical_stage, canonical_stage)}",
        now_iso
    ))
    conn.commit()
    conn.close()
    
    return {
        'id': tracking_id,
        'track_id': track_id,
        'fir_id': fir_id,
        'stage': canonical_stage,
        'status': 'INITIALIZED'
    }


def get_case_stage_progress(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get backward-compatible case stage progress object.
    Used by test scripts and older components.
    """
    current_stage = get_current_case_stage(fir_id)
    history = get_case_tracking_history(fir_id)
    
    completed_stages = set()
    canon_cur = normalize_stage(current_stage)
    if canon_cur and canon_cur in CASE_STAGES:
        cur_idx = CASE_STAGES.index(canon_cur)
        completed_stages = set(CASE_STAGES[:cur_idx + 1])
        
    # Also add legacy aliases if their canonical stage is in completed_stages
    for alias_k, canon_k in STAGE_ALIASES.items():
        if canon_k in completed_stages:
            completed_stages.add(alias_k)
    
    return {
        'current_stage': current_stage,
        'current_stage_label': STAGE_LABELS.get(current_stage, '—') if current_stage else 'Not Started',
        'completed_stages': list(completed_stages),
        'history': history,
        'all_stages': CASE_STAGES,
        'stage_labels': STAGE_LABELS
    }


def get_fir_complete_tracking(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Master function to compile the 10-Stage Live Tracking Data for an FIR:
    - Fetches FIR record & citizen/officer details.
    - Evaluates all 10 stages with exact status, timestamp, description, and officer details.
    - Checks cryptographic integrity and security monitoring alerts.
    - Returns synchronized structure for Citizen and Main Officer portals.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.*, 
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name, o.badge_number AS officer_badge, o.rank AS officer_rank, o.station AS officer_station
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE f.id = ?
    """, (fir_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {}
    fir = dict(row)

    # Live tracking carries internal remarks, stage timing and the investigating officer's
    # identity, so the same assignment/ownership rule as every other case read applies here.
    role = (actor_user or {}).get('role')
    actor_id = (actor_user or {}).get('id')
    if role in ('ADMIN', 'VERIFICATION_OFFICER'):
        pass
    elif role == 'OFFICER':
        if fir.get('assigned_officer_id') != actor_id:
            raise PermissionError('Only the officer assigned to this case may open its live tracking.')
    elif role == 'CITIZEN':
        if fir.get('citizen_id') != actor_id:
            raise PermissionError('This case belongs to another citizen.')
    elif actor_user:
        raise PermissionError('This account is not authorized for case tracking.')

    # Tracking history
    history = get_case_tracking_history(fir_id)
    is_public_view = not actor_user or role == 'CITIZEN'
    history_by_stage: Dict[str, Dict[str, Any]] = {}
    public_note_by_stage: Dict[str, str] = {}
    for h in history:
        stage_k = h.get('normalized_new_stage') or normalize_stage(h.get('new_stage'))
        if stage_k:
            if stage_k in history_by_stage and h.get('action') == 'PROGRESS':
                # Keep the stage's start/completion row but surface the latest progress text.
                merged = dict(history_by_stage[stage_k])
                merged['remarks'] = h.get('remarks') or merged.get('remarks')
                history_by_stage[stage_k] = merged
            else:
                history_by_stage[stage_k] = h
            if h.get('public_note'):
                public_note_by_stage[stage_k] = h['public_note']

    def _stage_text(stage_k: str, hist: Optional[Dict[str, Any]], fallback: str) -> str:
        if is_public_view:
            return public_note_by_stage.get(stage_k) or fallback
        return (hist or {}).get('remarks') or fallback
            
    current_stage = get_current_case_stage(fir_id)
    sec_status = get_security_monitoring_status(fir_id)
    all_alerts = sec_status.get('alerts', [])
    
    # Determine base progress
    is_verified = (fir.get('status') != 'PENDING_VERIFICATION')
    has_officer = bool(fir.get('assigned_officer_id'))
    is_closed = (fir.get('status') in ('CLOSED', 'RESOLVED'))
    
    # Calculate current stage index
    if current_stage and current_stage in CASE_STAGES:
        cur_idx = CASE_STAGES.index(current_stage)
    else:
        # Default based on FIR state
        if is_closed:
            cur_idx = CASE_STAGES.index('CASE_CLOSED')
        elif fir.get('status') == 'CHARGESHEET_FILED':
            cur_idx = CASE_STAGES.index('CHARGESHEET_PREPARED')
        elif has_officer:
            cur_idx = CASE_STAGES.index('OFFICER_ASSIGNED')
        elif is_verified:
            cur_idx = CASE_STAGES.index('FIR_VERIFIED')
        else:
            cur_idx = CASE_STAGES.index('FIR_CREATED')
    current_action = (history[-1].get('action') or 'STARTED') if history else None
            
    stages_output = []
    
    for idx, stage_key in enumerate(CASE_STAGES):
        num = idx + 1
        label = STAGE_LABELS.get(stage_key, stage_key)
        default_desc = STAGE_DESCRIPTIONS.get(stage_key, '')
        icon = STAGE_ICONS.get(stage_key, 'circle')
        
        # Check if stage has history entry
        stage_hist = history_by_stage.get(stage_key)
        
        # Check alerts related to this stage. Security alerts carry internal reasons
        # and account identities, so they are never surfaced in the citizen view.
        stage_alerts = [] if is_public_view else [
            a for a in all_alerts if normalize_stage(a.get('stage')) == stage_key
        ]
        has_critical_alert = any(a.get('severity') == 'CRITICAL' and a.get('status') == 'PENDING_INVESTIGATION' for a in stage_alerts)
        has_warning_alert = any(a.get('severity') == 'WARNING' and a.get('status') == 'PENDING_INVESTIGATION' for a in stage_alerts)
        
        # Determine status & color
        # Green: Completed
        # Blue: Current
        # Grey: Upcoming
        # Red: Rejected, failed, suspended, or genuine security alert
        # Orange: Delayed or action required
        
        timestamp_str = None
        desc = default_desc
        officer_info = None
        
        if num == 1:
            # Complaint Submitted
            status = 'COMPLETED'
            color = 'green'
            timestamp_str = fir.get('created_at')
            desc = f"Complaint submitted by {fir.get('citizen_name', 'Citizen')}. Reference {fir.get('reference_number', '')} generated."
            
        elif num == 2:
            # FIR Created
            status = 'COMPLETED'
            color = 'green'
            timestamp_str = fir.get('created_at')
            desc = f"Official FIR {fir.get('fir_number')} registered under {fir.get('incident_type', 'General Offense')}."
            
        elif num == 3:
            # FIR Verified
            if is_verified or idx <= cur_idx or 'FIR_VERIFIED' in history_by_stage:
                status = 'COMPLETED'
                color = 'green'
                timestamp_str = stage_hist.get('timestamp') if stage_hist else fir.get('updated_at', fir.get('created_at'))
                desc = "FIR verified by Authorized Verification Officer. Legal authenticity confirmed."
            elif idx == cur_idx:
                status = 'CURRENT'
                color = 'blue'
                desc = "Pending verification by Authorized Police Verification Officer."
            else:
                status = 'UPCOMING'
                color = 'grey'
                
        elif num == 4:
            # Officer Assigned
            if has_officer or idx <= cur_idx or 'OFFICER_ASSIGNED' in history_by_stage:
                status = 'COMPLETED'
                color = 'green'
                timestamp_str = stage_hist.get('timestamp') if stage_hist else fir.get('updated_at', fir.get('created_at'))
                officer_info = " ".join(part for part in (
                    fir.get('officer_rank') or 'Officer',
                    fir.get('officer_name') or 'Investigating Officer',
                    f"(Badge: {fir.get('officer_badge') or 'not recorded'})",
                ) if part)
                desc = (
                    "Investigating officer assigned to this case at "
                    f"{fir.get('police_station') or 'the jurisdiction station'}."
                )
            elif idx == cur_idx:
                status = 'CURRENT'
                color = 'blue'
                desc = "Awaiting investigating officer assignment by Main Officer."
            else:
                status = 'UPCOMING'
                color = 'grey'
                
        else:
            # Investigation stages: completed only when actually recorded, skipped otherwise.
            def _officer_line(hist):
                parts = [hist.get('updated_by_officer_name')]
                badge = hist.get('updated_by_officer_badge')
                # Internal badge numbers stay out of the citizen-facing timeline.
                if not is_public_view and badge not in (None, '', 'N/A'):
                    parts.append(f"({badge})")
                return " ".join(part for part in parts if part)

            is_current = idx == cur_idx and not is_closed
            if stage_hist and (idx < cur_idx or is_closed or (is_current and current_action == 'COMPLETED')
                               or stage_key == 'CASE_CLOSED'):
                status = 'COMPLETED'
                color = 'green'
                timestamp_str = stage_hist.get('timestamp')
                desc = _stage_text(stage_key, stage_hist, default_desc)
                officer_info = _officer_line(stage_hist)
            elif is_current:
                status = 'CURRENT'
                color = 'blue'
                if stage_hist:
                    timestamp_str = stage_hist.get('timestamp')
                    desc = _stage_text(stage_key, stage_hist, default_desc)
                    officer_info = _officer_line(stage_hist)
            elif idx < cur_idx or is_closed:
                status = 'SKIPPED'
                color = 'grey'
                desc = 'Not applicable to this case.'
            else:
                status = 'UPCOMING'
                color = 'grey'

        # Override with alerts if present
        if has_critical_alert:
            status = 'ALERT'
            color = 'red'
        elif has_warning_alert:
            status = 'WARNING'
            color = 'orange'
            
        stages_output.append({
            'number': num,
            'key': stage_key,
            'label': label,
            'status': status,
            'color': color,
            'icon': icon,
            'timestamp': timestamp_str,
            'description': desc,
            'officer_info': officer_info,
            'alerts': stage_alerts
        })
        
    tracking = {
        'fir_id': fir_id,
        'fir_number': fir.get('fir_number'),
        'reference_number': fir.get('reference_number'),
        'citizen_name': fir.get('citizen_name'),
        'citizen_phone': fir.get('citizen_phone'),
        'status': fir.get('status'),
        'current_stage_key': CASE_STAGES[cur_idx],
        'current_action': current_action,
        'current_stage_label': STAGE_LABELS.get(CASE_STAGES[cur_idx]),
        'current_stage_index': cur_idx + 1,
        'total_stages': len(CASE_STAGES),
        'stages': stages_output,
        'security_status': sec_status,
        'last_updated_at': fir.get('updated_at', fir.get('created_at')),
        # Progress remarks recorded inside the current stage never touch firs.updated_at, so
        # the live poll needs the newest tracking event itself to notice them.
        'last_tracking_event_at': (history[-1].get('timestamp') if history else None)
                                  or fir.get('updated_at') or fir.get('created_at'),
        'assigned_officer': {
            'id': fir.get('assigned_officer_id'),
            'name': fir.get('officer_name'),
            'badge': fir.get('officer_badge'),
            'rank': fir.get('officer_rank'),
            'station': fir.get('police_station')
        }
    }

    # Cryptographic integrity and security-alert detail is technical audit data. Citizens
    # get a plain progress colour only; every non-Administrator role loses the hash block.
    if is_public_view:
        tracking['security_status'] = {
            'status': sec_status.get('status'),
            'color': sec_status.get('color'),
            'summary': '',
            'badge_text': '',
            'alerts': [],
        }
    elif role != 'ADMIN':
        tracking['security_status'] = {**sec_status, 'integrity': {}}

    return tracking


def get_all_firs_for_tracking(
    actor_user: Dict[str, Any],
    search_query: str = ''
) -> List[Dict[str, Any]]:
    """
    Get all FIRs that the user is authorized to track, supporting search by:
    - FIR Number
    - Citizen Name
    - Incident Type / Location
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    role = actor_user.get('role', 'CITIZEN')
    user_id = actor_user.get('id', '')
    
    base_query = """
        SELECT f.*, 
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name, o.badge_number AS officer_badge, o.rank AS officer_rank
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE 1=1
    """
    params = []
    
    if role == 'CITIZEN':
        base_query += " AND f.citizen_id = ?"
        params.append(user_id)
        
    if search_query.strip():
        q = f"%{search_query.strip().lower()}%"
        base_query += " AND (LOWER(f.fir_number) LIKE ? OR LOWER(u.name) LIKE ? OR LOWER(f.incident_type) LIKE ? OR LOWER(f.reference_number) LIKE ?)"
        params.extend([q, q, q, q])
        
    base_query += " ORDER BY f.created_at DESC"
    
    cursor.execute(base_query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    if role == 'OFFICER':
        from backend.services.auth_service import can_user_access_fir
        rows = [r for r in rows if can_user_access_fir(actor_user, r)]

    results = []
    for r in rows:
        fid = r['id']
        cur_st = get_current_case_stage(fid)
        r['current_stage'] = cur_st
        r['current_stage_label'] = STAGE_LABELS.get(cur_st, 'Under Process')
        results.append(r)
        
    return results


# Initialize tables on import
init_case_tracking_table()

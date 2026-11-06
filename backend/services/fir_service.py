"""
Core FIR Management Service.
Handles:
1. Citizen online FIR submission
2. Immutable Version Control
3. Cryptographic SHA-256 hashing & Blockchain Audit Event recording
4. Officer-controlled modifications with an optional reason and Old vs New diffs
5. Role-based notification output separation:
   - Citizen: Simple notification only ("Your FIR has been updated by an authorized police officer.")
   - Authorized Officer: Forensic audit trail with Old vs New diffs and blockchain proofs
6. Strict server-side access control for detailed change history
"""

import json
import random
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services.auth_service import (
    can_user_access_fir,
    can_user_access_fir_audit,
    can_user_modify_fir,
    get_user_by_id
)
from backend.services.blockchain_service import record_fir_change, record_fir_created, verify_fir_integrity
from backend.services.crypto_service import calculate_sha256, canonical_json, extract_canonical_fir_data
from backend.services.db import get_db_connection
from backend.services.notification_service import create_notification, notify_role


def format_ist_timestamp(dt: Optional[datetime] = None) -> Tuple[str, str, str]:
    """Format date and time in Indian Standard Time (IST)."""
    if not dt:
        dt = datetime.now()
    date_str = dt.strftime("%d %B %Y")
    time_str = dt.strftime("%H:%M IST")
    iso_str = dt.isoformat()
    return date_str, time_str, iso_str


def _next_fir_sequence(cursor) -> int:
    """Return the next FIR sequence number from the database (no year prefix)."""
    cursor.execute("SELECT fir_number FROM firs")
    highest = 0
    for row in cursor.fetchall():
        value = str(row["fir_number"] or '')
        match = re.search(r'(\d+)$', value)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _format_fir_number(sequence: int) -> str:
    return f"FIR-{sequence:06d}"


def generate_fir_number() -> Tuple[str, str]:
    """Generate a unique official FIR number (without a year) and tracking reference.

    The FIR number is derived from the highest existing sequence in SQL so it is
    stable, duplicate-free, and never generated in the browser.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    sequence = _next_fir_sequence(cursor)
    conn.close()
    fir_number = _format_fir_number(sequence)
    ref_number = f"REF-{uuid.uuid4().hex[:8].upper()}"
    return fir_number, ref_number


def generate_event_number() -> str:
    """Generate sequential/unique audit event number (e.g. EVT-000042)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) AS cnt FROM fir_change_events")
    count = cursor.fetchone()["cnt"] + 1
    conn.close()
    return f"EVT-{count:06d}"


def log_officer_activity(
    user: Dict[str, Any],
    action_type: str,
    fir_id: str,
    fir_number: str,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    details: Optional[str] = None
) -> None:
    """Record a server-side timestamped officer action event for operational case tracking."""
    if not user:
        return
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        log_id = f"act-{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        
        cursor.execute("""
            INSERT INTO officer_activity_logs (
                id, user_id, user_name, user_role, action_type, fir_id, fir_number,
                status_from, status_to, details, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            log_id, user.get("id", "sys"), user.get("name", "System"), user.get("role", "SYSTEM"),
            action_type, fir_id, fir_number, status_from, status_to, details, now_iso
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error logging officer activity: {e}")


def get_officer_activity_logs(fir_id: str) -> List[Dict[str, Any]]:
    """Retrieve server-timestamped activity log entries for a given FIR."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM officer_activity_logs
            WHERE fir_id = ?
            ORDER BY timestamp ASC
        """, (fir_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_operational_case_timeline(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Generate clean, operational case tracking timeline with server timestamps.
    Used by Verification Officers, Police Officers, and Citizens to track case progression:
    Citizen Submitted → Verification Received → Under Review → FIR Verified → Officer Assigned → Police Processing → Case Updates → Case Completed
    NEVER exposes cryptographic hashes, Merkle roots, or tamper workbench alerts.
    """
    fir = get_fir_by_id(fir_id, actor_user)
    if not fir:
        return []

    logs = get_officer_activity_logs(fir_id)
    timeline = []

    # 1. Citizen Submission Milestone
    sub_date = str(fir.get("created_at", ""))[:16].replace("T", " ")
    timeline.append({
        "stage": "Citizen Submitted",
        "title": "FIR Filed Online by Citizen",
        "description": f"Complainant {fir.get('citizen_name', 'Citizen')} registered initial FIR submission under category '{fir.get('incident_type')}'. Tracking Ref: {fir.get('reference_number')}.",
        "timestamp": sub_date,
        "actor_name": fir.get("citizen_name", "Citizen"),
        "actor_role": "CITIZEN",
        "icon": "edit_document",
        "color": "emerald"
    })

    # 2. Activity Logs Progression
    action_icons = {
        "FIR_SUBMITTED": ("Verification Received", "FIR Received in Verification Queue", "fact_check", "amber"),
        "FIR_EDITED": ("Under Review", "FIR Scrutinized & Structured", "edit", "indigo"),
        "FIR_VERIFIED": ("FIR Verified", "FIR Verification Approved & Accepted", "verified", "emerald"),
        "FIR_RETURNED": ("Needs Correction", "FIR Returned to Citizen for Correction", "undo", "red"),
        "OFFICER_ASSIGNMENT": ("Officer Assigned", "Investigating Police Officer Assigned", "local_police", "blue"),
        "POLICE_CASE_OPENED": ("Police Processing", "Assigned Police Officer Opened Case File", "folder_open", "purple"),
        "STATUS_UPDATED": ("Case Progress", "Case Investigation Status Updated", "update", "sky"),
    }

    for log in logs:
        atype = log.get("action_type")
        if atype == "FIR_SUBMITTED":
            continue  # Already added as milestone 1
        
        stage_name, default_title, icon, color = action_icons.get(atype, ("Case Activity", "Case Action Recorded", "info", "blue"))
        ts = str(log.get("timestamp", ""))[:16].replace("T", " ")
        
        timeline.append({
            "stage": stage_name,
            "title": f"{log.get('user_name', 'Officer')} ({log.get('user_role', 'OFFICER')}): {default_title}",
            "description": log.get("details", "") or f"Status changed from {log.get('status_from')} to {log.get('status_to')}",
            "timestamp": ts,
            "actor_name": log.get("user_name"),
            "actor_role": log.get("user_role"),
            "icon": icon,
            "color": color
        })

    # Fallback default milestones if logs are empty (e.g. legacy FIRs)
    if len(timeline) == 1:
        if fir.get("status") in ("VERIFIED", "UNDER_INVESTIGATION", "RESOLVED", "CLOSED"):
            timeline.append({
                "stage": "FIR Verified",
                "title": "FIR Verified & Accepted by Police Department",
                "description": f"FIR {fir.get('fir_number')} passed scrutiny review and was marked as VERIFIED.",
                "timestamp": str(fir.get("updated_at", ""))[:16].replace("T", " "),
                "actor_name": "Verification Bureau",
                "actor_role": "VERIFICATION_OFFICER",
                "icon": "verified",
                "color": "emerald"
            })
        if fir.get("assigned_officer_id") and fir.get("officer_name"):
            timeline.append({
                "stage": "Officer Assigned",
                "title": f"Assigned to {(fir.get('officer_rank') or 'Officer')} {fir.get('officer_name')}",
                "description": f"Badge {fir.get('officer_badge') or 'not recorded'} · Station: {fir.get('police_station') or 'not recorded'}",
                "timestamp": str(fir.get("updated_at", ""))[:16].replace("T", " "),
                "actor_name": fir.get("officer_name"),
                "actor_role": "OFFICER",
                "icon": "local_police",
                "color": "blue"
            })

    return timeline


def _enforce_citizen_access(actor_user: Optional[Dict[str, Any]]) -> None:
    """Block citizens whose account is not yet approved by a Verification Officer."""
    if actor_user and actor_user.get("role") == "CITIZEN":
        from backend.services.auth_service import assert_active_citizen
        assert_active_citizen(actor_user)


def create_fir(citizen_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Citizen files a new FIR online.
    1. Generates unique FIR & Reference number.
    2. Builds canonical JSON representation.
    3. Calculates SHA-256 hash (Version 1 hash H1).
    4. Stores FIR row in database.
    5. Stores immutable Version 1 snapshot in `fir_versions`.
    6. Submits genesis audit event to blockchain smart contract (`recordFIRCreated`).
    7. Creates citizen notification.
    """
    from backend.services.auth_service import assert_active_citizen, get_user_by_id
    assert_active_citizen(get_user_by_id(citizen_id))

    conn = get_db_connection()
    cursor = conn.cursor()
    conn.execute("BEGIN IMMEDIATE")

    fir_id = f"fir-{uuid.uuid4().hex[:12]}"
    fir_number = _format_fir_number(_next_fir_sequence(cursor))
    ref_number = f"REF-{uuid.uuid4().hex[:8].upper()}"
    now_dt = datetime.now()
    date_str, time_str, iso_now = format_ist_timestamp(now_dt)

    police_station = payload.get("police_station", "Unassigned")
    incident_type = payload.get("incident_type", "Cyber Crime & Online Fraud")
    incident_date = payload.get("incident_date", datetime.now().strftime("%Y-%m-%d"))
    incident_time = payload.get("incident_time", datetime.now().strftime("%H:%M"))
    incident_location = payload.get("incident_location", "Bangalore, Karnataka")
    description = payload.get("description", "")
    accused_details = payload.get("accused_details", "Unknown / Under Investigation")
    witness_details = payload.get("witness_details", "None provided")
    evidence_files = payload.get("evidence_files", "[]")
    assigned_officer_id = payload.get("assigned_officer_id")

    # Do NOT auto-assign officer - officer should be assigned by Verification Officer AFTER verification

    fir_dict = {
        "id": fir_id,
        "fir_number": fir_number,
        "reference_number": ref_number,
        "citizen_id": citizen_id,
        "assigned_officer_id": assigned_officer_id,  # Will be None until Verification Officer assigns
        "police_station": police_station,
        "status": "PENDING_VERIFICATION",  # Changed from SUBMITTED to PENDING_VERIFICATION
        "incident_type": incident_type,
        "incident_date": incident_date,
        "incident_time": incident_time,
        "incident_location": incident_location,
        "description": description,
        "accused_details": accused_details,
        "witness_details": witness_details,
        "evidence_files": evidence_files if isinstance(evidence_files, str) else json.dumps(evidence_files),
        "current_version": 1,
        "created_at": iso_now,
        "updated_at": iso_now
    }

    # Canonicalize and hash Version 1
    canonical_data = extract_canonical_fir_data(fir_dict)
    initial_hash = calculate_sha256(canonical_data)
    fir_dict["current_hash"] = initial_hash

    # Insert into FIRs table
    cursor.execute("""
        INSERT INTO firs (
            id, fir_number, reference_number, citizen_id, assigned_officer_id,
            police_station, status, incident_type, incident_date, incident_time,
            incident_location, description, accused_details, witness_details,
            evidence_files, current_version, current_hash, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fir_id, fir_number, ref_number, citizen_id, assigned_officer_id,
        police_station, "PENDING_VERIFICATION", incident_type, incident_date, incident_time,
        incident_location, description, accused_details, witness_details,
        fir_dict["evidence_files"], 1, initial_hash, iso_now, iso_now
    ))

    # Insert immutable Version 1 snapshot
    version_id = f"ver-{uuid.uuid4().hex[:12]}"
    cursor.execute("""
        INSERT INTO fir_versions (
            id, fir_id, version_number, snapshot_json, previous_hash,
            current_hash, created_by, created_at, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        version_id, fir_id, 1, json.dumps(fir_dict), None,
        initial_hash, citizen_id, iso_now, "Initial Online FIR Submission by Citizen"
    ))

    conn.commit()
    conn.close()

    # Record genesis proof on blockchain
    bc_res = record_fir_created(
        fir_id=fir_id,
        version=1,
        record_hash=initial_hash,
        actor_id=citizen_id,
        timestamp=iso_now
    )

    # Citizen Notification
    create_notification(
        user_id=citizen_id,
        fir_id=fir_id,
        title="✓ FIR Filed Successfully - Pending Verification",
        message=f"Your online FIR has been registered with number {fir_number} (Ref: {ref_number}). It is now pending verification by police department. You will be notified once verified.",
        notification_type="FIR_SUBMISSION",
        severity="SUCCESS"
    )

    # Notify all Verification Officers in the system - new FIR in their queue
    try:
        _conn = get_db_connection()
        _cursor = _conn.cursor()
        _cursor.execute("SELECT id FROM users WHERE role = 'VERIFICATION_OFFICER'")
        vo_rows = _cursor.fetchall()
        _conn.close()
        for vo in vo_rows:
            create_notification(
                user_id=vo["id"],
                fir_id=fir_id,
                title="New FIR Awaiting Scrutiny",
                message=f"A new citizen FIR ({fir_number}) has been submitted in category '{incident_type}'. Please review and process in the Verification Queue.",
                notification_type="NEW_FIR",
                severity="INFO"
            )
    except Exception:
        pass

    # No officer notification at creation time - officer will be notified when assigned by Verification Officer

    # Record activity log
    try:
        citizen_user = get_user_by_id(citizen_id) or {"id": citizen_id, "name": "Citizen", "role": "CITIZEN"}
        log_officer_activity(
            user=citizen_user,
            action_type="FIR_SUBMITTED",
            fir_id=fir_id,
            fir_number=fir_number,
            status_from=None,
            status_to="PENDING_VERIFICATION",
            details=f"Citizen registered new online FIR under category '{incident_type}'."
        )
    except Exception:
        pass

    fir_dict["blockchain_tx_id"] = bc_res.get("tx_id")
    fir_dict["blockchain_block"] = bc_res.get("block_index")
    return fir_dict


def update_fir(
    fir_id: str,
    actor_user: Dict[str, Any],
    updated_fields: Dict[str, Any],
    change_reason: str,
    ip_address: Optional[str] = "10.42.18.91 (Police Secure VPN)",
    device_info: Optional[str] = "Police CAD Terminal KA-BLR-04"
) -> Dict[str, Any]:
    """
    Authorized Police Officer modifies an existing FIR.
    1. Validates officer authorization (must be assigned officer, station lead, or admin).
    2. Validates the actor's edit permission; the change reason is optional.
    3. Loads current FIR and previous version hash (H_old).
    4. Computes changed fields diff (OLD vs NEW).
    5. Computes new canonical state and new SHA-256 hash (H_new).
    6. Creates new immutable version record (Version n+1).
    7. Submits audit event to blockchain smart contract (`recordFIRChange`).
    8. Records forensic audit change event with blockchain transaction ID.
    9. Creates Output A (Citizen Notification Only):
       - FIR number
       - Date/time of update
       - Simple text: "Your FIR has been updated by an authorized police officer."
       - (NO old/new values, NO fields list, NO officer badge, NO reason, NO hashes).
    10. Creates Output B (Authorized Officer Alert):
       - Officer alert with badge, version transition, fields count, and audit link.
    """
    # A reason is optional; when one is supplied it is recorded in the audit trail.
    change_reason = (change_reason or "").strip()

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    current_fir_row = cursor.fetchone()
    if not current_fir_row:
        conn.close()
        raise ValueError(f"FIR {fir_id} not found.")

    current_fir = dict(current_fir_row)

    if not can_user_modify_fir(actor_user, current_fir):
        conn.close()
        raise PermissionError("Forbidden: You are not authorized to modify this FIR. Only assigned officers or supervisors have edit permissions.")

    old_version = current_fir.get("current_version", 1)
    new_version = old_version + 1
    previous_hash = current_fir.get("current_hash")
    now_dt = datetime.now()
    date_str, time_str, iso_now = format_ist_timestamp(now_dt)

    # Determine what fields changed
    changed_fields_list = []
    old_values = {}
    new_values = {}

    allowed_updatable_fields = [
        "incident_location", "incident_type", "description",
        "accused_details", "witness_details", "status", "police_station"
    ]

    updated_fir_dict = dict(current_fir)

    for field in allowed_updatable_fields:
        if field in updated_fields:
            old_val = str(current_fir.get(field, "") or "")
            new_val = str(updated_fields.get(field, "") or "")
            if old_val != new_val:
                changed_fields_list.append(field)
                old_values[field] = old_val
                new_values[field] = new_val
                updated_fir_dict[field] = new_val

    if not changed_fields_list:
        conn.close()
        raise ValueError("No changes were detected in the submitted fields.")

    updated_fir_dict["current_version"] = new_version
    updated_fir_dict["updated_at"] = iso_now

    # Compute new canonical hash H_new
    new_canonical = extract_canonical_fir_data(updated_fir_dict)
    new_hash = calculate_sha256(new_canonical)
    updated_fir_dict["current_hash"] = new_hash

    # 1. Update FIRs table
    cursor.execute("""
        UPDATE firs SET
            incident_type = ?,
            incident_location = ?,
            description = ?,
            accused_details = ?,
            witness_details = ?,
            status = ?,
            police_station = ?,
            current_version = ?,
            current_hash = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        updated_fir_dict["incident_type"],
        updated_fir_dict["incident_location"],
        updated_fir_dict["description"],
        updated_fir_dict["accused_details"],
        updated_fir_dict["witness_details"],
        updated_fir_dict["status"],
        updated_fir_dict["police_station"],
        new_version,
        new_hash,
        iso_now,
        fir_id
    ))

    # 2. Insert new immutable version
    version_id = f"ver-{uuid.uuid4().hex[:12]}"
    cursor.execute("""
        INSERT INTO fir_versions (
            id, fir_id, version_number, snapshot_json, previous_hash,
            current_hash, created_by, created_at, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        version_id, fir_id, new_version, json.dumps(updated_fir_dict), previous_hash,
        new_hash, actor_user.get("id"), iso_now, change_reason.strip()
    ))

    conn.commit()
    conn.close()

    # 3. Submit audit event to blockchain
    event_payload = {
        "fir_id": fir_id,
        "version": new_version,
        "previous_version": old_version,
        "changed_fields": changed_fields_list,
        "old_values": old_values,
        "new_values": new_values,
        "reason": change_reason.strip(),
        "actor_badge": actor_user.get("badge_number", "N/A"),
        "timestamp": iso_now
    }
    event_hash = calculate_sha256(event_payload)

    bc_res = record_fir_change(
        fir_id=fir_id,
        version=new_version,
        previous_hash=previous_hash,
        new_hash=new_hash,
        actor_id=actor_user.get("id"),
        event_hash=event_hash,
        reason=change_reason.strip(),
        timestamp=iso_now
    )

    # 4. Insert FIR Change Event into forensic audit table
    conn = get_db_connection()
    cursor = conn.cursor()
    change_event_id = f"evt-{uuid.uuid4().hex[:12]}"
    event_number = generate_event_number()

    cursor.execute("""
        INSERT INTO fir_change_events (
            id, event_number, fir_id, version_id, previous_version, new_version,
            actor_id, actor_name, actor_badge, actor_role, event_type,
            changed_fields_json, old_values_json, new_values_json, reason,
            timestamp, timezone, ip_address, device_info, previous_hash,
            new_hash, blockchain_tx_id, blockchain_block, blockchain_status, event_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        change_event_id, event_number, fir_id, version_id, old_version, new_version,
        actor_user.get("id"), actor_user.get("name", "Officer"),
        actor_user.get("badge_number", "N/A"), actor_user.get("role", "OFFICER"),
        "AUTHORIZED_FIR_UPDATE", json.dumps(changed_fields_list), json.dumps(old_values),
        json.dumps(new_values), change_reason.strip(), iso_now, "IST (UTC+05:30)",
        ip_address, device_info, previous_hash, new_hash, bc_res.get("tx_id"),
        bc_res.get("block_index"), "CONFIRMED", event_hash
    ))
    conn.commit()
    conn.close()

    # 5. OUTPUT A — CITIZEN NOTIFICATION ONLY (Strict Visibility Rule)
    # Citizen receives simple notification text:
    # "Your FIR has been updated by an authorized police officer."
    # NO old/new values, NO changed fields, NO officer name/ID, NO reasons, NO hashes.
    citizen_id = current_fir.get("citizen_id")
    citizen_msg = (
        f"Your FIR has been updated by an authorized police officer.\n\n"
        f"FIR: {current_fir.get('fir_number')}\n"
        f"Updated: {date_str}, {time_str}"
    )

    create_notification(
        user_id=citizen_id,
        fir_id=fir_id,
        title="🔔 Your FIR Has Been Updated",
        message=citizen_msg,
        notification_type="FIR_UPDATE",
        event_id=change_event_id,
        severity="INFO"
    )

    # 6. OUTPUT B — role-based delivery of the amendment (§5 delivery matrix)
    case_reference = current_fir.get("fir_number")
    actor_label = f"{actor_user.get('role', 'OFFICER').replace('_', ' ').title()} {actor_user.get('name', 'Officer')}"
    assigned_officer_id = current_fir.get("assigned_officer_id")

    if assigned_officer_id and assigned_officer_id != actor_user.get("id"):
        create_notification(
            user_id=assigned_officer_id,
            fir_id=fir_id,
            title="Case Record Amended",
            message=(
                f"FIR {case_reference} was amended by {actor_label}. "
                f"Version {old_version} → {new_version}, {len(changed_fields_list)} field(s) changed. "
                f"Reason: {change_reason or 'Not provided'}"
            ),
            notification_type="FIR_UPDATE",
            severity="INFO",
            event_id=f"fir-assigned-officer-{change_event_id}",
        )

    notify_role(
        "VERIFICATION_OFFICER",
        "FIR Record Updated",
        (
            f"FIR {case_reference} was amended by {actor_label} "
            f"(version {old_version} → {new_version}, {len(changed_fields_list)} field(s) changed)."
        ),
        f"fir-update-verification-{change_event_id}",
        fir_id=fir_id,
        notification_type="FIR_UPDATE",
        severity="INFO",
        exclude_user_id=actor_user.get("id"),
    )

    notify_role(
        "ADMIN",
        "FIR Amendment Audit Record",
        (
            f"FIR {case_reference}: {actor_label} changed {', '.join(changed_fields_list)} "
            f"in version {old_version} → {new_version}. Reason: {change_reason or 'Not provided'}. "
            f"Audit event {event_number}."
        ),
        f"fir-update-audit-{change_event_id}",
        fir_id=fir_id,
        notification_type="AUDIT_ALERT",
        severity="WARNING",
        exclude_user_id=actor_user.get("id"),
    )

    # Server-side activity log for operational case tracking
    try:
        log_officer_activity(
            user=actor_user,
            action_type="FIR_EDITED",
            fir_id=fir_id,
            fir_number=current_fir.get("fir_number", fir_id),
            status_from=current_fir.get("status"),
            status_to=updated_fir_dict.get("status", current_fir.get("status")),
            details=f"{actor_user.get('role', 'OFFICER')} {actor_user.get('name', 'Officer')} updated {len(changed_fields_list)} field(s). Reason: {change_reason or 'Not provided'}"
        )
    except Exception:
        pass

    return {
        "success": True,
        "event_id": change_event_id,
        "event_number": event_number,
        "fir_id": fir_id,
        "fir_number": current_fir.get("fir_number"),
        "old_version": old_version,
        "new_version": new_version,
        "previous_hash": previous_hash,
        "new_hash": new_hash,
        "changed_fields": changed_fields_list,
        "old_values": old_values,
        "new_values": new_values,
        "change_reason": change_reason.strip(),
        "actor_badge": actor_user.get("badge_number", "N/A"),
        "timestamp": iso_now,
        "timezone": "IST (UTC+05:30)",
        "blockchain_tx_id": bc_res.get("tx_id"),
        "blockchain_block": bc_res.get("block_index"),
        "blockchain_status": "VERIFIED"
    }


def get_pending_firs_for_verification(actor_user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Retrieve FIRs that are pending verification.
    Accessible to officers, verification officers, and administrators.
    """
    if not actor_user or actor_user.get("role") not in ("OFFICER", "VERIFICATION_OFFICER", "ADMIN"):
        raise PermissionError("Only officers and administrators can access pending FIRs.")

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


def get_firs(
    actor_user: Optional[Dict[str, Any]] = None,
    status_filter: Optional[str] = None,
    search_query: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieve list of FIRs filtered by user permissions and optional status/search."""
    _enforce_citizen_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               o.name AS officer_name, o.badge_number AS officer_badge, o.rank AS officer_rank
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE 1=1
    """
    params = []

    if actor_user:
        role = actor_user.get("role")
        user_id = actor_user.get("id")
        if role == "CITIZEN":
            query += " AND f.citizen_id = ?"
            params.append(user_id)

    if status_filter and status_filter.upper() != "ALL":
        query += " AND UPPER(f.status) = ?"
        params.append(status_filter.upper())

    if search_query:
        search_like = f"%{search_query.strip().lower()}%"
        query += """ AND (
            LOWER(f.fir_number) LIKE ? OR
            LOWER(f.reference_number) LIKE ? OR
            LOWER(f.incident_location) LIKE ? OR
            LOWER(f.incident_type) LIKE ? OR
            LOWER(u.name) LIKE ?
        )"""
        params.extend([search_like, search_like, search_like, search_like, search_like])

    query += " ORDER BY f.created_at DESC"
    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if actor_user and actor_user.get("role") == "OFFICER":
        rows = [row for row in rows if can_user_access_fir(actor_user, row)]

    # Attach live cryptographic integrity badge status — Authorized Officers only.
    if actor_user and actor_user.get("role") == "ADMIN":
        for row in rows:
            integrity = verify_fir_integrity(row["id"])
            row["integrity_status"] = integrity.get("status")
            row["integrity_valid"] = integrity.get("is_valid", False)
            row["blockchain_block"] = integrity.get("blockchain_block")

    return rows


def get_fir_by_id(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Get basic case details for an FIR, enforcing access authorization."""
    _enforce_citizen_access(actor_user)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT f.*, u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               u.username AS citizen_username,
               u.gov_id_masked, u.address AS citizen_address,
               o.name AS officer_name, o.badge_number AS officer_badge, o.rank AS officer_rank, o.station AS officer_station,
               (SELECT a.assigned_at FROM officer_assignments a
                WHERE a.fir_id = f.id AND a.officer_id = f.assigned_officer_id
                ORDER BY a.assigned_at DESC LIMIT 1) AS assigned_at
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        WHERE f.id = ?
    """, (fir_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    fir_dict = dict(row)

    if actor_user and not can_user_access_fir(actor_user, fir_dict):
        raise PermissionError("Forbidden: You are not authorized to view this FIR.")

    if actor_user and actor_user.get("role") == "ADMIN":
        fir_dict["integrity"] = verify_fir_integrity(fir_id)
    return fir_dict


def get_fir_versions(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Retrieve full version history for an FIR.
    Restricted to Authorized Officers; version hashes stay hidden from every other role.
    """
    fir = get_fir_by_id(fir_id, actor_user)
    if not fir:
        return []

    if actor_user and not can_user_access_fir_audit(actor_user, fir):
        raise PermissionError("Forbidden: FIR version history and hashes are restricted to Authorized Officers.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT v.*, u.name AS creator_name, u.role AS creator_role, u.badge_number AS creator_badge
        FROM fir_versions v
        LEFT JOIN users u ON v.created_by = u.id
        WHERE v.fir_id = ?
        ORDER BY v.version_number ASC
    """, (fir_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_fir_changes(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Retrieve all logged change events with forensic diffs for an FIR.
    Restricted to Authorized Officers.
    """
    fir = get_fir_by_id(fir_id, actor_user)
    if not fir:
        return []

    if actor_user and not can_user_access_fir_audit(actor_user, fir):
        raise PermissionError("Forbidden: FIR change audit history is restricted to Authorized Officers.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, v.version_number
        FROM fir_change_events e
        LEFT JOIN fir_versions v ON e.version_id = v.id
        WHERE e.fir_id = ?
        ORDER BY e.timestamp ASC
    """, (fir_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for r in rows:
        try:
            r["changed_fields"] = json.loads(r["changed_fields_json"])
            r["old_values"] = json.loads(r["old_values_json"])
            r["new_values"] = json.loads(r["new_values_json"])
        except Exception:
            pass

    return rows


def get_change_event_by_id(event_id_or_number: str, actor_user: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Retrieve a single change audit event by ID or event number with authorization enforcement."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT e.*, f.fir_number, f.reference_number, f.incident_type, f.police_station, f.assigned_officer_id, f.citizen_id
        FROM fir_change_events e
        LEFT JOIN firs f ON e.fir_id = f.id
        WHERE e.id = ? OR e.event_number = ?
    """, (event_id_or_number, event_id_or_number))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    r = dict(row)

    if actor_user and not can_user_access_fir_audit(actor_user, r):
        raise PermissionError("Forbidden: Detailed audit inspection is restricted to authorized investigating officers and supervisors.")

    try:
        r["changed_fields"] = json.loads(r["changed_fields_json"])
        r["old_values"] = json.loads(r["old_values_json"])
        r["new_values"] = json.loads(r["new_values_json"])
    except Exception:
        pass
    return r


def get_fir_timeline(fir_id: str, actor_user: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    Generate chronological timeline.
    - If user is CITIZEN: shows simple, public case milestones (Submitted, Under Investigation, Updated) without internal officer IDs, diffs, or hashes.
    - If user is AUTHORIZED POLICE: shows complete forensic timeline with event numbers and links to audit trail.
    """
    fir = get_fir_by_id(fir_id, actor_user)
    if not fir:
        return []

    is_citizen = actor_user and actor_user.get("role") == "CITIZEN"
    can_audit = actor_user and can_user_access_fir_audit(actor_user, fir)

    timeline = []

    # 1. Submission event
    timeline.append({
        "type": "FIR_CREATED",
        "title": "FIR Filed Online by Citizen" if is_citizen else "● FIR CREATED",
        "description": f"Initial FIR registered under {fir.get('incident_type')}. Reference {fir.get('reference_number')} generated.",
        "timestamp": fir.get("created_at"),
        "icon": "edit_document",
        "color": "emerald",
        "badge": "Submitted",
        "fir_id": fir_id
    })

    # 2. Officer Assignment
    if fir.get("assigned_officer_id"):
        desc = (
            f"Assigned to {fir.get('police_station') or 'police station not recorded'}"
            if is_citizen
            else f"Badge {fir.get('officer_badge') or 'not recorded'} · "
                 f"{fir.get('police_station') or 'station not recorded'}"
        )
        timeline.append({
            "type": "FIR_ASSIGNED",
            "title": "Case Assigned to Police Station" if is_citizen else f"● FIR ASSIGNED to {(fir.get('officer_rank') or 'Officer')} {fir.get('officer_name')}",
            "description": desc,
            "timestamp": fir.get("created_at"),
            "icon": "local_police",
            "color": "blue",
            "badge": "Assigned",
            "fir_id": fir_id
        })

    # 3. Modifications
    if can_audit:
        changes = get_fir_changes(fir_id, actor_user)
        for ch in changes:
            fields = ch.get("changed_fields", [])
            timeline.append({
                "type": "FIR_UPDATED",
                "title": f"● FIR UPDATED (v{ch.get('previous_version', 1)} → v{ch.get('new_version', 2)})",
                "description": f"Officer: {ch.get('actor_badge', 'N/A')} · {len(fields)} fields changed\nReason: {ch.get('reason') or 'Not provided'}",
                "timestamp": ch.get("timestamp"),
                "icon": "update",
                "color": "indigo",
                "badge": f"Event #{ch.get('event_number', 'EVT-001')}",
                "event_id": ch.get("id"),
                "event_number": ch.get("event_number"),
                "fir_id": fir_id,
                "fields_count": len(fields)
            })
    elif is_citizen:
        # Simple high-level status progression for citizen
        ver = fir.get("current_version", 1)
        if ver > 1:
            timeline.append({
                "type": "FIR_STATUS_UPDATE",
                "title": "FIR Record Updated by Police Department",
                "description": f"Case investigation progress updated. Status: {fir.get('status')}.",
                "timestamp": fir.get("updated_at"),
                "icon": "update",
                "color": "blue",
                "badge": "Updated",
                "fir_id": fir_id
            })

    # 4. Latest Blockchain Integrity state (Only for authorized officers/supervisors)
    integrity = fir.get("integrity", {})
    if can_audit:
        if integrity.get("is_valid"):
            timeline.append({
                "type": "BLOCKCHAIN_RECORDED",
                "title": "● BLOCKCHAIN RECORDED & VERIFIED",
                "description": f"Cryptographic SHA-256 seal confirmed on-chain in Block #{integrity.get('blockchain_block')}. Tx ID: {integrity.get('blockchain_tx_id')}",
                "timestamp": integrity.get("verified_at", datetime.now().isoformat()),
                "icon": "verified",
                "color": "emerald",
                "badge": "✓ BLOCKCHAIN VERIFIED",
                "fir_id": fir_id
            })
        elif integrity.get("status") == "TAMPER_DETECTED":
            timeline.append({
                "type": "TAMPER_ALERT",
                "title": "🔴 FIR TAMPERING DETECTED",
                "description": f"State mismatch against on-chain proof. Expected: {integrity.get('expected_hash', '')[:12]}..., Current: {integrity.get('database_hash', '')[:12]}...",
                "timestamp": integrity.get("verified_at", datetime.now().isoformat()),
                "icon": "warning",
                "color": "red",
                "badge": "🔴 TAMPERING DETECTED",
                "fir_id": fir_id
            })

    return timeline


def verify_fir(fir_id: str, verified_by_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Verify a pending FIR and change status from PENDING_VERIFICATION to VERIFIED.
    This is done by verification officers or police officers after reviewing the submitted FIR.
    Sends notifications to citizen about verification.
    """
    if not verified_by_user or verified_by_user.get("role") not in ("OFFICER", "VERIFICATION_OFFICER", "ADMIN"):
        raise PermissionError("Only verification officers, police officers, and administrators can verify FIRs.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    fir = cursor.fetchone()
    if not fir:
        conn.close()
        raise ValueError(f"FIR {fir_id} not found.")

    date_str, time_str, iso_now = format_ist_timestamp()

    # Update status to VERIFIED
    cursor.execute("""
        UPDATE firs SET status = 'VERIFIED', updated_at = ? WHERE id = ?
    """, (iso_now, fir_id))

    conn.commit()
    conn.close()

    # Notify Citizen - FIR Verified
    create_notification(
        user_id=fir["citizen_id"],
        fir_id=fir_id,
        title="✓ Your FIR Has Been Verified",
        message=f"Your FIR {fir['fir_number']} has been verified and accepted by the police department. The case will be assigned to an investigating officer shortly.",
        notification_type="FIR_VERIFIED",
        severity="SUCCESS",
        event_id=f"fir-verified-citizen-{fir_id}-{fir['status']}",
    )

    # Notify verifying officer
    create_notification(
        user_id=verified_by_user.get("id"),
        fir_id=fir_id,
        title="FIR Verification Complete",
        message=f"FIR {fir['fir_number']} has been verified and marked as VERIFIED.",
        notification_type="FIR_VERIFIED",
        severity="SUCCESS",
        event_id=f"fir-verified-actor-{fir_id}-{fir['status']}",
    )

    try:
        log_officer_activity(
            user=verified_by_user,
            action_type="FIR_VERIFIED",
            fir_id=fir_id,
            fir_number=fir['fir_number'],
            status_from="PENDING_VERIFICATION",
            status_to="VERIFIED",
            details=f"Verification Officer {verified_by_user.get('name')} completed scrutiny and verified FIR."
        )
    except Exception:
        pass

    return {
        "success": True,
        "fir_id": fir_id,
        "fir_number": fir['fir_number'],
        "status": "VERIFIED",
        "verified_by": verified_by_user.get("badge_number", verified_by_user.get("id")),
        "verified_at": iso_now
    }


def reject_fir(fir_id: str, rejected_by_user: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """
    Return/Reject a pending FIR requiring correction by the citizen.
    Changes status to NEEDS_CORRECTION and notifies the citizen with the reason.
    """
    if not rejected_by_user or rejected_by_user.get("role") not in ("OFFICER", "VERIFICATION_OFFICER", "ADMIN"):
        raise PermissionError("Only verification officers and administrators can return FIRs.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    fir = cursor.fetchone()
    if not fir:
        conn.close()
        raise ValueError(f"FIR {fir_id} not found.")

    date_str, time_str, iso_now = format_ist_timestamp()

    # Update status to NEEDS_CORRECTION
    cursor.execute("""
        UPDATE firs SET status = 'NEEDS_CORRECTION', updated_at = ? WHERE id = ?
    """, (iso_now, fir_id))

    conn.commit()
    conn.close()

    # Notify Citizen - FIR Returned for Correction
    create_notification(
        user_id=fir["citizen_id"],
        fir_id=fir_id,
        title="⚠ FIR Returned for Correction / Resubmission",
        message=f"Your FIR {fir['fir_number']} has been reviewed by the Verification Officer and returned for correction. Reason: {reason}",
        notification_type="FIR_REJECTED",
        severity="WARNING"
    )

    try:
        log_officer_activity(
            user=rejected_by_user,
            action_type="FIR_RETURNED",
            fir_id=fir_id,
            fir_number=fir['fir_number'],
            status_from=fir["status"],
            status_to="NEEDS_CORRECTION",
            details=f"Verification Officer {rejected_by_user.get('name')} returned FIR for citizen correction: {reason}"
        )
    except Exception:
        pass

    return {
        "success": True,
        "fir_id": fir_id,
        "fir_number": fir['fir_number'],
        "status": "NEEDS_CORRECTION",
        "rejected_by": rejected_by_user.get("badge_number", rejected_by_user.get("id")),
        "reason": reason,
        "rejected_at": iso_now
    }


def assign_officer_to_fir(fir_id: str, officer_id: str, assigned_by_user: Dict[str, Any]) -> bool:
    """Assign or reassign the investigating officer with a preserved audit history.

    Only Verification Officers, Administrators, and authorised police staff can
    assign. Repeating the same assignment is a safe no-op; a different officer
    reassignment marks the previous assignment record REASSIGNED.
    """
    if not assigned_by_user or assigned_by_user.get("role") not in (
        "VERIFICATION_OFFICER", "ADMIN", "OFFICER"
    ):
        raise PermissionError("Only authorised police personnel can assign investigating officers.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        return False
    fir = dict(fir_row)

    cursor.execute(
        "SELECT * FROM users WHERE id = ? AND role = 'OFFICER' AND status = 'ACTIVE'",
        (officer_id,),
    )
    officer_row = cursor.fetchone()
    if not officer_row:
        conn.close()
        return False
    officer = dict(officer_row)

    previous_officer_id = fir.get("assigned_officer_id")
    if previous_officer_id == officer_id:
        conn.close()
        return True

    date_str, time_str, iso_now = format_ist_timestamp()
    assign_id = f"asg-{uuid.uuid4().hex[:12]}"

    cursor.execute("""
        UPDATE officer_assignments
        SET status = 'REASSIGNED'
        WHERE fir_id = ? AND status = 'ACTIVE'
    """, (fir_id,))
    cursor.execute(
        "UPDATE firs SET assigned_officer_id = ?, updated_at = ? WHERE id = ?",
        (officer_id, iso_now, fir_id),
    )

    if fir["complaint_id"]:
        cursor.execute("""
            UPDATE complaints
            SET assigned_officer_id = ?, assigned_officer_name = ?,
                assigned_at = COALESCE(assigned_at, ?), updated_at = ?
            WHERE id = ?
        """, (officer_id, officer["name"], iso_now, iso_now, fir["complaint_id"]))

    cursor.execute("""
        INSERT INTO officer_assignments (
            id, fir_id, officer_id, assigned_by, assigned_at, status
        ) VALUES (?, ?, ?, ?, ?, 'ACTIVE')
    """, (assign_id, fir_id, officer_id, assigned_by_user.get("id"), iso_now))

    complaint_reference = None
    if fir.get("complaint_id"):
        cursor.execute("SELECT reference FROM complaints WHERE id = ?", (fir["complaint_id"],))
        ref_row = cursor.fetchone()
        complaint_reference = ref_row["reference"] if ref_row else None
    cursor.execute("SELECT name FROM users WHERE id = ?", (fir["citizen_id"],))
    citizen_row = cursor.fetchone()
    citizen_name = citizen_row["name"] if citizen_row else "Citizen"

    conn.commit()
    conn.close()

    phone = str(officer.get("phone") or "")
    contact = phone if any(ch.isdigit() for ch in phone) else "Contact not recorded"
    rank = officer.get("rank") or "Investigating Officer"
    station = officer.get("station") or fir.get("police_station") or "Police Department"

    # Notify the assigned officer with the complaint reference and FIR number.
    create_notification(
        user_id=officer_id,
        fir_id=fir_id,
        complaint_id=fir.get("complaint_id"),
        title="New Case Assigned",
        message=(
            f"You have been assigned as the investigating officer for FIR {fir['fir_number']}"
            f" (Citizen: {citizen_name})"
            + (f", complaint {complaint_reference}" if complaint_reference else "")
            + f". Open your portal to review the authorised case file and FIR document."
        ),
        notification_type="OFFICER_ASSIGNMENT",
        severity="INFO",
        event_id=f"officer-assigned-{fir_id}-{officer_id}-{iso_now}",
    )

    # Notify the citizen with the officer's authorised identity and contact details.
    create_notification(
        user_id=fir["citizen_id"],
        fir_id=fir_id,
        complaint_id=fir.get("complaint_id"),
        title="Investigating Officer Assigned",
        message=(
            f"Your FIR {fir['fir_number']} has been assigned to {rank} {officer['name']} "
            f"({station}, Badge {officer.get('badge_number') or 'N/A'}). "
            f"Contact: {contact}. Chat with your assigned officer is now available."
        ),
        notification_type="OFFICER_ASSIGNMENT",
        severity="SUCCESS",
        event_id=f"citizen-officer-assigned-{fir_id}-{officer_id}-{iso_now}",
    )

    if previous_officer_id and previous_officer_id != officer_id:
        create_notification(
            user_id=previous_officer_id,
            fir_id=fir_id,
            title="Case Reassigned",
            message=(
                f"FIR {fir['fir_number']} has been reassigned to another investigating officer "
                "through the authorised assignment workflow."
            ),
            notification_type="OFFICER_ASSIGNMENT",
            severity="WARNING",
            event_id=f"officer-reassigned-{fir_id}-{previous_officer_id}-{iso_now}",
        )

    # §5 delivery matrix for a police assignment: the verification desk that queued
    # the case and the audit desk both track the assignment outcome.
    assigning_role = assigned_by_user.get("role", "OFFICER").replace("_", " ").title()
    assigner_label = f"{assigning_role} {assigned_by_user.get('name', 'Officer')}"

    notify_role(
        "VERIFICATION_OFFICER",
        "Investigating Officer Assigned",
        (f"FIR {fir['fir_number']} was assigned to {rank} {officer['name']} ({station}) "
         f"by {assigner_label}."),
        f"assignment-verification-{fir_id}-{officer_id}-{iso_now}",
        fir_id=fir_id,
        complaint_id=fir.get("complaint_id"),
        notification_type="OFFICER_ASSIGNMENT",
        severity="INFO",
        exclude_user_id=assigned_by_user.get("id"),
    )

    notify_role(
        "ADMIN",
        "Officer Assignment Audit Record",
        (f"FIR {fir['fir_number']}: {assigner_label} assigned {rank} {officer['name']} "
         f"({station}, Badge {officer.get('badge_number') or 'N/A'}) as investigating officer."
         + (" The previous assignment record was superseded." if previous_officer_id else "")),
        f"assignment-audit-{fir_id}-{officer_id}-{iso_now}",
        fir_id=fir_id,
        complaint_id=fir.get("complaint_id"),
        notification_type="AUDIT_ALERT",
        severity="INFO",
        exclude_user_id=assigned_by_user.get("id"),
    )

    try:
        log_officer_activity(
            user=assigned_by_user,
            action_type="OFFICER_ASSIGNMENT",
            fir_id=fir_id,
            fir_number=fir['fir_number'],
            status_from=fir["status"],
            status_to=fir["status"],
            details=(
                f"Assigned lead investigating officer {rank} {officer['name']} "
                f"({officer.get('badge_number') or 'N/A'})."
                + (f" Previous officer: {previous_officer_id}." if previous_officer_id else "")
            )
        )
    except Exception:
        pass

    try:
        from backend.services.case_tracking_service import (
            CASE_STAGES,
            get_current_case_stage,
            initialize_case_tracking,
            normalize_stage,
            update_case_stage,
        )
        current_stage = normalize_stage(get_current_case_stage(fir_id))
        if not current_stage:
            initialize_case_tracking(fir_id, assigned_by_user, 'OFFICER_ASSIGNED')
        elif (current_stage in CASE_STAGES
              and CASE_STAGES.index(current_stage) < CASE_STAGES.index('OFFICER_ASSIGNED')):
            update_case_stage(
                fir_id, 'OFFICER_ASSIGNED', assigned_by_user,
                remarks=(
                    f"{rank} {officer['name']} assigned as investigating officer "
                    f"({station}, Badge {officer.get('badge_number') or 'N/A'})."
                ),
                assigned_officer_id=officer_id,
            )
    except Exception as exc:
        print(f"Case tracking assignment update error: {exc}")

    try:
        from backend.services.realtime_events import publish
        publish({
            'type': 'FIR_UPDATED',
            'fir_id': fir_id,
            'fir_number': fir['fir_number'],
            'citizen_id': fir['citizen_id'],
            'officer_id': officer_id,
            'previous_officer_id': previous_officer_id,
        })
    except Exception:
        pass

    return True


def create_fir_from_complaint(complaint_id: str, officer_user: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create an official FIR from a verified complaint.
    Only police officers, verification officers, and admins can perform this action.
    Links the new FIR to the originating complaint and marks the complaint as FIR_CREATED.
    """
    if not officer_user or officer_user.get("role") not in ("OFFICER", "VERIFICATION_OFFICER", "ADMIN"):
        raise PermissionError("Only authorized police officers can register FIRs from complaints.")

    conn = get_db_connection()
    cursor = conn.cursor()
    conn.execute("BEGIN IMMEDIATE")

    # Fetch the complaint
    cursor.execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,))
    _row = cursor.fetchone()
    if not _row:
        conn.close()
        raise ValueError(f"Complaint {complaint_id} not found.")
    complaint = dict(_row)

    if complaint["status"] == "FIR_CREATED":
        conn.close()
        raise ValueError("An FIR has already been created for this complaint.")

    # A pre-assigned investigating officer (set during complaint assignment) is
    # carried into the FIR. A police officer registering the complaint directly
    # becomes the investigating officer. Verification/Admin staff never become
    # the investigating officer.
    investigating_officer_id = None
    investigating_officer_name = None
    if complaint.get("assigned_officer_id"):
        cursor.execute(
            "SELECT id, name, role, status FROM users WHERE id = ?",
            (complaint["assigned_officer_id"],),
        )
        pre_assigned = cursor.fetchone()
        if pre_assigned and pre_assigned["role"] == "OFFICER" and pre_assigned["status"] == "ACTIVE":
            investigating_officer_id = pre_assigned["id"]
            investigating_officer_name = pre_assigned["name"]

    if not investigating_officer_id and officer_user.get("role") == "OFFICER":
        investigating_officer_id = officer_user.get("id")
        investigating_officer_name = officer_user.get("name")

    # Build FIR payload from complaint data
    payload = {
        "police_station": complaint.get("police_station") or officer_user.get("station") or "Police station not recorded",
        "incident_type": complaint["category"],
        "incident_date": complaint.get("incident_date") or str(complaint["submitted_at"])[:10],
        "incident_time": complaint.get("incident_time") or str(complaint["submitted_at"])[11:16] or datetime.now().strftime("%H:%M"),
        "incident_location": complaint["location"],
        "description": complaint["description"],
        "accused_details": complaint.get("accused_details") or "Under Investigation",
        "witness_details": complaint.get("witness_details") or "None provided",
        "evidence_files": complaint.get("evidence_files") or "[]",
        "assigned_officer_id": investigating_officer_id,
    }

    fir_id = f"fir-{uuid.uuid4().hex[:12]}"
    fir_number = _format_fir_number(_next_fir_sequence(cursor))
    ref_number = f"REF-{uuid.uuid4().hex[:8].upper()}"
    now_dt = datetime.now()
    date_str, time_str, iso_now = format_ist_timestamp(now_dt)

    fir_dict = {
        "id": fir_id,
        "fir_number": fir_number,
        "reference_number": ref_number,
        "citizen_id": complaint["citizen_id"],
        "assigned_officer_id": payload["assigned_officer_id"],
        "police_station": payload["police_station"],
        "status": "UNDER_INVESTIGATION",
        "incident_type": payload["incident_type"],
        "incident_date": payload["incident_date"],
        "incident_time": payload["incident_time"],
        "incident_location": payload["incident_location"],
        "description": payload["description"],
        "accused_details": payload["accused_details"],
        "witness_details": payload["witness_details"],
        "evidence_files": payload["evidence_files"],
        "current_version": 1,
        "created_at": iso_now,
        "updated_at": iso_now,
        "complaint_id": complaint_id,
    }

    canonical_data = extract_canonical_fir_data(fir_dict)
    initial_hash = calculate_sha256(canonical_data)
    fir_dict["current_hash"] = initial_hash

    # Insert FIR row
    cursor.execute("""
        INSERT INTO firs (
            id, fir_number, reference_number, citizen_id, assigned_officer_id,
            police_station, status, incident_type, incident_date, incident_time,
            incident_location, description, accused_details, witness_details,
            evidence_files, current_version, current_hash, created_at, updated_at,
            complaint_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        fir_id, fir_number, ref_number, complaint["citizen_id"], payload["assigned_officer_id"],
        payload["police_station"], "UNDER_INVESTIGATION", payload["incident_type"],
        payload["incident_date"], payload["incident_time"], payload["incident_location"],
        payload["description"], payload["accused_details"], payload["witness_details"],
        payload["evidence_files"], 1, initial_hash, iso_now, iso_now, complaint_id
    ))

    # Insert Version 1 snapshot
    version_id = f"ver-{uuid.uuid4().hex[:12]}"
    cursor.execute("""
        INSERT INTO fir_versions (id, fir_id, version_number, snapshot_json,
            previous_hash, current_hash, created_by, created_at, change_reason)
        VALUES (?, ?, 1, ?, NULL, ?, ?, ?, ?)
    """, (version_id, fir_id, canonical_json(fir_dict), initial_hash,
          officer_user["id"], iso_now, "Initial FIR created from verified complaint"))

    if investigating_officer_id:
        cursor.execute(
            """
            SELECT id FROM officer_assignments
            WHERE fir_id = ? AND officer_id = ? AND status = 'ACTIVE'
            """,
            (fir_id, investigating_officer_id),
        )
        if cursor.fetchone() is None:
            cursor.execute("""
                INSERT INTO officer_assignments (
                    id, fir_id, officer_id, assigned_by, assigned_at, status
                ) VALUES (?, ?, ?, ?, ?, 'ACTIVE')
            """, (
                f"asg-{uuid.uuid4().hex[:12]}", fir_id, investigating_officer_id,
                officer_user.get("id"), iso_now,
            ))

    cursor.execute("""
        UPDATE complaints
        SET status = 'FIR_CREATED', fir_id = ?, assigned_officer_id = ?,
            assigned_officer_name = ?, assigned_at = COALESCE(assigned_at, ?), updated_at = ?
        WHERE id = ?
    """, (fir_id, investigating_officer_id, investigating_officer_name, iso_now, iso_now, complaint_id))

    conn.commit()
    conn.close()

    # Blockchain genesis block
    try:
        record_fir_created(
            fir_id=fir_id,
            version=1,
            record_hash=initial_hash,
            actor_id=officer_user["id"],
            timestamp=iso_now,
        )
    except Exception as exc:
        print(f"Blockchain record error for {fir_number}: {exc}")

    # Auto-generate the official FIR PDF immediately so the Police Officer
    # portal and citizen always have a document to download without an extra
    # manual step by the Verification Officer.
    try:
        from backend.services.fir_document_service import generate_fir_pdf as _gen_pdf
        _gen_pdf(fir_id, officer_user)
    except Exception as exc:
        print(f"FIR PDF auto-generation error for {fir_number}: {exc}")

    # Notify citizen
    create_notification(
        user_id=complaint["citizen_id"],
        fir_id=fir_id,
        complaint_id=complaint_id,
        title="✅ FIR Officially Registered",
        message=(
            f"Your complaint has been reviewed and an official FIR has been registered as {fir_number}."
            + (
                " An investigating officer has been assigned to your case."
                if investigating_officer_id else
                " An investigating officer will be assigned through the authorised case workflow."
            )
        ),
        notification_type="FIR_REGISTERED",
        severity="SUCCESS",
        event_id=f"fir-registered-{fir_id}",
    )

    # Notify the assigned investigating officer (if any). The complaint reference
    # and official FIR number are included so the case can be opened directly.
    if investigating_officer_id:
        create_notification(
            user_id=investigating_officer_id,
            fir_id=fir_id,
            complaint_id=complaint_id,
            title="FIR Registered and Case Assigned",
            message=(
                f"FIR {fir_number} has been registered from complaint "
                f"{complaint.get('reference', complaint_id)}. You are the assigned "
                "investigating officer. Open your portal to access the case file, "
                "evidence and FIR document."
            ),
            notification_type="FIR_REGISTERED",
            severity="INFO",
            event_id=f"fir-registered-officer-{fir_id}",
        )

    if officer_user.get("id") != investigating_officer_id:
        create_notification(
            user_id=officer_user["id"],
            fir_id=fir_id,
            complaint_id=complaint_id,
            title="FIR Registered Successfully",
            message=(
                f"FIR {fir_number} has been registered from complaint "
                f"{complaint.get('reference', complaint_id)}."
            ),
            notification_type="FIR_REGISTERED",
            severity="SUCCESS",
            event_id=f"fir-registered-actor-{fir_id}",
        )

    # The verification desk that raised the record and the audit desk both need the
    # registration event; the actor is excluded as they already have the confirmation.
    registering_role = officer_user.get("role", "OFFICER").replace("_", " ").title()
    actor_label = f"{registering_role} {officer_user.get('name', 'Officer')}"
    complaint_ref = complaint.get("reference", complaint_id)

    notify_role(
        "VERIFICATION_OFFICER",
        "FIR Registered",
        (f"FIR {fir_number} has been registered from complaint {complaint_ref} "
         f"by {actor_label}."),
        f"fir-register-verification-{fir_id}",
        fir_id=fir_id,
        complaint_id=complaint_id,
        notification_type="FIR_REGISTERED",
        severity="INFO",
        exclude_user_id=officer_user.get("id"),
    )

    notify_role(
        "ADMIN",
        "FIR Registration Audit Record",
        (f"FIR {fir_number} registered from complaint {complaint_ref} by {actor_label}. "
         + (f"Investigating officer: {investigating_officer_name}. "
            if investigating_officer_id else "No investigating officer assigned yet. ")
         + f"Version 1 recorded at {iso_now}."),
        f"fir-register-audit-{fir_id}",
        fir_id=fir_id,
        complaint_id=complaint_id,
        notification_type="AUDIT_ALERT",
        severity="INFO",
        exclude_user_id=officer_user.get("id"),
    )

    try:
        from backend.services.case_tracking_service import (
            get_current_case_stage,
            initialize_case_tracking,
        )
        if not get_current_case_stage(fir_id):
            initialize_case_tracking(
                fir_id, officer_user,
                'OFFICER_ASSIGNED' if investigating_officer_id else 'FIR_CREATED',
            )
    except Exception as exc:
        print(f"Case tracking initialisation error for {fir_number}: {exc}")

    try:
        from backend.services.realtime_events import publish
        publish({
            'type': 'COMPLAINT_UPDATED',
            'complaint_id': complaint_id,
            'reference': complaint.get('reference'),
            'citizen_id': complaint['citizen_id'],
            'status': 'FIR_CREATED',
            'fir_id': fir_id,
        })
        publish({
            'type': 'FIR_UPDATED',
            'fir_id': fir_id,
            'fir_number': fir_number,
            'citizen_id': complaint['citizen_id'],
            'officer_id': investigating_officer_id,
        })
        publish({
            'type': 'CASE_STAGE_UPDATED',
            'fir_id': fir_id,
            'citizen_id': complaint['citizen_id'],
            'stage': 'OFFICER_ASSIGNED' if investigating_officer_id else 'FIR_CREATED',
        })
    except Exception:
        pass

    try:
        log_officer_activity(
            user=officer_user,
            action_type="FIR_REGISTERED",
            fir_id=fir_id,
            fir_number=fir_number,
            status_from=None,
            status_to="UNDER_INVESTIGATION",
            details=f"FIR registered from complaint {complaint.get('reference', complaint_id)}."
        )
    except Exception:
        pass

    return {
        "success": True,
        "fir_id": fir_id,
        "fir_number": fir_number,
        "reference_number": ref_number,
        "complaint_id": complaint_id,
        "status": "UNDER_INVESTIGATION",
        "registered_by": officer_user.get("badge_number", officer_user["id"]),
        "registered_at": iso_now,
    }

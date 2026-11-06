"""
FastAPI REST API Layer for Online FIR Platform & Mobile Integration.
Provides complete endpoints for:
- Authentication & RBAC
- FIR CRUD & versioning
- Side-by-side changes & chronological timeline
- Blockchain integrity verification
- Officer assignment
- Notifications
- Tamper simulation & restoration
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.services.auth_service import (
    authenticate_user,
    citizen_login_denial_reason,
    get_citizen_access_issue,
    get_session_user_strict,
    get_staff_access_issue,
    get_user_by_id,
    set_current_user
)
from backend.services.complaint_service import create_complaint
from backend.services.config_service import is_test_mode
from backend.services.blockchain_service import (
    get_blockchain_ledger,
    restore_tampered_fir,
    simulate_db_tamper,
    verify_fir_integrity
)
from backend.services.fir_service import (
    assign_officer_to_fir,
    create_fir,
    get_change_event_by_id,
    get_fir_by_id,
    get_fir_changes,
    get_fir_timeline,
    get_fir_versions,
    get_firs,
    get_pending_firs_for_verification,
    update_fir,
    verify_fir
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read
)

api_router = APIRouter(prefix="/api/v1", tags=["REST API"])


# Helper to get authenticated user from the caller's browser session
def get_auth_user_from_request(x_user_id: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Resolve the caller from the session established by signing in.

    ``X-User-Id`` is accepted only when it names the identity the same browser
    already authenticated as, so the header can never override a session, and it
    is honoured without any session at all only while TEST_MODE=1 (scripted runs).
    """
    session_user = get_session_user_strict()
    if x_user_id and session_user and x_user_id != session_user.get('id'):
        raise HTTPException(
            status_code=403,
            detail='X-User-Id does not match the authenticated session.',
        )

    user = session_user
    if user is None and x_user_id and is_test_mode():
        user = get_user_by_id(x_user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail='Authentication required. Sign in to the portal, or send X-User-Id under TEST_MODE=1.',
        )

    access_issue = get_citizen_access_issue(user) or get_staff_access_issue(user)
    if access_issue:
        raise HTTPException(status_code=403, detail=access_issue)
    return user


# ==========================================
# 1. HEALTH & SYSTEM
# ==========================================
@api_router.get("/health")
def health_check():
    """Health check endpoint."""
    return {
        "status": "online",
        "system": "Blockchain-Based Online FIR Platform",
        "consensus": "Proof-of-Authority Cryptographic Ledger",
        "hashing": "SHA-256 Canonical JSON",
        "timestamp": datetime.now().isoformat()
    }


# ==========================================
# 2. AUTHENTICATION & USERS
# ==========================================
class RegisterPayload(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    role: str = "CITIZEN"
    badge_number: Optional[str] = None
    station: Optional[str] = None
    district: Optional[str] = None
    address: Optional[str] = None
    gov_id: Optional[str] = None


class LoginPayload(BaseModel):
    email: str
    password: str
    role: Optional[str] = None


@api_router.post("/auth/register")
def api_register(payload: RegisterPayload):
    """Public API registration is disabled: identity documents cannot be verified here."""
    raise HTTPException(
        status_code=403,
        detail=(
            "Citizen registration requires a photograph and government ID verification. "
            "Please register through the Citizen Portal so a Verification Officer can approve the account."
        ),
    )


@api_router.post("/auth/login")
def api_login(payload: LoginPayload):
    """Authenticate citizen or staff credentials."""
    user = authenticate_user(payload.email, payload.password, required_role=payload.role)
    if not user:
        denial = citizen_login_denial_reason(payload.email, payload.password)
        raise HTTPException(
            status_code=403 if denial else 401,
            detail=denial or "Invalid email/badge or password.",
        )
    set_current_user(user)
    return {
        "success": True,
        "user": user,
        "message": f"Welcome back, {user['name']}!"
    }


@api_router.get("/auth/me")
def api_get_current_user(x_user_id: Optional[str] = Header(None)):
    """Get active user profile and unread notification counts."""
    user = get_auth_user_from_request(x_user_id)
    unread = get_unread_count(user["id"])
    return {"user": user, "unread_notifications": unread}


# ==========================================
# 3. FIR MANAGEMENT ENDPOINTS
# ==========================================
class CreateFIRPayload(BaseModel):
    police_station: str
    incident_type: str
    incident_date: str
    incident_time: str
    incident_location: str
    description: str
    accused_details: Optional[str] = "Unknown"
    witness_details: Optional[str] = "None"
    evidence_files: Optional[List[str]] = []
    assigned_officer_id: Optional[str] = None


class UpdateFIRPayload(BaseModel):
    updated_fields: Dict[str, Any]
    change_reason: Optional[str] = ""


@api_router.get("/firs")
def api_list_firs(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None)
):
    """List FIRs accessible to the authenticated user."""
    user = get_auth_user_from_request(x_user_id)
    return get_firs(actor_user=user, status_filter=status, search_query=search)


@api_router.post("/firs")
def api_create_fir(payload: CreateFIRPayload, x_user_id: Optional[str] = Header(None)):
    """Submit a new online FIR."""
    user = get_auth_user_from_request(x_user_id)
    try:
        created = create_fir(citizen_id=user["id"], payload=payload.model_dump())
        return {"success": True, "fir": created, "message": "FIR created and sealed to blockchain."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.get("/firs/{fir_id}")
def api_get_fir_details(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Get complete case file details for an FIR."""
    user = get_auth_user_from_request(x_user_id)
    try:
        fir = get_fir_by_id(fir_id, actor_user=user)
        if not fir:
            raise HTTPException(status_code=404, detail="FIR not found.")
        return fir
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@api_router.patch("/firs/{fir_id}")
def api_update_fir(fir_id: str, payload: UpdateFIRPayload, x_user_id: Optional[str] = Header(None)):
    """Modify permitted FIR fields; the change reason is optional and recorded when given."""
    user = get_auth_user_from_request(x_user_id)
    try:
        res = update_fir(
            fir_id=fir_id,
            actor_user=user,
            updated_fields=payload.updated_fields,
            change_reason=payload.change_reason or ""
        )
        if user.get("role") != "ADMIN":
            # Version hashes stay inside the Authorized Officer audit view.
            for key in ("previous_hash", "new_hash"):
                res.pop(key, None)
        return res
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/firs/{fir_id}/versions")
def api_get_fir_versions(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Retrieve full immutable version history of snapshots (Authorized Officers only)."""
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_fir_versions(fir_id, actor_user=user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/firs/{fir_id}/changes")
@api_router.get("/firs/{fir_id}/audit")
def api_get_fir_changes(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Retrieve forensic audit change events with OLD vs NEW diffs and blockchain proof (Authorized Officers only)."""
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_fir_changes(fir_id, actor_user=user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/firs/{fir_id}/audit/{event_id}")
def api_get_single_change_event(fir_id: str, event_id: str, x_user_id: Optional[str] = Header(None)):
    """Retrieve a single change audit event (Authorized Officers only)."""
    user = get_auth_user_from_request(x_user_id)
    try:
        ev = get_change_event_by_id(event_id, actor_user=user)
        if not ev:
            raise HTTPException(status_code=404, detail="Audit event not found.")
        return ev
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/firs/{fir_id}/timeline")
def api_get_fir_timeline(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Retrieve chronological lifecycle timeline."""
    user = get_auth_user_from_request(x_user_id)
    return get_fir_timeline(fir_id, actor_user=user)


# ==========================================
# 4. BLOCKCHAIN VERIFICATION & INTEGRITY
# ==========================================
def require_authorized_officer(user: Dict[str, Any]) -> Dict[str, Any]:
    """Hashes, ledger contents and tamper simulations are Authorized-Officer-only."""
    if user.get("role") != "ADMIN":
        raise HTTPException(
            status_code=403,
            detail="Forbidden: cryptographic integrity and blockchain data are restricted to Authorized Officers.",
        )
    return user


@api_router.post("/firs/{fir_id}/verify-integrity")
def api_verify_integrity(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Verify whether current database record matches blockchain proof."""
    require_authorized_officer(get_auth_user_from_request(x_user_id))
    return verify_fir_integrity(fir_id)


class AssignOfficerPayload(BaseModel):
    officer_id: str


@api_router.post("/firs/{fir_id}/assign-officer")
def api_assign_officer(fir_id: str, payload: AssignOfficerPayload, x_user_id: Optional[str] = Header(None)):
    """Assign an officer to an FIR."""
    user = get_auth_user_from_request(x_user_id)
    if user.get("role") not in ("ADMIN", "OFFICER", "VERIFICATION_OFFICER"):
        raise HTTPException(status_code=403, detail="Only admins, verification officers, or supervisors can assign cases.")
    success = assign_officer_to_fir(fir_id, payload.officer_id, user)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to assign officer.")
    return {"success": True, "message": "Officer assigned successfully."}


@api_router.post("/firs/{fir_id}/verify")
def api_verify_fir(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Police officer verifies a pending FIR, transitioning it from PENDING_VERIFICATION → VERIFIED."""
    user = get_auth_user_from_request(x_user_id)
    try:
        result = verify_fir(fir_id=fir_id, verified_by_user=user)
        return result
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/firs/pending-verification")
def api_list_pending_firs(x_user_id: Optional[str] = Header(None)):
    """List all FIRs pending police verification (Officers/Admins only)."""
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_pending_firs_for_verification(actor_user=user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


# ==========================================
# 5. NOTIFICATIONS
# ==========================================
@api_router.get("/notifications")
def api_list_notifications(x_user_id: Optional[str] = Header(None)):
    """List notifications for the authenticated user."""
    user = get_auth_user_from_request(x_user_id)
    return {
        "notifications": get_user_notifications(user["id"]),
        "unread_count": get_unread_count(user["id"])
    }


@api_router.patch("/notifications/{notif_id}/read")
def api_mark_notification_read(notif_id: str, x_user_id: Optional[str] = Header(None)):
    """Mark a notification as read."""
    user = get_auth_user_from_request(x_user_id)
    success = mark_notification_read(notif_id, user["id"])
    return {"success": success}


@api_router.post("/notifications/read-all")
def api_mark_all_read(x_user_id: Optional[str] = Header(None)):
    """Mark all notifications as read for current user."""
    user = get_auth_user_from_request(x_user_id)
    return {"success": mark_all_read(user["id"])}


# ==========================================
# 5A. CITIZEN COMPLAINTS (VERIFIED ACCOUNTS ONLY)
# ==========================================
class CreateComplaintPayload(BaseModel):
    category: str = "Other"
    title: str
    description: str
    location: Optional[str] = ""
    landmark: Optional[str] = ""
    area: Optional[str] = ""
    district: Optional[str] = ""
    state: Optional[str] = ""
    police_station: Optional[str] = ""
    incident_date: Optional[str] = ""
    incident_time: Optional[str] = ""
    evidence_files: Optional[list] = None


@api_router.post("/complaints")
def api_create_complaint(payload: CreateComplaintPayload, x_user_id: Optional[str] = Header(None)):
    """File a complaint. Requires an approved, active citizen account."""
    user = get_auth_user_from_request(x_user_id)
    if user.get("role") != "CITIZEN":
        raise HTTPException(status_code=403, detail="Only citizen accounts can file complaints.")
    try:
        complaint = create_complaint(user["id"], payload.model_dump())
        return {"success": True, "complaint": complaint}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error))


# ==========================================
# 5B. SECURE CITIZEN VERIFICATION DOCUMENTS
# ==========================================
@api_router.get("/secure/citizen-applications/{application_id}/{kind}")
def api_secure_citizen_document(application_id: str, kind: str):
    """Serve a citizen photograph or ID document to authorized reviewers only.

    Files live outside the public web root and are never exposed through static
    URLs. Access requires a Verification Officer / Administrator browser session.
    """
    from backend.services.citizen_registration_service import (
        get_citizen_application,
        media_type_for,
        resolve_secure_file,
    )

    user = get_session_user_strict()
    if not user or user.get("role") not in ("VERIFICATION_OFFICER", "ADMIN"):
        raise HTTPException(status_code=403, detail="Authorized verification personnel only.")

    application = get_citizen_application(application_id)
    if not application:
        raise HTTPException(status_code=404, detail="Citizen application not found.")

    if kind == "photo":
        relative_path = application.get("photo_path")
    elif kind == "document":
        relative_path = application.get("id_document_path")
    else:
        raise HTTPException(status_code=404, detail="Document not found.")

    absolute_path = resolve_secure_file(relative_path)
    if not absolute_path:
        raise HTTPException(status_code=404, detail="Document not found.")

    return FileResponse(
        absolute_path,
        media_type=media_type_for(absolute_path),
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
        },
    )


# ==========================================
# 5C. SECURE FIR DOCUMENTS (PDF)
# ==========================================
@api_router.get("/secure/fir-documents/{fir_id}")
def api_secure_fir_document(fir_id: str):
    """Serve the current official FIR PDF to authorized users only.

    Authorization: Verification Officers / Administrators, the citizen who filed
    the complaint, or the Police Officer currently assigned to the case. Files are
    stored outside the web root and never exposed through static URLs.
    """
    from backend.services.fir_document_service import latest_document_path_for

    user = get_session_user_strict()
    if not user:
        raise HTTPException(status_code=403, detail="Authentication required.")

    resolved = latest_document_path_for(fir_id, user)
    if not resolved:
        raise HTTPException(status_code=404, detail="FIR document not available.")

    absolute_path, download_name = resolved
    return FileResponse(
        absolute_path,
        media_type="application/pdf",
        filename=download_name,
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


@api_router.get("/secure/fir-documents/{fir_id}/version/{version}")
def api_secure_fir_document_version(fir_id: str, version: int):
    """Serve a specific version of the official FIR PDF to authorized users only."""
    from backend.services.fir_document_service import document_path_for_version

    user = get_session_user_strict()
    if not user:
        raise HTTPException(status_code=403, detail="Authentication required.")

    resolved = document_path_for_version(fir_id, version, user)
    if not resolved:
        raise HTTPException(status_code=404, detail="FIR document version not available.")

    absolute_path, download_name = resolved
    return FileResponse(
        absolute_path,
        media_type="application/pdf",
        filename=download_name,
        headers={
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
        },
    )


# ==========================================
# 6. BLOCKCHAIN LEDGER & TAMPER DEMO
# ==========================================
@api_router.get("/blockchain/ledger")
def api_get_ledger(limit: int = 50, x_user_id: Optional[str] = Header(None)):
    """Inspect mined blocks and transaction proofs on the blockchain."""
    require_authorized_officer(get_auth_user_from_request(x_user_id))
    return get_blockchain_ledger(limit=limit)


class SimulateTamperPayload(BaseModel):
    fir_id: str
    field_name: str = "incident_location"
    malicious_value: str = "TAMPERED_LOCATION_RAW_MUTATION"


@api_router.post("/blockchain/simulate-tamper")
def api_simulate_tamper(payload: SimulateTamperPayload, x_user_id: Optional[str] = Header(None)):
    """Simulate unauthorized database modification to test tamper detection."""
    require_authorized_officer(get_auth_user_from_request(x_user_id))
    return simulate_db_tamper(payload.fir_id, payload.field_name, payload.malicious_value)


@api_router.post("/blockchain/restore-fir/{fir_id}")
def api_restore_fir(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """Restore database record to confirmed blockchain snapshot."""
    require_authorized_officer(get_auth_user_from_request(x_user_id))
    return restore_tampered_fir(fir_id)


# ==========================================
# 7. AUTHORIZED OFFICER ENDPOINTS
# ==========================================
# Strict access control: Only users with ADMIN/AUTHORIZED_OFFICER role
# Verification Officers, Police Officers, and Citizens CANNOT access these endpoints

from backend.services.authorized_officer_service import (
    check_authorized_officer_access,
    get_dashboard_data,
    compare_fir_versions,
    get_fir_version_history,
    get_audit_logs,
    get_fir_timeline as get_authorized_fir_timeline,
    reassign_fir_officer,
    get_officer_activity_report,
    get_integrity_alerts
)


@api_router.get("/authorized/dashboard")
def api_authorized_dashboard(x_user_id: Optional[str] = Header(None)):
    """
    Get Authorized Officer integrity dashboard with FIR monitoring statistics.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_dashboard_data(user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/authorized/firs/{fir_id}/comparison")
def api_fir_comparison(
    fir_id: str,
    version1: int = Query(..., description="First version number (typically original)"),
    version2: int = Query(..., description="Second version number (typically current)"),
    x_user_id: Optional[str] = Header(None)
):
    """
    Compare two versions of an FIR showing field-by-field differences.
    Shows Original vs Current with complete change tracking.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return compare_fir_versions(fir_id, version1, version2, user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@api_router.get("/authorized/firs/{fir_id}/version-history")
def api_fir_version_history(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """
    Get complete version history with cryptographic hash verification.
    Shows all versions with SHA-256 hashes and integrity status.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_fir_version_history(fir_id, user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/authorized/firs/{fir_id}/complete-timeline")
def api_fir_complete_timeline(fir_id: str, x_user_id: Optional[str] = Header(None)):
    """
    Get complete chronological timeline with all events and state changes.
    Shows every action from submission to current state.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_authorized_fir_timeline(fir_id, user)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/authorized/audit-logs")
def api_audit_logs(
    fir_id: Optional[str] = Query(None),
    officer_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="ISO format: 2026-08-01T00:00:00"),
    date_to: Optional[str] = Query(None, description="ISO format: 2026-08-19T23:59:59"),
    action_type: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    x_user_id: Optional[str] = Header(None)
):
    """
    Get complete audit logs with filtering options.
    Filter by FIR, officer, role, date range, or action type.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_audit_logs(
            user=user,
            fir_id=fir_id,
            officer_id=officer_id,
            role=role,
            date_from=date_from,
            date_to=date_to,
            action_type=action_type,
            limit=limit
        )
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


class ReassignOfficerPayload(BaseModel):
    new_officer_id: str
    reason: str


@api_router.post("/authorized/firs/{fir_id}/reassign-officer")
def api_reassign_officer(
    fir_id: str,
    payload: ReassignOfficerPayload,
    x_user_id: Optional[str] = Header(None)
):
    """
    Reassign an officer to an FIR (administrative correction).
    Creates complete audit trail of the reassignment.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return reassign_fir_officer(
            fir_id=fir_id,
            new_officer_id=payload.new_officer_id,
            reason=payload.reason,
            user=user
        )
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/authorized/officers/{officer_id}/activity")
def api_officer_activity(
    officer_id: str,
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    x_user_id: Optional[str] = Header(None)
):
    """
    Get complete activity report for a specific officer.
    Shows all actions, FIRs touched, and event type breakdown.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_officer_activity_report(
            officer_id=officer_id,
            user=user,
            date_from=date_from,
            date_to=date_to
        )
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))


@api_router.get("/authorized/integrity-alerts")
def api_integrity_alerts(
    limit: int = Query(50, le=200),
    x_user_id: Optional[str] = Header(None)
):
    """
    Get FIR integrity alerts requiring attention.
    Shows suspicious activities and integrity issues.
    
    Access: AUTHORIZED_OFFICER / ADMIN only
    """
    user = get_auth_user_from_request(x_user_id)
    try:
        return get_integrity_alerts(user, limit=limit)
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))

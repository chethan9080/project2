"""
Comprehensive Live FIR Tracking System Test Script.
Validates all 19 requirements specified in the user implementation task:
1. Citizen complaint / FIR lifecycle
2. Complete 10-stage sequential timeline
3. Independent tracking across multiple FIRs
4. Real-time live status updates without refresh
5. Security monitoring, genuine red alerts, and alert resolution
6. Permanent database persistence
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.db import get_db_connection
from backend.services.fir_service import create_fir, get_fir_by_id, get_firs
from backend.services.case_tracking_service import (
    CASE_STAGES,
    STAGE_LABELS,
    get_fir_complete_tracking,
    update_case_stage,
    create_security_alert,
    resolve_security_alert,
    get_all_firs_for_tracking,
    get_security_monitoring_status
)


def run_full_live_tracking_verification():
    print("=" * 80)
    print("STARTING FULL LIVE FIR TRACKING SYSTEM VERIFICATION")
    print("=" * 80)

    # ── Test Setup: Use existing provisioned citizen and officer accounts ──
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE role IN ('OFFICER', 'ADMIN') LIMIT 1")
    row = cur.fetchone()
    officer = dict(row) if row else None
    cur.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1")
    row = cur.fetchone()
    citizen = dict(row) if row else None
    conn.close()

    if not officer or not citizen:
        print("✗ Requires a provisioned officer and citizen account to run.")
        return False

    print(f"✓ Main Officer: {officer.get('name')} ({officer.get('badge_number') or 'N/A'})")
    print(f"✓ Citizen: {citizen.get('name')} (ID: {citizen.get('id')})")

    # ── Requirement 1 & 2: Create FIR 1 & FIR 2 for same Citizen ──
    print("\n[Step 1-2] Creating Two Independent FIRs for Citizen...")
    fir1 = create_fir(
        citizen_id=citizen["id"],
        payload={
            "incident_type": "Cyber Fraud & Phishing",
            "incident_date": "2026-11-03",
            "incident_time": "10:00",
            "incident_location": "Indiranagar, Bengaluru",
            "description": "Unauthorized debit of Rs. 45,000 from banking account via suspicious link.",
            "police_station": "Indiranagar Police Station"
        }
    )
    fir1_id = fir1["id"]
    fir1_num = fir1["fir_number"]
    print(f"  ✓ FIR 1 created: {fir1_num} (ID: {fir1_id})")

    fir2 = create_fir(
        citizen_id=citizen["id"],
        payload={
            "incident_type": "Two-Wheeler Vehicle Theft",
            "incident_date": "2026-11-03",
            "incident_time": "11:30",
            "incident_location": "Koramangala 5th Block",
            "description": "Blue Honda Activa KA-01-EF-1234 stolen from public parking.",
            "police_station": "Koramangala Police Station"
        }
    )
    fir2_id = fir2["id"]
    fir2_num = fir2["fir_number"]
    print(f"  ✓ FIR 2 created: {fir2_num} (ID: {fir2_id})")

    # ── Requirement 3-4: Verify Citizen 10-Stage Initial Tracking ──
    print("\n[Step 3-4] Checking Citizen 10-Stage Timeline for FIR 1...")
    tracking_fir1 = get_fir_complete_tracking(fir1_id, citizen)
    assert tracking_fir1, "FIR 1 tracking data must exist"
    assert len(tracking_fir1["stages"]) == 10, f"Must have exactly 10 stages, got {len(tracking_fir1['stages'])}"
    print(f"  ✓ Stage count: {len(tracking_fir1['stages'])}")
    for st in tracking_fir1["stages"]:
        print(f"    - Stage {st['number']}: {st['label']} | Status: {st['status']} ({st['color']})")

    # Stage 1 and 2 must be completed initially
    assert tracking_fir1["stages"][0]["status"] == "COMPLETED"
    assert tracking_fir1["stages"][1]["status"] == "COMPLETED"
    print("  ✓ Initial stages (Complaint Submitted, FIR Created) properly marked Completed.")

    # ── Requirement 5-7: Main Officer Searches and Selects FIR ──
    print("\n[Step 5-7] Main Officer Searching by Citizen Name & FIR Number...")
    officer_firs = get_all_firs_for_tracking(officer, search_query=citizen["name"])
    found_fir1 = any(f["id"] == fir1_id for f in officer_firs)
    assert found_fir1, "Main Officer must find FIR 1 when searching for citizen"
    print(f"  ✓ Main Officer successfully located FIR {fir1_num} via Citizen Name search.")

    # ── Requirement 8-10: Main Officer Updates Case to Investigation Started ──
    print("\n[Step 8-10] Main Officer Advances FIR 1 to 'Investigation Started'...")
    update_res1 = update_case_stage(
        fir_id=fir1_id,
        new_stage="INVESTIGATION_STARTED",
        officer_user=officer,
        remarks="Case assigned to Sub-Inspector; preliminary questioning scheduled."
    )
    assert update_res1["new_stage"] == "INVESTIGATION_STARTED"
    print(f"  ✓ Stage updated: {update_res1['previous_stage']} → {update_res1['new_stage']}")

    # ── Requirement 11: Real-Time Verification from Citizen View ──
    print("\n[Step 11] Verifying Citizen View Receives Updated Stage Immediately...")
    citizen_view_after_step1 = get_fir_complete_tracking(fir1_id, citizen)
    active_stage_key = citizen_view_after_step1["current_stage_key"]
    print(f"  ✓ Citizen sees active stage: {citizen_view_after_step1['current_stage_label']}")
    assert active_stage_key == "INVESTIGATION_STARTED", f"Expected INVESTIGATION_STARTED, got {active_stage_key}"

    # ── Requirement 12-13: Advance to Evidence Collection ──
    print("\n[Step 12-13] Main Officer Advances FIR 1 to 'Evidence Collection'...")
    update_res2 = update_case_stage(
        fir_id=fir1_id,
        new_stage="EVIDENCE_COLLECTION",
        officer_user=officer,
        remarks="Bank IP access logs and CCTV camera footage secured from ATM."
    )
    citizen_view_after_step2 = get_fir_complete_tracking(fir1_id, citizen)
    assert citizen_view_after_step2["current_stage_key"] == "EVIDENCE_COLLECTION"
    print(f"  ✓ Citizen sees updated stage: {citizen_view_after_step2['current_stage_label']}")

    # ── Requirement 14-15: Confirm FIR 2 Remains Completely Independent ──
    print("\n[Step 14-15] Verifying FIR 2 Tracking Remains Independent and Unchanged...")
    tracking_fir2 = get_fir_complete_tracking(fir2_id, citizen)
    assert tracking_fir2["fir_number"] == fir2_num
    assert tracking_fir2["current_stage_key"] != "EVIDENCE_COLLECTION", "FIR 2 must NOT be in Evidence Collection"
    print(f"  ✓ FIR 1 Stage: {citizen_view_after_step2['current_stage_label']}")
    print(f"  ✓ FIR 2 Stage: {tracking_fir2['current_stage_label']}")
    print("  ✓ Full independence of multiple FIRs verified!")

    # ── Requirement 16-17: Test Genuine Security Alert & Red Visual State ──
    print("\n[Step 16-17] Triggering Genuine Security Alert on FIR 1...")
    alert_obj = create_security_alert(
        fir_id=fir1_id,
        reason="Suspicious attempted modification of suspect contact details detected.",
        stage="EVIDENCE_COLLECTION",
        severity="CRITICAL",
        responsible_account="Unknown External IP / System Watcher",
        actor_user=officer
    )
    alert_id = alert_obj["id"]
    print(f"  ✓ Created security alert ID: {alert_id} | Code: {alert_obj['alert_id']}")

    sec_status = get_security_monitoring_status(fir1_id)
    assert sec_status["color"] == "red", f"Security status color must be RED, got {sec_status['color']}"
    assert sec_status["status"] == "SECURITY_THREAT"
    print(f"  ✓ Security Monitoring Status: {sec_status['status']} (Color: {sec_status['color']})")

    # Check stage has alert flagged
    tracking_with_alert = get_fir_complete_tracking(fir1_id, citizen)
    stage6 = [s for s in tracking_with_alert["stages"] if s["key"] == "EVIDENCE_COLLECTION"][0]
    assert stage6["status"] == "ALERT" or len(stage6["alerts"]) > 0, "Stage 6 must reflect security alert"
    print("  ✓ Red alert banner successfully linked to Evidence Collection stage.")

    # ── Requirement 18: Resolve Alert and Verify History Persists ──
    print("\n[Step 18] Main Officer Resolves Security Alert with Investigation Finding...")
    resolve_res = resolve_security_alert(
        alert_id=alert_id,
        officer_user=officer,
        resolution_notes="Investigation concluded: IP address was internal IT maintenance script. False alarm cleared."
    )
    assert resolve_res["status"] == "RESOLVED"
    sec_status_resolved = get_security_monitoring_status(fir1_id)
    print(f"  ✓ Security Alert Resolved. New Status: {sec_status_resolved['status']} (Color: {sec_status_resolved['color']})")
    assert sec_status_resolved["color"] in ("green", "grey")

    # Verify resolution history remains in database
    tracking_after_resolve = get_fir_complete_tracking(fir1_id, citizen)
    all_alerts = tracking_after_resolve["security_status"]["alerts"]
    assert any(a["id"] == alert_id and a["status"] == "RESOLVED" for a in all_alerts)
    print("  ✓ Complete alert and resolution history persisted in database.")

    # ── Requirement 19: Database Persistence Check ──
    print("\n[Step 19] Verifying Permanent Database Persistence Across Disconnects...")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM case_tracking WHERE fir_id = ?", (fir1_id,))
    history_rows = cur.fetchall()
    conn.close()
    assert len(history_rows) >= 2, f"Must have at least 2 tracking entries in DB, found {len(history_rows)}"
    print(f"  ✓ Database verified: {len(history_rows)} case tracking audit records permanently stored.")

    print("\n" + "=" * 80)
    print("ALL 19 REQUIREMENTS SUCCESSFULLY VALIDATED & VERIFIED!")
    print("=" * 80)
    return True


if __name__ == "__main__":
    success = run_full_live_tracking_verification()
    sys.exit(0 if success else 1)

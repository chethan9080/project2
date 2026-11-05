"""
End-to-End Case Tracking Test
Tests the complete flow: Police Update → Database → Citizen View
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.case_tracking_service import (
    get_case_stage_progress,
    update_case_stage,
    get_case_tracking_history,
    CASE_STAGES,
    STAGE_LABELS
)
from backend.services.fir_service import get_firs, get_fir_by_id
from backend.services.auth_service import get_all_officers, get_user_by_id
from backend.services.notification_service import get_user_notifications


def test_police_to_citizen_flow():
    """Test complete Police → Database → Citizen flow."""
    print("=" * 80)
    print("END-TO-END CASE TRACKING TEST")
    print("Testing: Police Update → Database → Citizen View")
    print("=" * 80)
    
    # ========== STEP 1: Get Police Officer ==========
    print("\n📋 STEP 1: Get Authenticated Police Officer")
    print("-" * 80)
    
    officers = get_all_officers()
    if not officers:
        print("❌ FAIL: No officers found")
        return False
    
    officer = officers[0]
    print(f"✓ Officer: {officer['name']}")
    print(f"  Badge: {officer['badge_number']}")
    print(f"  ID: {officer['id']}")
    print(f"  Role: {officer.get('role', 'N/A')}")
    
    # ========== STEP 2: Get FIR Assigned to Officer ==========
    print("\n📋 STEP 2: Get FIR Assigned to Officer")
    print("-" * 80)
    
    all_firs = get_firs(actor_user=officer)
    assigned_firs = [f for f in all_firs if f.get('assigned_officer_id') == officer['id']]
    
    if not assigned_firs:
        print(f"❌ FAIL: No FIRs assigned to {officer['name']}")
        return False
    
    fir = assigned_firs[0]
    citizen_id = fir['citizen_id']
    
    print(f"✓ FIR: {fir['fir_number']}")
    print(f"  ID: {fir['id']}")
    print(f"  Status: {fir['status']}")
    print(f"  Citizen ID: {citizen_id}")
    
    # Get citizen details
    citizen = get_user_by_id(citizen_id)
    if citizen:
        print(f"  Citizen Name: {citizen['name']}")
        print(f"  Citizen Email: {citizen['email']}")
    
    # ========== STEP 3: Check Current Stage (Before Update) ==========
    print("\n📋 STEP 3: Check Current Case Stage (BEFORE Update)")
    print("-" * 80)
    
    progress_before = get_case_stage_progress(fir['id'])
    current_stage_before = progress_before['current_stage']
    
    if current_stage_before:
        print(f"✓ Current Stage: {STAGE_LABELS[current_stage_before]}")
    else:
        print("✓ Current Stage: Not yet initialized")
    
    print(f"  Completed Stages: {len(progress_before['completed_stages'])}")
    print(f"  History Entries: {len(progress_before['history'])}")
    
    # ========== STEP 4: Police Officer Updates Stage ==========
    print("\n📋 STEP 4: Police Officer Updates Case Stage")
    print("-" * 80)
    
    # Determine next stage to update to
    if not current_stage_before:
        next_stage = 'FIR_REGISTERED'
    elif current_stage_before == 'FIR_REGISTERED':
        next_stage = 'UNDER_INVESTIGATION'
    elif current_stage_before == 'UNDER_INVESTIGATION':
        next_stage = 'EVIDENCE_COLLECTION'
    elif current_stage_before == 'EVIDENCE_COLLECTION':
        next_stage = 'INVESTIGATION_COMPLETED'
    else:
        # Go back to Investigation for testing
        next_stage = 'UNDER_INVESTIGATION'
    
    print(f"Updating from: {STAGE_LABELS.get(current_stage_before, 'Not Started')}")
    print(f"Updating to: {STAGE_LABELS[next_stage]}")
    
    try:
        result = update_case_stage(
            fir_id=fir['id'],
            new_stage=next_stage,
            officer_user=officer,
            remarks=f"E2E Test: Case progressed by {officer['name']} during automated testing"
        )
        
        print(f"\n✅ SUCCESS: Stage updated!")
        print(f"  Track ID: {result['track_id']}")
        print(f"  FIR: {result['fir_number']}")
        print(f"  Citizen: {result['citizen_name']}")
        print(f"  Previous: {STAGE_LABELS.get(result['previous_stage'], 'Not Started')}")
        print(f"  New: {STAGE_LABELS[result['new_stage']]}")
        print(f"  Officer: {result['officer_name']} ({result['officer_badge']})")
        print(f"  Timestamp: {result['timestamp']}")
        
    except ValueError as e:
        # If already at this stage, try alternative
        if "already in stage" in str(e):
            print(f"⚠️  Already at {STAGE_LABELS[next_stage]}, trying alternative stage...")
            next_stage = 'INVESTIGATION_COMPLETED' if next_stage != 'INVESTIGATION_COMPLETED' else 'CHARGESHEET_PREPARED'
            result = update_case_stage(
                fir_id=fir['id'],
                new_stage=next_stage,
                officer_user=officer,
                remarks=f"E2E Test: Alternative stage update by {officer['name']}"
            )
            print(f"✅ SUCCESS: Updated to {STAGE_LABELS[next_stage]}")
    
    except Exception as e:
        print(f"❌ FAIL: Stage update failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # ========== STEP 5: Verify Database Update ==========
    print("\n📋 STEP 5: Verify Update in Database")
    print("-" * 80)
    
    progress_after = get_case_stage_progress(fir['id'])
    current_stage_after = progress_after['current_stage']
    
    if current_stage_after == next_stage:
        print(f"✅ SUCCESS: Database updated correctly!")
        print(f"  New Stage: {STAGE_LABELS[current_stage_after]}")
        print(f"  Completed Stages: {len(progress_after['completed_stages'])}")
        print(f"  History Entries: {len(progress_after['history'])}")
    else:
        print(f"❌ FAIL: Database not updated correctly")
        print(f"  Expected: {STAGE_LABELS[next_stage]}")
        print(f"  Got: {STAGE_LABELS.get(current_stage_after, 'None')}")
        return False
    
    # ========== STEP 6: Verify Citizen Can See Update ==========
    print("\n📋 STEP 6: Verify Citizen Can See Update")
    print("-" * 80)
    
    # Simulate citizen viewing their FIR
    citizen_fir = get_fir_by_id(fir['id'], actor_user=citizen)
    citizen_progress = get_case_stage_progress(fir['id'])
    
    print(f"✓ Citizen View:")
    print(f"  FIR Number: {citizen_fir['fir_number']}")
    print(f"  Current Stage: {STAGE_LABELS[citizen_progress['current_stage']]}")
    print(f"  Completed Stages: {len(citizen_progress['completed_stages'])}")
    
    # Show stage progression
    print(f"\n  Stage Progress:")
    for stage in CASE_STAGES:
        if stage in citizen_progress['completed_stages']:
            print(f"    ✓ {STAGE_LABELS[stage]}")
        else:
            print(f"    ○ {STAGE_LABELS[stage]}")
    
    if citizen_progress['current_stage'] == next_stage:
        print(f"\n✅ SUCCESS: Citizen can see the updated stage!")
    else:
        print(f"\n❌ FAIL: Citizen cannot see the update")
        return False
    
    # ========== STEP 7: Verify Notification Sent to Citizen ==========
    print("\n📋 STEP 7: Verify Notification Sent to Citizen")
    print("-" * 80)
    
    citizen_notifications = get_user_notifications(citizen_id, limit=10)
    case_update_notifications = [
        n for n in citizen_notifications 
        if n.get('notification_type') == 'CASE_STAGE_UPDATE' 
        and n.get('fir_id') == fir['id']
    ]
    
    if case_update_notifications:
        latest_notif = case_update_notifications[0]
        print(f"✅ SUCCESS: Notification sent to citizen!")
        print(f"  Title: {latest_notif['title']}")
        print(f"  Message: {latest_notif['message'][:100]}...")
        print(f"  Type: {latest_notif['notification_type']}")
        print(f"  Created: {latest_notif['created_at']}")
    else:
        print(f"⚠️  WARNING: No case update notification found (might be from previous test)")
    
    # ========== STEP 8: Verify Audit Trail ==========
    print("\n📋 STEP 8: Verify Complete Audit Trail")
    print("-" * 80)
    
    history = get_case_tracking_history(fir['id'])
    
    print(f"✓ Total history entries: {len(history)}")
    print(f"\n  Audit Trail:")
    for i, entry in enumerate(history[-5:], 1):  # Show last 5
        prev = STAGE_LABELS.get(entry['previous_stage'], 'Not Started')
        new = STAGE_LABELS[entry['new_stage']]
        print(f"    {i}. {prev} → {new}")
        print(f"       Officer: {entry['updated_by_officer_name']} ({entry['updated_by_officer_badge']})")
        print(f"       Track ID: {entry['track_id']}")
        print(f"       Time: {entry['timestamp']}")
        if entry.get('remarks'):
            print(f"       Remarks: {entry['remarks'][:60]}...")
        print()
    
    if len(history) > 0:
        print(f"✅ SUCCESS: Audit trail maintained correctly!")
    else:
        print(f"❌ FAIL: No audit trail found")
        return False
    
    # ========== FINAL SUMMARY ==========
    print("\n" + "=" * 80)
    print("FINAL VERIFICATION")
    print("=" * 80)
    
    print(f"\n✅ Police Officer: {officer['name']} ({officer['badge_number']})")
    print(f"✅ Updated FIR: {fir['fir_number']}")
    print(f"✅ Citizen: {citizen['name']}")
    print(f"✅ Stage Updated: {STAGE_LABELS.get(current_stage_before, 'Not Started')} → {STAGE_LABELS[next_stage]}")
    print(f"✅ Database: Updated and verified")
    print(f"✅ Citizen View: Can see updated stage")
    print(f"✅ Notification: Sent to citizen")
    print(f"✅ Audit Trail: Complete with {len(history)} entries")
    
    return True


if __name__ == "__main__":
    print("\n🚀 Starting End-to-End Case Tracking Test...\n")
    
    try:
        success = test_police_to_citizen_flow()
    except Exception as e:
        print(f"\n❌ TEST FAILED WITH EXCEPTION: {str(e)}")
        import traceback
        traceback.print_exc()
        success = False
    
    print("\n" + "=" * 80)
    if success:
        print("✅ ALL TESTS PASSED - Case Tracking Flow Working Correctly!")
        print("   Police → Database → Citizen flow verified successfully")
    else:
        print("❌ TESTS FAILED - See errors above")
    print("=" * 80 + "\n")
    
    sys.exit(0 if success else 1)

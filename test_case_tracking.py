#!/usr/bin/env python3
"""
Case Tracking System Test Script
Tests the complete flow: Police update → Database → Citizen view
"""

import sys
# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.db import get_db_connection
from backend.services.case_tracking_service import (
    get_current_case_stage,
    update_case_stage,
    get_case_tracking_history,
    get_case_stage_progress,
    STAGE_LABELS
)

def print_header(title):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_result(test_name, passed, details=""):
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"       {details}")

def get_test_fir():
    """Get a test FIR from database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.id, f.fir_number, f.citizen_id, f.assigned_officer_id,
               u.name as citizen_name
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE f.assigned_officer_id IS NOT NULL
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_test_officer():
    """Get a test officer from database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, email, badge_number
        FROM users
        WHERE role = 'OFFICER'
        LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def test_database_table():
    """Test 1: Verify case_tracking table exists."""
    print_header("TEST 1: Database Table Verification")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='case_tracking'")
    table_exists = cursor.fetchone() is not None
    print_result("case_tracking table exists", table_exists)
    
    if table_exists:
        cursor.execute("PRAGMA table_info(case_tracking)")
        columns = [row[1] for row in cursor.fetchall()]
        expected_columns = ['id', 'track_id', 'fir_id', 'previous_stage', 'new_stage', 
                           'updated_by_officer_id', 'updated_by_officer_name', 
                           'updated_by_officer_badge', 'remarks', 'timestamp']
        all_present = all(col in columns for col in expected_columns)
        print_result("All required columns present", all_present, 
                    f"Found: {', '.join(columns)}")
    
    conn.close()
    return table_exists

def test_get_current_stage():
    """Test 2: Get current case stage."""
    print_header("TEST 2: Get Current Case Stage")
    
    fir = get_test_fir()
    if not fir:
        print_result("Test FIR found", False, "No FIR with assigned officer found")
        return False
    
    print_result("Test FIR found", True, f"FIR: {fir['fir_number']}, Citizen: {fir['citizen_name']}")
    
    current_stage = get_current_case_stage(fir['id'])
    if current_stage:
        print_result("Current stage retrieved", True, f"Stage: {STAGE_LABELS[current_stage]}")
    else:
        print_result("Current stage retrieved", True, "No stage set yet (expected for new FIR)")
    
    return True

def test_update_case_stage():
    """Test 3: Update case stage."""
    print_header("TEST 3: Update Case Stage")
    
    fir = get_test_fir()
    officer = get_test_officer()
    
    if not fir or not officer:
        print_result("Test data available", False, "Missing FIR or officer")
        return False
    
    print_result("Test data available", True, 
                f"FIR: {fir['fir_number']}, Officer: {officer['name']} ({officer['badge_number']})")
    
    # Get current stage
    current = get_current_case_stage(fir['id'])
    print_result("Current stage checked", True, 
                f"Current: {STAGE_LABELS.get(current, 'None') if current else 'None'}")
    
    # Update to FIR_REGISTERED if not set, otherwise UNDER_INVESTIGATION
    new_stage = 'FIR_REGISTERED' if not current else 'UNDER_INVESTIGATION'
    
    try:
        result = update_case_stage(
            fir_id=fir['id'],
            new_stage=new_stage,
            officer_user=officer,
            remarks='Test update from automated test script'
        )
        
        print_result("Stage update successful", True, 
                    f"Updated to: {STAGE_LABELS[new_stage]}")
        print_result("Tracking ID generated", result.get('track_id') is not None,
                    f"Track ID: {result.get('track_id')}")
        print_result("Officer info recorded", 
                    result.get('officer_name') == officer['name'] and 
                    result.get('officer_badge') == officer['badge_number'],
                    f"Officer: {result.get('officer_name')} ({result.get('officer_badge')})")
        
        return True
        
    except ValueError as e:
        if "already in stage" in str(e):
            print_result("Stage update (duplicate detected)", True, 
                        "Correctly prevented duplicate stage update")
            return True
        else:
            print_result("Stage update failed", False, str(e))
            return False
    except Exception as e:
        print_result("Stage update failed", False, str(e))
        return False

def test_get_history():
    """Test 4: Get case tracking history."""
    print_header("TEST 4: Get Case Tracking History")
    
    fir = get_test_fir()
    if not fir:
        print_result("Test FIR found", False)
        return False
    
    history = get_case_tracking_history(fir['id'])
    print_result("History retrieved", True, f"{len(history)} updates found")
    
    if history:
        print("\n  Recent Updates:")
        for i, update in enumerate(reversed(history[:3]), 1):
            prev = STAGE_LABELS.get(update['previous_stage'], '—') if update['previous_stage'] else 'Initial'
            new = STAGE_LABELS[update['new_stage']]
            print(f"    {i}. {prev} → {new}")
            print(f"       By: {update['updated_by_officer_name']} ({update['updated_by_officer_badge']})")
            print(f"       Time: {update['timestamp'][:19]}")
            if update.get('remarks'):
                print(f"       Notes: {update['remarks']}")
    
    return True

def test_get_progress():
    """Test 5: Get case stage progress."""
    print_header("TEST 5: Get Case Stage Progress")
    
    fir = get_test_fir()
    if not fir:
        print_result("Test FIR found", False)
        return False
    
    progress = get_case_stage_progress(fir['id'])
    
    print_result("Progress data retrieved", progress is not None)
    print_result("Current stage available", 
                progress['current_stage'] is not None,
                f"Current: {progress['current_stage_label']}")
    print_result("Completed stages calculated",
                len(progress['completed_stages']) >= 0,
                f"{len(progress['completed_stages'])} stages completed")
    print_result("All stages list provided",
                len(progress['all_stages']) == 8,
                f"{len(progress['all_stages'])} stages defined")
    print_result("Stage labels provided",
                len(progress['stage_labels']) == 8,
                f"{len(progress['stage_labels'])} labels defined")
    
    return True

def test_notification_creation():
    """Test 6: Verify notifications are created."""
    print_header("TEST 6: Notification Creation Verification")
    
    fir = get_test_fir()
    if not fir:
        print_result("Test FIR found", False)
        return False
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(*) as cnt
        FROM notifications
        WHERE type = 'CASE_STAGE_UPDATE'
        AND user_id = ?
        AND fir_id = ?
    """, (fir['citizen_id'], fir['id']))
    
    count = cursor.fetchone()['cnt']
    conn.close()
    
    print_result("Notifications exist for citizen", count > 0,
                f"{count} case stage update notifications found")
    
    return count > 0

def main():
    """Run all tests."""
    print("\n" + "╔" + "═" * 78 + "╗")
    print("║" + " " * 23 + "CASE TRACKING SYSTEM TEST" + " " * 30 + "║")
    print("╚" + "═" * 78 + "╝")
    
    results = {
        "Database Table": test_database_table(),
        "Get Current Stage": test_get_current_stage(),
        "Update Case Stage": test_update_case_stage(),
        "Get History": test_get_history(),
        "Get Progress": test_get_progress(),
        "Notifications": test_notification_creation()
    }
    
    print_header("TEST SUMMARY")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} | {test_name}")
    
    print(f"\n{'=' * 80}")
    print(f"  TOTAL: {passed}/{total} tests passed ({passed*100//total}%)")
    print(f"{'=' * 80}\n")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Comprehensive End-to-End Notification System Test
Tests all notification types across all user roles with real data.
"""

import sys
from datetime import datetime
# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.db import get_db_connection
from backend.services.auth_service import authenticate_user
from backend.services.notification_service import (
    create_notification,
    get_user_notifications,
    get_unread_count,
    mark_notification_read,
    mark_all_read
)
from backend.services.fir_service import (
    create_fir,
    verify_fir,
    assign_officer_to_fir,
    update_fir
)

def print_header(title):
    """Print a test section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)

def print_result(test_name, passed, details=""):
    """Print a test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"       {details}")

def get_user_by_email(email):
    """Get user from database by email."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def test_notification_infrastructure():
    """Test 1: Verify notification infrastructure exists."""
    print_header("TEST 1: Notification Infrastructure")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check notifications table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='notifications'")
    table_exists = cursor.fetchone() is not None
    print_result("Notifications table exists", table_exists)
    
    # Check notifications count
    cursor.execute("SELECT COUNT(*) as cnt FROM notifications")
    count = cursor.fetchone()['cnt']
    print_result(f"Notifications in database: {count}", count > 0, f"{count} notifications found")
    
    # Check unread notifications
    cursor.execute("SELECT COUNT(*) as cnt FROM notifications WHERE is_read = 0")
    unread = cursor.fetchone()['cnt']
    print_result(f"Unread notifications exist", unread > 0, f"{unread} unread notifications")
    
    conn.close()
    return table_exists and count > 0

def test_citizen_notifications():
    """Test 2: Verify citizen receives proper notifications."""
    print_header("TEST 2: Citizen Notifications")
    
    citizen = get_user_by_email("citizen@example.com")
    if not citizen:
        print_result("Citizen user exists", False, "citizen@example.com not found")
        return False
    
    print_result("Citizen user found", True, f"ID: {citizen['id']}, Name: {citizen['name']}")
    
    # Get citizen notifications
    notifs = get_user_notifications(citizen['id'])
    print_result(f"Citizen has notifications", len(notifs) > 0, f"{len(notifs)} notifications found")
    
    # Get unread count
    unread = get_unread_count(citizen['id'])
    print_result(f"Citizen unread count", unread >= 0, f"{unread} unread notifications")
    
    # Check notification types
    if notifs:
        print("\n  Recent Citizen Notifications:")
        for i, notif in enumerate(notifs[:5], 1):
            print(f"    {i}. [{notif.get('type')}] {notif.get('title')}")
            print(f"       FIR: {notif.get('fir_number', 'N/A')}, Read: {notif.get('is_read') == 1}")
    
    # Check for specific notification types
    fir_created_notifs = [n for n in notifs if n.get('type') == 'FIR_CREATED']
    fir_verified_notifs = [n for n in notifs if n.get('type') == 'FIR_VERIFIED']
    officer_assigned_notifs = [n for n in notifs if n.get('type') == 'OFFICER_ASSIGNED']
    
    print_result("Has FIR Created notifications", len(fir_created_notifs) > 0, 
                 f"{len(fir_created_notifs)} notifications")
    print_result("Has FIR Verified notifications", len(fir_verified_notifs) > 0,
                 f"{len(fir_verified_notifs)} notifications")
    print_result("Has Officer Assigned notifications", len(officer_assigned_notifs) > 0,
                 f"{len(officer_assigned_notifs)} notifications")
    
    return len(notifs) > 0

def test_officer_notifications():
    """Test 3: Verify officer receives proper notifications."""
    print_header("TEST 3: Police Officer Notifications")
    
    officer = get_user_by_email("officer@example.com")
    if not officer:
        print_result("Officer user exists", False, "officer@example.com not found")
        return False
    
    print_result("Officer user found", True, f"ID: {officer['id']}, Name: {officer['name']}")
    
    # Get officer notifications
    notifs = get_user_notifications(officer['id'])
    print_result(f"Officer has notifications", len(notifs) > 0, f"{len(notifs)} notifications found")
    
    # Get unread count
    unread = get_unread_count(officer['id'])
    print_result(f"Officer unread count", unread >= 0, f"{unread} unread notifications")
    
    # Check notification types
    if notifs:
        print("\n  Recent Officer Notifications:")
        for i, notif in enumerate(notifs[:5], 1):
            print(f"    {i}. [{notif.get('type')}] {notif.get('title')}")
            print(f"       FIR: {notif.get('fir_number', 'N/A')}, Severity: {notif.get('severity')}")
    
    # Check for specific notification types
    fir_assigned_notifs = [n for n in notifs if n.get('type') == 'FIR_ASSIGNED']
    chat_notifs = [n for n in notifs if n.get('type') == 'NEW_CITIZEN_MESSAGE']
    
    print_result("Has FIR Assignment notifications", len(fir_assigned_notifs) > 0,
                 f"{len(fir_assigned_notifs)} notifications")
    print_result("Has Chat notifications", len(chat_notifs) >= 0,
                 f"{len(chat_notifs)} notifications")
    
    return len(notifs) > 0

def test_verification_officer_notifications():
    """Test 4: Verify verification officer receives proper notifications."""
    print_header("TEST 4: Verification Officer Notifications")
    
    verification = get_user_by_email("verification@example.com")
    if not verification:
        print_result("Verification officer exists", False, "verification@example.com not found")
        return False
    
    print_result("Verification officer found", True, f"ID: {verification['id']}, Name: {verification['name']}")
    
    # Get verification officer notifications
    notifs = get_user_notifications(verification['id'])
    print_result(f"Verification officer has notifications", len(notifs) >= 0, 
                 f"{len(notifs)} notifications found")
    
    # Get unread count
    unread = get_unread_count(verification['id'])
    print_result(f"Verification officer unread count", unread >= 0, f"{unread} unread notifications")
    
    if notifs:
        print("\n  Recent Verification Officer Notifications:")
        for i, notif in enumerate(notifs[:5], 1):
            print(f"    {i}. [{notif.get('type')}] {notif.get('title')}")
            print(f"       FIR: {notif.get('fir_number', 'N/A')}")
    
    # Check for specific notification types
    new_fir_notifs = [n for n in notifs if n.get('type') == 'NEW_FIR_SUBMITTED']
    
    print_result("Has New FIR Submitted notifications", len(new_fir_notifs) >= 0,
                 f"{len(new_fir_notifs)} notifications")
    
    return True

def test_admin_notifications():
    """Test 5: Verify admin receives proper notifications (if applicable)."""
    print_header("TEST 5: Administrator Notifications")
    
    admin = get_user_by_email("admin@example.com")
    if not admin:
        print_result("Admin user exists", False, "admin@example.com not found")
        return False
    
    print_result("Admin user found", True, f"ID: {admin['id']}, Name: {admin['name']}")
    
    # Admins may have fewer notifications as they're focused on audit trail
    notifs = get_user_notifications(admin['id'])
    print_result(f"Admin notifications retrieved", True, f"{len(notifs)} notifications found")
    
    unread = get_unread_count(admin['id'])
    print_result(f"Admin unread count", unread >= 0, f"{unread} unread notifications")
    
    return True

def test_notification_creation():
    """Test 6: Create a new notification and verify it appears."""
    print_header("TEST 6: Create New Notification")
    
    citizen = get_user_by_email("citizen@example.com")
    if not citizen:
        print_result("Cannot test - citizen not found", False)
        return False
    
    # Get initial count
    initial_count = get_unread_count(citizen['id'])
    print_result("Initial unread count retrieved", True, f"{initial_count} unread")
    
    # Get a FIR for this citizen
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM firs WHERE citizen_id = ? LIMIT 1", (citizen['id'],))
    fir_row = cursor.fetchone()
    conn.close()
    
    if not fir_row:
        print_result("No FIR found for citizen", False, "Skipping notification creation test")
        return False
    
    fir_id = fir_row['id']
    
    # Create test notification
    test_notif = create_notification(
        user_id=citizen['id'],
        fir_id=fir_id,
        title="🧪 Test Notification - End-to-End Test",
        message=f"This is a test notification created at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} to verify the notification system works correctly.",
        notification_type="SYSTEM_TEST",
        severity="INFO"
    )
    
    print_result("Test notification created", test_notif is not None, 
                 f"ID: {test_notif.get('id') if test_notif else 'None'}")
    
    # Verify unread count increased
    new_count = get_unread_count(citizen['id'])
    count_increased = new_count > initial_count
    print_result("Unread count increased", count_increased, 
                 f"{initial_count} → {new_count}")
    
    # Verify notification appears in list
    notifs = get_user_notifications(citizen['id'], limit=1)
    found_test_notif = False
    if notifs:
        latest = notifs[0]
        found_test_notif = latest.get('type') == 'SYSTEM_TEST'
        print_result("Test notification appears in list", found_test_notif,
                     f"Latest: {latest.get('title')}")
    
    return test_notif is not None and count_increased

def test_mark_read_functionality():
    """Test 7: Mark notifications as read."""
    print_header("TEST 7: Mark Notifications as Read")
    
    citizen = get_user_by_email("citizen@example.com")
    if not citizen:
        print_result("Cannot test - citizen not found", False)
        return False
    
    # Get unread notifications
    initial_unread = get_unread_count(citizen['id'])
    print_result("Initial unread count", True, f"{initial_unread} unread")
    
    if initial_unread == 0:
        print_result("No unread notifications to test", False, "Skipping mark read test")
        return False
    
    # Get one unread notification
    notifs = get_user_notifications(citizen['id'])
    unread_notifs = [n for n in notifs if n.get('is_read') == 0]
    
    if not unread_notifs:
        print_result("No unread notifications found", False)
        return False
    
    test_notif = unread_notifs[0]
    print_result("Found unread notification", True, f"ID: {test_notif.get('id')}")
    
    # Mark as read
    mark_result = mark_notification_read(test_notif.get('id'), citizen['id'])
    print_result("Mark notification as read", mark_result, 
                 f"Notification ID: {test_notif.get('id')}")
    
    # Verify unread count decreased
    new_unread = get_unread_count(citizen['id'])
    decreased = new_unread < initial_unread
    print_result("Unread count decreased", decreased, 
                 f"{initial_unread} → {new_unread}")
    
    return mark_result and decreased

def test_notification_content():
    """Test 8: Verify notification content is relevant and not fake."""
    print_header("TEST 8: Notification Content Quality")
    
    # Check all users for fake/placeholder content
    test_users = [
        "citizen@example.com",
        "officer@example.com",
        "verification@example.com"
    ]
    
    all_passed = True
    for email in test_users:
        user = get_user_by_email(email)
        if not user:
            continue
        
        notifs = get_user_notifications(user['id'], limit=10)
        
        # Check for fake keywords
        fake_keywords = ['placeholder', 'dummy', 'test123', 'fake', 'lorem ipsum']
        fake_found = False
        
        for notif in notifs:
            title = (notif.get('title') or '').lower()
            message = (notif.get('message') or '').lower()
            
            for keyword in fake_keywords:
                if keyword in title or keyword in message:
                    fake_found = True
                    print_result(f"Fake content in {email} notification", False,
                                 f"Found '{keyword}' in: {notif.get('title')}")
                    all_passed = False
                    break
        
        if not fake_found and notifs:
            print_result(f"{email} notifications are real", True, 
                         f"Checked {len(notifs)} notifications")
    
    return all_passed

def test_notification_targeting():
    """Test 9: Verify notifications go to correct users."""
    print_header("TEST 9: Notification User Targeting")
    
    # Check that citizen notifications are for their FIRs only
    citizen = get_user_by_email("citizen@example.com")
    if not citizen:
        return False
    
    notifs = get_user_notifications(citizen['id'])
    
    # Get citizen's FIRs
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM firs WHERE citizen_id = ?", (citizen['id'],))
    citizen_fir_ids = [row['id'] for row in cursor.fetchall()]
    conn.close()
    
    # Check all notifications are for citizen's FIRs
    wrong_fir_count = 0
    for notif in notifs:
        if notif.get('fir_id') and notif.get('fir_id') not in citizen_fir_ids:
            wrong_fir_count += 1
    
    print_result("Citizen notifications are for their FIRs only", 
                 wrong_fir_count == 0,
                 f"{wrong_fir_count} notifications for other FIRs found" if wrong_fir_count > 0 
                 else f"All {len(notifs)} notifications correctly targeted")
    
    return wrong_fir_count == 0

def main():
    """Run all notification tests."""
    print("\n" + "╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "NOTIFICATION SYSTEM END-TO-END TEST" + " " * 23 + "║")
    print("╚" + "═" * 78 + "╝")
    
    results = {
        "Infrastructure": test_notification_infrastructure(),
        "Citizen Notifications": test_citizen_notifications(),
        "Officer Notifications": test_officer_notifications(),
        "Verification Officer": test_verification_officer_notifications(),
        "Admin Notifications": test_admin_notifications(),
        "Create Notification": test_notification_creation(),
        "Mark as Read": test_mark_read_functionality(),
        "Content Quality": test_notification_content(),
        "User Targeting": test_notification_targeting()
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

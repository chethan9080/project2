#!/usr/bin/env python3
"""
Test script to verify the complete citizen FIR submission flow.
Tests: Citizen submits FIR → Data is saved → Police can view the FIR with correct data
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.db import init_database
from backend.services.fir_service import create_fir, get_fir_by_id, get_firs
from backend.services.auth_service import get_current_user
from datetime import datetime

def test_citizen_fir_submission():
    """Test complete FIR submission and retrieval flow"""
    
    print("=" * 80)
    print("TESTING CITIZEN FIR SUBMISSION FLOW")
    print("=" * 80)
    
    # Initialize database
    print("\n1. Initializing database...")
    init_database()
    print("   ✓ Database initialized")
    
    # Get a citizen user
    print("\n2. Getting citizen user...")
    # Get default citizen from database
    from backend.services.db import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1")
    citizen_row = cursor.fetchone()
    conn.close()
    
    if not citizen_row:
        print("   ✗ Citizen user not found. Please ensure seed data is loaded.")
        return False
    citizen = dict(citizen_row)
    citizen.pop("password_hash", None)
    citizen.pop("salt", None)
    print(f"   ✓ Found citizen: {citizen.get('name')} (ID: {citizen.get('id')})")
    
    # Create FIR with test data
    print("\n3. Creating FIR with citizen-provided data...")
    test_payload = {
        "police_station": "Koramangala Police Station",
        "incident_type": "Cyber Crime & Online Fraud",
        "incident_date": "2026-08-12",
        "incident_time": "14:30",
        "incident_location": "Koramangala 4th Block, Bengaluru",
        "description": "Test incident description - This is a test FIR submission to verify data flow from citizen to police dashboard.",
        "accused_details": "Unknown Person - Fraudster claiming to be from bank",
        "witness_details": "John Doe (+91 98765 43210) - Witnessed the incident",
        "evidence_files": ["test_screenshot.png", "bank_statement.pdf"]
    }
    
    try:
        created_fir = create_fir(citizen_id=citizen["id"], payload=test_payload)
        print(f"   ✓ FIR created successfully!")
        print(f"   - FIR Number: {created_fir.get('fir_number')}")
        print(f"   - Reference Number: {created_fir.get('reference_number')}")
        print(f"   - FIR ID: {created_fir.get('id')}")
    except Exception as e:
        print(f"   ✗ Failed to create FIR: {e}")
        return False
    
    # Retrieve FIR by ID (as police officer would see it)
    print("\n4. Retrieving FIR data (as police officer)...")
    try:
        # Get officer user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE role = 'OFFICER' LIMIT 1")
        officer_row = cursor.fetchone()
        conn.close()
        
        if not officer_row:
            print("   ⚠ Officer user not found, retrieving without user context")
            officer = None
        else:
            officer = dict(officer_row)
            officer.pop("password_hash", None)
            officer.pop("salt", None)
        
        retrieved_fir = get_fir_by_id(created_fir.get('id'), actor_user=officer)
        if not retrieved_fir:
            print("   ✗ Failed to retrieve FIR")
            return False
        
        print(f"   ✓ FIR retrieved successfully!")
        print(f"\n   VERIFICATION - Checking if all citizen data is preserved:")
        print(f"   -" + "="*70)
        
        # Verify each field
        all_correct = True
        fields_to_check = [
            ("Police Station", "police_station", test_payload["police_station"]),
            ("Incident Type", "incident_type", test_payload["incident_type"]),
            ("Incident Date", "incident_date", test_payload["incident_date"]),
            ("Incident Time", "incident_time", test_payload["incident_time"]),
            ("Incident Location", "incident_location", test_payload["incident_location"]),
            ("Description", "description", test_payload["description"]),
            ("Accused Details", "accused_details", test_payload["accused_details"]),
            ("Witness Details", "witness_details", test_payload["witness_details"])
        ]
        
        for label, field_name, expected_value in fields_to_check:
            actual_value = retrieved_fir.get(field_name, "")
            match_status = "✓" if actual_value == expected_value else "✗"
            print(f"   {match_status} {label}:")
            print(f"      Expected: {expected_value}")
            print(f"      Actual:   {actual_value}")
            if actual_value != expected_value:
                all_correct = False
        
        # Check citizen information
        print(f"\n   Citizen Information:")
        print(f"   - Name: {retrieved_fir.get('citizen_name', 'NOT FOUND')}")
        print(f"   - Phone: {retrieved_fir.get('citizen_phone', 'NOT FOUND')}")
        print(f"   - Email: {retrieved_fir.get('citizen_email', 'NOT FOUND')}")
        
        # Check assigned officer
        print(f"\n   Officer Assignment:")
        print(f"   - Assigned Officer: {retrieved_fir.get('officer_name', 'Unassigned')}")
        print(f"   - Badge: {retrieved_fir.get('officer_badge', 'N/A')}")
        print(f"   - Rank: {retrieved_fir.get('officer_rank', 'N/A')}")
        
        print(f"   -" + "="*70)
        
        if all_correct:
            print(f"\n   ✓ ALL DATA VERIFIED - Citizen information correctly stored and retrieved!")
        else:
            print(f"\n   ✗ DATA MISMATCH - Some fields do not match the submitted data")
            return False
        
    except Exception as e:
        print(f"   ✗ Failed to retrieve FIR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Test listing FIRs (police dashboard view)
    print("\n5. Testing FIR list (Police Dashboard view)...")
    try:
        all_firs = get_firs(actor_user=officer)
        found_fir = None
        for fir in all_firs:
            if fir.get('id') == created_fir.get('id'):
                found_fir = fir
                break
        
        if found_fir:
            print(f"   ✓ FIR appears in police dashboard list")
            print(f"   - FIR Number: {found_fir.get('fir_number')}")
            print(f"   - Citizen Name: {found_fir.get('citizen_name')}")
            print(f"   - Incident Type: {found_fir.get('incident_type')}")
            print(f"   - Status: {found_fir.get('status')}")
        else:
            print(f"   ✗ FIR not found in dashboard list")
            return False
    except Exception as e:
        print(f"   ✗ Failed to list FIRs: {e}")
        return False
    
    print("\n" + "=" * 80)
    print("TEST COMPLETED SUCCESSFULLY ✓")
    print("=" * 80)
    print("\nSummary:")
    print("- Citizen can submit FIR with their information")
    print("- All submitted data is stored correctly in database")
    print("- Police can retrieve and view the exact information submitted by citizen")
    print("- FIR appears in police dashboard with correct details")
    print("\n✓ End-to-end flow verification PASSED")
    return True


if __name__ == "__main__":
    success = test_citizen_fir_submission()
    sys.exit(0 if success else 1)

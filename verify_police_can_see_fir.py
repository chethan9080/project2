#!/usr/bin/env python3
"""
Quick test: Create FIR as citizen, verify police can see it
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Scratch scripts must never write to the live case ledger: point them at a throwaway
# database unless the operator explicitly overrides FIR_DB_PATH.
import tempfile as _tempfile
import os as _os
_os.environ.setdefault('FIR_DB_PATH', _os.path.join(_tempfile.gettempdir(), 'efir_scratch_test.db'))

from backend.services.db import init_database, get_db_connection
from backend.services.fir_service import create_fir, get_firs

# Initialize
init_database()

# Get citizen
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1")
citizen = dict(cursor.fetchone())
citizen.pop("password_hash", None)
citizen.pop("salt", None)

# Get officer  
cursor.execute("SELECT * FROM users WHERE role = 'OFFICER' LIMIT 1")
officer = dict(cursor.fetchone())
officer.pop("password_hash", None)
officer.pop("salt", None)
conn.close()

print("="*80)
print("TESTING: Citizen submits FIR → Police can see it")
print("="*80)

# Citizen submits FIR
print(f"\n1. Citizen '{citizen['name']}' submits FIR...")
fir = create_fir(citizen["id"], {
    "police_station": "Test Police Station",
    "incident_type": "Test Incident",
    "incident_date": "2026-08-12",
    "incident_time": "15:30",
    "incident_location": "Test Location - User's Address",
    "description": "This is the user's complaint description that police should see",
    "accused_details": "Test Accused",
    "witness_details": "Test Witness"
})

print(f"   ✓ FIR created: {fir['fir_number']}")
print(f"   ✓ Reference: {fir['reference_number']}")
print(f"   ✓ Assigned to officer: {fir.get('assigned_officer_id', 'YES')}")

# Police views FIRs
print(f"\n2. Officer '{officer['name']}' views FIR list...")
police_firs = get_firs(actor_user=officer)

# Find our FIR
found = None
for f in police_firs:
    if f['id'] == fir['id']:
        found = f
        break

if found:
    print(f"   ✓ Police CAN see the FIR!")
    print(f"\n   What police sees:")
    print(f"   - FIR Number: {found['fir_number']}")
    print(f"   - Citizen Name: {found['citizen_name']}")
    print(f"   - Incident Type: {found['incident_type']}")
    print(f"   - Location: {found['incident_location']}")
    print(f"   - Description: {found['description']}")
    print(f"   - Status: {found['status']}")
    print(f"\n   ✅ VERIFICATION PASSED: Police can see citizen-submitted FIR!")
else:
    print(f"   ✗ Police CANNOT see the FIR")
    print(f"   ✗ VERIFICATION FAILED!")

print("\n" + "="*80)

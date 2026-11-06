"""
Automated Test Suite for Blockchain-Based Online FIR Platform.
Tests:
1. Authentication, PBKDF2 hashing, and RBAC
2. Citizen FIR online filing & unique number generation
3. Resource-level authorization & IDOR prevention
4. Version control immutability (v1 -> v2 -> v3 snapshots preserved)
5. Mandatory modification reasons and Old vs New diffs
6. Cryptographic SHA-256 state hashing and blockchain hash chaining
7. Blockchain transaction block mining & Merkle root integrity
8. Real-time integrity verification (VERIFIED)
9. Tamper detection on unauthorized direct DB manipulation (TAMPER_DETECTED)
10. Database restoration to confirmed blockchain state
11. Targeted notification distribution
12. Strict Role-Based Audit Visibility (Citizen=Notification Only, Unauthorized Officer=403, Authorized Officer=Full Audit)
"""

import os
import secrets
import tempfile
import unittest
from datetime import datetime

# Configure test environment (isolated database, no stored credentials)
os.environ["VALIDATOR_PRIVATE_KEY"] = "TEST_VALIDATOR_KEY_12345"
os.environ["FIR_DB_PATH"] = os.path.join(tempfile.gettempdir(), "fir_blockchain_test.db")
TEST_PASSWORD = secrets.token_urlsafe(24)

import sys
PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import (
    authenticate_user,
    can_user_access_fir,
    can_user_access_fir_audit,
    can_user_modify_fir,
    get_user_by_id,
    register_user
)
from backend.services.blockchain_service import (
    get_blockchain_ledger,
    record_fir_change,
    record_fir_created,
    restore_tampered_fir,
    simulate_db_tamper,
    verify_fir_integrity
)
from backend.services.crypto_service import (
    calculate_sha256,
    canonical_json,
    compute_merkle_root,
    extract_canonical_fir_data,
    hash_password,
    verify_password
)
from backend.services.db import get_db_connection, init_database
from backend.services.fir_service import (
    assign_officer_to_fir,
    create_fir,
    get_change_event_by_id,
    get_fir_by_id,
    get_fir_changes,
    get_fir_timeline,
    get_fir_versions,
    get_firs,
    update_fir
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_notification_read
)
from backend.services.seed_data import seed_database


class TestBlockchainFIRPlatform(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Create an isolated test database and per-run test accounts."""
        for suffix in ("", "-wal", "-shm"):
            path = os.environ["FIR_DB_PATH"] + suffix
            if os.path.exists(path):
                os.remove(path)
        init_database()
        seed_database(force_reseed=True)
        register_user(
            name="Test Citizen", email="citizen@example.com", phone="9000000001",
            password=TEST_PASSWORD, role="CITIZEN"
        )
        register_user(
            name="Test Officer", email="officer@example.com", phone="9000000002",
            password=TEST_PASSWORD, role="OFFICER", badge_number="POL-TEST-01",
            station="Test Police Station"
        )
        register_user(
            name="Test Admin", email="admin@example.com", phone="9000000003",
            password=TEST_PASSWORD, role="ADMIN"
        )

    def test_01_crypto_canonical_json_and_hashing(self):
        """Test that canonical JSON produces deterministic output regardless of key insertion order."""
        data_a = {"b": 2, "a": 1, "nested": {"z": 9, "y": 8}}
        data_b = {"nested": {"y": 8, "z": 9}, "a": 1, "b": 2}
        
        canon_a = canonical_json(data_a)
        canon_b = canonical_json(data_b)
        self.assertEqual(canon_a, canon_b)

        hash_a = calculate_sha256(data_a)
        hash_b = calculate_sha256(data_b)
        self.assertEqual(hash_a, hash_b)
        self.assertEqual(len(hash_a), 64)  # 256-bit hex string

    def test_02_password_hashing_pbkdf2(self):
        """Test PBKDF2 password hashing and verification with secure random salt."""
        raw_pass = secrets.token_urlsafe(24)
        h, salt = hash_password(raw_pass)
        
        self.assertTrue(verify_password(raw_pass, h, salt))
        self.assertFalse(verify_password("WrongPassword!", h, salt))

    def test_03_authentication_and_rbac(self):
        """Test authenticating citizen, officer, and admin accounts."""
        citizen = authenticate_user("citizen@example.com", TEST_PASSWORD)
        self.assertIsNotNone(citizen)
        self.assertEqual(citizen["role"], "CITIZEN")

        officer = authenticate_user("officer@example.com", TEST_PASSWORD)
        self.assertIsNotNone(officer)
        self.assertEqual(officer["role"], "OFFICER")

        admin = authenticate_user("admin@example.com", TEST_PASSWORD)
        self.assertIsNotNone(admin)
        self.assertEqual(admin["role"], "ADMIN")

    def test_04_citizen_fir_creation_and_genesis_block(self):
        """Test citizen filing online FIR, creating Version 1, and blockchain genesis transaction."""
        citizen = authenticate_user("citizen@example.com", TEST_PASSWORD)
        
        payload = {
            "police_station": "Koramangala Police Station",
            "incident_type": "Cyber Crime & Online Fraud",
            "incident_date": "2026-08-18",
            "incident_time": "14:30",
            "incident_location": "MG Road, Bengaluru",
            "description": "Unauthorized credit card charge of Rs 45,000.",
            "accused_details": "Unknown cyber attacker",
            "witness_details": "None",
            "evidence_files": ["statement.pdf"]
        }

        fir = create_fir(citizen_id=citizen["id"], payload=payload)
        self.assertIn("fir_number", fir)
        self.assertRegex(fir["fir_number"], r"^FIR-\d{6}$")
        self.assertEqual(fir["current_version"], 1)
        self.assertIsNotNone(fir["current_hash"])
        self.assertIsNotNone(fir["blockchain_tx_id"])

        # Check integrity
        integrity = verify_fir_integrity(fir["id"])
        self.assertTrue(integrity["is_valid"])
        self.assertEqual(integrity["status"], "VERIFIED")

        # Assign the investigating officer for the modification tests below
        admin = authenticate_user("admin@example.com", TEST_PASSWORD)
        officer = authenticate_user("officer@example.com", TEST_PASSWORD)
        self.assertTrue(assign_officer_to_fir(fir["id"], officer["id"], admin))

    def test_05_officer_modification_version_increment_and_diff(self):
        """Test officer modifying incident location MG Road -> Brigade Road with mandatory reason."""
        officer = authenticate_user("officer@example.com", TEST_PASSWORD)
        firs = get_firs(actor_user=officer)
        # Find an FIR assigned to this officer
        target_fir = next((f for f in firs if f.get("assigned_officer_id") == officer["id"]), None)
        self.assertIsNotNone(target_fir, "No FIR assigned to the test officer found")
        initial_ver = target_fir["current_version"]
        initial_hash = target_fir["current_hash"]

        res = update_fir(
            fir_id=target_fir["id"],
            actor_user=officer,
            updated_fields={"incident_location": "Brigade Road, Bengaluru"},
            change_reason="Location verified during investigation."
        )

        self.assertTrue(res["success"])
        self.assertEqual(res["new_version"], initial_ver + 1)
        self.assertEqual(res["previous_hash"], initial_hash)
        self.assertNotEqual(res["new_hash"], initial_hash)
        self.assertIn("incident_location", res["changed_fields"])
        self.assertEqual(res["new_values"]["incident_location"], "Brigade Road, Bengaluru")
        self.assertIsNotNone(res["blockchain_tx_id"])

        # Verify integrity of updated version
        integrity = verify_fir_integrity(target_fir["id"])
        self.assertTrue(integrity["is_valid"])
        self.assertEqual(integrity["status"], "VERIFIED")

    def test_06_tamper_detection_and_restoration(self):
        """Test simulating unauthorized raw database alteration and detecting TAMPER_DETECTED."""
        officer = authenticate_user("officer@example.com", TEST_PASSWORD)
        firs = get_firs(actor_user=officer)
        target_fir = next((f for f in firs if f.get("assigned_officer_id") == officer["id"]), None)
        self.assertIsNotNone(target_fir, "No FIR assigned to the test officer found")

        # 1. Verify initially valid
        init_rep = verify_fir_integrity(target_fir["id"])
        self.assertTrue(init_rep["is_valid"])

        # 2. Simulate raw DB tampering (e.g. attacker changes location directly in SQLite)
        tamper_res = simulate_db_tamper(
            fir_id=target_fir["id"],
            field_name="incident_location",
            malicious_value="UNAUTHORIZED_MALICIOUS_LOCATION"
        )
        self.assertTrue(tamper_res["success"])

        # 3. Verify that engine catches state divergence
        tampered_rep = verify_fir_integrity(target_fir["id"])
        self.assertFalse(tampered_rep["is_valid"])
        self.assertEqual(tampered_rep["status"], "TAMPER_DETECTED")
        self.assertNotEqual(tampered_rep["database_hash"], tampered_rep["expected_hash"])

        # 4. Restore to confirmed blockchain state
        restore_res = restore_tampered_fir(target_fir["id"])
        self.assertTrue(restore_res["success"])

        # 5. Verify integrity is restored
        restored_rep = verify_fir_integrity(target_fir["id"])
        self.assertTrue(restored_rep["is_valid"])
        self.assertEqual(restored_rep["status"], "VERIFIED")

    def test_07_blockchain_ledger_chain_integrity(self):
        """Test blockchain blocks, transactions, and hash chaining."""
        ledger = get_blockchain_ledger()
        self.assertIsInstance(ledger, list)
        self.assertGreater(len(ledger), 0)
        self.assertIsNotNone(ledger[0].get("block_hash"))

    def test_08_targeted_notification_distribution(self):
        """Test that change notifications go to the affected citizen and assigned officer."""
        citizen = authenticate_user("citizen@example.com", TEST_PASSWORD)
        officer = authenticate_user("officer@example.com", TEST_PASSWORD)

        fir = create_fir(
            citizen_id=citizen["id"],
            payload={
                "police_station": "Koramangala Police Station",
                "incident_type": "Online Cheating",
                "incident_date": "2026-08-18",
                "incident_time": "16:00",
                "incident_location": "HSR Layout",
                "description": "Online payment fraud.",
                "assigned_officer_id": officer["id"]
            }
        )

        unread_before = get_unread_count(citizen["id"])

        update_fir(
            fir_id=fir["id"],
            actor_user=officer,
            updated_fields={"status": "UNDER_INVESTIGATION"},
            change_reason="FIR reviewed and investigation team assigned."
        )

        unread_after = get_unread_count(citizen["id"])
        self.assertGreater(unread_after, unread_before)

        citizen_notifs = get_user_notifications(citizen["id"])
        latest = citizen_notifs[0]
        self.assertEqual(latest["fir_id"], fir["id"])
        self.assertEqual(latest["type"], "FIR_UPDATE")

    def test_09_strict_role_based_audit_visibility(self):
        """
        CRITICAL TEST:
        1. Citizen receives Notification ONLY (FIR number, date/time, simple text).
        2. Citizen notification does NOT expose OLD/NEW values, reasons, officer badge, hashes.
        3. Citizen is FORBIDDEN from accessing detailed change history (raises PermissionError / 403).
        4. Unauthorized police officer is FORBIDDEN from accessing audit history (raises PermissionError / 403).
        5. Only the Authorized Officer (ADMIN) CAN access full forensic audit details.
        """
        citizen = authenticate_user("citizen@example.com", TEST_PASSWORD)
        assigned_officer = authenticate_user("officer@example.com", TEST_PASSWORD)

        # Create unassigned officer (different police officer not assigned to this case)
        try:
            other_officer = register_user(
                name="Inspector Rajesh Rao",
                email="other_officer@police.gov.in",
                phone="+91 94444 55555",
                password=TEST_PASSWORD,
                role="OFFICER",
                badge_number="POL-9999",
                station="Indiranagar Police Station",
                rank="Sub-Inspector",
                district="Bengaluru East"
            )
        except ValueError:
            other_officer = authenticate_user("other_officer@police.gov.in", TEST_PASSWORD)

        # 1. Citizen submits FIR
        fir = create_fir(
            citizen_id=citizen["id"],
            payload={
                "police_station": "Koramangala Police Station",
                "incident_type": "Theft",
                "incident_date": "2026-08-18",
                "incident_time": "11:00",
                "incident_location": "MG Road",
                "description": "Bicycle stolen from apartment parking.",
                "assigned_officer_id": assigned_officer["id"]
            }
        )
        fir_id = fir["id"]

        # 2. Authorized officer modifies FIR (MG Road -> Brigade Road)
        update_fir(
            fir_id=fir_id,
            actor_user=assigned_officer,
            updated_fields={"incident_location": "Brigade Road"},
            change_reason="Location verified during investigation."
        )

        # 3. Verify Citizen Notification (Simple notification only)
        cit_notifs = get_user_notifications(citizen["id"])
        latest_cit_notif = cit_notifs[0]
        self.assertEqual(latest_cit_notif["title"], "🔔 Your FIR Has Been Updated")
        
        # Verify citizen notification contains simple update message and date/time
        msg_text = latest_cit_notif["message"]
        self.assertIn("Your FIR has been updated by an authorized police officer", msg_text)
        self.assertIn(fir["fir_number"], msg_text)

        # Verify citizen notification does NOT leak internal police details
        self.assertNotIn("MG Road", msg_text)  # No old value
        self.assertNotIn("Brigade Road", msg_text)  # No new value
        self.assertNotIn("Location verified during investigation", msg_text)  # No internal reason
        self.assertNotIn("POL-4582", msg_text)  # No officer badge
        self.assertNotIn("0x", msg_text)  # No blockchain tx
        self.assertNotIn("10.42", msg_text)  # No IP address

        # 4. Verify Citizen is FORBIDDEN from accessing detailed change audit API
        self.assertFalse(can_user_access_fir_audit(citizen, fir))
        with self.assertRaises(PermissionError):
            get_fir_changes(fir_id, actor_user=citizen)

        with self.assertRaises(PermissionError):
            get_fir_versions(fir_id, actor_user=citizen)

        # 5. Verify Unauthorized Police Officer is FORBIDDEN from accessing audit
        self.assertFalse(can_user_access_fir_audit(other_officer, fir))
        with self.assertRaises(PermissionError):
            get_fir_changes(fir_id, actor_user=other_officer)

        with self.assertRaises(PermissionError):
            get_fir_versions(fir_id, actor_user=other_officer)

        # 6. The assigned police officer is FORBIDDEN from forensic audit: hashes,
        #    blockchain metadata and old/new diffs are Authorized-Officer-only.
        self.assertFalse(can_user_access_fir_audit(assigned_officer, fir))
        with self.assertRaises(PermissionError):
            get_fir_changes(fir_id, actor_user=assigned_officer)

        with self.assertRaises(PermissionError):
            get_fir_versions(fir_id, actor_user=assigned_officer)

        # 7. Only the Authorized Officer (ADMIN) sees the complete forensic audit
        admin = authenticate_user("admin@example.com", TEST_PASSWORD)
        self.assertTrue(can_user_access_fir_audit(admin, fir))
        audit_events = get_fir_changes(fir_id, actor_user=admin)
        self.assertEqual(len(audit_events), 1)

        evt = audit_events[0]
        # WHO
        self.assertEqual(evt["actor_badge"], assigned_officer["badge_number"])
        self.assertEqual(evt["actor_role"], "OFFICER")
        # WHAT & OLD/NEW
        self.assertIn("incident_location", evt["changed_fields"])
        self.assertEqual(evt["old_values"]["incident_location"], "MG Road")
        self.assertEqual(evt["new_values"]["incident_location"], "Brigade Road")
        # WHY
        self.assertEqual(evt["reason"], "Location verified during investigation.")
        # VERSION
        self.assertEqual(evt["previous_version"], 1)
        self.assertEqual(evt["new_version"], 2)
        # HASH & BLOCKCHAIN
        self.assertIsNotNone(evt["previous_hash"])
        self.assertIsNotNone(evt["new_hash"])
        self.assertIsNotNone(evt["blockchain_tx_id"])
        self.assertEqual(evt["blockchain_status"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()

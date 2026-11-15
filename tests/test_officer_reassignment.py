"""
End-to-end tests for the Authorized Officer "Change Officer" workflow.

Covers transaction integrity, idempotency, audit preservation, notifications for
every role, revocation of the previous officer and seamless chat transfer.
"""

import os
import secrets
import tempfile
import unittest

os.environ.setdefault("VALIDATOR_PRIVATE_KEY", "TEST_VALIDATOR_KEY_REASSIGN")
os.environ["FIR_DB_PATH"] = os.path.join(tempfile.gettempdir(), "fir_reassignment_test.db")
TEST_PASSWORD = secrets.token_urlsafe(24)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import authenticate_user, register_user
from backend.services.blockchain_service import verify_fir_integrity
from backend.services.chat_service import get_messages, get_thread, send_message
from backend.services.db import get_db_connection, init_database
from backend.services.fir_service import assign_officer_to_fir, create_fir, get_fir_by_id, update_fir
from backend.services.fir_document_service import generate_fir_pdf, latest_document_path_for
from backend.services.investigation_service import (
    add_investigation_note,
    list_investigation_entries,
)
from backend.services.notification_service import get_user_notifications
from backend.services.authorized_officer_service import (
    get_complete_fir_case_history,
    reassign_fir_officer,
)
from backend.services.case_tracking_service import (
    CASE_STAGES,
    get_case_tracking_history,
    get_current_case_stage,
    get_fir_complete_tracking,
    update_case_stage,
)

REASON = "Security concern"


class TestOfficerReassignment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        for suffix in ("", "-wal", "-shm"):
            path = os.environ["FIR_DB_PATH"] + suffix
            if os.path.exists(path):
                os.remove(path)
        init_database()

        cls.citizen = register_user(
            name="Reassign Citizen", email="reassign.citizen@example.com", phone="9111000001",
            password=TEST_PASSWORD, role="CITIZEN",
        )
        cls.officer_one = register_user(
            name="Officer One", email="officer.one@example.com", phone="9111000002",
            password=TEST_PASSWORD, role="OFFICER", badge_number="RC-001",
            station="Central Police Station", rank="Police Inspector",
        )
        cls.officer_two = register_user(
            name="Officer Two", email="officer.two@example.com", phone="9111000003",
            password=TEST_PASSWORD, role="OFFICER", badge_number="RC-002",
            station="Central Police Station", rank="Sub Inspector",
        )
        cls.admin = register_user(
            name="Authorized Officer", email="authorized@example.com", phone="9111000004",
            password=TEST_PASSWORD, role="ADMIN", badge_number="AO-001",
        )
        cls.verifier = register_user(
            name="Verification Officer", email="verifier@example.com", phone="9111000005",
            password=TEST_PASSWORD, role="VERIFICATION_OFFICER", badge_number="VO-001",
        )

        cls.fir = create_fir(
            citizen_id=cls.citizen["id"],
            payload={
                "police_station": "Central Police Station",
                "incident_type": "Cyber Crime & Online Fraud",
                "incident_date": "2026-11-01",
                "incident_time": "10:30",
                "incident_location": "MG Road, Bengaluru",
                "description": "Unauthorized transfer of funds from a savings account.",
                "accused_details": "Unknown",
                "witness_details": "None",
                "evidence_files": ["bank-statement.pdf"],
            },
        )
        assert assign_officer_to_fir(cls.fir["id"], cls.officer_one["id"], cls.admin)
        # Move the assigned case out of verification through the audited update
        # path so the stored hash and ledger stay consistent (citizen chat opens).
        update_fir(
            fir_id=cls.fir["id"],
            actor_user=cls.admin,
            updated_fields={"status": "UNDER_INVESTIGATION"},
            change_reason="Case taken up for investigation.",
        )
        assigned_fir = get_fir_by_id(cls.fir["id"], cls.admin)
        cls.fir_number_before = assigned_fir["fir_number"]
        cls.hash_before = assigned_fir["current_hash"]
        cls.version_before = assigned_fir["current_version"]
        cls.integrity_before = verify_fir_integrity(cls.fir["id"])

    def _current_rows(self):
        conn = get_db_connection()
        try:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM officer_assignments WHERE fir_id = ? ORDER BY assigned_at ASC",
                (self.fir["id"],),
            ).fetchall()]
        finally:
            conn.close()

    def test_01_previous_officer_has_access_and_chat_before_change(self):
        fir = get_fir_by_id(self.fir["id"], self.officer_one)
        self.assertEqual(fir["assigned_officer_id"], self.officer_one["id"])
        thread = get_thread(self.fir["id"], self.officer_one)
        self.assertTrue(thread and thread["can_chat"])

        message = send_message(
            self.fir["id"], self.citizen, self.officer_one["id"],
            "Sharing the bank statement for review.", is_complaint=False,
        )
        self.assertTrue(message["id"].startswith("msg-"))
        self.assertEqual(len(get_messages(self.fir["id"])), 1)

        note = add_investigation_note(
            self.fir["id"], self.officer_one, "Initial review", "Statement received and logged.",
        )
        self.assertTrue(note)

    def test_02_change_officer_is_atomic_and_preserves_the_fir(self):
        result = reassign_fir_officer(
            self.fir["id"], self.officer_two["id"], REASON, self.admin,
            remarks="Supervision review requested a fresh lead.",
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["access_verified"])
        self.assertFalse(result.get("already_assigned"))
        self.assertEqual(result["fir_number"], self.fir_number_before)
        self.assertEqual(result["previous_officer"]["id"], self.officer_one["id"])
        self.assertEqual(result["new_officer"]["id"], self.officer_two["id"])

        rows = self._current_rows()
        self.assertEqual(len(rows), 2)
        by_officer = {row["officer_id"]: row for row in rows}
        previous = by_officer[self.officer_one["id"]]
        current = by_officer[self.officer_two["id"]]
        self.assertEqual(previous["status"], "REASSIGNED")
        self.assertTrue(previous["revoked_at"])
        self.assertEqual(previous["reason"], REASON)
        self.assertEqual(current["status"], "ACTIVE")
        self.assertEqual(current["officer_id"], self.officer_two["id"])
        self.assertEqual(current["reason"], REASON)
        self.assertEqual(current["remarks"], "Supervision review requested a fresh lead.")

        conn = get_db_connection()
        try:
            fir_count = conn.execute(
                "SELECT COUNT(*) FROM firs WHERE fir_number = ?", (self.fir_number_before,)
            ).fetchone()[0]
            fir_row = conn.execute("SELECT * FROM firs WHERE id = ?", (self.fir["id"],)).fetchone()
            audit = conn.execute(
                "SELECT * FROM fir_change_events WHERE fir_id = ? AND event_type = 'OFFICER_REASSIGNMENT'",
                (self.fir["id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(fir_count, 1, "Reassignment must never duplicate the FIR")
        self.assertEqual(fir_row["fir_number"], self.fir_number_before)
        self.assertEqual(fir_row["current_hash"], self.hash_before)
        self.assertEqual(fir_row["current_version"], self.version_before)
        self.assertIsNotNone(audit)
        self.assertEqual(audit["new_hash"], self.hash_before)
        self.assertEqual(audit["previous_hash"], self.hash_before)
        self.assertEqual(audit["actor_id"], self.admin["id"])
        self.assertIn(REASON, audit["reason"])

        integrity = verify_fir_integrity(self.fir["id"])
        self.assertTrue(integrity["is_valid"], integrity)
        self.assertEqual(self.integrity_before["blockchain_hash"], integrity["blockchain_hash"])

    def test_03_previous_officer_access_is_revoked_everywhere(self):
        with self.assertRaises(PermissionError):
            get_fir_by_id(self.fir["id"], self.officer_one)
        self.assertIsNone(get_thread(self.fir["id"], self.officer_one))
        with self.assertRaises(PermissionError):
            send_message(self.fir["id"], self.officer_one, self.citizen["id"], "Still here?")
        with self.assertRaises(PermissionError):
            add_investigation_note(
                self.fir["id"], self.officer_one, "Late note", "This must be rejected.",
            )
        with self.assertRaises(PermissionError):
            list_investigation_entries(self.fir["id"], self.officer_one)
        with self.assertRaises(PermissionError):
            update_fir(
                fir_id=self.fir["id"],
                actor_user=self.officer_one,
                updated_fields={"description": "Unauthorized edit attempt."},
                change_reason="Should be rejected.",
            )

        # Historical records stay intact and readable by the authorized desk.
        messages = get_messages(self.fir["id"])
        self.assertEqual(len(messages), 1)
        self.assertIn("bank statement", messages[0]["message"])

    def test_04_new_officer_immediately_owns_case_history_and_chat(self):
        fir = get_fir_by_id(self.fir["id"], self.officer_two)
        self.assertEqual(fir["assigned_officer_id"], self.officer_two["id"])
        self.assertEqual(fir["citizen_id"], self.citizen["id"])

        thread = get_thread(self.fir["id"], self.officer_two)
        self.assertTrue(thread and thread["can_chat"])
        self.assertEqual(thread["participant_id"], self.citizen["id"])
        self.assertEqual(len(get_messages(self.fir["id"])), 1)

        reply = send_message(
            self.fir["id"], self.officer_two, self.citizen["id"],
            "I have the statement. Continuing the investigation.",
        )
        self.assertTrue(reply["id"])
        self.assertEqual(len(get_messages(self.fir["id"])), 2)

        citizen_thread = get_thread(self.fir["id"], self.citizen)
        self.assertEqual(citizen_thread["participant_id"], self.officer_two["id"])

        # The previous investigator's notes and the original evidence come across intact.
        entries = list_investigation_entries(self.fir["id"], self.officer_two)
        self.assertTrue(any(e.get("title") == "Initial review" for e in entries))
        self.assertIn("bank-statement.pdf", fir.get("evidence_files") or "")

    def test_05_new_officer_can_open_the_latest_document(self):
        try:
            generate_fir_pdf(self.fir["id"], self.admin)
        except Exception as exc:  # PDF engine unavailable in a minimal environment
            self.skipTest(f"PDF generation unavailable: {exc}")
        document = latest_document_path_for(self.fir["id"], self.officer_two)
        self.assertIsNotNone(document)
        self.assertIsNone(latest_document_path_for(self.fir["id"], self.officer_one))

    def test_06_notifications_reach_every_role_in_the_same_workflow(self):
        new_officer_notifs = get_user_notifications(self.officer_two["id"])
        match = next((n for n in new_officer_notifs if n["title"] == "New FIR Assigned to You"), None)
        self.assertIsNotNone(match, "New officer did not receive the assignment notification")
        self.assertIn(
            "An existing FIR has been reassigned to you by the Authorized Officer.", match["message"]
        )
        self.assertIn(self.fir_number_before, match["message"])
        self.assertIn(self.citizen["name"], match["message"])
        self.assertIn(f"/police/fir/{self.fir['id']}", match["message"])

        citizen_notifs = get_user_notifications(self.citizen["id"])
        citizen_match = next(
            (n for n in citizen_notifs if n["title"] == "Your FIR has been assigned to a new Police Officer."),
            None,
        )
        self.assertIsNotNone(citizen_match)
        self.assertIn(self.fir_number_before, citizen_match["message"])
        self.assertIn(self.officer_two["name"], citizen_match["message"])
        self.assertNotIn(REASON.lower(), citizen_match["message"].lower(),
                         "Internal reassignment reason must not leak to the citizen")

        previous_notifs = get_user_notifications(self.officer_one["id"])
        self.assertTrue(any(n["title"] == "FIR Reassigned to Another Officer" for n in previous_notifs))

        admin_notifs = get_user_notifications(self.admin["id"])
        self.assertTrue(any(n["title"] == "Officer Reassignment Recorded" for n in admin_notifs))

        verifier_notifs = get_user_notifications(self.verifier["id"])
        self.assertTrue(any(n["title"] == "Investigating Officer Reassigned" for n in verifier_notifs))

    def test_07_replaying_the_same_request_is_idempotent(self):
        before_rows = self._current_rows()
        before_new = len([
            n for n in get_user_notifications(self.officer_two["id"])
            if n["title"] == "New FIR Assigned to You"
        ])
        repeated = reassign_fir_officer(
            self.fir["id"], self.officer_two["id"], REASON, self.admin,
        )
        self.assertTrue(repeated["success"])
        self.assertTrue(repeated.get("already_assigned"))
        self.assertEqual(len(self._current_rows()), len(before_rows))
        after_new = len([
            n for n in get_user_notifications(self.officer_two["id"])
            if n["title"] == "New FIR Assigned to You"
        ])
        self.assertEqual(after_new, before_new)

    def test_08_invalid_target_rolls_back_without_partial_state(self):
        before = self._current_rows()
        with self.assertRaises(ValueError):
            reassign_fir_officer(self.fir["id"], self.citizen["id"], REASON, self.admin)
        with self.assertRaises(ValueError):
            reassign_fir_officer(self.fir["id"], "missing-officer", REASON, self.admin)
        after = self._current_rows()
        self.assertEqual([r["id"] for r in before], [r["id"] for r in after])
        fir = get_fir_by_id(self.fir["id"], self.officer_two)
        self.assertEqual(fir["assigned_officer_id"], self.officer_two["id"])

    def test_09_non_authorized_roles_cannot_change_the_officer(self):
        with self.assertRaises(PermissionError):
            reassign_fir_officer(self.fir["id"], self.officer_one["id"], REASON, self.verifier)
        with self.assertRaises(PermissionError):
            reassign_fir_officer(self.fir["id"], self.officer_one["id"], REASON, self.officer_two)

    def test_10_authorized_officer_can_audit_versions_hashes_and_reassignment(self):
        record = get_complete_fir_case_history(self.fir["id"], self.admin)

        assignments = {a["officer_id"]: a for a in record["assignments"]}
        self.assertEqual(assignments[self.officer_one["id"]]["status"], "REASSIGNED")
        self.assertTrue(assignments[self.officer_one["id"]]["revoked_at"])
        self.assertEqual(assignments[self.officer_two["id"]]["status"], "ACTIVE")
        self.assertEqual(assignments[self.officer_two["id"]]["reason"], REASON)

        event = next(
            m for m in record["all_modifications"]
            if "assigned_officer_id" in (m.get("changed_fields") or [])
        )
        self.assertEqual(event["actor_id"], self.admin["id"])
        self.assertIn(REASON, event["reason"])
        self.assertEqual(event["previous_hash"], self.hash_before)
        self.assertEqual(event["new_hash"], self.hash_before)
        self.assertIn(
            self.officer_two["name"],
            event["new_values"].get("assigned_officer_id", ""),
        )

        self.assertGreaterEqual(len(record["versions"]), 1)
        for version in record["versions"]:
            self.assertRegex(version["current_hash"], r"^[0-9a-f]{64}$")
        for previous, current in zip(record["versions"], record["versions"][1:]):
            self.assertEqual(current["previous_hash"], previous["current_hash"])
        self.assertTrue(record["integrity_verification"]["is_valid"])

        with self.assertRaises(PermissionError):
            get_complete_fir_case_history(self.fir["id"], self.citizen)


class TestReassignmentKeepsInvestigationStage(unittest.TestCase):
    """A mid-investigation handover must not rewind the citizen's live timeline."""

    @classmethod
    def setUpClass(cls):
        cls.citizen = register_user(
            name="Stage Citizen", email="stage.citizen@example.com", phone="9111000011",
            password=TEST_PASSWORD, role="CITIZEN",
        )
        cls.officer_one = register_user(
            name="Stage Officer One", email="stage.one@example.com", phone="9111000012",
            password=TEST_PASSWORD, role="OFFICER", badge_number="STG-001",
            station="Central Police Station",
        )
        cls.officer_two = register_user(
            name="Stage Officer Two", email="stage.two@example.com", phone="9111000013",
            password=TEST_PASSWORD, role="OFFICER", badge_number="STG-002",
            station="Central Police Station",
        )
        cls.admin = register_user(
            name="Stage Authorized Officer", email="stage.admin@example.com", phone="9111000014",
            password=TEST_PASSWORD, role="ADMIN", badge_number="STG-AO",
        )
        cls.fir = create_fir(
            citizen_id=cls.citizen["id"],
            payload={
                "police_station": "Central Police Station",
                "incident_type": "Theft",
                "incident_date": "2026-11-02",
                "incident_time": "09:00",
                "incident_location": "Market Road",
                "description": "Bicycle stolen from outside the market.",
                "accused_details": "Unknown",
                "witness_details": "Shopkeeper",
                "evidence_files": [],
            },
        )
        assert assign_officer_to_fir(cls.fir["id"], cls.officer_one["id"], cls.admin)
        update_fir(
            fir_id=cls.fir["id"],
            actor_user=cls.admin,
            updated_fields={"status": "UNDER_INVESTIGATION"},
            change_reason="Investigation opened.",
        )
        update_case_stage(cls.fir["id"], "INVESTIGATION_STARTED", cls.officer_one,
                          remarks="First steps taken.")
        update_case_stage(cls.fir["id"], "EVIDENCE_COLLECTION", cls.officer_one,
                          remarks="Collecting CCTV footage.")

    def test_reassignment_preserves_current_stage_and_history(self):
        stage_before = get_current_case_stage(self.fir["id"])
        history_before = get_case_tracking_history(self.fir["id"])
        self.assertEqual(stage_before, "EVIDENCE_COLLECTION")

        result = reassign_fir_officer(
            self.fir["id"], self.officer_two["id"], "Investigation continuity", self.admin,
        )
        self.assertTrue(result["success"])

        stage_after = get_current_case_stage(self.fir["id"])
        history_after = get_case_tracking_history(self.fir["id"])
        self.assertEqual(stage_after, stage_before,
                         "Reassignment must not reset the investigation stage")
        self.assertEqual(len(history_after), len(history_before),
                         "Reassignment must not insert a timeline stage")
        self.assertEqual(history_after[-1]["new_stage"], "EVIDENCE_COLLECTION")

        tracking = get_fir_complete_tracking(self.fir["id"], self.citizen)
        self.assertEqual(tracking["current_stage_key"], "EVIDENCE_COLLECTION")
        self.assertEqual(tracking["current_stage_index"],
                         CASE_STAGES.index("EVIDENCE_COLLECTION") + 1)
        officer_stage = next(s for s in tracking["stages"] if s["key"] == "OFFICER_ASSIGNED")
        self.assertIn("Stage Officer Two", officer_stage["officer_info"])
        self.assertIn("reassigned", officer_stage["description"].lower())


if __name__ == "__main__":
    unittest.main()

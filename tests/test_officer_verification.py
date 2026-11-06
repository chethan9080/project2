"""
Automated Test Suite for Authorized Officer Police Officer Verification.

Tests:
1. Only an Authorized Officer may read an officer's verification dossier
2. The directory lists pending and suspended accounts, not only active ones
3. Verify, suspend and return-to-pending decisions persist the account status,
   the verification status and the verification timestamp
4. Every decision is written to the audit trail with the acting officer and the
   optional reason, and notifies the officer concerned
5. A suspended or unverified officer cannot sign in, and an already open staff
   session stops being honoured
6. The dossier exposes the officer's assigned FIR cases and assignment trail
7. No password material or citizen identity document path leaves the service
"""

import itertools
import json
import os
import shutil
import tempfile
import unittest

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_officer_verification_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'officer_verification_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import (
    authenticate_user,
    get_all_officers,
    get_all_police_officers,
    get_staff_access_issue,
    register_user,
    update_officer_verification_status,
)
from backend.services.case_tracking_service import init_case_tracking_table
from backend.services.complaint_service import assign_officer_to_complaint, create_complaint
from backend.services.complaint_verification_service import record_complaint_verification_action
from backend.services.db import get_db_connection, init_database
from backend.services.fir_service import create_fir_from_complaint, get_fir_by_id
from backend.services.investigation_service import (
    get_admin_officer_record,
    init_investigation_tables,
    record_investigation_action,
)
from backend.services.notification_service import get_user_notifications

PASSWORD = 'OfficerVerifyPass!23'
COUNTER = itertools.count(1)
STATION = 'Verification Desk Police Station'


class OfficerVerificationTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(
            TEST_DB_DIRECTORY, f'verify_{self.id()}.db')
        init_database()
        init_case_tracking_table()
        init_investigation_tables()

        self.citizen = register_user(
            name='Verification Citizen', email=f'citizen{next(COUNTER)}@verify.test',
            phone='9000000401', password=PASSWORD, role='CITIZEN', status='ACTIVE')
        self.officer = register_user(
            name='Verification Investigator', email=f'officer{next(COUNTER)}@verify.test',
            phone='9000000402', password=PASSWORD, role='OFFICER', status='ACTIVE',
            badge_number='VER-PSI-01', station=STATION, rank='Police Sub Inspector')
        self.pending = register_user(
            name='Unreviewed Constable', email=f'pending{next(COUNTER)}@verify.test',
            phone='9000000403', password=PASSWORD, role='OFFICER',
            status='PENDING_VERIFICATION', badge_number='VER-PC-02', station=STATION,
            rank='Police Constable')
        self.vo = register_user(
            name='Verification Desk Officer', email=f'vo{next(COUNTER)}@verify.test',
            phone='9000000404', password=PASSWORD, role='VERIFICATION_OFFICER',
            status='ACTIVE', badge_number='VER-VO-01', station=STATION)
        self.ao = register_user(
            name='Verification Authorized Officer', email=f'ao{next(COUNTER)}@verify.test',
            phone='9000000405', password=PASSWORD, role='ADMIN', status='ACTIVE',
            badge_number='VER-AO-01', station=STATION)

        self.complaint = create_complaint(self.citizen['id'], {
            'category': 'Theft',
            'title': 'Cycle stolen from the station yard',
            'description': 'A cycle was taken from the parking yard overnight.',
            'location': 'Station Yard, Ward 7',
            'district': 'Bengaluru Urban',
            'state': 'Karnataka',
            'police_station': STATION,
            'incident_date': '2026-10-25',
            'incident_time': '23:10',
        })
        record_complaint_verification_action(
            self.complaint['id'], self.vo, 'VERIFY', 'Complaint verified for registration.')
        assign_officer_to_complaint(self.complaint['id'], self.officer['id'], self.vo)
        created = create_fir_from_complaint(self.complaint['id'], self.vo)
        self.fir_id = created['fir_id']
        self.fir = get_fir_by_id(self.fir_id)

    # --------------------------------------
    # helpers
    # --------------------------------------
    def record(self, officer_id=None):
        return get_admin_officer_record(officer_id or self.officer['id'], self.ao)

    def account(self, officer_id=None):
        conn = get_db_connection()
        row = conn.execute(
            "SELECT status, verification_status, verified_at FROM users WHERE id = ?",
            ((officer_id or self.officer['id']),)).fetchone()
        conn.close()
        return dict(row)

    def decide(self, status, remarks=None, officer_id=None):
        return update_officer_verification_status(
            officer_id or self.officer['id'], status, self.ao, remarks)

    def audit_rows(self, officer_id=None):
        conn = get_db_connection()
        rows = [dict(r) for r in conn.execute("""
            SELECT * FROM system_audit_logs
            WHERE action = 'OFFICER_STATUS_UPDATE' AND resource_id = ?
            ORDER BY timestamp ASC
        """, ((officer_id or self.officer['id']),)).fetchall()]
        conn.close()
        return rows

    def notifications_for(self, user_id):
        return get_user_notifications(user_id, limit=200)

    def close_case(self):
        for stage in ('INVESTIGATION_STARTED', 'EVIDENCE_COLLECTION',
                      'INVESTIGATION_IN_PROGRESS', 'INVESTIGATION_COMPLETED', 'CASE_CLOSED'):
            record_investigation_action(
                self.fir_id, stage, 'STARTED', self.officer,
                'Case closed after the charge sheet was accepted by the court.'
                if stage == 'CASE_CLOSED' else f'{stage} recorded for this case.')
            if stage != 'CASE_CLOSED':
                record_investigation_action(
                    self.fir_id, stage, 'COMPLETED', self.officer,
                    f'{stage} completed with recorded findings.',
                    public_note='Investigation is progressing as recorded.')

    # --------------------------------------
    # access control
    # --------------------------------------
    def test_only_authorized_officers_may_read_the_dossier(self):
        for actor in (None, self.citizen, self.officer, self.vo):
            with self.assertRaises(PermissionError) as caught:
                get_admin_officer_record(self.officer['id'], actor)
            self.assertIn('Authorized Officer', str(caught.exception))

    def test_unknown_or_non_officer_accounts_are_refused(self):
        with self.assertRaises(ValueError):
            get_admin_officer_record('usr-does-not-exist', self.ao)
        with self.assertRaises(ValueError):
            get_admin_officer_record(self.citizen['id'], self.ao)
        with self.assertRaises(ValueError):
            self.decide('ACTIVE', officer_id=self.vo['id'])

    def test_only_authorized_officers_may_change_status(self):
        for actor in (None, self.citizen, self.officer, self.vo):
            with self.assertRaises(PermissionError):
                update_officer_verification_status(self.officer['id'], 'SUSPENDED', actor)
        self.assertEqual(self.account()['status'], 'ACTIVE')
        self.assertEqual(self.audit_rows(), [])

    def test_invalid_status_is_refused(self):
        with self.assertRaises(ValueError):
            self.decide('DELETED')
        self.assertEqual(self.account()['status'], 'ACTIVE')

    # --------------------------------------
    # directory
    # --------------------------------------
    def test_directory_includes_pending_and_suspended_accounts(self):
        self.decide('SUSPENDED', 'Credential check failed.', officer_id=self.officer['id'])
        everyone = {o['id']: o for o in get_all_police_officers()}
        self.assertIn(self.officer['id'], everyone)
        self.assertIn(self.pending['id'], everyone)
        self.assertEqual(everyone[self.officer['id']]['status'], 'SUSPENDED')
        self.assertEqual(everyone[self.pending['id']]['status'], 'PENDING_VERIFICATION')
        self.assertNotIn(self.vo['id'], everyone)
        self.assertNotIn(self.ao['id'], everyone)

        active_only = {o['id'] for o in get_all_officers()}
        self.assertNotIn(self.officer['id'], active_only)
        self.assertNotIn(self.pending['id'], active_only)

    def test_directory_reports_real_case_counts(self):
        entry = next(o for o in get_all_police_officers() if o['id'] == self.officer['id'])
        self.assertEqual(entry['active_cases_count'], 1)
        self.assertEqual(entry['total_assignments_count'], 1)
        pending_entry = next(o for o in get_all_police_officers() if o['id'] == self.pending['id'])
        self.assertEqual(pending_entry['active_cases_count'], 0)
        self.assertEqual(pending_entry['total_assignments_count'], 0)

    def test_closed_case_leaves_the_active_count(self):
        self.close_case()
        entry = next(o for o in get_all_police_officers() if o['id'] == self.officer['id'])
        self.assertEqual(entry['active_cases_count'], 0)
        self.assertEqual(entry['total_assignments_count'], 1)
        record = self.record()
        self.assertEqual(record['stats']['closed'], 1)
        self.assertEqual(record['stats']['total'], 1)

    # --------------------------------------
    # decisions
    # --------------------------------------
    def test_verification_records_status_and_timestamp(self):
        self.assertIsNone(self.account(self.pending['id'])['verified_at'])
        self.decide('ACTIVE', 'Badge and service record checked.', officer_id=self.pending['id'])
        account = self.account(self.pending['id'])
        self.assertEqual(account['status'], 'ACTIVE')
        self.assertEqual(account['verification_status'], 'VERIFIED')
        self.assertTrue(account['verified_at'])

    def test_suspension_keeps_the_original_verification_date(self):
        self.decide('ACTIVE', 'Service record checked.')
        verified_at = self.account()['verified_at']
        self.decide('SUSPENDED', 'Complaint against the officer under enquiry.')
        account = self.account()
        self.assertEqual(account['status'], 'SUSPENDED')
        self.assertEqual(account['verification_status'], 'SUSPENDED')
        self.assertEqual(account['verified_at'], verified_at)

    def test_return_to_pending_does_not_invent_a_verification_date(self):
        self.decide('PENDING_VERIFICATION', 'Badge number could not be confirmed.')
        account = self.account()
        self.assertEqual(account['status'], 'PENDING_VERIFICATION')
        self.assertEqual(account['verification_status'], 'PENDING')
        self.assertIsNone(account['verified_at'])

    def test_decision_is_audited_with_the_acting_officer_and_reason(self):
        self.decide('SUSPENDED', 'Misuse of the case file reported.')
        rows = self.audit_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row['user_id'], self.ao['id'])
        self.assertEqual(row['role'], 'ADMIN')
        self.assertEqual(row['resource_id'], self.officer['id'])
        self.assertIn('ACTIVE -> SUSPENDED', row['details'])
        self.assertIn('Misuse of the case file reported.', row['details'])
        self.assertIn('VER-PSI-01', row['details'])

    def test_decision_without_a_reason_is_still_recorded(self):
        self.decide('SUSPENDED')
        rows = self.audit_rows()
        self.assertEqual(len(rows), 1)
        self.assertIn('Remarks: None', rows[0]['details'])

    def test_decision_history_lists_every_decision(self):
        self.decide('SUSPENDED', 'Enquiry opened.')
        self.decide('ACTIVE', 'Enquiry closed, officer cleared.')
        decisions = self.record()['decisions']
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0]['details'], self.audit_rows()[-1]['details'])
        for decision in decisions:
            self.assertEqual(decision['decided_by_name'], self.ao['name'])
            self.assertEqual(decision['decided_by_badge'], 'VER-AO-01')
            self.assertTrue(decision['timestamp'])

    def test_decision_notifies_only_the_officer_concerned(self):
        self.decide('SUSPENDED', 'Account placed under review.')

        def status_notes(user_id):
            return [n for n in self.notifications_for(user_id)
                    if n['type'] == 'OFFICER_STATUS_UPDATE']

        notes = status_notes(self.officer['id'])
        self.assertEqual(len(notes), 1)
        self.assertIn('SUSPENDED', notes[0]['message'])
        self.assertIn(self.ao['name'], notes[0]['message'])
        self.assertIn('Account placed under review.', notes[0]['message'])
        for other in (self.citizen, self.pending, self.vo, self.ao):
            self.assertEqual(status_notes(other['id']), [], other['role'])

    # --------------------------------------
    # access really is revoked
    # --------------------------------------
    def test_suspended_officer_cannot_sign_in(self):
        self.assertIsNotNone(
            authenticate_user(self.officer['email'], PASSWORD, required_role='OFFICER'))
        self.decide('SUSPENDED', 'Account suspended pending enquiry.')
        self.assertIsNone(
            authenticate_user(self.officer['email'], PASSWORD, required_role='OFFICER'))
        self.assertIsNone(
            authenticate_user('VER-PSI-01', PASSWORD, required_role='OFFICER'))

    def test_unverified_officer_cannot_sign_in_until_reviewed(self):
        self.assertIsNone(
            authenticate_user(self.pending['email'], PASSWORD, required_role='OFFICER'))
        self.decide('ACTIVE', 'Credentials verified.', officer_id=self.pending['id'])
        signed_in = authenticate_user(self.pending['email'], PASSWORD, required_role='OFFICER')
        self.assertIsNotNone(signed_in)
        self.assertEqual(signed_in['id'], self.pending['id'])

    def test_open_staff_session_stops_after_suspension(self):
        self.assertIsNone(get_staff_access_issue(self.officer))
        self.decide('SUSPENDED', 'Account suspended pending enquiry.')
        self.assertIn('suspended', get_staff_access_issue(self.officer).lower())
        self.decide('PENDING_VERIFICATION', 'Verification withdrawn.')
        self.assertIn('awaiting verification', get_staff_access_issue(self.officer).lower())
        self.decide('ACTIVE', 'Officer cleared.')
        self.assertIsNone(get_staff_access_issue(self.officer))

    def test_citizen_and_missing_accounts_are_handled_separately(self):
        self.assertIsNone(get_staff_access_issue(self.citizen))
        self.assertIsNone(get_staff_access_issue(None))
        self.assertIn('no longer exists', get_staff_access_issue(
            dict(self.officer, id='usr-gone')))

    # --------------------------------------
    # dossier content
    # --------------------------------------
    def test_dossier_lists_the_assigned_case_and_assignment_trail(self):
        record = self.record()
        self.assertEqual(record['officer']['badge_number'], 'VER-PSI-01')
        self.assertEqual(record['officer']['rank'], 'Police Sub Inspector')
        self.assertEqual(record['officer']['station'], STATION)
        self.assertEqual(len(record['cases']), 1)
        case = record['cases'][0]
        self.assertEqual(case['id'], self.fir_id)
        self.assertEqual(case['fir_number'], self.fir['fir_number'])
        self.assertEqual(case['citizen_name'], self.citizen['name'])
        self.assertEqual(case['complaint_reference'], self.complaint['reference'])
        self.assertTrue(case['assigned_at'])
        self.assertTrue(case['stage_label'])

        self.assertEqual(len(record['assignments']), 1)
        assignment = record['assignments'][0]
        self.assertEqual(assignment['fir_id'], self.fir_id)
        self.assertEqual(assignment['status'], 'ACTIVE')
        self.assertEqual(assignment['assigned_by_name'], self.vo['name'])
        self.assertEqual(assignment['citizen_name'], self.citizen['name'])

    def test_dossier_of_an_officer_with_no_cases_is_empty_not_fabricated(self):
        record = self.record(self.pending['id'])
        self.assertEqual(record['cases'], [])
        self.assertEqual(record['assignments'], [])
        self.assertEqual(record['decisions'], [])
        self.assertEqual(record['stats']['total'], 0)
        self.assertEqual(record['performance']['total_credits'], 0)

    def test_dossier_exposes_no_credentials_or_identity_documents(self):
        self.decide('SUSPENDED', 'Enquiry opened.')
        payload = json.dumps(self.record(), default=str)
        for secret in ('password_hash', 'salt', PASSWORD, 'id_document_path', 'photo_path'):
            self.assertNotIn(secret, payload)


if __name__ == '__main__':
    unittest.main()
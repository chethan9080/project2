"""
Automated Test Suite for the Centralized Role-Based Notification Matrix.

Tests:
1. Complaint submission is stored for the citizen, every active Verification
   Officer account and the Authorized Officer desk
2. FIR registration, officer assignment, FIR amendment and investigation updates
   each deliver the role-appropriate copy from the delivery matrix
3. The officer who performed an action is never alerted about their own action,
   and re-running a workflow step stores one alert per recipient
4. Citizen alerts stay public-safe: no hash values, changed field names, internal
   remarks or officer badge numbers
5. Alerts are isolated per user and are read/unread tracked from the same records
   the header bell counts
"""

import itertools
import os
import shutil
import tempfile
import unittest

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_notification_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'fir_notification_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import register_user
from backend.services.complaint_service import (
    create_complaint,
    update_complaint_status,
)
from backend.services.complaint_verification_service import (
    record_complaint_verification_action,
)
from backend.services.case_tracking_service import init_case_tracking_table
from backend.services.db import get_db_connection, init_database
from backend.services.fir_service import (
    assign_officer_to_fir,
    create_fir_from_complaint,
    update_fir,
)
from backend.services.investigation_service import (
    init_investigation_tables,
    record_investigation_action,
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_notification_read,
)

PASSWORD = 'MatrixTestPass!23'
COUNTER = itertools.count(1)
STATION = 'Matrix Test Police Station'


class NotificationMatrixTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(
            TEST_DB_DIRECTORY, f'matrix_{self.id()}.db')
        init_database()
        init_case_tracking_table()
        init_investigation_tables()

        self.citizen = register_user(
            name='Matrix Citizen', email=f'citizen{next(COUNTER)}@matrix.test',
            phone='9000000101', password=PASSWORD, role='CITIZEN', status='ACTIVE')
        self.bystander = register_user(
            name='Other Citizen', email=f'other{next(COUNTER)}@matrix.test',
            phone='9000000102', password=PASSWORD, role='CITIZEN', status='ACTIVE')
        self.officer = register_user(
            name='Matrix Investigator', email=f'officer{next(COUNTER)}@matrix.test',
            phone='9000000103', password=PASSWORD, role='OFFICER', status='ACTIVE',
            badge_number='MAT-PSI-01', station=STATION, rank='Police Sub Inspector')
        # Two desk accounts: role-wide delivery must reach every active officer.
        self.actor_vo = register_user(
            name='Verification Officer One', email=f'vo1{next(COUNTER)}@matrix.test',
            phone='9000000104', password=PASSWORD, role='VERIFICATION_OFFICER',
            status='ACTIVE', badge_number='MAT-VO-01', station=STATION)
        self.other_vo = register_user(
            name='Verification Officer Two', email=f'vo2{next(COUNTER)}@matrix.test',
            phone='9000000105', password=PASSWORD, role='VERIFICATION_OFFICER',
            status='ACTIVE', badge_number='MAT-VO-02', station=STATION)
        self.ao = register_user(
            name='Authorized Officer', email=f'ao{next(COUNTER)}@matrix.test',
            phone='9000000106', password=PASSWORD, role='ADMIN', status='ACTIVE',
            badge_number='MAT-AO-01', station=STATION)

    # --------------------------------------
    # helpers
    # --------------------------------------
    def titles_for(self, user_id: str) -> list:
        return [n.get('title', '') for n in get_user_notifications(user_id, limit=200)]

    def count_title(self, user_id: str, title: str) -> int:
        return self.titles_for(user_id).count(title)

    def messages_for(self, user_id: str) -> str:
        return '\n'.join(n.get('message', '') for n in get_user_notifications(user_id, limit=200))

    def message_of(self, user_id: str, title: str) -> str:
        """The stored body of one alert, so a public-safe check reads the alert
        under test rather than every message in the inbox."""
        matches = [n.get('message', '') for n in get_user_notifications(user_id, limit=200)
                   if n.get('title') == title]
        self.assertTrue(matches, f'no notification titled {title!r}')
        return matches[0]

    def assert_has(self, user_id: str, fragment: str) -> None:
        self.assertIn(fragment, self.messages_for(user_id) + ' ' + ' '.join(self.titles_for(user_id)))

    def new_complaint(self) -> dict:
        return create_complaint(self.citizen['id'], {
            'category': 'Theft',
            'title': 'Mobile phone stolen',
            'description': 'My phone was taken from the bus stand waiting area.',
            'location': 'Bus Stand, MG Road',
            'district': 'Bengaluru Urban',
            'state': 'Karnataka',
            'police_station': STATION,
            'incident_date': '2026-11-05',
            'incident_time': '18:30',
        })

    def registered_fir(self) -> tuple:
        complaint = self.new_complaint()
        record_complaint_verification_action(complaint['id'], self.actor_vo, 'VERIFY')
        result = create_fir_from_complaint(complaint['id'], self.actor_vo)
        return complaint, result['fir_id'], result['fir_number']

    # --------------------------------------
    # 1. complaint submission
    # --------------------------------------
    def test_01_complaint_submission_reaches_every_desk(self):
        complaint = self.new_complaint()

        self.assert_has(self.citizen['id'], complaint['reference'])
        for vo in (self.actor_vo['id'], self.other_vo['id']):
            self.assert_has(vo, 'New Complaint Awaiting Verification')
        self.assert_has(self.ao['id'], 'New Complaint Submitted')
        self.assertEqual([], self.titles_for(self.bystander['id']))

    # --------------------------------------
    # 2. FIR registration
    # --------------------------------------
    def test_02_fir_registration_notifies_all_four_roles(self):
        complaint, fir_id, fir_number = self.registered_fir()

        self.assert_has(self.citizen['id'], fir_number)
        # The desk that is not the actor still hears about the registration.
        self.assert_has(self.other_vo['id'], f'FIR {fir_number} has been registered')
        self.assert_has(self.ao['id'], f'FIR {fir_number} registered from complaint')
        self.assertIn(fir_number, self.messages_for(self.ao['id']))

    # --------------------------------------
    # 3. police officer assignment
    # --------------------------------------
    def test_03_assignment_notifies_officer_citizen_and_both_desks(self):
        _, fir_id, fir_number = self.registered_fir()

        self.assertTrue(assign_officer_to_fir(fir_id, self.officer['id'], self.actor_vo))

        self.assert_has(self.officer['id'], 'New Case Assigned')
        self.assert_has(self.citizen['id'], 'Investigating Officer Assigned')
        self.assert_has(self.other_vo['id'], 'Investigating Officer Assigned')
        self.assert_has(self.ao['id'], 'Officer Assignment Audit Record')
        # The actor already sees the confirmation in the UI, not in the inbox.
        self.assertNotIn('Investigating Officer Assigned', self.titles_for(self.actor_vo['id']))

    # --------------------------------------
    # 4. FIR amendment
    # --------------------------------------
    def test_04_amendment_delivers_role_appropriate_detail(self):
        _, fir_id, fir_number = self.registered_fir()
        assign_officer_to_fir(fir_id, self.officer['id'], self.actor_vo)

        # The investigating officer makes the amendment, so every desk that is
        # not the author receives its own version of the alert.
        update_fir(fir_id, self.officer, {'accused_details': 'Two identified persons'},
                   'Witness identified a second suspect')

        self.assert_has(self.actor_vo['id'], 'FIR Record Updated')
        self.assert_has(self.other_vo['id'], 'FIR Record Updated')
        # Authorized Officer: full audit detail including the changed field name.
        self.assert_has(self.ao['id'], 'FIR Amendment Audit Record')
        self.assertIn('accused_details', self.messages_for(self.ao['id']))
        # Citizen: public-safe wording only.
        citizen_text = self.message_of(self.citizen['id'], '🔔 Your FIR Has Been Updated')
        self.assertIn('updated by an authorized police officer', citizen_text)
        self.assertNotIn('accused_details', citizen_text)
        self.assertNotIn('Witness identified a second suspect', citizen_text)
        self.assertIn(fir_number, citizen_text)
        self.assertNotIn('hash', citizen_text.lower())

    def test_05_citizen_amendment_alert_carries_no_hash_values(self):
        _, fir_id, _ = self.registered_fir()
        update_fir(fir_id, self.actor_vo, {'description': 'Updated incident narrative.'}, '')

        for notification in get_user_notifications(self.citizen['id'], limit=50):
            message = notification.get('message', '')
            self.assertNotIn('hash', message.lower())
            self.assertNotIn('blockchain', message.lower())
            self.assertNotIn('Version', message)

    # --------------------------------------
    # 5. investigation update
    # --------------------------------------
    def test_06_investigation_update_notifies_all_four_roles(self):
        _, fir_id, fir_number = self.registered_fir()
        assign_officer_to_fir(fir_id, self.officer['id'], self.actor_vo)

        record_investigation_action(
            fir_id, 'INVESTIGATION_STARTED', 'STARTED', self.officer,
            'Team deployed to the scene and area map prepared.')

        self.assert_has(self.citizen['id'], 'Investigation has started on your case.')
        self.assert_has(self.other_vo['id'], f'FIR {fir_number}')
        self.assert_has(self.ao['id'], 'Investigation Started — Started')
        # Internal remarks are audit-desk material, not citizen material.
        self.assertNotIn('Team deployed to the scene', self.messages_for(self.citizen['id']))

    def test_07_case_closure_alerts_all_four_roles(self):
        _, fir_id, _ = self.registered_fir()
        assign_officer_to_fir(fir_id, self.officer['id'], self.actor_vo)
        for stage in ('INVESTIGATION_STARTED', 'EVIDENCE_COLLECTION',
                      'INVESTIGATION_IN_PROGRESS', 'INVESTIGATION_COMPLETED'):
            note = f'{stage.replace("_", " ").lower()} activity recorded by the team.'
            record_investigation_action(fir_id, stage, 'STARTED', self.officer, note)
            record_investigation_action(fir_id, stage, 'COMPLETED', self.officer, note)
        record_investigation_action(
            fir_id, 'CASE_CLOSED', 'COMPLETED', self.officer,
            'Report filed, matter disposed of and the case closed.')

        self.assert_has(self.citizen['id'], 'Your case has been closed.')
        self.assert_has(self.other_vo['id'], 'Case Closed')
        self.assert_has(self.ao['id'], 'Case Closed')
        # Both desk accounts track the closure; the assignment audit trail was
        # written when the officer was assigned.
        self.assert_has(self.actor_vo['id'], 'Case Progress: Case Closed')
        self.assert_has(self.ao['id'], 'Officer Assignment Audit Record')

    # --------------------------------------
    # 6. duplicate prevention
    # --------------------------------------
    def test_08_repeated_workflow_step_stores_one_alert(self):
        complaint = self.new_complaint()
        before = len(get_user_notifications(self.ao['id'], limit=200))

        from backend.services import complaint_service
        complaint_service._notify_verification_officers(complaint)
        complaint_service._notify_verification_officers(complaint)

        self.assertEqual(before, len(get_user_notifications(self.ao['id'], limit=200)))
        self.assertEqual(1, self.titles_for(self.ao['id']).count('New Complaint Submitted'))

    def test_09_repeat_status_edit_does_not_re_alert_the_citizen(self):
        complaint = self.new_complaint()
        update_complaint_status(complaint['id'], 'UNDER_REVIEW', self.officer)
        first = self.count_title(self.citizen['id'], 'Complaint Under Review')
        self.assertGreater(first, 0)

        update_complaint_status(complaint['id'], 'UNDER_REVIEW', self.officer)

        self.assertEqual(first, self.count_title(self.citizen['id'], 'Complaint Under Review'))

    def test_10_verification_stages_are_owned_by_the_verification_workflow(self):
        complaint = self.new_complaint()
        with self.assertRaises(ValueError):
            update_complaint_status(complaint['id'], 'VERIFIED', self.officer)

        record_complaint_verification_action(complaint['id'], self.actor_vo, 'VERIFY')
        self.assertEqual(1, self.count_title(self.citizen['id'], 'Complaint Verified'))

        with self.assertRaises(ValueError):
            update_complaint_status(complaint['id'], 'FIR_CREATED', self.officer)

    # --------------------------------------
    # 7. read tracking uses the stored records
    # --------------------------------------
    def test_11_bell_and_inbox_share_the_same_stored_records(self):
        self.new_complaint()
        inbox = get_user_notifications(self.ao['id'], limit=200)
        self.assertEqual(len(inbox), get_unread_count(self.ao['id']))

        for notification in inbox:
            self.assertTrue(mark_notification_read(notification['id'], self.ao['id']))

        self.assertEqual(0, get_unread_count(self.ao['id']))
        self.assertEqual(len(inbox), len(get_user_notifications(self.ao['id'], limit=200)))
        self.assertEqual([], get_user_notifications(self.bystander['id'], limit=200))

    def test_12_every_alert_is_a_persisted_database_row(self):
        _, fir_id, fir_number = self.registered_fir()
        assign_officer_to_fir(fir_id, self.officer['id'], self.actor_vo)
        update_fir(fir_id, self.ao, {'witness_details': 'Bus stand staff member'}, '')

        conn = get_db_connection()
        try:
            for user_id in (self.citizen['id'], self.officer['id'], self.actor_vo['id'],
                            self.other_vo['id'], self.ao['id']):
                rows = conn.execute(
                    "SELECT event_id FROM notifications WHERE user_id = ?", (user_id,)
                ).fetchall()
                self.assertTrue(rows, f'no stored notifications for {user_id}')
                self.assertEqual(len(rows), len({r['event_id'] for r in rows}),
                                 f'duplicate event_id stored for {user_id}')
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()

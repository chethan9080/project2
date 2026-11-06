"""
Automated Test Suite for Pre-Registration FIR Detail Review and Draft Documents.

Tests:
1. Only Verification Officers and Administrators may edit the FIR details a
   complaint will become, and only while no FIR has been registered
2. Every saved correction is written to the complaint record, attributed to the
   acting officer and appended to the verification history
3. FIR registration inherits the stored corrections instead of the defaults
4. Re-saving identical values changes nothing and records no new history row
5. Each recorded edit alerts the Authorized Officer desk once, and never the
   citizen or the acting officer
6. The draft FIR document renders from the saved record without creating an
   official document or requiring a registered FIR
"""

import itertools
import os
import shutil
import tempfile
import unittest

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_fir_draft_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'fir_draft_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import register_user
from backend.services.complaint_service import create_complaint
from backend.services.complaint_verification_service import (
    get_complaint_for_verification,
    get_complaint_verification_events,
    record_complaint_verification_action,
    update_fir_details_before_registration,
)
from backend.services.case_tracking_service import init_case_tracking_table
from backend.services.db import get_db_connection, init_database
from backend.services.fir_document_service import render_draft_document_for_complaint
from backend.services.fir_service import create_fir_from_complaint, get_fir_by_id
from backend.services.investigation_service import init_investigation_tables
from backend.services.notification_service import get_user_notifications

PASSWORD = 'DraftTestPass!23'
COUNTER = itertools.count(1)
STATION = 'Draft Test Police Station'


class FirDraftReviewTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(
            TEST_DB_DIRECTORY, f'draft_{self.id()}.db')
        init_database()
        init_case_tracking_table()
        init_investigation_tables()

        self.citizen = register_user(
            name='Draft Citizen', email=f'citizen{next(COUNTER)}@draft.test',
            phone='9000000201', password=PASSWORD, role='CITIZEN', status='ACTIVE')
        self.officer = register_user(
            name='Draft Investigator', email=f'officer{next(COUNTER)}@draft.test',
            phone='9000000202', password=PASSWORD, role='OFFICER', status='ACTIVE',
            badge_number='DFT-PSI-01', station=STATION, rank='Police Sub Inspector')
        self.actor_vo = register_user(
            name='Draft Verification Officer', email=f'vo{next(COUNTER)}@draft.test',
            phone='9000000203', password=PASSWORD, role='VERIFICATION_OFFICER',
            status='ACTIVE', badge_number='DFT-VO-01', station=STATION)
        self.ao = register_user(
            name='Draft Authorized Officer', email=f'ao{next(COUNTER)}@draft.test',
            phone='9000000204', password=PASSWORD, role='ADMIN', status='ACTIVE',
            badge_number='DFT-AO-01', station=STATION)

        self.complaint = create_complaint(self.citizen['id'], {
            'category': 'Theft',
            'title': 'Laptop stolen from office',
            'description': 'A laptop was taken from the cabin between 6pm and 8pm.',
            'location': 'MG Road Office Complex',
            'district': 'Bengaluru Urban',
            'state': 'Karnataka',
            'police_station': 'Central Police Station',
            'incident_date': '2026-10-11',
            'incident_time': '19:00',
        })

    # --------------------------------------
    # helpers
    # --------------------------------------
    def titles_for(self, user_id: str) -> list:
        return [n.get('title', '') for n in get_user_notifications(user_id, limit=200)]

    def messages_for_text(self, user_id: str) -> str:
        return '\n'.join(n.get('message', '') for n in get_user_notifications(user_id, limit=200))

    def edit_events(self) -> list:
        events = get_complaint_verification_events(self.complaint['id'])
        return [e for e in events if e.get('action') == 'FIR_DETAILS_EDITED']

    def corrections(self, **overrides) -> dict:
        fields = {
            'category': 'Fraud',
            'description': 'Fraudulent transfers were made from the same account.',
            'location': 'Indiranagar 100 Feet Road',
            'police_station': 'Indiranagar Police Station',
            'accused_details': 'A known account holder named R. Kumar (mobile 98••••••21).',
            'witness_details': 'Two colleagues witnessed the login alerts.',
        }
        fields.update(overrides)
        return fields

    # --------------------------------------
    # 1. role and state guards
    # --------------------------------------
    def test_01_only_review_roles_may_edit_before_registration(self):
        for actor in (self.citizen, self.officer):
            with self.subTest(role=actor['role']):
                with self.assertRaises(PermissionError):
                    update_fir_details_before_registration(
                        self.complaint['id'], self.corrections(), actor)

    def test_02_registered_complaint_is_edited_as_an_fir_instead(self):
        record_complaint_verification_action(
            self.complaint['id'], self.actor_vo, 'VERIFY', 'Details confirmed.')
        create_fir_from_complaint(self.complaint['id'], self.actor_vo)

        with self.assertRaises(ValueError) as caught:
            update_fir_details_before_registration(
                self.complaint['id'], self.corrections(), self.actor_vo)
        self.assertIn('registered', str(caught.exception))

    # --------------------------------------
    # 2. persistence and attribution
    # --------------------------------------
    def test_03_saved_corrections_are_written_to_the_record(self):
        updated = update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        self.assertEqual(updated['category'], 'Fraud')
        self.assertEqual(updated['location'], 'Indiranagar 100 Feet Road')
        self.assertEqual(updated['police_station'], 'Indiranagar Police Station')
        self.assertEqual(
            updated['accused_details'],
            'A known account holder named R. Kumar (mobile 98••••••21).')
        self.assertEqual(updated['fir_edited_by'], self.actor_vo['id'])
        self.assertEqual(updated['fir_edited_by_name'], self.actor_vo['name'])
        self.assertTrue(updated['fir_edited_at'])

        stored = get_complaint_for_verification(self.complaint['id'])
        self.assertEqual(stored['description'], 'Fraudulent transfers were made from the same account.')

    def test_04_edit_is_appended_to_the_verification_history(self):
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        events = self.edit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['actor_id'], self.actor_vo['id'])
        self.assertEqual(events[0]['actor_role'], 'VERIFICATION_OFFICER')
        self.assertIn('Offence category', events[0]['remarks'])
        self.assertIn('Accused / suspect details', events[0]['remarks'])

    def test_05_required_fields_cannot_be_cleared(self):
        for column in ('category', 'description', 'location'):
            with self.subTest(column=column):
                with self.assertRaises(ValueError):
                    update_fir_details_before_registration(
                        self.complaint['id'], {column: '   '}, self.actor_vo)
        unchanged = get_complaint_for_verification(self.complaint['id'])
        self.assertEqual(unchanged['category'], 'Theft')
        self.assertIsNone(unchanged['fir_edited_at'])

    def test_06_columns_outside_the_fir_details_are_ignored(self):
        before = get_complaint_for_verification(self.complaint['id'])
        update_fir_details_before_registration(
            self.complaint['id'],
            {'status': 'REJECTED', 'citizen_id': self.officer['id'], 'reference': 'CMP-HACKED'},
            self.actor_vo)

        after = get_complaint_for_verification(self.complaint['id'])
        self.assertEqual(after['status'], before['status'])
        self.assertEqual(after['citizen_id'], before['citizen_id'])
        self.assertEqual(after['reference'], before['reference'])
        self.assertEqual(self.edit_events(), [])

    def test_07_unchanged_save_records_no_new_history_row(self):
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)
        stored = get_complaint_for_verification(self.complaint['id'])
        before_update = stored['updated_at']

        again = update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        self.assertEqual(len(self.edit_events()), 1)
        self.assertEqual(again['updated_at'], before_update)

    # --------------------------------------
    # 3. registration inherits the reviewed record
    # --------------------------------------
    def test_08_registration_inherits_the_reviewed_details(self):
        record_complaint_verification_action(
            self.complaint['id'], self.actor_vo, 'VERIFY', 'Details confirmed.')
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        result = create_fir_from_complaint(self.complaint['id'], self.actor_vo)
        fir = get_fir_by_id(result['fir_id'])

        self.assertEqual(fir['incident_type'], 'Fraud')
        self.assertEqual(fir['incident_location'], 'Indiranagar 100 Feet Road')
        self.assertEqual(fir['police_station'], 'Indiranagar Police Station')
        self.assertEqual(
            fir['accused_details'],
            'A known account holder named R. Kumar (mobile 98••••••21).')
        self.assertEqual(fir['witness_details'], 'Two colleagues witnessed the login alerts.')

    def test_09_registration_keeps_defaults_without_officer_corrections(self):
        record_complaint_verification_action(
            self.complaint['id'], self.actor_vo, 'VERIFY', 'Details confirmed.')

        result = create_fir_from_complaint(self.complaint['id'], self.actor_vo)
        fir = get_fir_by_id(result['fir_id'])

        self.assertEqual(fir['accused_details'], 'Under Investigation')
        self.assertEqual(fir['witness_details'], 'None provided')

    # --------------------------------------
    # 4. notifications
    # --------------------------------------
    def test_10_edit_alerts_the_authorized_officer_once(self):
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        titles = self.titles_for(self.ao['id'])
        self.assertEqual(titles.count('FIR Details Edited Before Registration'), 1)
        self.assertIn('CMP', self.messages_for_text(self.ao['id']))
        # The acting officer is excluded and the citizen is not alerted about an
        # internal review correction made before the FIR exists.
        self.assertNotIn('FIR Details Edited Before Registration',
                         self.titles_for(self.actor_vo['id']))
        self.assertNotIn('FIR Details Edited Before Registration',
                         self.titles_for(self.citizen['id']))

    # --------------------------------------
    # 5. draft document review
    # --------------------------------------
    def test_11_draft_pdf_renders_from_the_saved_record(self):
        update_fir_details_before_registration(
            self.complaint['id'], self.corrections(), self.actor_vo)

        pdf_bytes, file_name = render_draft_document_for_complaint(
            self.complaint['id'], self.actor_vo)

        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
        self.assertEqual(file_name, f"DRAFT-{self.complaint['reference']}.pdf")
        self._assert_no_official_document_rows()

    def test_12_draft_pdf_is_not_an_official_document(self):
        render_draft_document_for_complaint(self.complaint['id'], self.actor_vo)
        render_draft_document_for_complaint(self.complaint['id'], self.ao)

        self._assert_no_official_document_rows()
        self.assertEqual(self.titles_for(self.citizen['id']).count('FIR Document Available'), 0)

    def test_13_draft_pdf_requires_a_review_role(self):
        for actor in (self.citizen, self.officer):
            with self.subTest(role=actor['role']):
                with self.assertRaises(PermissionError):
                    render_draft_document_for_complaint(self.complaint['id'], actor)

    def test_14_draft_preview_ends_once_the_fir_is_registered(self):
        record_complaint_verification_action(
            self.complaint['id'], self.actor_vo, 'VERIFY', 'Details confirmed.')
        create_fir_from_complaint(self.complaint['id'], self.actor_vo)

        with self.assertRaises(ValueError) as caught:
            render_draft_document_for_complaint(self.complaint['id'], self.actor_vo)
        self.assertIn('official FIR document', str(caught.exception))

    def _assert_no_official_document_rows(self) -> None:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS total FROM fir_documents")
        total = cursor.fetchone()['total']
        cursor.execute("SELECT COUNT(*) AS total FROM firs")
        fir_total = cursor.fetchone()['total']
        conn.close()
        self.assertEqual(total, 0)
        self.assertEqual(fir_total, 0)


if __name__ == '__main__':
    unittest.main()

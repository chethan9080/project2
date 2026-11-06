"""
Automated Test Suite for the Centralized Authorized Officer FIR Case Record.

Tests:
1. Only an Authorized Officer may read the complete case record
2. Citizen registration details, application date and the approving officer are
   taken from the stored registration application
3. The complaint reference stays distinct from the official FIR number
4. FIR registration is attributed to the Verification Officer who registered it
5. Every generated document version is listed with its SHA-256 digest
6. Police officer amendments carry the previous value, the updated value, the
   officer identity, the timestamp and the optional reason
7. Verification Officer actions, including pre-registration corrections, are
   listed in the same audit section
8. Every recorded version exposes its SHA-256 hash and the chain links to the
   previous version
9. Real tampering of the stored FIR row is reported by the integrity check
10. Closure information is reported once the case is closed
"""

import itertools
import json
import os
import shutil
import tempfile
import unittest

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_case_record_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'case_record_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import register_user
from backend.services.case_tracking_service import init_case_tracking_table
from backend.services.citizen_credentials_service import issue_credentials
from backend.services.citizen_registration_service import (
    create_citizen_application,
    record_application_action,
)
from backend.services.complaint_service import assign_officer_to_complaint, create_complaint
from backend.services.complaint_verification_service import (
    record_complaint_verification_action,
    update_fir_details_before_registration,
)
from backend.services.db import get_db_connection, init_database
from backend.services.fir_document_service import generate_fir_pdf
from backend.services.fir_service import create_fir_from_complaint, get_fir_by_id, update_fir
from backend.services.investigation_service import (
    get_admin_case_detail,
    get_admin_case_record,
    init_investigation_tables,
    record_investigation_action,
)

PASSWORD = 'CaseRecordPass!23'
COUNTER = itertools.count(1)
STATION = 'Case Record Police Station'
PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
    b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05'
    b'\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


class AdminCaseRecordTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(
            TEST_DB_DIRECTORY, f'record_{self.id()}.db')
        init_database()
        init_case_tracking_table()
        init_investigation_tables()

        self.citizen = register_user(
            name='Record Citizen', email=f'citizen{next(COUNTER)}@record.test',
            phone='9000000301', password=PASSWORD, role='CITIZEN', status='ACTIVE')
        self.officer = register_user(
            name='Record Investigator', email=f'officer{next(COUNTER)}@record.test',
            phone='9000000302', password=PASSWORD, role='OFFICER', status='ACTIVE',
            badge_number='REC-PSI-01', station=STATION, rank='Police Sub Inspector')
        self.vo = register_user(
            name='Record Verification Officer', email=f'vo{next(COUNTER)}@record.test',
            phone='9000000303', password=PASSWORD, role='VERIFICATION_OFFICER',
            status='ACTIVE', badge_number='REC-VO-01', station=STATION)
        self.ao = register_user(
            name='Record Authorized Officer', email=f'ao{next(COUNTER)}@record.test',
            phone='9000000304', password=PASSWORD, role='ADMIN', status='ACTIVE',
            badge_number='REC-AO-01', station=STATION)

        application = create_citizen_application(
            citizen_id=self.citizen['id'], full_name='Record Citizen',
            date_of_birth='1994-04-02', gender='Female', mobile='9000000301',
            email=self.citizen['email'], address='12 Record Street, Ward 4',
            state='Karnataka', district='Bengaluru Urban',
            username=self.citizen['email'], gov_id_type='Aadhaar Card',
            gov_id_masked='XXXX-XXXX-4455', photo_bytes=PNG, photo_ext='.png',
            document_bytes=PNG, document_ext='.png', document_name='aadhaar.png')
        self.application = record_application_action(
            application['id'], self.vo, 'APPROVE', 'Identity documents match.')
        self.credentials = issue_credentials(self.application, self.vo, deliver=False)
        conn = get_db_connection()
        self.username = conn.execute(
            "SELECT username FROM users WHERE id = ?", (self.citizen['id'],)
        ).fetchone()[0]
        conn.close()

        self.complaint = create_complaint(self.citizen['id'], {
            'category': 'Theft',
            'title': 'Shop break-in at Record Street',
            'description': 'The shutter was broken overnight and stock was taken.',
            'location': '12 Record Street, Ward 4',
            'district': 'Bengaluru Urban',
            'state': 'Karnataka',
            'police_station': STATION,
            'incident_date': '2026-10-21',
            'incident_time': '02:30',
        })
        self.corrected_description = (
            'The rear shutter was broken overnight; two cartons of stock were taken.')
        update_fir_details_before_registration(self.complaint['id'], {
            'description': self.corrected_description,
            'accused_details': 'Unknown person seen on the street camera.',
        }, self.vo)
        record_complaint_verification_action(self.complaint['id'], self.vo, 'VERIFY',
                                             'Complaint verified for registration.')
        assign_officer_to_complaint(self.complaint['id'], self.officer['id'], self.vo)
        created = create_fir_from_complaint(self.complaint['id'], self.vo)
        self.fir_id = created['fir_id']
        self.fir = get_fir_by_id(self.fir_id)

    # --------------------------------------
    # helpers
    # --------------------------------------
    def record(self):
        return get_admin_case_record(self.fir_id, self.ao)

    def officer_edit(self, reason: str = ''):
        return update_fir(self.fir_id, self.officer, {
            'description': 'Additional loss of a cash box was confirmed by the owner.',
            'incident_location': '12 Record Street, Ward 4 (rear entrance)',
        }, reason)

    def close_case(self):
        for stage in ('INVESTIGATION_STARTED', 'EVIDENCE_COLLECTION',
                      'INVESTIGATION_IN_PROGRESS', 'INVESTIGATION_COMPLETED', 'CASE_CLOSED'):
            description = (
                'Case closed after the charge sheet was accepted by the court.'
                if stage == 'CASE_CLOSED' else
                f'{stage.replace("_", " ").title()} opened for this case.')
            record_investigation_action(
                self.fir_id, stage, 'STARTED', self.officer, description)
            if stage == 'CASE_CLOSED':
                # Closing completes the stage in the same action.
                continue
            record_investigation_action(
                self.fir_id, stage, 'COMPLETED', self.officer,
                f'{stage.replace("_", " ").title()} completed with recorded findings.',
                public_note='Investigation is progressing as recorded.')

    # --------------------------------------
    # access control
    # --------------------------------------
    def test_only_authorized_officers_may_read_the_record(self):
        for actor in (None, self.citizen, self.officer, self.vo):
            with self.assertRaises(PermissionError) as caught:
                get_admin_case_record(self.fir_id, actor)
            self.assertIn('Authorized Officer', str(caught.exception))

    def test_unknown_fir_is_rejected(self):
        with self.assertRaises(ValueError):
            get_admin_case_record('fir-does-not-exist', self.ao)

    # --------------------------------------
    # items 1-6: origin and registration
    # --------------------------------------
    def test_citizen_registration_username_and_identity_approval(self):
        record = self.record()
        citizen = record['citizen']
        application = record['application']
        self.assertEqual(citizen['username'], self.username)
        self.assertEqual(citizen['name'], 'Record Citizen')
        self.assertTrue(citizen['created_at'])
        self.assertEqual(application['reference'], self.application['reference'])
        self.assertTrue(application['submitted_at'])
        self.assertEqual(application['reviewed_by_name'], self.vo['name'])
        self.assertTrue(application['reviewed_at'])
        self.assertEqual(application['status'], 'APPROVED')
        self.assertEqual(application['gov_id_masked'], 'XXXX-XXXX-4455')
        self.assertEqual(record['counts']['complaints'], 1)
        self.assertEqual(record['counts']['firs'], 1)

    def test_complaint_reference_is_not_the_fir_number(self):
        record = self.record()
        complaint = record['complaint']
        self.assertEqual(complaint['reference'], self.complaint['reference'])
        self.assertNotEqual(complaint['reference'], self.fir['fir_number'])
        self.assertEqual(record['case']['fir_number'], self.fir['fir_number'])
        self.assertTrue(complaint['submitted_at'])
        self.assertEqual(complaint['description'], self.corrected_description)
        self.assertEqual(complaint['verified_by_name'], self.vo['name'])
        self.assertEqual(complaint['fir_edited_by_name'], self.vo['name'])
        self.assertTrue(complaint['fir_edited_at'])

    def test_registration_names_the_registering_verification_officer(self):
        registration = self.record()['registration']
        self.assertEqual(registration['officer_name'], self.vo['name'])
        self.assertEqual(registration['officer_role'], 'VERIFICATION_OFFICER')
        self.assertEqual(registration['officer_badge'], 'REC-VO-01')
        self.assertEqual(registration['created_at'], self.fir['created_at'])

    # --------------------------------------
    # item 7: documents
    # --------------------------------------
    def test_every_generated_document_version_is_listed(self):
        first = generate_fir_pdf(self.fir_id, self.vo)
        self.officer_edit()
        second = generate_fir_pdf(self.fir_id, self.vo, force=True)
        documents = self.record()['documents']
        self.assertEqual(len(documents), 2)
        self.assertEqual({d['version'] for d in documents}, {1, 2})
        self.assertTrue(all(len(d['sha256']) == 64 for d in documents))
        current = [d for d in documents if d['is_current']]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]['version'], second['document']['version'])
        self.assertEqual(current[0]['sha256'], second['document']['sha256'])
        self.assertTrue(first['document']['file_name'].endswith('.pdf'))
        self.assertEqual(documents[0]['generated_by_name'], self.vo['name'])

    # --------------------------------------
    # items 10-11: modifications
    # --------------------------------------
    def test_officer_amendment_shows_previous_and_updated_values(self):
        original = self.record()['case']['incident_location']
        self.officer_edit('Owner produced the purchase bill.')
        changes = self.record()['officer_changes']
        self.assertEqual(len(changes), 1)
        event = changes[0]
        self.assertEqual(event['actor_name'], self.officer['name'])
        self.assertEqual(event['actor_badge'], 'REC-PSI-01')
        self.assertEqual(event['reason'], 'Owner produced the purchase bill.')
        self.assertTrue(event['timestamp'])
        self.assertEqual((event['previous_version'], event['new_version']), (1, 2))
        diffs = {d['field']: d for d in event['diffs']}
        self.assertEqual(diffs['incident_location']['label'], 'Place of occurrence')
        self.assertEqual(diffs['incident_location']['old'], original)
        self.assertEqual(diffs['incident_location']['new'],
                         '12 Record Street, Ward 4 (rear entrance)')
        self.assertEqual(diffs['description']['label'], 'Complaint description')
        self.assertIn('cash box', diffs['description']['new'])

    def test_officer_amendment_without_a_reason_is_still_recorded(self):
        self.officer_edit()
        changes = self.record()['officer_changes']
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]['reason'], '')
        self.assertEqual(len(changes[0]['diffs']), 2)

    def test_police_role_edits_are_not_misfiled_as_verification_changes(self):
        self.officer_edit()
        record = self.record()
        self.assertEqual(record['verification_changes'], [])
        self.assertEqual(len(record['officer_changes']), 1)

    def test_verification_officer_actions_including_pre_registration_edits(self):
        events = self.record()['verification_events']
        actions = [e['action'] for e in events]
        self.assertIn('FIR_DETAILS_EDITED', actions)
        self.assertIn('VERIFIED', actions)
        edit = next(e for e in events if e['action'] == 'FIR_DETAILS_EDITED')
        self.assertEqual(edit['actor_name'], self.vo['name'])
        self.assertIn('Complaint description', edit['remarks'])
        self.assertIn('Accused / suspect details', edit['remarks'])
        self.assertTrue(edit['created_at'])

    # --------------------------------------
    # items 12-14: versions and hashes
    # --------------------------------------
    def test_each_version_carries_its_hash_and_chains_to_the_previous(self):
        self.officer_edit()
        versions = self.record()['versions']
        self.assertEqual([v['version_number'] for v in versions], [1, 2])
        self.assertIsNone(versions[0]['previous_hash'])
        self.assertEqual(versions[1]['previous_hash'], versions[0]['current_hash'])
        for version in versions:
            self.assertRegex(version['current_hash'], r'^[0-9a-f]{64}$')
            self.assertTrue(version['created_at'])
            self.assertTrue(version['creator_name'])
            self.assertTrue(version['creator_role'])
        self.assertEqual(versions[0]['creator_name'], self.vo['name'])
        self.assertEqual(versions[1]['creator_name'], self.officer['name'])
        self.assertEqual(versions[1]['creator_badge'], 'REC-PSI-01')

    def test_integrity_status_is_verified_for_an_untouched_case(self):
        self.officer_edit()
        chain = self.record()['chain']
        self.assertTrue(chain['chain_valid'])
        self.assertEqual(chain['status'], 'VERIFIED')
        self.assertEqual(chain['total_versions'], 2)
        self.assertEqual(chain['issues'], [])

    def test_integrity_status_reports_real_tampering(self):
        self.officer_edit()
        conn = get_db_connection()
        conn.execute("UPDATE firs SET description = ? WHERE id = ?",
                     ('Tampered outside the application.', self.fir_id))
        conn.commit()
        conn.close()
        chain = self.record()['chain']
        self.assertFalse(chain['chain_valid'])
        self.assertEqual(chain['status'], 'INTEGRITY_ISSUE')
        self.assertTrue(any(i['type'] == 'DATA_MISMATCH' for i in chain['issues']))

    # --------------------------------------
    # item 15: closure
    # --------------------------------------
    def test_open_case_reports_no_closure(self):
        record = self.record()
        self.assertFalse(record['is_closed'])
        self.assertEqual(record['closure'], {})

    def test_closed_case_reports_closure_officer_and_timestamp(self):
        self.close_case()
        record = self.record()
        self.assertTrue(record['is_closed'])
        closure = record['closure']
        self.assertEqual(closure['new_stage'], 'CASE_CLOSED')
        self.assertEqual(closure['updated_by_officer_name'], self.officer['name'])
        self.assertEqual(closure['updated_by_officer_badge'], 'REC-PSI-01')
        self.assertTrue(closure['timestamp'])
        self.assertIn('closed', closure['remarks'].lower())

    # --------------------------------------
    # integration and privacy
    # --------------------------------------
    def test_case_detail_carries_the_record_for_the_monitor(self):
        detail = get_admin_case_detail(self.fir_id, self.ao)
        self.assertIn('record', detail)
        self.assertEqual(detail['record']['case']['fir_number'], self.fir['fir_number'])
        self.assertEqual(detail['record']['citizen']['username'], self.username)

    def test_record_never_exposes_credentials_or_identity_documents(self):
        record = self.record()
        self.assertNotIn('password_hash', record['citizen'])
        self.assertNotIn('salt', record['citizen'])
        self.assertNotIn('id_document_path', record['application'])
        self.assertNotIn('photo_path', record['application'])
        payload = json.dumps(record)
        self.assertNotIn(PASSWORD, payload)
        self.assertNotIn('id_document.png', payload)
        self.assertNotIn('aadhaar.png', payload)


if __name__ == '__main__':
    unittest.main()
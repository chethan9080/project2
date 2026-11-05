"""
Automated Test Suite for Police Officer Account Provisioning.
Tests:
1. SEED_OFFICER_USERNAMES creates one ACTIVE OFFICER row per username in users
2. Passwords are stored with the existing PBKDF2-HMAC-SHA256 hash, never plaintext
3. Re-running the seed never duplicates an account
4. An already-provisioned officer is never overwritten
5. Without SEED_OFFICER_PASSWORD nothing is created (no fallback password)
6. Usernames are trimmed, lower-cased and de-duplicated
7. Login resolves the officer by username or email and refuses other roles
8. Officer identity (id, name, badge, role) is recorded in the session audit trail
9. Existing admin and citizen accounts keep working after provisioning
"""

import os
import shutil
import sqlite3
import tempfile
import unittest

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_staff_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'fir_staff_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import authenticate_user, register_user
from backend.services.crypto_service import verify_password
from backend.services.db import get_db_connection, init_database
from backend.services.staff_accounts import ensure_seed_officer_accounts
from backend.services.verification_service import create_officer_session

SEED_USERNAMES = 'person1,person2,person3'
SEED_PASSWORD = 'person@1'
SEED_KEYS = ('SEED_OFFICER_USERNAMES', 'SEED_OFFICER_PASSWORD', 'SEED_OFFICER_EMAIL_DOMAIN')


class StaffAccountSeedTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, f'staff_{self.id()}.db')
        init_database()
        os.environ['SEED_OFFICER_USERNAMES'] = SEED_USERNAMES
        os.environ['SEED_OFFICER_PASSWORD'] = SEED_PASSWORD
        os.environ.pop('SEED_OFFICER_EMAIL_DOMAIN', None)

    def tearDown(self):
        for key in SEED_KEYS:
            os.environ.pop(key, None)

    # ── helpers ────────────────────────────────────────────────────────────
    def _users(self, role=None):
        conn = get_db_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            if role:
                cursor.execute('SELECT * FROM users WHERE role = ? ORDER BY badge_number', (role,))
            else:
                cursor.execute('SELECT * FROM users ORDER BY role, badge_number')
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    # ── 1. provisioning ────────────────────────────────────────────────────
    def test_three_officer_accounts_are_created(self):
        outcome = ensure_seed_officer_accounts()
        self.assertEqual(outcome['created'], ['person1', 'person2', 'person3'])

        officers = self._users(role='OFFICER')
        self.assertEqual(len(officers), 3)
        self.assertEqual([o['badge_number'] for o in officers], ['person1', 'person2', 'person3'])
        self.assertEqual({o['role'] for o in officers}, {'OFFICER'})
        self.assertEqual({o['status'] for o in officers}, {'ACTIVE'})
        self.assertEqual(len({o['id'] for o in officers}), 3, 'each account needs a unique user id')
        self.assertEqual(len({o['email'] for o in officers}), 3)
        for officer in officers:
            self.assertTrue(officer['name'].startswith('Officer '), officer['name'])

    def test_custom_email_domain_is_used(self):
        os.environ['SEED_OFFICER_EMAIL_DOMAIN'] = 'police.example'
        ensure_seed_officer_accounts()
        officers = self._users(role='OFFICER')
        self.assertEqual([o['email'] for o in officers], [
            'person1@police.example', 'person2@police.example', 'person3@police.example'
        ])

    # ── 2. password storage ────────────────────────────────────────────────
    def test_passwords_are_hashed_and_salted(self):
        ensure_seed_officer_accounts()
        for officer in self._users(role='OFFICER'):
            self.assertNotEqual(officer['password_hash'], SEED_PASSWORD)
            self.assertNotIn(SEED_PASSWORD, officer['password_hash'])
            self.assertNotIn(SEED_PASSWORD, officer['salt'])
            self.assertEqual(len(officer['password_hash']), 64)
            self.assertEqual(len(officer['salt']), 64)
            self.assertTrue(verify_password(SEED_PASSWORD, officer['password_hash'], officer['salt']))
            self.assertFalse(verify_password('wrong', officer['password_hash'], officer['salt']))

        officers = self._users(role='OFFICER')
        self.assertEqual(len({o['salt'] for o in officers}), 3, 'each account gets its own salt')

    # ── 3. idempotency ─────────────────────────────────────────────────────
    def test_rerunning_the_seed_creates_no_duplicates(self):
        first = ensure_seed_officer_accounts()
        hashes_before = {o['badge_number']: o['password_hash'] for o in self._users(role='OFFICER')}

        second = ensure_seed_officer_accounts()
        third = ensure_seed_officer_accounts()

        self.assertEqual(first['created'], ['person1', 'person2', 'person3'])
        self.assertEqual(second['created'], [])
        self.assertEqual(sorted(second['existing']), ['person1', 'person2', 'person3'])
        self.assertEqual(third['created'], [])
        self.assertEqual(len(self._users(role='OFFICER')), 3)
        self.assertEqual(
            hashes_before,
            {o['badge_number']: o['password_hash'] for o in self._users(role='OFFICER')},
            'a repeated seed must not re-hash or replace an account'
        )

    def test_existing_officer_is_not_overwritten(self):
        register_user(
            name='Existing Investigator',
            email='person1@other.station',
            phone='9000000001',
            password='already-in-place',
            role='OFFICER',
            badge_number='person1',
        )
        outcome = ensure_seed_officer_accounts()

        officers = self._users(role='OFFICER')
        self.assertEqual(len(officers), 3, 'the pre-existing badge number is reused, not duplicated')
        self.assertIn('person1', outcome['existing'])
        original = [o for o in officers if o['badge_number'] == 'person1'][0]
        self.assertEqual(original['name'], 'Existing Investigator')
        self.assertTrue(verify_password('already-in-place', original['password_hash'], original['salt']))
        self.assertIsNone(authenticate_user('person1', SEED_PASSWORD, required_role='OFFICER'))

    def test_without_a_password_nothing_is_created(self):
        os.environ.pop('SEED_OFFICER_PASSWORD')
        outcome = ensure_seed_officer_accounts()
        self.assertEqual(outcome['created'], [])
        self.assertEqual(outcome['skipped'], ['person1', 'person2', 'person3'])
        self.assertEqual(self._users(role='OFFICER'), [])

    def test_without_usernames_nothing_happens(self):
        os.environ['SEED_OFFICER_USERNAMES'] = '  '
        outcome = ensure_seed_officer_accounts()
        self.assertEqual(outcome, {'created': [], 'existing': [], 'skipped': []})
        self.assertEqual(self._users(), [])

    def test_usernames_are_normalised_and_deduplicated(self):
        os.environ['SEED_OFFICER_USERNAMES'] = ' Person1 , person1 ,,PERSON1 , person2 '
        ensure_seed_officer_accounts()
        officers = self._users(role='OFFICER')
        self.assertEqual([o['badge_number'] for o in officers], ['person1', 'person2'])

    # ── 4. authentication ──────────────────────────────────────────────────
    def test_login_by_username_and_email(self):
        ensure_seed_officer_accounts()
        for username in ('person1', 'person2', 'person3'):
            user = authenticate_user(username, SEED_PASSWORD, required_role='OFFICER')
            self.assertIsNotNone(user, username)
            self.assertEqual(user['badge_number'], username)
            self.assertEqual(user['role'], 'OFFICER')
            self.assertNotIn('password_hash', user)
            self.assertNotIn('salt', user)
            self.assertIsNotNone(
                authenticate_user(f'{username}@eksp.gov.in', SEED_PASSWORD, required_role='OFFICER')
            )
            self.assertIsNotNone(authenticate_user(username.upper(), SEED_PASSWORD, required_role='OFFICER'))

    def test_wrong_password_is_refused(self):
        ensure_seed_officer_accounts()
        self.assertIsNone(authenticate_user('person1', 'person@2', required_role='OFFICER'))
        self.assertIsNone(authenticate_user('person1', '', required_role='OFFICER'))
        self.assertIsNone(authenticate_user('person4', SEED_PASSWORD, required_role='OFFICER'))

    def test_officers_cannot_sign_in_to_other_roles(self):
        ensure_seed_officer_accounts()
        self.assertIsNone(authenticate_user('person1', SEED_PASSWORD, required_role='ADMIN'))
        self.assertIsNone(authenticate_user('person1', SEED_PASSWORD, required_role='CITIZEN'))
        self.assertIsNone(authenticate_user('person1', SEED_PASSWORD, required_role='VERIFICATION_OFFICER'))

    def test_suspended_officer_cannot_sign_in(self):
        ensure_seed_officer_accounts()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'SUSPENDED' WHERE badge_number = 'person2'")
        conn.commit()
        conn.close()
        self.assertIsNone(authenticate_user('person2', SEED_PASSWORD, required_role='OFFICER'))
        self.assertIsNotNone(authenticate_user('person1', SEED_PASSWORD, required_role='OFFICER'))

    # ── 5. session / audit identity ────────────────────────────────────────
    def test_officer_session_and_audit_record_identity(self):
        ensure_seed_officer_accounts()
        officer = authenticate_user('person3', SEED_PASSWORD, required_role='OFFICER')
        session = create_officer_session(officer_user=officer, location_name='Central Station')

        conn = get_db_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM officer_sessions WHERE id = ?', (session['session_id'],))
            row = dict(cursor.fetchone())
            cursor.execute(
                'SELECT * FROM system_audit_logs WHERE resource_id = ?', (session['session_id'],)
            )
            audit = dict(cursor.fetchone())
        finally:
            conn.close()

        self.assertEqual(row['officer_id'], officer['id'])
        self.assertEqual(row['officer_name'], officer['name'])
        self.assertEqual(row['badge_number'], 'person3')
        self.assertEqual(row['role'], 'OFFICER')
        self.assertEqual(audit['user_id'], officer['id'])
        self.assertEqual(audit['user_email'], officer['email'])
        self.assertEqual(audit['action'], 'OFFICER_AUTHENTICATED_LOGIN')
        self.assertIn('person3', audit['details'])

    # ── 6. other roles keep working ────────────────────────────────────────
    def test_admin_and_citizen_logins_are_unaffected(self):
        admin = register_user(
            name='Site Admin', email='admin@eksp.gov.in', phone='admin@eksp.gov.in',
            password='admin-pass', role='ADMIN', badge_number='KA-ADM-01',
        )
        citizen = register_user(
            name='Approved Citizen', email='citizen@eksp.gov.in', phone='9876500001',
            password='citizen-pass', role='CITIZEN', status='ACTIVE',
        )

        ensure_seed_officer_accounts()

        signed_in_admin = authenticate_user('KA-ADM-01', 'admin-pass', required_role='ADMIN')
        self.assertIsNotNone(signed_in_admin)
        self.assertEqual(signed_in_admin['id'], admin['id'])
        self.assertIsNotNone(authenticate_user('citizen@eksp.gov.in', 'citizen-pass', required_role='CITIZEN'))

        roles = {user['id']: user['role'] for user in self._users()}
        self.assertEqual(roles[admin['id']], 'ADMIN')
        self.assertEqual(roles[citizen['id']], 'CITIZEN')


if __name__ == '__main__':
    unittest.main()

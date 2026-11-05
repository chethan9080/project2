"""
Automated Test Suite for Staff Portal Account Provisioning.
Tests:
1. One username can serve the Verification, Police and Main Authorized Officer portals
2. Each portal gets its own role, id, email, badge and salt
3. Passwords go through the existing PBKDF2-HMAC-SHA256 hash, never plaintext
4. Re-running the seed on every boot creates no duplicates and rewrites nothing
5. A username that already resolves for a role is left alone, even under an older
   email scheme, and a blocked email is reported instead of raising
6. Without SEED_OFFICER_PASSWORD nothing is created (no fallback password)
7. Logins are role-scoped: each portal reaches its own account and no other
8. An identifier matching several accounts is refused when no role is supplied
9. Existing citizen and administrator accounts keep working untouched
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
from backend.services.staff_accounts import ensure_seed_staff_accounts
from backend.services.verification_service import create_officer_session

# A fixture password only: these tests run against a throwaway database, so no
# real account credential ever appears here.
SEED_PASSWORD = 'staff-seed-fixture'
SHARED_USERNAME = 'Person 1'
SEED_ENV_KEYS = (
    'SEED_OFFICER_USERNAMES',
    'SEED_VERIFICATION_OFFICER_USERNAMES',
    'SEED_POLICE_OFFICER_USERNAMES',
    'SEED_MAIN_AUTHORIZED_OFFICER_USERNAMES',
    'SEED_OFFICER_PASSWORD',
    'SEED_OFFICER_EMAIL_DOMAIN',
)
PORTAL_ROLES = ('VERIFICATION_OFFICER', 'OFFICER', 'ADMIN')


class StaffPortalSeedTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, f'staff_{self.id()}.db')
        init_database()
        self.clear_env()
        os.environ['SEED_VERIFICATION_OFFICER_USERNAMES'] = SHARED_USERNAME
        os.environ['SEED_POLICE_OFFICER_USERNAMES'] = SHARED_USERNAME
        os.environ['SEED_MAIN_AUTHORIZED_OFFICER_USERNAMES'] = SHARED_USERNAME
        os.environ['SEED_OFFICER_PASSWORD'] = SEED_PASSWORD

    def tearDown(self):
        self.clear_env()

    def clear_env(self):
        for key in SEED_ENV_KEYS:
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

    def _snapshot(self):
        conn = get_db_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM users')
            return {row['id']: dict(row) for row in cursor.fetchall()}
        finally:
            conn.close()

    # ── 1. one username, three portals ─────────────────────────────────────
    def test_shared_username_provisions_one_account_per_portal(self):
        outcome = ensure_seed_staff_accounts()

        self.assertEqual(sorted(outcome['created']), sorted([
            f'VERIFICATION_OFFICER:{SHARED_USERNAME}',
            f'OFFICER:{SHARED_USERNAME}',
            f'ADMIN:{SHARED_USERNAME}',
        ]))
        staff = self._users()
        self.assertEqual(len(staff), 3)
        self.assertEqual({o['role'] for o in staff}, set(PORTAL_ROLES))
        self.assertEqual({o['status'] for o in staff}, {'ACTIVE'})
        self.assertEqual(len({o['id'] for o in staff}), 3, 'each account needs a unique user id')
        self.assertEqual(len({o['email'] for o in staff}), 3, 'emails must stay unique')
        self.assertEqual(len({o['badge_number'] for o in staff}), 3, 'badge numbers must stay unique')
        self.assertEqual({o['name'] for o in staff}, {SHARED_USERNAME})
        self.assertEqual(
            {o['rank'] for o in staff},
            {'Verification Officer', 'Police Officer', 'Main Authorized Officer'}
        )

    def test_three_portals_do_not_leak_into_a_fourth(self):
        ensure_seed_staff_accounts()
        officers = self._users(role='OFFICER')
        self.assertEqual(len(officers), 1)
        self.assertEqual(len(self._users(role='ADMIN')), 1)
        self.assertEqual(len(self._users(role='VERIFICATION_OFFICER')), 1)

    # ── 2. password storage ────────────────────────────────────────────────
    def test_passwords_are_hashed_with_individual_salts(self):
        ensure_seed_staff_accounts()
        staff = self._users()
        for account in staff:
            self.assertNotEqual(account['password_hash'], SEED_PASSWORD)
            self.assertNotIn(SEED_PASSWORD, account['password_hash'])
            self.assertNotIn(SEED_PASSWORD, account['salt'])
            self.assertEqual(len(account['password_hash']), 64)
            self.assertEqual(len(account['salt']), 64)
            self.assertTrue(verify_password(SEED_PASSWORD, account['password_hash'], account['salt']))
            self.assertFalse(verify_password('wrong', account['password_hash'], account['salt']))
        self.assertEqual(len({account['salt'] for account in staff}), 3, 'each account gets its own salt')

    # ── 3. idempotency ─────────────────────────────────────────────────────
    def test_rerunning_the_seed_creates_no_duplicates(self):
        first = ensure_seed_staff_accounts()
        before = self._snapshot()

        second = ensure_seed_staff_accounts()
        third = ensure_seed_staff_accounts()

        self.assertEqual(len(first['created']), 3)
        self.assertEqual(second['created'], [])
        self.assertEqual(sorted(second['existing']), sorted(first['created']))
        self.assertEqual(third['created'], [])
        self.assertEqual(len(self._users()), 3)
        self.assertEqual(before, self._snapshot(), 'a repeated seed must not rewrite any row')

    def test_account_from_an_older_email_scheme_is_not_duplicated(self):
        register_user(
            name='Officer Person1', email='person1@eksp.gov.in', phone='9000000001',
            password='already-in-place', role='OFFICER', badge_number='person-1-police',
        )
        os.environ['SEED_POLICE_OFFICER_USERNAMES'] = 'Officer Person1'

        outcome = ensure_seed_staff_accounts()

        self.assertIn("OFFICER:Officer Person1", outcome['existing'])
        self.assertEqual(len(self._users(role='OFFICER')), 1)
        self.assertEqual(len(self._users()), 3)

    def test_taken_email_is_skipped_instead_of_raising(self):
        register_user(
            name='Existing Citizen', email='person-1-police@eksp.gov.in', phone='9876500002',
            password='citizen-pass', role='CITIZEN', status='ACTIVE',
        )
        outcome = ensure_seed_staff_accounts()

        self.assertNotIn('OFFICER:Person 1', outcome['created'])
        self.assertIn('OFFICER:Person 1', outcome['existing'])
        self.assertEqual(len(self._users(role='OFFICER')), 0)
        self.assertEqual(len(self._users()), 3)

    def test_without_a_password_nothing_is_created(self):
        os.environ.pop('SEED_OFFICER_PASSWORD')
        outcome = ensure_seed_staff_accounts()
        self.assertEqual(outcome['created'], [])
        self.assertEqual(sorted(outcome['skipped']), sorted([
            'VERIFICATION_OFFICER:Person 1', 'OFFICER:Person 1', 'ADMIN:Person 1'
        ]))
        self.assertEqual(self._users(), [])

    def test_without_usernames_nothing_happens(self):
        for key in ('SEED_VERIFICATION_OFFICER_USERNAMES', 'SEED_POLICE_OFFICER_USERNAMES',
                    'SEED_MAIN_AUTHORIZED_OFFICER_USERNAMES'):
            os.environ[key] = '   '
        outcome = ensure_seed_staff_accounts()
        self.assertEqual(outcome, {'created': [], 'existing': [], 'skipped': []})
        self.assertEqual(self._users(), [])

    def test_legacy_police_officer_list_is_still_provisioned(self):
        self.clear_env()
        os.environ['SEED_OFFICER_USERNAMES'] = 'person2, Person 2 , person2'
        os.environ['SEED_OFFICER_PASSWORD'] = SEED_PASSWORD

        ensure_seed_staff_accounts()
        second_run = ensure_seed_staff_accounts()

        officers = self._users(role='OFFICER')
        self.assertEqual([o['name'] for o in officers], ['Person 2', 'person2'])
        self.assertEqual(second_run['created'], [])

    # ── 4. authentication ──────────────────────────────────────────────────
    def test_each_portal_authenticates_its_own_account(self):
        ensure_seed_staff_accounts()
        accounts = {account['role']: account for account in self._users()}

        for role in PORTAL_ROLES:
            signed_in = authenticate_user(SHARED_USERNAME, SEED_PASSWORD, required_role=role)
            self.assertIsNotNone(signed_in, role)
            self.assertEqual(signed_in['id'], accounts[role]['id'], role)
            self.assertEqual(signed_in['role'], role)
            self.assertNotIn('password_hash', signed_in)
            self.assertNotIn('salt', signed_in)
            # case-insensitive and space-tolerant, like every other staff login
            self.assertEqual(
                authenticate_user('  person 1 ', SEED_PASSWORD, required_role=role)['id'],
                accounts[role]['id']
            )

    def test_wrong_password_is_refused_on_every_portal(self):
        ensure_seed_staff_accounts()
        for role in PORTAL_ROLES:
            self.assertIsNone(authenticate_user(SHARED_USERNAME, 'wrong', required_role=role), role)
            self.assertIsNone(authenticate_user(SHARED_USERNAME, '', required_role=role), role)

    def test_no_portal_accepts_another_roles_account(self):
        ensure_seed_staff_accounts()
        accounts = {account['role']: account for account in self._users()}
        for role in PORTAL_ROLES:
            by_email = authenticate_user(accounts[role]['email'], SEED_PASSWORD,
                                         required_role=role)
            self.assertIsNotNone(by_email)
            for other in PORTAL_ROLES:
                if other == role:
                    continue
                self.assertIsNone(
                    authenticate_user(accounts[role]['email'], SEED_PASSWORD, required_role=other),
                    f"{role} account must not sign in as {other}"
                )

    def test_shared_username_without_a_role_is_refused(self):
        ensure_seed_staff_accounts()
        self.assertIsNone(authenticate_user(SHARED_USERNAME, SEED_PASSWORD))
        self.assertIsNone(authenticate_user(SHARED_USERNAME, SEED_PASSWORD, required_role='CITIZEN'))

    def test_badge_and_email_identifiers_stay_unambiguous(self):
        ensure_seed_staff_accounts()
        accounts = {account['role']: account for account in self._users()}
        for role, account in accounts.items():
            by_badge = authenticate_user(account['badge_number'], SEED_PASSWORD)
            self.assertIsNotNone(by_badge, f"{role} badge resolves on its own")
            self.assertEqual(by_badge['id'], account['id'])
            self.assertEqual(by_badge['role'], role)

    def test_suspended_account_cannot_sign_in(self):
        ensure_seed_staff_accounts()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'SUSPENDED' WHERE role = 'ADMIN'")
        conn.commit()
        conn.close()
        self.assertIsNone(authenticate_user(SHARED_USERNAME, SEED_PASSWORD, required_role='ADMIN'))
        self.assertIsNotNone(
            authenticate_user(SHARED_USERNAME, SEED_PASSWORD, required_role='OFFICER')
        )

    # ── 5. session / audit identity ────────────────────────────────────────
    def test_session_and_audit_record_the_portal_identity(self):
        ensure_seed_staff_accounts()
        accounts = {account['role']: account for account in self._users()}

        conn = get_db_connection()
        cursor = conn.cursor()
        for role in PORTAL_ROLES:
            officer = accounts[role]
            session = create_officer_session(officer_user=officer, location_name='State HQ')
            cursor.execute('SELECT * FROM officer_sessions WHERE id = ?', (session['session_id'],))
            row = dict(zip([c[0] for c in cursor.description], cursor.fetchone()))
            cursor.execute('SELECT * FROM system_audit_logs WHERE resource_id = ?',
                           (session['session_id'],))
            audit = dict(zip([c[0] for c in cursor.description], cursor.fetchone()))
            self.assertEqual(row['officer_id'], officer['id'])
            self.assertEqual(row['badge_number'], officer['badge_number'])
            self.assertEqual(row['role'], role)
            self.assertEqual(audit['user_id'], officer['id'])
            self.assertEqual(audit['user_email'], officer['email'])
            self.assertEqual(audit['role'], role)
            self.assertEqual(audit['action'], 'OFFICER_AUTHENTICATED_LOGIN')
        conn.close()

    # ── 6. other accounts keep working ─────────────────────────────────────
    def test_existing_citizen_and_admin_accounts_are_untouched(self):
        admin = register_user(
            name='Person 4', email='person 4', phone='Person 4',
            password='old-admin-pass', role='ADMIN',
        )
        citizen = register_user(
            name=SHARED_USERNAME, email='person1-citizen@example.test', phone='9876500003',
            password='citizen-pass', role='CITIZEN', status='ACTIVE',
        )
        before = self._snapshot()

        ensure_seed_staff_accounts()

        after = self._snapshot()
        for user_id in (admin['id'], citizen['id']):
            self.assertEqual(before[user_id], after[user_id], f'{user_id} must stay byte-identical')

        self.assertIsNotNone(
            authenticate_user('Person 4', 'old-admin-pass', required_role='ADMIN')
        )
        self.assertIsNotNone(
            authenticate_user(SHARED_USERNAME, 'citizen-pass', required_role='CITIZEN')
        )
        citizen_session = authenticate_user(SHARED_USERNAME, 'citizen-pass', required_role='CITIZEN')
        self.assertEqual(citizen_session['id'], citizen['id'])
        admin_session = authenticate_user('Person 4', 'old-admin-pass', required_role='ADMIN')
        self.assertEqual(admin_session['id'], admin['id'])
        self.assertEqual(len(self._users(role='ADMIN')), 2, 'seeded and pre-existing admins coexist')


if __name__ == '__main__':
    unittest.main()

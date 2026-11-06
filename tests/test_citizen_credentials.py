"""
Automated Test Suite for Citizen Credential Generation, Activation and Notification.

Tests:
1. Approval provisions exactly one login account per approved citizen and records
   the officer identity, decision and timestamp
2. Usernames are unique, readable, and never reuse the registered email or mobile
3. Only a PBKDF2-HMAC-SHA256 hash is stored; no plain-text password or live token
   appears in any table, notification or audit row
4. A generated username is a working login identifier and the citizen's own
   password replaces the registration one
5. Activation links are single-use, expiring, superseded by a newer link, hashed at
   rest and capped at a fixed number of attempts
6. Weak or mismatched passwords are refused without spending the link
7. Delivery reports exactly what the provider answered: SENT only on real
   acceptance, FAILED on an unreachable provider, NOT_CONFIGURED with no provider
8. Retrying credential delivery mints a fresh link and records another attempt
9. Repeating the approval cannot create a second set of credentials
10. Password reset works from username, email or mobile and never confirms whether
    an account exists
11. Citizens stay isolated: one citizen's credentials are reachable only by id
"""

import itertools
import os
import re
import shutil
import socket
import socketserver
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_credential_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'fir_credential_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services.auth_service import authenticate_user, register_user
from backend.services.crypto_service import verify_password
from backend.services.citizen_registration_service import (
    get_application_events,
    get_citizen_application,
    record_application_action,
)
from backend.services.citizen_credentials_service import (
    ACTIVATION,
    PASSWORD_RESET,
    SUBJECT,
    activation_summary,
    complete_activation,
    complete_password_reset,
    get_credentials,
    hash_token,
    issue_credentials,
    issue_self_service_link,
    mint_token,
    request_password_reset,
    resolve_token,
    retry_delivery,
)
from backend.services.db import get_db_connection, init_database

COUNTER = itertools.count(1)

# Fixture credentials only: every test runs against a throwaway database, so no
# real account credential ever appears here.
REGISTRATION_PASSWORD = 'registration-fixture-1'
ACTIVATION_PASSWORD = 'self-chosen-fixture-2'
RESET_PASSWORD = 'reset-chosen-fixture-3'
OFFICER_PASSWORD = 'officer-fixture-4'

PROVIDER_ENV_KEYS = (
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD',
    'SMTP_MAIL_FROM', 'SMTP_USE_TLS',
    'SMS_GATEWAY_URL', 'SMS_GATEWAY_API_KEY', 'SMS_GATEWAY_SENDER',
    'PUBLIC_BASE_URL', 'ACTIVATION_LINK_TTL_HOURS', 'ACTIVATION_MAX_ATTEMPTS',
)

LINK_PATTERN = re.compile(r'https://portal\.example\.test/(activate|reset-password)/([A-Za-z0-9_\-]+)')


# ═══════════════════════════════════════════════════════════════════════════
# A real, local SMTP server: SENT may only be reported by an actual provider
# answer, never by a stub that pretends to accept mail.
# ═══════════════════════════════════════════════════════════════════════════

class _SinkHandler(socketserver.StreamRequestHandler):

    def handle(self) -> None:
        self.wfile.write(b'220 sink.local ESMTP test sink\r\n')
        gathering = False
        collected: list = []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            if gathering:
                if line.rstrip(b'\r\n') == b'.':
                    gathering = False
                    self.server.messages.append(b''.join(collected).decode('utf-8', 'replace'))
                    collected = []
                    self.wfile.write(b'250 2.0.0 Message accepted for delivery\r\n')
                else:
                    collected.append(line)
                continue
            verb = line.strip().split(b' ', 1)[0].upper()
            if verb == b'QUIT':
                self.wfile.write(b'221 2.0.0 Closing connection\r\n')
                return
            if verb == b'DATA':
                gathering = True
                self.wfile.write(b'354 2.0.0 Start mail input\r\n')
                continue
            self.wfile.write(b'250 2.0.0 Ok\r\n')


class _SmtpSink:

    def __init__(self) -> None:
        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), _SinkHandler)
        self.server.daemon_threads = True
        self.server.allow_reuse_address = True
        self.server.messages = []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> '_SmtpSink':
        self.thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    @property
    def messages(self) -> list:
        return self.server.messages


def _closed_port() -> int:
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class CitizenCredentialTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, f'creds_{self.id()}.db')
        init_database()
        self.clear_provider_env()
        os.environ['PUBLIC_BASE_URL'] = 'https://portal.example.test'
        self.officer = register_user(
            name='Verification Officer V1', email=f'vo{next(COUNTER)}@eksp.gov.test',
            phone='9000000001', password=OFFICER_PASSWORD,
            role='VERIFICATION_OFFICER', status='ACTIVE', badge_number='VO-01',
        )

    def tearDown(self):
        self.clear_provider_env()

    def clear_provider_env(self):
        for key in PROVIDER_ENV_KEYS:
            os.environ.pop(key, None)

    # ── helpers ────────────────────────────────────────────────────────────
    def _rows(self, query: str, params: tuple = ()) -> list:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _user(self, user_id: str) -> dict:
        return self._rows('SELECT * FROM users WHERE id = ?', (user_id,))[0]

    def _citizen(self, full_name: str = 'Asha Menon') -> dict:
        """A registered citizen holding a pending application, as approval sees it."""
        suffix = next(COUNTER)
        email = f'citizen{suffix}@example.test'
        phone = f'98{suffix:08d}'
        user = register_user(
            name=full_name, email=email, phone=phone,
            password=REGISTRATION_PASSWORD, role='CITIZEN', status='PENDING_VERIFICATION',
        )
        application_id = f"capp-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO citizen_applications (
                id, reference, citizen_id, full_name, date_of_birth, gender, mobile, email,
                address, state, district, username, gov_id_type, gov_id_masked,
                status, submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, '1994-05-18', 'FEMALE', ?, ?, '1 Marina Road', 'Tamil Nadu',
                      'Chennai', ?, 'AADHAAR', 'XXXX-XXXX-1234', 'PENDING', ?, ?)
            """,
            (application_id, f'CVR-T{suffix:06d}', user['id'], full_name, phone, email,
             f'{full_name.split()[0].lower()}{suffix}', now, now),
        )
        conn.commit()
        conn.close()
        return {'user': user, 'application': get_citizen_application(application_id)}

    def _approve(self, case: dict) -> dict:
        return record_application_action(case['application']['id'], self.officer, 'APPROVE', '')

    def _use_provider(self, sink: _SmtpSink) -> None:
        os.environ['SMTP_HOST'] = '127.0.0.1'
        os.environ['SMTP_PORT'] = str(sink.port)
        os.environ['SMTP_USE_TLS'] = 'none'
        os.environ['SMTP_MAIL_FROM'] = 'no-reply@eksp.gov.test'

    def _stored_text(self) -> str:
        """Every citizen-visible string the server keeps, minus the hash columns."""
        tables = ('citizen_credentials', 'citizen_activation_tokens', 'notifications',
                  'citizen_application_alerts', 'citizen_application_events',
                  'system_audit_logs', 'citizen_applications')
        chunks = []
        for table in tables:
            for row in self._rows(f'SELECT * FROM {table}'):
                chunks.extend(str(value) for value in row.values() if value is not None)
        for row in self._rows('SELECT * FROM users'):
            chunks.extend(
                str(value) for key, value in row.items()
                if key not in ('password_hash', 'salt')
            )
        return '\n'.join(chunks)

    # ── 1. approval provisions the login account ───────────────────────────
    def test_approval_provisions_one_login_account_with_officer_identity(self):
        case = self._citizen()
        updated = self._approve(case)
        citizen_id = case['user']['id']

        credentials = get_credentials(citizen_id)
        self.assertIsNotNone(credentials)
        self.assertEqual(len(self._rows('SELECT * FROM citizen_credentials')), 1)
        self.assertEqual(credentials['citizen_id'], citizen_id)
        self.assertEqual(credentials['application_id'], case['application']['id'])
        self.assertEqual(credentials['reference'], case['application']['reference'])

        account = self._user(citizen_id)
        self.assertEqual(account['username'], credentials['username'])
        self.assertEqual(account['verification_status'], 'VERIFIED')
        self.assertEqual(account['status'], 'ACTIVE')
        self.assertIsNotNone(account['verified_at'])

        self.assertEqual(updated['status'], 'APPROVED')
        self.assertEqual(updated['reviewed_by'], self.officer['id'])
        self.assertEqual(updated['reviewed_by_name'], self.officer['name'])
        self.assertIsNotNone(updated['reviewed_at'])

        issued_by = self._rows(
            'SELECT * FROM citizen_application_events WHERE application_id = ? AND action = ?',
            (case['application']['id'], 'CREDENTIALS_ISSUED'),
        )
        self.assertEqual(len(issued_by), 1)
        self.assertEqual(issued_by[0]['actor_id'], self.officer['id'])
        self.assertEqual(issued_by[0]['actor_name'], self.officer['name'])
        self.assertIsNotNone(issued_by[0]['created_at'])

        audit = self._rows(
            "SELECT * FROM system_audit_logs WHERE action = 'CITIZEN_CREDENTIALS_ISSUED'"
        )
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]['user_id'], self.officer['id'])
        self.assertEqual(audit[0]['role'], 'VERIFICATION_OFFICER')

    def test_issuance_requires_a_reviewer_role(self):
        case = self._citizen()
        with self.assertRaises(PermissionError):
            issue_credentials(case['application'], {'role': 'OFFICER', 'id': 'not-an-officer'})
        self.assertIsNone(get_credentials(case['user']['id']))

    # ── 2. usernames ───────────────────────────────────────────────────────
    def test_same_name_citizens_get_different_usernames(self):
        first = self._citizen('Asha Menon')
        second = self._citizen('Asha Menon')
        issue_credentials(first['application'], self.officer, deliver=False)
        issue_credentials(second['application'], self.officer, deliver=False)

        a = get_credentials(first['user']['id'])['username']
        b = get_credentials(second['user']['id'])['username']
        self.assertNotEqual(a, b)
        self.assertTrue(a.startswith('asha-menon-'), a)
        self.assertEqual(len(self._rows('SELECT * FROM users WHERE username IS NOT NULL')), 2)

    def test_username_never_reuses_the_registered_contact_details(self):
        case = self._citizen('Asha Menon')
        approved = self._approve(case)
        username = approved['credentials']['username']
        self.assertNotIn(case['user']['email'].split('@')[0], username)
        self.assertNotIn(case['user']['phone'], username)
        self.assertRegex(username, r'^asha-menon-[0-9a-f]{6}$')

    # ── 3. password storage ────────────────────────────────────────────────
    def test_only_a_hashed_password_is_stored(self):
        case = self._citizen()
        self._approve(case)
        account = self._user(case['user']['id'])

        self.assertNotEqual(account['password_hash'], REGISTRATION_PASSWORD)
        self.assertNotIn(REGISTRATION_PASSWORD, account['password_hash'])
        self.assertNotIn(REGISTRATION_PASSWORD, account['salt'])
        self.assertEqual(len(account['password_hash']), 64)
        self.assertEqual(len(account['salt']), 64)
        self.assertTrue(verify_password(REGISTRATION_PASSWORD, account['password_hash'], account['salt']))

    def test_no_password_or_live_token_is_stored_anywhere(self):
        with _SmtpSink() as sink:
            self._use_provider(sink)
            case = self._citizen()
            approved = self._approve(case)
            self.assertEqual(approved['credentials']['delivery_status'], 'SENT')
            raw_token = LINK_PATTERN.search(sink.messages[-1]).group(2)
            complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

        dump = self._stored_text()
        for secret in (REGISTRATION_PASSWORD, ACTIVATION_PASSWORD, OFFICER_PASSWORD, raw_token):
            self.assertNotIn(secret, dump)
        for token_row in self._rows('SELECT * FROM citizen_activation_tokens'):
            self.assertRegex(token_row['token_hash'], r'^[0-9a-f]{64}$')
            self.assertNotIn(raw_token, token_row['token_hash'])

    def test_the_activation_link_is_stored_only_as_a_digest(self):
        case = self._citizen()
        self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION, issued_by=self.officer['id'])
        stored = self._rows(
            'SELECT * FROM citizen_activation_tokens ORDER BY issued_at DESC LIMIT 1'
        )[0]
        self.assertEqual(stored['token_hash'], hash_token(raw_token))
        self.assertNotIn(raw_token, self._stored_text())

    # ── 4. login with the generated username ───────────────────────────────
    def test_generated_username_and_new_password_sign_in(self):
        case = self._citizen()
        approved = self._approve(case)
        username = approved['credentials']['username']
        raw_token = mint_token(case['user']['id'], ACTIVATION)
        complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

        signed_in = authenticate_user(username, ACTIVATION_PASSWORD, required_role='CITIZEN')
        self.assertIsNotNone(signed_in)
        self.assertEqual(signed_in['id'], case['user']['id'])
        self.assertEqual(signed_in['role'], 'CITIZEN')
        self.assertNotIn('password_hash', signed_in)
        self.assertNotIn('salt', signed_in)

        self.assertEqual(
            authenticate_user(case['user']['email'], ACTIVATION_PASSWORD, required_role='CITIZEN')['id'],
            case['user']['id'],
        )
        self.assertIsNone(authenticate_user(username, REGISTRATION_PASSWORD, required_role='CITIZEN'))
        self.assertIsNone(authenticate_user(username, ACTIVATION_PASSWORD, required_role='OFFICER'))

    def test_a_suspended_account_cannot_sign_in(self):
        case = self._citizen()
        approved = self._approve(case)
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET status = 'SUSPENDED' WHERE id = ?", (case['user']['id'],))
        conn.commit()
        conn.close()
        self.assertIsNone(
            authenticate_user(approved['credentials']['username'], REGISTRATION_PASSWORD,
                              required_role='CITIZEN')
        )

    # ── 5. activation link properties ──────────────────────────────────────
    def test_activation_sets_the_permanent_password_and_marks_the_account(self):
        case = self._citizen()
        approved = self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)

        result = complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

        self.assertEqual(result['username'], approved['credentials']['username'])
        account = self._user(case['user']['id'])
        self.assertEqual(account['status'], 'ACTIVE')
        credentials = get_credentials(case['user']['id'])
        self.assertIsNotNone(credentials['activated_at'])
        self.assertIsNotNone(credentials['password_set_at'])
        token = self._rows(
            'SELECT * FROM citizen_activation_tokens WHERE token_hash = ?', (hash_token(raw_token),)
        )[0]
        self.assertIsNotNone(token['used_at'])
        self.assertTrue(verify_password(
            ACTIVATION_PASSWORD, account['password_hash'], account['salt']
        ))
        self.assertIn('CITIZEN_ACCOUNT_ACTIVATED',
                      [row['action'] for row in self._rows('SELECT action FROM system_audit_logs')])

    def test_link_is_single_use(self):
        case = self._citizen()
        self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)
        complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

        with self.assertRaisesRegex(ValueError, 'already been used'):
            complete_activation(raw_token, 'another-fixture-9', 'another-fixture-9')

    def test_expired_link_is_refused(self):
        case = self._citizen()
        self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE citizen_activation_tokens SET expires_at = ?', (past,))
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(ValueError, 'expired'):
            complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

    def test_guessed_link_is_refused_without_touching_any_account(self):
        case = self._citizen()
        self._approve(case)
        before = self._user(case['user']['id'])

        with self.assertRaisesRegex(ValueError, 'not valid'):
            resolve_token('obviously-not-a-real-token', ACTIVATION)
        with self.assertRaisesRegex(ValueError, 'not valid'):
            resolve_token('', ACTIVATION)
        self.assertEqual(self._user(case['user']['id']), before)

    def test_a_newer_link_supersedes_the_previous_one(self):
        case = self._citizen()
        self._approve(case)
        first = mint_token(case['user']['id'], ACTIVATION)
        second = mint_token(case['user']['id'], ACTIVATION)

        with self.assertRaisesRegex(ValueError, 'no longer valid'):
            resolve_token(first, ACTIVATION)
        self.assertEqual(resolve_token(second, ACTIVATION)['citizen_id'], case['user']['id'])

    def test_attempt_cap_locks_a_link(self):
        case = self._citizen()
        self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)
        max_attempts = int(self._rows(
            'SELECT max_attempts FROM citizen_activation_tokens WHERE token_hash = ?',
            (hash_token(raw_token),),
        )[0]['max_attempts'])

        for _ in range(max_attempts):
            self.assertEqual(resolve_token(raw_token, ACTIVATION)['citizen_id'], case['user']['id'])
        with self.assertRaisesRegex(ValueError, 'Too many attempts'):
            resolve_token(raw_token, ACTIVATION)

    def test_reset_and_activation_tokens_are_not_interchangeable(self):
        case = self._citizen()
        self._approve(case)
        activation_token = mint_token(case['user']['id'], ACTIVATION)
        with self.assertRaisesRegex(ValueError, 'not valid'):
            resolve_token(activation_token, PASSWORD_RESET)
        with self.assertRaisesRegex(ValueError, 'not valid'):
            complete_password_reset(activation_token, RESET_PASSWORD, RESET_PASSWORD)

    # ── 6. password strength on a fresh link ───────────────────────────────
    def test_weak_and_mismatched_passwords_are_refused(self):
        case = self._citizen()
        self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)

        with self.assertRaisesRegex(ValueError, 'at least 8 characters'):
            complete_activation(raw_token, 'short', 'short')
        with self.assertRaisesRegex(ValueError, 'do not match'):
            complete_activation(raw_token, 'long-enough-1', 'long-enough-2')
        with self.assertRaisesRegex(ValueError, 'space'):
            complete_activation(raw_token, ' padded-123 ', ' padded-123 ')

        self.assertEqual(self._rows(
            'SELECT * FROM citizen_activation_tokens WHERE token_hash = ? AND used_at IS NOT NULL',
            (hash_token(raw_token),),
        ), [], 'a rejected password must not spend the link')
        complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)
        self.assertIsNotNone(self._user(case['user']['id'])['password_changed_at'])

    # ── 7. honest delivery reporting ───────────────────────────────────────
    def test_delivery_is_reported_as_not_configured_without_a_provider(self):
        case = self._citizen()
        approved = self._approve(case)

        self.assertEqual(approved['credentials']['delivery_status'], 'NOT_CONFIGURED')
        self.assertEqual(approved['credentials']['delivery_channel'], 'NONE')
        credentials = get_credentials(case['user']['id'])
        self.assertIsNone(credentials['delivered_at'])
        self.assertEqual(credentials['delivery_status'], 'NOT_CONFIGURED')

        summary = activation_summary(case['user']['id'])
        self.assertEqual(summary['delivery_status'], 'NOT_CONFIGURED')
        self.assertEqual(summary['link_status'], 'AVAILABLE')

        notices = self._rows('SELECT * FROM notifications WHERE type = ?', ('CITIZEN_CREDENTIALS',))
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0]['user_id'], case['user']['id'])
        self.assertIn('could not be sent', notices[0]['message'])
        self.assertNotIn('have been sent to your', notices[0]['message'])

    def test_delivery_is_reported_sent_only_when_the_provider_accepts(self):
        with _SmtpSink() as sink:
            self._use_provider(sink)
            case = self._citizen()
            approved = self._approve(case)

            self.assertEqual(approved['credentials']['delivery_status'], 'SENT')
            self.assertEqual(approved['credentials']['delivery_channel'], 'EMAIL')
            self.assertEqual(len(sink.messages), 1)

            message = sink.messages[0]
            self.assertIn(f'Subject: {SUBJECT}', message)
            self.assertIn('Your registration and identity verification have been successfully completed.', message)
            self.assertIn('Your Citizen Portal account is now ready for activation.', message)
            self.assertIn(f"Your username: {approved['credentials']['username']}", message)
            self.assertIn('Please use the secure account activation link to set your password', message)
            self.assertIn('Thank you for using the Digital FIR Portal.', message)
            self.assertIn('/activate/', message)
            self.assertNotIn(REGISTRATION_PASSWORD, message)

            link = LINK_PATTERN.search(message).group(0)
            raw_token = link.rsplit('/', 1)[1]
            result = complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)
            self.assertEqual(result['username'], approved['credentials']['username'])

            credentials = get_credentials(case['user']['id'])
            self.assertIsNotNone(credentials['delivered_at'])
            self.assertEqual(credentials['delivery_attempts'], 1)
            self.assertEqual(activation_summary(case['user']['id'])['link_status'], 'USED')

    def test_delivery_is_reported_failed_when_the_provider_is_unreachable(self):
        os.environ['SMTP_HOST'] = '127.0.0.1'
        os.environ['SMTP_PORT'] = str(_closed_port())
        os.environ['SMTP_USE_TLS'] = 'none'
        os.environ['SMTP_MAIL_FROM'] = 'no-reply@eksp.gov.test'
        case = self._citizen()

        approved = self._approve(case)

        self.assertEqual(approved['credentials']['delivery_status'], 'FAILED')
        self.assertIn('did not accept the message', approved['credentials']['delivery_detail'])
        credentials = get_credentials(case['user']['id'])
        self.assertIsNone(credentials['delivered_at'])
        notices = self._rows('SELECT * FROM notifications WHERE type = ?', ('CITIZEN_CREDENTIALS',))
        self.assertEqual(len(notices), 1)
        self.assertIn('delivery failed', notices[0]['message'])
        self.assertEqual(notices[0]['severity'], 'WARNING')

    def test_email_without_a_sender_address_is_not_configured(self):
        os.environ['SMTP_HOST'] = '127.0.0.1'
        case = self._citizen()
        approved = self._approve(case)
        self.assertEqual(approved['credentials']['delivery_status'], 'NOT_CONFIGURED')
        self.assertIn('SMTP_MAIL_FROM', approved['credentials']['delivery_detail'])

    def test_the_provider_password_never_reaches_a_log_or_a_message(self):
        smtp_secret = 'smtp-provider-fixture-5'
        with _SmtpSink() as sink:
            self._use_provider(sink)
            os.environ['SMTP_USERNAME'] = 'no-reply@eksp.gov.test'
            os.environ['SMTP_PASSWORD'] = smtp_secret
            case = self._citizen()
            approved = self._approve(case)

            # The sink offers no AUTH mechanism over a plaintext connection, so the
            # client refuses to authenticate and the failure is recorded with the
            # exception name only — never with the credential that failed.
            self.assertEqual(approved['credentials']['delivery_status'], 'FAILED')
            self.assertIn('SMTPNotSupportedError', approved['credentials']['delivery_detail'])
            self.assertEqual(sink.messages, [], 'nothing was handed over for delivery')

        dump = self._stored_text()
        self.assertNotIn(smtp_secret, dump)
        self.assertNotIn(smtp_secret, '\n'.join(sink.messages))

    # ── 8. retry ───────────────────────────────────────────────────────────
    def test_retry_mints_a_fresh_link_and_records_another_attempt(self):
        with _SmtpSink() as sink:
            self._use_provider(sink)
            case = self._citizen()
            approved = self._approve(case)
            self.assertEqual(approved['credentials']['delivery_status'], 'SENT')
            first_token = LINK_PATTERN.search(sink.messages[-1]).group(2)

            outcome = retry_delivery(case['user']['id'], self.officer)
            second_token = LINK_PATTERN.search(sink.messages[-1]).group(2)

            self.assertEqual(outcome['delivery_status'], 'SENT')
            self.assertEqual(outcome['delivery_attempts'], 2)
            self.assertNotEqual(first_token, second_token)
            with self.assertRaisesRegex(ValueError, 'no longer valid'):
                resolve_token(first_token, ACTIVATION)
            complete_activation(second_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)

            notices = self._rows('SELECT * FROM notifications WHERE type = ?', ('CITIZEN_CREDENTIALS',))
            self.assertEqual(len(notices), 2, 'each attempt records exactly one notice')
            self.assertEqual(len({row['event_id'] for row in notices}), 2)

    def test_retry_before_any_credentials_is_refused(self):
        case = self._citizen()
        with self.assertRaisesRegex(ValueError, 'No credentials have been issued'):
            retry_delivery(case['user']['id'], self.officer)

    def test_self_service_link_recovers_from_a_failed_delivery(self):
        os.environ['SMTP_HOST'] = '127.0.0.1'
        os.environ['SMTP_PORT'] = str(_closed_port())
        os.environ['SMTP_USE_TLS'] = 'none'
        os.environ['SMTP_MAIL_FROM'] = 'no-reply@eksp.gov.test'
        case = self._citizen()
        approved = self._approve(case)
        self.assertEqual(approved['credentials']['delivery_status'], 'FAILED')

        issued = issue_self_service_link(case['user']['id'])
        raw_token = issued['link'].rsplit('/', 1)[1]
        self.assertTrue(issued['link'].startswith('https://portal.example.test/activate/'))

        complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)
        self.assertIsNotNone(
            authenticate_user(approved['credentials']['username'], ACTIVATION_PASSWORD,
                              required_role='CITIZEN')
        )

    # ── 9. duplicate approval ──────────────────────────────────────────────
    def test_repeating_the_approval_cannot_create_a_second_set(self):
        case = self._citizen()
        approved = self._approve(case)
        username = approved['credentials']['username']

        with self.assertRaisesRegex(ValueError, 'already approved'):
            self._approve(case)
        self.assertEqual(len(self._rows('SELECT * FROM citizen_credentials')), 1)

        again = issue_credentials(get_citizen_application(case['application']['id']),
                                  self.officer, deliver=False)
        self.assertFalse(again['created'])
        self.assertEqual(again['username'], username)
        self.assertEqual(get_credentials(case['user']['id'])['username'], username)
        self.assertEqual(len(self._rows('SELECT * FROM users')), 2, 'one citizen, one officer')

    def test_rejection_keeps_the_account_inactive_and_issues_nothing(self):
        case = self._citizen()
        record_application_action(case['application']['id'], self.officer, 'REJECT',
                                  'Document image unreadable.')

        self.assertIsNone(get_credentials(case['user']['id']))
        self.assertEqual(self._user(case['user']['id'])['status'], 'SUSPENDED')
        self.assertIsNone(activation_summary(case['user']['id']))
        application = get_citizen_application(case['application']['id'])
        self.assertEqual(application['internal_remarks'], 'Document image unreadable.')
        self.assertIsNone(authenticate_user(case['user']['email'], REGISTRATION_PASSWORD,
                                            required_role='CITIZEN'))

    # ── 10. password reset ─────────────────────────────────────────────────
    def test_password_reset_link_from_the_email_changes_the_password(self):
        with _SmtpSink() as sink:
            self._use_provider(sink)
            case = self._citizen()
            approved = self._approve(case)
            username = approved['credentials']['username']

            result = request_password_reset(username)

            self.assertEqual(result['delivery_status'], 'SENT')
            reset_link = LINK_PATTERN.search(sink.messages[-1]).group(0)
            self.assertIn('/reset-password/', reset_link)
            raw_token = reset_link.rsplit('/', 1)[1]

            completed = complete_password_reset(raw_token, RESET_PASSWORD, RESET_PASSWORD)
            self.assertEqual(completed['username'], username)
            self.assertIsNotNone(authenticate_user(username, RESET_PASSWORD, required_role='CITIZEN'))
            self.assertIsNone(authenticate_user(username, REGISTRATION_PASSWORD, required_role='CITIZEN'))
            self.assertEqual(len(sink.messages), 2, 'one approval notice and one reset notice')

    def test_reset_can_be_requested_by_email_or_mobile(self):
        with _SmtpSink() as sink:
            self._use_provider(sink)
            case = self._citizen()
            self._approve(case)
            for identifier in (case['user']['email'], case['user']['phone']):
                self.assertEqual(request_password_reset(identifier)['delivery_status'], 'SENT', identifier)

    def test_unknown_identifier_does_not_reveal_whether_an_account_exists(self):
        unknown = request_password_reset('nobody@example.test')
        self.assertTrue(unknown['requested'])
        self.assertEqual(unknown['delivery_status'], 'NOT_CONFIGURED')
        self.assertIn('If that account is verified', unknown['detail'])
        self.assertEqual(self._rows('SELECT * FROM citizen_activation_tokens'), [])

        case = self._citizen()
        self._approve(case)
        result = request_password_reset('nobody@example.test')
        self.assertEqual(result['detail'], unknown['detail'], 'same generic wording either way')
        self.assertNotIn('username_shown', result)

    def test_ambiguous_identifier_is_refused_instead_of_guessing(self):
        shared_phone = '9800000000'
        first = self._citizen('Bala Krishnan')
        second_user = register_user(
            name='Chitra Devi', email='chitra@example.test', phone=shared_phone,
            password=REGISTRATION_PASSWORD, role='CITIZEN', status='ACTIVE',
        )
        first['user'] = self._touch_phone(first['user']['id'], shared_phone)
        issue_credentials(first['application'], self.officer, deliver=False)
        second_application = self._application_for(second_user)
        issue_credentials(second_application, self.officer, deliver=False)

        result = request_password_reset(shared_phone)
        self.assertEqual(result['delivery_status'], 'NOT_CONFIGURED')
        self.assertIn('If that account is verified', result['detail'])
        self.assertEqual(self._rows('SELECT * FROM citizen_activation_tokens'), [])

    def _touch_phone(self, user_id: str, phone: str) -> dict:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET phone = ? WHERE id = ?', (phone, user_id))
        conn.commit()
        conn.close()
        return self._user(user_id)

    def _application_for(self, user: dict) -> dict:
        application_id = f"capp-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO citizen_applications (
                id, reference, citizen_id, full_name, mobile, email, address, state, district,
                gov_id_type, gov_id_masked, status, submitted_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, '5 Salt Street', 'Tamil Nadu', 'Chennai',
                      'PASSPORT', 'P1234567', 'APPROVED', ?, ?)
            """,
            (application_id, f'CVR-T{next(COUNTER):06d}', user['id'], user['name'],
             user['phone'], user['email'], now, now),
        )
        conn.commit()
        conn.close()
        return get_citizen_application(application_id)

    # ── 11. citizen isolation ──────────────────────────────────────────────
    def test_each_citizen_sees_only_their_own_credentials(self):
        first = self._citizen('Devi Menon')
        second = self._citizen('Devi Menon')
        self._approve(first)
        self._approve(second)

        summary_one = activation_summary(first['user']['id'])
        summary_two = activation_summary(second['user']['id'])
        self.assertNotEqual(summary_one['username'], summary_two['username'])
        self.assertNotIn(summary_two['username'],
                         str(self._rows('SELECT * FROM notifications WHERE user_id = ?',
                                        (first['user']['id'],))))
        self.assertIsNone(activation_summary('citizen-that-does-not-exist'))

    def test_in_app_notice_names_the_username_and_no_secret(self):
        case = self._citizen()
        approved = self._approve(case)
        raw_token = mint_token(case['user']['id'], ACTIVATION)

        notices = self._rows('SELECT * FROM notifications WHERE user_id = ?', (case['user']['id'],))
        credentials_notice = [row for row in notices if row['type'] == 'CITIZEN_CREDENTIALS']
        self.assertEqual(len(credentials_notice), 1)
        self.assertIn(approved['credentials']['username'], credentials_notice[0]['message'])
        self.assertIn(SUBJECT, credentials_notice[0]['title'])
        self.assertNotIn(raw_token, credentials_notice[0]['message'])
        self.assertNotIn(REGISTRATION_PASSWORD, credentials_notice[0]['message'])
        self.assertEqual(credentials_notice[0]['is_read'], 0)

    def test_events_are_recorded_for_the_application(self):
        case = self._citizen()
        self._approve(case)
        actions = [event['action'] for event in get_application_events(case['application']['id'])]
        self.assertIn('CREDENTIALS_ISSUED', actions)
        self.assertIn('APPROVED', actions)


if __name__ == '__main__':
    unittest.main()

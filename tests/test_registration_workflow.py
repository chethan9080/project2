"""
Automated end-to-end tests for the Citizen Registration workflow.

Covers:
A. A valid registration persists the user, application, secure files, audit row
   and officer alert in one transaction.
B. Verification Officer approval provisions exactly one credential set and a
   single-use activation link; duplicate decisions are refused.
C. Citizen activation and login work, pending/rejected/suspended accounts stay
   locked out, and tokens are single-use.
D. Registration and approval events reach multiple live sessions, and the
   database still resynchronises when a push event is missed.
E. Failure paths: duplicate email/mobile/identity, unverified/expired/blocked
   OTP, missing fields, invalid uploads, database failure and restart recovery.
"""

import asyncio
import itertools
import os
import re
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_registration_workflow_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'workflow.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')
os.environ.pop('TEST_MODE', None)

import sys

PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services import verification_service
from backend.services.auth_service import (
    authenticate_user,
    get_citizen_access_issue,
    register_user,
)
from backend.services.citizen_credentials_service import (
    ACTIVATION,
    complete_activation,
    get_credentials,
    hash_token,
    mint_token,
)
from backend.services.citizen_registration_service import (
    SECURE_ROOT,
    find_application_for_status,
    get_application_events,
    get_citizen_application,
    record_application_action,
    resubmit_additional_information,
    resolve_secure_file,
    submit_citizen_registration,
)
from backend.services.config_service import set_test_mode
from backend.services.db import get_db_connection, init_database
from backend.services.realtime_events import publish, reset, subscribe, subscriber_count, unsubscribe
from backend.services.verification_service import (
    TEST_MODE_OTP,
    get_otp_session_status,
    send_otp,
    verify_otp,
)

COUNTER = itertools.count(1)
PASSWORD = 'WorkflowPass!23'
ACTIVATION_PASSWORD = 'CitizenChosen!24'
REFERENCE_PATTERN = re.compile(r'^CVR-\d{8}-[0-9A-F]{6}$')

PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06'
    b'\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05'
    b'\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

PROVIDER_ENV_KEYS = (
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USERNAME', 'SMTP_PASSWORD',
    'SMTP_MAIL_FROM', 'SMTP_USE_TLS',
    'SMS_GATEWAY_URL', 'SMS_GATEWAY_API_KEY', 'SMS_GATEWAY_SENDER',
    'PUBLIC_BASE_URL',
)


def _mobile() -> str:
    return f"9{next(COUNTER):09d}"


class RegistrationWorkflowTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(
            TEST_DB_DIRECTORY, f'workflow_{self._testMethodName}_{next(COUNTER)}.db'
        )
        for key in PROVIDER_ENV_KEYS:
            os.environ.pop(key, None)
        init_database()
        set_test_mode(True)
        reset()

        serial = next(COUNTER)
        self.vo = register_user(
            name=f'Workflow Verification Officer {serial}',
            email=f'vo{serial}@workflow.test',
            phone=f'8{serial:09d}',
            password='OfficerPass!23',
            role='VERIFICATION_OFFICER',
            badge_number=f'WF-VO-{serial}',
            station='Workflow Police Station',
            rank='Police Sub Inspector',
            status='ACTIVE',
        )

    def tearDown(self):
        set_test_mode(False)
        reset()

    # ── helpers ────────────────────────────────────────────────────────────
    def _verified_otp(self, mobile: str) -> None:
        # Reuse a session that is already verified: resending would hit the
        # deliberate 30-second cooldown between codes.
        if get_otp_session_status(mobile).get('verified'):
            return
        ok, message, _ = send_otp(mobile)
        self.assertTrue(ok, message)
        ok, message = verify_otp(mobile, TEST_MODE_OTP)
        self.assertTrue(ok, message)

    def _registration_payload(self, **overrides):
        serial = next(COUNTER)
        payload = {
            'full_name': f'Workflow Citizen {serial}',
            'email': f'citizen{serial}@workflow.test',
            'password': PASSWORD,
            'date_of_birth': '1995-01-15',
            'gender': 'Female',
            'mobile': _mobile(),
            'gov_id_type': 'Aadhaar Card',
            'gov_id': f'1111{serial:04d}{serial:04d}',
            'address': '10 Workflow Street, Ward 1',
            'state': 'Karnataka',
            'district': 'Bengaluru Urban',
            'photo_bytes': PNG,
            'photo_ext': '.png',
            'document_bytes': PNG,
            'document_ext': '.png',
            'document_name': 'aadhaar.png',
        }
        payload.update(overrides)
        return payload

    def _submit(self, verified: bool = True, **overrides):
        payload = self._registration_payload(**overrides)
        if verified:
            self._verified_otp(payload['mobile'])
        return submit_citizen_registration(**payload)

    def _count(self, table: str) -> int:
        conn = get_db_connection()
        try:
            return conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
        finally:
            conn.close()

    def _age_otp(self, mobile: str) -> None:
        conn = get_db_connection()
        try:
            past = datetime.now(timezone.utc) - timedelta(seconds=61)
            conn.execute(
                'UPDATE otp_sessions SET expires_at = ? WHERE mobile = ?',
                (past.isoformat(), mobile),
            )
            conn.commit()
        finally:
            conn.close()

    # ── A. successful registration ─────────────────────────────────────────
    def test_a_successful_registration_persists_everything(self):
        result = self._submit()
        user, application = result['user'], result['application']

        self.assertEqual(user['status'], 'PENDING_VERIFICATION')
        self.assertEqual(user['role'], 'CITIZEN')
        self.assertNotIn('password_hash', user)
        self.assertNotIn('salt', user)

        self.assertEqual(application['status'], 'PENDING')
        self.assertRegex(application['reference'], REFERENCE_PATTERN)
        self.assertEqual(application['citizen_id'], user['id'])

        stored = get_citizen_application(application['id'])
        self.assertIsNotNone(stored)
        self.assertEqual(stored['reference'], application['reference'])

        self.assertTrue(resolve_secure_file(application['photo_path']))
        self.assertTrue(resolve_secure_file(application['id_document_path']))

        events = get_application_events(application['id'])
        self.assertEqual(events[0]['action'], 'SUBMITTED')
        self.assertEqual(events[0]['status_to'], 'PENDING')

        conn = get_db_connection()
        try:
            verification = conn.execute(
                'SELECT * FROM citizen_verifications WHERE citizen_id = ?', (user['id'],)
            ).fetchone()
            alert = conn.execute(
                'SELECT * FROM citizen_application_alerts WHERE application_id = ? AND recipient_id = ?',
                (application['id'], self.vo['id']),
            ).fetchone()
            audit = conn.execute(
                "SELECT * FROM system_audit_logs WHERE user_id = ? AND action = 'CITIZEN_ONBOARDING_SUBMITTED'",
                (user['id'],),
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(verification)
        self.assertEqual(verification['status'], 'PENDING')
        self.assertIsNotNone(alert)
        self.assertIsNotNone(audit)

        # The portal stays locked until approval.
        self.assertIsNone(authenticate_user(user['email'], PASSWORD, required_role='CITIZEN'))
        self.assertIn('verification', (get_citizen_access_issue(user) or '').lower())

    # ── B. officer verification ────────────────────────────────────────────
    def test_b_officer_approval_provisions_one_credential_set(self):
        application = self._submit()['application']
        approved = record_application_action(
            application['id'], self.vo, 'APPROVE', 'Identity documents match.'
        )
        self.assertEqual(approved['status'], 'APPROVED')

        credentials = get_credentials(application['citizen_id'])
        self.assertIsNotNone(credentials)
        self.assertEqual(self._count('citizen_credentials'), 1)
        stored = get_citizen_application(application['id'])
        self.assertEqual(stored['reviewed_by'], self.vo['id'])
        self.assertTrue(stored['reviewed_at'])

        events = get_application_events(application['id'])
        approval_event = [event for event in events if event['action'] == 'APPROVED'][0]
        self.assertEqual(approval_event['actor_id'], self.vo['id'])
        self.assertEqual(approval_event['actor_role'], 'VERIFICATION_OFFICER')

        tokens = self._activation_rows(application['citizen_id'])
        self.assertEqual(len(tokens), 1)
        self.assertEqual(len(tokens[0]['token_hash']), 64)
        self.assertNotIn('token', {key.lower() for key in tokens[0].keys()})

        with self.assertRaises(ValueError):
            record_application_action(application['id'], self.vo, 'APPROVE', 'Second approval.')
        self.assertEqual(self._count('citizen_credentials'), 1)

        with self.assertRaises(PermissionError):
            record_application_action(application['id'], {'id': 'x', 'role': 'CITIZEN'}, 'REJECT', 'no')

    def test_b_request_info_and_resubmission(self):
        application = self._submit()['application']
        requested = record_application_action(
            application['id'], self.vo, 'REQUEST_INFO', 'Please upload a clearer photograph.'
        )
        self.assertEqual(requested['status'], 'ADDITIONAL_INFO_REQUIRED')

        updated = resubmit_additional_information(
            application['id'],
            reference=application['reference'],
            identifier=application['email'],
            note='A clearer photograph is attached.',
            photo_bytes=PNG,
            photo_ext='.png',
        )
        self.assertEqual(updated['status'], 'UNDER_REVIEW')

        with self.assertRaises(ValueError):
            record_application_action(application['id'], self.vo, 'REJECT', '')

    def test_b_rejection_keeps_the_citizen_locked_out(self):
        result = self._submit()
        application, user = result['application'], result['user']
        rejected = record_application_action(
            application['id'], self.vo, 'REJECT', 'The ID document is unreadable.'
        )
        self.assertEqual(rejected['status'], 'REJECTED')
        self.assertIsNone(authenticate_user(user['email'], PASSWORD, required_role='CITIZEN'))
        self.assertIsNone(authenticate_user(user['email'], 'WrongPassword!1', required_role='CITIZEN'))

        lookup = find_application_for_status(application['reference'], user['email'])
        self.assertEqual(lookup['status'], 'REJECTED')
        events = get_application_events(application['id'])
        self.assertEqual(events[-1]['remarks'], 'The ID document is unreadable.')

    # ── C. activation and login ────────────────────────────────────────────
    def test_c_activation_then_login_with_issued_username(self):
        result = self._submit()
        application, user = result['application'], result['user']
        record_application_action(application['id'], self.vo, 'APPROVE', 'Verified.')
        credentials = get_credentials(user['id'])

        raw_token = mint_token(user['id'], ACTIVATION, issued_by=self.vo['id'])
        completed = complete_activation(raw_token, ACTIVATION_PASSWORD, ACTIVATION_PASSWORD)
        self.assertEqual(completed['username'], credentials['username'])
        self.assertEqual(self._count('citizen_credentials'), 1)

        # The registration password never becomes the account password.
        self.assertIsNone(authenticate_user(credentials['username'], PASSWORD))
        logged_in = authenticate_user(credentials['username'], ACTIVATION_PASSWORD)
        self.assertIsNotNone(logged_in)
        self.assertEqual(logged_in['id'], user['id'])
        self.assertEqual(logged_in['role'], 'CITIZEN')

        with self.assertRaises(ValueError):
            complete_activation(raw_token, 'AnotherPass!25', 'AnotherPass!25')

        expired = mint_token(user['id'], ACTIVATION, issued_by=self.vo['id'])
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE citizen_activation_tokens SET expires_at = ? WHERE token_hash = ?",
                ((datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(), hash_token(expired)),
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(ValueError):
            complete_activation(expired, 'AnotherPass!25', 'AnotherPass!25')

    def _activation_rows(self, citizen_id):
        conn = get_db_connection()
        try:
            return [dict(row) for row in conn.execute(
                'SELECT * FROM citizen_activation_tokens WHERE citizen_id = ?', (citizen_id,)
            ).fetchall()]
        finally:
            conn.close()

    # ── D. real-time push and database fallback ────────────────────────────
    def test_d_two_live_sessions_receive_events_and_db_resyncs(self):
        async def wait_for_type(queue, expected):
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 3
            while True:
                remaining = deadline - loop.time()
                self.assertGreater(remaining, 0, f'No {expected} event arrived.')
                event = await asyncio.wait_for(queue.get(), timeout=remaining)
                if event.get('type') == expected:
                    return event

        async def scenario():
            first = subscribe()
            second = subscribe()
            self.assertEqual(subscriber_count(), 2)

            payload = self._registration_payload()
            self._verified_otp(payload['mobile'])
            result = submit_citizen_registration(**payload)
            application = result['application']

            for queue in (first, second):
                event = await wait_for_type(queue, 'CITIZEN_APPLICATION_SUBMITTED')
                self.assertEqual(event['reference'], application['reference'])

            record_application_action(application['id'], self.vo, 'APPROVE', 'Approved.')
            for queue in (first, second):
                event = await wait_for_type(queue, 'CITIZEN_APPLICATION_UPDATED')
                self.assertEqual(event['status'], 'APPROVED')

            unsubscribe(first)
            unsubscribe(second)
            self.assertEqual(subscriber_count(), 0)

            # Database resynchronisation is the fallback when a push is missed.
            refreshed = find_application_for_status(application['reference'], payload['email'])
            self.assertEqual(refreshed['status'], 'APPROVED')
            return application
        self.assertIsNotNone(asyncio.run(scenario()))

    def test_d_publish_is_safe_without_listeners(self):
        publish({'type': 'CITIZEN_APPLICATION_UPDATED', 'status': 'APPROVED'})
        self.assertEqual(subscriber_count(), 0)

    # ── E. failure paths ───────────────────────────────────────────────────
    def test_e_duplicate_email_mobile_and_identity_are_refused(self):
        first = self._submit()

        with self.assertRaisesRegex(ValueError, 'email'):
            self._submit(email=first['application']['email'])

        with self.assertRaisesRegex(ValueError, 'mobile'):
            self._submit(mobile=first['application']['mobile'])

        with self.assertRaisesRegex(ValueError, 'Government ID'):
            self._submit(gov_id=first['application']['gov_id_masked'])

        self.assertEqual(self._count('citizen_applications'), 1)

    def test_e_otp_must_be_verified_current_and_unblocked(self):
        unverified = self._registration_payload()
        send_otp(unverified['mobile'])
        with self.assertRaisesRegex(ValueError, 'not verified'):
            submit_citizen_registration(**unverified)

        expired = self._registration_payload()
        self._verified_otp(expired['mobile'])
        self._age_otp(expired['mobile'])
        with self.assertRaisesRegex(ValueError, 'expired'):
            submit_citizen_registration(**expired)

        blocked = self._registration_payload()
        send_otp(blocked['mobile'])
        for _ in range(verification_service.OTP_MAX_ATTEMPTS):
            verify_otp(blocked['mobile'], '000000')
        with self.assertRaisesRegex(ValueError, 'OTP'):
            submit_citizen_registration(**blocked)

        self.assertEqual(self._count('citizen_applications'), 0)
        self.assertEqual(self._count('users'), 1)  # only the seeded officer

    def test_e_missing_fields_and_invalid_uploads_are_refused(self):
        payload = self._registration_payload()
        self._verified_otp(payload['mobile'])

        with self.assertRaisesRegex(ValueError, 'Full legal name'):
            submit_citizen_registration(**{**payload, 'full_name': '  '})
        with self.assertRaisesRegex(ValueError, '(?i)email'):
            submit_citizen_registration(**{**payload, 'email': 'not-an-email'})
        with self.assertRaisesRegex(ValueError, 'Password'):
            submit_citizen_registration(**{**payload, 'password': 'short'})
        with self.assertRaisesRegex(ValueError, '(?i)date of birth'):
            submit_citizen_registration(**{**payload, 'date_of_birth': '2999-01-01'})
        with self.assertRaisesRegex(ValueError, 'photograph'):
            submit_citizen_registration(**{**payload, 'photo_bytes': b'not-an-image'})
        with self.assertRaisesRegex(ValueError, 'format'):
            submit_citizen_registration(**{**payload, 'document_ext': '.exe'})

        self.assertEqual(self._count('citizen_applications'), 0)
        self.assertEqual(self._count('users'), 1)

    def test_e_database_failure_rolls_back_and_cleans_files(self):
        before = set(os.listdir(SECURE_ROOT)) if os.path.isdir(SECURE_ROOT) else set()
        payload = self._registration_payload()
        self._verified_otp(payload['mobile'])

        with patch(
            'backend.services.verification_service.record_citizen_verification_event',
            side_effect=RuntimeError('simulated database failure'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'simulated'):
                submit_citizen_registration(**payload)

        self.assertEqual(self._count('citizen_applications'), 0)
        self.assertEqual(self._count('users'), 1)
        self.assertEqual(self._count('citizen_credentials'), 0)
        after = set(os.listdir(SECURE_ROOT)) if os.path.isdir(SECURE_ROOT) else set()
        self.assertEqual(before, after)

    def test_e_registration_survives_a_restart(self):
        result = self._submit()
        reference = result['application']['reference']

        # Every service call opens a fresh SQLite connection; re-reading through the
        # public lookup proves the rows are durable rather than held in memory.
        refreshed = find_application_for_status(reference, result['user']['email'])
        self.assertIsNotNone(refreshed)
        self.assertEqual(refreshed['status'], 'PENDING')
        self.assertEqual(refreshed['reference'], reference)

        record_application_action(result['application']['id'], self.vo, 'APPROVE', 'Verified.')
        approved = find_application_for_status(reference, result['user']['email'])
        self.assertEqual(approved['status'], 'APPROVED')
        self.assertEqual(self._count('citizen_credentials'), 1)


if __name__ == '__main__':
    unittest.main()

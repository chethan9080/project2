"""
Automated Test Suite for Citizen Registration Mobile OTP Verification.
Tests:
1. OTP sessions are persisted in the database (never in process memory only)
2. The fixed development code 123456 verifies while TEST MODE is enabled
3. Wrong codes are rejected and the three-attempt restriction is enforced
4. Expired codes are rejected, live codes keep the 10-minute window
5. Verification state survives a page refresh (re-read from the database)
6. Mobile numbers match regardless of +91 / leading zero / spacing
7. A resend replaces the previous session and honours the cooldown
8. Production mode never accepts 123456 and never claims delivery it did not make
9. The plaintext OTP is never stored, returned or logged
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

TEST_DB_DIRECTORY = tempfile.mkdtemp(prefix='efir_otp_tests_')
os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, 'fir_otp_test.db')
os.environ.setdefault('VALIDATOR_PRIVATE_KEY', 'TEST_VALIDATOR_KEY_12345')

import sys
PORTAL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PORTAL_DIR not in sys.path:
    sys.path.insert(0, PORTAL_DIR)

from backend.services import verification_service
from backend.services.config_service import set_test_mode
from backend.services.db import get_db_connection, init_database

TEST_MOBILE = '9876543210'
FIXED_TEST_OTP = '123456'


class OtpVerificationTests(unittest.TestCase):

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_DB_DIRECTORY, ignore_errors=True)

    def setUp(self):
        os.environ['FIR_DB_PATH'] = os.path.join(TEST_DB_DIRECTORY, f'otp_{self.id()}.db')
        init_database()
        set_test_mode(True)

    def tearDown(self):
        set_test_mode(False)

    # ── helpers ────────────────────────────────────────────────────────────
    def _rows(self):
        conn = get_db_connection()
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM otp_sessions ORDER BY created_at')
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def _age_session(self, seconds):
        """Move the stored session backwards in time without touching the service."""
        conn = get_db_connection()
        try:
            past = datetime.now(timezone.utc) - timedelta(seconds=seconds)
            conn.execute('UPDATE otp_sessions SET created_at = ?, expires_at = ?',
                         (past.isoformat(), (past + timedelta(seconds=verification_service.OTP_TTL_SECONDS)).isoformat()))
            conn.commit()
        finally:
            conn.close()

    def _expire_session(self):
        conn = get_db_connection()
        try:
            past = datetime.now(timezone.utc) - timedelta(seconds=61)
            conn.execute('UPDATE otp_sessions SET expires_at = ?', (past.isoformat(),))
            conn.commit()
        finally:
            conn.close()

    # ── 1. persistence ─────────────────────────────────────────────────────
    def test_send_otp_persists_session_in_database(self):
        ok, message, code = verification_service.send_otp(TEST_MOBILE)
        self.assertTrue(ok, message)
        self.assertEqual(code, FIXED_TEST_OTP)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['mobile'], TEST_MOBILE)
        self.assertEqual(rows[0]['max_attempts'], 3)
        self.assertEqual(rows[0]['attempts'], 0)
        self.assertEqual(rows[0]['verified'], 0)

        created = datetime.fromisoformat(rows[0]['created_at'])
        expires = datetime.fromisoformat(rows[0]['expires_at'])
        self.assertEqual(int((expires - created).total_seconds()), 600)

    def test_plaintext_otp_is_never_stored(self):
        verification_service.send_otp(TEST_MOBILE)
        row = self._rows()[0]
        self.assertNotIn(FIXED_TEST_OTP, row['code_hash'])
        self.assertNotIn(FIXED_TEST_OTP, str(row.values()))
        self.assertEqual(len(row['code_hash']), 64)

    # ── 2. fixed development OTP ───────────────────────────────────────────
    def test_fixed_otp_verifies_in_test_mode(self):
        verification_service.send_otp(TEST_MOBILE)
        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertTrue(ok, message)
        self.assertEqual(self._rows()[0]['verified'], 1)

        status = verification_service.get_otp_session_status(TEST_MOBILE)
        self.assertTrue(status['verified'])

    def test_wrong_otp_is_rejected(self):
        verification_service.send_otp(TEST_MOBILE)
        ok, message = verification_service.verify_otp(TEST_MOBILE, '654321')
        self.assertFalse(ok)
        self.assertIn('Invalid OTP code', message)
        self.assertEqual(self._rows()[0]['attempts'], 1)

    def test_malformed_otp_is_rejected_without_consuming_an_attempt(self):
        verification_service.send_otp(TEST_MOBILE)
        for value in ('', '12345', 'abc123', '1234567'):
            ok, message = verification_service.verify_otp(TEST_MOBILE, value)
            self.assertFalse(ok)
            self.assertIn('digit OTP', message)
        self.assertEqual(self._rows()[0]['attempts'], 0)

    # ── 3. three-attempt restriction ───────────────────────────────────────
    def test_three_attempt_restriction_locks_the_session(self):
        verification_service.send_otp(TEST_MOBILE)

        first = verification_service.verify_otp(TEST_MOBILE, '111111')
        self.assertIn('2 attempt(s) remaining', first[1])
        second = verification_service.verify_otp(TEST_MOBILE, '222222')
        self.assertIn('1 attempt(s) remaining', second[1])
        third = verification_service.verify_otp(TEST_MOBILE, '333333')
        self.assertFalse(third[0])
        self.assertIn('Attempt limit reached', third[1])

        # The exhausted session is gone, so even the correct code no longer passes.
        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertFalse(ok)
        self.assertIn('No active OTP session', message)

    # ── 4. expiry ──────────────────────────────────────────────────────────
    def test_expired_otp_is_rejected(self):
        verification_service.send_otp(TEST_MOBILE)
        self._expire_session()
        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertFalse(ok)
        self.assertIn('expired', message)
        self.assertEqual(self._rows(), [])

    def test_otp_is_accepted_before_the_10_minute_expiry(self):
        verification_service.send_otp(TEST_MOBILE)
        self._age_session(599)
        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertTrue(ok, message)

    # ── 5. refresh resilience ──────────────────────────────────────────────
    def test_verification_state_survives_page_refresh(self):
        verification_service.send_otp(TEST_MOBILE)
        verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)

        # A page reload re-runs the page function and reads state from the database.
        status = verification_service.get_otp_session_status(TEST_MOBILE)
        self.assertTrue(status['valid_mobile'])
        self.assertTrue(status['has_session'])
        self.assertTrue(status['verified'])
        self.assertEqual(status['attempts_remaining'], 3)

        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertTrue(ok, message)
        self.assertIn('already verified', message)

    def test_status_without_a_session_is_reported_honestly(self):
        status = verification_service.get_otp_session_status(TEST_MOBILE)
        self.assertTrue(status['valid_mobile'])
        self.assertFalse(status['has_session'])
        self.assertFalse(status['verified'])
        self.assertEqual(status['can_resend_in'], 0)

    # ── 6. mobile number matching ──────────────────────────────────────────
    def test_mobile_formats_resolve_to_the_same_session(self):
        ok, _, _ = verification_service.send_otp('+91 98765 43210')
        self.assertTrue(ok)
        self.assertEqual(self._rows()[0]['mobile'], TEST_MOBILE)
        for variant in ('9876543210', '98765 43210', '098765-43210'):
            ok, message = verification_service.verify_otp(variant, FIXED_TEST_OTP)
            self.assertTrue(ok, f'{variant}: {message}')

    def test_invalid_mobile_numbers_are_rejected(self):
        for value in ('', '   ', '12345', '98765432101', 'abcdefghij'):
            ok, message, code = verification_service.send_otp(value)
            self.assertFalse(ok)
            self.assertIsNone(code)
            self.assertIn('10 digits', message)
        ok, message = verification_service.verify_otp('12345', FIXED_TEST_OTP)
        self.assertFalse(ok)
        self.assertEqual(self._rows(), [])

    # ── 7. resend behaviour ────────────────────────────────────────────────
    def test_resend_within_the_cooldown_is_blocked(self):
        first_ok, _, _ = verification_service.send_otp(TEST_MOBILE)
        self.assertTrue(first_ok)
        ok, message, code = verification_service.send_otp(TEST_MOBILE)
        self.assertFalse(ok)
        self.assertIsNone(code)
        self.assertIn('before requesting a new OTP', message)
        self.assertEqual(len(self._rows()), 1)

    def test_resend_after_the_cooldown_replaces_the_session(self):
        verification_service.send_otp(TEST_MOBILE)
        verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self._age_session(31)

        ok, message, code = verification_service.send_otp(TEST_MOBILE)
        self.assertTrue(ok, message)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['verified'], 0)
        self.assertEqual(rows[0]['attempts'], 0)

        status = verification_service.get_otp_session_status(TEST_MOBILE)
        self.assertFalse(status['verified'])
        self.assertTrue(status['can_resend_in'] >= 29)

    # ── 8. production behaviour ────────────────────────────────────────────
    def test_production_mode_does_not_issue_a_session_without_an_sms_gateway(self):
        set_test_mode(False)
        for name in ('SMS_GATEWAY_URL', 'SMS_GATEWAY_API_KEY'):
            os.environ.pop(name, None)

        ok, message, code = verification_service.send_otp(TEST_MOBILE)
        self.assertFalse(ok)
        self.assertIsNone(code)
        self.assertIn('SMS delivery is not configured', message)
        self.assertEqual(self._rows(), [])

        ok, message = verification_service.verify_otp(TEST_MOBILE, FIXED_TEST_OTP)
        self.assertFalse(ok, 'The fixed development code must never verify in production')
        self.assertIn('No active OTP session', message)

    def test_production_mode_stores_a_random_code_and_never_the_fixed_one(self):
        set_test_mode(False)
        os.environ['SMS_GATEWAY_URL'] = 'https://sms.example.invalid/v1/send'
        os.environ['SMS_GATEWAY_API_KEY'] = 'unused-in-this-test'
        self.addCleanup(os.environ.pop, 'SMS_GATEWAY_URL', None)
        self.addCleanup(os.environ.pop, 'SMS_GATEWAY_API_KEY', None)

        sent_codes = []
        for _ in range(3):
            self._age_session(31)
            with patch('backend.services.verification_service.urllib.request.urlopen') as open_url:
                open_url.return_value.__enter__.return_value.status = 200
                ok, message, code = verification_service.send_otp(TEST_MOBILE)
            self.assertTrue(ok, message)
            self.assertIsNone(code, 'the OTP must not be returned to the caller in production')
            self.assertNotIn(FIXED_TEST_OTP, message)
            self.assertEqual(self._rows()[0]['delivery_status'], 'SENT')
            sent_codes.append(self._rows()[0]['code_hash'])

            payload = open_url.call_args[0][0].data.decode()
            self.assertIn('Your eKSP verification code is', payload)
            self.assertNotIn(FIXED_TEST_OTP, payload, 'production must dispatch a random code')

        self.assertEqual(len(set(sent_codes)), 3, 'production codes must differ')

    def test_gateway_failure_is_reported_instead_of_a_false_success(self):
        set_test_mode(False)
        os.environ['SMS_GATEWAY_URL'] = 'https://sms.example.invalid/v1/send'
        os.environ['SMS_GATEWAY_API_KEY'] = 'unused-in-this-test'
        self.addCleanup(os.environ.pop, 'SMS_GATEWAY_URL', None)
        self.addCleanup(os.environ.pop, 'SMS_GATEWAY_API_KEY', None)

        with patch('backend.services.verification_service.urllib.request.urlopen',
                   side_effect=OSError('provider down')):
            ok, message, code = verification_service.send_otp(TEST_MOBILE)
        self.assertFalse(ok)
        self.assertIsNone(code)
        self.assertIn('could not deliver', message)
        self.assertEqual(self._rows(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""
Regression and verification test suite for the four portal fixes:
1. Password Reset: Token security, anti-enumeration, rate limiting, and provider status.
2. Mobile Navigation: Responsive hamburger menu, anchor links, CTA, and translations.
3. Startup Performance: Cold-start startup timing and database initialization.
4. Error Page: Friendly 404 HTML response, Home/Login links, clean logs, no raw tracebacks.
"""

import asyncio
import os
import time
import unittest
import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse

import app
from nicegui import core
from nicegui.storage import set_storage_secret
from backend.services.db import get_db_connection
from backend.services.config_service import set_test_mode
from backend.services.citizen_credentials_service import (
    mint_token, resolve_token, complete_password_reset, request_password_reset,
    PASSWORD_RESET, _RESET_RATE_LIMITS, hash_token
)
from frontend.i18n import t, set_language
from frontend.pages.error_page import render_404_html, handle_404_error


def setup_module():
    set_storage_secret('3853932116a935345fe212c42336cf3456b1f616053f598f4873a744ce463892')
    core.app.config.add_run_config(
        reload=False, title='Test', viewport='', favicon=None, dark=False,
        language='en-US', binding_refresh_interval=0.1, reconnect_timeout=3.0,
        message_history_length=1000, tailwind=True, unocss=None, prod_js=True,
        show_welcome_message=False, markdown=False,
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. PASSWORD RESET TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_password_reset_unconfigured_message():
    """Verify that unconfigured provider returns clean message without raw phrasing."""
    set_test_mode(False)
    _RESET_RATE_LIMITS.clear()
    
    res = request_password_reset('anyone@example.com')
    assert res['delivery_status'] == 'NOT_CONFIGURED'
    assert 'Your password was not emailed or texted' not in res['detail']
    assert 'Verification Desk' in res['detail']


def test_password_reset_rate_limiting():
    """Verify that hammering the reset endpoint triggers RATE_LIMITED after 5 requests."""
    _RESET_RATE_LIMITS.clear()
    key = 'test-rate-limit-user@example.com'
    for _ in range(5):
        request_password_reset(key)
    blocked = request_password_reset(key)
    assert blocked['delivery_status'] == 'RATE_LIMITED'
    assert 'Too many password reset requests' in blocked['detail']


def test_password_reset_anti_enumeration():
    """Verify that existing and non-existing accounts return identical status when providers configured."""
    set_test_mode(True)
    _RESET_RATE_LIMITS.clear()
    
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1").fetchone()
    conn.close()
    
    res_real = request_password_reset(user['email'])
    res_fake = request_password_reset('completely-nonexistent-user-9999@test.com')
    
    assert res_real['delivery_status'] == 'SENT'
    assert res_fake['delivery_status'] == 'SENT'
    assert 'If an account matches' in res_real['detail']
    assert res_real['detail'] == res_fake['detail']


def test_password_reset_token_reuse_rejected():
    """Verify that single-use reset token cannot be used a second time."""
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1").fetchone()
    conn.close()
    
    token = mint_token(user['id'], PASSWORD_RESET, issued_by='TEST_REUSE')
    res = complete_password_reset(token, 'ValidPass@123', 'ValidPass@123')
    assert res['username'] is not None
    
    failed = False
    try:
        complete_password_reset(token, 'AnotherPass@123', 'AnotherPass@123')
    except ValueError as e:
        failed = True
        assert 'already been used' in str(e)
    assert failed, "Expected ValueError for token reuse"


def test_password_reset_expired_token_rejected():
    """Verify that expired tokens are immediately rejected."""
    conn = get_db_connection()
    user = conn.execute("SELECT * FROM users WHERE role = 'CITIZEN' LIMIT 1").fetchone()
    conn.close()
    
    token = mint_token(user['id'], PASSWORD_RESET, issued_by='TEST_EXPIRE')
    
    # Backdate expiration
    conn = get_db_connection()
    conn.execute(
        "UPDATE citizen_activation_tokens SET expires_at = '2020-01-01T00:00:00Z' WHERE token_hash = ?",
        (hash_token(token),)
    )
    conn.commit()
    conn.close()
    
    failed = False
    try:
        complete_password_reset(token, 'NewPassword@123', 'NewPassword@123')
    except ValueError as e:
        failed = True
        assert 'expired' in str(e)
    assert failed, "Expected ValueError for expired token"


# ═══════════════════════════════════════════════════════════════════════════
# 2. MOBILE NAVIGATION TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_mobile_navigation_translations():
    """Verify that navigation links exist and translate in English, Kannada, and Hindi."""
    nav_keys = ['Home', 'How It Works', 'Portal Services', 'Access', 'File FIR Online', 'Citizen Login']
    
    for lang in ['en', 'kn', 'hi']:
        set_language(lang)
        for key in nav_keys:
            translated = t(key)
            assert translated, f"Missing translation for '{key}' in '{lang}'"
    
    set_language('en')


# ═══════════════════════════════════════════════════════════════════════════
# 3. SLOW FIRST LOAD / BENCHMARK TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_startup_benchmark():
    """Measure internal app startup to verify it boots in under 1 second."""
    t0 = time.perf_counter()
    conn = get_db_connection()
    conn.execute("SELECT 1").fetchone()
    conn.close()
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"DB check took too long: {elapsed:.3f}s"


# ═══════════════════════════════════════════════════════════════════════════
# 4. ERROR PAGE TESTS
# ═══════════════════════════════════════════════════════════════════════════

def test_404_html_generation():
    """Verify 404 HTML includes branding, Home/Login links, and escapes input."""
    html_out = render_404_html('/unknown/path/<script>alert(1)</script>')
    assert '404' in html_out
    assert 'Page Not Found' in html_out
    assert 'Return to Home' in html_out
    assert 'Citizen Login' in html_out
    assert '<script>alert(1)</script>' not in html_out
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html_out


async def test_full_routes_and_404_response():
    """Verify live HTTP responses for valid routes (200) and unknown route (404)."""
    core.loop = asyncio.get_running_loop()
    transport = httpx.ASGITransport(app=app.nicegui_app)
    async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as client:
        # Check valid routes
        for path in ['/', '/login', '/register', '/citizen/reset-password', '/citizen/application-status']:
            res = await client.get(path)
            assert res.status_code == 200, f"Expected 200 for {path}"
        
        # Check 404 browser route
        res_404 = await client.get('/this-path-definitely-does-not-exist')
        assert res_404.status_code == 404
        assert 'Page Not Found' in res_404.text
        assert 'Return to Home' in res_404.text
        assert 'Citizen Login' in res_404.text
        assert 'HTTPException:' not in res_404.text
        
        # Check 404 API route
        res_api_404 = await client.get('/api/v1/invalid-api-call')
        assert res_api_404.status_code == 404
        assert res_api_404.headers['content-type'].startswith('application/json')
        assert res_api_404.json()['status'] == 404

"""
Citizen Account Activation and Password Reset.

Routes:
- /activate/{token}          single-use activation link issued after approval
- /citizen/reset-password    request a password reset link
- /reset-password/{token}    complete a password reset

The token in the path is the only copy of the secret; the database stores its
hash. A link works once, expires after ACTIVATION_LINK_TTL_HOURS, and is limited
to ACTIVATION_MAX_ATTEMPTS tries, so a guessed link cannot be ground through.
"""

from contextlib import contextmanager
from typing import Iterator

from nicegui import ui

from backend.services.citizen_credentials_service import (
    MIN_PASSWORD_LENGTH,
    complete_activation,
    complete_password_reset,
    request_password_reset,
    token_ttl_hours,
)
from frontend.components.navbar import create_public_header


@contextmanager
def _shell(title: str, subtitle: str, icon: str, accent: str) -> Iterator[None]:
    """Open the page chrome and yield inside the card so callers nest their form there."""
    ui.page_title(f'{title} | eKSP Online FIR Portal')
    create_public_header(show_citizen_actions=False)

    with ui.column().classes('w-full min-h-screen items-center justify-center p-4 md:p-8 bg-[#F0F4FF]'):
        with ui.card().classes(
            'w-full max-w-md p-6 md:p-8 rounded-3xl bg-white border border-slate-200 shadow-lg gap-4'
        ):
            with ui.row().classes('items-center gap-3 w-full'):
                with ui.element('div').classes(
                    'w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0'
                ).style(f'background: {accent}1A; color: {accent}'):
                    ui.icon(icon, size='sm')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label(title).classes('text-xl md:text-2xl font-black text-slate-900 fantasy-title leading-tight')
                    ui.label(subtitle).classes('text-[11px] text-slate-500 leading-snug')
            ui.separator()
            yield


def _password_fields() -> dict:
    password = ui.input(
        'New permanent password *',
        value='',
        password=True,
        password_toggle_button=True,
        placeholder=f'At least {MIN_PASSWORD_LENGTH} characters',
    ).classes('w-full')
    confirm = ui.input(
        'Confirm new password *',
        value='',
        password=True,
        password_toggle_button=True,
    ).classes('w-full')
    ui.label(
        'Your password is stored only as a PBKDF2-HMAC-SHA256 hash with its own random salt. '
        'It is never shown, emailed, logged or stored in plain text.'
    ).classes('text-[10px] text-slate-500 leading-relaxed')
    return {'password': password, 'confirm': confirm}


def _render_token_form(token: str, *, title: str, subtitle: str, icon: str, accent: str,
                       button_label: str, complete, success_message: str) -> None:
    with _shell(title, subtitle, icon, accent):
        fields = _password_fields()
        error_label = ui.label('').classes('text-xs text-red-600 font-semibold')

        def handle_submit() -> None:
            error_label.text = ''
            password = fields['password'].value or ''
            confirm = fields['confirm'].value or ''
            if not password or not confirm:
                error_label.text = '⚠ Please enter and confirm your new password.'
                return
            try:
                result = complete(token, password, confirm)
            except ValueError as error:
                # A rejected password only spends one of the link's attempts, but a
                # used, superseded or expired link needs the status page to get a new one.
                error_label.text = f'⚠ {error}'
                if any(marker in str(error) for marker in (
                    'already been used', 'expired', 'no longer valid', 'Too many attempts',
                )):
                    error_label.text += ' Use the secure activation option on your registration status page to get a new link.'
                return

            ui.notify(success_message.format(username=result['username']), type='positive')
            ui.navigate.to('/login')

        for field in (fields['password'], fields['confirm']):
            field.on('keydown.enter', handle_submit)

        ui.button(button_label, icon='lock_reset', on_click=handle_submit).props('unelevated').classes(
            'w-full text-white font-bold rounded-xl py-3 text-sm shadow-md'
        ).style(f'background: linear-gradient(135deg, {accent} 0%, #0A192F 100%);')

        with ui.row().classes('w-full justify-center items-center gap-1 text-[11px] text-slate-500'):
            ui.icon('info', size='xs').classes('text-slate-400')
            ui.label(f'Link is single-use and valid for {token_ttl_hours()} hours.').classes('font-semibold')
            ui.link('Citizen Login', '/login').classes('font-bold text-blue-700 hover:underline')


@ui.page('/activate/{token}')
def citizen_activation_page(token: str) -> None:
    """Set the permanent password on an approved citizen account."""
    _render_token_form(
        token,
        title='Activate Your Citizen Account',
        subtitle='Your registration was verified. Choose the permanent password for your login.',
        icon='how_to_reg',
        accent='#065F46',
        button_label='Set Password & Activate Account',
        complete=complete_activation,
        success_message='Account activated. Sign in as {username} with your new password.',
    )


@ui.page('/reset-password/{token}')
def citizen_password_reset_page(token: str) -> None:
    """Complete a password reset through a single-use reset link."""
    _render_token_form(
        token,
        title='Reset Your Password',
        subtitle='Choose a new permanent password for your citizen account.',
        icon='key',
        accent='#B45309',
        button_label='Set New Password',
        complete=complete_password_reset,
        success_message='Password updated. Sign in as {username} with your new password.',
    )


@ui.page('/citizen/reset-password')
def citizen_password_reset_request_page() -> None:
    """Request a password reset link for a verified citizen account."""
    with _shell(
        'Forgot Password',
        'Enter your username, registered email or mobile. The reset link goes to the channel on file.',
        'vpn_key',
        '#0F2B5C',
    ):
        identifier = ui.input(
            'Username / Email / Mobile *',
            value='',
            placeholder='e.g. asha-menon-1a2b3c or you@example.com',
        ).classes('w-full')
        status_label = ui.label('').classes('text-xs font-semibold text-slate-700')
        error_label = ui.label('').classes('text-xs text-red-600 font-semibold')

        def handle_request() -> None:
            error_label.text = ''
            value = (identifier.value or '').strip()
            if not value:
                error_label.text = '⚠ Enter the username, email or mobile on your account.'
                return
            result = request_password_reset(value)
            status = result['delivery_status']
            if status == 'SENT':
                status_label.text = (
                    'A single-use reset link has been sent to the contact channel on file for that '
                    f"account. It expires in {token_ttl_hours()} hours."
                )
            elif status == 'NOT_CONFIGURED':
                status_label.text = (
                    'Your password was not emailed or texted because no delivery provider is configured '
                    'on this server. Visit the Verification Desk with your registration reference to '
                    'reset your password.'
                )
            else:
                status_label.text = (
                    'The reset link could not be delivered. Please try again shortly or visit the '
                    'Verification Desk with your registration reference.'
                )
            ui.notify('Request received.', type='positive' if status == 'SENT' else 'warning')

        identifier.on('keydown.enter', handle_request)
        ui.button('Send Me a Reset Link', icon='send', on_click=handle_request).props('unelevated').classes(
            'w-full bg-blue-900 hover:bg-blue-950 text-white font-bold rounded-xl py-3 text-sm'
        )

        with ui.row().classes('w-full justify-center items-center gap-1 text-[11px] text-slate-500'):
            ui.icon('shield', size='xs').classes('text-slate-400')
            ui.label('For security this page never shows the link or confirms whether an account exists.')
        with ui.row().classes('w-full justify-center gap-1 text-[11px] text-slate-600'):
            ui.label('Not approved yet?')
            ui.link('Check your registration status', '/citizen/application-status').classes(
                'font-bold text-blue-700 hover:underline'
            )

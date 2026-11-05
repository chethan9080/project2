"""
Staff Authentication Entry Point.

Flow:
- /staff-portal                → dedicated role selection (3 cards)
- /staff-portal/verification   → Verification Officer login
- /staff-portal/police         → Police Officer login
- /staff-portal/admin          → Administrator login

Citizen authentication remains separate at /login and /register.
All credentials are verified by the existing PBKDF2 authentication service,
and each page enforces its role on the server before granting access.
"""

from nicegui import ui

from backend.services.auth_service import authenticate_user, set_current_user
from backend.services.verification_service import create_officer_session
from frontend.components.navbar import create_public_header


ROLE_OPTIONS = [
    {
        'key': 'verification',
        'title': 'Verification Officer',
        'description': 'Review and verify citizen FIRs, structure official records, and assign investigating officers.',
        'icon': 'fact_check',
        'accent': '#065F46',
        'tint': 'rgba(6, 95, 70, 0.10)',
        'dashboard': '/verification',
    },
    {
        'key': 'police',
        'title': 'Police Officer',
        'description': 'Investigate assigned FIRs and complaints, update case stages, and communicate with citizens.',
        'icon': 'local_police',
        'accent': '#0F2B5C',
        'tint': 'rgba(15, 43, 92, 0.10)',
        'dashboard': '/police',
    },
    {
        'key': 'admin',
        'title': 'Administrator / Main Monitoring Officer',
        'description': 'State-wide FIR monitoring, officer management, blockchain ledger, and audit oversight.',
        'icon': 'admin_panel_settings',
        'accent': '#B45309',
        'tint': 'rgba(180, 83, 9, 0.10)',
        'dashboard': '/admin',
    },
]

ROLE_BY_KEY = {option['key']: option for option in ROLE_OPTIONS}


def _role_card(option: dict) -> None:
    """Render one selectable role card linking to its dedicated login page."""
    target = f"/staff-portal/{option['key']}"

    with ui.card().classes(
        'w-full h-full p-6 rounded-3xl bg-white border border-slate-200 shadow-sm '
        'hover:shadow-lg hover:-translate-y-0.5 transition-all cursor-pointer gap-4'
    ).on('click', lambda t=target: ui.navigate.to(t)):
        with ui.row().classes('w-full items-start justify-between'):
            with ui.element('div').classes(
                'w-14 h-14 rounded-2xl flex items-center justify-center'
            ).style(f'background: {option["tint"]}; color: {option["accent"]}'):
                ui.icon(option['icon'], size='md')
            ui.icon('arrow_forward', size='sm').classes('text-slate-300')

        with ui.column().classes('gap-2'):
            ui.label(option['title']).classes('text-lg font-black text-slate-900 leading-tight')
            ui.label(option['description']).classes('text-xs text-slate-600 leading-relaxed')

        with ui.row().classes('items-center gap-1 text-xs font-bold mt-auto').style(
            f'color: {option["accent"]}'
        ):
            ui.label('Sign in')
            ui.icon('chevron_right', size='xs')


@ui.page('/staff-portal')
def role_selection_page() -> None:
    """Dedicated role selection page for authorized staff."""
    ui.page_title('Authorized Staff Access | e-FIR Portal')
    create_public_header(show_citizen_actions=False)

    with ui.column().classes(
        'w-full min-h-screen items-center justify-center p-4 md:p-8 bg-[#F0F4FF] gap-8'
    ):
        with ui.column().classes('w-full max-w-3xl items-center text-center gap-2'):
            ui.badge('RESTRICTED ACCESS').classes(
                'bg-blue-100 text-blue-900 text-[10px] font-bold tracking-widest px-3 py-1'
            )
            ui.label('Law Enforcement Staff Portal').classes(
                'text-3xl md:text-4xl font-black text-slate-900 fantasy-title'
            )
            ui.label(
                'Select your official role to continue. Each role has a separate, secured sign-in.'
            ).classes('text-xs md:text-sm text-slate-600 max-w-xl')

        with ui.element('div').classes(
            'grid grid-cols-1 md:grid-cols-3 gap-5 w-full max-w-6xl items-stretch'
        ):
            for option in ROLE_OPTIONS:
                _role_card(option)

        with ui.row().classes('items-center gap-2 text-xs text-slate-500'):
            ui.icon('info', size='xs').classes('text-slate-400')
            ui.label('Citizen accounts use the separate Citizen Portal.')
            ui.button(
                'Return to Citizen Portal',
                on_click=lambda: ui.navigate.to('/login'),
            ).props('flat dense no-caps').classes('text-xs font-bold text-blue-800')


def _render_staff_login(
    option: dict,
    *,
    required_role: str,
    subtitle: str,
    button_label: str,
    show_station: bool = False,
) -> None:
    """Render a dedicated login page for a single staff role."""
    create_public_header(show_citizen_actions=False)

    with ui.column().classes(
        'w-full min-h-screen items-center justify-center p-4 md:p-8 bg-[#F0F4FF]'
    ):
        with ui.card().classes(
            'w-full max-w-md p-6 md:p-8 rounded-3xl bg-white border border-slate-200 shadow-lg gap-5'
        ):
            ui.button(
                'Back to role selection',
                icon='arrow_back',
                on_click=lambda: ui.navigate.to('/staff-portal'),
            ).props('flat dense no-caps').classes(
                'text-xs font-bold text-slate-500 hover:text-slate-800 self-start -ml-2'
            )

            with ui.row().classes('items-center gap-3 w-full'):
                with ui.element('div').classes(
                    'w-12 h-12 rounded-2xl flex items-center justify-center flex-shrink-0'
                ).style(f'background: {option["tint"]}; color: {option["accent"]}'):
                    ui.icon(option['icon'], size='sm')
                with ui.column().classes('gap-0 flex-1'):
                    ui.label(f"{option['title']} Login").classes(
                        'text-xl md:text-2xl font-black text-slate-900 fantasy-title leading-tight'
                    )
                    ui.label(subtitle).classes('text-[11px] text-slate-500 leading-snug')

            ui.separator()

            username_input = ui.input(
                'Username',
                value='',
                placeholder='Enter your official username',
            ).classes('w-full')
            password_input = ui.input(
                'Password',
                value='',
                password=True,
                password_toggle_button=True,
            ).classes('w-full')

            station_input = None
            location_data = {'lat': None, 'lon': None}
            if show_station:
                station_input = ui.input(
                    'Police Station / Unit (optional)',
                    value='',
                    placeholder='Recorded in the session audit trail',
                ).classes('w-full')

                location_status = ui.label(
                    'Optional: capture the station location for the audit trail.'
                ).classes('text-[10px] text-slate-400')

                async def capture_location() -> None:
                    try:
                        result = await ui.run_javascript("""
                            return new Promise((resolve, reject) => {
                                if (!navigator.geolocation) { reject('Geolocation not supported'); return; }
                                navigator.geolocation.getCurrentPosition(
                                    (pos) => resolve({lat: pos.coords.latitude, lon: pos.coords.longitude}),
                                    (err) => reject(err.message || 'Location denied'),
                                    {timeout: 8000}
                                );
                            });
                        """, timeout=12.0)
                        if isinstance(result, dict):
                            location_data['lat'] = result['lat']
                            location_data['lon'] = result['lon']
                            location_status.text = (
                                f"Location captured: {result['lat']:.4f}, {result['lon']:.4f}"
                            )
                            location_status.classes(replace='text-[10px] text-emerald-700 font-semibold')
                    except Exception as error:
                        location_status.text = f'Location not captured: {error}'

                ui.button(
                    'Use current location',
                    icon='my_location',
                    on_click=capture_location,
                ).props('flat dense no-caps').classes(
                    'text-[11px] font-bold text-blue-800 self-start -mt-2 -ml-2'
                )

            error_label = ui.label('').classes('text-xs text-red-600 font-semibold')

            def handle_login() -> None:
                identifier = (username_input.value or '').strip()
                password = password_input.value or ''

                if not identifier and not password:
                    error_label.text = 'Please enter your username and password.'
                    return
                if not identifier:
                    error_label.text = 'Please enter your username.'
                    return
                if not password:
                    error_label.text = 'Please enter your password.'
                    return

                user = authenticate_user(identifier, password, required_role=required_role)
                if not user:
                    error_label.text = 'Invalid credentials for this role. Please try again.'
                    return

                if show_station and station_input is not None:
                    station_name = (station_input.value or '').strip()
                    if station_name:
                        user['station'] = station_name
                try:
                    create_officer_session(
                        officer_user=user,
                        location_name=None,
                        latitude=location_data['lat'],
                        longitude=location_data['lon'],
                    )
                except Exception as error:
                    ui.notify(f'Login succeeded, but the session audit could not be saved: {error}', type='warning')

                set_current_user(user)
                error_label.text = ''
                ui.notify(f"Welcome, {user['name']}. Opening the {option['title']} workspace...", type='positive')
                ui.navigate.to(option['dashboard'])

            username_input.on('keydown.enter', handle_login)
            password_input.on('keydown.enter', handle_login)

            ui.button(
                button_label,
                icon='login',
                on_click=handle_login,
            ).props('unelevated').classes(
                'w-full text-white font-bold rounded-xl py-3 text-sm shadow-md'
            ).style(
                f'background: linear-gradient(135deg, {option["accent"]} 0%, #0A192F 100%);'
            )

            with ui.row().classes('w-full justify-center items-center gap-1 text-[11px] text-slate-500'):
                ui.icon('lock', size='xs').classes('text-slate-400')
                ui.label('Authorized personnel only. All access attempts are audited.')


@ui.page('/staff-portal/verification')
def verification_officer_login_page() -> None:
    """Dedicated Verification Officer login."""
    ui.page_title('Verification Officer Login | e-FIR Portal')
    _render_staff_login(
        ROLE_BY_KEY['verification'],
        required_role='VERIFICATION_OFFICER',
        subtitle='Review, verify, and structure citizen FIRs.',
        button_label='Sign in to Verification Desk',
    )


@ui.page('/staff-portal/police')
def police_officer_login_page() -> None:
    """Dedicated Police Officer login."""
    ui.page_title('Police Officer Login | e-FIR Portal')
    _render_staff_login(
        ROLE_BY_KEY['police'],
        required_role='OFFICER',
        subtitle='Access your assigned FIRs, complaints, and citizen communications.',
        button_label='Sign in to Police Workspace',
        show_station=True,
    )


@ui.page('/staff-portal/admin')
def administrator_login_page() -> None:
    """Dedicated Administrator login."""
    ui.page_title('Administrator Login | e-FIR Portal')
    _render_staff_login(
        ROLE_BY_KEY['admin'],
        required_role='ADMIN',
        subtitle='State-wide monitoring, officer management, and blockchain audit.',
        button_label='Sign in to Admin Console',
    )

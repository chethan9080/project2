"""
Citizen Login Page with Secure Authentication.
"""

from nicegui import ui
from frontend.components.navbar import create_public_header
from backend.services.auth_service import (
    authenticate_user,
    citizen_login_denial_reason,
    get_dev_auto_login_user,
    set_current_user,
)


@ui.page('/login')
def create_login_page() -> None:
    """Citizen login interface."""
    ui.page_title('Citizen Login | Online FIR Portal')
    create_public_header()

    with ui.column().classes('w-full min-h-screen items-center p-6 pt-10 bg-[#F8FAFC]'):
        with ui.card().classes('w-full max-w-lg p-8 rounded-3xl paper-card border border-slate-200 shadow-md bg-white'):
            # Header
            with ui.row().classes('items-center justify-between w-full mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('person', size='sm').classes('text-emerald-700')
                    ui.label('CITIZEN AUTHENTICATION').classes('font-bold text-xs text-emerald-800 tracking-widest')
                ui.badge('SECURE CITIZEN ACCESS').classes('bg-emerald-100 text-emerald-900 text-[10px] font-bold')

            ui.label('Citizen Login').classes('text-3xl font-black text-slate-900 fantasy-title')
            ui.label('Log in to file an online FIR, track status, view change history, and verify blockchain proofs.').classes('text-xs text-slate-600 mt-1')

            ui.separator().classes('my-4')

            # Credentials Form
            with ui.column().classes('w-full gap-4'):
                email_input = ui.input(
                    'Username / Email / Phone *',
                    value='',
                    placeholder='Your issued username, email or phone',
                ).classes('w-full')
                pass_input = ui.input('Password *', value='', password=True, password_toggle_button=True).classes('w-full')

                with ui.row().classes('w-full justify-end'):
                    ui.link('Forgot password?', '/citizen/reset-password').classes(
                        'text-[11px] font-bold text-blue-700 hover:underline'
                    )

                login_message = ui.label('').classes('text-red-600 text-xs font-semibold')
                status_link = ui.row().classes('w-full items-center gap-1.5 text-xs text-slate-600')

                def handle_login():
                    login_message.text = ''
                    status_link.set_visibility(False)
                    if not email_input.value or not pass_input.value:
                        ui.notify('Please provide both your account identifier and password.', type='warning')
                        return

                    user = authenticate_user(email_input.value, pass_input.value, required_role="CITIZEN")
                    if not user:
                        denial = citizen_login_denial_reason(email_input.value, pass_input.value)
                        if denial:
                            login_message.text = f'⚠ {denial}'
                            status_link.set_visibility(True)
                        else:
                            login_message.text = '⚠ Invalid username/email/phone or password.'
                        ui.notify(denial or 'Invalid username/email/phone or password.', type='negative')
                        return

                    set_current_user(user)
                    ui.notify(f"Welcome back, {user['name']}! Logging in...", type='positive')
                    ui.navigate.to('/citizen')

                with status_link:
                    ui.icon('fact_check', size='xs').classes('text-blue-700')
                    ui.label('Registration not approved yet?')
                    ui.link('Check application status →', '/citizen/application-status').classes(
                        'font-bold text-blue-700 hover:underline'
                    )
                # The whole row stays hidden until a verification-specific denial occurs.
                status_link.set_visibility(False)

                email_input.on('keydown.enter', handle_login)
                pass_input.on('keydown.enter', handle_login)

                ui.button('Sign In to Citizen Portal ✦', icon='login', on_click=handle_login).props(
                    'unelevated'
                ).classes('w-full bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl py-3.5 text-sm mt-2 shadow-md')

                dev_user = get_dev_auto_login_user()
                if dev_user:
                    def handle_dev_login():
                        set_current_user(dev_user)
                        ui.notify(f"TEST_MODE auto-login: {dev_user['name']}", type='info')
                        ui.navigate.to('/citizen')

                    ui.button(
                        f"TEST_MODE: Continue as {dev_user['name']}",
                        icon='developer_mode',
                        on_click=handle_dev_login,
                    ).props('outline no-caps').classes(
                        'w-full text-amber-800 border-amber-300 bg-amber-50 font-bold rounded-xl py-2.5 text-xs'
                    )
                    ui.label('Development shortcut only. Disabled when TEST_MODE is not 1.').classes(
                        'text-[10px] text-amber-700 text-center'
                    )

            # Registration helper link
            with ui.row().classes('w-full justify-center items-center text-xs text-slate-600 my-4 gap-1.5'):
                ui.label("New user or need an account?")
                ui.link('Create Citizen Account →', '/register').classes('font-bold text-emerald-700 hover:underline')

            ui.separator().classes('my-2')

            # =========================================================
            # POLICE / AUTHORIZED ACCESS SECTION (BOTTOM & SEPARATE)
            # =========================================================
            with ui.card().classes('w-full p-4 bg-slate-50 border border-slate-200/90 rounded-2xl mt-3'):
                with ui.row().classes('w-full items-center justify-between gap-2 mb-2'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('shield', size='xs').classes('text-blue-900')
                        ui.label('Police & Authorized Personnel Access').classes('font-bold text-xs text-blue-950')
                    ui.badge('RESTRICTED').classes('bg-blue-100 text-blue-900 text-[10px] font-bold')

                ui.label(
                    'Investigating officers, station supervisors, and administrative personnel must access the system via the authorized law enforcement gateway.'
                ).classes('text-[11px] text-slate-600 leading-relaxed mb-3')

                ui.button(
                    'Police / Authorized Login',
                    icon='local_police',
                    on_click=lambda: ui.navigate.to('/staff-portal')
                ).props('outline color=blue').classes(
                    'w-full bg-white hover:bg-blue-50 text-blue-900 border-blue-300 font-bold rounded-xl py-2.5 text-xs shadow-sm'
                )

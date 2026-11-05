"""
Unified Navigation Headers for Citizen, Police Officer, and Administrator Portals.
Includes centralized 3-language switcher (English, ಕನ್ನಡ, हिन्दी).
"""

from nicegui import ui, background_tasks
from frontend.i18n import set_language, get_language, t
from backend.services.auth_service import authenticate_user, get_current_user, set_current_user
from backend.services.notification_service import get_unread_count
from backend.services.realtime_events import subscribe, unsubscribe


def render_language_switcher() -> None:
    """Centralized 3-language switcher button group for English, Kannada, and Hindi."""
    current = get_language()
    languages = [
        ('en', 'English'),
        ('kn', 'ಕನ್ನಡ'),
        ('hi', 'हिन्दी'),
    ]
    with ui.row().classes('items-center gap-1 bg-slate-900/80 p-1 rounded-xl border border-amber-400/30 shadow-sm'):
        for code, label in languages:
            is_active = (current == code)
            ui.button(
                label,
                on_click=lambda c=code: set_language(c)
            ).props(
                'unelevated dense size=sm' if is_active else 'flat dense size=sm'
            ).classes(
                'px-2.5 py-1 text-xs font-bold rounded-lg transition-all ' +
                ('bg-amber-400 text-slate-950 shadow-md font-black' if is_active else 'text-slate-200 hover:text-white hover:bg-white/10')
            )


def create_public_header(show_language_switcher: bool = True, show_citizen_actions: bool = True) -> None:
    """Create the public navigation header for landing, login, and registration pages."""
    # Inject global CSS classes needed across all pages
    ui.add_head_html("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
    body { font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; }
    .fantasy-title { font-family: 'Georgia', 'Cinzel', serif; letter-spacing: -0.015em; }
    .paper-card {
        background: linear-gradient(135deg, #FFFDF7 0%, #F5EBE0 100%);
        border: 2px solid rgba(82, 121, 111, 0.22);
        box-shadow: 0 10px 30px rgba(45, 90, 63, 0.07);
        border-radius: 1.25rem;
        transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }
    .paper-card:hover { transform: translateY(-2px); box-shadow: 0 14px 36px rgba(45, 90, 63, 0.12); }
</style>
""", shared=True)
    with ui.header().classes(
        'w-full px-6 py-4 border-b'
    ).style(
        'background: linear-gradient(135deg, #0A192F 0%, #1B365D 100%); '
        'border-color: rgba(217, 119, 6, 0.3); '
        'box-shadow: 0 4px 20px rgba(10, 25, 47, 0.25);'
    ):
        with ui.row().classes('w-full max-w-7xl mx-auto items-center justify-between flex-wrap gap-4'):
            # Logo and title
            with ui.row().classes('items-center gap-3 cursor-pointer').on('click', lambda: ui.navigate.to('/')):
                ui.icon('gavel', size='md').classes('text-amber-400')
                with ui.column().classes('gap-0'):
                    ui.label(t('Digital FIR & Blockchain Audit Portal')).classes('text-xl font-bold text-white tracking-wide fantasy-title')
                    ui.label(t('Government of Karnataka · Law Enforcement & Citizen Services')).classes('text-[10px] text-amber-200 uppercase tracking-widest')

            # Navigation links for citizens (Primary) & Authorized Staff (Secondary)
            with ui.row().classes('gap-3 items-center flex-wrap'):
                ui.button(t('Home'), icon='home', on_click=lambda: ui.navigate.to('/')).props('flat color=white').classes('text-xs font-semibold text-white')

                if show_citizen_actions:
                    ui.button(t('File FIR Online'), icon='edit_document', on_click=lambda: ui.navigate.to('/citizen/submit')).props('unelevated').classes(
                        'bg-amber-500 hover:bg-amber-600 text-slate-950 font-bold rounded-xl px-4 py-2 text-xs shadow-md'
                    )
                    ui.button(t('Citizen Login'), icon='login', on_click=lambda: ui.navigate.to('/login')).props('outline color=white').classes(
                        'text-white border-white/60 hover:bg-white/10 rounded-xl px-3.5 py-1.5 text-xs font-bold'
                    )

                # Centralized 3-Language switcher
                if show_language_switcher:
                    render_language_switcher()

                # Subtle secondary link for staff
                if show_citizen_actions:
                    with ui.row().classes('items-center pl-2 ml-1 border-l border-white/20'):
                        ui.link(t('Authorized Staff →'), '/staff-portal').classes(
                            'text-[11px] text-amber-300/80 hover:text-amber-200 font-medium hover:underline tracking-wide'
                        )


def create_topbar(title: str = 'Online FIR Portal') -> None:
    """Create top navigation bar for authenticated portal pages."""
    user = get_current_user() or {}
    user_role = user.get("role", "CITIZEN")
    user_name = user.get("name", "User")

    role_colors = {
        "CITIZEN": ("#10B981", "Citizen"),
        "OFFICER": ("#3B82F6", "Police Officer"),
        "VERIFICATION_OFFICER": ("#10B981", "Verification Officer"),
        "ADMIN": ("#F59E0B", "Administrator")
    }
    badge_bg, role_label = role_colors.get(user_role, ("#64748B", user_role))

    with ui.header().classes(
        'w-full text-white px-6 py-3 shadow-md border-b'
    ).style(
        'background: linear-gradient(135deg, #0A192F 0%, #1B365D 100%); '
        'border-color: rgba(217, 119, 6, 0.3);'
    ):
        with ui.row().classes('w-full max-w-7xl mx-auto items-center justify-between flex-wrap gap-4'):
            # Brand
            with ui.row().classes('items-center gap-3 cursor-pointer').on('click', lambda: ui.navigate.to('/')):
                ui.icon('security', size='md').classes('text-amber-400')
                with ui.column().classes('gap-0'):
                    ui.label(t(title)).classes('text-lg font-bold text-white fantasy-title')
                    platform_tagline = 'Secure Government FIR Portal' if user_role == 'CITIZEN' else 'Tamper-Evident Blockchain Proof Platform'
                    ui.label(t(platform_tagline)).classes('text-[10px] text-amber-200 tracking-wider')

            # User Profile, Language Switcher & Action Pills
            with ui.row().classes('items-center gap-3 flex-wrap'):
                # Role pill
                with ui.row().classes('items-center gap-1.5 px-3 py-1 rounded-full bg-slate-800/80 border border-slate-600 text-xs'):
                    ui.element('div').classes('w-2 h-2 rounded-full').style(f'background: {badge_bg}')
                    ui.label(f"{user_name} · {t(role_label)}").classes('font-bold text-slate-200')

                # Centralized 3-Language switcher on all topbars
                render_language_switcher()

                # Notification Bell with Badge
                if user_role == "CITIZEN":
                    notif_path = "/citizen/notifications"
                elif user_role == "VERIFICATION_OFFICER":
                    notif_path = "/verification/notifications"
                elif user_role == "ADMIN":
                    notif_path = "/admin/audit-logs"
                else:
                    notif_path = "/police/notifications"
                with ui.button(icon='notifications', on_click=lambda p=notif_path: ui.navigate.to(p)).props('flat round color=white size=sm').classes('relative text-white'):
                    @ui.refreshable
                    def unread_badge() -> None:
                        count = get_unread_count(user.get('id', '')) if user.get('id') else 0
                        if count > 0:
                            ui.badge(str(count)).classes('bg-red-500 text-white text-[10px] font-bold absolute -top-1 -right-1')

                    unread_badge()

                    if user.get('id'):
                        client = ui.context.client
                        event_queue = subscribe()

                        async def watch_notifications() -> None:
                            while True:
                                event = await event_queue.get()
                                if event.get('type') not in ('NOTIFICATION_CREATED', 'NOTIFICATION_UPDATED'):
                                    continue
                                if event.get('user_id') != user.get('id'):
                                    continue
                                with client:
                                    unread_badge.refresh()

                        event_listener = background_tasks.create(
                            watch_notifications(), name='topbar-notification-badge'
                        )

                        def stop_badge_listener() -> None:
                            unsubscribe(event_queue)
                            event_listener.cancel()

                        client.on_disconnect(stop_badge_listener)

                def handle_logout():
                    set_current_user(None)
                    ui.navigate.to('/login' if user_role == 'CITIZEN' else '/staff-portal')

                ui.button('Logout', icon='logout', on_click=handle_logout).props('flat dense size=sm color=red').classes(
                    'text-rose-300 hover:text-white text-xs font-semibold ml-2'
                )

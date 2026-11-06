"""
Sidebar Navigation System for Citizen, Police, and Admin Portals.
"""

from typing import Any, Optional
from weakref import WeakValueDictionary

from nicegui import ui, context
from backend.services.auth_service import get_current_user, set_current_user
# Ranks that are considered "authorized" for tampering audit access
from backend.services.audit_service import AUTHORIZED_OFFICER_RANKS

# The citizen drawer hides itself on compact screens, so the topbar menu button
# needs to find the drawer belonging to the client it is serving.
_ACTIVE_DRAWERS: WeakValueDictionary = WeakValueDictionary()


def get_active_drawer(client_id: str) -> Optional[Any]:
    """Return the responsive citizen drawer for this client, if one is open."""
    return _ACTIVE_DRAWERS.get(client_id)

PORTAL_LINKS = {
    'citizen': [
        ('Dashboard', 'dashboard', '/citizen'),
        ('File an FIR', 'add_circle', '/citizen/submit'),
        ('My Complaints', 'report_problem', '/citizen/complaints'),
        ('FIR Tracking', 'track_changes', '/citizen/tracking'),
        ('Chat with Officer', 'chat', '/citizen/chat'),
        ('Notifications', 'notifications', '/citizen/notifications'),
        ('Profile', 'person', '/citizen/profile'),
        ('Logout', 'logout', '/login')
    ],
    'police': [
        ('Dashboard', 'dashboard', '/police'),
        ('Assigned Complaints', 'report_problem', '/police/complaints'),
        ('My Assigned Cases', 'folder_special', '/police/firs'),
        ('Chat with Citizens', 'forum', '/police/chat'),
        ('Notifications', 'notifications', '/police/notifications'),
        ('Profile', 'person', '/police/profile'),
        ('Logout', 'logout', '/staff-portal')
    ],
    'verification': [
        ('Dashboard', 'dashboard', '/verification'),
        ('Citizen Verification', 'how_to_reg', '/verification/citizens'),
        ('Verify Queries', 'fact_check', '/verification/complaints'),
        ('Verify Your FIR', 'description', '/verification/firs'),
        ('Verification History', 'history', '/verification/history'),
        ('Notifications', 'notifications', '/verification/notifications'),
        ('Profile', 'person', '/verification/profile'),
        ('Logout', 'logout', '/staff-portal')
    ],
    'admin': [
        ('Dashboard', 'dashboard', '/admin'),
        ('Authorized Officers', 'badge', '/admin/officers'),
        ('Blockchain Ledger', 'toll', '/admin/blockchain'),
        ('Case Assignments', 'assignment_ind', '/admin/assignments'),
        ('Investigation Monitor', 'monitoring', '/admin/investigations'),
        ('System Audit Logs', 'history', '/admin/audit-logs'),
        ('FIR Tampering & Audit', 'policy', '/admin/tampering-audit'),
        ('Profile', 'person', '/admin/profile'),
        ('Logout', 'logout', '/staff-portal')
    ],
}

PORTAL_THEME_COLORS = {
    'citizen': '#1B365D',
    'police': '#0F2B5C',
    'verification': '#065F46',
    'admin': '#312E81',
}


def _is_authorized_officer(user: dict) -> bool:
    """Check if the officer has a senior rank."""
    if not user:
        return False
    if user.get('role') == 'ADMIN':
        return True
    rank = (user.get('rank') or '').lower()
    return any(r.lower() in rank for r in AUTHORIZED_OFFICER_RANKS)


def create_sidebar(portal: str, active_path: str) -> None:
    """Create navigation drawer matching selected role."""
    user = get_current_user() or {}
    links = list(PORTAL_LINKS.get(portal, PORTAL_LINKS['citizen']))
    portal_color = PORTAL_THEME_COLORS.get(portal, '#1B365D')
    # Only the citizen portal collapses the drawer on compact screens; the
    # topbar menu button needs a handle on it to reopen it.
    responsive = portal == 'citizen'

    with ui.left_drawer(value=None if responsive else True, fixed=False).classes(
        'border-r flex flex-col h-screen'
    ).style(
        'background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%); '
        'border-color: rgba(203, 213, 225, 0.8);'
    ) as drawer:
        if responsive:
            _ACTIVE_DRAWERS[context.client.id] = drawer
        # Header banner
        with ui.element('div').classes('relative px-6 pt-6 pb-4 border-b border-slate-200'):
            ui.element('div').classes('absolute left-0 top-0 bottom-0 w-1.5 rounded-r-full').style(f'background: {portal_color}')
            ui.label(f'✦ {portal.title()} Portal').classes('text-xs font-bold tracking-widest text-slate-800 uppercase ml-3 fantasy-title')

        # Scrollable links
        with ui.scroll_area().classes('flex-1'):
            with ui.column().classes('gap-1 py-4 px-3'):
                for label, icon, path in links:
                    active = (path == active_path) or (path != f'/{portal}' and active_path.startswith(path))
                    if active:
                        _render_active_nav_item(label, icon, path, portal_color)
                    else:
                        _render_inactive_nav_item(label, icon, path, portal_color)

        # Footer
        with ui.element('div').classes('border-t border-slate-200 p-4 mt-auto bg-slate-50'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('verified_user', size='xs').style(f'color: {portal_color}')
                footer_label = 'Secure Government Portal' if portal == 'citizen' else 'Blockchain Proof Active'
                ui.label(footer_label).classes('text-xs text-slate-600 font-semibold')



def _handle_nav_click(destination: str, label: str) -> None:
    if label.strip().lower() == 'logout':
        set_current_user(None)
    ui.navigate.to(destination)


def _render_active_nav_item(label: str, icon: str, path: str, portal_color: str) -> None:
    """Render active navigation item with solid pill styling."""
    with ui.element('div').classes('mb-1 w-full'):
        ui.button(
            label,
            icon=icon,
            on_click=lambda destination=path, lbl=label: _handle_nav_click(destination, lbl)
        ).props('flat align=left').classes(
            'w-full justify-start px-4 py-2.5 rounded-xl text-white font-semibold transition-all shadow-sm text-xs'
        ).style(
            f'background: linear-gradient(135deg, {portal_color} 0%, #0A192F 100%);'
        )


def _render_inactive_nav_item(label: str, icon: str, path: str, portal_color: str) -> None:
    """Render inactive navigation item with hover effect."""
    with ui.element('div').classes('mb-1 w-full'):
        ui.button(
            label,
            icon=icon,
            on_click=lambda destination=path, lbl=label: _handle_nav_click(destination, lbl)
        ).props('flat align=left').classes(
            'w-full justify-start px-4 py-2.5 rounded-xl text-slate-700 font-medium transition-all text-xs hover:bg-slate-100'
        ).style(
            'background: transparent;'
        )

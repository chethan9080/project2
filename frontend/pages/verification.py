"""
Verification Officer Portal.

Routes:
- /verification                     live bureau dashboard (all figures from SQLite)
- /verification/citizens            citizen registration queue (see citizen_verification.py)
- /verification/complaints          "Verify Queries" complaint verification queue
- /verification/complaint/{id}      complaint review & verification decisions
- /verification/firs                "Verify Your FIR" — verified complaints + registered FIRs
- /verification/fir-register/{id}   FIR detail review, officer assignment, draft document, registration
- /verification/fir/{id}            FIR case file, officer reassignment, PDF document
- /verification/history             append-only verification history and audit
- /verification/notifications       notification center (per-item read state)
- /verification/profile             staff profile with permitted updates

Everything shown is read from the database. Status changes are persisted,
append-only audit events are recorded, the citizen is notified, and open
dashboards receive the change over the in-process websocket event bus.
"""
import base64
import json
from datetime import datetime

from nicegui import background_tasks, ui

from frontend.components.badges import fir_status_badge
from frontend.components.layout import portal_page
from backend.services.auth_service import (
    get_current_user,
    set_current_user,
    update_staff_profile,
)
from backend.services.complaint_evidence_service import evidence_bytes
from backend.services.complaint_service import COMPLAINT_CATEGORIES, assign_officer_to_complaint
from backend.services.complaint_verification_service import (
    FIR_DETAIL_LABELS,
    action_label,
    get_active_police_officers,
    get_complaint_for_verification,
    get_complaint_verification_events,
    get_complaints_ready_for_fir,
    get_dashboard_stats,
    get_officer_assignment_history,
    get_recent_activity,
    get_recent_assignments,
    get_verification_history,
    get_verification_queue,
    record_complaint_verification_action,
    update_fir_details_before_registration,
    verification_label,
)
from backend.services.fir_document_service import (
    generate_fir_pdf,
    get_current_document,
    list_documents,
    read_document_bytes,
    render_draft_document_for_complaint,
)
from backend.services.fir_service import (
    assign_officer_to_fir,
    create_fir_from_complaint,
    get_fir_by_id,
    get_firs,
    get_operational_case_timeline,
    log_officer_activity,
    reject_fir,
    update_fir,
    verify_fir,
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read,
)
from backend.services.realtime_events import subscribe, unsubscribe


COMPLAINT_STATUS_STYLES = {
    'SUBMITTED': 'bg-amber-100 text-amber-900 border-amber-300',
    'ASSIGNED': 'bg-sky-100 text-sky-900 border-sky-300',
    'UNDER_REVIEW': 'bg-blue-100 text-blue-900 border-blue-300',
    'VERIFIED': 'bg-emerald-100 text-emerald-900 border-emerald-300',
    'ADDITIONAL_INFO_REQUIRED': 'bg-orange-100 text-orange-900 border-orange-300',
    'INVESTIGATION': 'bg-indigo-100 text-indigo-900 border-indigo-300',
    'FIR_CREATED': 'bg-teal-100 text-teal-900 border-teal-300',
    'RESOLVED': 'bg-green-100 text-green-900 border-green-300',
    'CLOSED': 'bg-slate-100 text-slate-700 border-slate-300',
    'REJECTED': 'bg-rose-100 text-rose-900 border-rose-300',
}

ACTIVITY_ICONS = {
    'CITIZEN_APPLICATION': 'how_to_reg',
    'COMPLAINT': 'fact_check',
    'FIR': 'description',
}


def require_verification_officer():
    """Ensure active user is a Verification Officer or Administrator."""
    user = get_current_user() or {}
    if not user or user.get('role') not in ('VERIFICATION_OFFICER', 'ADMIN'):
        ui.navigate.to('/staff-portal')
        return None
    return user


def _fmt(value, with_time: bool = True) -> str:
    text = str(value or '').strip()
    if not text or text == 'None':
        return '—'
    text = text.replace('T', ' ')
    return text[:19] if with_time else text[:10]


def _status_badge(status: str) -> None:
    classes = COMPLAINT_STATUS_STYLES.get(status or '', 'bg-slate-100 text-slate-700 border-slate-300')
    ui.badge((status or 'UNKNOWN').replace('_', ' ')).classes(
        f'{classes} border font-bold text-[10px] px-2.5 py-0.5 rounded-full'
    )


def _verification_badge(status: str) -> None:
    colour = {
        'PENDING': 'bg-amber-100 text-amber-900 border-amber-300',
        'UNDER_REVIEW': 'bg-blue-100 text-blue-900 border-blue-300',
        'VERIFIED': 'bg-emerald-100 text-emerald-900 border-emerald-300',
        'ADDITIONAL_INFO_REQUIRED': 'bg-orange-100 text-orange-900 border-orange-300',
        'REJECTED': 'bg-rose-100 text-rose-900 border-rose-300',
    }.get(status or 'PENDING', 'bg-slate-100 text-slate-700 border-slate-300')
    ui.badge(verification_label(status)).classes(
        f'{colour} border font-bold text-[10px] px-2.5 py-0.5 rounded-full'
    )


def _parse_evidence(raw) -> list:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        except (TypeError, ValueError):
            return []
    return []


def _fmt_size(size) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return '—'
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.0f} KB'
    return f'{size} B'


def render_evidence(complaint: dict) -> None:
    """Authorised evidence download — files never have public URLs."""
    items = _parse_evidence(complaint.get('evidence_files'))

    def download(item: dict) -> None:
        data = evidence_bytes(complaint['id'], item.get('stored_name') or '')
        if not data:
            ui.notify('This evidence file is no longer available.', type='warning')
            return
        ui.download(data, item.get('name') or 'evidence')

    if not items:
        ui.label('No evidence files were attached to this complaint.').classes('text-xs text-slate-500 italic')
        return
    with ui.column().classes('w-full gap-2'):
        for item in items:
            with ui.row().classes(
                'w-full items-center justify-between gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200'
            ):
                with ui.row().classes('items-center gap-2 flex-1 min-w-0'):
                    ui.icon('attach_file', size='xs').classes('text-slate-500')
                    with ui.column().classes('gap-0 min-w-0'):
                        ui.label(item.get('name') or 'evidence').classes('text-xs font-bold text-slate-800 truncate')
                        ui.label(
                            f"{_fmt_size(item.get('size'))} · {item.get('content_type') or 'file'}"
                        ).classes('text-[10px] text-slate-500')
                ui.button('Download', icon='download', on_click=lambda i=item: download(i)).props(
                    'flat dense size=sm'
                ).classes('text-emerald-700 font-bold text-[11px]')


def _listen(refreshable_fn, event_types, on_event=None) -> None:
    """Refresh the page in place whenever a relevant domain event is published."""
    client = ui.context.client
    queue = subscribe()

    async def listener() -> None:
        while True:
            event = await queue.get()
            if event.get('type') not in event_types:
                continue
            if not client.has_socket_connection:
                break
            with client:
                refreshable_fn.refresh()
                if on_event:
                    on_event(event)

    task = background_tasks.create(listener(), name='verification-live-listener')

    def stop() -> None:
        unsubscribe(queue)
        task.cancel()

    client.on_disconnect(stop)


def _stat_card(label: str, value, icon: str, colour: str, background: str, target: str = '') -> None:
    with ui.card().classes(f'min-w-40 flex-1 p-5 rounded-2xl border shadow-xs {background} gap-1'):
        with ui.row().classes('w-full items-center justify-between'):
            ui.icon(icon, size='md').style(f'color: {colour}')
            ui.label(str(value)).classes('text-3xl font-black text-slate-900')
        ui.label(label).classes('text-[11px] font-bold text-slate-700 leading-tight')
        if target:
            ui.button('Open', icon='arrow_forward', on_click=lambda t=target: ui.navigate.to(t)).props(
                'flat dense no-caps size=xs'
            ).classes('text-[10px] font-bold text-slate-500 self-start px-0')


# ==========================================
# 1. LIVE VERIFICATION DASHBOARD
# ==========================================
@ui.page('/verification')
def verification_dashboard() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification',
        '/verification',
        'Verification Officer Bureau',
        'Live citizen verification, complaint scrutiny, FIR registration and police assignment command desk.',
    ):
        with ui.card().classes('w-full p-5 rounded-3xl bg-white border border-slate-200 shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                with ui.row().classes('items-center gap-3'):
                    with ui.element('div').classes(
                        'w-14 h-14 rounded-full flex items-center justify-center '
                        'bg-gradient-to-br from-emerald-800 to-slate-900 text-white shadow-md'
                    ):
                        ui.icon('fact_check', size='md')
                    with ui.column().classes('gap-0'):
                        ui.label(f"{user.get('rank') or 'Verification Officer'} {user.get('name', 'Officer')}").classes(
                            'text-xl md:text-2xl font-black text-slate-900 fantasy-title'
                        )
                        ui.label(
                            f"Badge {user.get('badge_number') or 'N/A'} · Unit {user.get('station') or 'Not recorded'}"
                        ).classes('text-[11px] text-slate-500 font-mono')
                with ui.row().classes('items-center gap-2 flex-wrap'):
                    with ui.row().classes(
                        'items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200'
                    ):
                        ui.element('div').classes('w-2 h-2 rounded-full bg-emerald-500 animate-pulse')
                        ui.label('Live — updates stream automatically').classes('text-[10px] font-bold text-emerald-900')
                    unread = get_unread_count(user['id'])
                    if unread > 0:
                        ui.button(
                            f'Notifications ({unread})', icon='notifications',
                            on_click=lambda: ui.navigate.to('/verification/notifications'),
                        ).props('unelevated').classes(
                            'bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl px-4 py-2 text-[11px]'
                        )

        @ui.refreshable
        def render_dashboard() -> None:
            stats = get_dashboard_stats()
            assignments = get_recent_assignments(limit=5)
            activity = get_recent_activity(limit=8)

            ui.label(
                f"Last synced {datetime.now().strftime('%H:%M:%S')} · figures read directly from the database"
            ).classes('text-[10px] text-slate-400 font-mono')
            with ui.row().classes('w-full flex-wrap gap-4'):
                _stat_card('Total Citizen Registrations', stats['total_citizen_registrations'],
                           'groups', '#0F766E', 'bg-teal-50/80 border-teal-200', '/verification/citizens')
                _stat_card('Pending Citizen Verifications', stats['pending_citizen_verifications'],
                           'how_to_reg', '#D97706', 'bg-amber-50/80 border-amber-200', '/verification/citizens')
                _stat_card('Verified Citizens', stats['verified_citizens'],
                           'verified_user', '#059669', 'bg-emerald-50/80 border-emerald-200', '/verification/citizens')
                _stat_card('Pending FIR Verifications', stats['pending_fir_verifications'],
                           'pending_actions', '#2563EB', 'bg-blue-50/80 border-blue-200', '/verification/complaints')
                _stat_card('Verified FIRs', stats['verified_firs'],
                           'description', '#065F46', 'bg-emerald-50/80 border-emerald-200', '/verification/firs')
                _stat_card('Cases Awaiting Police Assignment', stats['cases_awaiting_assignment'],
                           'local_police', '#4F46E5', 'bg-indigo-50/80 border-indigo-200', '/verification/firs')
                _stat_card('Recently Assigned Cases', stats['recently_assigned_cases'],
                           'assignment_ind', '#0E7490', 'bg-cyan-50/80 border-cyan-200', '/verification/firs')
                _stat_card('Awaiting FIR Registration', stats['awaiting_fir_registration'],
                           'gavel', '#B45309', 'bg-orange-50/80 border-orange-200', '/verification/firs')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                for label, icon, target, classes in [
                    ('Citizen Verification', 'how_to_reg', '/verification/citizens',
                     'bg-emerald-800 hover:bg-emerald-900'),
                    ('Verify Queries', 'report_problem', '/verification/complaints',
                     'bg-blue-800 hover:bg-blue-900'),
                    ('Verify Your FIR', 'description', '/verification/firs',
                     'bg-indigo-800 hover:bg-indigo-900'),
                    ('Verification History', 'history', '/verification/history',
                     'bg-slate-700 hover:bg-slate-800'),
                ]:
                    ui.button(label, icon=icon, on_click=lambda t=target: ui.navigate.to(t)).props(
                        'unelevated'
                    ).classes(f'{classes} text-white font-bold rounded-xl px-4 py-2.5 text-xs shadow-sm')

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-2 pb-3 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('local_police', size='sm').classes('text-blue-800')
                        ui.label('Recently Assigned Cases').classes('text-lg font-bold text-slate-900 fantasy-title')
                    ui.badge(f'{len(assignments)}').classes('bg-blue-100 text-blue-900 font-bold text-xs')
                if not assignments:
                    ui.label('No officer assignments recorded yet.').classes('text-xs text-slate-500 italic mt-3')
                else:
                    with ui.column().classes('w-full gap-2 mt-3'):
                        for item in assignments:
                            with ui.row().classes(
                                'w-full items-center justify-between gap-3 p-3 rounded-xl '
                                'bg-slate-50 border border-slate-200 flex-wrap'
                            ):
                                with ui.column().classes('gap-0 min-w-0'):
                                    ui.label(
                                        f"{item.get('fir_number') or '—'} · "
                                        f"{item.get('complaint_reference') or 'No complaint reference'}"
                                    ).classes('text-xs font-bold text-slate-900 font-mono')
                                    ui.label(
                                        f"{item.get('officer_rank') or 'Officer'} "
                                        f"{item.get('officer_name') or '—'} · "
                                        f"Badge {item.get('officer_badge') or 'N/A'}"
                                    ).classes('text-[10px] text-slate-500')
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.badge(item.get('assignment_status') or '').classes(
                                        'bg-slate-200 text-slate-700 font-bold text-[9px]'
                                    )
                                    ui.label(_fmt(item.get('assigned_at'))).classes(
                                        'text-[10px] font-mono text-slate-400'
                                    )
                                    ui.button(
                                        'View Case', icon='open_in_new',
                                        on_click=lambda fid=item['fir_id']: ui.navigate.to(f'/verification/fir/{fid}'),
                                    ).props('flat dense no-caps size=sm').classes(
                                        'text-blue-800 font-bold text-[10px]'
                                    )

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-2 pb-3 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('history', size='sm').classes('text-emerald-800')
                        ui.label('Recent Verification Activity').classes(
                            'text-lg font-bold text-slate-900 fantasy-title'
                        )
                    ui.button(
                        'Full Audit History', icon='list_alt',
                        on_click=lambda: ui.navigate.to('/verification/history'),
                    ).props('flat dense no-caps').classes('text-emerald-800 font-bold text-[10px]')
                if not activity:
                    ui.label('No verification activity recorded yet.').classes('text-xs text-slate-500 italic mt-3')
                else:
                    with ui.column().classes('w-full gap-2 mt-3'):
                        for item in activity:
                            with ui.row().classes('w-full items-start gap-3'):
                                with ui.element('div').classes(
                                    'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center '
                                    'bg-emerald-100 text-emerald-800'
                                ):
                                    ui.icon(ACTIVITY_ICONS.get(item.get('kind'), 'info'), size='xs')
                                with ui.card().classes(
                                    'flex-1 p-3 rounded-xl bg-slate-50 border border-slate-200 shadow-xs gap-0.5'
                                ):
                                    with ui.row().classes(
                                        'w-full justify-between items-start flex-wrap gap-1'
                                    ):
                                        ui.label(item.get('title') or '').classes(
                                            'text-xs font-bold text-slate-900'
                                        )
                                        ui.label(_fmt(item.get('created_at'))).classes(
                                            'text-[9px] text-slate-400 font-mono'
                                        )
                                    ui.label(
                                        f"{item.get('subject') or '—'} · {item.get('reference') or ''}"
                                    ).classes('text-[10px] text-slate-600 font-semibold')
                                    actor = f"{item.get('actor_name') or 'System'}"
                                    if item.get('actor_badge') and item.get('actor_badge') != 'N/A':
                                        actor += f" ({item.get('actor_badge')})"
                                    ui.label(actor).classes('text-[9px] text-slate-400 font-mono')
                                    if item.get('remarks'):
                                        ui.label(str(item['remarks'])[:220]).classes(
                                            'text-[10px] text-slate-600 mt-0.5 leading-relaxed'
                                        )
                                    ui.button(
                                        'Open', icon='open_in_new',
                                        on_click=lambda t=item.get('target'): ui.navigate.to(t),
                                    ).props('flat dense no-caps size=xs').classes(
                                        'text-emerald-800 font-bold text-[9px] px-0 self-start'
                                    )

        render_dashboard()

        _listen(
            render_dashboard,
            (
                'CITIZEN_APPLICATION_SUBMITTED',
                'CITIZEN_APPLICATION_UPDATED',
                'COMPLAINT_UPDATED',
                'COMPLAINT_VERIFICATION_UPDATED',
                'FIR_UPDATED',
                'FIR_DOCUMENT_GENERATED',
                'CASE_STAGE_UPDATED',
            ),
            on_event=lambda event: ui.notify(
                f"Update received: {str(event.get('type', '')).replace('_', ' ').lower()}",
                type='info', position='top-right', timeout=3000,
            ),
        )
        ui.timer(15.0, render_dashboard.refresh)


# ==========================================
# 2. VERIFY QUERIES — COMPLAINT VERIFICATION
# ==========================================
@ui.page('/verification/complaints')
def verification_complaints_page() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification',
        '/verification/complaints',
        'Verify Queries — Complaint Verification',
        'Review citizen complaints, inspect evidence, record decisions and forward verified complaints '
        'for FIR registration.',
    ):
        search_input = ui.input(placeholder='Search reference, citizen, category or location').props(
            'outlined dense clearable'
        ).classes('w-full max-w-md')

        @ui.refreshable
        def render_queue() -> None:
            complaints = get_verification_queue(search_input.value or '')
            stats = get_dashboard_stats()

            with ui.row().classes('w-full flex-wrap gap-3'):
                for label, value, icon, colour, bg in [
                    ('Pending Verification', stats['pending_fir_verifications'], 'pending_actions', '#D97706',
                     'bg-amber-50/80 border-amber-200'),
                    ('Verified — Awaiting FIR', stats['awaiting_fir_registration'], 'gavel', '#B45309',
                     'bg-orange-50/80 border-orange-200'),
                    ('Registered FIRs', stats['verified_firs'], 'description', '#065F46',
                     'bg-emerald-50/80 border-emerald-200'),
                    ('Assigned Cases', stats['recently_assigned_cases'], 'local_police', '#4F46E5',
                     'bg-indigo-50/80 border-indigo-200'),
                ]:
                    with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border shadow-xs {bg}'):
                        with ui.row().classes('items-center justify-between w-full'):
                            ui.icon(icon, size='sm').style(f'color: {colour}')
                            ui.label(str(value)).classes('text-2xl font-black text-slate-900')
                        ui.label(label).classes('text-[11px] font-bold text-slate-700 mt-1')

            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 mt-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('report_problem', size='sm').classes('text-blue-800')
                    ui.label('Complaints Awaiting Verification').classes(
                        'text-lg font-bold text-slate-900 fantasy-title'
                    )
                ui.badge(f'{len(complaints)} in queue').classes('bg-amber-500 text-slate-950 font-bold text-xs')

            if not complaints:
                with ui.card().classes('w-full p-10 rounded-2xl bg-white border border-slate-200 shadow-xs'):
                    with ui.column().classes('w-full items-center gap-3 text-center'):
                        ui.icon('task_alt', size='xl').classes('text-emerald-500')
                        ui.label('No complaints are awaiting verification.').classes(
                            'text-base font-bold text-slate-700'
                        )
                        ui.label('New citizen complaints appear here automatically.').classes(
                            'text-xs text-slate-500'
                        )
                return

            with ui.element('div').classes('grid grid-cols-1 xl:grid-cols-2 gap-4 w-full'):
                for complaint in complaints:
                    with ui.card().classes(
                        'w-full h-full p-5 rounded-2xl bg-white border border-slate-200 shadow-xs gap-2 '
                        'hover:shadow-md transition-all'
                    ):
                        with ui.row().classes('w-full items-start justify-between gap-2'):
                            with ui.column().classes('gap-0 min-w-0'):
                                ui.label(complaint.get('reference') or '—').classes(
                                    'text-base font-black text-slate-900 font-mono'
                                )
                                ui.label(
                                    complaint.get('citizen_name') or complaint.get('applicant_name') or 'Citizen'
                                ).classes('text-xs font-bold text-slate-700 truncate')
                            _verification_badge(complaint.get('verification_status') or 'PENDING')

                        with ui.column().classes('w-full gap-1 text-[11px] text-slate-600'):
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('category', size='xs').classes('text-slate-400')
                                ui.label(complaint.get('category') or '—').classes('font-semibold text-slate-800')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('event', size='xs').classes('text-slate-400')
                                ui.label(
                                    f"{complaint.get('incident_date') or 'Date not recorded'} · "
                                    f"{complaint.get('location') or 'Location not recorded'}"
                                ).classes('truncate')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('local_police', size='xs').classes('text-slate-400')
                                ui.label(
                                    complaint.get('police_station') or 'Police station not recorded'
                                ).classes('truncate')
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('schedule', size='xs').classes('text-slate-400')
                                ui.label(f"Submitted {_fmt(complaint.get('submitted_at'))}").classes(
                                    'font-mono text-[10px]'
                                )

                        with ui.row().classes(
                            'w-full justify-between items-center pt-2 border-t border-slate-100 mt-auto'
                        ):
                            _status_badge(complaint.get('status'))
                            ui.button(
                                'Review Complaint', icon='visibility',
                                on_click=lambda cid=complaint['id']: ui.navigate.to(
                                    f'/verification/complaint/{cid}'
                                ),
                            ).props('unelevated size=sm').classes(
                                'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-lg px-3 py-1.5 text-[11px]'
                            )

        search_input.on('keydown.enter', lambda: render_queue.refresh())
        ui.button('Search', icon='search', on_click=render_queue.refresh).props('flat dense').classes(
            'text-slate-600 font-bold text-xs'
        )
        render_queue()

        _listen(
            render_queue,
            ('COMPLAINT_VERIFICATION_UPDATED', 'COMPLAINT_UPDATED', 'FIR_UPDATED'),
            on_event=lambda event: ui.notify(
                f"Complaint {event.get('reference') or ''} → "
                f"{verification_label(event.get('verification_status'))}",
                type='info', position='top-right', timeout=5000,
            ) if event.get('reference') else None,
        )
        ui.timer(15.0, render_queue.refresh)


def _open_complaint_action_dialog(complaint: dict, user: dict, action: str) -> None:
    meta = {
        'START_REVIEW': (
            'Start Verification Review',
            'Marks the complaint as under verification and notifies the citizen. No decision is taken yet.',
            'Start Review', 'bg-blue-800 hover:bg-blue-900', False,
        ),
        'VERIFY': (
            'Approve & Forward for FIR Registration',
            'Verifies the complaint and unlocks official FIR registration with police officer assignment. '
            'The citizen is notified immediately.',
            'Verify Complaint', 'bg-emerald-700 hover:bg-emerald-800', False,
        ),
        'REJECT': (
            'Reject Complaint',
            'Rejection is final for this complaint. The reason is shared with the citizen.',
            'Reject Complaint', 'bg-rose-700 hover:bg-rose-800', True,
        ),
        'REQUEST_INFO': (
            'Request Additional Information',
            'The citizen is notified with your remarks and the complaint remains open for re-review.',
            'Send Request', 'bg-amber-600 hover:bg-amber-700', True,
        ),
        'REMARK': (
            'Add Internal Verification Remark',
            'Internal remarks are recorded in the audit history and are never shown to citizens or '
            'unauthorised police staff.',
            'Save Remark', 'bg-slate-700 hover:bg-slate-800', True,
        ),
    }
    title, description, button_label, button_class, remarks_required = meta[action]

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6 rounded-3xl bg-white shadow-2xl gap-4'):
        with ui.row().classes('w-full items-start justify-between'):
            with ui.column().classes('gap-0'):
                ui.label(title).classes('text-xl font-black text-slate-900 fantasy-title')
                ui.label(
                    f"{complaint.get('reference')} · {complaint.get('citizen_name') or 'Citizen'}"
                ).classes('text-[11px] font-mono text-slate-500')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

        ui.label(description).classes('text-xs text-slate-600 leading-relaxed')
        remarks_input = ui.textarea(
            'Remarks *' if remarks_required else 'Officer remarks (optional)',
            placeholder='Record the verification findings, missing information, or decision reason...',
        ).props('outlined rows=4').classes('w-full')
        error_label = ui.label('').classes('text-xs text-rose-600 font-semibold')

        def submit() -> None:
            try:
                record_complaint_verification_action(
                    complaint['id'], user, action, remarks_input.value or ''
                )
                ui.notify(f"Complaint {complaint.get('reference')}: {title} recorded.", type='positive')
                dialog.close()
                ui.navigate.to(f"/verification/complaint/{complaint['id']}")
            except (PermissionError, ValueError) as error:
                error_label.text = f'⚠ {error}'
            except Exception as error:  # pragma: no cover - defensive UI boundary
                error_label.text = f'⚠ {error}'

        with ui.row().classes('w-full justify-end gap-2 pt-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-slate-600 font-bold')
            ui.button(button_label, on_click=submit).props('unelevated').classes(
                f'{button_class} text-white font-bold rounded-xl px-5 py-2 text-xs shadow-sm'
            )

    dialog.open()


@ui.page('/verification/complaint/{complaint_id}')
def verification_complaint_detail_page(complaint_id: str) -> None:
    user = require_verification_officer()
    if not user:
        return

    complaint = get_complaint_for_verification(complaint_id)
    if not complaint:
        with portal_page('verification', '/verification/complaints', 'Complaint Not Found', ''):
            ui.label('This complaint could not be found.').classes('text-sm font-bold text-rose-700')
            ui.button(
                'Back to Verify Queries', on_click=lambda: ui.navigate.to('/verification/complaints')
            ).props('flat')
        return

    with portal_page(
        'verification',
        '/verification/complaints',
        f"Complaint Verification — {complaint.get('reference')}",
        complaint.get('title') or 'Complaint review and verification desk.',
    ):
        ui.button(
            '← Back to Verify Queries', icon='arrow_back',
            on_click=lambda: ui.navigate.to('/verification/complaints'),
        ).props('flat no-caps').classes('text-slate-600 font-bold text-xs')

        @ui.refreshable
        def render_detail() -> None:
            record = get_complaint_for_verification(complaint_id)
            if not record:
                ui.label('This complaint is no longer available.').classes('text-sm font-bold text-rose-700')
                return
            events = get_complaint_verification_events(record['id'])
            v_status = record.get('verification_status') or 'PENDING'
            locked = bool(record.get('fir_id')) or (record.get('status') in ('REJECTED', 'CLOSED'))

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes(
                    'w-full items-start justify-between flex-wrap gap-3 pb-4 border-b border-slate-200'
                ):
                    with ui.column().classes('gap-1 min-w-0'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.label(record.get('reference') or '—').classes(
                                'text-2xl font-black text-slate-900 font-mono'
                            )
                            _status_badge(record.get('status'))
                            _verification_badge(v_status)
                        ui.label(record.get('title') or '').classes('text-sm font-bold text-slate-700')
                        ui.label(
                            f"Submitted {_fmt(record.get('submitted_at'))} · "
                            f"Last updated {_fmt(record.get('updated_at'))}"
                        ).classes('text-[10px] text-slate-500 font-mono')
                    if record.get('fir_id'):
                        ui.button(
                            f"Open FIR {record.get('fir_number') or ''}", icon='description',
                            on_click=lambda fid=record['fir_id']: ui.navigate.to(f'/verification/fir/{fid}'),
                        ).props('unelevated').classes(
                            'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-5 py-2.5 text-xs'
                        )
                    elif v_status == 'VERIFIED':
                        ui.button(
                            'Register FIR & Assign Officer', icon='gavel',
                            on_click=lambda cid=record['id']: ui.navigate.to(f'/verification/fir-register/{cid}'),
                        ).props('unelevated').classes(
                            'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-5 py-2.5 text-xs'
                        )

            with ui.row().classes('w-full gap-4 flex-wrap items-start'):
                with ui.card().classes(
                    'flex-1 min-w-72 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
                ):
                    with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                        ui.icon('person', size='sm').classes('text-blue-800')
                        ui.label('Citizen & Complaint Details').classes(
                            'text-base font-bold text-slate-900 fantasy-title'
                        )
                    for label, value, icon in [
                        ('Citizen', record.get('citizen_name') or record.get('applicant_name') or 'Not recorded', 'badge'),
                        ('Citizen Username', record.get('citizen_username') or 'Not issued yet', 'person_search'),
                        ('Mobile', record.get('citizen_phone') or 'Not recorded', 'phone'),
                        ('Email', record.get('citizen_email') or 'Not recorded', 'email'),
                        ('Category', record.get('category') or 'Not recorded', 'category'),
                        ('Incident Date', record.get('incident_date') or 'Not recorded', 'event'),
                        ('Incident Time', record.get('incident_time') or 'Not recorded', 'schedule'),
                        ('Location', record.get('location') or 'Not recorded', 'place'),
                        ('Landmark / Area', ', '.join(part for part in (record.get('landmark'), record.get('area')) if part) or 'Not recorded', 'my_location'),
                        ('District / State', ', '.join(part for part in (record.get('district'), record.get('state')) if part) or 'Not recorded', 'map'),
                        ('Police Station', record.get('police_station') or 'Not recorded', 'local_police'),
                    ]:
                        with ui.row().classes(
                            'w-full justify-between items-start gap-3 py-1.5 border-b border-slate-50'
                        ):
                            with ui.row().classes('items-center gap-2 shrink-0'):
                                ui.icon(icon, size='xs').classes('text-slate-400')
                                ui.label(label).classes('text-[10px] font-bold text-slate-500 uppercase')
                            ui.label(str(value)).classes(
                                'text-[11px] font-semibold text-slate-900 text-right break-words'
                            )
                    ui.label('Complaint Description').classes(
                        'text-[10px] font-bold text-slate-500 uppercase mt-3'
                    )
                    ui.label(record.get('description') or '—').classes(
                        'text-xs text-slate-800 leading-relaxed whitespace-pre-line mt-1'
                    )

                with ui.column().classes('flex-1 min-w-72 gap-4'):
                    with ui.card().classes(
                        'w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
                    ):
                        with ui.row().classes('items-center justify-between mb-3 pb-2 border-b border-slate-100'):
                            with ui.row().classes('items-center gap-2'):
                                ui.icon('attach_file', size='sm').classes('text-emerald-800')
                                ui.label('Uploaded Evidence').classes(
                                    'text-base font-bold text-slate-900 fantasy-title'
                                )
                            ui.badge(f"{len(_parse_evidence(record.get('evidence_files')))} file(s)").classes(
                                'bg-slate-100 text-slate-700 font-bold text-[10px]'
                            )
                        render_evidence(record)

                    with ui.card().classes(
                        'w-full p-6 bg-white border border-emerald-800/20 rounded-3xl shadow-sm'
                    ):
                        with ui.row().classes('items-center gap-2 mb-2'):
                            ui.icon('fact_check', size='sm').classes('text-emerald-800')
                            ui.label('Verification Decision').classes(
                                'text-base font-bold text-slate-900 fantasy-title'
                            )
                        if locked:
                            ui.label(
                                'This complaint is locked for further verification decisions. '
                                'Internal remarks can still be recorded.'
                            ).classes('text-[11px] text-slate-500 mb-3')
                        else:
                            ui.label(
                                'Each decision records your officer identity and a server timestamp in the '
                                'append-only verification history, and notifies the citizen.'
                            ).classes('text-[11px] text-slate-500 mb-3')

                        with ui.row().classes('w-full gap-2 flex-wrap'):
                            if not locked:
                                if v_status in ('PENDING', 'ADDITIONAL_INFO_REQUIRED'):
                                    ui.button(
                                        'Start Review', icon='manage_search',
                                        on_click=lambda: _open_complaint_action_dialog(
                                            record, user, 'START_REVIEW'
                                        ),
                                    ).props('unelevated').classes(
                                        'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl '
                                        'px-4 py-2 text-xs'
                                    )
                                if v_status != 'VERIFIED':
                                    ui.button(
                                        'Verify Complaint', icon='check_circle',
                                        on_click=lambda: _open_complaint_action_dialog(record, user, 'VERIFY'),
                                    ).props('unelevated').classes(
                                        'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl '
                                        'px-4 py-2 text-xs'
                                    )
                                ui.button(
                                    'Request Additional Info', icon='contact_support',
                                    on_click=lambda: _open_complaint_action_dialog(
                                        record, user, 'REQUEST_INFO'
                                    ),
                                ).props('unelevated').classes(
                                    'bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl '
                                    'px-4 py-2 text-xs'
                                )
                                ui.button(
                                    'Reject', icon='cancel',
                                    on_click=lambda: _open_complaint_action_dialog(record, user, 'REJECT'),
                                ).props('unelevated').classes(
                                    'bg-rose-700 hover:bg-rose-800 text-white font-bold rounded-xl '
                                    'px-4 py-2 text-xs'
                                )
                            ui.button(
                                'Add Internal Remark', icon='sticky_note_2',
                                on_click=lambda: _open_complaint_action_dialog(record, user, 'REMARK'),
                            ).props('unelevated').classes(
                                'bg-slate-700 hover:bg-slate-800 text-white font-bold rounded-xl '
                                'px-4 py-2 text-xs'
                            )

                        if record.get('verification_remarks'):
                            with ui.card().classes(
                                'w-full mt-4 p-3 rounded-xl bg-amber-50 border border-amber-200'
                            ):
                                ui.label('Latest Internal Verification Remark').classes(
                                    'text-[10px] font-bold text-amber-800 uppercase'
                                )
                                ui.label(record['verification_remarks']).classes(
                                    'text-xs text-amber-950 font-medium mt-1 whitespace-pre-line'
                                )
                        if record.get('rejection_reason') and record.get('status') == 'REJECTED':
                            with ui.card().classes(
                                'w-full mt-2 p-3 rounded-xl bg-rose-50 border border-rose-200'
                            ):
                                ui.label('Rejection reason shared with citizen').classes(
                                    'text-[10px] font-bold text-rose-800 uppercase'
                                )
                                ui.label(record['rejection_reason']).classes(
                                    'text-xs text-rose-950 font-medium mt-1 whitespace-pre-line'
                                )
                        if record.get('verified_by_name'):
                            ui.label(
                                f"Verified by {record.get('verified_by_name')} · "
                                f"{_fmt(record.get('verified_at'))}"
                            ).classes('text-[10px] text-slate-500 font-mono mt-3')

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 mb-3'):
                    ui.icon('history', size='sm').classes('text-emerald-800')
                    ui.label('Complaint Verification History').classes(
                        'text-base font-bold text-slate-900 fantasy-title'
                    )
                if not events:
                    ui.label('No verification events recorded yet.').classes('text-xs text-slate-500 italic')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for event in events:
                            with ui.row().classes('w-full items-start gap-3'):
                                with ui.element('div').classes(
                                    'w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center '
                                    'bg-emerald-100 text-emerald-800'
                                ):
                                    ui.icon('check', size='xs')
                                with ui.card().classes(
                                    'flex-1 p-3 rounded-xl bg-slate-50 border border-slate-200 '
                                    'shadow-xs gap-0.5'
                                ):
                                    with ui.row().classes(
                                        'w-full justify-between items-start flex-wrap gap-1'
                                    ):
                                        ui.label(action_label(event.get('action'))).classes(
                                            'text-xs font-bold text-slate-900'
                                        )
                                        ui.label(_fmt(event.get('created_at'))).classes(
                                            'text-[9px] text-slate-400 font-mono'
                                        )
                                    ui.label(
                                        f"{event.get('actor_role') or 'OFFICER'} · "
                                        f"{event.get('actor_name') or '—'}"
                                        + (f" ({event.get('actor_badge')})"
                                           if event.get('actor_badge') and event.get('actor_badge') != 'N/A'
                                           else '')
                                    ).classes('text-[10px] text-slate-500 font-semibold')
                                    if event.get('status_from') or event.get('status_to'):
                                        ui.label(
                                            f"{event.get('status_from') or '—'} → "
                                            f"{event.get('status_to') or '—'}"
                                        ).classes('text-[9px] text-slate-400 font-mono')
                                    if event.get('remarks'):
                                        ui.label(event['remarks']).classes(
                                            'text-[11px] text-slate-700 mt-0.5 leading-relaxed whitespace-pre-line'
                                        )

        render_detail()
        _listen(
            render_detail,
            ('COMPLAINT_VERIFICATION_UPDATED', 'COMPLAINT_UPDATED', 'FIR_UPDATED'),
        )


# ==========================================
# 3. VERIFY YOUR FIR — VERIFIED COMPLAINTS & REGISTERED FIRS
# ==========================================
@ui.page('/verification/firs')
@ui.page('/verification/queue')
@ui.page('/verification/verified')
@ui.page('/verification/assignments')
def verification_firs_page() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification',
        '/verification/firs',
        'Verify Your FIR',
        'Verified complaints awaiting official FIR registration, and all registered FIR case files.',
    ):
        @ui.refreshable
        def render_firs() -> None:
            ready = get_complaints_ready_for_fir()
            registered = get_firs(actor_user=user)
            documents = {row['fir_id'] for row in _document_index()}

            with ui.card().classes('w-full p-6 bg-white border border-amber-200 rounded-3xl shadow-sm'):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-2 pb-3 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('gavel', size='sm').classes('text-amber-700')
                        ui.label('Verified Complaints Awaiting FIR Registration').classes(
                            'text-lg font-bold text-slate-900 fantasy-title'
                        )
                    ui.badge(f'{len(ready)} awaiting registration').classes(
                        'bg-amber-500 text-slate-950 font-bold text-xs'
                    )
                if not ready:
                    ui.label('No verified complaints are awaiting FIR registration.').classes(
                        'text-xs text-slate-500 italic mt-3'
                    )
                else:
                    with ui.element('div').classes(
                        'grid grid-cols-1 xl:grid-cols-2 gap-4 w-full mt-3'
                    ):
                        for complaint in ready:
                            with ui.card().classes(
                                'w-full p-4 rounded-2xl bg-amber-50/50 border border-amber-200 gap-2'
                            ):
                                with ui.row().classes('w-full justify-between items-start gap-2'):
                                    with ui.column().classes('gap-0 min-w-0'):
                                        ui.label(complaint.get('reference') or '—').classes(
                                            'text-sm font-black text-slate-900 font-mono'
                                        )
                                        ui.label(
                                            complaint.get('citizen_name')
                                            or complaint.get('applicant_name') or 'Citizen'
                                        ).classes('text-xs font-bold text-slate-700')
                                    _verification_badge(complaint.get('verification_status'))
                                ui.label(
                                    f"{complaint.get('category') or '—'} · "
                                    f"{complaint.get('police_station') or 'Station not recorded'}"
                                ).classes('text-[11px] text-slate-600')
                                ui.label(
                                    f"Verified by {complaint.get('verified_by_name') or '—'} · "
                                    f"{_fmt(complaint.get('verified_at'))}"
                                ).classes('text-[10px] text-slate-500 font-mono')
                                ui.button(
                                    'Review & Register FIR', icon='description',
                                    on_click=lambda cid=complaint['id']: ui.navigate.to(
                                        f'/verification/fir-register/{cid}'
                                    ),
                                ).props('unelevated').classes(
                                    'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl '
                                    'px-4 py-2 text-[11px] self-start mt-1'
                                )

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-2 pb-3 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('description', size='sm').classes('text-emerald-800')
                        ui.label('Registered FIR Case Files').classes(
                            'text-lg font-bold text-slate-900 fantasy-title'
                        )
                    ui.badge(f'{len(registered)} FIRs').classes(
                        'bg-emerald-100 text-emerald-900 font-bold text-xs'
                    )
                if not registered:
                    ui.label('No FIRs have been registered yet.').classes('text-xs text-slate-500 italic mt-3')
                else:
                    with ui.element('div').classes('w-full overflow-x-auto mt-3'):
                        with ui.element('table').classes('w-full text-left text-xs border-collapse'):
                            with ui.element('thead').classes(
                                'bg-slate-100 text-slate-700 border-b border-slate-200'
                            ):
                                with ui.element('tr'):
                                    for col in ('FIR Number', 'Citizen', 'Offence & Station', 'Status',
                                                'Assigned Officer', 'PDF', 'Action'):
                                        ui.element('th').classes('p-3 font-bold').text = col
                            with ui.element('tbody').classes('divide-y divide-slate-200'):
                                for fir in registered:
                                    with ui.element('tr').classes('hover:bg-slate-50 transition-colors'):
                                        with ui.element('td').classes(
                                            'p-3 font-bold text-slate-900 font-mono'
                                        ):
                                            ui.label(fir.get('fir_number') or '—')
                                        with ui.element('td').classes('p-3'):
                                            ui.label(fir.get('citizen_name') or 'Citizen').classes(
                                                'font-bold text-slate-800'
                                            )
                                        with ui.element('td').classes('p-3'):
                                            ui.label(fir.get('incident_type') or '—').classes(
                                                'font-semibold text-slate-800'
                                            )
                                            ui.label(fir.get('police_station') or '').classes(
                                                'text-[10px] text-slate-500'
                                            )
                                        with ui.element('td').classes('p-3'):
                                            fir_status_badge(fir.get('status'))
                                        with ui.element('td').classes('p-3 text-slate-800'):
                                            if fir.get('officer_name'):
                                                ui.label(
                                                    f"{fir.get('officer_rank') or ''} {fir.get('officer_name')}"
                                                ).classes('font-semibold text-blue-900')
                                                ui.label(
                                                    f"Badge {fir.get('officer_badge') or 'N/A'}"
                                                ).classes('text-[10px] text-slate-500 font-mono')
                                            else:
                                                ui.label('Unassigned').classes('text-amber-700 italic')
                                        with ui.element('td').classes('p-3'):
                                            if fir['id'] in documents:
                                                ui.badge('Available').classes(
                                                    'bg-emerald-100 text-emerald-900 border border-emerald-300 '
                                                    'font-bold text-[10px]'
                                                )
                                            else:
                                                ui.badge('Not generated').classes(
                                                    'bg-slate-100 text-slate-600 border border-slate-300 '
                                                    'font-bold text-[10px]'
                                                )
                                        with ui.element('td').classes('p-3'):
                                            ui.button(
                                                'Open Case', icon='visibility',
                                                on_click=lambda fid=fir['id']: ui.navigate.to(
                                                    f'/verification/fir/{fid}'
                                                ),
                                            ).props('unelevated size=xs').classes(
                                                'bg-blue-800 hover:bg-blue-900 text-white rounded-lg '
                                                'px-3 py-1 font-bold'
                                            )

        render_firs()
        _listen(
            render_firs,
            ('COMPLAINT_VERIFICATION_UPDATED', 'COMPLAINT_UPDATED', 'FIR_UPDATED',
             'FIR_DOCUMENT_GENERATED'),
        )
        ui.timer(15.0, render_firs.refresh)


def _document_index() -> list:
    """Current FIR PDFs, used to show document availability in the registry."""
    from backend.services.db import get_db_connection

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT fir_id FROM fir_documents WHERE is_current = 1")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# ==========================================
# 4. OFFICER ASSIGNMENT & FIR REGISTRATION
# ==========================================
@ui.page('/verification/fir-register/{complaint_id}')
def fir_registration_page(complaint_id: str) -> None:
    user = require_verification_officer()
    if not user:
        return

    complaint = get_complaint_for_verification(complaint_id)
    if not complaint:
        with portal_page('verification', '/verification/firs', 'Complaint Not Found', ''):
            ui.label('This complaint could not be found.').classes('text-sm font-bold text-rose-700')
            ui.button('Back', on_click=lambda: ui.navigate.to('/verification/firs')).props('flat')
        return

    with portal_page(
        'verification',
        '/verification/firs',
        f"FIR Registration — {complaint.get('reference')}",
        'Confirm the verified complaint record, assign the investigating officer, and register the official FIR.',
    ):
        ui.button(
            '← Back', icon='arrow_back',
            on_click=lambda: ui.navigate.to(f"/verification/complaint/{complaint['id']}"),
        ).props('flat no-caps').classes('text-slate-600 font-bold text-xs')

        if complaint.get('fir_id') or complaint.get('verification_status') != 'VERIFIED':
            with ui.card().classes('w-full p-6 rounded-2xl bg-amber-50 border border-amber-300'):
                ui.label(
                    'This complaint is not eligible for FIR registration. Only verified complaints without '
                    'an existing FIR can be registered.'
                ).classes('text-sm font-bold text-amber-900')
            return

        # ── Officer review: edit the FIR details before registration ───────
        loaded = {column: (complaint.get(column) or '') for column in FIR_DETAIL_LABELS}
        snapshot = dict(loaded)
        fields: dict = {}
        category_options = list(COMPLAINT_CATEGORIES)
        if loaded['category'] and loaded['category'] not in category_options:
            category_options.append(loaded['category'])

        with ui.card().classes('w-full p-6 bg-white border-2 border-emerald-800/25 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 mb-1'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('edit_note', size='sm').classes('text-emerald-800')
                    ui.label('Review & Edit FIR Details Before Registration').classes(
                        'text-base font-bold text-slate-900 fantasy-title'
                    )
                ui.badge('OFFICER REVIEW').classes(
                    'bg-emerald-100 text-emerald-900 font-bold text-[10px] px-3 py-1'
                )
            ui.label(
                'Correct or complete the details the official FIR will carry. Saving writes them to the '
                'complaint record, appends them to the verification history and hands them to FIR '
                'registration. Accused and witness details stay on the police record and are never shown '
                'to the citizen. The draft document preview is built from the saved values.'
            ).classes('text-[11px] text-slate-600 leading-relaxed mb-4')

            def add_detail_field(column: str, kind: str, width: str) -> None:
                label = FIR_DETAIL_LABELS[column]
                if column in ('category', 'description', 'location'):
                    label = f'{label} *'
                if kind == 'select':
                    element = ui.select(category_options, value=loaded[column] or category_options[0], label=label)
                elif kind == 'textarea':
                    element = ui.textarea(label=label, value=loaded[column]).props('autogrow')
                else:
                    element = ui.input(label=label, value=loaded[column])
                element.props('outlined').classes(width)
                fields[column] = element

            with ui.row().classes('w-full gap-3 flex-wrap items-start'):
                add_detail_field('category', 'select', 'flex-1 min-w-44')
                add_detail_field('police_station', 'input', 'flex-1 min-w-44')
                add_detail_field('incident_date', 'input', 'flex-1 min-w-40')
                add_detail_field('incident_time', 'input', 'flex-1 min-w-32')

            with ui.row().classes('w-full gap-3 flex-wrap items-start mt-3'):
                add_detail_field('location', 'input', 'flex-1 min-w-52')
                add_detail_field('landmark', 'input', 'flex-1 min-w-40')
                add_detail_field('area', 'input', 'flex-1 min-w-36')
                add_detail_field('district', 'input', 'flex-1 min-w-36')
                add_detail_field('state', 'input', 'flex-1 min-w-36')

            with ui.column().classes('w-full gap-3 mt-3'):
                add_detail_field('description', 'textarea', 'w-full')
                add_detail_field('accused_details', 'textarea', 'w-full')
                add_detail_field('witness_details', 'textarea', 'w-full')

            def save_fir_details() -> None:
                payload = {column: element.value for column, element in fields.items()}
                try:
                    updated = update_fir_details_before_registration(complaint['id'], payload, user)
                except (PermissionError, ValueError) as error:
                    ui.notify(str(error), type='negative')
                    return
                except Exception as error:  # pragma: no cover - UI boundary
                    ui.notify(f'Could not save the FIR details: {error}', type='negative')
                    return
                for column, element in fields.items():
                    stored = updated.get(column) or ''
                    element.value = stored
                    snapshot[column] = stored
                status_label.text = (
                    f"Saved by {user.get('name') or 'Officer'} · {_fmt(updated.get('updated_at'))}"
                )
                ui.notify('FIR details saved. Registration will use these values.', type='positive')
                record_summary.refresh()

            def preview_draft_document() -> None:
                try:
                    pdf_bytes, file_name = render_draft_document_for_complaint(complaint['id'], user)
                except (PermissionError, ValueError) as error:
                    ui.notify(str(error), type='negative')
                    return
                except Exception as error:  # pragma: no cover - UI boundary
                    ui.notify(f'Draft preview failed: {error}', type='negative')
                    return
                encoded = base64.b64encode(pdf_bytes).decode('ascii')
                with ui.dialog() as dialog, ui.card().classes(
                    'w-full max-w-5xl p-4 gap-3 bg-white rounded-3xl shadow-2xl'
                ):
                    with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                        with ui.column().classes('gap-0'):
                            ui.label('Draft FIR Document — review before registration').classes(
                                'text-base font-bold text-slate-900 fantasy-title'
                            )
                            ui.label(
                                f'{file_name} · built from the values stored in the complaint record'
                            ).classes('text-[10px] text-slate-500 font-mono')
                        with ui.row().classes('gap-2'):
                            ui.button(
                                'Download Draft PDF', icon='download',
                                on_click=lambda: ui.download(pdf_bytes, file_name),
                            ).props('unelevated').classes(
                                'bg-slate-800 hover:bg-slate-900 text-white font-bold rounded-xl px-4 py-2 text-xs'
                            )
                            ui.button('Close', icon='close', on_click=dialog.close).props('flat').classes(
                                'text-slate-600 font-bold'
                            )
                    # the payload is a self-generated base64 PDF, so the markup is
                    # emitted verbatim instead of being stripped by the sanitiser
                    ui.html(
                        '<embed src="data:application/pdf;base64,' + encoded + '" type="application/pdf" '
                        'style="width:100%;height:70vh;border:1px solid #E2E8F0;border-radius:12px"></embed>',
                        sanitize=False,
                    )
                dialog.open()

            with ui.row().classes(
                'w-full items-center justify-between flex-wrap gap-3 mt-4 pt-3 border-t border-slate-100'
            ):
                status_label = ui.label('').classes('text-[11px] font-semibold text-slate-500')
                with ui.row().classes('gap-2 flex-wrap'):
                    ui.button('Save FIR Details', icon='save', on_click=save_fir_details).props(
                        'unelevated'
                    ).classes(
                        'bg-emerald-800 hover:bg-emerald-900 text-white font-bold rounded-xl px-5 py-2 text-xs'
                    )
                    ui.button(
                        'Preview Draft FIR Document', icon='picture_as_pdf',
                        on_click=preview_draft_document,
                    ).props('outline no-caps').classes(
                        'border-2 border-rose-700 text-rose-800 font-bold rounded-xl px-4 py-2 text-xs'
                    )

        @ui.refreshable
        def record_summary() -> None:
            record = get_complaint_for_verification(complaint['id']) or complaint
            for column, element in fields.items():
                stored = record.get(column) or ''
                if element.value == snapshot[column] and stored != snapshot[column]:
                    element.value = stored
                    snapshot[column] = stored

            with ui.card().classes(
                'flex-1 min-w-72 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
            ):
                with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                    ui.icon('fact_check', size='sm').classes('text-emerald-800')
                    ui.label('Verified Complaint Record').classes(
                        'text-base font-bold text-slate-900 fantasy-title'
                    )
                for label, value in [
                    ('Complaint Reference', record.get('reference') or 'Not recorded'),
                    ('Citizen', record.get('citizen_name') or record.get('applicant_name') or 'Not recorded'),
                    ('Citizen Username', record.get('citizen_username') or 'Not issued yet'),
                    ('Mobile', record.get('citizen_phone') or 'Not recorded'),
                    ('Category', record.get('category') or 'Not recorded'),
                    ('Incident Date / Time',
                     f"{record.get('incident_date') or '—'} {record.get('incident_time') or ''}".strip()),
                    ('Location', record.get('location') or 'Not recorded'),
                    ('District / State',
                     ', '.join(part for part in (record.get('district'), record.get('state')) if part)
                     or 'Not recorded'),
                    ('Police Station', record.get('police_station') or 'Not recorded'),
                    ('Verified By', record.get('verified_by_name') or 'Not recorded'),
                    ('Verified At', _fmt(record.get('verified_at'))),
                ]:
                    with ui.row().classes(
                        'w-full justify-between items-start gap-3 py-1.5 border-b border-slate-50'
                    ):
                        ui.label(label).classes('text-[10px] font-bold text-slate-500 uppercase shrink-0')
                        ui.label(str(value)).classes(
                            'text-[11px] font-semibold text-slate-900 text-right break-words'
                        )
                if record.get('fir_edited_at'):
                    ui.label(
                        f"Officer corrections saved by {record.get('fir_edited_by_name') or '—'} · "
                        f"{_fmt(record.get('fir_edited_at'))}"
                    ).classes('text-[10px] font-bold text-emerald-800 mt-2')
                ui.label('Complaint Description').classes(
                    'text-[10px] font-bold text-slate-500 uppercase mt-3'
                )
                ui.label(record.get('description') or '—').classes(
                    'text-xs text-slate-800 leading-relaxed whitespace-pre-line mt-1'
                )
                ui.label('Verification Remarks').classes(
                    'text-[10px] font-bold text-slate-500 uppercase mt-3'
                )
                ui.label(record.get('verification_remarks') or 'No remarks recorded.').classes(
                    'text-xs text-slate-700 leading-relaxed whitespace-pre-line'
                )

        with ui.row().classes('w-full gap-4 flex-wrap items-start'):
            record_summary()

            with ui.column().classes('flex-1 min-w-72 gap-4'):
                with ui.card().classes(
                    'w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
                ):
                    with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                        ui.icon('attach_file', size='sm').classes('text-emerald-800')
                        ui.label('Evidence').classes('text-base font-bold text-slate-900 fantasy-title')
                    render_evidence(complaint)

                with ui.card().classes(
                    'w-full p-6 bg-white border-2 border-blue-800/20 rounded-3xl shadow-sm'
                ):
                    with ui.row().classes('items-center gap-2 mb-2'):
                        ui.icon('assignment_ind', size='sm').classes('text-blue-800')
                        ui.label('Assign Investigating Officer').classes(
                            'text-base font-bold text-slate-900 fantasy-title'
                        )
                    ui.label(
                        'Only active Police Officer accounts are listed. The assignment stores the actual user ID, '
                        'notifies the officer and the citizen, and is carried into the registered FIR.'
                    ).classes('text-[11px] text-slate-500 mb-3')

                    officers = get_active_police_officers()
                    if not officers:
                        with ui.card().classes('w-full p-4 rounded-xl bg-rose-50 border border-rose-200'):
                            ui.label(
                                'No active police officer accounts exist. An officer account must be activated '
                                'before an FIR can be assigned.'
                            ).classes('text-xs font-bold text-rose-900')
                    else:
                        options = {
                            officer['id']: (
                                f"{officer.get('rank') or 'Officer'} {officer.get('name') or ''} · "
                                f"Badge {officer.get('badge_number') or 'N/A'} · "
                                f"{officer.get('station') or 'Station not recorded'}"
                            )
                            for officer in officers
                        }
                        default_officer = complaint.get('assigned_officer_id') or officers[0]['id']
                        officer_select = ui.select(
                            options=options,
                            value=default_officer if default_officer in options else officers[0]['id'],
                            label='Investigating Officer *',
                        ).props('outlined').classes('w-full')

                        status_label = ui.label('').classes(
                            'text-[11px] font-semibold text-slate-500 mt-1'
                        )

                        def save_assignment() -> None:
                            if not officer_select.value:
                                ui.notify('Select an investigating officer first.', type='warning')
                                return
                            try:
                                assign_officer_to_complaint(complaint['id'], officer_select.value, user)
                                ui.notify('Investigating officer assignment saved.', type='positive')
                                status_label.text = 'Assignment saved to the complaint record.'
                            except (PermissionError, ValueError) as error:
                                ui.notify(str(error), type='negative')
                            except Exception as error:  # pragma: no cover - UI boundary
                                ui.notify(f'Assignment failed: {error}', type='negative')

                        ui.button(
                            'Save Officer Assignment', icon='save', on_click=save_assignment,
                        ).props('unelevated').classes(
                            'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl px-4 py-2 text-xs mt-2'
                        )

                    ui.element('div').classes('w-full border-t border-slate-200 my-4')

                    ui.label('Register Official FIR').classes(
                        'text-sm font-black text-slate-900 uppercase tracking-wide'
                    )
                    ui.label(
                        'The FIR number is generated by the backend, is unique, carries no year component, and '
                        'cannot be duplicated. Registration is irreversible. A draft official PDF is generated '
                        'from the persisted record immediately afterwards.'
                    ).classes('text-[11px] text-slate-600 leading-relaxed mt-1 mb-3')

                    def confirm_register() -> None:
                        selected = officer_select.value if officers else None
                        if not selected:
                            ui.notify('Assign an investigating officer before registering the FIR.',
                                      type='warning')
                            return
                        with ui.dialog() as dialog, ui.card().classes(
                            'w-full max-w-md p-6 rounded-3xl bg-white shadow-2xl gap-3'
                        ):
                            ui.label('Register Official FIR?').classes(
                                'text-lg font-black text-slate-900 fantasy-title'
                            )
                            ui.label(
                                f"Complaint {complaint.get('reference')} will be converted into a registered FIR. "
                                'This action cannot be undone.'
                            ).classes('text-xs text-slate-600')
                            error_label = ui.label('').classes('text-xs text-rose-600 font-semibold')

                            def do_register() -> None:
                                try:
                                    current = get_complaint_for_verification(complaint['id']) or complaint
                                    if selected != current.get('assigned_officer_id'):
                                        assign_officer_to_complaint(complaint['id'], selected, user)
                                    result = create_fir_from_complaint(complaint['id'], user)
                                    fir_id = result['fir_id']
                                    try:
                                        generate_fir_pdf(fir_id, user)
                                    except Exception as pdf_error:  # PDF failure must not lose the FIR
                                        print(f"FIR PDF generation error: {pdf_error}")
                                    ui.notify(
                                        f"FIR {result['fir_number']} registered successfully.",
                                        type='positive',
                                    )
                                    dialog.close()
                                    ui.navigate.to(f'/verification/fir/{fir_id}')
                                except (ValueError, PermissionError) as error:
                                    error_label.text = f'⚠ {error}'
                                except Exception as error:  # pragma: no cover - UI boundary
                                    error_label.text = f'⚠ Registration failed: {error}'

                            with ui.row().classes('w-full justify-end gap-2 pt-2'):
                                ui.button('Cancel', on_click=dialog.close).props('flat').classes(
                                    'text-slate-600 font-bold'
                                )
                                ui.button('Register FIR', icon='gavel', on_click=do_register).props(
                                    'unelevated'
                                ).classes(
                                    'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl '
                                    'px-5 py-2 text-xs'
                                )
                        dialog.open()

                    ui.button(
                        'Register FIR & Generate PDF', icon='gavel', on_click=confirm_register,
                    ).props('unelevated').classes(
                        'bg-emerald-700 hover:bg-emerald-800 text-white font-black rounded-xl '
                        'px-6 py-3 text-sm shadow-md'
                    )

        # Another desk can verify, edit or register this complaint while the page is
        # open, so the record and the form follow the stored values without a reload.
        _listen(record_summary, ('COMPLAINT_UPDATED', 'COMPLAINT_VERIFICATION_UPDATED'))
        ui.timer(15.0, record_summary.refresh)


# ==========================================
# 5. FIR SCRUTINY, ASSIGNMENT & DOCUMENT
# ==========================================
def open_edit_and_format_fir_dialog(fir_id: str, fir: dict, user: dict, on_success=None):
    """Edit & format citizen-submitted FIR data into the official structured FIR format."""
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-4xl p-8 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-200 mb-4'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('fact_check', size='md').classes('text-emerald-800')
                with ui.column().classes('gap-0'):
                    ui.label(f"Edit & Format Structured FIR — {fir.get('fir_number')}").classes(
                        'text-2xl font-black text-slate-900 fantasy-title'
                    )
                    ui.label(
                        f"Tracking Ref: {fir.get('reference_number')} · "
                        f"Version v{fir.get('current_version', 1)}"
                    ).classes('text-xs text-slate-500 font-mono')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

        with ui.scroll_area().classes('w-full h-96 p-2'):
            with ui.column().classes('w-full gap-4 text-xs'):
                with ui.card().classes(
                    'w-full p-4 bg-emerald-50/60 border border-emerald-200 rounded-2xl'
                ):
                    ui.label('Complainant Information (From Citizen Submission)').classes(
                        'text-xs font-bold text-emerald-900 uppercase tracking-wider mb-2'
                    )
                    with ui.row().classes('w-full gap-6 flex-wrap text-slate-700'):
                        ui.label(f"Name: {fir.get('citizen_name', 'Unknown')}").classes(
                            'font-bold text-slate-900'
                        )
                        ui.label(f"Phone: {fir.get('citizen_phone', 'N/A')}").classes('font-mono')
                        ui.label(f"Email: {fir.get('citizen_email', 'N/A')}")
                        ui.label(f"Gov ID: {fir.get('gov_id_masked', 'XXXX-XXXX-XXXX')}")

                with ui.row().classes('w-full gap-4'):
                    type_options = ['Cyber Crime & Online Fraud', 'Financial Fraud / Cheating', 'Vehicle Theft',
                                    'House Burglary / Trespass', 'Mobile Snatching', 'Extortion / Threats',
                                    'Other Offence']
                    status_options = ['PENDING_VERIFICATION', 'VERIFIED', 'UNDER_REVIEW', 'UNDER_INVESTIGATION',
                                      'CHARGESHEET_FILED', 'NEEDS_CORRECTION', 'RESOLVED', 'CLOSED']
                    # A citizen files a case under a short category (Theft, Fraud, …) and the ledger can
                    # hold any registered status; NiceGUI rejects a stored value missing from its options.
                    if fir.get('incident_type') and fir['incident_type'] not in type_options:
                        type_options.append(fir['incident_type'])
                    if fir.get('status') and fir['status'] not in status_options:
                        status_options.append(fir['status'])
                    e_type = ui.select(
                        type_options,
                        label='Official Incident Classification *', value=fir.get('incident_type'),
                    ).classes('flex-1').props('outlined')
                    e_status = ui.select(
                        status_options,
                        label='Verification / Case Status *', value=fir.get('status'),
                    ).classes('flex-1').props('outlined')

                with ui.row().classes('w-full gap-4'):
                    e_date = ui.input(
                        'Incident Date (YYYY-MM-DD) *', value=fir.get('incident_date', '')
                    ).classes('flex-1').props('outlined')
                    e_time = ui.input(
                        'Incident Time (HH:MM) *', value=fir.get('incident_time', '')
                    ).classes('flex-1').props('outlined')

                e_station = ui.input(
                    'Police Jurisdiction Station *', value=fir.get('police_station') or ''
                ).classes('w-full').props('outlined')
                e_loc = ui.input(
                    'Incident Location / Address *', value=fir.get('incident_location', '')
                ).classes('w-full').props('outlined')
                e_desc = ui.textarea(
                    'Official Case Description / Formatted Incident Statement *',
                    value=fir.get('description', ''),
                ).classes('w-full').props('outlined rows=4')
                e_accused = ui.textarea(
                    'Accused / Suspect Details', value=fir.get('accused_details', '')
                ).classes('w-full').props('outlined rows=3')
                e_witness = ui.textarea(
                    'Witness Information & Reference Documents', value=fir.get('witness_details', '')
                ).classes('w-full').props('outlined rows=3')
                e_reason = ui.input(
                    'Scrutiny Audit Memo / Change Reason (optional)',
                    value='Formatted structured FIR & verified incident parameters',
                ).classes('w-full').props('outlined')

        def save_edited_fir():
            if not e_loc.value or not e_desc.value:
                ui.notify('Please provide location and description.', type='warning')
                return
            reason = (e_reason.value or '').strip()
            updated_dict = {
                'incident_type': e_type.value,
                'status': e_status.value,
                'incident_date': e_date.value,
                'incident_time': e_time.value,
                'police_station': e_station.value,
                'incident_location': e_loc.value.strip(),
                'description': e_desc.value.strip(),
                'accused_details': e_accused.value.strip() if e_accused.value else '',
                'witness_details': e_witness.value.strip() if e_witness.value else '',
            }
            try:
                update_fir(
                    fir_id=fir_id, actor_user=user, updated_fields=updated_dict,
                    change_reason=reason,
                )
                try:
                    log_officer_activity(
                        user=user, action_type='FIR_EDITED', fir_id=fir_id,
                        fir_number=fir.get('fir_number', fir_id),
                        status_from=fir.get('status'),
                        status_to=updated_dict.get('status', fir.get('status')),
                        details=f"Verification Officer {user.get('name')} edited and structured FIR. "
                                f"Reason: {reason or 'Not provided'}",
                    )
                except Exception:
                    pass
                ui.notify(f"✓ FIR {fir.get('fir_number')} formatted and saved.", type='positive')
                dialog.close()
                if on_success:
                    on_success()
                else:
                    ui.navigate.to(f'/verification/fir/{fir_id}')
            except Exception as ex:
                ui.notify(f'Failed to update FIR: {ex}', type='negative')

        with ui.row().classes('w-full justify-between items-center mt-6 pt-4 border-t border-slate-200'):
            ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-slate-600 font-bold')
            ui.button('Save Structured FIR', icon='save', on_click=save_edited_fir).props(
                'unelevated'
            ).classes(
                'bg-emerald-800 hover:bg-emerald-900 text-white font-bold rounded-xl px-8 py-2.5 shadow-md'
            )
    dialog.open()


def open_assign_officer_dialog(fir_id: str, fir: dict, user: dict, on_success=None):
    """Assign or reassign the investigating officer from active OFFICER accounts."""
    officers = get_active_police_officers()

    with ui.dialog() as dialog, ui.card().classes('w-full max-w-2xl p-8 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-200 mb-4'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('assignment_ind', size='md').classes('text-blue-800')
                with ui.column().classes('gap-0'):
                    ui.label('Assign Investigating Police Officer').classes(
                        'text-2xl font-black text-slate-900 fantasy-title'
                    )
                    ui.label(
                        f"Case File: {fir.get('fir_number')} ({fir.get('incident_type') or 'FIR'})"
                    ).classes('text-xs text-slate-500 font-mono')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

        if not officers:
            ui.label('No active police officers found in the system.').classes(
                'text-rose-600 text-sm font-bold my-4'
            )
        else:
            ui.label(
                'Select from active Police Officer accounts. Previous assignments are preserved in history.'
            ).classes('text-xs font-bold text-slate-700 uppercase mb-3')
            officer_options = {
                officer['id']: (
                    f"{officer.get('rank') or 'Officer'} {officer.get('name')} · "
                    f"Badge {officer.get('badge_number') or 'N/A'} "
                    f"({officer.get('station') or 'Station not recorded'})"
                )
                for officer in officers
            }
            current = fir.get('assigned_officer_id')
            officer_select = ui.select(
                options=officer_options,
                value=current if current in officer_options else officers[0]['id'],
                label='Investigating Officer *',
            ).classes('w-full mb-4').props('outlined')

            def confirm_assignment():
                if not officer_select.value:
                    ui.notify('Please select an officer.', type='warning')
                    return
                try:
                    if not assign_officer_to_fir(fir_id, officer_select.value, user):
                        ui.notify('Failed to assign officer.', type='negative')
                        return
                    ui.notify(
                        f"✓ Assigned {officer_options.get(officer_select.value, 'officer')} to FIR "
                        f"{fir.get('fir_number')}. Officer and citizen notified.",
                        type='positive',
                    )
                    dialog.close()
                    if on_success:
                        on_success()
                    else:
                        ui.navigate.to(f'/verification/fir/{fir_id}')
                except Exception as ex:
                    ui.notify(f'Error: {ex}', type='negative')

            with ui.row().classes(
                'w-full justify-between items-center mt-6 pt-4 border-t border-slate-200'
            ):
                ui.button('Cancel', on_click=dialog.close).props('flat').classes(
                    'text-slate-600 font-bold'
                )
                ui.button('Confirm Officer Assignment', icon='check_circle', on_click=confirm_assignment).props(
                    'unelevated'
                ).classes(
                    'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl px-8 py-2.5 shadow-md'
                )
    dialog.open()


def open_return_fir_dialog(fir_id: str, fir: dict, user: dict, on_success=None):
    """Return FIR for correction by citizen."""
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-xl p-8 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-4 border-b border-amber-200 mb-4'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('undo', size='md').classes('text-amber-700')
                with ui.column().classes('gap-0'):
                    ui.label('Return FIR for Correction').classes(
                        'text-2xl font-black text-amber-900 fantasy-title'
                    )
                    ui.label(
                        f"FIR File: {fir.get('fir_number')} · "
                        f"Complainant: {fir.get('citizen_name', 'Citizen')}"
                    ).classes('text-xs text-slate-600 font-mono')
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

        ui.label('State the reason for returning this FIR to the citizen.').classes(
            'text-xs text-slate-600 mb-3'
        )
        reason_input = ui.textarea(
            'Return / Rejection Reason *',
            placeholder='E.g. Please provide the exact street address and attach the supporting document...',
        ).classes('w-full').props('outlined rows=4')

        def handle_return():
            if not reason_input.value or not reason_input.value.strip():
                ui.notify('Please state a reason for return.', type='warning')
                return
            try:
                reject_fir(fir_id, user, reason_input.value.strip())
                ui.notify(
                    f"✓ FIR {fir.get('fir_number')} returned to citizen with notification.", type='warning'
                )
                dialog.close()
                if on_success:
                    on_success()
                else:
                    ui.navigate.to('/verification/firs')
            except Exception as ex:
                ui.notify(f'Error returning FIR: {ex}', type='negative')

        with ui.row().classes('w-full justify-between items-center mt-6 pt-4 border-t border-slate-200'):
            ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-slate-600 font-bold')
            ui.button('Return FIR to Citizen', icon='send', on_click=handle_return).props(
                'unelevated'
            ).classes(
                'bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl px-6 py-2.5 shadow-md'
            )
    dialog.open()


@ui.page('/verification/fir/{fir_id}')
def verification_fir_detail_page(fir_id: str) -> None:
    user = require_verification_officer()
    if not user:
        return

    try:
        fir = get_fir_by_id(fir_id, actor_user=user)
    except PermissionError:
        fir = None

    if not fir:
        with portal_page('verification', '/verification/firs', 'FIR Not Found', ''):
            ui.label('This FIR could not be found or is not accessible.').classes(
                'text-sm font-bold text-rose-700'
            )
            ui.button('Back to FIRs', on_click=lambda: ui.navigate.to('/verification/firs')).props('flat')
        return

    st = fir.get('status', 'PENDING_VERIFICATION')
    complaint_id = fir.get('complaint_id')

    with portal_page(
        'verification', '/verification/firs',
        f"Scrutiny: {fir.get('fir_number')}", f"Status: {st}",
    ):
        ui.button(
            '← Back to Verify Your FIR', icon='arrow_back',
            on_click=lambda: ui.navigate.to('/verification/firs'),
        ).props('flat no-caps').classes('text-slate-600 font-bold text-xs mb-1')

        @ui.refreshable
        def render_case() -> None:
            record = get_fir_by_id(fir_id, actor_user=user)
            if not record:
                ui.label('This FIR is no longer available.').classes('text-sm font-bold text-rose-700')
                return
            status = record.get('status', 'PENDING_VERIFICATION')
            current_doc = get_current_document(fir_id)
            documents = list_documents(fir_id)
            assignment_history = get_officer_assignment_history(fir_id)

            with ui.card().classes(
                'w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'
            ):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-4 pb-4 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('policy', size='lg').classes('text-emerald-800')
                        with ui.column().classes('gap-0'):
                            ui.label(
                                f"FIR Scrutiny & Formation File — {record.get('fir_number')}"
                            ).classes('text-2xl font-black text-slate-900 fantasy-title')
                            ui.label(
                                f"Tracking Ref: {record.get('reference_number')} · Created: "
                                f"{_fmt(record.get('created_at'), with_time=False)}"
                            ).classes('text-xs text-slate-500 font-mono')
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        fir_status_badge(status)
                        if status != 'VERIFIED':
                            def handle_verif_click():
                                try:
                                    verify_fir(fir_id, user)
                                    ui.notify(
                                        f"✓ FIR {record.get('fir_number')} verified.", type='positive'
                                    )
                                    ui.navigate.to(f'/verification/fir/{fir_id}')
                                except Exception as ex:
                                    ui.notify(f'Error: {ex}', type='negative')

                            ui.button('Verify FIR', icon='verified', on_click=handle_verif_click).props(
                                'unelevated'
                            ).classes(
                                'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl '
                                'px-4 py-2.5 text-xs'
                            )
                        ui.button(
                            'Edit & Format', icon='edit',
                            on_click=lambda: open_edit_and_format_fir_dialog(
                                fir_id, record, user,
                                lambda: ui.navigate.to(f'/verification/fir/{fir_id}'),
                            ),
                        ).props('unelevated').classes(
                            'bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl '
                            'px-4 py-2.5 text-xs'
                        )
                        ui.button(
                            'Assign / Reassign Officer', icon='assignment_ind',
                            on_click=lambda: open_assign_officer_dialog(
                                fir_id, record, user,
                                lambda: ui.navigate.to(f'/verification/fir/{fir_id}'),
                            ),
                        ).props('unelevated').classes(
                            'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl '
                            'px-4 py-2.5 text-xs'
                        )
                        if status in ('PENDING_VERIFICATION', 'SUBMITTED', 'UNDER_REVIEW'):
                            ui.button(
                                'Return to Citizen', icon='undo',
                                on_click=lambda: open_return_fir_dialog(
                                    fir_id, record, user,
                                    lambda: ui.navigate.to('/verification/firs'),
                                ),
                            ).props('unelevated').classes(
                                'bg-rose-700 hover:bg-rose-800 text-white font-bold rounded-xl '
                                'px-4 py-2.5 text-xs'
                            )
                        if complaint_id:
                            ui.button(
                                'Open Complaint', icon='report_problem',
                                on_click=lambda cid=complaint_id: ui.navigate.to(
                                    f'/verification/complaint/{cid}'
                                ),
                            ).props('flat').classes('text-slate-600 font-bold text-xs')

            with ui.row().classes('w-full gap-4 flex-wrap items-start'):
                with ui.card().classes(
                    'flex-1 min-w-72 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
                ):
                    with ui.row().classes(
                        'items-center justify-between mb-3 pb-2 border-b border-slate-100'
                    ):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('local_police', size='sm').classes('text-blue-800')
                            ui.label('Investigating Officer').classes(
                                'text-base font-bold text-slate-900 fantasy-title'
                            )
                        ui.button(
                            'Reassign', icon='swap_horiz',
                            on_click=lambda: open_assign_officer_dialog(
                                fir_id, record, user,
                                lambda: ui.navigate.to(f'/verification/fir/{fir_id}'),
                            ),
                        ).props('flat dense no-caps').classes(
                            'text-blue-800 font-bold text-[10px]'
                        )
                    if record.get('officer_name'):
                        ui.label(
                            f"{record.get('officer_rank') or 'Officer'} {record.get('officer_name')}"
                        ).classes('text-sm font-black text-slate-900')
                        ui.label(
                            f"Badge {record.get('officer_badge') or 'N/A'} · Station "
                            f"{record.get('officer_station') or record.get('police_station') or 'Not recorded'}"
                        ).classes('text-[11px] text-slate-500 font-mono')
                    else:
                        ui.label('No investigating officer assigned.').classes(
                            'text-xs font-bold text-amber-700'
                        )
                    if assignment_history:
                        ui.label('Assignment History').classes(
                            'text-[10px] font-bold text-slate-500 uppercase mt-4 mb-1'
                        )
                        with ui.column().classes('w-full gap-1'):
                            for item in assignment_history:
                                with ui.row().classes(
                                    'w-full justify-between items-start gap-2 p-2 rounded-lg '
                                    'bg-slate-50 border border-slate-200'
                                ):
                                    with ui.column().classes('gap-0'):
                                        ui.label(
                                            f"{item.get('officer_rank') or 'Officer'} "
                                            f"{item.get('officer_name') or '—'}"
                                        ).classes('text-[11px] font-bold text-slate-800')
                                        ui.label(
                                            f"By {item.get('assigned_by_name') or 'System'} · "
                                            f"{_fmt(item.get('assigned_at'))}"
                                        ).classes('text-[9px] text-slate-500 font-mono')
                                    ui.badge(item.get('status') or '').classes(
                                        'bg-slate-200 text-slate-700 font-bold text-[9px]'
                                    )

                with ui.card().classes(
                    'flex-1 min-w-72 p-6 bg-white border border-emerald-800/20 rounded-3xl shadow-sm'
                ):
                    with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                        ui.icon('picture_as_pdf', size='sm').classes('text-rose-700')
                        ui.label('Official FIR Document').classes(
                            'text-base font-bold text-slate-900 fantasy-title'
                        )
                    if current_doc:
                        ui.label(
                            f"Version v{current_doc.get('version')} · {current_doc.get('file_name')}"
                        ).classes('text-xs font-bold text-slate-900 font-mono')
                        ui.label(
                            f"Generated by {current_doc.get('generated_by_name') or '—'} · "
                            f"{_fmt(current_doc.get('generated_at'))}"
                        ).classes('text-[10px] text-slate-500')
                        with ui.row().classes('gap-2 mt-3 flex-wrap'):
                            def download_pdf() -> None:
                                data = read_document_bytes(current_doc)
                                if not data:
                                    ui.notify(
                                        'The stored document file is no longer available.', type='warning'
                                    )
                                    return
                                ui.download(data, current_doc.get('file_name') or 'FIR.pdf')

                            ui.button('Download FIR PDF', icon='download', on_click=download_pdf).props(
                                'unelevated'
                            ).classes(
                                'bg-slate-800 hover:bg-slate-900 text-white font-bold rounded-xl '
                                'px-4 py-2 text-xs'
                            )

                            def regenerate_pdf() -> None:
                                try:
                                    result = generate_fir_pdf(fir_id, user, force=True)
                                    ui.notify(
                                        f"New FIR PDF version v{result['document'].get('version')} generated.",
                                        type='positive',
                                    )
                                    ui.navigate.to(f'/verification/fir/{fir_id}')
                                except (PermissionError, ValueError) as error:
                                    ui.notify(str(error), type='negative')
                                except Exception as error:  # pragma: no cover - UI boundary
                                    ui.notify(f'PDF regeneration failed: {error}', type='negative')

                            ui.button(
                                'Regenerate from Latest Record', icon='refresh', on_click=regenerate_pdf,
                            ).props('flat').classes('text-emerald-800 font-bold rounded-xl px-3 py-2 text-xs')
                    else:
                        ui.label(
                            'No official document has been generated for this FIR yet. Generation uses only '
                            'the persisted FIR record and is clearly marked as a draft pending authorised approval.'
                        ).classes('text-[11px] text-slate-500 leading-relaxed mb-3')

                        def generate_now() -> None:
                            try:
                                result = generate_fir_pdf(fir_id, user)
                                ui.notify(
                                    'FIR PDF generated.' if result.get('created')
                                    else 'Existing FIR PDF opened.',
                                    type='positive',
                                )
                                ui.navigate.to(f'/verification/fir/{fir_id}')
                            except (PermissionError, ValueError) as error:
                                ui.notify(str(error), type='negative')
                            except Exception as error:  # pragma: no cover - UI boundary
                                ui.notify(f'PDF generation failed: {error}', type='negative')

                        ui.button(
                            'Generate Official FIR PDF', icon='picture_as_pdf', on_click=generate_now,
                        ).props('unelevated').classes(
                            'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl '
                            'px-4 py-2 text-xs'
                        )
                    if len(documents) > 1:
                        ui.label('Document Version History').classes(
                            'text-[10px] font-bold text-slate-500 uppercase mt-4 mb-1'
                        )
                        with ui.column().classes('w-full gap-1'):
                            for doc in documents:
                                with ui.row().classes('w-full justify-between items-center gap-2'):
                                    ui.label(
                                        f"v{doc.get('version')} · {_fmt(doc.get('generated_at'))}"
                                    ).classes('text-[10px] text-slate-600 font-mono')
                                    if doc.get('is_current'):
                                        ui.badge('CURRENT').classes(
                                            'bg-emerald-100 text-emerald-900 text-[9px] font-bold'
                                        )

            with ui.card().classes(
                'w-full p-8 paper-card bg-slate-50 border-2 border-emerald-800/30 rounded-3xl shadow-md'
            ):
                with ui.row().classes(
                    'w-full items-center justify-between pb-4 border-b-2 border-slate-300 mb-6'
                ):
                    with ui.row().classes('items-center gap-4'):
                        ui.icon('gavel', size='lg').classes('text-emerald-900')
                        with ui.column().classes('gap-0'):
                            ui.label('STATE POLICE DEPARTMENT · FIRST INFORMATION REPORT').classes(
                                'text-lg font-black text-slate-900 tracking-wider'
                            )
                            ui.label(
                                'Under Section 154 Cr.P.C. / Section 173 Bharatiya Nagarik Suraksha '
                                'Sanhita (BNSS)'
                            ).classes('text-xs text-slate-600 font-semibold')
                    ui.badge(f"SYSTEM-GENERATED · v{record.get('current_version', 1)}").classes(
                        'bg-emerald-900 text-white font-mono font-bold text-xs px-3 py-1'
                    )

                with ui.column().classes('w-full gap-6 text-xs text-slate-800'):
                    with ui.row().classes(
                        'w-full bg-white p-4 rounded-xl border border-slate-200 gap-6 flex-wrap'
                    ):
                        with ui.column().classes('flex-1 min-w-40 gap-1'):
                            ui.label('1. Official FIR Number:').classes(
                                'font-bold text-slate-500 uppercase text-[10px]'
                            )
                            ui.label(record.get('fir_number')).classes(
                                'font-mono font-black text-base text-slate-900'
                            )
                        with ui.column().classes('flex-1 min-w-40 gap-1'):
                            ui.label('2. Citizen Tracking Reference:').classes(
                                'font-bold text-slate-500 uppercase text-[10px]'
                            )
                            ui.label(record.get('reference_number')).classes(
                                'font-mono font-bold text-sm text-slate-900'
                            )
                        with ui.column().classes('flex-1 min-w-40 gap-1'):
                            ui.label('3. Police Station Jurisdiction:').classes(
                                'font-bold text-slate-500 uppercase text-[10px]'
                            )
                            ui.label(record.get('police_station')).classes(
                                'font-bold text-sm text-slate-900'
                            )
                        with ui.column().classes('flex-1 min-w-40 gap-1'):
                            ui.label('4. Registration Date & Time:').classes(
                                'font-bold text-slate-500 uppercase text-[10px]'
                            )
                            ui.label(_fmt(record.get('created_at'))).classes(
                                'font-bold text-sm text-slate-900 font-mono'
                            )

                    with ui.card().classes('w-full bg-white p-4 rounded-xl border border-slate-200'):
                        ui.label('5. Complainant / Informant Details').classes(
                            'font-black text-slate-900 uppercase text-xs mb-2 pb-1 border-b border-slate-100'
                        )
                        with ui.row().classes('w-full gap-6 flex-wrap'):
                            with ui.column().classes('flex-1 min-w-40 gap-0.5'):
                                ui.label('Full Name:').classes('text-slate-500 font-semibold')
                                ui.label(record.get('citizen_name', 'Unknown')).classes(
                                    'font-bold text-slate-900'
                                )
                            with ui.column().classes('flex-1 min-w-40 gap-0.5'):
                                ui.label('Contact Number:').classes('text-slate-500 font-semibold')
                                ui.label(record.get('citizen_phone', 'N/A')).classes(
                                    'font-bold text-slate-900 font-mono'
                                )
                            with ui.column().classes('flex-1 min-w-40 gap-0.5'):
                                ui.label('Email Address:').classes('text-slate-500 font-semibold')
                                ui.label(record.get('citizen_email', 'N/A')).classes(
                                    'font-bold text-slate-900'
                                )
                            with ui.column().classes('flex-1 min-w-40 gap-0.5'):
                                ui.label('Masked Gov Identification:').classes(
                                    'text-slate-500 font-semibold'
                                )
                                ui.label(record.get('gov_id_masked', 'XXXX-XXXX-XXXX')).classes(
                                    'font-bold text-slate-900 font-mono'
                                )
                        if record.get('citizen_address'):
                            ui.label(
                                f"Residential Address: {record.get('citizen_address')}"
                            ).classes('text-xs text-slate-600 mt-2')

                    with ui.card().classes('w-full bg-white p-4 rounded-xl border border-slate-200'):
                        ui.label('6. Incident Classification & Location Matrix').classes(
                            'font-black text-slate-900 uppercase text-xs mb-2 pb-1 border-b border-slate-100'
                        )
                        with ui.row().classes('w-full gap-6 flex-wrap'):
                            for label, value in [
                                ('Offence Category', record.get('incident_type')),
                                ('Incident Date & Time',
                                 f"{record.get('incident_date')} at {record.get('incident_time')}"),
                                ('Exact Location of Occurrence', record.get('incident_location')),
                            ]:
                                with ui.column().classes('flex-1 min-w-40 gap-0.5'):
                                    ui.label(f'{label}:').classes('text-slate-500 font-semibold')
                                    ui.label(value or '—').classes(
                                        'font-bold text-slate-900 text-sm'
                                    )

                    with ui.card().classes('w-full bg-white p-4 rounded-xl border border-slate-200'):
                        ui.label('7. Official Case Description & Statement of Fact').classes(
                            'font-black text-slate-900 uppercase text-xs mb-2 pb-1 border-b border-slate-100'
                        )
                        ui.label(record.get('description', '')).classes(
                            'text-xs text-slate-800 leading-relaxed whitespace-pre-line font-medium'
                        )

                    with ui.row().classes('w-full gap-4 flex-wrap'):
                        with ui.card().classes(
                            'flex-1 min-w-64 bg-white p-4 rounded-xl border border-slate-200'
                        ):
                            ui.label('8. Suspect / Accused Details').classes(
                                'font-black text-slate-900 uppercase text-xs mb-2 pb-1 '
                                'border-b border-slate-100'
                            )
                            ui.label(
                                record.get('accused_details') or 'None specified / Under investigation'
                            ).classes('text-xs text-slate-800')
                        with ui.card().classes(
                            'flex-1 min-w-64 bg-white p-4 rounded-xl border border-slate-200'
                        ):
                            ui.label('9. Witness & Evidence References').classes(
                                'font-black text-slate-900 uppercase text-xs mb-2 pb-1 '
                                'border-b border-slate-100'
                            )
                            ui.label(record.get('witness_details') or 'None provided').classes(
                                'text-xs text-slate-800'
                            )

                    with ui.card().classes(
                        'w-full bg-emerald-50/70 p-4 rounded-xl border border-emerald-300'
                    ):
                        ui.label('10. Departmental Verification & Officer Assignment Seal').classes(
                            'font-black text-emerald-950 uppercase text-xs mb-2 pb-1 border-b border-emerald-200'
                        )
                        with ui.row().classes(
                            'w-full justify-between items-center flex-wrap gap-4'
                        ):
                            with ui.column().classes('gap-1'):
                                ui.label('Verification Bureau Officer:').classes(
                                    'text-[10px] font-bold text-emerald-800 uppercase'
                                )
                                ui.label(
                                    f"{user.get('rank') or 'Verification Officer'} "
                                    f"{user.get('name', 'Officer')} ({user.get('badge_number') or 'N/A'})"
                                ).classes('font-bold text-emerald-950')
                            with ui.column().classes('gap-1'):
                                ui.label('Assigned Investigating Officer:').classes(
                                    'text-[10px] font-bold text-blue-800 uppercase'
                                )
                                if record.get('officer_name'):
                                    ui.label(
                                        " ".join(part for part in (
                                            record.get('officer_rank'),
                                            record.get('officer_name'),
                                            f"({record.get('officer_badge') or 'Badge not recorded'})",
                                        ) if part)
                                    ).classes('font-bold text-blue-950')
                                else:
                                    ui.label('No Officer Assigned Yet').classes(
                                        'text-amber-800 italic font-semibold'
                                    )

            with ui.card().classes(
                'w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'
            ):
                with ui.row().classes('w-full items-center gap-3 mb-4'):
                    ui.icon('timeline', size='md').classes('text-emerald-800')
                    ui.label('Case Progress & Officer Activity Timeline').classes(
                        'text-lg font-bold text-slate-900 fantasy-title'
                    )
                events = get_operational_case_timeline(fir_id, actor_user=user)
                if not events:
                    ui.label('No case activity recorded yet.').classes('text-xs text-slate-500')
                else:
                    for event in events:
                        colour = event.get('color', 'blue')
                        with ui.row().classes('w-full items-start gap-4 mb-3'):
                            with ui.element('div').classes(
                                f'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center '
                                f'shadow-sm bg-{colour}-700 text-white'
                            ):
                                ui.icon(event.get('icon', 'info'), size='xs')
                            with ui.card().classes(
                                'flex-1 p-4 rounded-2xl border border-slate-200 bg-slate-50 shadow-xs'
                            ):
                                with ui.row().classes(
                                    'w-full justify-between items-start flex-wrap gap-1'
                                ):
                                    ui.label(event.get('title', '')).classes(
                                        'font-bold text-slate-900 text-sm flex-1'
                                    )
                                    ui.label(str(event.get('timestamp', ''))).classes(
                                        'text-[10px] text-slate-500 font-mono shrink-0'
                                    )
                                ui.label(event.get('description', '')).classes(
                                    'text-xs text-slate-700 mt-1 leading-relaxed'
                                )

        render_case()
        _listen(render_case, ('FIR_UPDATED', 'FIR_DOCUMENT_GENERATED', 'CASE_STAGE_UPDATED'))


# ==========================================
# 6. VERIFICATION HISTORY & AUDIT
# ==========================================
@ui.page('/verification/history')
def verification_history_page() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification', '/verification/history',
        'Verification History & Audit',
        'Append-only record of every citizen and complaint verification decision.',
    ):
        @ui.refreshable
        def render_history() -> None:
            records = get_verification_history(limit=300)
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('history', size='sm').classes('text-emerald-800')
                    ui.label('Recorded Verification Decisions').classes(
                        'text-lg font-bold text-slate-900 fantasy-title'
                    )
                ui.badge(f'{len(records)} records').classes(
                    'bg-slate-200 text-slate-800 font-bold text-xs'
                )

            if not records:
                with ui.card().classes(
                    'w-full p-10 rounded-2xl bg-white border border-slate-200 shadow-xs'
                ):
                    ui.label('No verification history has been recorded yet.').classes(
                        'text-sm font-bold text-slate-600 text-center w-full'
                    )
                return

            with ui.element('div').classes('w-full overflow-x-auto'):
                with ui.element('table').classes('w-full text-left text-xs border-collapse'):
                    with ui.element('thead').classes(
                        'bg-slate-100 text-slate-700 border-b border-slate-200'
                    ):
                        with ui.element('tr'):
                            for col in ('Reference', 'Citizen / Subject', 'Type', 'Decision', 'Officer',
                                        'Timestamp', 'Current Status', 'Open'):
                                ui.element('th').classes('p-3 font-bold').text = col
                    with ui.element('tbody').classes('divide-y divide-slate-200'):
                        for row in records:
                            with ui.element('tr').classes('hover:bg-slate-50 align-top'):
                                with ui.element('td').classes(
                                    'p-3 font-mono font-bold text-slate-900'
                                ):
                                    ui.label(row.get('reference') or '—')
                                with ui.element('td').classes('p-3'):
                                    ui.label(row.get('subject') or '—').classes(
                                        'font-semibold text-slate-800'
                                    )
                                    if row.get('remarks'):
                                        ui.label(str(row['remarks'])[:120]).classes(
                                            'text-[10px] text-slate-500 mt-1 leading-relaxed'
                                        )
                                with ui.element('td').classes('p-3'):
                                    ui.label(row.get('verification_type') or '—').classes(
                                        'text-slate-700 font-semibold'
                                    )
                                with ui.element('td').classes('p-3'):
                                    ui.label(
                                        str(row.get('decision') or '—').replace('_', ' ').title()
                                    ).classes('text-slate-800 font-bold')
                                with ui.element('td').classes('p-3'):
                                    ui.label(row.get('actor_name') or '—').classes(
                                        'font-semibold text-slate-800'
                                    )
                                    ui.label(
                                        f"{row.get('actor_role') or ''}"
                                        + (f" · {row.get('actor_badge')}"
                                           if row.get('actor_badge') and row.get('actor_badge') != 'N/A'
                                           else '')
                                    ).classes('text-[9px] text-slate-500 font-mono')
                                with ui.element('td').classes(
                                    'p-3 font-mono text-[10px] text-slate-600'
                                ):
                                    ui.label(_fmt(row.get('created_at')))
                                with ui.element('td').classes('p-3'):
                                    ui.label(
                                        str(row.get('current_status') or '—').replace('_', ' ').title()
                                    ).classes('text-[10px] font-bold text-slate-600')
                                with ui.element('td').classes('p-3'):
                                    ui.button(
                                        'Open', icon='open_in_new',
                                        on_click=lambda t=row.get('target'): ui.navigate.to(t),
                                    ).props('flat dense no-caps size=xs').classes(
                                        'text-emerald-800 font-bold text-[10px]'
                                    )

        render_history()
        _listen(
            render_history,
            ('COMPLAINT_VERIFICATION_UPDATED', 'CITIZEN_APPLICATION_UPDATED', 'FIR_UPDATED'),
        )
        ui.timer(20.0, render_history.refresh)


# ==========================================
# 7. NOTIFICATIONS
# ==========================================
@ui.page('/verification/notifications')
def verification_notifications_page() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification', '/verification/notifications',
        'Verification Officer Inbox',
        'Real events only — new registrations, complaint decisions, FIR registrations and assignments.',
    ):
        @ui.refreshable
        def render_notifications() -> None:
            notifications = get_user_notifications(user['id'], limit=100)
            unread = get_unread_count(user['id'])

            with ui.card().classes(
                'w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'
            ):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-2 pb-4 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('notifications', size='md').classes('text-emerald-800')
                        ui.label('Verification Inbox Alerts').classes(
                            'text-2xl font-bold text-slate-900 fantasy-title'
                        )
                        if unread:
                            ui.badge(f'{unread} Unread').classes(
                                'bg-amber-500 text-slate-950 font-bold text-xs px-2.5 py-0.5 rounded-full'
                            )

                    if notifications:
                        def handle_read_all() -> None:
                            mark_all_read(user['id'])
                            ui.notify('All notifications marked as read.', type='positive')
                            render_notifications.refresh()

                        ui.button('Mark All Read', icon='done_all', on_click=handle_read_all).props(
                            'flat size=sm'
                        ).classes('text-emerald-900 font-bold text-xs')

                if not notifications:
                    with ui.column().classes(
                        'w-full items-center py-16 gap-3 text-slate-400 text-center'
                    ):
                        ui.icon('notifications_none', size='xl')
                        ui.label('No verification notifications received yet.').classes(
                            'text-base font-semibold text-slate-600'
                        )
                else:
                    with ui.column().classes('w-full gap-3 mt-4'):
                        for notification in notifications:
                            is_read = notification.get('is_read', 0) == 1
                            card_bg = (
                                'bg-slate-50 border-slate-200 opacity-80'
                                if is_read else 'bg-emerald-50/70 border-emerald-200'
                            )
                            with ui.card().classes(
                                f'w-full p-5 rounded-2xl border {card_bg} shadow-xs'
                            ):
                                with ui.row().classes('w-full items-start gap-4'):
                                    ui.icon(
                                        'mark_email_unread' if not is_read else 'mail', size='sm'
                                    ).classes('text-emerald-800 mt-1')
                                    with ui.column().classes('gap-1 flex-1'):
                                        with ui.row().classes(
                                            'w-full items-center justify-between flex-wrap gap-2'
                                        ):
                                            ui.label(
                                                notification.get('title', 'Notification')
                                            ).classes('text-base font-bold text-slate-900')
                                            ui.label(_fmt(notification.get('created_at'))).classes(
                                                'text-[10px] text-slate-400 font-mono'
                                            )
                                        ui.label(notification.get('message', '')).classes(
                                            'text-xs text-slate-800 whitespace-pre-line '
                                            'leading-relaxed font-medium mt-1'
                                        )
                                        with ui.row().classes(
                                            'items-center gap-2 flex-wrap mt-1'
                                        ):
                                            if notification.get('fir_number'):
                                                ui.label(
                                                    f"FIR: {notification.get('fir_number')}"
                                                ).classes(
                                                    'text-[10px] font-bold text-slate-500 font-mono'
                                                )
                                            if notification.get('complaint_reference'):
                                                ui.label(
                                                    f"Complaint: "
                                                    f"{notification.get('complaint_reference')}"
                                                ).classes(
                                                    'text-[10px] font-bold text-slate-500 font-mono'
                                                )
                                            if not is_read:
                                                def mark_one(nid=notification['id']) -> None:
                                                    mark_notification_read(nid, user['id'])
                                                    render_notifications.refresh()

                                                ui.button(
                                                    'Mark as Read', icon='done', on_click=mark_one,
                                                ).props('flat dense no-caps size=xs').classes(
                                                    'text-emerald-800 font-bold text-[10px]'
                                                )

        render_notifications()
        _listen(
            render_notifications,
            ('NOTIFICATION_CREATED', 'NOTIFICATION_UPDATED'),
            on_event=lambda event: (
                render_notifications.refresh()
                if event.get('user_id') == user['id'] else None
            ),
        )
        ui.timer(20.0, render_notifications.refresh)


# ==========================================
# 8. PROFILE
# ==========================================
@ui.page('/verification/profile')
def verification_profile_page() -> None:
    user = require_verification_officer()
    if not user:
        return

    with portal_page(
        'verification', '/verification/profile',
        'Verification Officer Profile',
        'Official credentials and permitted contact details. Authentication secrets are never displayed.',
    ):
        with ui.card().classes(
            'w-full max-w-4xl mx-auto p-8 rounded-3xl paper-card bg-white '
            'border border-slate-200 shadow-md'
        ):
            with ui.row().classes(
                'items-center gap-6 mb-6 pb-6 border-b border-slate-200 flex-wrap'
            ):
                with ui.element('div').classes(
                    'w-20 h-20 rounded-full flex items-center justify-center '
                    'bg-gradient-to-br from-emerald-800 to-slate-900 text-white shadow-md'
                ):
                    ui.icon('fact_check', size='lg')
                with ui.column().classes('gap-1 flex-1'):
                    ui.label(
                        f"{user.get('rank') or 'Verification Officer'} {user.get('name', 'Officer')}"
                    ).classes('text-3xl font-black text-slate-900 fantasy-title')
                    ui.label(
                        f"@{user.get('username') or user.get('name', '').lower().replace(' ', '')} · "
                        f"{user.get('role', 'VERIFICATION_OFFICER')}"
                    ).classes('text-xs font-bold text-emerald-800 font-mono')
                    ui.badge(user.get('status') or 'UNKNOWN').classes(
                        'bg-emerald-100 text-emerald-900 border border-emerald-300 '
                        'font-bold text-[10px] px-2 w-fit'
                    )

            with ui.column().classes('w-full gap-0'):
                for label, value, icon in [
                    ('Officer Full Name', user.get('name') or 'Not recorded', 'person'),
                    ('Login Username', user.get('username') or 'Not recorded', 'account_circle'),
                    ('System Role', user.get('role') or 'VERIFICATION_OFFICER', 'verified_user'),
                    ('Department / Unit', user.get('station') or 'Not recorded', 'fact_check'),
                    ('District', user.get('district') or 'Not recorded', 'location_city'),
                    ('Official Rank', user.get('rank') or 'Verification Officer', 'military_tech'),
                    ('Badge Identification No.', user.get('badge_number') or 'Not recorded', 'badge'),
                    ('Registered Mobile', user.get('phone') or 'Not recorded', 'phone'),
                    ('Email Address', user.get('email') or 'Not recorded', 'email'),
                    ('Account Status', user.get('status') or 'Not recorded', 'shield'),
                ]:
                    with ui.row().classes(
                        'w-full justify-between p-4 rounded-xl bg-slate-50 border border-slate-200 '
                        'items-center gap-3 flex-wrap'
                    ):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon(icon, size='xs').classes('text-emerald-800')
                            ui.label(label).classes('font-bold text-slate-600 text-xs')
                        ui.label(str(value)).classes(
                            'font-bold text-slate-900 text-sm break-words'
                        )

        with ui.card().classes(
            'w-full max-w-4xl mx-auto p-8 rounded-3xl bg-white border border-slate-200 shadow-md'
        ):
            with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                ui.icon('edit', size='sm').classes('text-emerald-800')
                ui.label('Update Permitted Contact Details').classes(
                    'text-lg font-bold text-slate-900 fantasy-title'
                )
            ui.label(
                'Only contact and posting fields may be changed here. Name, role, badge, username and '
                'authentication credentials are managed by system administration.'
            ).classes('text-[11px] text-slate-500 mb-4')

            phone_input = ui.input('Registered Mobile', value=user.get('phone') or '').props(
                'outlined'
            ).classes('w-full')
            station_input = ui.input('Department / Unit', value=user.get('station') or '').props(
                'outlined'
            ).classes('w-full')
            district_input = ui.input('District', value=user.get('district') or '').props(
                'outlined'
            ).classes('w-full')
            address_input = ui.textarea('Address', value=user.get('address') or '').props(
                'outlined rows=2'
            ).classes('w-full')

            def save_profile() -> None:
                try:
                    updated = update_staff_profile(
                        user['id'],
                        phone=phone_input.value,
                        station=station_input.value,
                        district=district_input.value,
                        address=address_input.value,
                    )
                    set_current_user(updated)
                    ui.notify('Profile details updated.', type='positive')
                    ui.navigate.to('/verification/profile')
                except ValueError as error:
                    ui.notify(str(error), type='warning')
                except Exception as error:  # pragma: no cover - UI boundary
                    ui.notify(f'Update failed: {error}', type='negative')

            ui.button('Save Profile Changes', icon='save', on_click=save_profile).props(
                'unelevated'
            ).classes(
                'bg-emerald-800 hover:bg-emerald-900 text-white font-bold rounded-xl '
                'px-5 py-2.5 text-xs mt-2'
            )

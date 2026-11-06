"""
Police Officer Portal - assigned-case dashboard, investigation tracking, FIR
documents, citizen chat and notifications.

Every number on these pages is read from the live database and every status
change is written through the investigation service, which keeps the FIR record,
the versioned ledger, the citizen timeline and the officer credit history in sync.
"""

import base64
import json

from nicegui import background_tasks, ui

from backend.services.auth_service import get_current_user, get_staff_access_issue, set_current_user
from backend.services.complaint_evidence_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    evidence_bytes,
)
from backend.services.complaint_service import (
    get_all_complaints,
    get_complaint_by_id,
    get_complaints_for_officer,
    update_complaint_status,
)
from backend.services.fir_document_service import (
    generate_fir_pdf,
    get_current_document,
    list_documents,
    read_document_bytes,
)
from backend.services.fir_service import (
    create_fir_from_complaint as _create_fir_from_complaint,
    get_fir_by_id,
    get_firs,
    get_operational_case_timeline,
    log_officer_activity,
    update_fir,
)
from backend.services.investigation_service import (
    ACTION_LABELS,
    BLOCKED_FIR_STATUSES,
    EVIDENCE_STATUSES,
    add_investigation_evidence,
    add_investigation_note,
    compute_case_stats,
    get_admin_investigation_overview,
    get_evidence_file,
    get_investigation_panel,
    get_officer_cases,
    get_officer_performance,
    get_recent_activities,
    get_recent_assignments,
    list_investigation_entries,
    record_investigation_action,
    update_evidence_status,
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read,
)
from backend.services.realtime_events import subscribe, unsubscribe
from frontend.components.badges import fir_status_badge
from frontend.components.layout import portal_page

OFFICER_EVENTS = (
    'NOTIFICATION_CREATED', 'FIR_UPDATED', 'CASE_STAGE_UPDATED',
    'INVESTIGATION_UPDATED', 'OFFICER_CREDITS_UPDATED', 'CHAT_MESSAGE',
)

STATUS_COLOURS = {
    'SUBMITTED': 'bg-amber-100 text-amber-800 border-amber-200',
    'ASSIGNED': 'bg-blue-100 text-blue-800 border-blue-200',
    'UNDER_REVIEW': 'bg-indigo-100 text-indigo-800 border-indigo-200',
    'UNDER_INVESTIGATION': 'bg-purple-100 text-purple-800 border-purple-200',
    'INVESTIGATION': 'bg-purple-100 text-purple-800 border-purple-200',
    'CHARGESHEET_FILED': 'bg-teal-100 text-teal-800 border-teal-200',
    'RESOLVED': 'bg-emerald-100 text-emerald-800 border-emerald-200',
    'CLOSED': 'bg-slate-100 text-slate-600 border-slate-200',
    'PENDING_VERIFICATION': 'bg-amber-100 text-amber-800 border-amber-200',
    'NEEDS_CORRECTION': 'bg-orange-100 text-orange-800 border-orange-200',
    'REJECTED': 'bg-red-100 text-red-800 border-red-200',
}

STAGE_COLOURS = {
    'COMPLETED': ('bg-emerald-600 text-white', 'border-emerald-200 bg-emerald-50/60', 'check'),
    'IN_PROGRESS': ('bg-blue-700 text-white', 'border-blue-200 bg-blue-50/60', 'pending'),
    'SKIPPED': ('bg-slate-300 text-slate-600', 'border-slate-200 bg-slate-50', 'skip_next'),
    'PENDING': ('bg-slate-200 text-slate-500', 'border-slate-200 bg-white', 'circle'),
}


def require_police_user():
    """Ensure the active session belongs to an active police officer or administrator."""
    user = get_current_user() or {}
    if not user or user.get("role") not in ("OFFICER", "ADMIN"):
        ui.navigate.to('/staff-portal')
        return None
    if get_staff_access_issue(user):
        set_current_user(None)
        ui.navigate.to('/staff-portal')
        return None
    return user


def _initials(name) -> str:
    parts = [word for word in (name or '').split() if word]
    return ''.join(word[0] for word in parts[:2]).upper() or 'O'


def _fmt(value) -> str:
    text = str(value or '').replace('T', ' ')
    return text[:16] if len(text) >= 16 else (text or '—')


def _status_class(status) -> str:
    return STATUS_COLOURS.get(status or '', 'bg-slate-100 text-slate-600 border-slate-200')


def _listen(refreshable_fn, event_types=OFFICER_EVENTS, on_event=None) -> None:
    """Refresh the open page in place when a relevant domain event is published."""
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

    task = background_tasks.create(listener(), name='police-live-listener')

    def stop() -> None:
        unsubscribe(queue)
        task.cancel()

    client.on_disconnect(stop)


_BEEP_JS = """
try {
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const osc = ctx.createOscillator();
  const gain = ctx.createGain();
  osc.type = 'sine';
  osc.frequency.value = 880;
  gain.gain.setValueAtTime(0.05, ctx.currentTime);
  gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
  osc.connect(gain); gain.connect(ctx.destination);
  osc.start(); osc.stop(ctx.currentTime + 0.25);
} catch (e) {}
"""


def _alert_sound() -> None:
    ui.run_javascript(_BEEP_JS)


def _case_identity(
    fir_number,
    citizen_name,
    complaint_reference=None,
    citizen_username=None,
    size: str = 'text-lg',
) -> None:
    """FIR number with the citizen's name directly below it, everywhere one is shown."""
    ui.label(f"FIR No: {fir_number or '—'}").classes(f'{size} font-black text-slate-900 font-mono leading-tight')
    name_tag = f"{citizen_name or 'Not recorded'}"
    if citizen_username:
        name_tag += f"  (@{citizen_username})"
    ui.label(f"Citizen: {name_tag}").classes('text-[11px] font-bold text-blue-800')
    if complaint_reference:
        ui.label(f"Complaint Ref: {complaint_reference}").classes('text-[10px] text-slate-500 font-mono')


def _open_file_viewer(content: bytes, file_name: str, content_type: str) -> None:
    """Show a secured document inline without ever exposing a public URL."""
    encoded = base64.b64encode(content).decode('ascii')
    data_url = f"data:{content_type or 'application/octet-stream'};base64,{encoded}"
    with ui.dialog() as dlg, ui.card().classes('w-full max-w-5xl p-5 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('insert_drive_file', size='sm').classes('text-blue-800')
                ui.label(file_name or 'Document').classes('text-sm font-black text-slate-900')
            with ui.row().classes('items-center gap-2'):
                ui.button('Download', icon='download', on_click=lambda: ui.download(content, file_name or 'document')).props(
                    'flat dense size=sm'
                ).classes('text-blue-800 font-bold')
                ui.button(icon='close', on_click=dlg.close).props('flat round dense').classes('text-slate-400')
        if content_type == 'application/pdf':
            ui.html(
                f'<iframe src="{data_url}" title="{file_name}" '
                'style="width:100%;height:70vh;border:1px solid #e2e8f0;border-radius:16px;"></iframe>',
                sanitize=False,
            )
        elif (content_type or '').startswith('image/'):
            ui.image(data_url).classes('w-full rounded-2xl border border-slate-200')
        elif (content_type or '').startswith('video/'):
            ui.html(
                f'<video src="{data_url}" controls '
                'style="width:100%;max-height:70vh;border-radius:16px;"></video>',
                sanitize=False,
            )
        else:
            ui.label('Preview is not available for this file type. Use Download.').classes('text-xs text-slate-600')
        ui.label('Served from secure storage to authorised case participants only.').classes('text-[10px] text-slate-400 mt-2')
    dlg.open()


# ==========================================
# EDIT FIR DIALOG
# ==========================================
def open_edit_fir_dialog(fir_id: str, fir: dict, user: dict, on_success_callback=None):
    """Open the FIR amendment dialog pre-loaded with the persisted record."""
    with ui.dialog() as edit_dialog, ui.card().classes('w-full max-w-3xl p-8 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-200 mb-6'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('edit_note', size='md').classes('text-blue-800')
                with ui.column().classes('gap-0'):
                    ui.label(f"Edit FIR Record — {fir.get('fir_number')}").classes('text-2xl font-black text-slate-900 fantasy-title')
                    ui.label(f"Citizen: {fir.get('citizen_name') or 'Not recorded'} · Current version v{fir.get('current_version', 1)}").classes('text-xs text-slate-500')
            ui.button(icon='close', on_click=edit_dialog.close).props('flat round dense').classes('text-slate-400')

        with ui.column().classes('w-full gap-4 text-xs'):
            with ui.row().classes('w-full gap-4'):
                e_type = ui.input(
                    'Incident Classification *', value=fir.get('incident_type') or ''
                ).classes('flex-1').props('outlined')
                e_station = ui.input(
                    'Police Station Jurisdiction *', value=fir.get('police_station') or ''
                ).classes('flex-1').props('outlined')

            e_loc = ui.input('Incident Location *', value=fir.get('incident_location', '')).classes('w-full').props('outlined')
            e_desc = ui.textarea('Official Case Description / Detailed Findings *', value=fir.get('description', '')).classes('w-full').props('outlined rows=4')
            e_accused = ui.textarea('Accused / Suspect Details', value=fir.get('accused_details', '')).classes('w-full').props('outlined rows=3')
            e_witness = ui.textarea('Witness Statements & Evidence References', value=fir.get('witness_details', '')).classes('w-full').props('outlined rows=3')
            e_reason = ui.input(
                'Reason for Change / Case Update Memo (optional)',
                placeholder='E.g., statement recorded, new evidence added, suspect identified...',
            ).classes('w-full mt-2').props('outlined')
            ui.label(
                'Every amendment is versioned and hashed on the case ledger. The FIR status itself is '
                'changed only through the Investigation Progress controls.'
            ).classes('text-[10px] text-slate-500')

            def save_fir_updates():
                if not e_loc.value or not e_desc.value:
                    ui.notify('Please fill in location and description.', type='warning')
                    return

                updated_dict = {
                    "incident_type": (e_type.value or '').strip(),
                    "police_station": (e_station.value or '').strip(),
                    "incident_location": e_loc.value.strip(),
                    "description": e_desc.value.strip(),
                    "accused_details": (e_accused.value or '').strip(),
                    "witness_details": (e_witness.value or '').strip(),
                }
                try:
                    update_fir(
                        fir_id=fir_id,
                        actor_user=user,
                        updated_fields=updated_dict,
                        change_reason=e_reason.value.strip(),
                    )
                    ui.notify(f"FIR {fir.get('fir_number')} updated and versioned.", type='positive')
                    edit_dialog.close()
                    if on_success_callback:
                        on_success_callback()
                    else:
                        ui.navigate.to(f'/police/fir/{fir_id}')
                except Exception as ex:
                    ui.notify(f'Failed to update FIR: {ex}', type='negative')

            with ui.row().classes('w-full justify-between items-center mt-6 pt-4 border-t border-slate-200'):
                ui.button('Cancel', on_click=edit_dialog.close).props('flat').classes('text-slate-600 font-bold')
                ui.button('Save FIR Updates', icon='save', on_click=save_fir_updates).props('unelevated').classes(
                    'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl px-8 py-2.5 shadow-md text-xs'
                )

    edit_dialog.open()


# ==========================================
# 1. POLICE DASHBOARD
# ==========================================
@ui.page('/police')
def police_dashboard() -> None:
    """Live investigating-officer workspace: real case counts, recent work, alerts."""
    user = require_police_user()
    if not user:
        return

    officer_id = user.get("id", "")
    is_admin = user.get('role') == 'ADMIN'

    with portal_page(
        'police', '/police', 'Investigating Officer Dashboard',
        'Assigned cases, investigation progress, citizen communication and departmental alerts in real time.',
    ):
        @ui.refreshable
        def dashboard_view() -> None:
            if is_admin:
                cases = get_admin_investigation_overview()
                assignments = []
                activities = []
            else:
                cases = get_officer_cases(officer_id)
                assignments = get_recent_assignments(officer_id)
                activities = get_recent_activities(officer_id)
            stats = compute_case_stats(cases)
            unread = get_unread_count(officer_id)

            # ── Officer banner ───────────────────────────────
            with ui.card().classes('w-full p-6 paper-card bg-white border-l-4 border-blue-800 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                    with ui.row().classes('items-center gap-4'):
                        with ui.element('div').classes(
                            'w-16 h-16 rounded-full flex items-center justify-center '
                            'bg-gradient-to-br from-blue-800 to-slate-900 text-white font-black text-lg shadow-md'
                        ):
                            ui.label(_initials(user.get('name')))
                        with ui.column().classes('gap-1'):
                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                ui.label(f"{user.get('rank') or 'Officer'} {user.get('name', 'Police Officer')}").classes(
                                    'text-2xl md:text-3xl font-black text-slate-900 fantasy-title'
                                )
                                ui.badge(f"Badge: {user.get('badge_number') or 'Not recorded'}").classes(
                                    'bg-blue-100 text-blue-900 border border-blue-300 font-bold text-[11px] px-3 py-1 rounded-full font-mono'
                                )
                            ui.label(
                                f"Station: {user.get('station') or 'Not recorded'} · "
                                f"Login: {user.get('email') or '—'} · "
                                f"{'All case oversight' if is_admin else 'Assigned Investigating Officer'}"
                            ).classes('text-[11px] text-slate-600')

                    with ui.row().classes('gap-2 flex-wrap'):
                        ui.button('My Assigned Cases', icon='folder_special', on_click=lambda: ui.navigate.to('/police/firs')).props(
                            'unelevated'
                        ).classes('bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl px-4 py-2.5 text-xs')
                        ui.button('Citizen Chat', icon='forum', on_click=lambda: ui.navigate.to('/police/chat')).props(
                            'unelevated'
                        ).classes('bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-4 py-2.5 text-xs')
                        ui.button(
                            f'Notifications{f" ({unread})" if unread else ""}',
                            icon='notifications',
                            on_click=lambda: ui.navigate.to('/police/notifications'),
                        ).props('unelevated').classes(
                            ('bg-amber-600 hover:bg-amber-700 ' if unread else 'bg-slate-200 hover:bg-slate-300 ')
                            + 'text-white font-bold rounded-xl px-4 py-2.5 text-xs'
                        )

            # ── Case statistics ──────────────────────────────
            with ui.row().classes('w-full flex-wrap gap-3'):
                cards_data = [
                    ('Total Assigned FIRs', stats['total'], 'assignment_ind', '#1E40AF', 'bg-blue-50/80 border-blue-200', '/police/firs'),
                    ('New Case Assignments', stats['new'], 'fiber_new', '#B45309', 'bg-amber-50/80 border-amber-200', '/police/firs'),
                    ('Under Investigation', stats['under_investigation'], 'manage_search', '#6D28D9', 'bg-purple-50/80 border-purple-200', '/police/firs'),
                    ('Awaiting Your Action', stats['awaiting_action'], 'priority_high', '#DC2626', 'bg-red-50/80 border-red-200', '/police/firs'),
                    ('Evidence Collection', stats['evidence'], 'policy', '#0284C7', 'bg-sky-50/80 border-sky-200', '/police/firs'),
                    ('Investigation Completed', stats['completed'], 'task_alt', '#059669', 'bg-emerald-50/80 border-emerald-200', '/police/firs'),
                    ('Submitted for Proceedings', stats['proceedings'], 'account_balance', '#0F766E', 'bg-teal-50/80 border-teal-200', '/police/firs'),
                    ('Closed Cases', stats['closed'], 'folder_off', '#475569', 'bg-slate-100 border-slate-200', '/police/firs'),
                ]
                for label, value, icon_name, colour, background, target in cards_data:
                    with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border shadow-xs {background} gap-1'):
                        with ui.row().classes('w-full items-center justify-between'):
                            ui.icon(icon_name, size='md').style(f'color: {colour}')
                            ui.label(str(value)).classes('text-3xl font-black text-slate-900')
                        ui.label(label).classes('text-[11px] font-bold text-slate-700 leading-tight')
                        ui.button('Open', icon='arrow_forward', on_click=lambda t=target: ui.navigate.to(t)).props(
                            'flat dense no-caps size=xs'
                        ).classes('text-[10px] font-bold text-slate-500 self-start px-0')

            with ui.row().classes('w-full gap-4 flex-wrap items-start'):
                # ── Recent assignments ───────────────────────
                with ui.card().classes('flex-1 min-w-80 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                        ui.icon('how_to_reg', size='sm').classes('text-blue-800')
                        ui.label('Recent Case Assignments').classes('text-base font-bold text-slate-900 fantasy-title')

                    if is_admin:
                        ui.label(
                            'Administrator oversight covers every assigned case — use My Assigned Cases for the full list.'
                        ).classes('text-[11px] text-slate-500')
                    elif not assignments:
                        with ui.column().classes('w-full items-center py-8 gap-2 text-center'):
                            ui.icon('inbox', size='lg').classes('text-slate-300')
                            ui.label('No case assignments received yet.').classes('text-sm font-bold text-slate-600')
                            ui.label('New assignments from the Verification Officer appear here automatically.').classes(
                                'text-[11px] text-slate-400 max-w-xs'
                            )
                    else:
                        with ui.column().classes('w-full gap-2'):
                            for row in assignments:
                                with ui.row().classes(
                                    'w-full p-3 rounded-xl border border-slate-200 bg-slate-50/60 '
                                    'items-center justify-between gap-3'
                                ):
                                    with ui.column().classes('gap-0.5 flex-1'):
                                        ui.label(f"FIR No: {row.get('fir_number')}").classes('text-sm font-black text-slate-900 font-mono')
                                        ui.label(f"Citizen: {row.get('citizen_name') or 'Not recorded'}").classes('text-[11px] font-bold text-blue-800')
                                        ui.label(
                                            f"By {row.get('assigned_by_name') or 'Verification Officer'} · {_fmt(row.get('assigned_at'))}"
                                        ).classes('text-[10px] text-slate-500')
                                    ui.button('Open', icon='open_in_new', on_click=lambda r=row['fir_id']: ui.navigate.to(f'/police/fir/{r}')).props(
                                        'unelevated size=xs'
                                    ).classes('bg-blue-800 text-white font-bold rounded-lg')

                # ── Recent activity ──────────────────────────
                with ui.card().classes('flex-1 min-w-80 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                        ui.icon('bolt', size='sm').classes('text-blue-800')
                        ui.label('Recent Case Activity').classes('text-base font-bold text-slate-900 fantasy-title')

                    if not activities:
                        with ui.column().classes('w-full items-center py-8 gap-2 text-center'):
                            ui.icon('timeline', size='lg').classes('text-slate-300')
                            ui.label('Your investigation updates will appear here.').classes('text-sm text-slate-500')
                    else:
                        with ui.column().classes('w-full gap-2'):
                            for row in activities:
                                with ui.row().classes('w-full items-start gap-3 p-3 rounded-xl border border-slate-200'):
                                    ui.icon(
                                        'flag' if row['kind'] == 'STAGE' else
                                        ('attachment' if row.get('action') == 'EVIDENCE' else 'sticky_note2'),
                                        size='xs',
                                    ).classes('text-blue-800 mt-1')
                                    with ui.column().classes('gap-0.5 flex-1'):
                                        ui.label(row.get('summary') or '').classes('text-xs font-bold text-slate-800')
                                        ui.label(f"FIR No: {row.get('fir_number')}").classes('text-[11px] font-black text-slate-900 font-mono')
                                        ui.label(f"Citizen: {row.get('citizen_name') or 'Not recorded'}").classes('text-[10px] font-bold text-blue-800')
                                    ui.label(_fmt(row.get('at'))).classes('text-[10px] text-slate-400 font-mono shrink-0')

        dashboard_view()

        def _on_dashboard_event(event) -> None:
            if event.get('type') == 'NOTIFICATION_CREATED' and event.get('user_id') == officer_id:
                note = event.get('notification') or {}
                ui.notify(
                    f"{note.get('title', 'Update')}",
                    type='info', position='top-right', close_button=True, timeout=7000,
                )
                _alert_sound()

        _listen(dashboard_view, on_event=_on_dashboard_event)
        ui.timer(25.0, dashboard_view.refresh)


# ==========================================
# 2. MY ASSIGNED CASES
# ==========================================
@ui.page('/police/firs')
def police_assigned_cases_page() -> None:
    """Dedicated My Assigned Cases list with the identity of every case."""
    user = require_police_user()
    if not user:
        return

    officer_id = user.get("id", "")
    is_admin = user.get('role') == 'ADMIN'

    with portal_page(
        'police', '/police/firs', 'My Assigned Cases',
        'Every FIR assigned to your badge, with the citizen, stage and open-case controls.',
    ):
        search = ui.input(
            'Search by FIR number, citizen, complaint reference or location',
            placeholder='Type to filter...',
        ).props('outlined dense clearable').classes('w-full max-w-xl mb-2')

        @ui.refreshable
        def cases_view() -> None:
            query = (search.value or '').strip().lower()
            if is_admin:
                cases = get_admin_investigation_overview()
            else:
                cases = get_officer_cases(officer_id)
            if query:
                cases = [
                    c for c in cases
                    if query in ' '.join(str(c.get(k) or '') for k in (
                        'fir_number', 'citizen_name', 'complaint_reference', 'incident_type', 'incident_location'
                    )).lower()
                ]

            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 mb-3'):
                ui.label(f'{len(cases)} case(s) in your view').classes('text-sm font-bold text-slate-700')
                ui.button('Dashboard', icon='dashboard', on_click=lambda: ui.navigate.to('/police')).props(
                    'flat dense size=sm'
                ).classes('text-blue-800 font-bold')

            if not cases:
                with ui.card().classes('w-full p-12 text-center bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    ui.icon('assignment_turned_in', size='xl').classes('text-slate-300 mb-3')
                    ui.label('No FIR cases currently assigned to you.').classes('text-base font-bold text-slate-700')
                    ui.label(
                        'When the Verification Officer assigns a registered FIR to your badge it appears here '
                        'immediately, without a refresh.'
                    ).classes('text-xs text-slate-500 max-w-md mx-auto mt-1')
                return

            with ui.column().classes('w-full gap-3'):
                for case in cases:
                    fir_id = case['id']
                    document = get_current_document(fir_id)
                    with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-xs hover:shadow-md transition-all'):
                        with ui.row().classes('w-full items-start justify-between flex-wrap gap-4'):
                            with ui.column().classes('gap-1 flex-1 min-w-64'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    _case_identity(
                                        case.get('fir_number'), case.get('citizen_name'),
                                        case.get('complaint_reference'),
                                        citizen_username=case.get('citizen_username'),
                                        size='text-base',
                                    )
                                    ui.badge(case.get('status') or '').classes(
                                        f'{_status_class(case.get("status"))} border font-bold text-[10px] px-2 rounded-full'
                                    )
                                    if case.get('status') in BLOCKED_FIR_STATUSES:
                                        ui.badge('DRAFT FIR').classes('bg-amber-100 text-amber-800 border border-amber-300 font-bold text-[10px] px-2 rounded-full')
                                    else:
                                        ui.badge('REGISTERED FIR').classes('bg-emerald-100 text-emerald-800 border border-emerald-300 font-bold text-[10px] px-2 rounded-full')
                                ui.label(
                                    f"{case.get('incident_type') or 'Incident'} · {case.get('incident_location') or 'Location not recorded'}"
                                ).classes('text-xs font-bold text-slate-700 mt-1')
                                ui.label(
                                    f"Assigned {_fmt(case.get('assigned_at'))} · "
                                    f"Station: {case.get('police_station') or 'Not recorded'} · "
                                    f"Incident date: {case.get('incident_date') or '—'}"
                                ).classes('text-[11px] text-slate-500')

                            with ui.column().classes('items-start gap-2 min-w-56'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.label('Stage:').classes('text-[11px] font-bold text-slate-500')
                                    ui.badge(case.get('stage_label') or 'Awaiting tracking').classes(
                                        'bg-indigo-100 text-indigo-800 border border-indigo-200 font-bold text-[10px] px-2 rounded-full'
                                    )
                                if document:
                                    ui.label(f"FIR PDF v{document.get('version')} available").classes('text-[10px] font-bold text-rose-700')
                                else:
                                    ui.label('FIR PDF not generated yet').classes('text-[10px] text-slate-400')
                                with ui.row().classes('gap-2 flex-wrap'):
                                    ui.button('Open Case', icon='folder_open', on_click=lambda fid=fir_id: ui.navigate.to(f'/police/fir/{fid}')).props(
                                        'unelevated size=xs'
                                    ).classes('bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-lg')
                                    ui.button('Chat', icon='chat', on_click=lambda fid=fir_id: ui.navigate.to(f'/police/chat/{fid}')).props(
                                        'unelevated size=xs'
                                    ).classes('bg-emerald-700 text-white font-bold rounded-lg')

        cases_view()
        search.on('update:value', lambda _: cases_view.refresh())
        _listen(cases_view)
        ui.timer(30.0, cases_view.refresh)


# ==========================================
# 3. CASE FILE, INVESTIGATION PROGRESS, NOTES & EVIDENCE
# ==========================================
@ui.page('/police/fir/{fir_id}')
def police_fir_case_page(fir_id: str) -> None:
    """Full authorised case file for the assigned investigating officer."""
    user = require_police_user()
    if not user:
        return

    try:
        fir = get_fir_by_id(fir_id, actor_user=user)
    except PermissionError:
        with portal_page('police', '/police/firs', 'Access Denied', 'Authorisation required for this case.'):
            ui.icon('lock', size='xl').classes('text-red-500')
            ui.label('Access denied: this case is not assigned to your badge.').classes('text-red-700 font-bold text-sm')
            ui.button('Back to My Assigned Cases', on_click=lambda: ui.navigate.to('/police/firs')).props('unelevated')
        return

    if not fir:
        with portal_page('police', '/police/firs', 'Case Not Found', 'The record could not be located.'):
            ui.label('FIR not found.').classes('text-slate-600')
            ui.button('Back to My Assigned Cases', on_click=lambda: ui.navigate.to('/police/firs')).props('unelevated')
        return

    complaint = None
    if fir.get('complaint_id'):
        complaint = get_complaint_by_id(fir['complaint_id'], actor_user=user)

    try:
        log_officer_activity(
            user=user, action_type="POLICE_CASE_OPENED", fir_id=fir_id,
            fir_number=fir.get('fir_number', fir_id), status_from=fir.get('status'),
            status_to=fir.get('status'),
            details=f"Assigned officer {user.get('rank') or 'Officer'} {user.get('name')} opened and reviewed the case file.",
        )
    except Exception:
        pass

    with portal_page(
        'police', '/police/firs', f"Case Record: {fir.get('fir_number')}",
        f"Citizen: {fir.get('citizen_name') or 'Not recorded'} · Station: {fir.get('police_station') or 'Not recorded'}",
    ):
        @ui.refreshable
        def case_view() -> None:
            fresh = get_fir_by_id(fir_id, actor_user=user) or fir
            status = fresh.get('status', 'PENDING_VERIFICATION')
            is_draft_case = status in BLOCKED_FIR_STATUSES
            panel = None
            panel_error = None
            try:
                panel = get_investigation_panel(fir_id, user)
            except PermissionError as exc:
                panel_error = str(exc)

            ui.button('← Back to My Assigned Cases', icon='arrow_back', on_click=lambda: ui.navigate.to('/police/firs')).props(
                'flat'
            ).classes('text-slate-600 font-bold mb-2')

            # ── Identity header ──────────────────────────────
            with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-4 pb-4 border-b border-slate-200'):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('description', size='lg').classes('text-blue-800')
                        with ui.column().classes('gap-0'):
                            _case_identity(
                                fresh.get('fir_number'), fresh.get('citizen_name'),
                                fresh.get('reference_number') and f"Tracking Ref {fresh.get('reference_number')}",
                                citizen_username=fresh.get('citizen_username'),
                                size='text-2xl md:text-3xl',
                            )
                            ui.label(f"Version v{fresh.get('current_version', 1)} · Opened {_fmt(fresh.get('created_at'))}").classes(
                                'text-[10px] text-slate-500 font-mono'
                            )
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        fir_status_badge(status)
                        ui.badge('DRAFT FIR' if is_draft_case else 'REGISTERED FIR').classes(
                            ('bg-amber-100 text-amber-900 border border-amber-300' if is_draft_case
                             else 'bg-emerald-100 text-emerald-900 border border-emerald-300')
                            + ' font-bold text-[11px] px-3 py-1 rounded-full'
                        )
                    with ui.row().classes('gap-2 flex-wrap w-full'):
                        ui.button('Chat with Citizen', icon='forum', on_click=lambda: ui.navigate.to(f'/police/chat/{fir_id}')).props(
                            'unelevated'
                        ).classes('bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-4 py-2 text-xs')
                        ui.button('Edit FIR Record', icon='edit', on_click=lambda f=fresh: open_edit_fir_dialog(fir_id, f, user, case_view.refresh)).props(
                            'unelevated'
                        ).classes('bg-amber-600 hover:bg-amber-700 text-white font-bold rounded-xl px-4 py-2 text-xs')

                # Citizen card
                with ui.card().classes('w-full mt-4 p-5 bg-blue-50/70 border border-blue-200 rounded-2xl'):
                    ui.label('Citizen / Complainant').classes('text-[11px] font-bold text-blue-900 uppercase tracking-wider mb-3')
                    with ui.row().classes('w-full gap-6 flex-wrap text-xs'):
                        for label, value in [
                            ('Full Name', fresh.get('citizen_name') or 'Not recorded'),
                            ('Username', f"@{fresh.get('citizen_username')}" if fresh.get('citizen_username') else 'Not recorded'),
                            ('Mobile Contact', fresh.get('citizen_phone') or 'Not recorded'),
                            ('Email Address', fresh.get('citizen_email') or 'Not recorded'),
                            ('Address', fresh.get('citizen_address') or 'Not recorded'),
                            ('Government ID', fresh.get('gov_id_masked') or 'Not recorded'),
                            ('FIR Registration Date', _fmt(fresh.get('created_at'))),
                            ('Officer Assignment Date', _fmt(fresh.get('assigned_at'))),
                        ]:
                            with ui.column().classes('min-w-40 gap-0.5'):
                                ui.label(label).classes('font-bold text-slate-500 text-[10px] uppercase')
                                ui.label(str(value)).classes('font-bold text-slate-900 text-sm')

                # Incident grid
                with ui.row().classes('w-full mt-4 flex-wrap gap-6 text-xs'):
                    for label, value in [
                        ('Incident Category', fresh.get('incident_type')),
                        ('Incident Date & Time', f"{fresh.get('incident_date') or '—'} at {fresh.get('incident_time') or '—'}"),
                        ('Incident Location', fresh.get('incident_location')),
                        ('Police Jurisdiction', fresh.get('police_station')),
                        ('Assigned Officer', f"{fresh.get('officer_rank') or 'Officer'} {fresh.get('officer_name') or 'Not assigned'}"
                                             f" (Badge {fresh.get('officer_badge') or 'N/A'})"),
                    ]:
                        with ui.column().classes('min-w-44 gap-0.5'):
                            ui.label(label).classes('font-bold text-slate-500 text-[10px] uppercase')
                            ui.label(str(value or 'Not recorded')).classes('font-bold text-slate-900 text-sm')

                for label, key in [
                    ('Official Incident Description', 'description'),
                    ('Accused / Suspect Information', 'accused_details'),
                    ('Witness Statements & References', 'witness_details'),
                ]:
                    text = (fresh.get(key) or '').strip()
                    if text:
                        with ui.card().classes('w-full mt-3 p-4 rounded-xl bg-slate-50 border border-slate-200'):
                            ui.label(label).classes('text-[11px] font-bold text-slate-700 mb-1')
                            ui.label(text).classes('text-xs text-slate-800 leading-relaxed whitespace-pre-line')

            # ── FIR draft & documents ────────────────────────
            with ui.card().classes('w-full mt-6 p-6 bg-white border border-rose-800/20 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                    ui.icon('folder_zip', size='sm').classes('text-rose-700')
                    ui.label('FIR Draft, Documents & Supporting Evidence').classes('text-base font-bold text-slate-900 fantasy-title')
                    ui.badge('DRAFT PDF — pending authorised approval').classes(
                        'bg-amber-100 text-amber-900 border border-amber-300 font-bold text-[10px] px-2 rounded-full'
                    )

                ui.label(
                    'The generated PDF is a draft for authorised approval: case-specific legal sections, '
                    'the officer signature and the station seal must be completed by the competent SHO. '
                    'Files are stored outside the web root and are served only to authorised case participants.'
                ).classes('text-[11px] text-slate-500 mb-3')

                current_doc = get_current_document(fir_id)
                documents = list_documents(fir_id)
                if current_doc:
                    with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                        with ui.column().classes('gap-0.5'):
                            ui.label(f"Draft FIR PDF — v{current_doc.get('version')} · {current_doc.get('file_name')}").classes(
                                'text-sm font-black text-slate-900 font-mono'
                            )
                            ui.label(
                                f"Citizen: {fresh.get('citizen_name') or 'Not recorded'} · "
                                f"Generated by {current_doc.get('generated_by_name') or '—'} · {_fmt(current_doc.get('generated_at'))}"
                            ).classes('text-[10px] text-slate-500')
                        with ui.row().classes('gap-2 flex-wrap'):
                            def view_draft():
                                data = read_document_bytes(current_doc)
                                if not data:
                                    ui.notify('The stored PDF is no longer available.', type='warning')
                                    return
                                _open_file_viewer(data, current_doc.get('file_name') or 'FIR.pdf', 'application/pdf')

                            def download_draft():
                                data = read_document_bytes(current_doc)
                                if not data:
                                    ui.notify('The stored PDF is no longer available.', type='warning')
                                    return
                                ui.download(data, current_doc.get('file_name') or 'FIR.pdf')

                            ui.button('View FIR Draft', icon='visibility', on_click=view_draft).props('unelevated').classes(
                                'bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl px-4 py-2 text-xs'
                            )
                            ui.button('Download FIR PDF', icon='download', on_click=download_draft).props('unelevated').classes(
                                'bg-slate-800 hover:bg-slate-900 text-white font-bold rounded-xl px-4 py-2 text-xs'
                            )
                else:
                    ui.label('No FIR document has been generated for this case yet.').classes('text-xs text-slate-500 mb-2')

                if documents:
                    with ui.column().classes('w-full gap-1 mt-3'):
                        ui.label('Document Version History').classes('text-[10px] font-bold text-slate-500 uppercase')
                        for doc in documents:
                            with ui.row().classes('w-full justify-between items-center gap-2'):
                                ui.label(f"v{doc.get('version')} · {_fmt(doc.get('generated_at'))} · {doc.get('file_name')}").classes(
                                    'text-[10px] text-slate-600 font-mono'
                                )
                                if doc.get('is_current'):
                                    ui.badge('CURRENT').classes('bg-emerald-100 text-emerald-900 text-[9px] font-bold')

                # Supporting documents (citizen complaint evidence + case evidence)
                ui.label('Supporting Documents').classes('text-[10px] font-bold text-slate-500 uppercase mt-5 mb-2')
                complaint_files = []
                if complaint:
                    try:
                        complaint_files = json.loads(complaint.get('evidence_files') or '[]')
                    except (TypeError, ValueError):
                        complaint_files = []

                # Also check evidence attached directly to the FIR record
                if not complaint_files:
                    try:
                        complaint_files = json.loads(fresh.get('evidence_files') or '[]')
                    except (TypeError, ValueError):
                        complaint_files = []

                # Resolve the complaint id safely — the complaint row may be None when
                # the FIR was created without a linked complaint record.
                _complaint_id = (complaint.get('id') if complaint else None) or fresh.get('complaint_id')

                if complaint_files:
                    for item in complaint_files:
                        with ui.row().classes('w-full items-center justify-between gap-3 p-2.5 rounded-xl border border-slate-200 bg-slate-50/70'):
                            with ui.column().classes('gap-0 flex-1'):
                                ui.label(item.get('name') or 'Attachment').classes('text-xs font-bold text-slate-800')
                                if item.get('stage') == 'CITIZEN_ADDITIONAL':
                                    ui.label(
                                        f"Added during investigation by {item.get('uploaded_by') or 'the complainant'} · "
                                        f"{_fmt(item.get('uploaded_at'))}"
                                        + (f" · {item.get('caption')}" if item.get('caption') else '')
                                    ).classes('text-[10px] font-bold text-emerald-700')
                                else:
                                    ui.label(
                                        f"Filed by complainant {(complaint.get('citizen_name') if complaint else None) or fresh.get('citizen_name') or 'Citizen'} · "
                                        f"{int(item.get('size') or 0) // 1024} KB"
                                    ).classes('text-[10px] text-slate-500')

                            def open_complaint_file(entry=item, cid=_complaint_id):
                                if not cid:
                                    ui.notify('No complaint record linked to this FIR.', type='warning')
                                    return
                                data = evidence_bytes(cid, entry.get('stored_name') or '')
                                if not data:
                                    ui.notify('The stored file is no longer available.', type='warning')
                                    return
                                _open_file_viewer(data, entry.get('name') or 'file', entry.get('content_type') or 'application/octet-stream')

                            ui.button('View', icon='open_in_new', on_click=open_complaint_file).props('flat dense size=sm').classes(
                                'text-blue-800 font-bold'
                            )
                else:
                    ui.label('The complainant filed no supporting documents with this complaint.').classes('text-[11px] text-slate-400')

            # ── Complaint & authorised verification details ──
            if complaint:
                with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                        ui.icon('verified_user', size='sm').classes('text-emerald-700')
                        ui.label('Source Complaint & Authorised Verification').classes('text-base font-bold text-slate-900 fantasy-title')
                    with ui.row().classes('w-full gap-6 flex-wrap text-xs'):
                        for label, value in [
                            ('Complaint Reference', complaint.get('reference')),
                            ('Complaint Category', complaint.get('category')),
                            ('Complaint Title', complaint.get('title')),
                            ('Filed On', _fmt(complaint.get('submitted_at'))),
                            ('Complaint Status', complaint.get('status')),
                            ('Verification Status', complaint.get('verification_status') or 'Not recorded'),
                            ('Verified By', complaint.get('verified_by_name') or 'Not recorded'),
                            ('Verified At', _fmt(complaint.get('verified_at'))),
                            ('Verification Remarks', complaint.get('verification_remarks') or '—'),
                        ]:
                            with ui.column().classes('min-w-40 gap-0.5'):
                                ui.label(label).classes('font-bold text-slate-500 text-[10px] uppercase')
                                ui.label(str(value or 'Not recorded')).classes('font-bold text-slate-900 text-sm')
                    ui.label(complaint.get('description') or '').classes('text-xs text-slate-700 mt-3 whitespace-pre-line')

            # ── Investigation progress ───────────────────────
            with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 pb-3 border-b border-slate-100 mb-4'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('timeline', size='sm').classes('text-blue-800')
                        ui.label('Investigation Progress').classes('text-base font-bold text-slate-900 fantasy-title')
                    if panel:
                        ui.badge(f"Current: {panel.get('current_label')}").classes(
                            'bg-indigo-100 text-indigo-900 border border-indigo-200 font-bold text-[11px] px-3 py-1 rounded-full'
                        )

                if panel_error:
                    ui.label(panel_error).classes('text-xs text-red-600 font-bold')
                elif not panel:
                    ui.label('Investigation tracking is unavailable for this record.').classes('text-xs text-slate-500')
                else:
                    if is_draft_case:
                        with ui.card().classes('w-full p-4 mb-4 rounded-2xl bg-amber-50 border border-amber-200'):
                            ui.label(
                                'This FIR is still in the verification stage, so investigation updates are locked. '
                                'Progress controls open once the Verification Officer registers the FIR.'
                            ).classes('text-[11px] font-bold text-amber-800')
                    elif not panel.get('can_manage'):
                        with ui.card().classes('w-full p-4 mb-4 rounded-2xl bg-slate-50 border border-slate-200'):
                            ui.label(
                                'Read-only view: this case is not assigned to your badge, so progress controls are disabled.'
                            ).classes('text-[11px] font-bold text-slate-600')

                    can_manage = panel.get('can_manage')

                    def open_action_dialog(stage_key, stage_label, action):
                        with ui.dialog() as dlg, ui.card().classes('w-full max-w-2xl p-7 bg-white rounded-3xl shadow-2xl'):
                            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4'):
                                with ui.column().classes('gap-0'):
                                    ui.label(f"{ACTION_LABELS[action]} — {stage_label}").classes(
                                        'text-xl font-black text-slate-900 fantasy-title'
                                    )
                                    ui.label(
                                        f"FIR No: {fresh.get('fir_number')}"
                                    ).classes('text-xs font-black text-slate-700 font-mono')
                                    ui.label(f"Citizen: {fresh.get('citizen_name') or 'Not recorded'}").classes(
                                        'text-[11px] font-bold text-blue-800'
                                    )
                                ui.button(icon='close', on_click=dlg.close).props('flat round dense').classes('text-slate-400')

                            desc = ui.textarea(
                                'Progress description *',
                                placeholder='Record the investigative action taken (minimum 10 characters)...',
                            ).props('outlined rows=4').classes('w-full')
                            ui.label(
                                'Internal note: visible to you and to administrators. Never shown to the citizen.'
                            ).classes('text-[10px] text-slate-500 mb-3')

                            public_note = ui.input(
                                'Citizen-visible update (optional)',
                                placeholder='Leave blank to use the standard public stage message.',
                            ).props('outlined').classes('w-full')

                            if action == 'COMPLETED' and stage_key == 'CASE_CLOSED':
                                with ui.card().classes('w-full p-4 mt-3 rounded-xl bg-red-50 border border-red-200'):
                                    ui.label(
                                        'Closing this case is final. The citizen and the administrator are notified '
                                        'and the FIR record is versioned on the case ledger.'
                                    ).classes('text-[11px] font-bold text-red-800')

                            def submit():
                                try:
                                    record_investigation_action(
                                        fir_id, stage_key, action, user,
                                        desc.value or '', public_note.value or '',
                                    )
                                    ui.notify(f"{stage_label}: {ACTION_LABELS[action].lower()} recorded.", type='positive')
                                    dlg.close()
                                    case_view.refresh()
                                except (ValueError, PermissionError) as exc:
                                    ui.notify(str(exc), type='warning')
                                except Exception as exc:
                                    ui.notify(f'Could not record the update: {exc}', type='negative')

                            with ui.row().classes('w-full justify-end gap-2 mt-5'):
                                ui.button('Cancel', on_click=dlg.close).props('flat').classes('text-slate-600 font-bold')
                                ui.button(f"Save {ACTION_LABELS[action]}", icon='save', on_click=submit).props('unelevated').classes(
                                    'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-6 py-2 text-xs'
                                )
                        dlg.open()

                    with ui.column().classes('w-full gap-2.5'):
                        for index, stage in enumerate(panel['stages'], start=1):
                            dot_cls, card_cls, icon_name = STAGE_COLOURS.get(stage['status'], STAGE_COLOURS['PENDING'])
                            hist = stage.get('last_update') or {}
                            with ui.row().classes(f'w-full items-start gap-3 p-3 rounded-2xl border {card_cls}'):
                                with ui.element('div').classes(
                                    f'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 shadow-sm {dot_cls}'
                                ):
                                    ui.icon(icon_name, size='xs')
                                with ui.column().classes('gap-1 flex-1'):
                                    with ui.row().classes('items-center gap-2 flex-wrap'):
                                        ui.label(f'{index}. {stage["label"]}').classes('text-sm font-black text-slate-900')
                                        if stage.get('optional'):
                                            ui.badge('Where applicable').classes('bg-slate-200 text-slate-600 font-bold text-[9px] px-1.5 rounded')
                                        ui.badge(stage['status'].replace('_', ' ')).classes(
                                            'bg-white/70 text-slate-700 border border-slate-300 font-bold text-[9px] px-1.5 rounded'
                                        )
                                    if hist:
                                        ui.label(str(hist.get('remarks') or '')).classes('text-[11px] text-slate-700')
                                        ui.label(
                                            f"{hist.get('updated_by_officer_name') or 'Officer'} · "
                                            f"{_fmt(hist.get('timestamp'))} · "
                                            f"{(hist.get('action') or 'STARTED').lower()}"
                                        ).classes('text-[10px] text-slate-500 font-mono')
                                        ui.label(
                                            f"Citizen sees: {hist.get('public_note') or 'standard stage message'}"
                                        ).classes('text-[10px] text-emerald-700')
                                    else:
                                        ui.label('Not recorded yet.').classes('text-[10px] text-slate-400')
                                if can_manage:
                                    with ui.column().classes('gap-1 items-end shrink-0'):
                                        if stage['can_start']:
                                            ui.button(
                                                'Mark as Started',
                                                on_click=lambda s=stage: open_action_dialog(s['key'], s['label'], 'STARTED'),
                                            ).props('unelevated size=xs').classes('bg-blue-800 text-white font-bold rounded-lg')
                                        if stage['can_progress']:
                                            ui.button(
                                                'Update Progress',
                                                on_click=lambda s=stage: open_action_dialog(s['key'], s['label'], 'PROGRESS'),
                                            ).props('outline size=xs').classes('bg-white text-blue-800 font-bold rounded-lg border-blue-300')
                                        if stage['can_complete'] and stage['key'] != 'CASE_CLOSED':
                                            ui.button(
                                                'Mark as Completed',
                                                on_click=lambda s=stage: open_action_dialog(s['key'], s['label'], 'COMPLETED'),
                                            ).props('unelevated size=xs').classes('bg-emerald-700 text-white font-bold rounded-lg')
                                        if stage['can_close']:
                                            ui.button(
                                                'Close Case',
                                                on_click=lambda s=stage: open_action_dialog(s['key'], s['label'], 'COMPLETED'),
                                            ).props('unelevated size=xs').classes('bg-red-700 text-white font-bold rounded-lg')

                    if panel['history']:
                        ui.label('Investigation History (internal)').classes(
                            'text-[10px] font-bold text-slate-500 uppercase mt-5 mb-2'
                        )
                        with ui.column().classes('w-full gap-1.5'):
                            for row in panel['history'][:12]:
                                with ui.row().classes('w-full items-start gap-3 p-2.5 rounded-xl border border-slate-200 bg-slate-50/60'):
                                    ui.label(
                                        f"{row.get('normalized_new_stage') or row.get('new_stage')}"
                                    ).classes('text-[10px] font-black text-blue-900 font-mono min-w-40')
                                    with ui.column().classes('gap-0 flex-1'):
                                        ui.label(str(row.get('remarks') or '')).classes('text-[11px] text-slate-700')
                                        ui.label(
                                            f"{row.get('updated_by_officer_name') or '—'} · Badge {row.get('updated_by_officer_badge') or 'N/A'} · "
                                            f"{(row.get('action') or 'STARTED').lower()}"
                                        ).classes('text-[9px] text-slate-500')
                                    ui.label(_fmt(row.get('timestamp'))).classes('text-[9px] text-slate-400 font-mono shrink-0')

            # ── Notes & evidence ─────────────────────────────
            with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                    ui.icon('engineering', size='sm').classes('text-blue-800')
                    ui.label('Investigation Notes & Collected Evidence').classes('text-base font-bold text-slate-900 fantasy-title')
                    ui.badge('Confidential — police and administrators only').classes(
                        'bg-red-50 text-red-700 border border-red-200 font-bold text-[10px] px-2 rounded-full'
                    )

                try:
                    entries = list_investigation_entries(fir_id, user)
                except PermissionError:
                    entries = []

                if panel and panel.get('can_manage'):
                    with ui.row().classes('w-full gap-4 flex-wrap items-start mt-2'):
                        # Note form
                        with ui.card().classes('flex-1 min-w-72 p-5 rounded-2xl bg-slate-50 border border-slate-200'):
                            ui.label('Add Internal Note').classes('text-[11px] font-black text-slate-700 uppercase mb-3')
                            n_title = ui.input('Note title *').props('outlined').classes('w-full mb-2')
                            n_text = ui.textarea('Note text *').props('outlined rows=3').classes('w-full mb-3')

                            def save_note():
                                try:
                                    add_investigation_note(fir_id, user, n_title.value or '', n_text.value or '')
                                    ui.notify('Investigation note recorded.', type='positive')
                                    case_view.refresh()
                                except (ValueError, PermissionError) as exc:
                                    ui.notify(str(exc), type='warning')
                                except Exception as exc:
                                    ui.notify(f'Could not save the note: {exc}', type='negative')

                            ui.button('Save Note', icon='sticky_note2', on_click=save_note).props('unelevated').classes(
                                'bg-blue-800 text-white font-bold rounded-xl px-5 py-2 text-xs'
                            )

                        # Evidence form
                        with ui.card().classes('flex-1 min-w-72 p-5 rounded-2xl bg-slate-50 border border-slate-200'):
                            ui.label('Record Collected Evidence').classes('text-[11px] font-black text-slate-700 uppercase mb-3')
                            e_title = ui.input('Evidence title *').props('outlined').classes('w-full mb-2')
                            e_desc = ui.textarea('Description of the material and how it was obtained *').props('outlined rows=2').classes('w-full mb-2')
                            e_when = ui.input('Collection date & time *', placeholder='2026-11-04 14:30').props('outlined type=datetime-local').classes('w-full mb-2')
                            e_status = ui.select(EVIDENCE_STATUSES, label='Evidence status', value='COLLECTED').props('outlined').classes('w-full mb-3')

                            async def handle_upload(event):
                                content = await event.file.read()
                                upload = event.file
                                try:
                                    add_investigation_evidence(
                                        fir_id=fir_id, officer_user=user,
                                        title=e_title.value or '',
                                        description=e_desc.value or f"Collected material: {upload.name}",
                                        collected_at=e_when.value or '',
                                        evidence_status=e_status.value or 'COLLECTED',
                                        file_name=upload.name, content=content,
                                        content_type=getattr(upload, 'content_type', None) or getattr(upload, 'type', None) or '',
                                    )
                                except (ValueError, PermissionError) as exc:
                                    ui.notify(str(exc), type='warning')
                                    return
                                except Exception as exc:
                                    ui.notify(f'Upload failed: {exc}', type='negative')
                                    return
                                ui.notify('Evidence file recorded in secure case storage.', type='positive')
                                case_view.refresh()

                            ui.upload(
                                label=f'Attach evidence file (max {MAX_FILE_BYTES // (1024 * 1024)} MB)',
                                auto_upload=True, max_files=1, max_file_size=MAX_FILE_BYTES,
                                on_upload=handle_upload,
                            ).props('flat bordered').classes('w-full mb-3')
                            ui.label('Permitted: ' + ' '.join(sorted(ALLOWED_EXTENSIONS))).classes('text-[9px] text-slate-400 mb-3')

                            def save_evidence_record():
                                try:
                                    add_investigation_evidence(
                                        fir_id=fir_id, officer_user=user,
                                        title=e_title.value or '', description=e_desc.value or '',
                                        collected_at=e_when.value or '', evidence_status=e_status.value or 'COLLECTED',
                                    )
                                    ui.notify('Evidence record saved.', type='positive')
                                    case_view.refresh()
                                except (ValueError, PermissionError) as exc:
                                    ui.notify(str(exc), type='warning')
                                except Exception as exc:
                                    ui.notify(f'Could not save the evidence: {exc}', type='negative')

                            ui.button('Save Evidence Record', icon='library_add', on_click=save_evidence_record).props('unelevated').classes(
                                'bg-emerald-700 text-white font-bold rounded-xl px-5 py-2 text-xs'
                            )
                else:
                    ui.label(
                        'Notes and evidence can be added only by the officer assigned to this case.'
                    ).classes('text-[11px] text-slate-500 mt-2')

                ui.label(f'Case records ({len(entries)})').classes('text-[10px] font-bold text-slate-500 uppercase mt-5 mb-2')
                if not entries:
                    ui.label('No internal notes or evidence recorded yet.').classes('text-[11px] text-slate-400')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for entry in entries:
                            with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-slate-50/60'):
                                with ui.row().classes('w-full items-start justify-between gap-3 flex-wrap'):
                                    with ui.row().classes('items-start gap-3 flex-1'):
                                        ui.icon(
                                            'attachment' if entry['entry_type'] == 'EVIDENCE' else 'sticky_note2',
                                            size='xs',
                                        ).classes('text-blue-800 mt-1')
                                        with ui.column().classes('gap-0.5'):
                                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                                ui.label(entry['title']).classes('text-xs font-black text-slate-900')
                                                ui.badge(entry['entry_type']).classes(
                                                    'bg-indigo-100 text-indigo-800 font-bold text-[9px] px-1.5 rounded'
                                                )
                                                if entry.get('evidence_status'):
                                                    ui.badge(entry['evidence_status'].replace('_', ' ')).classes(
                                                        'bg-amber-100 text-amber-800 border border-amber-200 font-bold text-[9px] px-1.5 rounded'
                                                    )
                                            ui.label(entry['description']).classes('text-[11px] text-slate-700')
                                            ui.label(
                                                f"{entry['officer_name']} · {_fmt(entry['created_at'])}"
                                                + (f" · collected {_fmt(entry['collected_at'])}" if entry.get('collected_at') else '')
                                            ).classes('text-[9px] text-slate-500 font-mono')
                                            if entry.get('file_name'):
                                                ui.label(
                                                    f"{entry['file_name']} · {int(entry.get('file_size') or 0) // 1024} KB"
                                                ).classes('text-[9px] text-slate-500 font-mono')

                                    with ui.row().classes('items-center gap-2'):
                                        if entry.get('stored_name'):
                                            def open_entry(item=entry):
                                                try:
                                                    loaded = get_evidence_file(item['id'], user)
                                                except PermissionError:
                                                    ui.notify('Not authorised to open this evidence.', type='negative')
                                                    return
                                                if not loaded:
                                                    ui.notify('The stored file is no longer available.', type='warning')
                                                    return
                                                data, name, ctype = loaded
                                                _open_file_viewer(data, name, ctype)

                                            ui.button('View File', icon='visibility', on_click=open_entry).props('flat dense size=sm').classes(
                                                'text-blue-800 font-bold'
                                            )
                                        if panel and panel.get('can_manage') and entry['entry_type'] == 'EVIDENCE':
                                            picker = ui.select(
                                                EVIDENCE_STATUSES, value=entry.get('evidence_status'),
                                            ).props('dense outlined options-dense').classes('w-44')

                                            def change_status(item=entry, sel=picker):
                                                try:
                                                    update_evidence_status(item['id'], user, sel.value)
                                                    ui.notify('Evidence status updated.', type='positive')
                                                    case_view.refresh()
                                                except (ValueError, PermissionError) as exc:
                                                    ui.notify(str(exc), type='warning')

                                            ui.button('Set', icon='update', on_click=change_status).props('flat dense size=sm').classes(
                                                'text-slate-600 font-bold'
                                            )

        case_view()
        _listen(case_view)


# ==========================================
# 4. COMMAND CENTRE REDIRECT
# ==========================================
@ui.page('/police/fir-monitor')
def police_fir_monitor_redirect() -> None:
    """All-FIR oversight belongs to the administrator monitor, not an officer badge."""
    ui.navigate.to('/police/firs')


# ==========================================
# 5. NOTIFICATION CENTRE
# ==========================================
@ui.page('/police/notifications')
def police_notifications_page() -> None:
    """Officer inbox: assignment alerts, citizen messages, evidence and stage updates."""
    user = require_police_user()
    if not user:
        return
    officer_id = user.get("id", "")

    with portal_page(
        'police', '/police/notifications', 'Notification Centre',
        'Every alert is generated by a real event on your assigned cases.',
    ):
        @ui.refreshable
        def inbox_view() -> None:
            notifs = get_user_notifications(officer_id)
            unread = get_unread_count(officer_id)

            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 pb-4 border-b border-slate-200'):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('notifications', size='md').classes('text-blue-800')
                        ui.label('Officer Inbox').classes('text-2xl font-bold text-slate-900 fantasy-title')
                        if unread:
                            ui.badge(f'{unread} unread').classes('bg-amber-500 text-slate-950 font-bold text-[11px] px-2.5 py-0.5 rounded-full')
                    with ui.row().classes('gap-2'):
                        if notifs:
                            def read_all():
                                mark_all_read(officer_id)
                                ui.notify('All notifications marked as read.', type='positive')
                                inbox_view.refresh()

                            ui.button('Mark All Read', icon='done_all', on_click=read_all).props('flat size=sm').classes(
                                'text-blue-900 font-bold'
                            )
                        ui.button('My Cases', icon='folder_special', on_click=lambda: ui.navigate.to('/police/firs')).props(
                            'flat size=sm'
                        ).classes('text-slate-600 font-bold')

                if not notifs:
                    with ui.column().classes('w-full items-center py-16 gap-3 text-center'):
                        ui.icon('notifications_none', size='xl').classes('text-slate-300')
                        ui.label('No notifications yet.').classes('text-base font-semibold text-slate-600')
                        ui.label(
                            'Case assignments, citizen chat messages, evidence uploads and stage updates '
                            'will appear here the moment they happen.'
                        ).classes('text-xs text-slate-400 max-w-sm')
                    return

                with ui.column().classes('w-full gap-3 mt-4'):
                    for item in notifs:
                        is_read = item.get('is_read', 0) == 1
                        severity = item.get('severity', 'INFO')
                        sev_map = {
                            'SUCCESS': ('bg-emerald-50 border-emerald-200', 'text-emerald-700', 'check_circle'),
                            'WARNING': ('bg-amber-50 border-amber-200', 'text-amber-700', 'warning'),
                            'ALERT': ('bg-red-50 border-red-200', 'text-red-700', 'error'),
                            'INFO': ('bg-blue-50/70 border-blue-200', 'text-blue-700', 'info'),
                        }
                        card_bg, icon_cls, default_icon = sev_map.get(severity, sev_map['INFO'])
                        if is_read:
                            card_bg = 'bg-slate-50 border-slate-200'
                        case_fir_id = item.get('case_fir_id') or ''

                        with ui.card().classes(f'w-full p-5 rounded-2xl border {card_bg} shadow-xs'):
                            with ui.row().classes('w-full items-start gap-4'):
                                ui.icon(default_icon, size='sm').classes(f'{icon_cls} mt-1')
                                with ui.column().classes('gap-1 flex-1'):
                                    with ui.row().classes('items-center justify-between w-full flex-wrap gap-2'):
                                        with ui.row().classes('items-center gap-2 flex-wrap'):
                                            ui.label(item.get('title') or 'Notification').classes('text-sm font-black text-slate-900')
                                            if not is_read:
                                                ui.badge('NEW').classes('bg-amber-500 text-slate-950 font-bold text-[9px] px-1.5 rounded')
                                        ui.label(_fmt(item.get('created_at'))).classes('text-[10px] text-slate-400 font-mono')

                                    if item.get('fir_number'):
                                        ui.label(f"FIR No: {item.get('fir_number')}").classes('text-xs font-black text-slate-900 font-mono')
                                        ui.label(f"Citizen: {item.get('citizen_name') or 'Not recorded'}").classes(
                                            'text-[11px] font-bold text-blue-800'
                                        )
                                    if item.get('complaint_reference'):
                                        ui.label(f"Complaint Ref: {item.get('complaint_reference')}").classes(
                                            'text-[10px] text-slate-500 font-mono'
                                        )

                                    ui.label(item.get('message') or '').classes(
                                        'text-xs text-slate-800 whitespace-pre-line leading-relaxed mt-1'
                                    )

                                    with ui.row().classes('gap-2 mt-2 flex-wrap'):
                                        if case_fir_id:
                                            ui.button('Open Case', icon='folder_open', on_click=lambda fid=case_fir_id: ui.navigate.to(f'/police/fir/{fid}')).props(
                                                'unelevated size=xs'
                                            ).classes('bg-blue-800 text-white font-bold rounded-lg')
                                            ui.button('Open Chat', icon='chat', on_click=lambda fid=case_fir_id: ui.navigate.to(f'/police/chat/{fid}')).props(
                                                'outline size=xs'
                                            ).classes('text-emerald-700 border-emerald-300 font-bold rounded-lg')
                                        if not is_read:
                                            def read_one(nid=item['id']):
                                                mark_notification_read(nid, officer_id)
                                                inbox_view.refresh()

                                            ui.button('Mark Read', icon='done', on_click=read_one).props('flat dense size=xs').classes(
                                                'text-slate-500 font-bold'
                                            )

        inbox_view()

        def _on_inbox_event(event) -> None:
            if event.get('type') == 'NOTIFICATION_CREATED' and event.get('user_id') == officer_id:
                note = event.get('notification') or {}
                ui.notify(
                    f"{note.get('title', 'Update')}: {str(note.get('message', ''))[:120]}",
                    type='info', position='top-right', close_button=True, timeout=8000,
                )
                _alert_sound()

        _listen(inbox_view, on_event=_on_inbox_event)
        ui.timer(30.0, inbox_view.refresh)


# ==========================================
# 6. OFFICER PROFILE & PERFORMANCE
# ==========================================
@ui.page('/police/profile')
def police_profile_page() -> None:
    """Departmental identity, caseload and milestone-based performance record."""
    user = require_police_user()
    if not user:
        return

    officer_id = user.get("id", "")
    performance = get_officer_performance(officer_id)
    stars = int(performance.get('stars') or 0)
    max_stars = int(performance.get('max_stars') or 5)
    next_level = performance.get('next_level')

    with portal_page(
        'police', '/police/profile', 'Officer Profile & Performance',
        'Departmental credentials, caseload and milestone credits earned on real investigations.',
    ):
        with ui.card().classes('w-full max-w-4xl mx-auto p-8 rounded-3xl paper-card bg-white border border-slate-200 shadow-md'):
            with ui.row().classes('items-center gap-6 mb-6 pb-6 border-b border-slate-200 flex-wrap'):
                with ui.element('div').classes(
                    'w-20 h-20 rounded-full flex items-center justify-center '
                    'bg-gradient-to-br from-blue-800 to-slate-900 text-white font-black text-2xl shadow-md'
                ):
                    ui.label(_initials(user.get('name')))
                with ui.column().classes('gap-1 flex-1'):
                    ui.label(f"{user.get('rank') or 'Officer'} {user.get('name', 'Police Officer')}").classes(
                        'text-3xl font-black text-slate-900 fantasy-title'
                    )
                    ui.label(
                        f"Username: {user.get('email') or '—'} · Badge: {user.get('badge_number') or 'Not recorded'} · "
                        f"Station: {user.get('station') or 'Not recorded'}"
                    ).classes('text-xs font-bold text-blue-800')
                    with ui.row().classes('items-center gap-1'):
                        for index in range(max_stars):
                            ui.icon('star' if index < stars else 'star_border', size='xs').classes(
                                'text-amber-500' if index < stars else 'text-slate-300'
                            )
                        ui.label(performance.get('level') or 'New Investigator').classes(
                            'text-xs font-black text-slate-700 ml-2'
                        )

            with ui.row().classes('w-full flex-wrap gap-3 mb-6'):
                for label, value, icon_name in [
                    ('Performance Credits', performance.get('total_credits', 0), 'emoji_events'),
                    ('Cases Assigned', performance.get('assigned_count', 0), 'assignment_ind'),
                    ('Cases Completed', performance.get('completed_count', 0), 'verified'),
                    ('Credit Level', performance.get('level', '—'), 'military_tech'),
                ]:
                    with ui.card().classes(f'flex-1 min-w-40 p-4 rounded-2xl bg-slate-50 border border-slate-200'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon(icon_name, size='xs').classes('text-blue-800')
                            ui.label(label).classes('text-[10px] font-bold text-slate-500 uppercase')
                        ui.label(str(value)).classes('text-2xl font-black text-slate-900 mt-1')

            if next_level:
                remaining = int(next_level['min_points']) - int(performance.get('total_credits') or 0)
                ui.label(
                    f'{remaining} more verified milestone credits reach {next_level["level"]} '
                    f'({next_level["stars"]} star level). Credits are awarded only for completed '
                    'investigation milestones, never for button clicks.'
                ).classes('text-[11px] text-slate-600 mb-5')

            with ui.column().classes('w-full gap-3 text-xs mb-6'):
                for label, val, icon in [
                    ('Officer Full Name', user.get('name'), 'person'),
                    ('Official Rank', user.get('rank') or 'Not recorded', 'military_tech'),
                    ('Badge Identification No.', user.get('badge_number') or 'Not recorded', 'badge'),
                    ('Station Jurisdiction', user.get('station') or 'Not recorded', 'local_police'),
                    ('Home District', user.get('district') or 'Not recorded', 'location_city'),
                    ('Departmental Role', user.get('role', 'OFFICER'), 'verified_user'),
                    ('Account Status', user.get('status') or 'ACTIVE', 'lock'),
                    ('Registered Contact', user.get('phone') or 'Not recorded', 'call'),
                ]:
                    with ui.row().classes('justify-between p-4 rounded-xl bg-slate-50 border border-slate-200 items-center'):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon(icon, size='xs').classes('text-blue-800')
                            ui.label(label).classes('font-bold text-slate-600')
                        ui.label(str(val)).classes('font-bold text-slate-900 text-sm')

            ui.label('Milestone Credit History').classes('text-sm font-black text-slate-700 uppercase tracking-wider mb-2')
            history = performance.get('history') or []
            if not history:
                with ui.card().classes('w-full p-8 rounded-2xl bg-slate-50 border border-slate-200 text-center'):
                    ui.icon('trophy', size='lg').classes('text-slate-300 mb-2')
                    ui.label('No credits awarded yet.').classes('text-xs font-bold text-slate-500')
                    ui.label(
                        'Credits are recorded automatically when a verified milestone is completed on an assigned FIR.'
                    ).classes('text-[10px] text-slate-400 mt-1')
            else:
                with ui.column().classes('w-full gap-2'):
                    for row in history:
                        with ui.row().classes(
                            'w-full items-center justify-between gap-3 p-3.5 rounded-xl border border-slate-200 bg-slate-50/70'
                        ):
                            with ui.column().classes('gap-0.5 flex-1'):
                                ui.label(row.get('milestone', '').replace('_', ' ')).classes('text-xs font-black text-slate-900')
                                ui.label(
                                    f"FIR No: {row.get('fir_number') or '—'}"
                                ).classes('text-[10px] font-bold text-slate-600 font-mono')
                                ui.label(f"Citizen: {row.get('citizen_name') or 'Not recorded'}").classes(
                                    'text-[10px] font-bold text-blue-800'
                                )
                                ui.label(row.get('reason') or '').classes('text-[10px] text-slate-500')
                            with ui.column().classes('items-end gap-0.5'):
                                ui.label(f"+{row.get('points')}").classes('text-base font-black text-emerald-700')
                                ui.label(_fmt(row.get('awarded_at'))).classes('text-[9px] text-slate-400 font-mono')


# ==========================================
# 7. ASSIGNED COMPLAINTS
# ==========================================
@ui.page('/police/complaints')
def police_complaints_page() -> None:
    """Complaints assigned to this officer's badge."""
    user = require_police_user()
    if not user:
        return

    if user.get('role') == 'ADMIN':
        complaints = get_all_complaints(actor_user=user)
    else:
        complaints = get_complaints_for_officer(user['id'])

    with portal_page(
        'police', '/police/complaints', 'Assigned Complaints',
        'Citizen complaints routed to your badge, before or after FIR registration.',
    ):
        ui.label(f'{len(complaints)} assigned complaint(s)').classes('text-sm font-bold text-slate-700 mb-3')

        if not complaints:
            with ui.card().classes('w-full p-12 text-center bg-white border border-slate-200 rounded-2xl shadow-sm'):
                ui.icon('inbox', size='xl').classes('text-slate-300 mb-3')
                ui.label('No complaints assigned to you yet.').classes('text-slate-600 text-lg font-bold')
                ui.label(
                    'Complaints appear here once the Verification Officer routes them to your badge.'
                ).classes('text-xs text-slate-500 mt-1')
        else:
            with ui.column().classes('w-full gap-3'):
                for complaint in complaints:
                    with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-xs hover:shadow-md transition-all'):
                        with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                            with ui.column().classes('flex-1 gap-1'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label(f"Complaint Ref: {complaint.get('reference', '')}").classes(
                                        'text-sm font-black text-slate-900 font-mono'
                                    )
                                    ui.badge((complaint.get('status') or '').replace('_', ' ')).classes(
                                        f'{_status_class(complaint.get("status"))} border font-bold text-[10px] px-2 rounded-full'
                                    )
                                ui.label(f"Citizen: {complaint.get('citizen_name') or 'Not recorded'}").classes(
                                    'text-xs font-bold text-blue-800'
                                )
                                ui.label(complaint.get('title') or '').classes('text-base font-bold text-slate-800')
                                ui.label(
                                    f"Phone: {complaint.get('citizen_phone') or '—'} · "
                                    f"Category: {complaint.get('category', '')} · {_fmt(complaint.get('submitted_at'))}"
                                ).classes('text-xs text-slate-500')
                            ui.button('View & Manage', icon='visibility', on_click=lambda cid=complaint['id']: ui.navigate.to(f'/police/complaint/{cid}')).props(
                                'unelevated size=xs'
                            ).classes('bg-blue-800 hover:bg-blue-900 text-white rounded-lg px-3 py-1 font-bold')


@ui.page('/police/complaint/{complaint_id}')
def police_complaint_detail_page(complaint_id: str) -> None:
    """Complaint detail with status control, citizen chat and FIR registration."""
    user = require_police_user()
    if not user:
        return

    complaint = get_complaint_by_id(complaint_id, actor_user=user)
    if not complaint:
        with portal_page('police', '/police/complaints', 'Not Found', ''):
            ui.label('Complaint not found or access denied.').classes('text-red-600 font-bold')
            ui.button('Back', on_click=lambda: ui.navigate.to('/police/complaints')).props('flat')
        return

    with portal_page(
        'police', '/police/complaints', f"Complaint: {complaint['reference']}",
        f"Citizen: {complaint.get('citizen_name') or 'Not recorded'}",
    ):
        ui.button('← Back to Assigned Complaints', icon='arrow_back', on_click=lambda: ui.navigate.to('/police/complaints')).props(
            'flat'
        ).classes('text-slate-600 font-bold mb-4')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-2xl shadow-sm mb-4'):
            with ui.row().classes('items-center justify-between mb-4 flex-wrap gap-2'):
                with ui.column().classes('gap-0'):
                    ui.label(f"Complaint Ref: {complaint['reference']}").classes('text-2xl font-black text-slate-900 font-mono')
                    ui.label(f"Citizen: {complaint.get('citizen_name') or 'Not recorded'}").classes(
                        'text-sm font-bold text-blue-800'
                    )
                    ui.label(complaint.get('title') or '').classes('text-base font-bold text-slate-700 mt-1')
                ui.badge((complaint.get('status') or '').replace('_', ' ')).classes(
                    f'{_status_class(complaint.get("status"))} border font-bold text-sm px-3 py-1 rounded-full'
                )

            with ui.column().classes('gap-3 text-sm'):
                for label, val in [
                    ('Category', complaint.get('category', '—')),
                    ('Submitted Date', _fmt(complaint.get('submitted_at'))),
                    ('Location', complaint.get('location', '—')),
                    ('Complainant Phone', complaint.get('citizen_phone', '—')),
                    ('Verification Status', complaint.get('verification_status') or 'Not recorded'),
                    ('Verified By', complaint.get('verified_by_name') or 'Not recorded'),
                    ('Description', complaint.get('description', '—')),
                ]:
                    with ui.row().classes('items-start gap-3'):
                        ui.label(f'{label}:').classes('font-bold text-slate-500 min-w-40')
                        ui.label(str(val)).classes('text-slate-800')

        with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-sm mb-4'):
            ui.label('Update Complaint Status').classes('text-sm font-black text-slate-700 uppercase tracking-wider mb-3')
            status_options = ['SUBMITTED', 'ASSIGNED', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED',
                              'INVESTIGATION', 'RESOLVED', 'CLOSED', 'REJECTED']
            current_status = complaint.get('status') or 'SUBMITTED'
            if current_status not in status_options:
                # A complaint already at the FIR desk (VERIFIED / FIR_CREATED) must still render
                # its real stage; NiceGUI rejects a select value that is missing from its options.
                status_options.append(current_status)
            status_select = ui.select(
                label='Status',
                options=status_options,
                value=current_status,
            ).classes('w-full mb-3').props('outlined')

            def update_status():
                if not status_select.value:
                    ui.notify('Please select a status', type='warning')
                    return
                try:
                    update_complaint_status(complaint['id'], status_select.value, user)
                    ui.notify('Complaint status updated.', type='positive')
                    ui.navigate.to(f'/police/complaint/{complaint_id}')
                except Exception as error:
                    ui.notify(f'Failed: {error}', type='negative')

            ui.button('Update Status', icon='update', on_click=update_status).props('unelevated').classes(
                'bg-emerald-700 text-white font-bold rounded-xl px-6 py-2 text-xs'
            )

        with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-sm mb-4'):
            ui.label('Communication').classes('text-sm font-black text-slate-700 uppercase tracking-wider mb-3')
            ui.button(
                'Chat with Citizen', icon='forum',
                on_click=lambda: ui.navigate.to(f'/police/complaint-chat/{complaint["id"]}'),
            ).props('unelevated').classes('bg-blue-800 text-white font-bold rounded-xl px-6 py-2 text-xs')

        if complaint.get('fir_id'):
            with ui.card().classes('w-full p-5 bg-emerald-50 border border-emerald-200 rounded-2xl shadow-sm'):
                ui.label('FIR Already Registered').classes('text-sm font-black text-emerald-800 uppercase tracking-wider mb-2')
                ui.label(
                    f"FIR No: {complaint.get('fir_number') or complaint.get('fir_id')}"
                ).classes('text-xs font-black text-emerald-900 font-mono')
                ui.label(f"Citizen: {complaint.get('citizen_name') or 'Not recorded'}").classes(
                    'text-[11px] font-bold text-emerald-800 mb-3'
                )
                ui.button('Open Case File', icon='folder_open', on_click=lambda fid=complaint['fir_id']: ui.navigate.to(f'/police/fir/{fid}')).props(
                    'unelevated size=sm'
                ).classes('bg-emerald-700 text-white font-bold rounded-xl')
        else:
            with ui.card().classes('w-full p-5 bg-emerald-50 border border-emerald-200 rounded-2xl shadow-sm'):
                ui.label('Register Official FIR').classes('text-sm font-black text-emerald-800 uppercase tracking-wider mb-1')
                ui.label(
                    'Convert this complaint into an official First Information Report. This is recorded on '
                    'the versioned case ledger and formally initiates the investigation.'
                ).classes('text-xs text-emerald-700 mb-4')

                def handle_register_fir():
                    try:
                        result = _create_fir_from_complaint(complaint['id'], user)
                        ui.notify(f"FIR {result['fir_number']} registered.", type='positive')
                        ui.navigate.to(f"/police/fir/{result['fir_id']}")
                    except ValueError as error:
                        ui.notify(str(error), type='warning')
                    except PermissionError as error:
                        ui.notify(str(error), type='negative')
                    except Exception as error:
                        ui.notify(f'Error registering FIR: {error}', type='negative')

                ui.button(
                    'Register FIR from this Complaint', icon='gavel', on_click=handle_register_fir,
                ).props('unelevated').classes(
                    'bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-xl px-6 py-2.5 shadow-md text-xs'
                )

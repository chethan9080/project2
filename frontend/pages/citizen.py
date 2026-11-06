"""
Citizen Portal - Dashboard, 5-step complaint filing wizard, My Complaints,
Live Tracking, Notifications and Profile.

All data comes from the existing database services. Citizens only ever see
their own complaints, FIRs, notifications and conversations; hashes, block
identifiers and internal verification remarks are never rendered here.
"""

import base64
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from nicegui import app, background_tasks, ui

from frontend.i18n import t
from frontend.components.badges import fir_status_badge
from frontend.components.layout import portal_page
from frontend.components.case_tracking_timeline import render_live_fir_timeline
from backend.services.auth_service import (
    get_citizen_access_issue,
    get_current_user,
    get_dev_auto_login_user,
    set_current_user,
)
from backend.services.fir_service import (
    get_fir_by_id,
    get_operational_case_timeline,
    get_firs,
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read,
)
from backend.services.complaint_service import (
    COMPLAINT_CATEGORIES,
    POLICE_STATION_OPTIONS,
    STATUS_GROUPS,
    attach_complaint_evidence,
    complaint_status_group,
    complaint_status_label,
    create_complaint,
    get_complaint_by_id,
    get_complaint_stage_progress,
    get_complaints_for_citizen,
)
from backend.services.complaint_evidence_service import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_BYTES,
    MAX_FILES,
    create_staging_token,
    evidence_bytes,
    list_staged_files,
    move_staged_files_to_complaint,
    remove_staged_file,
    save_staged_file,
)
from backend.services.realtime_events import subscribe, unsubscribe
from backend.services.fir_document_service import get_current_document
from backend.services.investigation_service import add_citizen_evidence
from backend.services.citizen_registration_service import (
    get_application_by_citizen,
    media_type_for,
    resolve_secure_file,
)


# ==========================================
# SHARED HELPERS
# ==========================================

def require_citizen_user() -> Optional[Dict[str, Any]]:
    """Ensure the session belongs to a fully verified, approved Citizen."""
    user = get_current_user() or {}
    if not user or user.get("role") != "CITIZEN":
        dev_user = get_dev_auto_login_user()
        if not dev_user:
            ui.navigate.to('/login')
            return None
        set_current_user(dev_user)
        user = dev_user

    issue = get_citizen_access_issue(user)
    if issue:
        set_current_user(None)
        ui.navigate.to('/login?verification=required')
        return None
    return user


def render_account_status_badge(user: dict) -> None:
    """Show the citizen's real account state instead of a generic verified claim."""
    status = user.get('status', 'ACTIVE')
    label, styles = {
        'PENDING_VERIFICATION': ('Verification Pending', 'bg-amber-100 text-amber-900 border-amber-300'),
        'SUSPENDED': ('Account Suspended', 'bg-rose-100 text-rose-900 border-rose-300'),
    }.get(status, ('Verified Citizen', 'bg-emerald-100 text-emerald-900 border-emerald-300'))
    ui.badge(label).classes(f'{styles} border font-bold text-xs px-3 py-1 rounded-full')


STATUS_BADGE_STYLES = {
    'SUBMITTED': 'bg-amber-100 text-amber-900 border-amber-300',
    'ASSIGNED': 'bg-blue-100 text-blue-900 border-blue-300',
    'UNDER_REVIEW': 'bg-blue-100 text-blue-900 border-blue-300',
    'ADDITIONAL_INFO_REQUIRED': 'bg-orange-100 text-orange-900 border-orange-300',
    'INVESTIGATION': 'bg-purple-100 text-purple-900 border-purple-300',
    'FIR_CREATED': 'bg-sky-100 text-sky-900 border-sky-300',
    'RESOLVED': 'bg-emerald-100 text-emerald-900 border-emerald-300',
    'CLOSED': 'bg-slate-100 text-slate-700 border-slate-300',
    'REJECTED': 'bg-rose-100 text-rose-900 border-rose-300',
}


def complaint_badge(status: Optional[str]) -> None:
    label = complaint_status_label(status)
    styles = STATUS_BADGE_STYLES.get(status or '', 'bg-slate-100 text-slate-700 border-slate-300')
    ui.badge(label).classes(f'{styles} border font-bold text-[10px] px-2.5 py-0.5 rounded-full')


def fmt_timestamp(value: Any, with_time: bool = True) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    text = text.replace('T', ' ')
    return text[:19] if with_time else text[:10]


def fmt_size(size: Any) -> str:
    try:
        size = int(size)
    except (TypeError, ValueError):
        return '—'
    if size >= 1024 * 1024:
        return f'{size / (1024 * 1024):.1f} MB'
    if size >= 1024:
        return f'{size / 1024:.0f} KB'
    return f'{size} B'


def parse_evidence(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        except (ValueError, TypeError):
            return []
    return []


def render_evidence_list(complaint_id: str, evidence: List[Dict[str, Any]]) -> None:
    """Render evidence files with server-side authorized downloads only."""
    if not evidence:
        ui.label('No evidence files were attached to this complaint.').classes('text-xs text-slate-500 italic')
        return

    def download(item: Dict[str, Any]) -> None:
        content = evidence_bytes(complaint_id, item.get('stored_name', ''))
        if not content:
            ui.notify('This evidence file is no longer available.', type='warning')
            return
        ui.download(content, item.get('name') or 'evidence')

    with ui.column().classes('w-full gap-2'):
        for item in evidence:
            with ui.row().classes('w-full items-center justify-between gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200'):
                with ui.row().classes('items-center gap-2 flex-1 min-w-0'):
                    ui.icon('attach_file', size='xs').classes('text-slate-500')
                    with ui.column().classes('gap-0 min-w-0'):
                        ui.label(item.get('name') or 'evidence').classes('text-xs font-bold text-slate-800 truncate')
                        ui.label(f"{fmt_size(item.get('size'))} · {item.get('content_type') or 'file'}").classes('text-[10px] text-slate-500')
                        if item.get('stage') == 'CITIZEN_ADDITIONAL':
                            ui.label(
                                f"{item.get('caption') or 'Added during the investigation'} · "
                                f"{str(item.get('uploaded_at') or '')[:16].replace('T', ' ')}"
                            ).classes('text-[10px] font-bold text-emerald-700')
                ui.button('Download', icon='download', on_click=lambda i=item: download(i)).props('flat dense size=sm').classes('text-emerald-700 font-bold text-[11px]')


TIMELINE_STYLES = {
    'COMPLETED': ('bg-emerald-600 text-white', 'border-emerald-200 bg-emerald-50/70', 'check'),
    'CURRENT': ('bg-blue-700 text-white', 'border-blue-200 bg-blue-50/70', 'radio_button_checked'),
    'UPCOMING': ('bg-slate-200 text-slate-500', 'border-slate-200 bg-white', 'radio_button_unchecked'),
    'WARNING': ('bg-amber-500 text-white', 'border-amber-300 bg-amber-50/70', 'warning'),
}


def render_complaint_timeline(stages: List[Dict[str, Any]]) -> None:
    """Data-driven complaint timeline; every timestamp comes from the database."""
    if not stages:
        ui.label('Progress information is not available yet.').classes('text-xs text-slate-500')
        return
    with ui.column().classes('w-full gap-3'):
        for stage in stages:
            dot_cls, card_cls, icon_name = TIMELINE_STYLES.get(stage.get('state', 'UPCOMING'), TIMELINE_STYLES['UPCOMING'])
            with ui.row().classes('w-full items-start gap-4'):
                with ui.element('div').classes(f'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center shadow-sm {dot_cls}'):
                    ui.icon(icon_name, size='xs')
                with ui.card().classes(f'flex-1 p-4 rounded-2xl border {card_cls} shadow-xs'):
                    with ui.row().classes('w-full justify-between items-start flex-wrap gap-1'):
                        ui.label(stage.get('label', '')).classes('font-bold text-slate-900 text-sm flex-1')
                        if stage.get('timestamp'):
                            ui.label(fmt_timestamp(stage.get('timestamp'))).classes('text-[10px] text-slate-500 font-mono shrink-0')
                    ui.label(stage.get('description', '')).classes('text-xs text-slate-700 mt-1 leading-relaxed')


def _notification_icon(severity: str, notification_type: str) -> str:
    if notification_type == 'CHAT_MESSAGE':
        return 'forum'
    return {
        'SUCCESS': 'check_circle',
        'WARNING': 'warning',
        'ALERT': 'error',
        'INFO': 'info',
    }.get(severity, 'notifications')


def _active_case_rows(user_id: str) -> List[Dict[str, Any]]:
    """Merge the citizen's own complaints and FIRs into one activity list."""
    rows: List[Dict[str, Any]] = []
    for cmp in get_complaints_for_citizen(user_id):
        rows.append({
            'kind': 'complaint',
            'id': cmp.get('id'),
            'reference': cmp.get('reference') or '—',
            'fir_number': cmp.get('fir_number'),
            'title': cmp.get('category') or 'Complaint',
            'status': cmp.get('status'),
            'status_label': complaint_status_label(cmp.get('status')),
            'updated_at': cmp.get('updated_at') or cmp.get('submitted_at'),
            'detail_url': f"/citizen/complaint/{cmp.get('id')}",
            'station': cmp.get('police_station'),
        })
    for fir in get_firs(actor_user={'id': user_id, 'role': 'CITIZEN'}):
        rows.append({
            'kind': 'fir',
            'id': fir.get('id'),
            'reference': fir.get('fir_number') or '—',
            'fir_number': fir.get('fir_number'),
            'title': fir.get('incident_type') or 'FIR',
            'status': fir.get('status'),
            'status_label': (fir.get('status') or '').replace('_', ' ').title(),
            'updated_at': fir.get('updated_at') or fir.get('created_at'),
            'detail_url': f"/citizen/fir/{fir.get('id')}",
            'station': fir.get('police_station'),
        })
    rows.sort(key=lambda item: str(item.get('updated_at') or ''), reverse=True)
    return rows


# ==========================================
# 1. CITIZEN DASHBOARD
# ==========================================
@ui.page('/citizen')
def citizen_dashboard() -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')
    client = ui.context.client

    with portal_page(
        'citizen',
        '/citizen',
        'Citizen Dashboard',
        'Track your complaints, registered FIRs, verification status and officer updates.',
    ):
        @ui.refreshable
        def dashboard_content() -> None:
            complaints = get_complaints_for_citizen(user_id)
            firs = get_firs(actor_user={'id': user_id, 'role': 'CITIZEN'})
            notifications = get_user_notifications(user_id, limit=5)
            unread = get_unread_count(user_id)
            active_cases = [
                row for row in _active_case_rows(user_id)
                if row.get('status') not in ('CLOSED', 'RESOLVED', 'REJECTED')
            ]

            with ui.card().classes('w-full p-5 bg-white rounded-2xl border border-slate-200 '
                                   'border-l-4 border-l-emerald-700 shadow-sm'):
                with ui.row().classes('w-full items-center gap-4 flex-wrap'):
                    with ui.element('div').classes(
                        'w-12 h-12 shrink-0 rounded-full flex items-center justify-center '
                        'bg-emerald-800 text-white text-lg font-black shadow'
                    ):
                        ui.label(str(user.get('name') or 'C')[:1].upper())
                    with ui.column().classes('gap-1 min-w-0 flex-1'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.label(f"{t('Welcome')}, {user.get('name') or t('Citizen')}").classes(
                                'text-xl font-black text-slate-900 fantasy-title')
                            render_account_status_badge(user)
                        ui.label(
                            f"{len(active_cases)} {t('Active Cases')} · {unread} {t('Unread')}"
                        ).classes('text-xs font-semibold text-slate-600')

            with ui.grid().classes('w-full gap-3 grid-cols-2 sm:grid-cols-3 lg:grid-cols-6'):
                tiles = [
                    ('File an FIR', 'add_circle', '/citizen/submit', None),
                    ('My Complaints', 'report_problem', '/citizen/complaints', len(complaints)),
                    ('FIR Tracking', 'track_changes', '/citizen/tracking', len(firs)),
                    ('Chat with Officer', 'chat', '/citizen/chat', None),
                    ('Notifications', 'notifications', '/citizen/notifications', unread),
                    ('My Profile', 'person', '/citizen/profile', None),
                ]
                for label, icon_name, path, count in tiles:
                    with ui.card().classes(
                        'w-full cursor-pointer items-center gap-1.5 p-4 text-center rounded-2xl '
                        'bg-white border border-slate-200 shadow-sm hover:border-emerald-500 transition-colors'
                    ).on('click', lambda destination=path: ui.navigate.to(destination)):
                        ui.icon(icon_name, size='md').classes('text-emerald-700')
                        ui.label(label).classes('text-xs font-bold text-slate-800 leading-tight')
                        if count:
                            ui.badge(str(count)).classes(
                                'bg-emerald-100 text-emerald-900 text-[10px] font-bold px-2 py-0.5 rounded-full')

            with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-sm'):
                with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                    ui.icon('folder_shared', size='sm').classes('text-emerald-700')
                    ui.label('Active Cases').classes('text-base font-bold text-slate-900 fantasy-title')

                if not active_cases:
                    never_filed = not complaints and not firs
                    with ui.column().classes('w-full items-center gap-2 py-10 text-center'):
                        ui.icon('inbox' if never_filed else 'task_alt', size='lg').classes('text-slate-300')
                        ui.label('No complaints or FIRs yet' if never_filed else 'No active cases').classes(
                            'text-sm font-bold text-slate-700')
                        ui.label(
                            'File an FIR and its verification, assignment and investigation stages will appear here.'
                            if never_filed else
                            'Your recent cases are closed. Open My Complaints for the full history.'
                        ).classes('text-xs text-slate-500 max-w-md leading-relaxed')
                        if never_filed:
                            ui.button(
                                'File an FIR', icon='add_circle',
                                on_click=lambda: ui.navigate.to('/citizen/submit')
                            ).props('unelevated no-caps').classes(
                                'mt-1 bg-emerald-700 hover:bg-emerald-800 text-white rounded-xl px-5 py-2 text-xs font-bold')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for row in active_cases[:5]:
                            with ui.row().classes(
                                'w-full items-center justify-between flex-wrap gap-3 p-3 rounded-xl '
                                'border border-slate-200 bg-slate-50/60'):
                                with ui.column().classes('gap-0.5 flex-1 min-w-48'):
                                    with ui.row().classes('items-center gap-2 flex-wrap'):
                                        ui.label(row['reference']).classes(
                                            'font-black text-slate-900 font-mono text-sm')
                                        complaint_badge(row.get('status'))
                                    ui.label(row.get('title') or '').classes('text-xs font-bold text-slate-700 mt-1')
                                    ui.label(
                                        f"{row.get('station') or '—'} · "
                                        f"{t('Updated')} {fmt_timestamp(row.get('updated_at'), False)}"
                                    ).classes('text-[10px] text-slate-500')
                                ui.button(
                                    'View Details', icon='visibility',
                                    on_click=lambda url=row['detail_url']: ui.navigate.to(url)
                                ).props('flat dense no-caps size=sm').classes('text-emerald-700 font-bold text-xs')

            with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-sm'):
                with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-100 mb-3'):
                    ui.icon('history', size='sm').classes('text-emerald-700')
                    ui.label('Recent Activity').classes('text-base font-bold text-slate-900 fantasy-title')

                if not notifications:
                    with ui.column().classes('w-full items-center gap-2 py-10 text-center'):
                        ui.icon('history_toggle_off', size='lg').classes('text-slate-300')
                        ui.label('No activity yet.').classes('text-sm font-bold text-slate-700')
                        ui.label(
                            'Updates about your complaints and FIRs will appear here.'
                        ).classes('text-xs text-slate-500 max-w-md leading-relaxed')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for notif in notifications:
                            is_read = notif.get('is_read', 0) == 1
                            with ui.row().classes(
                                f'w-full items-center gap-3 p-3 rounded-xl border '
                                f'{"bg-slate-50 border-slate-200" if is_read else "bg-amber-50/70 border-amber-200"}'):
                                ui.icon(
                                    _notification_icon(notif.get('severity'), notif.get('type')), size='xs'
                                ).classes('text-emerald-700 shrink-0')
                                with ui.column().classes('gap-0 flex-1 min-w-0'):
                                    ui.label(notif.get('title') or 'Notification').classes(
                                        'text-xs font-bold text-slate-900 truncate')
                                    ui.label(str(notif.get('message') or '')).classes(
                                        'text-[11px] text-slate-600 line-clamp-1')
                                ui.label(fmt_timestamp(notif.get('created_at'))[5:16]).classes(
                                    'text-[10px] text-slate-400 font-mono shrink-0')

        dashboard_content()

        # Push refresh on real complaint/notification events, plus a slow safety poll.
        queue = subscribe()

        async def listen_for_updates() -> None:
            while True:
                event = await queue.get()
                event_type = event.get('type')
                if event_type not in ('COMPLAINT_UPDATED', 'NOTIFICATION_CREATED', 'NOTIFICATION_UPDATED', 'CITIZEN_APPLICATION_UPDATED', 'CASE_STAGE_UPDATED', 'FIR_UPDATED'):
                    continue
                owner = event.get('citizen_id') or event.get('user_id')
                if owner and owner != user_id:
                    continue
                with client:
                    dashboard_content.refresh()

        listener = background_tasks.create(listen_for_updates(), name='citizen-dashboard-events')

        def stop_listener() -> None:
            unsubscribe(queue)
            listener.cancel()

        client.on_disconnect(stop_listener)
        ui.timer(15.0, dashboard_content.refresh)


# ==========================================
# 2. FILE AN FIR — 5-STEP GUIDED WIZARD (COMPLAINT FIRST)
# ==========================================
@ui.page('/citizen/submit')
def citizen_fir_submission_page() -> None:
    """Guided 5-step filing. Creates a complaint reference; the FIR number is
    issued only after authorized police verification and registration."""
    user = require_citizen_user()
    if not user:
        return

    application = get_application_by_citizen(user.get('id', '')) or {}
    staging_token = create_staging_token()
    preview_data: Dict[str, str] = {}
    submitting = {'active': False, 'done': False}

    form = {
        'name': application.get('full_name') or user.get('name') or '',
        'phone': application.get('mobile') or user.get('phone') or '',
        'email': application.get('email') or user.get('email') or '',
        'address': application.get('address') or user.get('address') or '',
        'category': None,
        'incident_date': datetime.now().strftime('%Y-%m-%d'),
        'incident_time': datetime.now().strftime('%H:%M'),
        'location': '',
        'landmark': '',
        'area': '',
        'district': application.get('district') or user.get('district') or '',
        'state': application.get('state') or '',
        'police_station': None,
        'description': '',
        'geo': '',
    }

    with portal_page(
        'citizen',
        '/citizen/submit',
        'File an FIR',
        'Complete the guided form. Your complaint is recorded securely and verified before an official FIR number is issued.',
    ):
        success_container = ui.column().classes('w-full max-w-4xl mx-auto')
        wizard_card = ui.card().classes('w-full max-w-4xl mx-auto p-6 md:p-8 rounded-3xl bg-white border border-slate-200 shadow-md')

        with wizard_card:
            with ui.stepper().classes('w-full') as stepper:
                # ── Step 1: Applicant information (verified profile) ──
                with ui.step('Applicant', icon='person'):
                    ui.label('Step 1 — Applicant Information').classes('text-xl font-bold text-slate-900 fantasy-title')
                    ui.label('These details come from your verified citizen profile and are not requested again.').classes('text-xs text-slate-600 mb-4')

                    with ui.card().classes('w-full p-3 bg-emerald-50 border border-emerald-200 rounded-xl'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('verified', size='xs').classes('text-emerald-700')
                            ui.label('Verified Citizen Profile').classes('text-xs font-bold text-emerald-900')

                    with ui.column().classes('w-full gap-4 mt-3'):
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            ui.input('Full Name', value=form['name']).props('outlined readonly').classes('flex-1 min-w-56')
                            ui.input('Mobile Number', value=form['phone']).props('outlined readonly').classes('flex-1 min-w-56')
                        ui.input('Email Address', value=form['email']).props('outlined readonly').classes('w-full')
                        ui.textarea('Residential Address', value=form['address']).props('outlined readonly').classes('w-full')

                    with ui.stepper_navigation():
                        ui.button('Next: Incident Details', on_click=stepper.next).props('unelevated no-caps').classes('bg-emerald-700 text-white rounded-xl px-6 py-2.5 font-bold text-xs')

                # ── Step 2: Incident information ──
                with ui.step('Incident', icon='event_note'):
                    ui.label('Step 2 — Incident Information').classes('text-xl font-bold text-slate-900 fantasy-title')
                    ui.label('Provide the incident category, date, approximate time and location.').classes('text-xs text-slate-600 mb-4')

                    with ui.column().classes('w-full gap-4'):
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            category = ui.select(COMPLAINT_CATEGORIES, label='Incident Category *', value=form['category']).props('outlined').classes('flex-1 min-w-56')
                            incident_date = ui.input('Date of Incident *', value=form['incident_date']).props('outlined type=date').classes('flex-1 min-w-40')
                            incident_time = ui.input('Approximate Time', value=form['incident_time']).props('outlined type=time').classes('flex-1 min-w-40')
                        location = ui.input('Incident Location *', value=form['location'], placeholder='Street, building or nearest address').props('outlined').classes('w-full')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            district = ui.input('District *', value=form['district']).props('outlined').classes('flex-1 min-w-40')
                            state = ui.input('State *', value=form['state']).props('outlined').classes('flex-1 min-w-40')
                        description = ui.textarea(
                            'Detailed Description *',
                            value=form['description'],
                            placeholder='Describe the sequence of events, what was lost or damaged, and any identifying details.',
                        ).props('outlined rows=5').classes('w-full')

                    with ui.stepper_navigation():
                        ui.button('Next: Police Station', on_click=stepper.next).props('unelevated no-caps').classes('bg-emerald-700 text-white rounded-xl px-6 py-2.5 font-bold text-xs')
                        ui.button('Back', on_click=stepper.previous).props('flat no-caps').classes('text-slate-600 font-semibold text-xs')

                # ── Step 3: Nearby police station & location details ──
                with ui.step('Station', icon='local_police'):
                    ui.label('Step 3 — Police Station & Location').classes('text-xl font-bold text-slate-900 fantasy-title')
                    ui.label('Choose the station responsible for the incident area and add nearby landmark details.').classes('text-xs text-slate-600 mb-4')

                    with ui.column().classes('w-full gap-4'):
                        station = ui.select(POLICE_STATION_OPTIONS, label='Nearby Police Station *', value=form['police_station']).props('outlined').classes('w-full')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            landmark = ui.input('Nearby Landmark', value=form['landmark'], placeholder='E.g., opposite city mall').props('outlined').classes('flex-1 min-w-44')
                            area = ui.input('Area / Locality', value=form['area'], placeholder='E.g., Ward 12').props('outlined').classes('flex-1 min-w-44')
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            station_district = ui.input('District', value=form['district']).props('outlined').classes('flex-1 min-w-40')
                            station_state = ui.input('State', value=form['state']).props('outlined').classes('flex-1 min-w-40')

                        with ui.card().classes('w-full p-4 bg-slate-50 border border-slate-200 rounded-xl'):
                            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                                with ui.column().classes('gap-0'):
                                    ui.label('Optional precise location').classes('text-xs font-bold text-slate-800')
                                    ui.label('Allow browser location access only if you want to attach GPS coordinates.').classes('text-[11px] text-slate-500')
                                geo_label = ui.label(form['geo'] or 'No GPS coordinates attached').classes('text-[11px] font-mono text-slate-600')
                                geo_button = ui.button('Use My Location', icon='my_location').props('outline no-caps').classes('text-emerald-800 font-bold rounded-xl text-xs')

                    async def use_geolocation() -> None:
                        geo_button.disable()
                        try:
                            coords = await ui.run_javascript("""
                                return await new Promise((resolve) => {
                                    if (!navigator.geolocation) { resolve(null); return; }
                                    navigator.geolocation.getCurrentPosition(
                                        (p) => resolve({lat: p.coords.latitude, lng: p.coords.longitude}),
                                        () => resolve(null),
                                        {timeout: 10000}
                                    );
                                });
                            """, timeout=15)
                        except Exception:
                            coords = None
                        finally:
                            geo_button.enable()
                        if not coords:
                            ui.notify('Location permission was not granted. You can continue with manual address entry.', type='warning')
                            return
                        form['geo'] = f"{float(coords['lat']):.5f}, {float(coords['lng']):.5f}"
                        geo_label.set_text(f"GPS: {form['geo']}")

                    geo_button.on('click', use_geolocation)

                    with ui.stepper_navigation():
                        ui.button('Next: Evidence', on_click=stepper.next).props('unelevated no-caps').classes('bg-emerald-700 text-white rounded-xl px-6 py-2.5 font-bold text-xs')
                        ui.button('Back', on_click=stepper.previous).props('flat no-caps').classes('text-slate-600 font-semibold text-xs')

                # ── Step 4: Evidence upload (private storage) ──
                with ui.step('Evidence', icon='attach_file'):
                    ui.label('Step 4 — Supporting Evidence').classes('text-xl font-bold text-slate-900 fantasy-title')
                    ui.label('Images, PDF or documents. Files are validated and stored in private, authenticated storage.').classes('text-xs text-slate-600 mb-4')

                    allowed_text = ', '.join(sorted(ext.lstrip('.').upper() for ext in ALLOWED_EXTENSIONS))
                    error_label = ui.label('').classes('text-xs font-bold text-rose-700 mb-2')
                    error_label.set_visibility(False)

                    def show_error(message: str) -> None:
                        error_label.set_text(message)
                        error_label.set_visibility(True)

                    def clear_error() -> None:
                        error_label.set_visibility(False)

                    def remove_file(stored_name: str) -> None:
                        try:
                            remove_staged_file(staging_token, stored_name)
                            preview_data.pop(stored_name, None)
                        except Exception as exc:
                            show_error(f'Could not remove file: {exc}')
                            return
                        clear_error()
                        render_staged_files.refresh()

                    @ui.refreshable
                    def render_staged_files() -> None:
                        items = list_staged_files(staging_token)
                        if not items:
                            ui.label('No evidence files attached yet.').classes('text-xs text-slate-500 italic')
                            return
                        for item in items:
                            stored_name = item.get('stored_name', '')
                            with ui.row().classes('w-full items-center gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200'):
                                if stored_name in preview_data:
                                    ui.image(preview_data[stored_name]).classes('w-14 h-14 rounded-lg object-cover border border-slate-200')
                                else:
                                    with ui.element('div').classes('w-14 h-14 rounded-lg bg-white border border-slate-200 flex items-center justify-center'):
                                        ui.icon('description', size='sm').classes('text-slate-500')
                                with ui.column().classes('gap-0 flex-1 min-w-0'):
                                    ui.label(item.get('name') or 'evidence').classes('text-xs font-bold text-slate-800 truncate')
                                    ui.label(fmt_size(item.get('size'))).classes('text-[10px] text-slate-500')
                                ui.button(icon='delete', on_click=lambda name=stored_name: remove_file(name)).props('flat round dense').classes('text-rose-600')

                    async def handle_upload(event) -> None:
                        clear_error()
                        try:
                            content = await event.file.read()
                            item = save_staged_file(
                                staging_token,
                                event.file.name,
                                content,
                                getattr(event.file, 'content_type', '') or '',
                            )
                        except Exception as exc:
                            show_error(str(exc))
                            ui.notify(str(exc), type='negative')
                            return
                        extension = os.path.splitext(item.get('name', ''))[1].lower()
                        if extension in ('.png', '.jpg', '.jpeg'):
                            preview_data[item['stored_name']] = (
                                'data:image/' + ('png' if extension == '.png' else 'jpeg') + ';base64,'
                                + base64.b64encode(content).decode('ascii')
                            )
                        render_staged_files.refresh()
                        ui.notify(f"{item.get('name')} attached.", type='positive')

                    def handle_rejected(event) -> None:
                        show_error(f'File rejected: {getattr(event, "reason", "") or "unsupported file"}')

                    ui.upload(
                        label=f'Attach evidence (up to {MAX_FILES} files, max {MAX_FILE_BYTES // (1024 * 1024)} MB each)',
                        multiple=True,
                        max_files=MAX_FILES,
                        max_file_size=MAX_FILE_BYTES,
                        auto_upload=True,
                        on_upload=handle_upload,
                        on_rejected=handle_rejected,
                    ).props('flat bordered').classes('w-full')
                    ui.label(f'Permitted formats: {allowed_text}').classes('text-[10px] text-slate-500 mt-1')
                    ui.label('You may continue without evidence and provide it to the investigating officer later.').classes('text-[10px] text-slate-400 mt-1')
                    file_list = ui.column().classes('w-full gap-2 mt-3')
                    with file_list:
                        render_staged_files()

                    def advance_from_evidence() -> None:
                        sync_form()
                        render_review()
                        stepper.next()

                    with ui.stepper_navigation():
                        ui.button('Next: Review & Submit', on_click=advance_from_evidence).props('unelevated no-caps').classes('bg-emerald-700 text-white rounded-xl px-6 py-2.5 font-bold text-xs')
                        ui.button('Back', on_click=stepper.previous).props('flat no-caps').classes('text-slate-600 font-semibold text-xs')

                # ── Step 5: Review and submit ──
                with ui.step('Review', icon='fact_check'):
                    ui.label('Step 5 — Review and Submit').classes('text-xl font-bold text-slate-900 fantasy-title')
                    ui.label('Check the details carefully. You will receive a complaint reference; the FIR number is issued after verification.').classes('text-xs text-slate-600 mb-4')

                    review_container = ui.column().classes('w-full')

                    def render_review() -> None:
                        review_container.clear()
                        with review_container:
                            with ui.card().classes('w-full p-5 rounded-2xl bg-slate-50 border border-slate-200'):
                                rows = [
                                    ('Applicant', form['name'] or '—'),
                                    ('Mobile', form['phone'] or '—'),
                                    ('Category', form['category'] or '—'),
                                    ('Incident Date / Time', f"{form['incident_date'] or '—'} {form['incident_time'] or ''}".strip()),
                                    ('Police Station', form['police_station'] or '—'),
                                    ('Incident Location', form['location'] or '—'),
                                    ('Landmark / Area', ', '.join(part for part in (form['landmark'], form['area']) if part) or '—'),
                                    ('District / State', ', '.join(part for part in (form['district'], form['state']) if part) or '—'),
                                    ('Description', form['description'] or '—'),
                                ]
                                for label, value in rows:
                                    with ui.row().classes('w-full justify-between items-start gap-4 py-2 border-b border-slate-200/70 last:border-0'):
                                        ui.label(label).classes('text-[11px] font-bold text-slate-500 uppercase tracking-wide w-44 shrink-0')
                                        ui.label(str(value)).classes('text-xs font-semibold text-slate-900 flex-1 break-words')
                            attached = list_staged_files(staging_token)
                            ui.label(f"{len(attached)} evidence file(s) attached").classes('text-xs font-bold text-slate-600 mt-3')
                            for item in attached:
                                with ui.row().classes('w-full items-center gap-2'):
                                    ui.icon('attach_file', size='xs').classes('text-slate-500')
                                    ui.label(f"{item.get('name')} ({fmt_size(item.get('size'))})").classes('text-[11px] text-slate-700')

                    declaration = ui.checkbox(
                        'I declare that the information provided is true and correct to the best of my knowledge.'
                    ).classes('text-xs font-semibold text-slate-700 mt-4')
                    submit_button = ui.button('Submit Complaint', icon='send').props('unelevated no-caps').classes('bg-emerald-700 hover:bg-emerald-800 text-white rounded-xl px-8 py-3 font-bold text-sm shadow-md mt-3')

                    def sync_form() -> None:
                        form['category'] = category.value
                        form['incident_date'] = incident_date.value
                        form['incident_time'] = incident_time.value
                        form['location'] = (location.value or '').strip()
                        form['landmark'] = (landmark.value or '').strip()
                        form['area'] = (area.value or '').strip()
                        form['district'] = (station_district.value or district.value or '').strip()
                        form['state'] = (station_state.value or state.value or '').strip()
                        form['police_station'] = station.value
                        form['description'] = (description.value or '').strip()

                    def go_to_review() -> None:
                        sync_form()
                        render_review()
                        stepper.next()

                    def submit_complaint() -> None:
                        if submitting['active'] or submitting['done']:
                            return
                        sync_form()

                        missing = []
                        if not form['category']:
                            missing.append('incident category')
                        if not form['incident_date']:
                            missing.append('incident date')
                        if not form['location'] and not form['area']:
                            missing.append('incident location')
                        if not form['police_station']:
                            missing.append('police station')
                        if not form['description']:
                            missing.append('detailed description')
                        if missing:
                            ui.notify('Please complete: ' + ', '.join(missing), type='warning')
                            return
                        if not declaration.value:
                            ui.notify('Please confirm the declaration before submitting.', type='warning')
                            return

                        submitting['active'] = True
                        submit_button.disable()
                        submit_button.set_text('Submitting…')

                        location_text = form['location']
                        if form['geo']:
                            location_text = f"{location_text} (GPS: {form['geo']})" if location_text else f"GPS: {form['geo']}"

                        payload = {
                            'applicant_name': form['name'],
                            'category': form['category'],
                            'title': f"{form['category']} — {form['area'] or form['location']}"[:160],
                            'description': form['description'],
                            'location': location_text,
                            'landmark': form['landmark'],
                            'area': form['area'],
                            'district': form['district'],
                            'state': form['state'],
                            'police_station': form['police_station'],
                            'incident_date': form['incident_date'],
                            'incident_time': form['incident_time'],
                        }

                        try:
                            created = create_complaint(user['id'], payload)
                            moved = move_staged_files_to_complaint(staging_token, created['id'])
                            attach_complaint_evidence(created['id'], moved)
                        except Exception as exc:
                            submitting['active'] = False
                            submit_button.enable()
                            submit_button.set_text('Submit Complaint')
                            ui.notify(f'Submission failed: {exc}', type='negative')
                            return

                        submitting['active'] = False
                        submitting['done'] = True
                        submit_button.set_text('Submitted')

                        success_container.clear()
                        with success_container:
                            with ui.card().classes('w-full mt-6 p-8 rounded-3xl bg-emerald-50 border-2 border-emerald-500 items-center text-center'):
                                ui.icon('check_circle', size='xl').classes('text-emerald-600')
                                ui.label('Complaint Submitted Successfully').classes('text-2xl font-black text-emerald-900 fantasy-title mt-2')
                                ui.label('Your complaint is now pending police verification. An official FIR number will be issued only after it is verified and registered.').classes('text-sm text-emerald-800 mt-1 max-w-xl text-center')

                                with ui.row().classes('w-full justify-center gap-4 my-6 flex-wrap'):
                                    with ui.card().classes('p-5 rounded-2xl bg-white border border-emerald-200 text-left min-w-60'):
                                        ui.label('COMPLAINT REFERENCE').classes('text-[10px] font-bold text-slate-500 tracking-wider')
                                        ui.label(created['reference']).classes('text-2xl font-black text-slate-900 font-mono mt-1')
                                    with ui.card().classes('p-5 rounded-2xl bg-white border border-emerald-200 text-left min-w-60'):
                                        ui.label('STATUS').classes('text-[10px] font-bold text-slate-500 tracking-wider')
                                        ui.label(complaint_status_label(created.get('status'))).classes('text-lg font-black text-amber-700 mt-1')

                                with ui.row().classes('justify-center gap-3 flex-wrap'):
                                    ui.button(
                                        'View Complaint Details',
                                        icon='visibility',
                                        on_click=lambda cid=created['id']: ui.navigate.to(f'/citizen/complaint/{cid}'),
                                    ).props('unelevated no-caps').classes('bg-emerald-700 text-white font-bold rounded-xl px-6 py-2.5 text-xs')
                                    ui.button(
                                        'Go to My Complaints',
                                        icon='list',
                                        on_click=lambda: ui.navigate.to('/citizen/complaints'),
                                    ).props('outline no-caps').classes('text-emerald-800 font-bold rounded-xl px-5 py-2.5 text-xs')

                        wizard_card.set_visibility(False)

                    submit_button.on('click', submit_complaint)
                    with ui.stepper_navigation():
                        ui.button('Back', on_click=stepper.previous).props('flat no-caps').classes('text-slate-600 font-semibold text-xs')
                        ui.button('Review Details', icon='fact_check', on_click=go_to_review).props('outline no-caps').classes('text-emerald-800 font-bold rounded-xl px-5 py-2.5 text-xs')

                    render_review()


# ==========================================
# 3. MY COMPLAINTS
# ==========================================
@ui.page('/citizen/complaints')
def citizen_complaints_list_page(active_path: str = '/citizen/complaints') -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')
    client = ui.context.client

    with portal_page(
        'citizen',
        active_path,
        'My Complaints',
        'Every complaint you have filed with the police department, grouped by its current status.',
    ):
        @ui.refreshable
        def complaints_body() -> None:
            complaints = get_complaints_for_citizen(user_id)

            with ui.row().classes('w-full justify-between items-center flex-wrap gap-3'):
                ui.label(f"{len(complaints)} complaint(s) on record").classes('text-sm font-bold text-slate-700')
                ui.button('File an FIR', icon='add_circle', on_click=lambda: ui.navigate.to('/citizen/submit')).props('unelevated no-caps').classes('bg-emerald-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs')

            if not complaints:
                with ui.card().classes('w-full p-12 bg-white border border-slate-200 rounded-3xl shadow-sm items-center text-center'):
                    ui.icon('folder_open', size='xl').classes('text-slate-300')
                    ui.label('You have not filed any complaints yet.').classes('text-base font-bold text-slate-700 mt-2')
                    ui.label('File an FIR to record a complaint with the police department.').classes('text-xs text-slate-500 mt-1')
                    ui.button('File an FIR', icon='add_circle', on_click=lambda: ui.navigate.to('/citizen/submit')).props('unelevated no-caps').classes('mt-4 bg-emerald-700 text-white font-bold rounded-xl px-6 py-2.5 text-xs')
                return

            grouped = {key: [] for key, _, _ in STATUS_GROUPS}
            for complaint in complaints:
                key, _ = complaint_status_group(complaint.get('status'))
                grouped.setdefault(key, []).append(complaint)

            for key, label, _statuses in STATUS_GROUPS:
                items = grouped.get(key) or []
                if not items:
                    continue
                with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-100 mb-4'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('folder', size='sm').classes('text-emerald-700')
                            ui.label(label).classes('text-lg font-bold text-slate-900 fantasy-title')
                        ui.badge(str(len(items))).classes('bg-slate-100 text-slate-700 font-bold text-[10px] px-2 rounded-full')

                    with ui.column().classes('w-full gap-3'):
                        for complaint in items:
                            complaint_id = complaint.get('id')
                            fir_number = complaint.get('fir_number')
                            with ui.card().classes('w-full p-4 bg-slate-50/70 border border-slate-200 rounded-2xl hover:border-emerald-400 transition-colors'):
                                with ui.row().classes('w-full items-start justify-between flex-wrap gap-3'):
                                    with ui.column().classes('gap-1 flex-1 min-w-48'):
                                        with ui.row().classes('items-center gap-2 flex-wrap'):
                                            ui.label(complaint.get('reference') or '—').classes('text-sm font-black text-slate-900 font-mono')
                                            complaint_badge(complaint.get('status'))
                                        ui.label(complaint.get('applicant_name') or '—').classes('text-xs font-bold text-slate-800')
                                        ui.label(f"{complaint.get('category') or 'Complaint'} · Submitted {fmt_timestamp(complaint.get('submitted_at'), False)}").classes('text-[11px] text-slate-600')
                                        ui.label(f"Police Station: {complaint.get('police_station') or '—'}").classes('text-[11px] text-slate-500')
                                        if fir_number:
                                            ui.label(f"Official FIR Number: {fir_number}").classes('text-[11px] font-bold text-emerald-800 font-mono')
                                        else:
                                            ui.label('Official FIR number will be issued after verification.').classes('text-[11px] text-amber-700 italic')
                                    ui.button(
                                        'View Details',
                                        icon='visibility',
                                        on_click=lambda cid=complaint_id: ui.navigate.to(f'/citizen/complaint/{cid}'),
                                    ).props('flat no-caps size=sm').classes('text-emerald-700 font-bold text-xs')

        complaints_body()

        queue = subscribe()

        async def listen_for_updates() -> None:
            while True:
                event = await queue.get()
                if event.get('type') not in ('COMPLAINT_UPDATED', 'CASE_STAGE_UPDATED', 'FIR_UPDATED'):
                    continue
                owner = event.get('citizen_id') or event.get('user_id')
                if owner and owner != user_id:
                    continue
                with client:
                    complaints_body.refresh()

        listener = background_tasks.create(listen_for_updates(), name='citizen-complaints-events')

        def stop_listener() -> None:
            unsubscribe(queue)
            listener.cancel()

        client.on_disconnect(stop_listener)
        ui.timer(15.0, complaints_body.refresh)


@ui.page('/citizen/my-firs')
def citizen_my_firs() -> None:
    """Legacy route retained for old links; opens the live tracking workspace."""
    ui.navigate.to('/citizen/tracking')


# ==========================================
# 4. LIVE FIR TRACKING
# ==========================================
@ui.page('/citizen/tracking')
def citizen_tracking_page() -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')

    with portal_page(
        'citizen',
        '/citizen/tracking',
        'FIR Tracking',
        'Live timelines built from real police status updates on your own records.',
    ):
        firs = get_firs(actor_user={'id': user_id, 'role': 'CITIZEN'})
        complaints = get_complaints_for_citizen(user_id)

        with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-100 mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('track_changes', size='sm').classes('text-emerald-700')
                    ui.label('Registered FIRs').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.badge(f"{len(firs)} FIR(s)").classes('bg-emerald-100 text-emerald-900 font-bold text-[10px] px-2 rounded-full')

            if not firs:
                with ui.column().classes('w-full items-center py-8 gap-2 text-center'):
                    ui.icon('track_changes', size='lg').classes('text-slate-300')
                    ui.label('No registered FIRs yet.').classes('text-sm font-bold text-slate-600')
                    ui.label('An FIR is registered after your complaint is verified by the police department.').classes('text-xs text-slate-400')
            else:
                options = {fir['id']: f"{fir.get('fir_number')} · {fir.get('incident_type') or 'FIR'}" for fir in firs}
                fir_select = ui.select(options, value=firs[0]['id'], label='Select FIR').props('outlined dense').classes('w-full max-w-xl')
                fir_timeline_container = ui.column().classes('w-full mt-4')

                def render_fir_timeline() -> None:
                    fir_timeline_container.clear()
                    with fir_timeline_container:
                        render_live_fir_timeline(fir_select.value, user, is_officer=False)

                fir_select.on_value_change(lambda _: render_fir_timeline())
                render_fir_timeline()

        with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-100 mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('assignment', size='sm').classes('text-blue-700')
                    ui.label('Complaints Awaiting Registration').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.badge(f"{len(complaints)} complaint(s)").classes('bg-blue-100 text-blue-900 font-bold text-[10px] px-2 rounded-full')

            active_complaints = [c for c in complaints if c.get('status') not in ('CLOSED', 'REJECTED')]
            if not active_complaints:
                with ui.column().classes('w-full items-center py-8 gap-2 text-center'):
                    ui.icon('assignment', size='lg').classes('text-slate-300')
                    ui.label('No active complaints to track.').classes('text-sm font-bold text-slate-600')
                    ui.label('File an FIR to see its verification timeline here.').classes('text-xs text-slate-400')
            else:
                options = {c['id']: f"{c.get('reference')} · {c.get('category') or 'Complaint'}" for c in active_complaints}
                complaint_select = ui.select(options, value=active_complaints[0]['id'], label='Select Complaint').props('outlined dense').classes('w-full max-w-xl')
                complaint_timeline_container = ui.column().classes('w-full mt-4')

                def render_complaint_progress() -> None:
                    complaint_timeline_container.clear()
                    complaint = get_complaint_by_id(complaint_select.value, citizen_id=user_id)
                    with complaint_timeline_container:
                        if not complaint:
                            ui.label('Complaint could not be loaded.').classes('text-xs text-rose-600')
                            return
                        if complaint.get('fir_id'):
                            ui.button(
                                f"Open registered FIR {complaint.get('fir_number') or ''}",
                                icon='open_in_new',
                                on_click=lambda fid=complaint['fir_id']: ui.navigate.to(f'/citizen/fir/{fid}'),
                            ).props('flat no-caps size=sm').classes('text-emerald-700 font-bold text-xs mb-2')
                        render_complaint_timeline(get_complaint_stage_progress(complaint))

                complaint_select.on_value_change(lambda _: render_complaint_progress())
                render_complaint_progress()


# ==========================================
# 5. COMPLAINT DETAIL
# ==========================================
@ui.page('/citizen/complaint/{complaint_id}')
def citizen_complaint_detail_page(complaint_id: str) -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')

    complaint = get_complaint_by_id(complaint_id, citizen_id=user_id)
    if not complaint:
        with portal_page('citizen', '/citizen/complaints', 'Access Denied', 'This complaint is not available.'):
            ui.label('Complaint not found or you are not authorized to view it.').classes('text-sm font-bold text-rose-700')
            ui.button('Back to My Complaints', on_click=lambda: ui.navigate.to('/citizen/complaints')).props('flat no-caps').classes('text-emerald-700 font-bold text-xs mt-3')
        return

    officer_name = complaint.get('assigned_officer_name') or complaint.get('officer_name_from_user')
    has_officer = bool(complaint.get('assigned_officer_id'))
    evidence = parse_evidence(complaint.get('evidence_files'))

    with portal_page(
        'citizen',
        '/citizen/complaints',
        f"Complaint {complaint.get('reference')}",
        complaint.get('title') or 'Complaint details and live progress.',
    ):
        ui.button('← Back to My Complaints', icon='arrow_back', on_click=lambda: ui.navigate.to('/citizen/complaints')).props('flat no-caps').classes('text-slate-600 font-bold text-xs')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-start justify-between flex-wrap gap-3 pb-4 border-b border-slate-200'):
                with ui.column().classes('gap-1'):
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        ui.label(complaint.get('reference') or '—').classes('text-2xl font-black text-slate-900 font-mono')
                        complaint_badge(complaint.get('status'))
                    ui.label(complaint.get('title') or '').classes('text-sm font-bold text-slate-700')
                if complaint.get('fir_id'):
                    ui.button(
                        f"View FIR {complaint.get('fir_number') or ''}",
                        icon='description',
                        on_click=lambda fid=complaint['fir_id']: ui.navigate.to(f'/citizen/fir/{fid}'),
                    ).props('unelevated no-caps').classes('bg-emerald-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs')

            details = [
                ('Applicant', complaint.get('applicant_name') or '—'),
                ('Category', complaint.get('category') or '—'),
                ('Incident Date / Time', f"{complaint.get('incident_date') or '—'} {complaint.get('incident_time') or ''}".strip()),
                ('Police Station', complaint.get('police_station') or '—'),
                ('Incident Location', complaint.get('location') or '—'),
                ('Landmark / Area', ', '.join(part for part in (complaint.get('landmark'), complaint.get('area')) if part) or '—'),
                ('District / State', ', '.join(part for part in (complaint.get('district'), complaint.get('state')) if part) or '—'),
                ('Submitted', fmt_timestamp(complaint.get('submitted_at'))),
                ('Last Updated', fmt_timestamp(complaint.get('updated_at'))),
                ('Official FIR Number', complaint.get('fir_number') or 'Not issued yet — complaint is pending verification'),
            ]
            with ui.column().classes('w-full gap-0 mt-3'):
                for label, value in details:
                    with ui.row().classes('w-full items-start justify-between gap-4 py-2.5 border-b border-slate-100 last:border-0'):
                        ui.label(label).classes('text-[11px] font-bold text-slate-500 uppercase tracking-wide w-44 shrink-0')
                        ui.label(str(value)).classes('text-xs font-semibold text-slate-900 flex-1 break-words')

            ui.label('Detailed Description').classes('text-xs font-bold text-slate-500 uppercase tracking-wide mt-4')
            ui.label(complaint.get('description') or '—').classes('text-xs text-slate-800 leading-relaxed mt-1 whitespace-pre-line')

            if complaint.get('status') == 'ADDITIONAL_INFO_REQUIRED':
                with ui.card().classes('w-full p-4 mt-4 bg-orange-50 border border-orange-300 rounded-xl'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('contact_support', size='xs').classes('text-orange-700')
                        ui.label('Additional information required').classes('text-xs font-bold text-orange-900')
                    ui.label('The police department needs more information about this complaint. Please contact the assigned station quoting your complaint reference.').classes('text-[11px] text-orange-900 mt-1')
            if complaint.get('status') == 'REJECTED' and complaint.get('rejection_reason'):
                with ui.card().classes('w-full p-4 mt-4 bg-rose-50 border border-rose-300 rounded-xl'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('error', size='xs').classes('text-rose-700')
                        ui.label('Complaint rejected').classes('text-xs font-bold text-rose-900')
                    ui.label(str(complaint.get('rejection_reason'))).classes('text-[11px] text-rose-900 mt-1')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-3'):
                ui.icon('timeline', size='sm').classes('text-emerald-700')
                ui.label('Complaint Progress').classes('text-lg font-bold text-slate-900 fantasy-title')
            render_complaint_timeline(get_complaint_stage_progress(complaint))

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('attach_file', size='sm').classes('text-emerald-700')
                    ui.label('Supporting Evidence').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.badge(f"{len(evidence)} file(s)").classes('bg-slate-100 text-slate-700 font-bold text-[10px] px-2 rounded-full')
            render_evidence_list(complaint['id'], evidence)

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                with ui.row().classes('items-center gap-3'):
                    with ui.element('div').classes('w-10 h-10 rounded-full bg-blue-50 border border-blue-200 flex items-center justify-center'):
                        ui.icon('local_police', size='sm').classes('text-blue-700')
                    with ui.column().classes('gap-0'):
                        ui.label('Investigating Officer').classes('text-sm font-bold text-slate-900')
                        if has_officer:
                            contact = f"{officer_name} · Badge {complaint.get('officer_badge') or '—'}"
                            if complaint.get('officer_phone') and any(
                                ch.isdigit() for ch in str(complaint['officer_phone'])
                            ):
                                contact += f" · {complaint['officer_phone']}"
                            ui.label(contact).classes('text-[11px] text-slate-500')
                        else:
                            ui.label('Not assigned yet').classes('text-[11px] text-amber-700 font-semibold')
                if has_officer:
                    ui.button(
                        f'Chat with {officer_name}',
                        icon='chat',
                        on_click=lambda cid=complaint['id']: ui.navigate.to(f'/citizen/complaint-chat/{cid}'),
                    ).props('unelevated no-caps').classes('bg-blue-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs')
                else:
                    with ui.row().classes('items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl'):
                        ui.icon('lock', size='xs').classes('text-amber-700')
                        ui.label('Chat will become available after an investigating officer is assigned to your case.').classes('text-[11px] font-semibold text-amber-900')


# ==========================================
# 6. NOTIFICATION CENTER
# ==========================================
@ui.page('/citizen/notifications')
def citizen_notifications_page() -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')
    client = ui.context.client
    sound_state = {'enabled': bool(app.storage.user.get('notification_sound', True))}
    last_seen = {'id': None}

    def play_sound() -> None:
        if not sound_state['enabled']:
            return
        ui.run_javascript("""
            (() => {
                try {
                    const ctx = new (window.AudioContext || window.webkitAudioContext)();
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.value = 880;
                    gain.gain.value = 0.05;
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start();
                    osc.stop(ctx.currentTime + 0.12);
                } catch (e) {}
            })();
        """)

    with portal_page(
        'citizen',
        '/citizen/notifications',
        'Notification Center',
        'Official updates on your complaints, FIRs and officer messages.',
    ):
        @ui.refreshable
        def notifications_body() -> None:
            notifications = get_user_notifications(user_id)
            unread = get_unread_count(user_id)

            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('notifications', size='sm').classes('text-emerald-700')
                    ui.label(f"{len(notifications)} notification(s)").classes('text-sm font-bold text-slate-700')
                    if unread:
                        ui.badge(f"{unread} unread").classes('bg-amber-500 text-slate-950 font-bold text-[10px] px-2 rounded-full')
                with ui.row().classes('items-center gap-3 flex-wrap'):
                    sound_switch = ui.switch('Notification sound', value=sound_state['enabled']).classes('text-xs font-semibold text-slate-600')

                    def toggle_sound(event) -> None:
                        sound_state['enabled'] = bool(event.value)
                        app.storage.user['notification_sound'] = bool(event.value)

                    sound_switch.on_value_change(toggle_sound)
                    if unread:
                        def handle_read_all() -> None:
                            mark_all_read(user_id)
                            ui.notify('All notifications marked as read.', type='positive')
                            notifications_body.refresh()

                        ui.button('Mark All as Read', icon='done_all', on_click=handle_read_all).props('flat no-caps size=sm').classes('text-emerald-800 font-bold text-xs')

            if not notifications:
                with ui.card().classes('w-full p-12 bg-white border border-slate-200 rounded-3xl shadow-sm items-center text-center'):
                    ui.icon('notifications_none', size='xl').classes('text-slate-300')
                    ui.label('No notifications yet.').classes('text-base font-bold text-slate-700 mt-2')
                    ui.label('Notifications appear only when a real event occurs on your complaints or FIRs.').classes('text-xs text-slate-500 mt-1 max-w-md text-center')
                return

            def handle_read(notification_id: str) -> None:
                mark_notification_read(notification_id, user_id)
                notifications_body.refresh()

            with ui.column().classes('w-full gap-2'):
                for notif in notifications:
                    is_read = notif.get('is_read', 0) == 1
                    severity = notif.get('severity', 'INFO')
                    styles = {
                        'SUCCESS': 'bg-emerald-50 border-emerald-200',
                        'WARNING': 'bg-amber-50 border-amber-200',
                        'ALERT': 'bg-rose-50 border-rose-200',
                        'INFO': 'bg-white border-slate-200',
                    }.get(severity, 'bg-white border-slate-200')
                    if is_read:
                        styles = 'bg-slate-50 border-slate-200 opacity-85'
                    with ui.card().classes(f'w-full p-4 rounded-2xl border {styles} shadow-xs'):
                        with ui.row().classes('w-full items-start gap-3'):
                            ui.icon(_notification_icon(severity, notif.get('type')), size='sm').classes('text-emerald-700 mt-0.5')
                            with ui.column().classes('gap-1 flex-1 min-w-0'):
                                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label(notif.get('title') or 'Notification').classes('text-sm font-bold text-slate-900')
                                        if not is_read:
                                            ui.badge('NEW').classes('bg-amber-500 text-slate-950 font-bold text-[9px] px-1.5 py-0.5 rounded')
                                    ui.label(fmt_timestamp(notif.get('created_at'))).classes('text-[10px] text-slate-400 font-mono')
                                ui.label(str(notif.get('message') or '')).classes('text-xs text-slate-700 whitespace-pre-line leading-relaxed')
                                reference = notif.get('fir_number') or notif.get('complaint_reference')
                                if reference:
                                    ui.label(f"Reference: {reference}").classes('text-[10px] font-bold text-slate-500 font-mono')
                            if not is_read:
                                ui.button(icon='mark_email_read', on_click=lambda nid=notif.get('id'): handle_read(nid)).props('flat round dense size=sm').classes('text-emerald-700').tooltip('Mark as read')

        notifications_body()
        # Push events are dropped while a tab is reconnecting, so the inbox also
        # re-reads the stored records periodically and cannot miss an update.
        ui.timer(30.0, notifications_body.refresh)

        existing = get_user_notifications(user_id, limit=1)
        last_seen['id'] = existing[0].get('id') if existing else None
        queue = subscribe()

        async def listen_for_notifications() -> None:
            while True:
                event = await queue.get()
                if event.get('type') != 'NOTIFICATION_CREATED':
                    continue
                if event.get('user_id') != user_id:
                    continue
                notification = event.get('notification') or {}
                if notification.get('id') == last_seen['id']:
                    continue
                last_seen['id'] = notification.get('id')
                with client:
                    notifications_body.refresh()
                    ui.notify(notification.get('title') or 'New notification', type='info')
                    play_sound()

        listener = background_tasks.create(listen_for_notifications(), name='citizen-notification-events')

        def stop_listener() -> None:
            unsubscribe(queue)
            listener.cancel()

        client.on_disconnect(stop_listener)


# ==========================================
# 7. CITIZEN PROFILE
# ==========================================
@ui.page('/citizen/profile')
def citizen_profile_page() -> None:
    user = require_citizen_user()
    if not user:
        return

    application = get_application_by_citizen(user.get('id', '')) or {}
    photo_uri = ''
    photo_file = resolve_secure_file(application.get('photo_path')) if application else None
    if photo_file:
        try:
            with open(photo_file, 'rb') as handle:
                encoded = base64.b64encode(handle.read()).decode('ascii')
            photo_uri = f"data:{media_type_for(photo_file)};base64,{encoded}"
        except OSError:
            photo_uri = ''

    account_status = 'Verified Citizen' if application.get('status') == 'APPROVED' else (
        (user.get('status') or 'ACTIVE').replace('_', ' ').title()
    )

    with portal_page('citizen', '/citizen/profile', 'My Profile', 'Your verified citizen identity and account information.'):
        with ui.column().classes('w-full max-w-4xl mx-auto gap-5'):
            with ui.card().classes('w-full p-6 md:p-8 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-6 flex-wrap pb-6 border-b border-slate-200'):
                    if photo_uri:
                        ui.image(photo_uri).classes('w-24 h-24 rounded-full object-cover border-4 border-emerald-100 shadow')
                    else:
                        with ui.element('div').classes('w-24 h-24 rounded-full flex items-center justify-center bg-emerald-800 text-white font-black text-3xl shadow'):
                            ui.label(str(user.get('name') or 'C')[:1].upper())
                    with ui.column().classes('gap-1 flex-1'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.label(user.get('name') or 'Citizen').classes('text-2xl md:text-3xl font-black text-slate-900 fantasy-title')
                            ui.badge(account_status).classes(
                                'bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-xs px-3 py-1 rounded-full'
                                if account_status == 'Verified Citizen' else
                                'bg-amber-100 text-amber-900 border border-amber-300 font-bold text-xs px-3 py-1 rounded-full'
                            )
                        ui.label(f"Registered on {fmt_timestamp(user.get('created_at') or application.get('submitted_at'), False) or '—'}").classes('text-xs text-slate-500')
                        if application.get('reference'):
                            ui.label(f"Verification reference: {application.get('reference')}").classes('text-[11px] text-slate-500 font-mono')

            with ui.card().classes('w-full p-6 md:p-8 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('person', size='sm').classes('text-emerald-700')
                    ui.label('Personal Information').classes('text-lg font-bold text-slate-900 fantasy-title')

                details = [
                    ('Full Name', application.get('full_name') or user.get('name'), 'person'),
                    ('Username', application.get('username'), 'alternate_email'),
                    ('Email Address', application.get('email') or user.get('email'), 'email'),
                    ('Mobile Number', application.get('mobile') or user.get('phone'), 'phone'),
                    ('Date of Birth', application.get('date_of_birth'), 'cake'),
                    ('Residential Address', application.get('address') or user.get('address'), 'home'),
                    ('District', application.get('district') or user.get('district'), 'location_city'),
                    ('State', application.get('state'), 'map'),
                    ('Account Status', account_status, 'verified_user'),
                ]
                with ui.column().classes('w-full gap-0'):
                    for label, value, icon_name in details:
                        with ui.row().classes('w-full items-center justify-between gap-4 py-3 border-b border-slate-100 last:border-0 flex-wrap'):
                            with ui.row().classes('items-center gap-3'):
                                ui.icon(icon_name, size='xs').classes('text-emerald-700')
                                ui.label(label).classes('text-xs font-bold text-slate-600')
                            ui.label(str(value or '—')).classes('text-xs font-bold text-slate-900 text-right break-words')

            with ui.card().classes('w-full p-5 bg-emerald-50/70 border border-emerald-200 rounded-3xl'):
                with ui.row().classes('items-center gap-2 mb-1'):
                    ui.icon('security', size='sm').classes('text-emerald-800')
                    ui.label('Your data is protected').classes('text-sm font-bold text-emerald-950')
                ui.label('Your verified identity photograph and government ID are stored privately and are never shown to other citizens. Only you and authorized verification officers can access your verification records.').classes('text-xs text-emerald-900 leading-relaxed')


# ==========================================
# 8. REGISTERED FIR — DETAIL & TRACKING
# ==========================================
@ui.page('/citizen/firs')
def citizen_firs_page() -> None:
    user = require_citizen_user()
    if not user:
        return
    firs = get_firs(actor_user={'id': user.get('id'), 'role': 'CITIZEN'})

    with portal_page('citizen', '/citizen/tracking', 'Registered FIRs', 'Official FIRs registered after police verification.'):
        if not firs:
            with ui.card().classes('w-full p-12 bg-white border border-slate-200 rounded-3xl shadow-sm items-center text-center'):
                ui.icon('description', size='xl').classes('text-slate-300')
                ui.label('No registered FIRs yet.').classes('text-sm font-bold text-slate-700 mt-2')
                ui.button('File an FIR', icon='add_circle', on_click=lambda: ui.navigate.to('/citizen/submit')).props('unelevated no-caps').classes('mt-3 bg-emerald-700 text-white rounded-xl px-5 py-2 text-xs font-bold')
            return

        with ui.column().classes('w-full gap-3'):
            for fir in firs:
                with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-xs'):
                    with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                        with ui.column().classes('gap-1'):
                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                ui.label(fir.get('fir_number') or '—').classes('font-black text-slate-900 font-mono text-base')
                                fir_status_badge(fir.get('status', 'SUBMITTED'))
                            ui.label(fir.get('incident_type') or 'FIR').classes('text-xs font-bold text-slate-700')
                            ui.label(f"{fir.get('police_station') or '—'} · {fir.get('incident_date') or ''}").classes('text-[11px] text-slate-500')
                        with ui.row().classes('gap-2'):
                            ui.button('Details', icon='visibility', on_click=lambda fid=fir['id']: ui.navigate.to(f'/citizen/fir/{fid}')).props('flat no-caps size=sm').classes('text-emerald-700 font-bold text-xs')
                            ui.button('Track', icon='track_changes', on_click=lambda fid=fir['id']: ui.navigate.to(f'/citizen/fir/{fid}/track')).props('flat no-caps size=sm').classes('text-blue-700 font-bold text-xs')


@ui.page('/citizen/fir/{fir_id}')
def citizen_fir_detail_page(fir_id: str) -> None:
    user = require_citizen_user()
    if not user:
        return
    user_id = user.get('id', '')
    try:
        fir = get_fir_by_id(fir_id, actor_user=user)
    except PermissionError:
        with portal_page('citizen', '/citizen/complaints', 'Access Denied', 'You are not authorized to view this FIR.'):
            ui.label('Access Denied: This FIR belongs to another citizen.').classes('text-sm font-bold text-rose-700')
            ui.button('Back to Dashboard', on_click=lambda: ui.navigate.to('/citizen')).props('flat no-caps').classes('text-emerald-700 font-bold text-xs mt-3')
        return

    if not fir:
        with portal_page('citizen', '/citizen/complaints', 'FIR Not Found', 'Record could not be located.'):
            ui.label('FIR not found.').classes('text-sm text-slate-600')
            ui.button('Back to Dashboard', on_click=lambda: ui.navigate.to('/citizen')).props('flat no-caps').classes('text-emerald-700 font-bold text-xs mt-3')
        return

    timeline = get_operational_case_timeline(fir_id, actor_user=user)
    status = fir.get('status', 'PENDING_VERIFICATION')
    is_verified = status != 'PENDING_VERIFICATION'
    has_officer = bool(fir.get('assigned_officer_id'))
    chat_available = is_verified and has_officer

    with portal_page(
        'citizen',
        '/citizen/tracking',
        f"FIR {fir.get('fir_number')}",
        f"Tracking reference: {fir.get('reference_number')}",
    ):
        ui.button('← Back to FIR Tracking', icon='arrow_back', on_click=lambda: ui.navigate.to('/citizen/tracking')).props('flat no-caps').classes('text-slate-600 font-bold text-xs')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 pb-4 border-b border-slate-200'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('description', size='lg').classes('text-emerald-700')
                    with ui.column().classes('gap-0'):
                        ui.label(fir.get('fir_number') or '—').classes('text-2xl md:text-3xl font-black text-slate-900 font-mono')
                        ui.label(f"{fir.get('incident_type') or 'FIR'} · {fir.get('police_station') or '—'}").classes('text-xs text-slate-600')
                with ui.row().classes('items-center gap-2 flex-wrap'):
                    fir_status_badge(status)
                    ui.badge('VERIFIED' if is_verified else 'PENDING VERIFICATION').classes(
                        'bg-sky-100 text-sky-900 border border-sky-300 font-bold text-[10px] px-2 rounded-full'
                        if is_verified else
                        'bg-amber-100 text-amber-900 border border-amber-300 font-bold text-[10px] px-2 rounded-full'
                    )

            with ui.row().classes('w-full mt-4 flex-wrap gap-6 text-xs text-slate-700'):
                for label, value in [
                    ('Incident Date & Time', f"{fir.get('incident_date') or '—'} {fir.get('incident_time') or ''}".strip()),
                    ('Location', fir.get('incident_location') or '—'),
                    ('Police Station', fir.get('police_station') or '—'),
                    ('Assigned Officer', f"{fir.get('officer_name')} ({fir.get('officer_rank') or 'Officer'})" if has_officer else 'Pending assignment'),
                ]:
                    with ui.column().classes('min-w-40 gap-1'):
                        ui.label(label).classes('font-bold text-slate-500 uppercase text-[10px]')
                        ui.label(value).classes('font-bold text-slate-900 text-sm')

            with ui.card().classes('w-full mt-4 p-4 rounded-xl bg-slate-50 border border-slate-200'):
                ui.label('Incident Description').classes('text-xs font-bold text-slate-700 mb-1')
                ui.label(fir.get('description') or '—').classes('text-xs text-slate-800 leading-relaxed whitespace-pre-line')

        fir_document = get_current_document(fir_id)
        if fir_document:
            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('picture_as_pdf', size='md').classes('text-rose-700')
                        with ui.column().classes('gap-0'):
                            ui.label('Official FIR Document').classes('text-lg font-bold text-slate-900 fantasy-title')
                            ui.label(
                                f"Version {fir_document.get('version') or 1} · Generated "
                                f"{str(fir_document.get('generated_at') or '')[:19].replace('T', ' ')} UTC"
                            ).classes('text-[11px] text-slate-500')
                    ui.button(
                        'Download FIR PDF',
                        icon='download',
                        on_click=lambda fid=fir_id: ui.download(f'/api/v1/secure/fir-documents/{fid}'),
                    ).props('unelevated no-caps').classes('bg-emerald-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
                ui.icon('folder_zip', size='sm').classes('text-emerald-700')
                ui.label('Supporting Documents').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.label('Stored privately and shared with your investigating officer').classes('text-[11px] text-slate-500')

            complaint_id = fir.get('complaint_id')

            @ui.refreshable
            def documents_view() -> None:
                complaint_row = get_complaint_by_id(complaint_id, citizen_id=user_id) if complaint_id else None
                files = parse_evidence((complaint_row or {}).get('evidence_files'))
                ui.badge(f"{len(files)} file(s) on record").classes(
                    'bg-slate-100 text-slate-700 font-bold text-[10px] px-2 rounded-full mb-3')
                if not files:
                    ui.label('No documents are attached to this case yet.').classes('text-xs text-slate-500 italic')
                    return
                render_evidence_list(complaint_id, files)

            documents_view()

            if not complaint_id:
                ui.label('This FIR has no complaint record that documents can be attached to.').classes(
                    'text-[11px] text-slate-400 mt-3')
            elif status in ('PENDING_VERIFICATION', 'NEEDS_CORRECTION', 'REJECTED'):
                with ui.row().classes('w-full items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl mt-3'):
                    ui.icon('lock', size='xs').classes('text-amber-700')
                    ui.label('You can add documents once your FIR is registered by the police department.').classes(
                        'text-[11px] font-semibold text-amber-900')
            else:
                ui.separator().classes('my-4')
                ui.label('Add a document for the investigating officer').classes(
                    'text-[11px] font-black text-slate-700 uppercase mb-2')
                document_caption = ui.input(
                    'What does this document show? (optional)',
                    placeholder='E.g. Medical certificate dated 4 November',
                ).props('outlined dense').classes('w-full mb-3')

                async def upload_supporting_document(event) -> None:
                    upload = event.file
                    content = await upload.read()
                    try:
                        add_citizen_evidence(
                            fir_id, user, upload.name, content,
                            getattr(upload, 'content_type', None) or getattr(upload, 'type', None) or '',
                            document_caption.value or '',
                        )
                    except (ValueError, PermissionError) as exc:
                        ui.notify(str(exc), type='warning')
                        return
                    except Exception as exc:
                        ui.notify(f'Could not store the document: {exc}', type='negative')
                        return
                    document_caption.value = ''
                    ui.notify('Document sent to your investigating officer.', type='positive')
                    documents_view.refresh()

                ui.upload(
                    label=f'Choose a file (max {MAX_FILE_BYTES // (1024 * 1024)} MB)',
                    auto_upload=True, max_files=1, max_file_size=MAX_FILE_BYTES,
                    on_upload=upload_supporting_document,
                ).props('flat bordered').classes('w-full')
                ui.label('Permitted formats: ' + ' '.join(sorted(ALLOWED_EXTENSIONS))).classes(
                    'text-[10px] text-slate-400 mt-1')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('chat', size='md').classes('text-blue-700')
                    with ui.column().classes('gap-0'):
                        ui.label('Chat with Assigned Officer').classes('text-lg font-bold text-slate-900 fantasy-title')
                        ui.label('Secure direct messaging about this FIR').classes('text-xs text-slate-500')
                if chat_available:
                    ui.button(
                        f"Chat with {fir.get('officer_name') or 'Officer'}",
                        icon='chat',
                        on_click=lambda: ui.navigate.to(f'/citizen/chat/{fir_id}'),
                    ).props('unelevated no-caps').classes('bg-blue-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs')
                else:
                    with ui.row().classes('items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-xl'):
                        ui.icon('lock', size='xs').classes('text-amber-700')
                        ui.label('Chat will become available after an investigating officer is assigned to your case.').classes('text-[11px] font-semibold text-amber-900')

        with ui.element('div').classes('w-full'):
            render_live_fir_timeline(fir_id, user, is_officer=False)

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-3'):
                ui.icon('timeline', size='sm').classes('text-emerald-700')
                ui.label('Case Status Progression').classes('text-lg font-bold text-slate-900 fantasy-title')
            if not timeline:
                ui.label('Case activity will appear here as your FIR progresses.').classes('text-xs text-slate-500')
            else:
                for event in timeline:
                    color_map = {
                        'emerald': ('bg-emerald-600 text-white', 'border-emerald-200 bg-emerald-50/60'),
                        'amber': ('bg-amber-500 text-white', 'border-amber-200 bg-amber-50/60'),
                        'blue': ('bg-blue-700 text-white', 'border-blue-200 bg-blue-50/60'),
                        'indigo': ('bg-indigo-700 text-white', 'border-indigo-200 bg-indigo-50/60'),
                        'red': ('bg-rose-600 text-white', 'border-rose-200 bg-rose-50/60'),
                    }
                    dot_cls, card_cls = color_map.get(event.get('color', 'emerald'), color_map['emerald'])
                    with ui.row().classes('w-full items-start gap-4 mb-3'):
                        with ui.element('div').classes(f'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center shadow-sm {dot_cls}'):
                            ui.icon(event.get('icon', 'info'), size='xs')
                        with ui.card().classes(f'flex-1 p-4 rounded-2xl border {card_cls} shadow-xs'):
                            with ui.row().classes('w-full justify-between items-start flex-wrap gap-1'):
                                ui.label(event.get('title', '')).classes('font-bold text-slate-900 text-sm flex-1')
                                ui.label(str(event.get('timestamp', ''))).classes('text-[10px] text-slate-500 font-mono shrink-0')
                            ui.label(event.get('description', '')).classes('text-xs text-slate-700 mt-1 leading-relaxed')


@ui.page('/citizen/fir/{fir_id}/track')
def citizen_fir_track_page(fir_id: str) -> None:
    user = require_citizen_user()
    if not user:
        return
    try:
        fir = get_fir_by_id(fir_id, actor_user=user)
    except PermissionError:
        ui.notify('Access Denied: You do not have permission to view this FIR record.', type='negative')
        ui.navigate.to('/citizen')
        return

    if not fir:
        ui.notify('FIR not found.', type='negative')
        ui.navigate.to('/citizen')
        return

    with portal_page(
        'citizen',
        '/citizen/tracking',
        f"Live Tracking: {fir.get('fir_number')}",
        f"Reference: {fir.get('reference_number')} · Status: {(fir.get('status') or '').replace('_', ' ').title()}",
    ):
        ui.button('← Back to Dashboard', icon='arrow_back', on_click=lambda: ui.navigate.to('/citizen')).props('flat no-caps').classes('text-slate-600 font-bold text-xs')
        render_live_fir_timeline(fir_id, user, is_officer=False)

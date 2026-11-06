"""
Administrator / Supervisor Portal - System Overview, Officer Management, Blockchain Explorer, and Audit Logs.
"""

import base64
import json
from typing import Any, Dict, List, Optional
from nicegui import background_tasks, ui

from frontend.components.badges import fir_status_badge, integrity_badge
from frontend.components.layout import portal_page
from backend.services.audit_service import get_audit_dashboard_stats, get_all_audit_events, get_audit_event_detail, get_audit_events_for_fir
from backend.services.auth_service import (
    get_all_citizens,
    get_all_officers,
    get_all_police_officers,
    get_current_user,
    get_user_by_id,
    set_current_user,
    update_officer_verification_status,
    update_staff_profile,
)
from backend.services.complaint_service import get_all_complaints, get_complaints_for_citizen, get_complaint_by_id
from backend.services.citizen_registration_service import get_application_by_citizen
from backend.services.complaint_verification_service import action_label as vo_action_label
from backend.services.fir_document_service import read_document_bytes
from data.integrity import get_hash_chain_status
from backend.services.authorized_officer_service import (
    get_complete_fir_case_history,
    get_citizen_complete_dossier,
)
from backend.services.complaint_evidence_service import evidence_bytes
from backend.services.blockchain_service import (
    get_blockchain_ledger,
    verify_fir_integrity,
    get_fir_blockchain_details,
)
from backend.services.db import get_db_connection
from backend.services.fir_service import assign_officer_to_fir, get_firs, get_fir_by_id, get_fir_versions, get_fir_changes
from backend.services.case_tracking_service import get_case_stage_progress, get_fir_complete_tracking, update_case_stage, CASE_STAGES, STAGE_LABELS, normalize_stage
from backend.services.investigation_service import (
    ACTION_LABELS,
    OFFICER_STAGES,
    OFFICER_STAGE_LABELS,
    compute_case_stats,
    get_admin_case_detail,
    get_admin_investigation_overview,
    get_admin_officer_record,
    get_evidence_file,
    send_officer_instruction,
)
from backend.services.notification_service import (
    get_unread_count,
    get_user_notifications,
    mark_all_read,
    mark_notification_read,
)
from backend.services.realtime_events import subscribe, unsubscribe
from frontend.components.case_tracking_timeline import render_live_fir_timeline

def require_admin_user():
    """Ensure active user is a verified Administrator / Supervisor."""
    user = get_current_user() or {}
    if not user or user.get("role") != "ADMIN":
        ui.navigate.to('/staff-portal')
        return None
    return user


@ui.page('/admin')
def admin_dashboard() -> None:
    """Administrator / Supervisor Master Dashboard."""
    user = require_admin_user()
    if not user:
        return
    all_firs = get_firs(actor_user=user)
    all_officers = get_all_officers()
    all_citizens = get_all_citizens()
    all_complaints = get_all_complaints(actor_user=user)
    ledger = get_blockchain_ledger(limit=10)

    # Enhanced stat breakdown
    tampered_count = len([f for f in all_firs if f.get("integrity_status") == "TAMPER_DETECTED"])
    pending_verif = len([f for f in all_firs if f.get("status") == "PENDING_VERIFICATION"])
    verified = len([f for f in all_firs if f.get("status") == "VERIFIED"])
    under_invest = len([f for f in all_firs if f.get("status") == "UNDER_INVESTIGATION"])
    chargesheet = len([f for f in all_firs if f.get("status") == "CHARGESHEET_FILED"])
    closed = len([f for f in all_firs if f.get("status") in ("RESOLVED", "CLOSED")])
    new_complaints = len([c for c in all_complaints if c.get("status") == "SUBMITTED"])

    with portal_page('admin', '/admin', 'Main Officer Command Centre', 'State-wide FIR monitoring, citizen records, officer management, and blockchain audit integrity.'):
        
        # Admin Banner
        with ui.card().classes('w-full p-6 paper-card mb-4 border-l-4 border-amber-600 bg-white rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                with ui.row().classes('items-center gap-4'):
                    with ui.element('div').classes('w-14 h-14 rounded-full flex items-center justify-center bg-gradient-to-br from-amber-600 to-orange-800 text-white shadow-md'):
                        ui.icon('admin_panel_settings', size='md')
                    with ui.column().classes('gap-0.5'):
                        ui.label(f"{user.get('rank') or 'Administrator'} {user.get('name', 'Administrator')}").classes('text-2xl md:text-3xl font-black text-slate-900 fantasy-title')
                        ui.label('Main Officer · Headquarters Oversight · Cyber Forensics & Legal Accountability Wing').classes('text-xs text-slate-600')

                with ui.row().classes('items-center gap-2 flex-wrap'):
                    ui.button('FIR Management 📋', icon='description', on_click=lambda: ui.navigate.to('/admin/fir-management')).props('unelevated').classes('bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-2xl px-4 py-2 text-xs shadow-md')
                    ui.button('Citizen Records 👥', icon='groups', on_click=lambda: ui.navigate.to('/admin/citizens')).props('unelevated').classes('bg-emerald-700 hover:bg-emerald-800 text-white font-bold rounded-2xl px-4 py-2 text-xs shadow-md')
                    ui.button('Blockchain Ledger 🔗', icon='toll', on_click=lambda: ui.navigate.to('/admin/blockchain')).props('unelevated').classes('bg-slate-900 hover:bg-slate-800 text-white font-bold rounded-2xl px-4 py-2 text-xs shadow-md')

        # ── Enhanced Stat Cards ──────────────────────────────────────
        with ui.row().classes('w-full flex-wrap gap-3 mb-4'):
            cards_data = [
                ('Total FIRs', len(all_firs), 'description', '#1E40AF', 'bg-blue-50 border-blue-200'),
                ('New Complaints', new_complaints, 'inbox', '#D97706', 'bg-amber-50 border-amber-200'),
                ('Pending Verification', pending_verif, 'pending_actions', '#DC6803', 'bg-orange-50 border-orange-200'),
                ('Verified', verified, 'verified', '#059669', 'bg-emerald-50 border-emerald-200'),
                ('Under Investigation', under_invest, 'manage_search', '#7C3AED', 'bg-purple-50 border-purple-200'),
                ('Chargesheet Filed', chargesheet, 'gavel', '#0369A1', 'bg-sky-50 border-sky-200'),
                ('Closed / Resolved', closed, 'task_alt', '#374151', 'bg-slate-50 border-slate-200'),
                ('Integrity Alerts', tampered_count, 'gpp_bad', '#DC2626', 'bg-red-50 border-red-200'),
            ]
            for title, val, icon_name, color, bg_cls in cards_data:
                with ui.card().classes(f'min-w-32 flex-1 p-4 rounded-2xl border shadow-sm {bg_cls}'):
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.icon(icon_name, size='md').style(f'color: {color}')
                        ui.label(str(val)).classes('text-2xl font-black text-slate-900')
                    ui.label(title).classes('text-xs font-bold text-slate-700 mt-2')

        # FIR Tampering Alerts card
        try:
            audit_stats = get_audit_dashboard_stats(user)
            with ui.card().classes('w-full p-6 rounded-2xl border-2 border-red-200 bg-red-50 shadow-sm cursor-pointer hover:shadow-md transition-all').on('click', lambda: ui.navigate.to('/admin/tampering-audit')):
                with ui.row().classes('w-full items-center justify-between mb-3'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('policy', size='md').classes('text-red-700')
                        ui.label('FIR TAMPERING ALERTS').classes('text-sm font-black text-red-900 tracking-wider uppercase')
                    ui.badge('ADMIN ONLY').classes('bg-red-700 text-white font-bold text-[10px]')
                with ui.row().classes('w-full gap-6 flex-wrap mt-2'):
                    for label, val, color in [
                        ('Total Audit Events', audit_stats['total_events'], 'text-slate-900'),
                        ('Last 24h Changes', audit_stats['recent_24h'], 'text-red-700'),
                        ('Officers Active', audit_stats['officers_count'], 'text-blue-700'),
                    ]:
                        with ui.column().classes('gap-0'):
                            ui.label(str(val)).classes(f'text-2xl font-black {color}')
                            ui.label(label).classes('text-xs text-slate-600 font-medium')
                ui.label('Click to open FIR Tampering & Audit Trail →').classes('text-xs text-red-600 font-bold mt-3')
        except Exception:
            pass

        # Quick Links & System Health Grid
        with ui.row().classes('w-full flex-wrap gap-6 mb-6'):
            with ui.card().classes('min-w-80 flex-1 p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                ui.label('Administrative Functions').classes('text-lg font-bold text-slate-900 fantasy-title mb-3')
                for label, icon, path in [
                    ('📋 FIR Management & Monitoring', 'description', '/admin/fir-management'),
                    ('👥 Citizen Records & FIR Search', 'groups', '/admin/citizens'),
                    ('🔗 Blockchain Hash Verification', 'toll', '/admin/blockchain'),
                    ('⚙️ Case Officer Assignments', 'assignment_ind', '/admin/assignments'),
                    ('🔒 Authorized Officer Portal (Integrity)', 'shield_lock', '/authorized-officer/dashboard'),
                    ('📖 Officer Audit / Complete Change History', 'history', '/audit/officer-changes'),
                    ('🔍 FIR Version Comparison & Hash Check', 'compare', '/authorized-officer/comparison'),
                    ('📊 Complete Audit Logs & Activity', 'fact_check', '/admin/audit-logs'),
                    ('🚨 FIR Tampering & Audit Trail', 'policy', '/admin/tampering-audit'),
                    ('🎖️ Police Officer Verification', 'badge', '/admin/officers'),
                ]:
                    ui.button(label, icon=icon, on_click=lambda dest=path: ui.navigate.to(dest)).props('flat align=left').classes(
                        'w-full justify-start text-slate-800 font-bold py-2.5 hover:bg-slate-100 rounded-xl text-xs my-0.5'
                    )

            with ui.card().classes('min-w-80 flex-1 p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                ui.label('System & Cryptographic Status').classes('text-lg font-bold text-slate-900 fantasy-title mb-3')
                with ui.column().classes('w-full gap-2 text-xs'):
                    for label, val, cls in [
                        ('Database Engine:', 'SQLite with Relational Version Control', 'font-bold text-emerald-800'),
                        ('Blockchain Consensus:', 'Permissioned Cryptographic PoA Ledger', 'font-bold text-blue-800'),
                        ('Validator Node:', 'NODE-IN-KA-POLICE-01 (Active)', 'font-mono font-bold text-slate-900'),
                        ('State Hashing:', 'SHA-256 Canonical JSON', 'font-mono font-bold text-purple-800'),
                        ('Registered Officers:', str(len(all_officers)), 'font-bold text-teal-800'),
                        ('Total Blockchain Blocks:', str(len(ledger)), 'font-bold text-amber-800'),
                    ]:
                        with ui.row().classes('items-center justify-between p-2 rounded-xl bg-slate-50'):
                            ui.label(label).classes('font-bold text-slate-600')
                            ui.label(val).classes(cls)


# ==========================================
# 2. POLICE OFFICER VERIFICATION
# ==========================================

OFFICER_STATUS_STYLES = {
    'ACTIVE': ('VERIFIED & ACTIVE', 'bg-emerald-100 text-emerald-900 border-emerald-300'),
    'PENDING_VERIFICATION': ('PENDING VERIFICATION', 'bg-amber-100 text-amber-900 border-amber-300'),
    'SUSPENDED': ('SUSPENDED', 'bg-rose-100 text-rose-900 border-rose-300'),
}

OFFICER_DECISIONS = {
    'ACTIVE': ('Verify & Activate', 'verified_user', 'bg-emerald-700 hover:bg-emerald-800'),
    'SUSPENDED': ('Suspend Account', 'block', 'bg-rose-700 hover:bg-rose-800'),
    'PENDING_VERIFICATION': ('Return to Pending', 'hourglass_top', 'bg-amber-600 hover:bg-amber-700'),
}


def _officer_status_badge(status) -> None:
    label, classes = OFFICER_STATUS_STYLES.get(
        str(status or '').upper(), ('NOT REVIEWED', 'bg-slate-100 text-slate-700 border-slate-300'))
    ui.badge(label).classes(f'border font-bold text-[10px] px-2 py-0.5 rounded-full {classes}')


def _officer_decision_dialog(officer: Dict[str, Any], new_status: str, user: Dict[str, Any], on_done) -> None:
    label, _, _ = OFFICER_DECISIONS[new_status]
    with ui.dialog() as dlg, ui.card().classes('w-full max-w-lg p-5 bg-white rounded-3xl shadow-2xl'):
        ui.label(f"{label} — {officer.get('name')}").classes('text-base font-black text-slate-900')
        ui.label(
            f"Badge {officer.get('badge_number') or 'not issued'} · current status "
            f"{officer.get('status') or 'not reviewed'}. The decision is written to the audit trail "
            'and the officer is notified.'
        ).classes('text-[11px] text-slate-500 mb-3')
        remarks = ui.textarea(
            'Reason / remarks (optional)',
            placeholder='Recorded against this decision in the officer audit history.',
        ).props('outlined dense autogrow').classes('w-full text-sm')

        def apply() -> None:
            try:
                update_officer_verification_status(officer['id'], new_status, user, remarks.value)
            except (PermissionError, ValueError) as exc:
                ui.notify(str(exc), type='negative')
                return
            dlg.close()
            ui.notify(f"{officer.get('name')} is now {new_status.replace('_', ' ')}.", type='positive')
            on_done()

        with ui.row().classes('w-full justify-end gap-2 mt-4'):
            ui.button('Cancel', on_click=dlg.close).props('flat no-caps size=sm').classes('text-slate-500 font-bold')
            ui.button(f'Confirm {label}', icon='gavel', on_click=apply).props(
                'unelevated no-caps size=sm').classes('bg-indigo-800 text-white font-bold rounded-xl text-xs')
    dlg.open()


def _officer_detail(record: Dict[str, Any], user: Dict[str, Any], on_decide) -> None:
    officer = record['officer']
    stats = record['stats']
    performance = record['performance']

    with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
        with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 pb-3 border-b border-slate-100'):
            with ui.column().classes('gap-1'):
                ui.label(officer.get('name') or 'Unnamed officer').classes('text-xl font-black text-slate-900 fantasy-title')
                ui.label(
                    f"{officer.get('rank') or 'Rank not recorded'} · "
                    f"{officer.get('station') or 'Station not recorded'}"
                ).classes('text-[11px] text-slate-600')
            with ui.row().classes('items-center gap-2 flex-wrap'):
                _officer_status_badge(officer.get('status'))
                ui.badge(f"{stats['total']} case(s) on file").classes(
                    'bg-indigo-100 text-indigo-900 font-bold text-[10px] px-2 rounded-full')

        with ui.row().classes('w-full flex-wrap gap-4 mt-4'):
            _mon_detail('Badge / Officer ID', officer.get('badge_number'), mono=True)
            _mon_detail('Staff Username', officer.get('username'), mono=True)
            _mon_detail('Rank', officer.get('rank'))
            _mon_detail('Police Station', officer.get('station'))
            _mon_detail('District', officer.get('district'))
            _mon_detail('Email Address', officer.get('email'), mono=True)
            _mon_detail('Contact Number', officer.get('phone'), mono=True)
            _mon_detail('Postal Address', officer.get('address'))
        with ui.row().classes('w-full flex-wrap gap-4 mt-3 pt-3 border-t border-slate-100'):
            _mon_detail('Verification Status', officer.get('verification_status'))
            _mon_detail('Identity Verified On', _mon_fmt(officer.get('verified_at')), mono=True)
            _mon_detail('Account Provisioned', _mon_fmt(officer.get('created_at')), mono=True)
            _mon_detail('Last Account Update', _mon_fmt(officer.get('updated_at')), mono=True)
            _mon_detail('Active Cases', officer.get('active_cases_count'))
            _mon_detail('Total Assignments', officer.get('total_assignments_count'))

        with ui.row().classes('w-full items-center gap-2 flex-wrap mt-4 pt-3 border-t border-slate-100'):
            ui.label('Account decision:').classes('text-[11px] font-black text-slate-600 uppercase tracking-wider')
            current = str(officer.get('status') or '').upper()
            for status, (label, icon, colour) in OFFICER_DECISIONS.items():
                if status == current:
                    continue
                ui.button(
                    label, icon=icon,
                    on_click=lambda oid=officer['id'], st=status: on_decide(oid, st),
                ).props('unelevated no-caps size=sm').classes(f'{colour} text-white font-bold rounded-xl text-xs')
            if current in OFFICER_DECISIONS:
                ui.label(f"Already {OFFICER_STATUS_STYLES[current][0].lower()}.").classes('text-[10px] text-slate-400')

    with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
        with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100'):
            ui.icon('assignment_ind', size='sm').classes('text-indigo-800')
            ui.label('Assigned FIR Cases').classes('text-sm font-black text-slate-900')
            ui.badge(
                f"{stats['total']} assigned · {stats['closed']} closed · {stats['under_investigation']} under investigation"
            ).classes('bg-slate-100 text-slate-700 font-bold text-[10px] px-2 rounded-full')
        ui.label(
            f"Cases completed: {performance['completed_count']} of {performance['assigned_count']} assigned · "
            f"investigation credits {performance['total_credits']} ({performance['level']})"
        ).classes('text-[10px] text-slate-500 mt-2')

        if not record['cases']:
            ui.label('No FIR has been assigned to this officer yet.').classes('text-[11px] text-slate-500 py-4')
        with ui.column().classes('w-full gap-2 mt-3'):
            for case in record['cases']:
                stage_class = ADMIN_STAGE_COLOURS.get(
                    case.get('current_stage'), 'bg-slate-100 text-slate-600 border-slate-200')
                with ui.card().classes('w-full p-3 rounded-2xl border border-slate-200 bg-slate-50/60 gap-1'):
                    with ui.row().classes('w-full items-start justify-between flex-wrap gap-2'):
                        with ui.column().classes('gap-1 flex-1 min-w-56'):
                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                _mon_identity(case.get('fir_number'), case.get('citizen_name'),
                                              case.get('complaint_reference'))
                                fir_status_badge(case.get('status'))
                            ui.badge(case.get('stage_label') or 'Awaiting tracking').classes(
                                f'border font-bold text-[10px] px-2 py-0.5 rounded-full self-start {stage_class}')
                            ui.label(
                                f"{case.get('incident_type') or '—'} · {case.get('police_station') or '—'} · "
                                f"assigned {_mon_fmt(case.get('assigned_at'))} · last update {_mon_fmt(case.get('last_update_at'))}"
                            ).classes('text-[10px] text-slate-500')
                        ui.button(
                            'Open Case', icon='monitoring',
                            on_click=lambda fid=case['id']: ui.navigate.to(f'/admin/investigations/{fid}'),
                        ).props('unelevated no-caps size=sm').classes(
                            'bg-indigo-800 text-white font-bold rounded-xl text-xs')

        if record['assignments']:
            ui.label('Assignment trail').classes('text-[11px] font-black text-slate-700 mt-4 mb-1')
            with ui.column().classes('w-full gap-1'):
                for entry in record['assignments']:
                    with ui.row().classes('w-full items-center gap-2 flex-wrap text-[10px]'):
                        ui.badge(entry.get('status') or 'ACTIVE').classes(
                            'bg-slate-200 text-slate-700 font-bold px-2 rounded-full')
                        ui.label(
                            f"{entry.get('fir_number') or '—'} · Citizen {entry.get('citizen_name') or 'not recorded'} · "
                            f"assigned by {entry.get('assigned_by_name') or 'not recorded'} on {_mon_fmt(entry.get('assigned_at'))}"
                        ).classes('text-slate-600')

    with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-3xl shadow-sm'):
        with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100'):
            ui.icon('fact_check', size='sm').classes('text-indigo-800')
            ui.label('Verification & Account Decision History').classes('text-sm font-black text-slate-900')
        if not record['decisions']:
            ui.label(
                'No Authorized Officer decision has been recorded for this account yet.'
            ).classes('text-[11px] text-slate-500 py-3')
        with ui.column().classes('w-full gap-2 mt-3'):
            for decision in record['decisions']:
                with ui.card().classes('w-full p-3 rounded-2xl border border-slate-200 bg-slate-50/60 gap-1'):
                    ui.label(
                        f"{_mon_fmt(decision.get('timestamp'))} · "
                        f"{decision.get('decided_by_name') or decision.get('user_email') or 'Authorized Officer'}"
                        f" ({decision.get('role') or 'ADMIN'}"
                        f"{', badge ' + decision['decided_by_badge'] if decision.get('decided_by_badge') else ''})"
                    ).classes('text-[11px] font-black text-slate-800')
                    ui.label(decision.get('details') or '—').classes('text-[10px] text-slate-600')


@ui.page('/admin/officers')
def admin_officers_page() -> None:
    """Review police officer accounts, decide their status, and open the cases they hold."""
    user = require_admin_user()
    if not user:
        return

    state = {'query': '', 'status': 'ALL', 'officer_id': None}

    def select(officer_id: str) -> None:
        state['officer_id'] = officer_id
        directory.refresh()

    def decide(officer_id: str, new_status: str) -> None:
        officers = {o['id']: o for o in get_all_police_officers()}
        officer = officers.get(officer_id)
        if not officer:
            ui.notify('That officer account no longer exists.', type='negative')
            directory.refresh()
            return
        _officer_decision_dialog(officer, new_status, user, directory.refresh)

    @ui.refreshable
    def directory() -> None:
        everyone = get_all_police_officers()
        query = state['query'].strip().lower()
        visible = everyone
        if query:
            visible = [
                o for o in visible
                if query in ' '.join(str(o.get(k) or '') for k in (
                    'name', 'badge_number', 'rank', 'station', 'district', 'email', 'username')).lower()
            ]
        if state['status'] != 'ALL':
            visible = [o for o in visible if str(o.get('status') or '').upper() == state['status']]

        def count(status: str) -> int:
            return sum(1 for o in everyone if str(o.get('status') or '').upper() == status)

        with ui.row().classes('w-full flex-wrap gap-3'):
            cards_data = [
                ('Police Officer Accounts', len(everyone), 'badge', '#1E40AF', 'bg-blue-50/80 border-blue-200'),
                ('Verified & Active', count('ACTIVE'), 'verified_user', '#059669', 'bg-emerald-50/80 border-emerald-200'),
                ('Pending Verification', count('PENDING_VERIFICATION'), 'hourglass_top', '#D97706', 'bg-amber-50/80 border-amber-200'),
                ('Suspended', count('SUSPENDED'), 'block', '#DC2626', 'bg-rose-50/80 border-rose-200'),
                ('Active Cases Held', sum(int(o.get('active_cases_count') or 0) for o in everyone),
                 'assignment_ind', '#6D28D9', 'bg-purple-50/80 border-purple-200'),
            ]
            for label, value, icon_name, colour, background in cards_data:
                with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border shadow-xs {background} gap-1'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.icon(icon_name, size='md').style(f'color: {colour}')
                        ui.label(str(value)).classes('text-3xl font-black text-slate-900')
                    ui.label(label).classes('text-[11px] font-bold text-slate-700 leading-tight')

        with ui.row().classes('w-full items-start gap-4 flex-wrap'):
            with ui.card().classes('w-full md:w-2/5 min-w-72 p-4 bg-white border border-slate-200 rounded-3xl shadow-sm gap-2'):
                with ui.row().classes('w-full items-center justify-between pb-2 border-b border-slate-100'):
                    ui.label(f"Officer Directory ({len(visible)})").classes('text-sm font-black text-slate-900')
                    with ui.row().classes('items-center gap-1'):
                        ui.icon('bolt', size='xs').classes('text-emerald-600')
                        ui.label('Live').classes('text-[10px] text-slate-500')

                if not everyone:
                    with ui.column().classes('w-full items-center py-8 gap-2 text-center'):
                        ui.icon('badge', size='lg').classes('text-slate-300')
                        ui.label('No police officer accounts provisioned yet.').classes('text-xs font-bold text-slate-700')
                        ui.label('Accounts appear here as soon as they are created.').classes('text-[10px] text-slate-500')
                elif not visible:
                    ui.label('No officer matches this search or status filter.').classes(
                        'text-[11px] text-slate-500 py-6 text-center w-full')

                with ui.column().classes('w-full gap-2 mt-2'):
                    for officer in visible:
                        selected = officer['id'] == state['officer_id']
                        with ui.card().classes(
                            'w-full p-3 rounded-2xl border gap-1 '
                            + ('border-indigo-400 bg-indigo-50/70' if selected else 'border-slate-200 bg-slate-50/60')
                        ):
                            ui.button(
                                f"{officer.get('name') or 'Unnamed officer'} · {officer.get('badge_number') or 'no badge'}",
                                on_click=lambda oid=officer['id']: select(oid),
                            ).props('flat align=left no-caps').classes(
                                'w-full justify-start text-slate-900 font-black text-xs px-0')
                            ui.label(
                                f"{officer.get('rank') or 'Rank not recorded'} · {officer.get('station') or 'Station not recorded'}"
                            ).classes('text-[10px] text-slate-600')
                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                _officer_status_badge(officer.get('status'))
                                ui.label(
                                    f"{officer.get('active_cases_count') or 0} active · "
                                    f"{officer.get('total_assignments_count') or 0} assigned"
                                ).classes('text-[10px] text-slate-500')

            with ui.column().classes('flex-1 min-w-80 gap-4'):
                if state['officer_id'] not in {o['id'] for o in everyone}:
                    state['officer_id'] = visible[0]['id'] if visible else (everyone[0]['id'] if everyone else None)
                if not state['officer_id']:
                    with ui.card().classes('w-full p-8 bg-white border border-slate-200 rounded-3xl shadow-sm items-center gap-2'):
                        ui.icon('person_search', size='lg').classes('text-slate-300')
                        ui.label('Select an officer to review their account.').classes('text-xs font-bold text-slate-600')
                else:
                    _officer_detail(get_admin_officer_record(state['officer_id'], user), user, decide)

    with portal_page(
        'admin', '/admin/officers', 'Police Officer Verification',
        'Review officer identities and credentials, verify or suspend accounts, and open the FIR cases each officer holds.',
    ):
        with ui.card().classes('w-full p-4 bg-white border border-slate-200 rounded-2xl shadow-sm'):
            with ui.row().classes('w-full items-center gap-3 flex-wrap'):
                search = ui.input(
                    placeholder='Search by officer name, badge, rank, station, district or email…',
                ).props('outlined dense clearable').classes('flex-1 min-w-64 text-sm')

                def on_search(event) -> None:
                    state['query'] = event.value or ''
                    directory.refresh()

                search.on_value_change(on_search)
                status_filter = ui.select(
                    {'ALL': 'All accounts', 'ACTIVE': 'Verified & active',
                     'PENDING_VERIFICATION': 'Pending verification', 'SUSPENDED': 'Suspended'},
                    value='ALL', label='Account status',
                ).props('outlined dense').classes('min-w-48 text-xs')

                def on_status(event) -> None:
                    state['status'] = event.value or 'ALL'
                    directory.refresh()

                status_filter.on_value_change(on_status)
                ui.button('Refresh', icon='refresh', on_click=directory.refresh).props(
                    'outline no-caps size=sm').classes('text-indigo-800 font-bold')

        directory()
        _mon_listen(directory)
        ui.timer(30, directory.refresh)


# ==========================================
# 3. BLOCKCHAIN LEDGER EXPLORER
# ==========================================
@ui.page('/admin/blockchain')
def admin_blockchain_page() -> None:
    """Blockchain Block & Transaction Explorer."""
    if not require_admin_user():
        return
    ledger = get_blockchain_ledger(limit=50)

    with portal_page('admin', '/admin/blockchain', 'Blockchain Ledger Explorer', 'Inspect cryptographically sealed blocks, Merkle roots, and transaction proofs.'):
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('toll', size='md').classes('text-amber-600')
                    ui.label(f"Mined Blocks & Transaction Ledger ({len(ledger)})").classes('text-xl font-bold text-slate-900 fantasy-title')

                ui.badge('Permissioned Proof-of-Authority Ledger').classes('bg-blue-100 text-blue-900 font-bold text-xs')

            with ui.element('div').classes('w-full overflow-x-auto'):
                with ui.element('table').classes('w-full text-left text-xs border-collapse font-mono'):
                    with ui.element('thead').classes('bg-slate-900 text-amber-300 font-sans'):
                        with ui.element('tr'):
                            for col in ['Block #', 'Tx ID', 'Method', 'FIR ID / Version', 'Block Hash', 'Transaction Hash']:
                                ui.element('th').classes('p-3 font-bold').text = col

                    with ui.element('tbody').classes('divide-y divide-slate-200 bg-white'):
                        for b in ledger:
                            with ui.element('tr').classes('hover:bg-slate-50'):
                                with ui.element('td').classes('p-3 font-bold text-amber-700'):
                                    ui.label(f"#{b.get('block_index')}")
                                with ui.element('td').classes('p-3 text-slate-800 font-bold'):
                                    ui.label(str(b.get('tx_id', 'GENESIS')))
                                with ui.element('td').classes('p-3 font-sans font-bold text-blue-800'):
                                    ui.label(str(b.get('contract_method', 'genesisInit')))
                                with ui.element('td').classes('p-3 text-slate-700'):
                                    fir_id = b.get('fir_id')
                                    ver = b.get('version')
                                    if fir_id:
                                        ui.label(f"{fir_id} (v{ver})")
                                    else:
                                        ui.label('—')
                                with ui.element('td').classes('p-3 text-[11px] text-slate-600'):
                                    ui.label(f"{b.get('block_hash', '')[:18]}...")
                                with ui.element('td').classes('p-3 text-[11px] text-emerald-800 font-bold'):
                                    tx_h = b.get('tx_hash')
                                    ui.label(f"{tx_h[:18]}..." if tx_h else '—')


# ==========================================
# 4. CASE ASSIGNMENTS WORKBENCH
# ==========================================
@ui.page('/admin/assignments')
def admin_assignments_page() -> None:
    """Assign or reassign investigating officers to FIRs."""
    user = require_admin_user()
    if not user:
        return
    all_firs = get_firs(actor_user=user)
    all_officers = get_all_officers()

    with portal_page('admin', '/admin/assignments', 'FIR Case Assignments', 'Assign lead investigating officers to incoming citizen FIRs.'):
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
            ui.label('Assign Officers to Open FIRs').classes('text-xl font-bold text-slate-900 fantasy-title mb-4')

            with ui.column().classes('w-full gap-4'):
                for fir in all_firs:
                    fir_id = fir["id"]
                    with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-slate-50/60 shadow-xs'):
                        with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
                            with ui.column().classes('gap-0.5 flex-1 min-w-64'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.label(fir.get('fir_number')).classes('text-base font-black text-slate-900 font-mono')
                                    fir_status_badge(fir.get('status'))
                                ui.label(f"Category: {fir.get('incident_type')} · Location: {fir.get('incident_location')}").classes('text-xs text-slate-600')
                                ui.label(f"Complainant: {fir.get('citizen_name')} ({fir.get('citizen_phone')})").classes('text-xs text-slate-500')

                            with ui.row().classes('items-center gap-3'):
                                officer_options = {o["id"]: f"{o.get('rank') or 'Officer'} {o['name']} ({o.get('badge_number') or 'N/A'})" for o in all_officers}
                                current_off_id = fir.get("assigned_officer_id")
                                if current_off_id not in officer_options:
                                    current_off_id = None
                                off_sel = ui.select(officer_options, value=current_off_id, label='Assigned Officer').classes('min-w-64 text-xs')

                                def handle_assign(f_id=fir_id, sel=off_sel):
                                    success = assign_officer_to_fir(f_id, sel.value, user)
                                    if success:
                                        ui.notify('Officer assignment updated & notifications dispatched!', type='positive')
                                        ui.navigate.to('/admin/assignments')
                                    else:
                                        ui.notify('Failed to assign officer.', type='negative')

                                ui.button('Update Officer', icon='how_to_reg', on_click=handle_assign).props('unelevated size=sm').classes(
                                    'bg-blue-800 text-white rounded-xl px-4 py-2 font-bold text-xs'
                                )


# ==========================================
# 4. MAIN OFFICER FIR MANAGEMENT & TRACKING
# ==========================================

@ui.page('/admin/fir-cases')
@ui.page('/admin/fir-management')
@ui.page('/admin/fir-monitor')
def admin_fir_management_page(fir_id: Optional[str] = None) -> None:
    """
    Main Officer Centralized FIR Management, Real-Time Case Tracking,
    and Cryptographic SHA-256 Blockchain Verification.
    """
    user = require_admin_user()
    if not user:
        return

    # Keep track of active state
    state = {
        'selected_fir_id': fir_id,
        'search_query': '',
        'status_filter': 'ALL'
    }

    with portal_page('admin', '/admin/fir-management', 'Main Officer FIR Management & Tracking', 'Real-time case progression, authorized stage updates, and cryptographic blockchain hashing proofs.'):
        
        # Top Action & Stats Bar
        with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4 flex-wrap gap-3'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('assignment_turned_in', size='md').classes('text-blue-800')
                with ui.column().classes('gap-0'):
                    ui.label('Centralized Case Tracking & Blockchain Verification').classes('text-xl font-black text-slate-900 fantasy-title')
                    ui.label('Search citizens and FIRs, execute authorized stage transitions, and inspect cryptographic proofs.').classes('text-xs text-slate-500')

            with ui.row().classes('items-center gap-2'):
                ui.button('View Citizen Directory 👥', icon='groups', on_click=lambda: ui.navigate.to('/admin/citizens')).props('unelevated outline size=sm').classes('text-slate-700 font-bold rounded-xl text-xs')
                ui.button('Full Blockchain Explorer 🔗', icon='toll', on_click=lambda: ui.navigate.to('/admin/blockchain')).props('unelevated outline size=sm').classes('text-slate-700 font-bold rounded-xl text-xs')

        # Main Layout
        list_container = ui.column().classes('w-full gap-3')
        detail_container = ui.column().classes('w-full gap-6')

        def render_detail_view():
            detail_container.clear()
            cur_fir_id = state['selected_fir_id']
            if not cur_fir_id:
                with detail_container:
                    with ui.card().classes('w-full p-12 text-center bg-slate-50 border-2 border-dashed border-slate-300 rounded-3xl'):
                        ui.icon('touch_app', size='xl').classes('text-slate-400 mb-2')
                        ui.label('Select an FIR from the list to inspect live tracking and cryptographic hashing.').classes('text-base font-bold text-slate-700')
                        ui.label('You can search by citizen name, FIR number, or police station above.').classes('text-xs text-slate-400')
                return

            fir = get_fir_by_id(cur_fir_id, actor_user=user)
            if not fir:
                with detail_container:
                    ui.label(f'FIR with ID {cur_fir_id} not found or access restricted.').classes('text-red-600 font-bold p-4')
                return

            # Fetch blockchain details
            bc_info = get_fir_blockchain_details(cur_fir_id)

            with detail_container:
                # 1. FIR Overview Banner
                with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center justify-between flex-wrap gap-4 pb-4 border-b border-slate-200'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes('w-12 h-12 rounded-2xl flex items-center justify-center bg-blue-50 text-blue-800 border border-blue-200'):
                                ui.icon('policy', size='md')
                            with ui.column().classes('gap-0.5'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label(fir.get('fir_number')).classes('text-2xl font-black text-slate-900 font-mono')
                                    fir_status_badge(fir.get('status'))
                                ui.label(f"Tracking Ref: {fir.get('reference_number')} · Police Station: {fir.get('police_station')}").classes('text-xs text-slate-600')

                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.button(
                                'Complete Case Dossier (15-Point Audit) 📜',
                                icon='history_edu',
                                on_click=lambda fid=cur_fir_id: ui.navigate.to(f'/admin/fir-cases/{fid}/full')
                            ).props('unelevated size=sm').classes('bg-indigo-900 hover:bg-indigo-950 text-white font-bold rounded-xl text-xs px-3 py-1.5 shadow-sm')
                            ui.badge(f"Record Version: v{fir.get('current_version', 1)}").classes('bg-blue-100 text-blue-900 border border-blue-300 font-mono font-bold text-xs px-3 py-1')
                            if bc_info.get('is_valid'):
                                ui.badge('✓ Cryptographically Verified').classes('bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-xs px-3 py-1')
                            else:
                                ui.badge('⚠️ Integrity Alert').classes('bg-red-100 text-red-900 border border-red-300 font-bold text-xs px-3 py-1')

                    # Meta Information Grid
                    with ui.row().classes('w-full flex-wrap gap-6 pt-4 text-xs'):
                        with ui.column().classes('gap-0 min-w-36 flex-1'):
                            ui.label('Complainant Name').classes('text-[10px] font-black text-slate-400 uppercase tracking-wider')
                            if fir.get('citizen_id'):
                                ui.link(
                                    fir.get('citizen_name', 'Citizen'),
                                    f"/admin/citizens/{fir.get('citizen_id')}"
                                ).classes('font-bold text-indigo-800 hover:underline break-words')
                            else:
                                ui.label(fir.get('citizen_name', 'Citizen')).classes('font-bold text-slate-800 break-words')

                        for label, val in [
                            ('Complainant Phone', fir.get('citizen_phone', '—')),
                            ('Complainant Email', fir.get('citizen_email', '—')),
                            ('Assigned Officer', f"{fir.get('officer_name', 'Unassigned')} ({fir.get('officer_badge', 'No Badge')})"),
                            ('Incident Type', fir.get('incident_type', '—')),
                            ('Incident Date & Time', f"{fir.get('incident_date', '—')} {fir.get('incident_time', '')}"),
                            ('Incident Location', fir.get('incident_location', '—')),
                        ]:
                            with ui.column().classes('gap-0 min-w-36 flex-1'):
                                ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-wider')
                                ui.label(str(val or '—')).classes('font-bold text-slate-800 break-words')

                # 2. Live FIR Tracking Timeline & Officer Controls (Connected 10-Stage Progression)
                with ui.column().classes('w-full gap-2'):
                    ui.label('Live FIR Tracking Timeline & Case Progression').classes('text-base font-black text-slate-900 fantasy-title')
                    render_live_fir_timeline(cur_fir_id, actor_user=user, is_officer=True, on_change_callback=lambda: render_detail_view())

                # 3. Dedicated Blockchain Verification & Cryptographic Hashing Details (Main Officer ONLY)
                with ui.card().classes('w-full p-6 paper-card bg-slate-950 text-white border border-slate-800 rounded-3xl shadow-xl'):
                    with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-800 flex-wrap gap-3'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes('w-12 h-12 rounded-2xl flex items-center justify-center bg-indigo-950 text-indigo-400 border border-indigo-700'):
                                ui.icon('toll', size='md')
                            with ui.column().classes('gap-0'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label('Cryptographic SHA-256 Blockchain Verification').classes('text-xl font-black text-white fantasy-title')
                                    ui.badge('MAIN OFFICER CONFIDENTIAL').classes('bg-amber-500/20 text-amber-300 border border-amber-600/40 text-[10px] font-bold')
                                ui.label('Immutable ledger state, cryptographic hashes, and tamper-evident proof records.').classes('text-xs text-slate-400')

                        # Live Verify Button
                        def run_live_integrity_verification():
                            res = verify_fir_integrity(cur_fir_id)
                            if res.get('is_valid'):
                                ui.notify(f"✓ Cryptographic Integrity Verified: {res.get('message')}", type='positive', position='top-right')
                            else:
                                ui.notify(f"⚠️ INTEGRITY ALERT: {res.get('message')}", type='negative', position='top-right')
                            render_detail_view()

                        ui.button('Verify Integrity Now 🔍', icon='verified', on_click=run_live_integrity_verification).props('unelevated').classes('bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl px-4 py-2 text-xs shadow-md')

                    # 12 Required Fields Grid
                    with ui.row().classes('w-full flex-wrap gap-4 mt-4 font-mono text-xs'):
                        # Field 1: Citizen Name
                        with ui.card().classes('flex-1 min-w-56 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            ui.label('1. Citizen Name').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                            ui.label(bc_info.get('citizen_name', 'Citizen')).classes('text-sm font-bold text-white mt-1')

                        # Field 2: FIR Number
                        with ui.card().classes('flex-1 min-w-56 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            ui.label('2. FIR Number').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                            ui.label(bc_info.get('fir_number', '—')).classes('text-sm font-bold text-amber-400 mt-1')

                        # Field 3: FIR ID
                        with ui.card().classes('flex-1 min-w-56 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            ui.label('3. Database FIR ID').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                            ui.label(bc_info.get('fir_id', '—')).classes('text-xs font-bold text-slate-300 mt-1')

                        # Field 4: Record Version
                        with ui.card().classes('flex-1 min-w-36 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            ui.label('4. Record Version').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                            ui.label(f"v{bc_info.get('record_version', 1)}").classes('text-base font-bold text-blue-400 mt-1')

                    # Hashes & Ledger Identifiers
                    with ui.column().classes('w-full gap-3 mt-4'):
                        # Field 5: Generated SHA-256 Hash
                        with ui.card().classes('w-full p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            with ui.row().classes('w-full items-center justify-between'):
                                ui.label('5. Generated SHA-256 Canonical Hash (Live Computed)').classes('text-[10px] font-sans font-black text-emerald-400 uppercase tracking-wider')
                                ui.badge('CANONICAL JSON').classes('bg-emerald-950 text-emerald-400 border border-emerald-800 text-[10px]')
                            ui.label(bc_info.get('generated_sha256_hash', '—')).classes('text-xs font-mono text-emerald-300 break-all mt-1')

                        # Field 6: Database Stored SHA-256 Hash
                        with ui.card().classes('w-full p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                            with ui.row().classes('w-full items-center justify-between'):
                                ui.label('6. Database Stored SHA-256 Hash (Current Hash Column)').classes('text-[10px] font-sans font-black text-cyan-400 uppercase tracking-wider')
                                match_status = 'MATCHES LIVE' if bc_info.get('generated_sha256_hash') == bc_info.get('stored_db_hash') else 'MISMATCH'
                                match_color = 'bg-cyan-950 text-cyan-400 border border-cyan-800' if match_status == 'MATCHES LIVE' else 'bg-red-950 text-red-400 border border-red-800'
                                ui.badge(match_status).classes(f'{match_color} text-[10px]')
                            ui.label(bc_info.get('stored_db_hash', '—')).classes('text-xs font-mono text-cyan-300 break-all mt-1')

                        # Field 7 & 8: Blockchain Block ID & Transaction ID
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            with ui.card().classes('flex-1 min-w-64 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('7. Blockchain Block ID').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                                blk_id = bc_info.get('blockchain_block_id')
                                ui.label(f"Block #{blk_id}" if blk_id is not None else 'Genesis Block #0').classes('text-base font-bold text-amber-300 mt-1')

                            with ui.card().classes('flex-1 min-w-64 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('8. Blockchain Transaction ID').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                                ui.label(bc_info.get('transaction_id', '—')).classes('text-xs font-mono text-purple-300 break-all mt-1')

                        # Field 9 & 10: Previous Block Hash & Current Block Hash
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            with ui.card().classes('flex-1 min-w-72 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('9. Previous Block Hash').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                                ui.label(bc_info.get('previous_block_hash', '—')).classes('text-xs font-mono text-slate-400 break-all mt-1')

                            with ui.card().classes('flex-1 min-w-72 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('10. Current Block Hash').classes('text-[10px] font-sans font-black text-indigo-400 uppercase tracking-wider')
                                ui.label(bc_info.get('current_block_hash', '—')).classes('text-xs font-mono text-indigo-300 break-all mt-1')

                        # Field 11 & 12: Timestamps & Verification Status
                        with ui.row().classes('w-full gap-4 flex-wrap'):
                            with ui.card().classes('flex-1 min-w-64 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('11. Hash Generation Date & Time').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                                gen_ts = str(bc_info.get('hash_generated_at', ''))[:19].replace('T', ' ')
                                ui.label(gen_ts or '—').classes('text-xs font-mono text-slate-300 mt-1')

                            with ui.card().classes('flex-1 min-w-64 p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                                ui.label('12. Last Integrity Verification').classes('text-[10px] font-sans font-black text-slate-400 uppercase tracking-wider')
                                ui.label(bc_info.get('last_verification_at', 'Just now')).classes('text-xs font-mono text-emerald-400 mt-1')

                    # Transactions Log on Chain
                    txs = bc_info.get('transactions', [])
                    if txs:
                        ui.label(f"On-Chain Transition Ledger ({len(txs)} Confirmed Proofs)").classes('text-xs font-sans font-black text-slate-400 uppercase tracking-wider mt-4')
                        with ui.column().classes('w-full gap-2 text-xs font-mono'):
                            for tx in txs:
                                with ui.card().classes('w-full p-3 bg-slate-900/80 border border-slate-800 rounded-xl'):
                                    with ui.row().classes('w-full items-center justify-between'):
                                        ui.label(f"Version v{tx.get('version')} · Block #{tx.get('block_index')} · Tx: {tx.get('tx_id')}").classes('font-bold text-indigo-300')
                                        ui.label(str(tx.get('timestamp'))[:19].replace('T', ' ')).classes('text-[10px] text-slate-500')
                                    with ui.row().classes('w-full items-center gap-2 mt-1'):
                                        ui.label(f"Hash: {str(tx.get('new_hash'))[:24]}...").classes('text-emerald-400')
                                        if tx.get('previous_hash'):
                                            ui.label(f"Prev: {str(tx.get('previous_hash'))[:16]}...").classes('text-slate-500')

                # 4. Modification History & Audit Link
                with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                        ui.label('Internal Administrative Audit Trail').classes('text-base font-black text-slate-900 fantasy-title')
                        ui.button('View Detailed Before & After Differences →', icon='history_edu', on_click=lambda fid=cur_fir_id: ui.navigate.to(f'/admin/fir-audit/{fid}')).props('flat size=xs').classes('text-blue-800 font-bold')

                    evs = get_audit_events_for_fir(cur_fir_id, user)
                    if evs:
                        with ui.column().classes('w-full gap-2'):
                            for ev in evs[:5]:
                                with ui.row().classes('w-full items-center justify-between p-2 rounded-xl bg-slate-50 text-xs'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.icon('edit_note', size='xs').classes('text-blue-700')
                                        ui.label(f"v{ev.get('previous_version')} → v{ev.get('new_version')}: {ev.get('reason', 'Authorized update')}").classes('font-bold text-slate-800')
                                    ui.label(str(ev.get('timestamp'))[:19].replace('T', ' ')).classes('font-mono text-slate-500 text-[10px]')
                    else:
                        ui.label('No modifications have been recorded for this FIR. It remains in initial Version 1.').classes('text-xs text-slate-500 italic')

        def render_list():
            list_container.clear()
            firs = get_firs(
                actor_user=user,
                status_filter=state['status_filter'],
                search_query=state['search_query']
            )

            # Auto-select first if none selected
            if not state['selected_fir_id'] and firs:
                state['selected_fir_id'] = firs[0]['id']

            with list_container:
                # Filter Header
                with ui.card().classes('w-full p-4 paper-card bg-white border border-slate-200 rounded-2xl shadow-sm mb-2'):
                    with ui.row().classes('w-full items-center gap-3 flex-wrap'):
                        # Search input
                        search_inp = ui.input(
                            placeholder='Search Citizen Name, FIR #, Station...',
                            value=state['search_query']
                        ).props('dense outlined').classes('flex-1 min-w-64 text-xs')

                        def on_search(e=None):
                            state['search_query'] = search_inp.value
                            render_list()

                        search_inp.on('keydown.enter', on_search)

                        # Status filter dropdown
                        status_options = {
                            'ALL': 'All Statuses',
                            'SUBMITTED': 'Submitted',
                            'PENDING_VERIFICATION': 'Pending Verification',
                            'VERIFIED': 'Verified',
                            'UNDER_INVESTIGATION': 'Under Investigation',
                            'CHARGESHEET_FILED': 'Chargesheet Filed',
                            'RESOLVED': 'Resolved',
                            'CLOSED': 'Closed'
                        }
                        status_sel = ui.select(
                            options=status_options,
                            value=state['status_filter'],
                            label='Status Filter'
                        ).props('dense outlined').classes('min-w-48 text-xs')

                        def on_status_change(e):
                            state['status_filter'] = status_sel.value
                            render_list()

                        status_sel.on_value_change(on_status_change)
                        ui.button('Search 🔍', on_click=on_search).props('unelevated size=sm').classes('bg-blue-800 text-white font-bold rounded-xl px-4 py-2 text-xs')

                ui.label(f"Displaying {len(firs)} FIR Record(s)").classes('text-xs font-bold text-slate-500 uppercase tracking-wider mb-2')

                if not firs:
                    with ui.card().classes('w-full p-12 text-center bg-white border border-slate-200 rounded-3xl'):
                        ui.icon('description', size='xl').classes('text-slate-300 mb-2')
                        ui.label('No FIR records available.').classes('text-base font-bold text-slate-700')
                        ui.label('New citizen FIRs will appear here after they are filed.').classes('text-xs text-slate-400')

                # Scrollable FIR items
                with ui.row().classes('w-full flex-wrap gap-3'):
                    for fir in firs:
                        fid = fir.get('id')
                        is_selected = (fid == state['selected_fir_id'])
                        border_cls = 'border-2 border-blue-600 bg-blue-50/70 shadow-md ring-2 ring-blue-100' if is_selected else 'border border-slate-200 bg-white hover:bg-slate-50/80 shadow-xs'

                        with ui.card().classes(f'flex-1 min-w-80 p-4 rounded-2xl {border_cls} transition-all cursor-pointer').on('click', lambda target_id=fid: select_fir(target_id)):
                            with ui.row().classes('w-full items-center justify-between mb-2'):
                                ui.label(fir.get('fir_number')).classes('text-base font-black text-slate-900 font-mono')
                                fir_status_badge(fir.get('status'))

                            with ui.row().classes('items-center gap-2 text-xs text-slate-700 font-bold mb-1'):
                                ui.icon('person', size='xs').classes('text-blue-700')
                                ui.label(fir.get('citizen_name', 'Citizen'))

                            ui.label(f"{fir.get('incident_type')} · {fir.get('police_station')}").classes('text-xs text-slate-500')
                            
                            with ui.row().classes('w-full items-center justify-between mt-3 pt-2 border-t border-slate-100 text-[10px] text-slate-400 font-mono'):
                                ui.label(str(fir.get('created_at', ''))[:10])
                                ui.label(f"Officer: {fir.get('officer_name') or 'Unassigned'}").classes('font-sans font-bold text-slate-600')

        def select_fir(target_id: str):
            state['selected_fir_id'] = target_id
            render_list()
            render_detail_view()

        render_list()
        render_detail_view()


@ui.page('/admin/fir-cases/{fir_id}')
@ui.page('/admin/fir-management/{fir_id}')
def admin_fir_management_param_page(fir_id: str) -> None:
    """Route support for direct FIR management link with path parameter."""
    return admin_fir_management_page(fir_id=fir_id)


# ==========================================
# 4B. CENTRALIZED FIR CASE VIEW (15-Point Master Spec)
# ==========================================

@ui.page('/admin/fir-cases/{fir_id}/full')
@ui.page('/admin/fir-case/{fir_id}/full')
def admin_fir_case_full_history_page(fir_id: str) -> None:
    """
    Centralized FIR Case View — Complete End-to-End Case Record.
    Authorized Officers and Administrators inspect all 15 audit points on one organized page:
    1. Citizen registration details and username
    2. Citizen application date
    3. Identity verification date and approving officer
    4. Original complaint details and submission date
    5. Complaint reference and official FIR number
    6. FIR registration date and Verification Officer details
    7. Original FIR document and all generated versions
    8. Assigned Police Officer and assignment date
    9. Investigation progress and status history
    10. Every change made by the Verification Officer
    11. Every change made by the Police Officer
    12. Previous and current FIR versions
    13. SHA-256 hashes for every recorded version
    14. Complete audit timestamps and responsible officer details
    15. Current case status and closure information
    """
    user = require_admin_user()
    if not user:
        return

    try:
        hist = get_complete_fir_case_history(fir_id, user)
    except Exception as exc:
        with portal_page('admin', '/admin/fir-cases', 'Case Not Found', 'Error loading FIR case record.'):
            ui.label(f"Could not load complete case record: {exc}").classes('text-red-600 font-bold p-6')
            ui.button('← Back to FIR Cases', on_click=lambda: ui.navigate.to('/admin/fir-cases')).classes('mt-4')
        return

    fir = hist['fir']
    citizen = hist['citizen']
    application = hist['application']
    complaint = hist['complaint']
    reg_info = hist['registration_info']
    docs = hist['documents']
    curr_assign = hist['current_assignment']
    all_assign = hist['assignments']
    tracking = hist['tracking_history']
    vo_changes = hist['verification_officer_changes']
    po_changes = hist['police_officer_changes']
    versions = hist['versions']
    closure = hist['closure_info']
    integrity = hist['integrity_verification']

    actual_fir_id = fir['id']
    fir_num = fir.get('fir_number', '—')

    with portal_page(
        'admin',
        '/admin/fir-cases',
        f'Centralized Case Record: {fir_num}',
        f'End-to-end statutory FIR dossier and cryptographic audit history for {fir_num}.'
    ):
        # Top Navigation & Quick Actions
        with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4 flex-wrap gap-3'):
            ui.button(
                '← Back to FIR Cases List',
                icon='arrow_back',
                on_click=lambda: ui.navigate.to(f'/admin/fir-cases?fir_id={actual_fir_id}')
            ).props('flat size=sm').classes('text-slate-700 font-bold rounded-xl text-xs')

            with ui.row().classes('items-center gap-2 flex-wrap'):
                ui.button(
                    'Interactive Tracking & Stage Update ⚙️',
                    icon='tune',
                    on_click=lambda: ui.navigate.to(f'/admin/fir-management/{actual_fir_id}')
                ).props('unelevated outline size=sm').classes('text-indigo-800 font-bold rounded-xl text-xs')
                ui.button(
                    'Blockchain Explorer 🔗',
                    icon='toll',
                    on_click=lambda: ui.navigate.to('/admin/blockchain')
                ).props('unelevated outline size=sm').classes('text-slate-700 font-bold rounded-xl text-xs')

        # ── MASTER SUMMARY BANNER ──────────────────────────────────────────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4 pb-4 border-b border-slate-200'):
                with ui.row().classes('items-center gap-4'):
                    with ui.element('div').classes('w-14 h-14 rounded-2xl flex items-center justify-center bg-indigo-50 text-indigo-900 border border-indigo-200 shadow-sm'):
                        ui.icon('policy', size='md')
                    with ui.column().classes('gap-1'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.label(fir_num).classes('text-2xl font-black text-slate-900 font-mono tracking-tight')
                            fir_status_badge(fir.get('status'))
                            ui.badge(f"Version v{fir.get('current_version', 1)}").classes('bg-blue-100 text-blue-900 border border-blue-300 font-mono font-bold text-xs px-2.5 py-0.5 rounded-full')
                        ui.label(
                            f"Complaint Ref: {complaint.get('reference') or fir.get('reference_number', '—')} · Police Station: {fir.get('police_station', '—')} · Registered: {_mon_fmt(fir.get('created_at'))}"
                        ).classes('text-xs text-slate-600')
                with ui.row().classes('items-center gap-2 flex-wrap'):
                    if integrity.get('is_valid'):
                        ui.badge('✓ Cryptographically Verified').classes('bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-xs px-3 py-1 rounded-full')
                    else:
                        ui.badge('⚠️ Integrity Alert').classes('bg-rose-100 text-rose-900 border border-rose-300 font-bold text-xs px-3 py-1 rounded-full')

        # ── SECTION 1, 2, 3: CITIZEN IDENTITY, APPLICATION & VERIFICATION ──────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('badge', size='sm').classes('text-emerald-700')
                    ui.label('1. Citizen Registration, Application & Identity Verification').classes('text-base font-black text-slate-900 fantasy-title')
                if citizen.get('id'):
                    ui.button(
                        'View Full Citizen Dossier 👥',
                        icon='open_in_new',
                        on_click=lambda cid=citizen.get('id'): ui.navigate.to(f'/admin/citizens/{cid}')
                    ).props('flat size=xs').classes('text-emerald-700 font-bold')

            with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                _mon_detail('Full Legal Name', citizen.get('name') or 'Citizen')
                with ui.column().classes('gap-0 min-w-36 flex-1'):
                    ui.label('Generated Username').classes('text-[10px] font-black text-slate-400 uppercase tracking-wider')
                    if citizen.get('username'):
                        ui.link(f"@{citizen.get('username')}", f"/admin/citizens/{citizen.get('id')}").classes('font-bold text-indigo-700 font-mono hover:underline')
                    else:
                        ui.label('Not issued yet').classes('font-bold text-slate-500 italic')
                _mon_detail('Contact Mobile', citizen.get('phone'), mono=True)
                _mon_detail('Registered Email', citizen.get('email'), mono=True)
                _mon_detail('Gov ID Proof', application.get('gov_id_masked') or citizen.get('gov_id_masked'), mono=True)
                _mon_detail('District / Jurisdiction', citizen.get('district') or application.get('district'))
                _mon_detail('Residential Address', citizen.get('address'))

            ui.separator().classes('my-3')
            with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                _mon_detail('Citizen Application Ref', application.get('reference') or '—', mono=True)
                _mon_detail('Application Date & Time', _mon_fmt(application.get('submitted_at')), mono=True)
                _mon_detail('Citizen Account Status', citizen.get('status') or 'ACTIVE')
                _mon_detail('Identity Verification Date', _mon_fmt(application.get('reviewed_at') or citizen.get('verified_at')), mono=True)
                _mon_detail('Approving Verification Officer', application.get('reviewed_by_name') or 'Authorized Verification Desk')
                _mon_detail('Verification Decision', application.get('status') or citizen.get('verification_status') or 'VERIFIED')

        # ── SECTION 4, 5, 6: COMPLAINT DETAILS & FORMAL FIR REGISTRATION ────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-200 mb-3'):
                ui.icon('assignment', size='sm').classes('text-blue-800')
                ui.label('2. Original Complaint Details & Formal FIR Registration').classes('text-base font-black text-slate-900 fantasy-title')

            with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                _mon_detail('Original Complaint Reference', complaint.get('reference') or fir.get('reference_number'), mono=True)
                _mon_detail('Complaint Submission Date', _mon_fmt(complaint.get('submitted_at') or fir.get('created_at')), mono=True)
                _mon_detail('Incident Category / Type', complaint.get('category') or fir.get('incident_type'))
                _mon_detail('Incident Date & Time', f"{fir.get('incident_date', '—')} {fir.get('incident_time', '')}")
                _mon_detail('Incident Location', complaint.get('location') or fir.get('incident_location'))
                _mon_detail('Accused Details (if named)', complaint.get('accused_details') or 'Not specified')

            # Original Complaint Statement
            with ui.column().classes('w-full mt-3 p-3 bg-slate-50 border border-slate-200 rounded-2xl'):
                ui.label('Original Complaint Statement:').classes('text-[10px] font-black text-slate-500 uppercase tracking-wider mb-1')
                ui.label(complaint.get('description') or fir.get('description') or 'No narrative text recorded.').classes('text-xs text-slate-800 leading-relaxed')

            ui.separator().classes('my-3')
            # Formal FIR Registration Particulars
            with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                _mon_detail('Official FIR Number', fir_num, mono=True)
                _mon_detail('Formal Registration Date & Time', _mon_fmt(reg_info.get('registered_at')), mono=True)
                _mon_detail('Police Station of Record', reg_info.get('police_station'))
                _mon_detail('Registering Verification Officer', reg_info.get('officer_name'))
                _mon_detail('Officer Badge / ID', reg_info.get('officer_badge'), mono=True)
                _mon_detail('Officer Station Jurisdiction', reg_info.get('officer_station'))

        # ── SECTION 7: ORIGINAL & VERSIONED FIR DOCUMENTS ──────────────────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('picture_as_pdf', size='sm').classes('text-rose-700')
                    ui.label(f"3. Official FIR Documents & Generated Versions ({len(docs)})").classes('text-base font-black text-slate-900 fantasy-title')
                ui.badge(f"{len(docs)} Document Copies Archived").classes('bg-rose-50 text-rose-800 border border-rose-200 font-bold text-[10px] px-2 py-0.5 rounded-full')

            if docs:
                with ui.column().classes('w-full gap-2'):
                    for d in docs:
                        with ui.card().classes('w-full p-3 bg-slate-50 border border-slate-200 rounded-2xl flex-row items-center justify-between gap-3 flex-wrap'):
                            with ui.row().classes('items-center gap-3'):
                                with ui.element('div').classes('w-10 h-10 rounded-xl bg-rose-100 text-rose-700 flex items-center justify-center font-bold text-xs'):
                                    ui.label(f"v{d.get('version')}")
                                with ui.column().classes('gap-0'):
                                    ui.label(d.get('file_name') or f"FIR_{fir_num}_v{d.get('version')}.pdf").classes('text-xs font-black text-slate-900 font-mono')
                                    ui.label(
                                        f"Generated {_mon_fmt(d.get('generated_at'))} · SHA-256: {str(d.get('sha256') or '—')[:16]}..."
                                    ).classes('text-[10px] text-slate-500 font-mono')
                            ui.button(
                                'Download Verified PDF 📥',
                                icon='download',
                                on_click=lambda url=d.get('download_url'): ui.navigate.to(url, new_tab=True)
                            ).props('unelevated size=sm').classes('bg-rose-700 hover:bg-rose-800 text-white font-bold rounded-xl text-xs px-3 py-1')
            else:
                ui.label('FIR document generation in progress or rendered on demand from official record.').classes('text-xs text-slate-400 italic py-2')

        # ── SECTION 8: ASSIGNED POLICE OFFICER & ASSIGNMENT TRAIL ──────────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('assignment_ind', size='sm').classes('text-indigo-800')
                    ui.label('4. Assigned Investigating Officer & Assignment Trail').classes('text-base font-black text-slate-900 fantasy-title')
                if curr_assign:
                    ui.badge('Active Assignment').classes('bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-[10px] px-2 py-0.5 rounded-full')
                else:
                    ui.badge('Pending Officer Assignment').classes('bg-amber-100 text-amber-900 border border-amber-300 font-bold text-[10px] px-2 py-0.5 rounded-full')

            if curr_assign:
                with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                    _mon_detail('Investigating Officer Name', curr_assign.get('officer_name'))
                    _mon_detail('Officer Badge / ID', curr_assign.get('officer_badge'), mono=True)
                    _mon_detail('Rank / Designation', curr_assign.get('officer_rank'))
                    _mon_detail('Police Station', curr_assign.get('officer_station'))
                    _mon_detail('Officer Contact Phone', curr_assign.get('officer_phone'), mono=True)
                    _mon_detail('Assignment Date & Time', _mon_fmt(curr_assign.get('assigned_at')), mono=True)
                    _mon_detail('Assigned By Officer', f"{curr_assign.get('assigner_name', 'Verification Desk')} ({curr_assign.get('assigner_badge', 'N/A')})")
            else:
                ui.label('No investigating officer is currently assigned to this FIR.').classes('text-xs text-slate-500 italic py-2')

            if len(all_assign) > 1:
                ui.label('Historical Assignment Chain:').classes('text-[10px] font-black text-slate-500 uppercase tracking-wider mt-3 mb-1')
                with ui.column().classes('w-full gap-1'):
                    for a in all_assign:
                        with ui.row().classes('w-full items-center justify-between p-2 rounded-xl bg-slate-50 text-[11px]'):
                            ui.label(f"{a.get('officer_name')} ({a.get('officer_badge')}) · Assigned {_mon_fmt(a.get('assigned_at'))} by {a.get('assigner_name') or 'Verification Desk'}").classes('text-slate-800')
                            ui.badge(a.get('status', 'ACTIVE')).classes('bg-slate-200 text-slate-700 text-[9px] font-bold')

        # ── SECTION 9: 10-STAGE INVESTIGATION PROGRESSION ──────────────────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('timeline', size='sm').classes('text-blue-700')
                    ui.label(f"5. Investigation Progress & 10-Stage Tracking Timeline ({len(tracking)} Entries)").classes('text-base font-black text-slate-900 fantasy-title')
                ui.badge(f"Current: {STAGE_LABELS.get(fir.get('current_stage'), fir.get('status', 'UNDER_INVESTIGATION'))}").classes('bg-blue-100 text-blue-900 border border-blue-300 font-bold text-xs px-3 py-1 rounded-full')

            if tracking:
                with ui.column().classes('w-full gap-3 mt-2'):
                    for idx, tr in enumerate(tracking):
                        stage_key = tr.get('new_stage', '')
                        st_colour = ADMIN_STAGE_COLOURS.get(stage_key, 'bg-slate-100 text-slate-800 border-slate-200')
                        with ui.card().classes('w-full p-3 rounded-2xl border border-slate-200 bg-slate-50/70 gap-1'):
                            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                                with ui.row().classes('items-center gap-2'):
                                    with ui.element('div').classes('w-6 h-6 rounded-full bg-blue-900 text-white flex items-center justify-center font-bold text-[10px]'):
                                        ui.label(str(idx + 1))
                                    ui.badge(STAGE_LABELS.get(stage_key, stage_key)).classes(f'border font-bold text-xs px-2.5 py-0.5 rounded-full {st_colour}')
                                    if tr.get('action'):
                                        ui.badge(tr.get('action')).classes('bg-slate-200 text-slate-700 font-mono text-[9px] px-1.5 rounded')
                                ui.label(_mon_fmt(tr.get('timestamp'))).classes('text-[11px] font-mono text-slate-500')
                            with ui.row().classes('w-full items-center gap-3 text-xs mt-1'):
                                ui.label(f"Updated by: {tr.get('updated_by_officer_name')} (Badge: {tr.get('updated_by_officer_badge')})").classes('text-slate-700 font-semibold')
                            if tr.get('public_note'):
                                with ui.row().classes('w-full items-start gap-2 mt-1 p-2 bg-white border border-slate-200 rounded-xl text-xs'):
                                    ui.icon('public', size='xs').classes('text-emerald-700 pt-0.5')
                                    with ui.column().classes('gap-0 flex-1'):
                                        ui.label('Citizen-Visible Update:').classes('text-[9px] font-black text-emerald-800 uppercase')
                                        ui.label(tr.get('public_note')).classes('text-slate-800')
                            if tr.get('remarks'):
                                with ui.row().classes('w-full items-start gap-2 mt-1 p-2 bg-indigo-50/50 border border-indigo-100 rounded-xl text-xs'):
                                    ui.icon('lock', size='xs').classes('text-indigo-700 pt-0.5')
                                    with ui.column().classes('gap-0 flex-1'):
                                        ui.label('Internal Police & Admin Remarks:').classes('text-[9px] font-black text-indigo-800 uppercase')
                                        ui.label(tr.get('remarks')).classes('text-slate-700 italic')
            else:
                ui.label('Case tracking initialization pending or complaint awaiting formal review.').classes('text-xs text-slate-400 italic py-2')

        # ── SECTION 10 & 11: VERIFICATION & POLICE OFFICER AUDIT MODIFICATIONS ──
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('history_edu', size='sm').classes('text-amber-700')
                    ui.label('6. Authorized Modifications & Before/After Value Differences').classes('text-base font-black text-slate-900 fantasy-title')
                ui.badge(
                    f"{len(vo_changes)} by Verification Desk · {len(po_changes)} by Police Officer"
                ).classes('bg-amber-50 text-amber-900 border border-amber-300 font-bold text-xs px-2.5 py-1 rounded-full')

            all_changes_combined = [('VERIFICATION OFFICER', vo_changes), ('POLICE INVESTIGATING OFFICER', po_changes)]
            has_any_change = False

            for role_group_title, change_list in all_changes_combined:
                if change_list:
                    has_any_change = True
                    ui.label(f"Changes by {role_group_title} ({len(change_list)} Event(s)):").classes('text-xs font-black text-slate-700 uppercase tracking-wider mt-3 mb-2')
                    with ui.column().classes('w-full gap-3'):
                        for ev in change_list:
                            diffs = ev.get('diffs', [])
                            with ui.card().classes('w-full p-4 bg-slate-50 border border-slate-200 rounded-2xl shadow-xs'):
                                with ui.row().classes('w-full items-center justify-between pb-2 border-b border-slate-200 flex-wrap gap-2'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.badge(f"Event #{ev.get('event_number')}").classes('bg-blue-900 text-white font-mono text-[10px]')
                                        ui.label(f"Version: v{ev.get('previous_version')} → v{ev.get('new_version')}").classes('font-bold text-slate-900 text-xs font-mono')
                                    with ui.row().classes('items-center gap-3 text-[11px] font-mono text-slate-600'):
                                        ui.label(f"Officer: {ev.get('actor_name')} ({ev.get('actor_badge', 'N/A')})")
                                        ui.label(f"Date: {_mon_fmt(ev.get('timestamp'))} {ev.get('timezone', '')}")

                                if ev.get('reason'):
                                    ui.label(f"Reason: {ev.get('reason')}").classes('text-xs text-slate-600 italic mt-2')

                                if diffs:
                                    ui.label('Modified Information:').classes('text-[10px] font-black text-slate-400 uppercase tracking-wider mt-2 mb-1')
                                    with ui.column().classes('w-full gap-2'):
                                        for d in diffs:
                                            with ui.row().classes('w-full items-start gap-2 text-xs flex-wrap'):
                                                ui.label(d['field'].replace('_', ' ').title()).classes('font-black text-slate-700 min-w-36 pt-1')
                                                with ui.element('div').classes('flex-1 min-w-44 p-2 bg-rose-50 border border-rose-200 rounded-xl text-rose-900'):
                                                    ui.label(f"Previous: {d.get('old_value') or '(empty)'}").classes('text-xs break-words')
                                                ui.icon('arrow_forward', size='xs').classes('text-slate-400 pt-2')
                                                with ui.element('div').classes('flex-1 min-w-44 p-2 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-900'):
                                                    ui.label(f"Updated: {d.get('new_value') or '(empty)'}").classes('text-xs break-words')

            if not has_any_change:
                ui.label('No statutory modifications have been made to this FIR record. The file remains in its initial genesis version.').classes('text-xs text-slate-500 italic py-2')

        # ── SECTION 12, 13, 14: RECORD VERSIONS, SHA-256 HASHES & BLOCKCHAIN ───
        with ui.card().classes('w-full p-6 paper-card bg-slate-950 text-white border border-slate-800 rounded-3xl shadow-xl mb-4'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-800 flex-wrap gap-2'):
                with ui.row().classes('items-center gap-3'):
                    with ui.element('div').classes('w-10 h-10 rounded-xl bg-indigo-900 text-indigo-300 flex items-center justify-center font-bold'):
                        ui.icon('toll', size='sm')
                    with ui.column().classes('gap-0'):
                        ui.label('7. Cryptographic SHA-256 Hashes & Blockchain Ledger Trail').classes('text-base font-black text-white fantasy-title')
                        ui.label('Complete immutable cryptographic hash chain and PoA consensus transaction records.').classes('text-xs text-slate-400')
                ui.badge(f"{len(versions)} Recorded Version(s)").classes('bg-indigo-900 text-indigo-200 border border-indigo-700 font-bold text-xs px-2.5 py-0.5 rounded-full')

            with ui.column().classes('w-full gap-3 mt-3'):
                for v in versions:
                    with ui.card().classes('w-full p-4 bg-slate-900 border border-slate-800 rounded-2xl'):
                        with ui.row().classes('w-full items-center justify-between pb-2 border-b border-slate-800 flex-wrap gap-2'):
                            with ui.row().classes('items-center gap-2'):
                                ui.badge(f"Version v{v.get('version_number')}").classes('bg-blue-600 text-white font-mono font-bold text-xs')
                                ui.label(f"Recorded: {_mon_fmt(v.get('created_at'))}").classes('text-xs text-slate-400 font-mono')
                            with ui.row().classes('items-center gap-2'):
                                ui.label(f"Officer: {v.get('created_by_name')} ({v.get('created_by_badge', 'N/A')})").classes('text-xs text-slate-300')
                                ui.badge(v.get('blockchain_status', 'VERIFIED')).classes('bg-emerald-950 text-emerald-300 border border-emerald-800 text-[10px] font-bold')

                        with ui.column().classes('w-full gap-1 mt-2 text-xs font-mono'):
                            with ui.row().classes('w-full items-center justify-between gap-2'):
                                ui.label('Current SHA-256 Canonical Hash:').classes('text-[10px] text-emerald-400 uppercase font-sans font-bold')
                            ui.label(v.get('current_hash', '—')).classes('text-xs text-emerald-300 break-all font-mono')

                            if v.get('previous_hash'):
                                with ui.row().classes('w-full items-center justify-between gap-2 mt-1'):
                                    ui.label('Previous Version Hash:').classes('text-[10px] text-slate-400 uppercase font-sans font-bold')
                                ui.label(v.get('previous_hash', '—')).classes('text-xs text-slate-400 break-all font-mono')

                            with ui.row().classes('w-full items-center gap-4 mt-2 pt-2 border-t border-slate-800 text-[11px] text-indigo-300 flex-wrap'):
                                ui.label(f"Block Index: #{v.get('blockchain_block', 1)}")
                                ui.label(f"Tx Hash: {v.get('blockchain_tx_hash', '—')}")
                                if v.get('change_reason'):
                                    ui.label(f"Reason: {v.get('change_reason')}").classes('text-slate-300 italic')

        # ── SECTION 15: CURRENT CASE STATUS & CLOSURE INFORMATION ──────────────
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('verified_user', size='sm').classes('text-blue-900')
                    ui.label('8. Current Case Status & Final Closure Audit').classes('text-base font-black text-slate-900 fantasy-title')
                fir_status_badge(fir.get('status'))

            if closure:
                with ui.column().classes('w-full p-4 bg-emerald-50 border border-emerald-200 rounded-2xl gap-2'):
                    ui.label('Case Formally Concluded & Closed').classes('text-sm font-black text-emerald-950')
                    with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                        _mon_detail('Closure Date & Time', _mon_fmt(closure.get('closed_at')), mono=True)
                        _mon_detail('Closing Officer', closure.get('closing_officer'))
                        _mon_detail('Closing Officer Badge', closure.get('closing_badge'), mono=True)
                    with ui.column().classes('gap-0 mt-2'):
                        ui.label('Final Closure Remarks / Court Findings:').classes('text-[10px] font-black text-emerald-900 uppercase')
                        ui.label(closure.get('remarks') or 'Case closed.').classes('text-xs text-slate-800 italic')
            else:
                with ui.row().classes('w-full items-center justify-between p-3 bg-slate-50 border border-slate-200 rounded-2xl flex-wrap gap-3'):
                    with ui.column().classes('gap-0'):
                        ui.label('Active Investigation File').classes('text-xs font-black text-slate-900')
                        ui.label(f"Case currently in stage: {STAGE_LABELS.get(fir.get('current_stage'), fir.get('status', 'UNDER_INVESTIGATION'))}").classes('text-xs text-slate-600')
                    ui.button(
                        'Update Case Progression ⚙️',
                        icon='arrow_forward',
                        on_click=lambda: ui.navigate.to(f'/admin/fir-management/{actual_fir_id}')
                    ).props('unelevated size=sm').classes('bg-indigo-900 text-white font-bold rounded-xl text-xs px-3 py-1')


# ==========================================
# 5. CITIZEN DIRECTORY & CASE RECORDS
# ==========================================

@ui.page('/admin/citizens')
def admin_citizens_page(citizen_id: Optional[str] = None) -> None:
    """
    Main Officer Citizen Directory, Registered Information,
    and Associated Complaints & FIR Records.
    """
    user = require_admin_user()
    if not user:
        return

    citizens = get_all_citizens()
    all_firs = get_firs(actor_user=user)
    all_complaints = get_all_complaints(actor_user=user)

    state = {
        'selected_citizen_id': citizen_id or (citizens[0]['id'] if citizens else None),
        'search_query': ''
    }

    with portal_page('admin', '/admin/citizens', 'Citizen Directory & Associated Records', 'Comprehensive citizen profiles, associated complaint submissions, and registered FIRs.'):
        
        with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4 flex-wrap gap-3'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('groups', size='md').classes('text-emerald-700')
                with ui.column().classes('gap-0'):
                    ui.label('State-wide Citizen Directory').classes('text-xl font-black text-slate-900 fantasy-title')
                    ui.label('Inspect citizen verification profiles, active complaints, and registered FIR cases.').classes('text-xs text-slate-500')

            ui.button('Back to Master Dashboard 🏛️', icon='arrow_back', on_click=lambda: ui.navigate.to('/admin')).props('unelevated outline size=sm').classes('text-slate-700 font-bold rounded-xl text-xs')

        list_container = ui.column().classes('w-full gap-3')
        detail_container = ui.column().classes('w-full gap-6')

        def render_citizen_detail():
            detail_container.clear()
            cid = state['selected_citizen_id']
            if not cid:
                with detail_container:
                    ui.label('Select a citizen from the directory to inspect their profile and records.').classes('text-slate-500 italic p-6')
                return

            citizen = get_user_by_id(cid)
            if not citizen:
                with detail_container:
                    ui.label('Citizen record not found.').classes('text-red-600 font-bold p-4')
                return

            # Citizen's complaints and FIRs
            c_complaints = get_complaints_for_citizen(cid)
            c_firs = [f for f in all_firs if f.get('citizen_id') == cid]

            with detail_container:
                # 1. Citizen Profile Card
                with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-200 flex-wrap gap-4'):
                        with ui.row().classes('items-center gap-4'):
                            with ui.element('div').classes('w-14 h-14 rounded-2xl flex items-center justify-center bg-emerald-50 text-emerald-800 border border-emerald-200 shadow-sm'):
                                ui.icon('person', size='md')
                            with ui.column().classes('gap-0.5'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    ui.label(citizen.get('name', 'Citizen')).classes('text-2xl font-black text-slate-900 fantasy-title')
                                    ui.badge(citizen.get('status', 'ACTIVE')).classes('bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-xs px-3 py-0.5 rounded-full')
                                ui.label(f"Citizen ID: {citizen.get('id')} · District: {citizen.get('district') or 'N/A'}").classes('text-xs text-slate-500 font-mono')

                        with ui.row().classes('items-center gap-3'):
                            with ui.column().classes('items-end'):
                                ui.label(f"Total Complaints: {len(c_complaints)}").classes('text-xs font-bold text-slate-700')
                                ui.label(f"Registered FIRs: {len(c_firs)}").classes('text-xs font-bold text-blue-800')

                    # Personal details grid
                    application = get_application_by_citizen(cid) or {}
                    with ui.row().classes('w-full flex-wrap gap-6 pt-4 text-xs'):
                        for label, val in [
                            ('Username', citizen.get('username') or 'Not issued yet'),
                            ('Email Address', citizen.get('email', '—')),
                            ('Phone Number', citizen.get('phone', '—')),
                            ('Gov ID Proof', citizen.get('gov_id_masked') or application.get('gov_id_masked') or '—'),
                            ('District Jurisdiction', citizen.get('district') or application.get('district') or '—'),
                            ('Residential Address', citizen.get('address') or '—'),
                            ('Registration Date', str(citizen.get('created_at', ''))[:19].replace('T', ' ')),
                            ('Application Reference', application.get('reference') or '—'),
                            ('Application Date', str(application.get('submitted_at') or '—')[:19].replace('T', ' ')),
                            ('Identity Verification Date', str(
                                application.get('reviewed_at') or citizen.get('verified_at') or '—'
                            )[:19].replace('T', ' ')),
                            ('Approving Officer', application.get('reviewed_by_name') or '—'),
                            ('Verification Status', citizen.get('verification_status')
                             or application.get('status') or '—'),
                        ]:
                            with ui.column().classes('gap-0 min-w-44 flex-1'):
                                ui.label(label).classes('text-[10px] font-black text-slate-400 uppercase tracking-wider')
                                ui.label(str(val or '—')).classes('font-bold text-slate-900 break-words')

                # 2. Associated Complaints Section
                with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    ui.label(f"Complaints Submitted by Citizen ({len(c_complaints)})").classes('text-base font-black text-slate-900 fantasy-title mb-3')
                    if c_complaints:
                        with ui.column().classes('w-full gap-3'):
                            for cmp in c_complaints:
                                with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-slate-50/60'):
                                    with ui.row().classes('w-full items-center justify-between mb-1'):
                                        with ui.row().classes('items-center gap-2'):
                                            ui.label(cmp.get('reference', cmp.get('id'))).classes('font-mono font-bold text-sm text-slate-900')
                                            ui.badge(cmp.get('category', 'General')).classes('bg-slate-200 text-slate-800 text-[10px] font-bold')
                                        ui.badge(cmp.get('status', 'SUBMITTED')).classes('bg-amber-100 text-amber-900 border border-amber-300 text-xs font-bold')
                                    ui.label(cmp.get('title', 'Complaint')).classes('text-sm font-bold text-slate-800')
                                    ui.label(cmp.get('description', '')).classes('text-xs text-slate-600 mt-1 line-clamp-2')
                                    with ui.row().classes('w-full items-center justify-between mt-2 pt-2 border-t border-slate-200 text-[10px] text-slate-500 font-mono'):
                                        ui.label(f"Location: {cmp.get('location', '—')}")
                                        ui.label(str(cmp.get('submitted_at', ''))[:19].replace('T', ' '))
                    else:
                        ui.label('No preliminary complaints on record for this citizen.').classes('text-xs text-slate-400 italic')

                # 3. Associated FIRs Section
                with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                    ui.label(f"Official FIRs Registered for Citizen ({len(c_firs)})").classes('text-base font-black text-slate-900 fantasy-title mb-3')
                    if c_firs:
                        with ui.column().classes('w-full gap-3'):
                            for f in c_firs:
                                fid = f.get('id')
                                with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-white hover:bg-slate-50 transition-all'):
                                    with ui.row().classes('w-full items-center justify-between mb-2 flex-wrap gap-2'):
                                        with ui.row().classes('items-center gap-2'):
                                            ui.label(f.get('fir_number')).classes('font-mono font-black text-base text-slate-900')
                                            fir_status_badge(f.get('status'))
                                        ui.button(
                                            'Inspect FIR & Blockchain 🔗',
                                            icon='open_in_new',
                                            on_click=lambda target_id=fid: ui.navigate.to(f'/admin/fir-management?fir_id={target_id}')
                                        ).props('unelevated size=sm').classes('bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl text-xs px-3 py-1.5')

                                    with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                                        for lbl, v in [
                                            ('Incident', f.get('incident_type')),
                                            ('Date', f.get('incident_date')),
                                            ('Station', f.get('police_station')),
                                            ('Assigned Officer', f.get('officer_name') or 'Unassigned'),
                                            ('Version', f"v{f.get('current_version', 1)}"),
                                        ]:
                                            with ui.column().classes('gap-0'):
                                                ui.label(lbl).classes('text-[10px] font-black text-slate-400 uppercase tracking-wider')
                                                ui.label(str(v or '—')).classes('font-bold text-slate-800')

                                    # §4D: the profile carries the audit and integrity
                                    # detail an Authorized Officer is permitted to see.
                                    versions = get_fir_versions(fid, actor_user=user)
                                    changes = get_fir_changes(fid, actor_user=user)
                                    chain = get_hash_chain_status(fid)
                                    latest = versions[-1] if versions else {}
                                    with ui.row().classes(
                                        'w-full items-center gap-3 flex-wrap mt-3 pt-2 border-t border-slate-100'):
                                        ui.label(
                                            f"Audit: {len(versions)} version(s) · {len(changes)} recorded change(s)"
                                            f" · last by {latest.get('creator_name') or '—'}"
                                            f" ({str(latest.get('creator_role') or '').replace('_', ' ').title() or '—'})"
                                            f" · {_mon_fmt(latest.get('created_at'))}"
                                        ).classes('text-[10px] font-bold text-slate-600')
                                        ui.badge(chain.get('status') or 'CHECKING').classes(
                                            'bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-[9px] px-1.5 rounded'
                                            if chain.get('chain_valid') else
                                            'bg-rose-100 text-rose-900 border border-rose-300 font-bold text-[9px] px-1.5 rounded')
                                    if latest.get('current_hash'):
                                        ui.label(
                                            f"SHA-256 v{latest.get('version_number')}: {latest['current_hash']}"
                                        ).classes('text-[9px] text-indigo-800 font-mono break-all mt-1')
                    else:
                        ui.label('No registered FIRs found for this citizen.').classes('text-xs text-slate-400 italic')

        def render_citizen_list():
            list_container.clear()
            q = state['search_query'].strip().lower()
            filtered = []
            for c in citizens:
                if not q:
                    filtered.append(c)
                else:
                    if (q in (c.get('name') or '').lower() or
                        q in (c.get('email') or '').lower() or
                        q in (c.get('phone') or '').lower() or
                        q in (c.get('district') or '').lower()):
                        filtered.append(c)
                    else:
                        # Check if matches any of their FIR numbers
                        user_firs = [f for f in all_firs if f.get('citizen_id') == c.get('id')]
                        if any(q in f.get('fir_number', '').lower() for f in user_firs):
                            filtered.append(c)

            with list_container:
                # Search Bar
                with ui.card().classes('w-full p-4 paper-card bg-white border border-slate-200 rounded-2xl shadow-sm mb-2'):
                    with ui.row().classes('w-full items-center gap-3'):
                        search_inp = ui.input(
                            placeholder='Search Citizen Name, Email, Phone, District, FIR #...',
                            value=state['search_query']
                        ).props('dense outlined').classes('flex-1 text-xs')

                        def on_search():
                            state['search_query'] = search_inp.value
                            render_citizen_list()

                        search_inp.on('keydown.enter', on_search)
                        ui.button('Search 🔍', on_click=on_search).props('unelevated size=sm').classes('bg-emerald-700 text-white font-bold rounded-xl px-4 py-2 text-xs')

                ui.label(f"Registered Citizens ({len(filtered)})").classes('text-xs font-bold text-slate-500 uppercase tracking-wider mb-2')

                if not filtered:
                    with ui.card().classes('w-full p-12 text-center bg-white border border-slate-200 rounded-3xl'):
                        ui.icon('groups', size='xl').classes('text-slate-300 mb-2')
                        ui.label('No registered citizens yet.').classes('text-base font-bold text-slate-700')
                        ui.label('Citizen accounts will appear here after registration.').classes('text-xs text-slate-400')

                with ui.row().classes('w-full flex-wrap gap-3'):
                    for c in filtered:
                        cid = c.get('id')
                        is_sel = (cid == state['selected_citizen_id'])
                        border_cls = 'border-2 border-emerald-600 bg-emerald-50/70 shadow-md ring-2 ring-emerald-100' if is_sel else 'border border-slate-200 bg-white hover:bg-slate-50 shadow-xs'

                        c_fir_cnt = len([f for f in all_firs if f.get('citizen_id') == cid])
                        c_cmp_cnt = len([cmp for cmp in all_complaints if cmp.get('citizen_id') == cid])

                        with ui.card().classes(f'flex-1 min-w-80 p-4 rounded-2xl {border_cls} transition-all cursor-pointer').on('click', lambda target_cid=cid: select_citizen(target_cid)):
                            with ui.row().classes('w-full items-center justify-between mb-1'):
                                ui.label(c.get('name', 'Citizen')).classes('text-base font-black text-slate-900')
                                ui.badge(c.get('district') or 'N/A').classes('bg-slate-100 text-slate-700 text-[10px] font-bold')

                            with ui.row().classes('items-center gap-2 text-xs text-slate-600 mb-2'):
                                ui.icon('mail', size='xs')
                                ui.label(c.get('email', '—'))

                            with ui.row().classes('w-full items-center justify-between pt-2 border-t border-slate-100 text-[11px] font-bold'):
                                ui.label(f"📞 {c.get('phone', '—')}").classes('text-slate-600')
                                with ui.row().classes('items-center gap-1'):
                                    ui.badge(f"{c_cmp_cnt} Complaints").classes('bg-amber-100 text-amber-800 text-[10px]')
                                    ui.badge(f"{c_fir_cnt} FIRs").classes('bg-blue-100 text-blue-800 text-[10px]')

        def select_citizen(target_cid: str):
            state['selected_citizen_id'] = target_cid
            render_citizen_list()
            render_citizen_detail()

        render_citizen_list()
        render_citizen_detail()


@ui.page('/admin/citizens/{citizen_id}')
def admin_citizens_param_page(citizen_id: str) -> None:
    """Route support for direct citizen profile link with path parameter."""
    return admin_citizens_page(citizen_id=citizen_id)


# ==========================================
# 6. SYSTEM AUDIT LOGS
# ==========================================
@ui.page('/admin/audit-logs')
def admin_audit_logs_page() -> None:
    """System Audit Logs."""
    user = require_admin_user()
    if not user:
        return
    all_firs = get_firs(actor_user=user)

    with portal_page('admin', '/admin/audit-logs', 'System Audit & Immutability Logs', 'Append-only event trails recorded across all FIR lifecycles.'):
        with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
            ui.label('Append-Only Audit Event Trail').classes('text-xl font-bold text-slate-900 fantasy-title mb-4')

            with ui.column().classes('w-full gap-4'):
                for fir in all_firs:
                    changes = fir.get("changes", [])
                    with ui.expansion(f"{fir.get('fir_number')} · {fir.get('incident_type')} (v{fir.get('current_version')})", icon='history').classes('w-full border rounded-2xl bg-slate-50'):
                        with ui.column().classes('w-full p-4 gap-2 text-xs'):
                            with ui.row().classes('justify-between p-2 bg-white rounded-xl border border-slate-200'):
                                ui.label('Genesis Hash (v1):').classes('font-bold text-slate-700')
                                ui.label(fir.get('current_hash')).classes('font-mono text-emerald-800')
                            with ui.row().classes('justify-between p-2 bg-white rounded-xl border border-slate-200'):
                                ui.label('Current Cryptographic Status:').classes('font-bold text-slate-700')
                                integrity_badge(fir.get('integrity_status', 'VERIFIED'))


# ==========================================
# 6. FIR TAMPERING & AUDIT TRAIL (ADMIN ONLY)
# ==========================================
@ui.page('/admin/tampering-audit')
def admin_tampering_audit_page() -> None:
    """FIR Tampering & Audit Trail - Administrator Only - Uses REAL data from fir_change_events table."""
    user = require_admin_user()
    if not user:
        return

    # Fetch REAL audit events and stats from database
    try:
        audit_stats = get_audit_dashboard_stats(user)
        events = get_all_audit_events(user)
    except PermissionError:
        with portal_page('admin', '/admin/tampering-audit', 'Access Denied', ''):
            ui.label('Administrator access required.').classes('text-red-600 font-bold')
        return

    with portal_page('admin', '/admin/tampering-audit', 'FIR Tampering & Audit Trail', 'Real-time audit of all FIR modifications by authenticated officers from database.'):

        # Security notice
        with ui.card().classes('w-full p-4 bg-red-50 border-l-4 border-red-600 rounded-xl mb-4'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('security', size='sm').classes('text-red-700')
                ui.label('RESTRICTED ACCESS — Administrator Eyes Only. All data from fir_change_events table (immutable audit log).').classes('text-xs font-bold text-red-900')
                ui.badge('🔴 LIVE').classes('bg-red-700 text-white font-bold text-xs animate-pulse')

        # Stats row - REAL DATA with live updates
        stats_container = ui.row().classes('w-full gap-4 mb-6 flex-wrap')
        
        def render_stats():
            stats_container.clear()
            with stats_container:
                fresh_stats = get_audit_dashboard_stats(user)
                for label, val, icon_name, color, bg in [
                    ('Total Audit Events', fresh_stats['total_events'], 'history', '#1E40AF', 'bg-blue-50 border-blue-200'),
                    ('Changes in Last 24h', fresh_stats['recent_24h'], 'update', '#B91C1C', 'bg-red-50 border-red-200'),
                    ('Officers With Changes', fresh_stats['officers_count'], 'badge', '#0F766E', 'bg-teal-50 border-teal-200'),
                ]:
                    with ui.card().classes(f'flex-1 min-w-36 p-4 rounded-2xl border {bg} shadow-sm'):
                        with ui.row().classes('items-center justify-between'):
                            ui.icon(icon_name, size='md').style(f'color: {color}')
                            ui.label(str(val)).classes('text-2xl font-black text-slate-900')
                        ui.label(label).classes('text-xs font-bold text-slate-600 mt-1')

        render_stats()

        # Search & Filter bar
        with ui.card().classes('w-full p-4 bg-white border border-slate-200 rounded-2xl shadow-sm mb-4'):
            ui.label('Search & Filter Audit Events').classes('text-sm font-bold text-slate-700 mb-3')
            with ui.row().classes('w-full gap-3 flex-wrap'):
                search_fir = ui.input('Search FIR Number').classes('flex-1 min-w-40').props('outlined dense')
                search_badge = ui.input('Search Officer Badge/ID').classes('flex-1 min-w-40').props('outlined dense')
                search_name = ui.input('Search Officer Name').classes('flex-1 min-w-40').props('outlined dense')
                sort_sel = ui.select(
                    {'DESC': 'Newest First', 'ASC': 'Oldest First'},
                    value='DESC', label='Sort'
                ).classes('min-w-36').props('outlined dense')

            def do_search():
                filtered = get_all_audit_events(
                    user,
                    search_fir=search_fir.value or '',
                    search_officer_id=search_badge.value or '',
                    search_officer_name=search_name.value or '',
                    sort_order=sort_sel.value or 'DESC'
                )
                results_container.clear()
                with results_container:
                    _render_audit_table(filtered, user)

            ui.button('Search', icon='search', on_click=do_search).props('unelevated').classes(
                'bg-blue-800 text-white font-bold rounded-xl px-6 py-2 text-xs'
            )

        # Audit events table - REAL DATA with live updates
        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200 mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('policy', size='sm').classes('text-red-700')
                    event_count_label = ui.label(f'All FIR Modification Events ({len(events)} from database)').classes('text-xl font-bold text-slate-900 fantasy-title')
                ui.badge('REAL DATABASE DATA').classes('bg-emerald-100 text-emerald-800 font-bold text-xs')

            results_container = ui.column().classes('w-full')
            with results_container:
                _render_audit_table(events, user)

        # Real-time polling for new tampering events (every 5 seconds)
        def check_for_new_events():
            try:
                fresh_events = get_all_audit_events(user)
                if len(fresh_events) != len(events):
                    # New event detected - refresh display
                    events.clear()
                    events.extend(fresh_events)
                    render_stats()
                    event_count_label.text = f'All FIR Modification Events ({len(events)} from database)'
                    results_container.clear()
                    with results_container:
                        _render_audit_table(events, user)
                    # Show notification
                    ui.notify('🔴 NEW TAMPERING EVENT DETECTED!', type='negative', position='top')
            except Exception:
                pass

        ui.timer(5.0, check_for_new_events)


def _render_audit_table(events: list, user: dict) -> None:
    """Render the audit events table."""
    if not events:
        with ui.column().classes('w-full items-center p-12 text-center'):
            ui.icon('search_off', size='xl').classes('text-slate-300 mb-3')
            ui.label('No audit events found matching your criteria.').classes('text-slate-500')
        return

    with ui.element('div').classes('w-full overflow-x-auto'):
        with ui.element('table').classes('w-full text-left text-xs border-collapse'):
            with ui.element('thead').classes('bg-slate-800 text-white'):
                with ui.element('tr'):
                    for col in ['Event #', 'FIR Number', 'Action', 'Changed By', 'Officer Badge', 'Timestamp', 'Location', 'Fields Changed', 'Details']:
                        ui.element('th').classes('p-3 font-bold whitespace-nowrap').text = col

            with ui.element('tbody').classes('divide-y divide-slate-200 bg-white'):
                for ev in events:
                    evt_id = ev.get('id', '')
                    fields = ev.get('changed_fields', [])
                    ts = str(ev.get('timestamp', ''))[:19]
                    with ui.element('tr').classes('hover:bg-red-50/30 transition-colors'):
                        with ui.element('td').classes('p-3 font-bold text-blue-800 font-mono whitespace-nowrap'):
                            ui.label(ev.get('event_number', 'EVT-?'))
                        with ui.element('td').classes('p-3 font-black text-slate-900 font-mono whitespace-nowrap'):
                            ui.label(ev.get('fir_number', ev.get('fir_id', '—')))
                        with ui.element('td').classes('p-3 whitespace-nowrap'):
                            ui.badge('MODIFIED').classes('bg-amber-100 text-amber-900 font-bold text-[10px]')
                        with ui.element('td').classes('p-3 font-bold text-slate-800 whitespace-nowrap'):
                            ui.label(ev.get('actor_name', '—'))
                        with ui.element('td').classes('p-3 font-bold text-blue-700 font-mono whitespace-nowrap'):
                            ui.label(ev.get('actor_badge', '—'))
                        with ui.element('td').classes('p-3 text-slate-700 font-mono whitespace-nowrap'):
                            ui.label(ts)
                        with ui.element('td').classes('p-3 text-slate-600 whitespace-nowrap'):
                            ui.label(ev.get('ip_address', '—'))
                        with ui.element('td').classes('p-3 whitespace-nowrap'):
                            ui.badge(str(len(fields))).classes('bg-indigo-100 text-indigo-900 font-bold')
                        with ui.element('td').classes('p-3 whitespace-nowrap'):
                            ui.button('View', icon='open_in_new',
                                on_click=lambda eid=evt_id: ui.navigate.to(f'/admin/tampering-audit/{eid}')
                            ).props('flat size=xs').classes('text-blue-700 font-bold')


@ui.page('/admin/tampering-audit/{event_id}')
def admin_audit_event_detail_page(event_id: str) -> None:
    """Full detail view of a single audit event. ADMIN ONLY."""
    user = require_admin_user()
    if not user:
        return

    try:
        ev = get_audit_event_detail(event_id, user)
    except PermissionError:
        with portal_page('admin', '/admin/tampering-audit', 'Access Denied', ''):
            ui.label('Administrator access required.').classes('text-red-600 font-bold')
        return

    if not ev:
        with portal_page('admin', '/admin/tampering-audit', 'Event Not Found', ''):
            ui.label('Audit event not found.').classes('text-slate-600')
            ui.button('Back', on_click=lambda: ui.navigate.to('/admin/tampering-audit')).props('unelevated')
        return

    fields = ev.get('changed_fields', [])
    old_vals = ev.get('old_values', {})
    new_vals = ev.get('new_values', {})
    ts = str(ev.get('timestamp', ''))[:19]

    with portal_page('admin', '/admin/tampering-audit', f"Audit Detail: {ev.get('event_number', event_id)}", f"FIR: {ev.get('fir_number', '—')}"):

        ui.button('← Back to Audit Trail', icon='arrow_back',
            on_click=lambda: ui.navigate.to('/admin/tampering-audit')
        ).props('flat').classes('text-slate-600 font-bold mb-4')

        # Header Card with Tampering ID and FIR Info
        with ui.card().classes('w-full p-6 bg-white border-l-4 border-red-600 rounded-2xl shadow-sm mb-4'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('policy', size='lg').classes('text-red-700')
                    with ui.column().classes('gap-0'):
                        ui.label(f"Tampering ID: {ev.get('event_number', event_id)}").classes('text-2xl font-black text-slate-900 font-mono')
                        ui.label(f"FIR: {ev.get('fir_number', '—')} · Type: {ev.get('incident_type', '—')}").classes('text-sm text-slate-600')
                        if ev.get('citizen_name'):
                            ui.label(f"Citizen: {ev.get('citizen_name')} ({ev.get('citizen_phone', '')})").classes('text-sm font-bold text-emerald-700')
                ui.badge('REAL DATABASE RECORD').classes('bg-emerald-700 text-white font-bold text-xs')

        with ui.row().classes('w-full gap-4 flex-wrap'):
            # FIR & Citizen Information
            with ui.card().classes('flex-1 min-w-72 p-5 bg-white border border-slate-200 rounded-2xl shadow-sm'):
                ui.label('FIR & Citizen Information').classes('text-sm font-black text-slate-700 uppercase tracking-wider mb-3 pb-2 border-b border-slate-200')
                for label, val in [
                    ('Tampering/Event ID', ev.get('event_number', event_id)),
                    ('FIR Number', ev.get('fir_number', '—')),
                    ('Citizen Name', ev.get('citizen_name', '—')),
                    ('Citizen Phone', ev.get('citizen_phone', '—')),
                    ('Citizen Email', ev.get('citizen_email', '—')),
                    ('Incident Type', ev.get('incident_type', '—')),
                    ('Police Station', ev.get('police_station', '—')),
                    ('Current FIR Status', ev.get('fir_status', '—')),
                    ('Incident Date', ev.get('incident_date', '—')),
                    ('Location', ev.get('incident_location', '—')),
                ]:
                    with ui.row().classes('items-start justify-between py-1 border-b border-slate-100 gap-2'):
                        ui.label(label).classes('text-xs font-bold text-slate-500 min-w-32')
                        ui.label(str(val or '—')).classes('text-xs font-bold text-slate-900 text-right')

            # Officer & Modification Information
            with ui.card().classes('flex-1 min-w-72 p-5 bg-white border border-slate-200 rounded-2xl shadow-sm'):
                ui.label('Officer Who Made Change').classes('text-sm font-black text-slate-700 uppercase tracking-wider mb-3 pb-2 border-b border-slate-200')
                for label, val in [
                    ('Change Type', ev.get('event_type', 'AUTHORIZED_FIR_UPDATE')),
                    ('Officer Name', ev.get('actor_name', '—')),
                    ('Officer Badge/ID', ev.get('actor_badge', '—')),
                    ('Officer Role', ev.get('actor_role', '—')),
                    ('Date & Time', ts),
                    ('Timezone', ev.get('timezone', 'IST (UTC+05:30)')),
                    ('IP Address', ev.get('ip_address', '—')),
                    ('Device Info', ev.get('device_info', '—')),
                    ('Change Reason', ev.get('reason', '—')),
                    ('Version Change', f"v{ev.get('previous_version', '?')} → v{ev.get('new_version', '?')}"),
                    ('Fields Modified', str(len(fields))),
                    ('Previous Hash', str(ev.get('previous_hash', '—'))[:16] + '...' if ev.get('previous_hash') else '—'),
                    ('New Hash', str(ev.get('new_hash', '—'))[:16] + '...' if ev.get('new_hash') else '—'),
                    ('Blockchain Tx ID', str(ev.get('blockchain_tx_id', '—'))[:20] + '...' if ev.get('blockchain_tx_id') else '—'),
                    ('Blockchain Block #', str(ev.get('blockchain_block', '—'))),
                    ('Integrity Status', ev.get('blockchain_status', '—')),
                ]:
                    with ui.row().classes('items-start justify-between py-1 border-b border-slate-100 gap-2'):
                        ui.label(label).classes('text-xs font-bold text-slate-500 min-w-32')
                        ui.label(str(val or '—')).classes('text-xs font-bold text-slate-900 text-right break-all')

        # Before & After comparison
        if fields:
            ui.label('Before & After Comparison').classes('text-lg font-black text-slate-900 mt-6 mb-3')
            with ui.row().classes('w-full gap-4 flex-wrap'):
                # BEFORE
                with ui.card().classes('flex-1 min-w-64 p-5 bg-red-50 border-2 border-red-200 rounded-2xl'):
                    with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-red-200'):
                        ui.icon('arrow_back', size='sm').classes('text-red-700')
                        ui.label('BEFORE').classes('text-sm font-black text-red-800 uppercase tracking-wider')
                    for field in fields:
                        old_val = old_vals.get(field, '—')
                        with ui.column().classes('gap-0.5 mb-3'):
                            ui.label(field.replace('_', ' ').title()).classes('text-[10px] font-black text-red-600 uppercase tracking-wider')
                            with ui.element('div').classes('p-2 rounded-lg bg-red-100 border border-red-200'):
                                ui.label(str(old_val) if old_val else '(empty)').classes('text-xs text-red-900 leading-relaxed')

                # AFTER
                with ui.card().classes('flex-1 min-w-64 p-5 bg-emerald-50 border-2 border-emerald-200 rounded-2xl'):
                    with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-emerald-200'):
                        ui.icon('arrow_forward', size='sm').classes('text-emerald-700')
                        ui.label('AFTER').classes('text-sm font-black text-emerald-800 uppercase tracking-wider')
                    for field in fields:
                        new_val = new_vals.get(field, '—')
                        with ui.column().classes('gap-0.5 mb-3'):
                            ui.label(field.replace('_', ' ').title()).classes('text-[10px] font-black text-emerald-600 uppercase tracking-wider')
                            with ui.element('div').classes('p-2 rounded-lg bg-emerald-100 border border-emerald-200'):
                                ui.label(str(new_val) if new_val else '(empty)').classes('text-xs text-emerald-900 leading-relaxed')

        # Cryptographic Hashes
        with ui.card().classes('w-full p-5 bg-slate-900 rounded-2xl mt-4'):
            ui.label('Cryptographic Proof').classes('text-xs font-black text-amber-400 uppercase tracking-wider mb-3')
            with ui.column().classes('gap-2 font-mono text-xs'):
                for label, val in [
                    ('Previous Hash (H_old)', ev.get('previous_hash', '—')),
                    ('New Hash (H_new)', ev.get('new_hash', '—')),
                    ('Event Hash', ev.get('event_hash', '—')),
                ]:
                    with ui.row().classes('items-start gap-3 flex-wrap'):
                        ui.label(f"{label}:").classes('text-slate-400 font-bold min-w-48 whitespace-nowrap')
                        ui.label(str(val or '—')).classes('text-emerald-400 break-all')


@ui.page('/admin/fir-audit/{fir_id}')
def admin_fir_audit_history_page(fir_id: str) -> None:
    """View full audit history for a specific FIR. ADMIN ONLY."""
    user = require_admin_user()
    if not user:
        return

    try:
        events = get_audit_events_for_fir(fir_id, user)
    except PermissionError:
        with portal_page('admin', '/admin/tampering-audit', 'Access Denied', ''):
            ui.label('Administrator access required.').classes('text-red-600 font-bold')
        return

    fir_number = events[0].get('fir_number', fir_id) if events else fir_id

    with portal_page('admin', '/admin/tampering-audit', f'FIR Audit History: {fir_number}', f'Chronological modification trail for {fir_number}'):

        ui.button('← Back to Audit Trail', icon='arrow_back',
            on_click=lambda: ui.navigate.to('/admin/tampering-audit')
        ).props('flat').classes('text-slate-600 font-bold mb-4')

        if not events:
            with ui.card().classes('w-full p-12 text-center bg-white border border-slate-200 rounded-2xl'):
                ui.icon('history', size='xl').classes('text-slate-300 mb-3')
                ui.label(f'No modification events recorded for {fir_number}.').classes('text-slate-500 text-lg')
                ui.label('The FIR is still in its original Version 1 state.').classes('text-slate-400 text-sm mt-1')
            return

        ui.label(f'{len(events)} Modification Event(s) Recorded').classes('text-sm font-bold text-slate-600 mb-4')

        with ui.column().classes('w-full gap-4'):
            for i, ev in enumerate(events):
                fields = ev.get('changed_fields', [])
                old_vals = ev.get('old_values', {})
                new_vals = ev.get('new_values', {})
                ts = str(ev.get('timestamp', ''))[:19]

                with ui.card().classes('w-full p-5 bg-white border-l-4 border-indigo-500 rounded-2xl shadow-sm'):
                    # Timeline indicator
                    with ui.row().classes('w-full items-center justify-between mb-3'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes('w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center text-white text-xs font-black'):
                                ui.label(str(i + 1))
                            with ui.column().classes('gap-0'):
                                ui.label(ev.get('event_number', f'Event {i+1}')).classes('text-sm font-black text-slate-900 font-mono')
                                ui.label(ts).classes('text-xs text-slate-500 font-mono')
                        ui.button('Full Detail →', icon='open_in_new',
                            on_click=lambda eid=ev.get('id', ''): ui.navigate.to(f'/admin/tampering-audit/{eid}')
                        ).props('flat size=xs').classes('text-blue-700 font-bold')

                    with ui.row().classes('w-full flex-wrap gap-4 text-xs'):
                        for label, val in [
                            ('Officer', ev.get('actor_name', '—')),
                            ('Badge', ev.get('actor_badge', '—')),
                            ('Version', f"v{ev.get('previous_version')} → v{ev.get('new_version')}"),
                            ('Fields Changed', str(len(fields))),
                            ('Reason', ev.get('reason', '—')),
                        ]:
                            with ui.column().classes('gap-0 min-w-28'):
                                ui.label(label).classes('text-[10px] font-black text-slate-500 uppercase tracking-wider')
                                ui.label(str(val or '—')).classes('font-bold text-slate-900')

                    # Inline before/after for each field
                    if fields:
                        ui.separator().classes('my-3')
                        with ui.column().classes('gap-2'):
                            for field in fields:
                                old_v = old_vals.get(field, '—')
                                new_v = new_vals.get(field, '—')
                                with ui.row().classes('w-full gap-3 items-start flex-wrap'):
                                    ui.label(field.replace('_', ' ').title()).classes('text-xs font-black text-slate-600 min-w-32 pt-1')
                                    with ui.element('div').classes('flex-1 p-2 bg-red-50 border border-red-200 rounded-lg'):
                                        ui.label(f"Before: {old_v or '(empty)'}").classes('text-xs text-red-800')
                                    ui.icon('arrow_forward', size='xs').classes('text-slate-400 pt-2')
                                    with ui.element('div').classes('flex-1 p-2 bg-emerald-50 border border-emerald-200 rounded-lg'):
                                        ui.label(f"After: {new_v or '(empty)'}").classes('text-xs text-emerald-800')


# ==========================================
# 7. INVESTIGATION MONITOR (officer workload oversight)
# ==========================================

ADMIN_CASE_EVENTS = (
    'NOTIFICATION_CREATED', 'FIR_UPDATED', 'CASE_STAGE_UPDATED',
    'INVESTIGATION_UPDATED', 'OFFICER_CREDITS_UPDATED', 'CHAT_MESSAGE',
    'OFFICER_STATUS_UPDATED',
)

ADMIN_STAGE_COLOURS = {
    'OFFICER_ASSIGNED': 'bg-amber-100 text-amber-900 border-amber-300',
    'INVESTIGATION_STARTED': 'bg-blue-100 text-blue-900 border-blue-300',
    'EVIDENCE_COLLECTION': 'bg-sky-100 text-sky-900 border-sky-300',
    'WITNESS_STATEMENTS': 'bg-cyan-100 text-cyan-900 border-cyan-300',
    'INVESTIGATION_IN_PROGRESS': 'bg-purple-100 text-purple-900 border-purple-300',
    'INVESTIGATION_COMPLETED': 'bg-emerald-100 text-emerald-900 border-emerald-300',
    'CHARGESHEET_PREPARED': 'bg-teal-100 text-teal-900 border-teal-300',
    'SUBMITTED_TO_COURT': 'bg-indigo-100 text-indigo-900 border-indigo-300',
    'CASE_CLOSED': 'bg-slate-200 text-slate-700 border-slate-300',
}


def _mon_fmt(value) -> str:
    text = str(value or '').replace('T', ' ')
    return text[:16] if len(text) >= 16 else (text or '—')


def _mon_identity(fir_number, citizen_name, complaint_reference=None) -> None:
    """Every FIR number on this portal is followed by the citizen's name."""
    ui.label(f"FIR No: {fir_number or '—'}").classes('text-base font-black text-slate-900 font-mono leading-tight')
    ui.label(f"Citizen: {citizen_name or 'Not recorded'}").classes('text-[11px] font-bold text-blue-800')
    if complaint_reference:
        ui.label(f"Complaint Ref: {complaint_reference}").classes('text-[10px] text-slate-500 font-mono')


def _mon_listen(refreshable_fn) -> None:
    """Keep the open monitor page in step with the officer working on the case."""
    client = ui.context.client
    queue = subscribe()

    async def listener() -> None:
        while True:
            event = await queue.get()
            if event.get('type') not in ADMIN_CASE_EVENTS:
                continue
            if not client.has_socket_connection:
                break
            with client:
                refreshable_fn.refresh()

    task = background_tasks.create(listener(), name='admin-investigation-listener')

    def stop() -> None:
        unsubscribe(queue)
        task.cancel()

    client.on_disconnect(stop)


def _mon_open_file(content: bytes, file_name: str, content_type: str) -> None:
    """Preview an authorized internal file without exposing a public URL."""
    encoded = base64.b64encode(content).decode('ascii')
    data_url = f"data:{content_type or 'application/octet-stream'};base64,{encoded}"
    with ui.dialog() as dlg, ui.card().classes('w-full max-w-5xl p-5 bg-white rounded-3xl shadow-2xl'):
        with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-200'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('insert_drive_file', size='sm').classes('text-indigo-800')
                ui.label(file_name or 'Document').classes('text-sm font-black text-slate-900')
            with ui.row().classes('items-center gap-2'):
                ui.button('Download', icon='download', on_click=lambda: ui.download(
                    content, file_name or 'document')).props('flat dense size=sm').classes('text-indigo-800 font-bold')
                ui.button(icon='close', on_click=dlg.close).props('flat round dense').classes('text-slate-400')
        if content_type == 'application/pdf':
            ui.html(
                f'<iframe src="{data_url}" title="{file_name}" '
                'style="width:100%;height:70vh;border:1px solid #e2e8f0;border-radius:16px;"></iframe>',
                sanitize=False,
            )
        elif (content_type or '').startswith('image/'):
            ui.image(data_url).classes('w-full rounded-2xl border border-slate-200')
        else:
            ui.label('Preview is unavailable for this file type. Use Download.').classes(
                'text-xs text-slate-500 py-6 text-center w-full')
        dlg.open()


@ui.page('/admin/investigations')
def admin_investigations_page() -> None:
    """Live oversight of every case an investigating officer holds."""
    user = require_admin_user()
    if not user:
        return

    state = {'query': ''}

    @ui.refreshable
    def monitor_view() -> None:
        rows = get_admin_investigation_overview()
        stats = compute_case_stats(rows)
        query = state['query'].strip().lower()
        if query:
            rows = [
                r for r in rows
                if query in ' '.join(str(r.get(k) or '') for k in (
                    'fir_number', 'citizen_name', 'officer_name', 'complaint_reference',
                    'incident_type', 'police_station')).lower()
            ]

        with ui.row().classes('w-full flex-wrap gap-3'):
            cards_data = [
                ('Cases Under Oversight', stats['total'], 'assignment_ind', '#1E40AF', 'bg-blue-50/80 border-blue-200'),
                ('Awaiting Officer Action', stats['awaiting_action'], 'priority_high', '#DC2626', 'bg-red-50/80 border-red-200'),
                ('Under Investigation', stats['under_investigation'], 'manage_search', '#6D28D9', 'bg-purple-50/80 border-purple-200'),
                ('Evidence Collection', stats['evidence'], 'policy', '#0284C7', 'bg-sky-50/80 border-sky-200'),
                ('Investigation Completed', stats['completed'], 'task_alt', '#059669', 'bg-emerald-50/80 border-emerald-200'),
                ('Submitted for Proceedings', stats['proceedings'], 'account_balance', '#0F766E', 'bg-teal-50/80 border-teal-200'),
                ('Closed Cases', stats['closed'], 'folder_off', '#475569', 'bg-slate-100 border-slate-200'),
            ]
            for label, value, icon_name, colour, background in cards_data:
                with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border shadow-xs {background} gap-1'):
                    with ui.row().classes('w-full items-center justify-between'):
                        ui.icon(icon_name, size='md').style(f'color: {colour}')
                        ui.label(str(value)).classes('text-3xl font-black text-slate-900')
                    ui.label(label).classes('text-[11px] font-bold text-slate-700 leading-tight')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 pb-4 border-b border-slate-100'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('engineering', size='sm').classes('text-indigo-800')
                    ui.label('Officer Case Board').classes('text-lg font-bold text-slate-900 fantasy-title')
                    ui.badge(f"{len(rows)} case(s)").classes(
                        'bg-indigo-100 text-indigo-900 font-bold text-[10px] px-2 rounded-full')
                with ui.row().classes('items-center gap-2'):
                    ui.icon('bolt', size='xs').classes('text-emerald-600')
                    ui.label('Updates live — no reload needed').classes('text-[10px] text-slate-500')

            if not rows:
                with ui.column().classes('w-full items-center py-10 gap-2 text-center'):
                    ui.icon('policy', size='lg').classes('text-slate-300')
                    ui.label('No assigned cases to monitor yet.').classes('text-sm font-bold text-slate-600')
                    ui.label('Cases appear here the moment the Verification Officer assigns an investigating officer.').classes(
                        'text-[11px] text-slate-400 max-w-md')
                return

            with ui.column().classes('w-full gap-3 mt-4'):
                for case in rows:
                    stage_class = ADMIN_STAGE_COLOURS.get(case.get('current_stage'), 'bg-slate-100 text-slate-600 border-slate-200')
                    with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-slate-50/60 shadow-xs'):
                        with ui.row().classes('w-full items-start justify-between flex-wrap gap-3'):
                            with ui.column().classes('gap-1 flex-1 min-w-64'):
                                with ui.row().classes('items-center gap-2 flex-wrap'):
                                    _mon_identity(
                                        case.get('fir_number'), case.get('citizen_name'),
                                        case.get('complaint_reference'))
                                    fir_status_badge(case.get('status'))
                                ui.badge(case.get('stage_label') or 'Awaiting tracking').classes(
                                    f'border font-bold text-[10px] px-2 py-0.5 rounded-full self-start {stage_class}')
                                ui.label(
                                    f"Investigation stage {case.get('stage_index', -1) + 1 if case.get('stage_index', -1) >= 0 else 0}"
                                    f" of {len(OFFICER_STAGES)} · milestones {case.get('milestones_completed', 0)}"
                                    f" · notes & evidence {case.get('entries_count', 0)}"
                                ).classes('text-[10px] text-slate-500')
                            with ui.column().classes('gap-1 min-w-56 text-right'):
                                ui.label(
                                    f"Officer: {case.get('officer_name') or 'Unassigned'}").classes(
                                        'text-xs font-black text-slate-800')
                                ui.label(
                                    f"{case.get('incident_type') or '—'} · {case.get('police_station') or '—'}").classes(
                                        'text-[10px] text-slate-500')
                                ui.label(f"Assigned: {_mon_fmt(case.get('assigned_at'))}").classes(
                                    'text-[10px] text-slate-500 font-mono')
                                ui.label(f"Last update: {_mon_fmt(case.get('last_update_at'))}").classes(
                                    'text-[10px] text-emerald-700 font-mono')
                                ui.button(
                                    'Open Case Monitor', icon='monitoring',
                                    on_click=lambda fid=case['id']: ui.navigate.to(f'/admin/investigations/{fid}'),
                                ).props('unelevated no-caps size=sm').classes(
                                    'bg-indigo-800 text-white font-bold rounded-xl text-xs')

    with portal_page(
        'admin', '/admin/investigations', 'Investigation Monitor',
        'Live view of every assigned case: officer, citizen, stage, progress history, internal records and instructions.',
    ):
        with ui.card().classes('w-full p-4 bg-white border border-slate-200 rounded-2xl shadow-sm'):
            with ui.row().classes('w-full items-center gap-3 flex-wrap'):
                search = ui.input(
                    placeholder='Search by FIR number, citizen, officer, category or station…',
                ).props('outlined dense clearable').classes('flex-1 min-w-64 text-sm')
                def on_search(event) -> None:
                    state['query'] = event.value or ''
                    monitor_view.refresh()

                search.on_value_change(on_search)
                ui.button('Refresh', icon='refresh', on_click=monitor_view.refresh).props(
                    'outline no-caps size=sm').classes('text-indigo-800 font-bold')

        monitor_view()
        _mon_listen(monitor_view)
        ui.timer(30, monitor_view.refresh)


def _mon_detail(label: str, value, *, mono: bool = False) -> None:
    """One labelled value in an authorized record grid."""
    with ui.column().classes('gap-0.5 min-w-40 flex-1'):
        ui.label(label).classes('text-[10px] font-black text-slate-500 uppercase tracking-wider')
        ui.label(str(value if value not in (None, '') else '—')).classes(
            f"text-xs font-bold text-slate-900 {'font-mono break-all' if mono else ''}")


def _render_case_origin(record: Dict[str, Any]) -> None:
    """Citizen registration, identity approval, complaint origin and FIR registration."""
    citizen = record.get('citizen') or {}
    application = record.get('application') or {}
    complaint = record.get('complaint') or {}
    registration = record.get('registration') or {}
    closure = record.get('closure') or {}
    case = record.get('case') or {}
    counts = record.get('counts') or {}

    with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
        with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
            ui.icon('badge', size='sm').classes('text-emerald-700')
            ui.label('Case Origin & Registration Record').classes(
                'text-base font-bold text-slate-900 fantasy-title')
            ui.badge('Authorized Officer view').classes(
                'bg-emerald-50 text-emerald-800 border border-emerald-200 font-bold text-[10px] px-2 rounded-full')

        with ui.row().classes('w-full items-center gap-3 flex-wrap'):
            ui.label(citizen.get('name') or case.get('citizen_name') or 'Citizen not recorded').classes(
                'text-sm font-black text-slate-900')
            if citizen.get('username'):
                def open_citizen_profile(target_id=citizen.get('id')):
                    ui.navigate.to(f'/admin/citizens/{target_id}')

                ui.button(str(citizen['username']), icon='account_circle',
                          on_click=open_citizen_profile).props('outline dense size=sm no-caps').classes(
                    'text-emerald-800 font-bold border-emerald-300 font-mono')
                ui.label('Click the username for the full citizen profile and case history.').classes(
                    'text-[10px] text-slate-400')
            else:
                ui.badge('USERNAME NOT ISSUED').classes(
                    'bg-slate-100 text-slate-600 border border-slate-200 font-bold text-[10px] px-2 rounded-full')

        with ui.row().classes('w-full flex-wrap gap-4 mt-4'):
            with ui.column().classes('gap-3 w-full'):
                ui.label('Citizen registration & identity verification').classes(
                    'text-[11px] font-black text-slate-700')
                with ui.row().classes('w-full flex-wrap gap-4'):
                    _mon_detail('Registration Date', _mon_fmt(citizen.get('created_at')))
                    _mon_detail('Application Reference', application.get('reference'))
                    _mon_detail('Application Date', _mon_fmt(application.get('submitted_at')))
                    _mon_detail('Application Status', application.get('status'))
                with ui.row().classes('w-full flex-wrap gap-4'):
                    _mon_detail('Identity Verified On', _mon_fmt(
                        application.get('reviewed_at') or citizen.get('verified_at')))
                    _mon_detail('Approving Officer', application.get('reviewed_by_name') or '—')
                    _mon_detail('Verification Status', citizen.get('verification_status') or '—')
                    _mon_detail('Government ID', citizen.get('gov_id_masked') or application.get('gov_id_masked'))
                    _mon_detail('Records On File',
                                f"{counts.get('complaints', 0)} complaint(s) · {counts.get('firs', 0)} FIR(s)")

            with ui.column().classes('gap-3 w-full'):
                ui.label('Original complaint & official registration').classes(
                    'text-[11px] font-black text-slate-700')
                with ui.row().classes('w-full flex-wrap gap-4'):
                    _mon_detail('Complaint Reference (not the FIR number)', complaint.get('reference'), mono=True)
                    _mon_detail('Complaint Submitted', _mon_fmt(complaint.get('submitted_at')))
                    _mon_detail('Complaint Category', complaint.get('category') or case.get('incident_type'))
                    _mon_detail('Verified By', f"{complaint.get('verified_by_name') or '—'} · "
                                               f"{_mon_fmt(complaint.get('verified_at'))}")
                with ui.row().classes('w-full flex-wrap gap-4'):
                    _mon_detail('Official FIR Number', case.get('fir_number'), mono=True)
                    _mon_detail('FIR Registered On', _mon_fmt(registration.get('created_at')))
                    _mon_detail('Registering Verification Officer',
                                f"{registration.get('officer_name') or 'Not recorded'}"
                                f" · {str(registration.get('officer_role') or '').replace('_', ' ').title() or '—'}"
                                + (f" · Badge {registration['officer_badge']}"
                                   if registration.get('officer_badge') else ''))
                    _mon_detail('Pre-registration Corrections',
                                f"By {complaint.get('fir_edited_by_name')}"
                                f" · {_mon_fmt(complaint.get('fir_edited_at'))}"
                                if complaint.get('fir_edited_at') else 'None recorded')

        if complaint.get('description'):
            ui.label(str(complaint['description'])).classes(
                'text-[11px] text-slate-700 leading-relaxed mt-4 whitespace-pre-line')

        with ui.row().classes('w-full flex-wrap gap-4 mt-4 pt-3 border-t border-slate-100'):
            _mon_detail('Current Case Status', case.get('status'))
            _mon_detail('Current Stage', case.get('stage_label'))
            if record.get('is_closed'):
                _mon_detail('Closed On', _mon_fmt(closure.get('timestamp')))
                _mon_detail('Closed By', f"{closure.get('updated_by_officer_name') or '—'}"
                                         f" · Badge {closure.get('updated_by_officer_badge') or 'N/A'}")
                _mon_detail('Closure Remarks', closure.get('remarks'))
            else:
                _mon_detail('Closure', 'Not closed — case is still under investigation')


def _render_case_documents(user: Dict[str, Any], record: Dict[str, Any]) -> None:
    """The FIR document and every version previously issued for this case."""
    documents = record.get('documents') or []
    with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
        with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
            ui.icon('description', size='sm').classes('text-blue-800')
            ui.label('FIR Document & Generated Versions').classes(
                'text-base font-bold text-slate-900 fantasy-title')
            ui.badge(f"{len(documents)} version(s)").classes(
                'bg-slate-100 text-slate-600 font-bold text-[10px] px-2 rounded-full')

        if not documents:
            ui.label('No FIR document has been generated for this case yet.').classes(
                'text-xs text-slate-500')
            return

        with ui.column().classes('w-full gap-2'):
            for document in documents:
                with ui.row().classes(
                    'w-full items-center justify-between gap-3 p-3 rounded-xl border border-slate-200 bg-slate-50/60'):
                    with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                        with ui.row().classes('items-center gap-2 flex-wrap'):
                            ui.label(f"v{document.get('version')} · {document.get('file_name')}").classes(
                                'text-xs font-black text-slate-900 font-mono truncate')
                            if document.get('is_current'):
                                ui.badge('CURRENT').classes(
                                    'bg-emerald-100 text-emerald-800 font-bold text-[9px] px-1.5 rounded')
                        ui.label(
                            f"Generated by {document.get('generated_by_name') or 'Officer'} · "
                            f"{_mon_fmt(document.get('generated_at'))}").classes('text-[10px] text-slate-500')
                        if document.get('sha256'):
                            ui.label(f"SHA-256 {document['sha256']}").classes(
                                'text-[9px] text-slate-400 font-mono break-all')

                    def open_document(entry=document):
                        content = read_document_bytes(entry)
                        if not content:
                            ui.notify('The stored document is no longer available.', type='warning')
                            return
                        _mon_open_file(content, entry.get('file_name') or 'FIR.pdf', 'application/pdf')

                    ui.button('Open', icon='visibility', on_click=open_document).props(
                        'outline dense size=sm no-caps').classes('text-blue-800 font-bold border-blue-300')


def _render_change_diffs(changes: List[Dict[str, Any]], empty_text: str) -> None:
    """Previous value vs updated value, officer, date/time and optional reason."""
    if not changes:
        ui.label(empty_text).classes('text-[11px] text-slate-500')
        return
    with ui.column().classes('w-full gap-2'):
        for event in changes:
            with ui.card().classes('w-full p-3 rounded-2xl border border-slate-200 bg-slate-50/60'):
                with ui.row().classes('w-full items-center justify-between gap-2 flex-wrap'):
                    ui.label(f"{event.get('actor_name') or 'Officer'} · "
                             f"{str(event.get('actor_role') or '').replace('_', ' ').title()}"
                             + (f" · Badge {event['actor_badge']}" if event.get('actor_badge') else '')).classes(
                        'text-[11px] font-black text-slate-900')
                    ui.label(_mon_fmt(event.get('timestamp'))).classes(
                        'text-[9px] text-slate-400 font-mono shrink-0')
                for diff in event.get('diffs') or []:
                    with ui.row().classes('w-full items-start gap-2 flex-wrap mt-1'):
                        ui.label(diff.get('label')).classes(
                            'text-[10px] font-black text-slate-600 min-w-40 uppercase tracking-wider')
                        ui.label(f"Previous: {diff.get('old') or '—'}").classes(
                            'text-[11px] text-rose-700 line-through decoration-rose-300')
                        ui.icon('arrow_right', size='xs').classes('text-slate-400 mt-0.5')
                        ui.label(f"Updated: {diff.get('new') or '—'}").classes('text-[11px] font-bold text-emerald-800')
                ui.label(
                    f"Reason: {event.get('reason') or 'No reason recorded'} · "
                    f"v{event.get('previous_version')} → v{event.get('new_version')}").classes(
                    'text-[10px] text-slate-500 mt-1')


def _render_modifications_and_hashes(record: Dict[str, Any]) -> None:
    """Audit trail with every recorded modification and the SHA-256 hash of each version."""
    versions = record.get('versions') or []
    chain = record.get('chain') or {}
    verification_events = record.get('verification_events') or []

    with ui.column().classes('w-full gap-4 mt-6'):
        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
                ui.icon('edit_document', size='sm').classes('text-indigo-800')
                ui.label('Modifications Made on This Case').classes(
                    'text-base font-bold text-slate-900 fantasy-title')
                ui.badge('Confidential audit view').classes(
                    'bg-red-50 text-red-700 border border-red-200 font-bold text-[10px] px-2 rounded-full')

            ui.label('Verification Officer actions').classes('text-[11px] font-black text-slate-700 mb-2')
            if verification_events:
                with ui.column().classes('w-full gap-1 mb-4'):
                    for event in verification_events:
                        with ui.row().classes('w-full items-start gap-3 text-[11px]'):
                            ui.label(vo_action_label(event.get('action'))).classes(
                                'font-black text-blue-900 min-w-56')
                            ui.label(str(event.get('remarks') or '—')).classes(
                                'text-slate-700 flex-1 whitespace-pre-line')
                            ui.label(
                                f"{event.get('actor_name') or '—'} · {_mon_fmt(event.get('created_at'))}").classes(
                                'text-[9px] text-slate-400 font-mono shrink-0')
            else:
                ui.label('No verification actions recorded for the source complaint.').classes(
                    'text-[11px] text-slate-500 mb-4')

            _render_change_diffs(record.get('verification_changes') or [],
                                 'No Verification Officer amendment of a registered FIR is recorded.')
            ui.separator().classes('my-4')
            ui.label('Police Officer amendments').classes('text-[11px] font-black text-slate-700 mb-2')
            _render_change_diffs(record.get('officer_changes') or [],
                                 'No police officer has amended the registered FIR details.')

        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
                ui.icon('key', size='sm').classes('text-slate-700')
                ui.label('Version History & SHA-256 Integrity').classes(
                    'text-base font-bold text-slate-900 fantasy-title')
                ui.badge('Authorized Officer only').classes(
                    'bg-slate-100 text-slate-700 border border-slate-200 font-bold text-[10px] px-2 rounded-full')
                ui.badge(str(chain.get('status') or 'CHECKING')).classes(
                    'bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-[10px] px-2 rounded-full'
                    if chain.get('chain_valid') else
                    'bg-rose-100 text-rose-900 border border-rose-300 font-bold text-[10px] px-2 rounded-full')

            if not versions:
                ui.label('No immutable versions have been recorded for this case.').classes(
                    'text-xs text-slate-500')
            else:
                with ui.column().classes('w-full gap-2'):
                    for version in versions:
                        with ui.card().classes(
                            'w-full p-3 rounded-2xl border border-slate-200 bg-slate-50/60 gap-1'):
                            with ui.row().classes('w-full items-center justify-between gap-2 flex-wrap'):
                                ui.label(
                                    f"Version {version.get('version_number')}"
                                    + (' — original' if version.get('version_number') == 1 else '')).classes(
                                    'text-xs font-black text-slate-900')
                                ui.label(_mon_fmt(version.get('created_at'))).classes(
                                    'text-[9px] text-slate-400 font-mono')
                            ui.label(
                                f"{version.get('creator_name') or 'Unknown'} · "
                                f"{str(version.get('creator_role') or '').replace('_', ' ').title() or '—'}"
                                + (f" · Badge {version['creator_badge']}" if version.get('creator_badge') else '')
                                + f" · Reason: {version.get('change_reason') or 'No reason recorded'}").classes(
                                'text-[10px] text-slate-600')
                            ui.label(
                                f"Previous hash: {version.get('previous_hash') or '— (initial version)'}").classes(
                                'text-[9px] text-slate-400 font-mono break-all')
                            ui.label(f"SHA-256: {version.get('current_hash') or '—'}").classes(
                                'text-[9px] text-indigo-800 font-mono break-all')

                ui.label(
                    f"{chain.get('message') or ''} · {len(versions)} version(s) recorded · "
                    f"latest v{versions[-1].get('version_number')}").classes('text-[10px] text-slate-500 mt-3')
                for issue in chain.get('issues') or []:
                    ui.label(f"⚠ {issue.get('message')}").classes('text-[10px] font-bold text-rose-700')


def _render_case_monitor(user: Dict[str, Any], fir_id: str,
                         detail: Dict[str, Any], state: Dict[str, str]) -> None:
    """Authorized case monitor body, re-rendered whenever the investigating officer publishes an update."""
    case = detail['case']
    record = detail.get('record') or {}

    with ui.column().classes('w-full gap-0'):
        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('w-full items-start justify-between flex-wrap gap-4'):
                with ui.column().classes('gap-1 flex-1 min-w-64'):
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        _mon_identity(case.get('fir_number'), case.get('citizen_name'),
                                      case.get('complaint_reference'))
                        fir_status_badge(case.get('status'))
                        ui.badge('DRAFT — not registered' if case.get('is_draft') else 'REGISTERED FIR').classes(
                            'bg-amber-100 text-amber-900 border border-amber-300 font-bold text-[10px] px-2 rounded-full'
                            if case.get('is_draft') else
                            'bg-emerald-100 text-emerald-900 border border-emerald-300 font-bold text-[10px] px-2 rounded-full')
                    ui.badge(case.get('stage_label') or 'Awaiting tracking').classes(
                        f"border font-bold text-[10px] px-2 py-0.5 rounded-full self-start "
                        f"{ADMIN_STAGE_COLOURS.get(case.get('current_stage'), 'bg-slate-100 text-slate-600 border-slate-200')}"
                    )
                with ui.grid().classes('w-full grid-cols-2 md:grid-cols-4 gap-4 mt-3'):
                    for label, value in [
                        ('Assigned Officer', case.get('officer_name') or 'Unassigned'),
                        ('Assignment Date', _mon_fmt(case.get('assigned_at'))),
                        ('Last Update', _mon_fmt(case.get('last_update_at'))),
                        ('Incident Location', case.get('incident_location') or '—'),
                    ]:
                        with ui.column().classes('gap-0.5'):
                            ui.label(label).classes('text-[10px] font-black text-slate-500 uppercase tracking-wider')
                            ui.label(str(value)).classes('text-xs font-bold text-slate-900')

        # ── Complete case record: origin, identity, registration ─
        _render_case_origin(record)

        # ── Instruction to the investigating officer ─────────
        with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                ui.icon('campaign', size='sm').classes('text-indigo-800')
                ui.label('Instruction to Investigating Officer').classes(
                    'text-base font-bold text-slate-900 fantasy-title')

            if not case.get('assigned_officer_id'):
                ui.label('Assign an investigating officer before sending case instructions.').classes(
                    'text-[11px] text-slate-500')
            else:
                with ui.row().classes('w-full items-end gap-3 flex-wrap'):
                    instruction = ui.textarea(
                        'Directed action, deadline or clarification…', value=state.get('text', '')).props(
                            'outlined rows=2').classes('flex-1 min-w-72 text-sm')
                    instruction.on(
                        'update:model-value', lambda event: state.__setitem__('text', event.args or ''))

                    def send_instruction() -> None:
                        try:
                            send_officer_instruction(fir_id, user, instruction.value or '')
                        except (ValueError, PermissionError) as exc:
                            ui.notify(str(exc), type='warning')
                            return
                        state['text'] = ''
                        instruction.value = ''
                        ui.notify(
                            f"Instruction delivered to {case.get('officer_name') or 'the assigned officer'}.",
                            type='positive')

                    ui.button('Send Instruction', icon='send', on_click=send_instruction).props(
                        'unelevated no-caps').classes('bg-indigo-800 text-white font-bold rounded-xl px-5 py-2.5 text-xs')
                ui.label(
                    'The officer receives this in their notification centre immediately, with the FIR number and citizen name.'
                ).classes('text-[10px] text-slate-400 mt-2')

        # ── Stage progress + full history ────────────────────
        with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                ui.icon('timeline', size='sm').classes('text-blue-800')
                ui.label('Complete Investigation Progress (authorized view)').classes(
                    'text-base font-bold text-slate-900 fantasy-title')

            if not detail['history']:
                ui.label('No stage updates recorded yet.').classes('text-xs text-slate-500')
            else:
                with ui.column().classes('w-full gap-2'):
                    for row in detail['history']:
                        stage_key = normalize_stage(row.get('new_stage'))
                        stage_label = OFFICER_STAGE_LABELS.get(stage_key) or STAGE_LABELS.get(stage_key, stage_key)
                        with ui.row().classes(
                            'w-full items-start gap-3 p-3 rounded-2xl border border-slate-200 bg-slate-50/60'):
                            with ui.column().classes('gap-0.5 min-w-56'):
                                ui.label(stage_label).classes('text-xs font-black text-blue-900')
                                ui.label(
                                    f"{ACTION_LABELS.get(row.get('action'), row.get('action') or 'STARTED').upper()}"
                                ).classes('text-[9px] font-bold text-slate-500 font-mono')
                            with ui.column().classes('gap-1 flex-1'):
                                ui.label(str(row.get('remarks') or '—')).classes('text-[11px] text-slate-700')
                                ui.label(
                                    f"Citizen sees: {row.get('public_note') or 'standard stage message'}").classes(
                                        'text-[10px] text-emerald-700')
                                ui.label(
                                    f"{row.get('updated_by_officer_name') or 'Officer'} · "
                                    f"Badge {row.get('updated_by_officer_badge') or 'N/A'}").classes(
                                        'text-[9px] text-slate-500')
                            ui.label(_mon_fmt(row.get('timestamp'))).classes(
                                'text-[9px] text-slate-400 font-mono shrink-0')

        # ── Modifications, audit trail and version hashes ────
        _render_modifications_and_hashes(record)

        # ── Internal notes and evidence ──────────────────────
        with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4 flex-wrap'):
                ui.icon('engineering', size='sm').classes('text-indigo-800')
                ui.label('Officer Notes & Collected Evidence').classes(
                    'text-base font-bold text-slate-900 fantasy-title')
                ui.badge('Confidential').classes(
                    'bg-red-50 text-red-700 border border-red-200 font-bold text-[10px] px-2 rounded-full')

            if not detail['entries']:
                ui.label('The investigating officer has not recorded notes or evidence yet.').classes(
                    'text-xs text-slate-500')
            else:
                with ui.column().classes('w-full gap-2'):
                    for entry in detail['entries']:
                        is_evidence = entry.get('entry_type') == 'EVIDENCE'
                        with ui.card().classes('w-full p-4 rounded-2xl border border-slate-200 bg-white shadow-xs'):
                            with ui.row().classes('w-full items-start justify-between gap-3 flex-wrap'):
                                with ui.row().classes('items-start gap-3 flex-1 min-w-64'):
                                    ui.icon('attachment' if is_evidence else 'sticky_note2', size='sm').classes(
                                        'text-indigo-700')
                                    with ui.column().classes('gap-1'):
                                        ui.label(entry.get('title') or '—').classes(
                                            'text-sm font-black text-slate-900')
                                        ui.label(str(entry.get('description') or '')).classes(
                                            'text-xs text-slate-700 leading-relaxed whitespace-pre-line')
                                        if is_evidence:
                                            ui.label(
                                                f"Collected: {_mon_fmt(entry.get('collected_at'))} · "
                                                f"Status: {str(entry.get('evidence_status') or '').replace('_', ' ') or '—'}"
                                            ).classes('text-[10px] text-slate-500')
                                        if entry.get('sha256'):
                                            ui.label(f"SHA-256 {str(entry['sha256'])[:32]}…").classes(
                                                'text-[9px] text-slate-400 font-mono')
                                with ui.column().classes('gap-1 items-end shrink-0'):
                                    ui.label(entry.get('officer_name') or '—').classes(
                                        'text-[10px] font-bold text-slate-600')
                                    ui.label(_mon_fmt(entry.get('created_at'))).classes(
                                        'text-[9px] text-slate-400 font-mono')
                                    if entry.get('file_name'):
                                        def open_entry(item=entry):
                                            try:
                                                loaded = get_evidence_file(item['id'], user)
                                            except PermissionError:
                                                loaded = None
                                            if not loaded:
                                                ui.notify('This evidence file is no longer available.', type='warning')
                                                return
                                            _mon_open_file(loaded[0], loaded[1], loaded[2])

                                        ui.button('Open File', icon='visibility', on_click=open_entry).props(
                                            'outline dense size=sm no-caps').classes(
                                                'text-indigo-800 font-bold border-indigo-300')

        # ── Documents filed by the complainant ───────────────
        with ui.card().classes('w-full mt-6 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
            with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                ui.icon('folder_zip', size='sm').classes('text-emerald-700')
                ui.label('Citizen-Supplied Documents').classes('text-base font-bold text-slate-900 fantasy-title')
                ui.badge(f"{case.get('complaint_reference') or 'No complaint record'}").classes(
                    'bg-slate-100 text-slate-600 font-bold text-[10px] px-2 rounded-full font-mono')

            complaint_row = get_complaint_by_id(case['complaint_id'], actor_user=user) if case.get('complaint_id') else None
            complaint_files = json.loads((complaint_row or {}).get('evidence_files') or '[]')
            complaint_files = [item for item in complaint_files if isinstance(item, dict)]
            if not complaint_files:
                ui.label('The complainant has not filed any supporting documents.').classes('text-xs text-slate-500')
            else:
                with ui.column().classes('w-full gap-2'):
                    for item in complaint_files:
                        with ui.row().classes(
                            'w-full items-center justify-between gap-3 p-3 rounded-xl '
                            'border border-slate-200 bg-slate-50/60'):
                            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                                ui.label(item.get('name') or 'Attachment').classes(
                                    'text-xs font-black text-slate-900 truncate')
                                if item.get('stage') == 'CITIZEN_ADDITIONAL':
                                    ui.label(
                                        f"Added during investigation by {item.get('uploaded_by') or 'complainant'} · "
                                        f"{_mon_fmt(item.get('uploaded_at'))}"
                                        + (f" · {item.get('caption')}" if item.get('caption') else '')
                                    ).classes('text-[10px] font-bold text-emerald-700')
                                else:
                                    ui.label(
                                        f"Filed with the complaint · {int(item.get('size') or 0) // 1024} KB").classes(
                                            'text-[10px] text-slate-500')
                            def open_citizen_file(entry=item, cid=case.get('complaint_id')):
                                data = evidence_bytes(cid, entry.get('stored_name') or '')
                                if not data:
                                    ui.notify('The stored file is no longer available.', type='warning')
                                    return
                                _mon_open_file(data, entry.get('name') or 'file',
                                               entry.get('content_type') or 'application/octet-stream')

                            ui.button('View', icon='visibility', on_click=open_citizen_file).props(
                                'outline dense size=sm no-caps').classes('text-emerald-800 font-bold border-emerald-300')

        # ── Generated FIR documents, current and past versions ─
        _render_case_documents(user, record)

        # ── Reassignment trail and milestone credits ─────────
        with ui.row().classes('w-full gap-4 flex-wrap items-start mt-6'):
            with ui.card().classes('flex-1 min-w-80 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                    ui.icon('swap_horiz', size='sm').classes('text-blue-800')
                    ui.label('Reassignment History').classes('text-base font-bold text-slate-900 fantasy-title')

                if not detail['assignments']:
                    ui.label('No assignment records for this case.').classes('text-xs text-slate-500')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for row in detail['assignments']:
                            with ui.row().classes(
                                'w-full items-center justify-between gap-3 p-3 rounded-xl border border-slate-200 bg-slate-50/60'):
                                with ui.column().classes('gap-0.5 flex-1'):
                                    ui.label(f"Officer: {row.get('officer_name') or 'Unknown'}").classes(
                                        'text-xs font-black text-slate-900')
                                    ui.label(
                                        f"By {row.get('assigned_by_name') or 'Verification Officer'}").classes(
                                            'text-[10px] text-slate-500')
                                with ui.column().classes('gap-0.5 items-end'):
                                    ui.label(_mon_fmt(row.get('assigned_at'))).classes(
                                        'text-[10px] text-slate-500 font-mono')
                                    if row.get('unassigned_at'):
                                        ui.label(
                                            f"Reassigned {_mon_fmt(row.get('unassigned_at'))}").classes(
                                                'text-[9px] text-rose-600 font-mono')
                                    else:
                                        ui.badge('CURRENT').classes(
                                            'bg-emerald-100 text-emerald-800 font-bold text-[9px] px-1.5 rounded')

            with ui.card().classes('flex-1 min-w-80 p-6 bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('items-center gap-2 pb-3 border-b border-slate-100 mb-4'):
                    ui.icon('military_tech', size='sm').classes('text-amber-600')
                    ui.label('Milestones Completed').classes('text-base font-bold text-slate-900 fantasy-title')

                if not detail['credits']:
                    ui.label('No verified milestones credited on this case yet.').classes('text-xs text-slate-500')
                else:
                    with ui.column().classes('w-full gap-2'):
                        for row in detail['credits']:
                            with ui.row().classes(
                                'w-full items-center justify-between gap-3 p-3 rounded-xl border border-slate-200 bg-slate-50/60'):
                                with ui.column().classes('gap-0.5 flex-1'):
                                    ui.label(str(row.get('milestone') or '').replace('_', ' ').title()).classes(
                                        'text-xs font-black text-slate-900')
                                    ui.label(
                                        f"{row.get('officer_name') or 'Officer'} · "
                                        f"FIR No: {case.get('fir_number')} · Citizen: {case.get('citizen_name') or 'Not recorded'}"
                                    ).classes('text-[10px] text-slate-500')
                                with ui.column().classes('items-end gap-0.5'):
                                    ui.badge(f"+{row.get('points')}").classes(
                                        'bg-amber-100 text-amber-900 font-bold text-[10px] px-2 rounded-full')
                                    ui.label(_mon_fmt(row.get('awarded_at'))).classes(
                                        'text-[9px] text-slate-400 font-mono')

        ui.label(
            'Confidential officer records are never shown to the citizen; they see only the public stage wording above.'
        ).classes('text-[10px] text-slate-400 mt-4')


@ui.page('/admin/investigations/{fir_id}')
def admin_investigation_detail_page(fir_id: str) -> None:
    """Complete authorized progress, internal records and reassignment trail for one case."""
    user = require_admin_user()
    if not user:
        return

    try:
        detail = get_admin_case_detail(fir_id, user)
    except (PermissionError, ValueError) as exc:
        with portal_page('admin', '/admin/investigations', 'Case Monitor Unavailable', ''):
            ui.label(str(exc)).classes('text-sm font-bold text-rose-700')
            ui.button('Back to Investigation Monitor', on_click=lambda: ui.navigate.to('/admin/investigations')).props(
                'flat no-caps').classes('text-indigo-700 font-bold text-xs mt-3')
        return

    case = detail['case']
    draft: Dict[str, str] = {'text': ''}

    with portal_page(
        'admin', '/admin/investigations',
        f"Case Monitor · {case.get('fir_number')}",
        f"Officer {case.get('officer_name') or 'unassigned'} · Citizen {case.get('citizen_name') or 'not recorded'}",
    ):
        ui.button('← Back to Investigation Monitor', icon='arrow_back',
                  on_click=lambda: ui.navigate.to('/admin/investigations')).props(
            'flat no-caps').classes('text-slate-600 font-bold text-xs')

        @ui.refreshable
        def case_view() -> None:
            try:
                live = get_admin_case_detail(fir_id, user)
            except (PermissionError, ValueError) as exc:
                ui.label(f'Case monitor unavailable: {exc}').classes('text-sm font-bold text-rose-700')
                return
            _render_case_monitor(user, fir_id, live, draft)

        case_view()
        _mon_listen(case_view)
        ui.timer(25, case_view.refresh)


@ui.page('/admin/profile')
def admin_profile_page() -> None:
    """Administrator identity record and permitted contact details."""
    user = require_admin_user()
    if not user:
        return

    with portal_page(
        'admin', '/admin/profile', 'Administrator Profile',
        'Official credentials and permitted contact details. Authentication secrets are never displayed.',
    ):
        with ui.card().classes('w-full max-w-4xl mx-auto p-8 rounded-3xl paper-card bg-white border border-slate-200 shadow-md'):
            with ui.row().classes('items-center gap-6 mb-6 pb-6 border-b border-slate-200 flex-wrap'):
                with ui.element('div').classes(
                    'w-20 h-20 rounded-full flex items-center justify-center '
                    'bg-gradient-to-br from-indigo-800 to-slate-900 text-white shadow-md'
                ):
                    ui.icon('admin_panel_settings', size='lg')
                with ui.column().classes('gap-1 flex-1'):
                    ui.label(f"{user.get('rank') or 'Administrator'} {user.get('name', 'Supervisor')}").classes(
                        'text-3xl font-black text-slate-900 fantasy-title')
                    ui.label(
                        f"@{user.get('username') or user.get('name', '').lower().replace(' ', '')} · "
                        f"{user.get('role', 'ADMIN')}").classes('text-xs font-bold text-indigo-800 font-mono')
                    ui.badge(user.get('status') or 'UNKNOWN').classes(
                        'bg-indigo-100 text-indigo-900 border border-indigo-300 font-bold text-[10px] px-2 w-fit')

            with ui.column().classes('w-full gap-0'):
                for label, value, icon in [
                    ('Administrator Full Name', user.get('name') or 'Not recorded', 'person'),
                    ('Login Username', user.get('username') or 'Not recorded', 'account_circle'),
                    ('System Role', user.get('role') or 'ADMIN', 'verified_user'),
                    ('Department / Unit', user.get('station') or 'Not recorded', 'apartment'),
                    ('District', user.get('district') or 'Not recorded', 'location_city'),
                    ('Badge Identification No.', user.get('badge_number') or 'Not recorded', 'badge'),
                    ('Registered Mobile', user.get('phone') or 'Not recorded', 'phone'),
                    ('Email Address', user.get('email') or 'Not recorded', 'email'),
                    ('Account Status', user.get('status') or 'Not recorded', 'shield'),
                    ('Account Created', user.get('created_at') or 'Not recorded', 'event'),
                ]:
                    with ui.row().classes(
                        'w-full justify-between p-4 rounded-xl bg-slate-50 border border-slate-200 items-center gap-3 flex-wrap'
                    ):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon(icon, size='xs').classes('text-indigo-800')
                            ui.label(label).classes('font-bold text-slate-600 text-xs')
                        ui.label(str(value)).classes('font-bold text-slate-900 text-sm break-words')

        with ui.card().classes('w-full max-w-4xl mx-auto p-8 rounded-3xl bg-white border border-slate-200 shadow-md'):
            with ui.row().classes('items-center gap-2 mb-3 pb-2 border-b border-slate-100'):
                ui.icon('edit', size='sm').classes('text-indigo-800')
                ui.label('Update Permitted Contact Details').classes('text-lg font-bold text-slate-900 fantasy-title')
            ui.label(
                'Only contact and posting fields may be changed here. Name, role, badge, username and '
                'authentication credentials are managed by system administration.'
            ).classes('text-[11px] text-slate-500 mb-4')

            phone_input = ui.input('Registered Mobile', value=user.get('phone') or '').props('outlined').classes('w-full')
            station_input = ui.input('Department / Unit', value=user.get('station') or '').props('outlined').classes('w-full')
            district_input = ui.input('District', value=user.get('district') or '').props('outlined').classes('w-full')
            address_input = ui.textarea('Address', value=user.get('address') or '').props('outlined rows=2').classes('w-full')

            def save_profile() -> None:
                try:
                    updated = update_staff_profile(
                        user['id'],
                        phone=phone_input.value,
                        station=station_input.value,
                        district=district_input.value,
                        address=address_input.value,
                    )
                except (PermissionError, ValueError) as exc:
                    ui.notify(str(exc), type='warning')
                    return
                except Exception as exc:                                # noqa: BLE001
                    ui.notify(f'Profile update failed: {exc}', type='negative')
                    return
                set_current_user(updated)
                ui.notify('Profile details updated.', type='positive')
                ui.navigate.to('/admin/profile')

            ui.button('Save Profile Changes', icon='save', on_click=save_profile).props(
                'unelevated'
            ).classes('bg-indigo-800 hover:bg-indigo-900 text-white font-bold rounded-xl px-5 py-2.5 text-xs mt-2')


# ==========================================
# 8. AUTHORIZED OFFICER NOTIFICATION CENTRE
# ==========================================

ADMIN_EVENT_LABELS = {
    'CITIZEN_REGISTRATION': ('Citizen registrations', 'how_to_reg'),
    'CITIZEN_VERIFICATION': ('Registration decisions', 'verified_user'),
    'CITIZEN_CREDENTIALS': ('Citizen accounts', 'badge'),
    'COMPLAINT_SUBMISSION': ('Complaint submissions', 'inbox'),
    'COMPLAINT_SUBMITTED': ('Complaint submissions', 'inbox'),
    'FIR_SUBMISSION': ('FIR submissions', 'description'),
    'NEW_FIR': ('FIR submissions', 'description'),
    'FIR_REGISTERED': ('FIR registrations', 'gavel'),
    'FIR_VERIFIED': ('FIR verification', 'fact_check'),
    'FIR_REJECTED': ('FIR returned for correction', 'report_gmailerrorred'),
    'FIR_UPDATE': ('FIR modifications', 'edit_document'),
    'FIR_DOCUMENT': ('FIR documents', 'picture_as_pdf'),
    'OFFICER_ASSIGNMENT': ('Officer assignments', 'assignment_ind'),
    'OFFICER_ASSIGNED': ('Officer assignments', 'assignment_ind'),
    'INVESTIGATION_UPDATE': ('Investigation updates', 'manage_search'),
    'CASE_STAGE_UPDATE': ('Case tracking', 'track_changes'),
    'AUDIT_ALERT': ('Audit records', 'policy'),
    'SECURITY_ALERT': ('Integrity alerts', 'gpp_bad'),
    'ADMIN_INSTRUCTION': ('Instructions issued', 'campaign'),
    'OFFICER_CREDIT': ('Officer credits', 'military_tech'),
    'CHAT_MESSAGE': ('Citizen chat', 'chat'),
}


@ui.page('/admin/notifications')
def admin_notifications_page() -> None:
    """Authorized Officer inbox: every registered database event addressed to this account."""
    user = require_admin_user()
    if not user:
        return

    with portal_page(
        'admin', '/admin/notifications', 'Notification Centre',
        'Registrations, complaints, FIR actions, assignments, investigation updates and audit records.',
    ):
        filter_value = {'category': 'ALL'}

        @ui.refreshable
        def inbox() -> None:
            notifications = get_user_notifications(user['id'], limit=200)
            unread = get_unread_count(user['id'])

            categories = []
            for notification in notifications:
                label = ADMIN_EVENT_LABELS.get(notification.get('type'), (None, None))[0]
                if label and label not in categories:
                    categories.append(label)
            if filter_value['category'] != 'ALL':
                notifications = [
                    n for n in notifications
                    if ADMIN_EVENT_LABELS.get(n.get('type'), (None, None))[0] == filter_value['category']
                ]

            with ui.card().classes(
                'w-full p-5 rounded-2xl bg-white border border-slate-200 shadow-sm'
            ):
                with ui.row().classes(
                    'w-full items-center justify-between flex-wrap gap-3 pb-3 border-b border-slate-200'
                ):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('notifications_active', size='md').classes('text-indigo-800')
                        ui.label('Authorized Officer Alerts').classes(
                            'text-xl font-black text-slate-900 fantasy-title')
                        if unread:
                            ui.badge(f'{unread} Unread').classes(
                                'bg-amber-500 text-slate-950 font-bold text-xs px-2.5 py-0.5 rounded-full')
                    with ui.row().classes('items-center gap-2 flex-wrap'):
                        ui.select(
                            ['ALL'] + categories,
                            value=filter_value['category'],
                            on_change=lambda e: (filter_value.update({'category': e.value or 'ALL'}),
                                                 inbox.refresh()),
                        ).props('outlined dense options-dense label=Category').classes('w-52')
                        if notifications:
                            def read_all() -> None:
                                mark_all_read(user['id'])
                                ui.notify('All notifications marked as read.', type='positive')
                                inbox.refresh()

                            ui.button('Mark All Read', icon='done_all', on_click=read_all).props(
                                'outline size=sm'
                            ).classes('text-indigo-800 font-bold rounded-xl')

                ui.label(
                    f'{len(notifications)} event(s) stored for this account. '
                    'Alerts are written to the notifications table by the same service the '
                    'header bell uses, so both views always agree.'
                ).classes('text-[11px] text-slate-500 mt-2')

            if not notifications:
                with ui.column().classes('w-full items-center py-16 gap-3 text-center'):
                    ui.icon('notifications_none', size='xl').classes('text-slate-300')
                    ui.label('No notifications received yet.').classes(
                        'text-base font-bold text-slate-700')
                    ui.label(
                        'Registrations, complaint submissions, FIR actions and audit records '
                        'will appear here the moment they are stored.'
                    ).classes('text-xs text-slate-500 max-w-md')
                return

            with ui.column().classes('w-full gap-3 mt-4'):
                for notification in notifications:
                    is_read = notification.get('is_read', 0) == 1
                    label, icon = ADMIN_EVENT_LABELS.get(
                        notification.get('type'), ('System update', 'notifications'))
                    severity = str(notification.get('severity') or 'INFO').upper()
                    accent = {
                        'SUCCESS': 'border-l-emerald-500',
                        'WARNING': 'border-l-amber-500',
                        'ALERT': 'border-l-red-500',
                        'ERROR': 'border-l-red-500',
                    }.get(severity, 'border-l-indigo-500')
                    with ui.card().classes(
                        f'w-full p-4 rounded-2xl border border-slate-200 border-l-4 {accent} '
                        f'shadow-xs {"bg-white" if not is_read else "bg-slate-50 opacity-80"}'
                    ):
                        with ui.row().classes('w-full items-start gap-3'):
                            ui.icon(icon if not is_read else 'mail', size='sm').classes(
                                'text-indigo-800 mt-1')
                            with ui.column().classes('gap-1 flex-1'):
                                with ui.row().classes(
                                    'w-full items-center justify-between flex-wrap gap-2'
                                ):
                                    ui.label(notification.get('title') or 'Notification').classes(
                                        'text-sm font-black text-slate-900')
                                    ui.label(_mon_fmt(notification.get('created_at'))).classes(
                                        'text-[10px] text-slate-400 font-mono')
                                ui.label(notification.get('message') or '').classes(
                                    'text-xs text-slate-700 whitespace-pre-line leading-relaxed')
                                with ui.row().classes('items-center gap-2 flex-wrap mt-1'):
                                    ui.badge(label).classes(
                                        'bg-indigo-50 text-indigo-800 border border-indigo-200 '
                                        'font-bold text-[10px] px-2')
                                    fir_number = notification.get('fir_number')
                                    fir_target = notification.get('case_fir_id') or notification.get('fir_id')
                                    if fir_number and fir_target:
                                        ui.button(
                                            f'Open FIR {fir_number}', icon='folder_special',
                                            on_click=lambda t=fir_target: ui.navigate.to(
                                                f'/admin/investigations/{t}'),
                                        ).props('flat dense no-caps size=xs').classes(
                                            'text-blue-800 font-bold text-[10px]')
                                    elif notification.get('complaint_reference'):
                                        ui.label(
                                            f"Complaint {notification.get('complaint_reference')}"
                                        ).classes('text-[10px] font-bold text-slate-500 font-mono')
                                    if not is_read:
                                        def mark_one(nid=notification['id']) -> None:
                                            mark_notification_read(nid, user['id'])
                                            inbox.refresh()

                                        ui.button('Mark as Read', icon='done', on_click=mark_one).props(
                                            'flat dense no-caps size=xs'
                                        ).classes('text-indigo-800 font-bold text-[10px]')

        inbox()
        _mon_listen(inbox)
        ui.timer(25.0, inbox.refresh)


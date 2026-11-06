"""
Live FIR Tracking Timeline Component.
Shared between Citizen and Main Officer portals.
Features:
- 10-Stage connected visual progression
- Real-time live synchronization without page reload
- Cryptographic security monitoring & mischievous activity alerts
- Main Officer stage controls & alert resolution
"""

from datetime import datetime
from typing import Any, Callable, Dict, Optional
from nicegui import ui

from frontend.components.badges import fir_status_badge
from backend.services.case_tracking_service import (
    CASE_STAGES,
    STAGE_LABELS,
    get_fir_complete_tracking,
    update_case_stage,
    create_security_alert,
    resolve_security_alert
)


def render_live_fir_timeline(
    fir_id: str,
    actor_user: Dict[str, Any],
    is_officer: bool = False,
    on_change_callback: Optional[Callable[[], None]] = None
) -> None:
    """
    Render the complete 10-stage Live FIR Tracking Timeline with Security Monitoring.
    Automatically polls and synchronizes in real time without refreshing the page.
    """
    container = ui.column().classes('w-full gap-6')
    last_state_ref = {'stage': None, 'timestamp': None, 'alerts_count': 0}

    def render_content():
        try:
            tracking_data = get_fir_complete_tracking(fir_id, actor_user)
        except PermissionError:
            tracking_data = {}
        if not tracking_data:
            with container:
                ui.label('FIR tracking data could not be found or access is restricted.').classes('text-red-600 font-bold p-4')
            return

        container.clear()

        # Update last known state
        last_state_ref['stage'] = tracking_data.get('current_stage_key')
        last_state_ref['timestamp'] = (tracking_data.get('last_tracking_event_at')
                                       or tracking_data.get('last_updated_at'))
        last_state_ref['alerts_count'] = len(tracking_data.get('security_status', {}).get('alerts', []))

        stages = tracking_data.get('stages', [])
        sec_status = tracking_data.get('security_status', {})
        cur_label = tracking_data.get('current_stage_label', 'In Progress')
        cur_idx = tracking_data.get('current_stage_index', 1)
        total_st = tracking_data.get('total_stages', 10)

        with container:
            # ── 1. Top Case Overview & Real-Time Pulse Card ──────────────────────────
            with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-4 pb-4 border-b border-slate-200'):
                    with ui.row().classes('items-center gap-3'):
                        with ui.element('div').classes('w-12 h-12 rounded-2xl flex items-center justify-center bg-indigo-50 text-indigo-700 border border-indigo-200 shadow-xs'):
                            ui.icon('track_changes', size='md')
                        with ui.column().classes('gap-0.5'):
                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                ui.label(f"FIR Number: {tracking_data.get('fir_number', '—')}").classes('text-2xl font-black text-slate-900 font-mono')
                                fir_status_badge(tracking_data.get('status', 'SUBMITTED'))
                            ui.label(f"Tracking Ref: {tracking_data.get('reference_number', '—')} · Complainant: {tracking_data.get('citizen_name', 'Citizen')}").classes('text-xs text-slate-600')

                    with ui.row().classes('items-center gap-3'):
                        # Live indicator
                        with ui.row().classes('items-center gap-1.5 px-3 py-1 bg-emerald-50 text-emerald-800 border border-emerald-300 rounded-full text-xs font-bold'):
                            with ui.element('div').classes('w-2 h-2 rounded-full bg-emerald-600 animate-ping'):
                                pass
                            ui.label('LIVE TRACKING ACTIVE')

                        completed_st = sum(1 for s in stages if s.get('status') == 'COMPLETED')
                        skipped_st = sum(1 for s in stages if s.get('status') == 'SKIPPED')
                        with ui.column().classes('gap-1 items-end'):
                            ui.badge(f"Stage {cur_idx} of {total_st}").classes('bg-indigo-100 text-indigo-900 border border-indigo-300 font-bold text-xs px-3 py-1 rounded-full')
                            note = f"{completed_st} stage(s) recorded"
                            if skipped_st:
                                note += f" · {skipped_st} not applicable"
                            ui.label(note).classes('text-[10px] text-slate-500')

                # Current Stage Highlight Banner
                with ui.row().classes('w-full mt-4 p-4 rounded-2xl bg-gradient-to-r from-blue-50 via-indigo-50 to-purple-50 border border-blue-200 items-center justify-between flex-wrap gap-3'):
                    with ui.column().classes('gap-1'):
                        ui.label('CURRENT ACTIVE STAGE').classes('text-[10px] font-black tracking-wider text-indigo-800 uppercase')
                        ui.label(cur_label).classes('text-xl font-black text-slate-900')
                    with ui.column().classes('gap-1 text-right'):
                        ui.label('LAST SYNCHRONIZED').classes('text-[10px] font-bold text-slate-500 uppercase')
                        ts = str(tracking_data.get('last_updated_at', ''))[:19].replace('T', ' ')
                        ui.label(ts or 'Just now').classes('text-xs font-mono font-bold text-slate-700')

            # ── 2. Security Monitoring Section (Officers ONLY — never shown to citizens) ───
            if is_officer:
                sec_color = sec_status.get('color', 'green')
                color_classes = {
                    'green': ('bg-emerald-50/70 border-emerald-300', 'text-emerald-800', 'shield', 'bg-emerald-600 text-white'),
                    'red': ('bg-red-50/90 border-red-400 animate-pulse', 'text-red-900', 'gpp_bad', 'bg-red-600 text-white'),
                    'orange': ('bg-amber-50 border-amber-300', 'text-amber-900', 'security_update_warning', 'bg-amber-600 text-white'),
                    'grey': ('bg-slate-50 border-slate-300', 'text-slate-800', 'help_outline', 'bg-slate-600 text-white')
                }
                card_cls_sec, text_cls, sec_icon, icon_badge = color_classes.get(sec_color, color_classes['grey'])

                with ui.card().classes(f'w-full p-6 rounded-3xl border shadow-sm {card_cls_sec}'):
                    with ui.row().classes('w-full items-start justify-between flex-wrap gap-3'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes(f'w-10 h-10 rounded-xl flex items-center justify-center shadow-xs {icon_badge}'):
                                ui.icon(sec_icon, size='sm')
                            with ui.column().classes('gap-0'):
                                ui.label('Security Monitoring & Cryptographic Integrity').classes('text-lg font-bold text-slate-900 fantasy-title')
                                ui.label(sec_status.get('summary', '')).classes(f'text-xs font-semibold {text_cls} mt-0.5')
                                ui.badge('OFFICER VIEW ONLY — NOT VISIBLE TO CITIZEN').classes('bg-slate-900 text-amber-300 font-bold text-[9px] px-2 py-0.5 rounded mt-1')

                        with ui.row().classes('items-center gap-2'):
                            ui.badge(sec_status.get('badge_text', 'STATUS: UNKNOWN')).classes(f'{icon_badge} font-bold text-xs px-3 py-1 rounded-full')
                            # Main Officer Security Alert Button
                            def trigger_test_alert():
                                try:
                                    create_security_alert(
                                        fir_id=fir_id,
                                        reason="Discrepancy detected during supervisor routine integrity check.",
                                        severity="CRITICAL",
                                        responsible_account=f"{actor_user.get('rank') or 'Officer'} {actor_user.get('name')}",
                                        actor_user=actor_user
                                    )
                                    ui.notify('🚨 Security Alert generated and logged to database!', type='warning')
                                    render_content()
                                except Exception as e:
                                    ui.notify(f"Alert error: {str(e)}", type='negative')

                            ui.button('Log Security Threat 🚨', icon='warning', on_click=trigger_test_alert).props('unelevated size=xs').classes('bg-red-700 hover:bg-red-800 text-white font-bold rounded-lg px-3 py-1.5 shadow-xs')

                    # Security alerts history (officer only)
                    alerts = sec_status.get('alerts', [])
                    if alerts:
                        with ui.column().classes('w-full gap-2 mt-4 pt-3 border-t border-slate-200/60'):
                            ui.label('Recorded Security Events & Mischief Audit Trail:').classes('text-xs font-bold text-slate-700 uppercase tracking-wider')
                            for alert in alerts:
                                is_pending = (alert.get('status') == 'PENDING_INVESTIGATION')
                                is_crit = (alert.get('severity') == 'CRITICAL')
                                al_bg = 'bg-red-100/80 border-red-300' if (is_pending and is_crit) else ('bg-amber-100/80 border-amber-300' if is_pending else 'bg-white border-slate-200')
                                
                                with ui.card().classes(f'w-full p-4 rounded-xl border {al_bg} shadow-xs'):
                                    with ui.row().classes('w-full items-start justify-between flex-wrap gap-2'):
                                        with ui.column().classes('gap-0.5 flex-1'):
                                            with ui.row().classes('items-center gap-2 flex-wrap'):
                                                ui.badge(alert.get('alert_type', 'SECURITY_ALERT').replace('_', ' ')).classes('bg-slate-900 text-white font-mono text-[9px] px-2 py-0.5 rounded')
                                                ui.label(f"Alert ID: {alert.get('alert_id', '—')}").classes('font-bold text-slate-900 text-xs font-mono')
                                                if is_pending:
                                                    ui.badge('PENDING INVESTIGATION').classes('bg-red-600 text-white font-bold text-[9px] px-2 py-0.5 rounded')
                                                else:
                                                    ui.badge('RESOLVED').classes('bg-emerald-600 text-white font-bold text-[9px] px-2 py-0.5 rounded')
                                            ui.label(f"Reason: {alert.get('reason')}").classes('text-xs text-slate-800 font-semibold mt-1')
                                            ui.label(f"Actor: {alert.get('responsible_account', 'Unknown')} · {str(alert.get('created_at'))[:19].replace('T', ' ')}").classes('text-[10px] text-slate-500 font-mono mt-0.5')
                                            if alert.get('resolution_notes'):
                                                ui.label(f"Resolution: {alert.get('resolution_notes')} (By: {alert.get('resolved_by_name', 'Officer')})").classes('text-xs text-emerald-800 font-medium mt-1 italic')

                                        # Officer can resolve pending alerts
                                        if is_pending:
                                            def open_resolve_dialog(al_obj=alert):
                                                with ui.dialog() as dlg, ui.card().classes('w-96 p-5 rounded-2xl'):
                                                    ui.label('Resolve Security Alert').classes('text-lg font-bold text-slate-900')
                                                    ui.label(f"Alert: {al_obj.get('alert_id')}").classes('text-xs text-slate-500 font-mono mb-2')
                                                    res_input = ui.textarea('Resolution Notes *', placeholder='Describe inquiry results and corrective actions taken...').classes('w-full').props('outlined dense rows=3')
                                                    
                                                    def do_resolve():
                                                        if not res_input.value.strip():
                                                            ui.notify('Please enter resolution notes', type='warning')
                                                            return
                                                        resolve_security_alert(al_obj['id'], actor_user, res_input.value.strip())
                                                        ui.notify('✓ Security alert resolved!', type='positive')
                                                        dlg.close()
                                                        render_content()

                                                    with ui.row().classes('w-full justify-end gap-2 mt-3'):
                                                        ui.button('Cancel', on_click=dlg.close).props('flat')
                                                        ui.button('Confirm Resolution ✓', on_click=do_resolve).props('unelevated').classes('bg-emerald-700 text-white font-bold text-xs rounded-xl')
                                                dlg.open()

                                            ui.button('Investigate & Resolve', icon='check', on_click=lambda al=alert: open_resolve_dialog(al)).props('unelevated size=xs').classes('bg-slate-900 text-white font-bold rounded-lg px-3 py-1.5')

            # ── 3. 10-Stage Connected Timeline ───────────────────────────────────────
            with ui.card().classes('w-full p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm'):
                with ui.row().classes('w-full items-center justify-between mb-6 pb-3 border-b border-slate-200'):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('timeline', size='md').classes('text-indigo-700')
                        with ui.column().classes('gap-0'):
                            ui.label('Official 10-Stage FIR Tracking Timeline').classes('text-xl font-black text-slate-900 fantasy-title')
                            ui.label('Continuous chronological milestone progress and investigative case lifecycle.').classes('text-xs text-slate-500')

                    # Legend
                    with ui.row().classes('items-center gap-3 text-xs font-bold text-slate-600 flex-wrap'):
                        with ui.row().classes('items-center gap-1'):
                            ui.element('div').classes('w-3 h-3 rounded-full bg-emerald-500')
                            ui.label('Completed')
                        with ui.row().classes('items-center gap-1'):
                            ui.element('div').classes('w-3 h-3 rounded-full bg-blue-600 animate-pulse')
                            ui.label('Active Stage')
                        with ui.row().classes('items-center gap-1'):
                            ui.element('div').classes('w-3 h-3 rounded-full bg-slate-300')
                            ui.label('Upcoming')
                        with ui.row().classes('items-center gap-1'):
                            ui.element('div').classes('w-3 h-3 rounded-full bg-red-500')
                            ui.label('Alert / Threat')

                # Timeline Steps List
                with ui.element('div').classes('w-full flex flex-col gap-0 relative'):
                    for i, st_item in enumerate(stages):
                        is_last = (i == len(stages) - 1)
                        st_color = st_item.get('color', 'grey')
                        st_status = st_item.get('status', 'UPCOMING')
                        num = st_item.get('number', i + 1)
                        alerts_for_st = st_item.get('alerts', [])

                        # Color styles
                        circle_colors = {
                            'green': 'bg-emerald-600 text-white shadow-emerald-200 shadow-md ring-4 ring-emerald-50',
                            'blue': 'bg-blue-600 text-white shadow-blue-300 shadow-lg ring-4 ring-blue-100 animate-pulse',
                            'grey': 'bg-slate-200 text-slate-500',
                            'red': 'bg-red-600 text-white shadow-red-200 shadow-md ring-4 ring-red-100 animate-bounce',
                            'orange': 'bg-amber-500 text-white shadow-amber-200 shadow-md ring-4 ring-amber-100'
                        }
                        c_cls = circle_colors.get(st_color, circle_colors['grey'])

                        card_border_colors = {
                            'green': 'border-emerald-200 bg-emerald-50/30',
                            'blue': 'border-blue-300 bg-blue-50/50 shadow-sm',
                            'grey': 'border-slate-200 bg-slate-50/50 opacity-80',
                            'red': 'border-red-400 bg-red-50',
                            'orange': 'border-amber-300 bg-amber-50'
                        }
                        card_cls = card_border_colors.get(st_color, card_border_colors['grey'])

                        status_badge_config = {
                            'COMPLETED': ('bg-emerald-100 text-emerald-900 border-emerald-300', '✓ Completed'),
                            'CURRENT': ('bg-blue-100 text-blue-900 border-blue-300', '⏳ Current Stage'),
                            'UPCOMING': ('bg-slate-100 text-slate-600 border-slate-300', '○ Upcoming'),
                            'SKIPPED': ('bg-slate-100 text-slate-500 border-slate-200', '— Not applicable'),
                            'ALERT': ('bg-red-100 text-red-900 border-red-400 font-black', '🚨 Security Alert'),
                            'WARNING': ('bg-amber-100 text-amber-900 border-amber-300 font-black', '⚠️ Action Required')
                        }
                        badge_style, badge_label = status_badge_config.get(st_status, ('bg-slate-100 text-slate-600', st_status))

                        with ui.row().classes('w-full items-start gap-4 mb-4 relative'):
                            # Left: Step Number Circle
                            with ui.element('div').classes(f'w-10 h-10 rounded-full flex items-center justify-center font-black text-sm shrink-0 z-10 {c_cls}'):
                                if st_color == 'green':
                                    ui.icon('check', size='xs')
                                else:
                                    ui.label(str(num))

                            # Connector line to next stage
                            if not is_last:
                                line_color = 'bg-emerald-400' if st_color == 'green' else 'bg-slate-200'
                                with ui.element('div').classes(f'absolute left-[19px] top-10 w-0.5 h-full {line_color} -z-0'):
                                    pass

                            # Right: Stage Card Content
                            with ui.card().classes(f'flex-1 p-5 rounded-2xl border {card_cls} transition-all'):
                                with ui.row().classes('w-full items-center justify-between flex-wrap gap-2'):
                                    with ui.row().classes('items-center gap-2'):
                                        ui.label(f"{num}. {st_item['label']}").classes('text-base font-black text-slate-900')
                                        ui.badge(badge_label).classes(f'{badge_style} border font-bold text-[10px] px-2.5 py-0.5 rounded-full')
                                    
                                    if st_item.get('timestamp'):
                                        t_str = str(st_item['timestamp'])[:19].replace('T', ' ')
                                        ui.label(t_str).classes('text-xs font-mono font-bold text-slate-500')

                                ui.label(st_item['description']).classes('text-xs text-slate-700 leading-relaxed mt-2')

                                if st_item.get('officer_info'):
                                    with ui.row().classes('items-center gap-1.5 mt-2.5 pt-2 border-t border-slate-200/60 text-xs text-slate-600'):
                                        ui.icon('badge', size='xs').classes('text-blue-700')
                                        ui.label(f"Assigned / Updated by: {st_item['officer_info']}").classes('font-bold text-slate-800')

                                # Prominent Red Alert if this stage is under alert (staff only)
                                if alerts_for_st and is_officer:
                                    for al in alerts_for_st:
                                        with ui.card().classes('w-full mt-3 p-3 bg-red-100 border border-red-400 rounded-xl text-red-950'):
                                            with ui.row().classes('items-center gap-2'):
                                                ui.icon('error', size='xs').classes('text-red-700')
                                                ui.label(f"Security Alert: {al.get('reason')}").classes('font-bold text-xs')
                                            ui.label(f"Reported on {str(al.get('created_at'))[:19].replace('T', ' ')} · Status: {al.get('status')}").classes('text-[10px] text-red-800 font-mono mt-1')

            # ── 4. Main Officer Stage Update & Case Management Controls ──────────────
            if is_officer:
                with ui.card().classes('w-full p-6 paper-card bg-slate-900 text-white rounded-3xl shadow-md'):
                    with ui.row().classes('w-full items-center justify-between pb-3 border-b border-slate-800 mb-4'):
                        with ui.row().classes('items-center gap-3'):
                            ui.icon('admin_panel_settings', size='md').classes('text-indigo-400')
                            with ui.column().classes('gap-0'):
                                ui.label('Main Officer Case Management & Stage Controls').classes('text-lg font-black text-white fantasy-title')
                                ui.label('Authorized stage transitions, officer assignments, and real-time database updates.').classes('text-xs text-slate-400')
                        ui.badge('OFFICER AUTHORIZATION').classes('bg-indigo-900 text-indigo-200 border border-indigo-700 font-bold text-xs px-3 py-1')

                    with ui.row().classes('w-full gap-4 flex-wrap items-start'):
                        # Stage Selector
                        stage_select_options = {s: f"{i+1}. {STAGE_LABELS[s]}" for i, s in enumerate(CASE_STAGES)}
                        stage_dropdown = ui.select(
                            options=stage_select_options,
                            value=tracking_data.get('current_stage_key') or CASE_STAGES[0],
                            label='Select Case Stage to Update'
                        ).classes('flex-1 min-w-64 bg-slate-800 text-white rounded-xl').props('dark outlined dense')

                        # Remarks field
                        remarks_input = ui.input(
                            label='Officer Remarks / Case Progress Notes',
                            placeholder='e.g., Evidence cataloged, cyber forensics completed, charge sheet filed in court...'
                        ).classes('flex-1 min-w-80 bg-slate-800 text-white rounded-xl').props('dark outlined dense')

                    def handle_officer_update():
                        selected = stage_dropdown.value
                        if not selected:
                            ui.notify('Please select a valid stage.', type='warning')
                            return
                        try:
                            res = update_case_stage(
                                fir_id=fir_id,
                                new_stage=selected,
                                officer_user=actor_user,
                                remarks=remarks_input.value.strip()
                            )
                            ui.notify(f"✓ FIR Stage updated to: {STAGE_LABELS.get(selected, selected)}", type='positive', position='top-right')
                            remarks_input.value = ''
                            render_content()
                            if on_change_callback:
                                on_change_callback()
                        except ValueError as ve:
                            ui.notify(str(ve), type='warning', position='top-right')
                        except Exception as ex:
                            ui.notify(f"Update failed: {str(ex)}", type='negative', position='top-right')

                    with ui.row().classes('w-full justify-between items-center mt-4 pt-3 border-t border-slate-800'):
                        ui.label('Updates are permanently recorded to database and synchronize immediately to the citizen portal.').classes('text-xs text-slate-400 italic')
                        ui.button('Save FIR Stage Update 💾', icon='cloud_upload', on_click=handle_officer_update).props('unelevated').classes('bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-xl px-6 py-2.5 text-xs shadow-md')

    # Initial Render
    render_content()

    # ── 5. Real-Time Live Polling Timer (Synchronizes without page reload) ─────
    poll_timer = None

    def check_for_live_updates():
        nonlocal poll_timer
        try:
            if getattr(container, 'is_deleted', False):
                if poll_timer:
                    poll_timer.cancel()
                return

            fresh_tracking = get_fir_complete_tracking(fir_id, actor_user)
            if not fresh_tracking:
                return

            fresh_stage = fresh_tracking.get('current_stage_key')
            fresh_ts = (fresh_tracking.get('last_tracking_event_at')
                        or fresh_tracking.get('last_updated_at'))
            fresh_alerts_cnt = len(fresh_tracking.get('security_status', {}).get('alerts', []))

            # Detect any update
            if (fresh_stage != last_state_ref['stage'] or 
                fresh_ts != last_state_ref['timestamp'] or 
                fresh_alerts_cnt != last_state_ref['alerts_count']):
                render_content()
        except Exception:
            if poll_timer:
                try:
                    poll_timer.cancel()
                except Exception:
                    pass

    # Poll every 1.5 seconds for instant real-time live synchronization
    poll_timer = ui.timer(1.5, check_for_live_updates)
    try:
        ui.context.client.on_disconnect(lambda: poll_timer.cancel() if poll_timer else None)
    except Exception:
        pass

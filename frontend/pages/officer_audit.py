"""
Complete Officer Audit / Change History System
Shows every modification made by officers with full before/after details.
"""

from nicegui import ui
from frontend.components.layout import portal_page
from backend.services.audit_service import (
    get_all_audit_events,
    get_audit_event_detail,
    get_audit_events_for_fir,
    is_authorized_for_audit
)
from backend.services.auth_service import get_current_user
from backend.services.db import get_db_connection


def require_authorized_user():
    """Ensure user has access to audit trail (Admin or Senior Officer)."""
    user = get_current_user() or {}
    if not user or not is_authorized_for_audit(user):
        ui.navigate.to('/login')
        return None
    return user


@ui.page('/audit/officer-changes')
def officer_audit_history_page() -> None:
    """Complete Officer Audit / Change History - Every modification ever made."""
    user = require_authorized_user()
    if not user:
        return

    try:
        all_events = get_all_audit_events(user)
    except PermissionError:
        with portal_page('admin', '/audit/officer-changes', 'Access Denied', ''):
            ui.label('Insufficient permissions. Admin or Senior Officer access required.').classes('text-red-600 font-bold')
        return

    # Get statistics
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT COUNT(DISTINCT actor_id) as officer_count,
               COUNT(DISTINCT fir_id) as fir_count,
               COUNT(*) as total_changes
        FROM fir_change_events
    """)
    stats = dict(cursor.fetchone())
    
    cursor.execute("""
        SELECT actor_name, actor_badge, COUNT(*) as change_count
        FROM fir_change_events
        GROUP BY actor_id, actor_name, actor_badge
        ORDER BY change_count DESC
    """)
    officer_stats = [dict(r) for r in cursor.fetchall()]
    
    conn.close()

    with portal_page('admin', '/audit/officer-changes', 'Officer Audit / Change History', 
                     'Complete audit trail of every modification made by officers with full before/after details.'):

        # Header Card
        with ui.card().classes('w-full p-6 bg-gradient-to-r from-indigo-50 to-purple-50 border-l-4 border-indigo-600 rounded-2xl shadow-sm mb-6'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                with ui.row().classes('items-center gap-3'):
                    ui.icon('history', size='lg').classes('text-indigo-700')
                    with ui.column().classes('gap-1'):
                        ui.label('Officer Audit / Change History').classes('text-2xl font-black text-slate-900')
                        ui.label('Every modification made by authenticated officers with complete before/after comparison').classes('text-xs text-slate-600')
                with ui.row().classes('items-center gap-2'):
                    ui.badge('REAL DATABASE DATA').classes('bg-emerald-600 text-white font-bold text-xs')
                    ui.badge('APPEND-ONLY LOG').classes('bg-blue-600 text-white font-bold text-xs')

        # Statistics Row
        with ui.row().classes('w-full gap-4 mb-6 flex-wrap'):
            stat_cards = [
                ('Total Changes', stats['total_changes'], 'edit_note', 'text-blue-700', 'bg-blue-50 border-blue-200'),
                ('Officers Active', stats['officer_count'], 'badge', 'text-purple-700', 'bg-purple-50 border-purple-200'),
                ('FIRs Modified', stats['fir_count'], 'folder_open', 'text-indigo-700', 'bg-indigo-50 border-indigo-200'),
            ]
            for title, value, icon, icon_color, card_bg in stat_cards:
                with ui.card().classes(f'flex-1 min-w-48 p-5 rounded-2xl border {card_bg} shadow-sm'):
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.icon(icon, size='md').classes(icon_color)
                        ui.label(str(value)).classes('text-3xl font-black text-slate-900')
                    ui.label(title).classes('text-xs font-bold text-slate-700 mt-2')

        # Officer Activity Summary
        if officer_stats:
            with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-2xl shadow-sm mb-6'):
                with ui.row().classes('w-full items-center gap-2 pb-3 border-b border-slate-200 mb-4'):
                    ui.icon('people', size='sm').classes('text-indigo-700')
                    ui.label('Officer Activity Summary').classes('text-lg font-bold text-slate-900')
                
                with ui.row().classes('w-full gap-3 flex-wrap'):
                    for officer in officer_stats[:10]:
                        with ui.card().classes('flex-1 min-w-64 p-4 bg-slate-50 border border-slate-200 rounded-xl'):
                            with ui.row().classes('items-center justify-between w-full'):
                                with ui.column().classes('gap-0.5'):
                                    ui.label(officer['actor_name']).classes('text-sm font-bold text-slate-900')
                                    ui.label(f"Badge: {officer['actor_badge']}").classes('text-xs text-slate-600 font-mono')
                                ui.badge(f"{officer['change_count']} changes").classes('bg-indigo-100 text-indigo-900 font-bold text-xs')

        # Search & Filter Section
        with ui.card().classes('w-full p-5 bg-white border border-slate-200 rounded-2xl shadow-sm mb-6'):
            ui.label('Search & Filter Audit Records').classes('text-sm font-bold text-slate-700 mb-3')
            with ui.row().classes('w-full gap-3 flex-wrap items-end'):
                search_fir = ui.input('FIR Number').classes('flex-1 min-w-48').props('outlined dense')
                search_officer_name = ui.input('Officer Name').classes('flex-1 min-w-48').props('outlined dense')
                search_officer_badge = ui.input('Officer Badge').classes('flex-1 min-w-48').props('outlined dense')
                
                date_from = ui.input('Date From (YYYY-MM-DD)').classes('min-w-48').props('outlined dense')
                date_to = ui.input('Date To (YYYY-MM-DD)').classes('min-w-48').props('outlined dense')
                
                sort_order = ui.select(
                    {'DESC': 'Newest First', 'ASC': 'Oldest First'},
                    value='DESC',
                    label='Sort Order'
                ).classes('min-w-40').props('outlined dense')

            def do_search():
                filtered = get_all_audit_events(
                    user,
                    search_fir=search_fir.value or '',
                    search_officer_name=search_officer_name.value or '',
                    search_officer_id=search_officer_badge.value or '',
                    filter_date_from=date_from.value or '',
                    filter_date_to=date_to.value or '',
                    sort_order=sort_order.value or 'DESC'
                )
                results_container.clear()
                with results_container:
                    render_audit_table(filtered)

            ui.button('Search & Filter', icon='search', on_click=do_search).props('unelevated').classes(
                'bg-indigo-700 text-white font-bold rounded-xl px-6 py-2.5 text-sm mt-3'
            )

        # Main Audit Table
        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-2xl shadow-sm'):
            with ui.row().classes('w-full items-center justify-between pb-4 border-b border-slate-200 mb-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('fact_check', size='sm').classes('text-indigo-700')
                    ui.label(f'All Officer Modifications ({len(all_events)} Records)').classes('text-xl font-bold text-slate-900')
                ui.badge('IMMUTABLE AUDIT LOG').classes('bg-slate-100 text-slate-800 font-bold text-xs')

            results_container = ui.column().classes('w-full')
            with results_container:
                render_audit_table(all_events)


def render_audit_table(events: list) -> None:
    """Render the complete audit table with all modifications."""
    if not events:
        with ui.column().classes('w-full items-center py-16 gap-3 text-center'):
            ui.icon('search_off', size='xl').classes('text-slate-300')
            ui.label('No audit records found.').classes('text-lg font-bold text-slate-600')
            ui.label('When officers make changes to FIRs, they will appear here automatically.').classes('text-sm text-slate-500')
        return

    with ui.element('div').classes('w-full overflow-x-auto'):
        with ui.element('table').classes('w-full text-left text-xs border-collapse'):
            # Table Header
            with ui.element('thead').classes('bg-indigo-700 text-white'):
                with ui.element('tr'):
                    headers = [
                        'Change ID',
                        'FIR Number',
                        'Citizen',
                        'Officer',
                        'Officer Badge',
                        'Action Type',
                        'Fields Changed',
                        'Date & Time',
                        'Details'
                    ]
                    for header in headers:
                        ui.element('th').classes('p-3 font-bold whitespace-nowrap text-xs').text = header

            # Table Body
            with ui.element('tbody').classes('divide-y divide-slate-200 bg-white'):
                for event in events:
                    event_id = event.get('id', '')
                    event_number = event.get('event_number', 'CHG-????')
                    fir_number = event.get('fir_number', '—')
                    officer_name = event.get('actor_name', 'Unknown Officer')
                    officer_badge = event.get('actor_badge', '—')
                    citizen_name = event.get('citizen_name', '—')
                    action_type = event.get('event_type', 'UPDATE')
                    changed_fields = event.get('changed_fields', [])
                    timestamp = str(event.get('timestamp', ''))[:19].replace('T', ' ')
                    
                    with ui.element('tr').classes('hover:bg-indigo-50/30 transition-colors'):
                        # Change ID
                        with ui.element('td').classes('p-3 font-bold text-indigo-700 font-mono text-xs'):
                            ui.label(event_number)
                        
                        # FIR Number
                        with ui.element('td').classes('p-3 font-black text-slate-900 font-mono text-xs'):
                            ui.label(fir_number)
                        
                        # Citizen
                        with ui.element('td').classes('p-3 font-bold text-slate-800 text-xs'):
                            ui.label(citizen_name if citizen_name != '—' else 'Loading...')
                        
                        # Officer Name
                        with ui.element('td').classes('p-3 font-bold text-slate-900 text-xs'):
                            ui.label(officer_name)
                        
                        # Officer Badge
                        with ui.element('td').classes('p-3 font-bold text-blue-700 font-mono text-xs'):
                            ui.label(officer_badge)
                        
                        # Action Type
                        with ui.element('td').classes('p-3 text-xs'):
                            action_colors = {
                                'AUTHORIZED_FIR_UPDATE': 'bg-amber-100 text-amber-900',
                                'FIR_CREATED': 'bg-emerald-100 text-emerald-900',
                                'FIR_VERIFIED': 'bg-blue-100 text-blue-900',
                                'OFFICER_ASSIGNED': 'bg-purple-100 text-purple-900',
                                'STATUS_CHANGED': 'bg-indigo-100 text-indigo-900',
                            }
                            badge_color = action_colors.get(action_type, 'bg-slate-100 text-slate-900')
                            ui.badge(action_type.replace('_', ' ')).classes(f'{badge_color} font-bold text-[10px] px-2 py-0.5')
                        
                        # Fields Changed
                        with ui.element('td').classes('p-3 text-center text-xs'):
                            ui.badge(str(len(changed_fields))).classes('bg-indigo-600 text-white font-bold text-xs')
                        
                        # Date & Time
                        with ui.element('td').classes('p-3 text-slate-700 font-mono text-xs whitespace-nowrap'):
                            ui.label(timestamp)
                        
                        # View Details Button
                        with ui.element('td').classes('p-3 text-xs'):
                            ui.button(
                                'View Complete Record',
                                icon='open_in_new',
                                on_click=lambda eid=event_id: ui.navigate.to(f'/audit/change-detail/{eid}')
                            ).props('flat size=xs').classes('text-indigo-700 font-bold whitespace-nowrap')


@ui.page('/audit/change-detail/{change_id}')
def change_detail_page(change_id: str) -> None:
    """Complete change record with full before/after comparison."""
    user = require_authorized_user()
    if not user:
        return

    try:
        event = get_audit_event_detail(change_id, user)
    except PermissionError:
        with portal_page('admin', '/audit/officer-changes', 'Access Denied', ''):
            ui.label('Insufficient permissions.').classes('text-red-600 font-bold')
        return

    if not event:
        with portal_page('admin', '/audit/officer-changes', 'Change Record Not Found', ''):
            ui.label('The requested change record could not be found.').classes('text-slate-600')
            ui.button('← Back to Audit History', on_click=lambda: ui.navigate.to('/audit/officer-changes')).props('unelevated')
        return

    # Extract data
    event_number = event.get('event_number', 'CHG-????')
    fir_number = event.get('fir_number', '—')
    citizen_name = event.get('citizen_name', '—')
    citizen_phone = event.get('citizen_phone', '—')
    officer_name = event.get('actor_name', 'Unknown Officer')
    officer_badge = event.get('actor_badge', '—')
    action_type = event.get('event_type', 'UPDATE')
    timestamp = str(event.get('timestamp', ''))[:19].replace('T', ' ')
    changed_fields = event.get('changed_fields', [])
    old_values = event.get('old_values', {})
    new_values = event.get('new_values', {})
    reason = event.get('reason', '—')
    previous_hash = event.get('previous_hash', '—')
    new_hash = event.get('new_hash', '—')
    blockchain_tx = event.get('blockchain_tx_id', '—')
    blockchain_block = event.get('blockchain_block', '—')

    with portal_page('admin', '/audit/change-detail', f'Change Record: {event_number}', 
                     f'Complete modification details for FIR {fir_number}'):

        ui.button('← Back to Audit History', icon='arrow_back', on_click=lambda: ui.navigate.to('/audit/officer-changes')).props('flat').classes('text-indigo-700 font-bold mb-4')

        # Main Record Header
        with ui.card().classes('w-full p-6 bg-gradient-to-r from-indigo-50 to-purple-50 border-l-4 border-indigo-600 rounded-2xl shadow-md mb-6'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                with ui.row().classes('items-center gap-4'):
                    ui.icon('receipt_long', size='lg').classes('text-indigo-700')
                    with ui.column().classes('gap-1'):
                        ui.label(f'Change ID: {event_number}').classes('text-2xl font-black text-slate-900 font-mono')
                        ui.label(f'FIR Number: {fir_number} · Action: {action_type.replace("_", " ")}').classes('text-sm text-slate-700 font-bold')
                ui.badge('IMMUTABLE RECORD').classes('bg-indigo-700 text-white font-bold text-xs px-3 py-1')

        # Summary Cards Row
        with ui.row().classes('w-full gap-4 flex-wrap mb-6'):
            # Citizen Info Card
            with ui.card().classes('flex-1 min-w-80 p-5 bg-white border border-emerald-200 rounded-2xl shadow-sm'):
                ui.label('Citizen Information').classes('text-sm font-black text-emerald-700 uppercase tracking-wider mb-3 pb-2 border-b border-emerald-100')
                info_rows = [
                    ('Citizen Name', citizen_name),
                    ('Phone Number', citizen_phone),
                    ('FIR Number', fir_number),
                    ('Incident Type', event.get('incident_type', '—')),
                ]
                for label, value in info_rows:
                    with ui.row().classes('items-center justify-between py-2 border-b border-slate-100'):
                        ui.label(label).classes('text-xs font-bold text-slate-600')
                        ui.label(str(value)).classes('text-xs font-bold text-slate-900 text-right')

            # Officer Info Card
            with ui.card().classes('flex-1 min-w-80 p-5 bg-white border border-blue-200 rounded-2xl shadow-sm'):
                ui.label('Officer Who Made Change').classes('text-sm font-black text-blue-700 uppercase tracking-wider mb-3 pb-2 border-b border-blue-100')
                officer_rows = [
                    ('Officer Name', officer_name),
                    ('Officer Badge', officer_badge),
                    ('Officer Role', event.get('actor_role', '—')),
                    ('Action Type', action_type.replace('_', ' ')),
                ]
                for label, value in officer_rows:
                    with ui.row().classes('items-center justify-between py-2 border-b border-slate-100'):
                        ui.label(label).classes('text-xs font-bold text-slate-600')
                        ui.label(str(value)).classes('text-xs font-bold text-slate-900 text-right')

        # Modification Details Card
        with ui.card().classes('w-full p-6 bg-white border border-slate-200 rounded-2xl shadow-sm mb-6'):
            ui.label('Modification Details').classes('text-lg font-black text-slate-900 mb-4 pb-2 border-b border-slate-200')
            
            with ui.row().classes('w-full gap-6 flex-wrap'):
                details = [
                    ('Date & Timestamp', timestamp),
                    ('Timezone', event.get('timezone', 'IST (UTC+05:30)')),
                    ('IP Address', event.get('ip_address', '—')),
                    ('Device Info', event.get('device_info', '—')),
                    ('Change Reason', reason),
                    ('Version', f"v{event.get('previous_version', '?')} → v{event.get('new_version', '?')}"),
                    ('Fields Modified', str(len(changed_fields))),
                ]
                
                for label, value in details:
                    with ui.column().classes('gap-1 min-w-48'):
                        ui.label(label).classes('text-xs font-bold text-slate-500 uppercase tracking-wide')
                        ui.label(str(value)).classes('text-sm font-bold text-slate-900')

        # Hash & Integrity Information
        with ui.card().classes('w-full p-6 bg-slate-50 border border-slate-300 rounded-2xl shadow-sm mb-6'):
            ui.label('Hash & Integrity Status').classes('text-lg font-black text-slate-900 mb-4 pb-2 border-b border-slate-300')
            
            hash_info = [
                ('Previous Hash', previous_hash[:32] + '...' if len(str(previous_hash)) > 32 else previous_hash),
                ('New Hash', new_hash[:32] + '...' if len(str(new_hash)) > 32 else new_hash),
                ('Blockchain Transaction ID', blockchain_tx[:32] + '...' if len(str(blockchain_tx)) > 32 else blockchain_tx),
                ('Blockchain Block Number', str(blockchain_block)),
                ('Integrity Status', event.get('blockchain_status', 'CONFIRMED')),
            ]
            
            for label, value in hash_info:
                with ui.row().classes('items-center justify-between py-2 border-b border-slate-200'):
                    ui.label(label).classes('text-xs font-bold text-slate-700')
                    ui.label(str(value)).classes('text-xs font-mono text-slate-900 break-all text-right')

        # Complete Before & After Comparison
        if changed_fields:
            ui.label('Complete Before & After Comparison').classes('text-2xl font-black text-slate-900 mb-4')
            
            with ui.row().classes('w-full gap-6 flex-wrap'):
                # BEFORE Column
                with ui.card().classes('flex-1 min-w-96 p-6 bg-red-50 border-2 border-red-300 rounded-2xl shadow-md'):
                    with ui.row().classes('items-center gap-3 mb-4 pb-3 border-b-2 border-red-300'):
                        ui.icon('history', size='md').classes('text-red-700')
                        ui.label('BEFORE (Previous Content)').classes('text-lg font-black text-red-800 uppercase tracking-wider')
                    
                    for field in changed_fields:
                        old_value = old_values.get(field, '(empty)')
                        with ui.column().classes('gap-2 mb-4 pb-4 border-b border-red-200'):
                            ui.label(field.replace('_', ' ').title()).classes('text-xs font-black text-red-700 uppercase tracking-wider')
                            with ui.element('div').classes('p-4 rounded-lg bg-red-100 border-2 border-red-200'):
                                ui.label(str(old_value) if old_value else '(empty)').classes('text-sm text-red-900 leading-relaxed whitespace-pre-wrap')

                # AFTER Column
                with ui.card().classes('flex-1 min-w-96 p-6 bg-emerald-50 border-2 border-emerald-300 rounded-2xl shadow-md'):
                    with ui.row().classes('items-center gap-3 mb-4 pb-3 border-b-2 border-emerald-300'):
                        ui.icon('update', size='md').classes('text-emerald-700')
                        ui.label('AFTER (New Content)').classes('text-lg font-black text-emerald-800 uppercase tracking-wider')
                    
                    for field in changed_fields:
                        new_value = new_values.get(field, '(empty)')
                        with ui.column().classes('gap-2 mb-4 pb-4 border-b border-emerald-200'):
                            ui.label(field.replace('_', ' ').title()).classes('text-xs font-black text-emerald-700 uppercase tracking-wider')
                            with ui.element('div').classes('p-4 rounded-lg bg-emerald-100 border-2 border-emerald-200'):
                                ui.label(str(new_value) if new_value else '(empty)').classes('text-sm text-emerald-900 leading-relaxed whitespace-pre-wrap')
        else:
            with ui.card().classes('w-full p-8 bg-slate-50 border border-slate-200 rounded-2xl text-center'):
                ui.icon('info', size='lg').classes('text-slate-400 mb-2')
                ui.label('No field changes recorded for this event.').classes('text-sm text-slate-600')

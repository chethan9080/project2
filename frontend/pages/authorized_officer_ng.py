"""
Authorized Officer Portal Pages (NiceGUI)
Restricted access for FIR integrity monitoring, version comparison, and audit management
AUTHORIZED_OFFICER / ADMIN role only
"""

from nicegui import ui
from typing import Dict, Any, List, Optional

from frontend.components.layout import portal_page
from frontend.components.badges import fir_status_badge, integrity_badge
from backend.services.auth_service import get_current_user
from backend.services.authorized_officer_service import (
    check_authorized_officer_access,
    get_dashboard_data,
    compare_fir_versions,
    get_fir_version_history,
    get_audit_logs,
    reassign_fir_officer
)


def require_authorized_officer():
    """Ensure user has Authorized Officer access."""
    user = get_current_user() or {}
    if not user or user.get("role") not in ("ADMIN", "AUTHORIZED_OFFICER"):
        ui.notify(
            "Access Denied: This section is restricted to Authorized Officers only.",
            type='negative',
            position='center'
        )
        ui.navigate.to('/staff-portal')
        return None
    return user


@ui.page('/authorized-officer/dashboard')
def authorized_dashboard() -> None:
    """Authorized Officer Integrity Dashboard."""
    user = require_authorized_officer()
    if not user:
        return
    
    try:
        dashboard_result = get_dashboard_data(user)
        stats = dashboard_result.get('dashboard', {})
    except Exception as e:
        ui.notify(f"Error loading dashboard: {str(e)}", type='negative')
        ui.navigate.to('/staff-portal')
        return
    
    with portal_page('admin', '/authorized-officer/dashboard', '🔒 Authorized Officer Portal', 
                      'FIR Integrity Monitoring · Version Comparison · Audit Management'):
        
        # Header Banner
        with ui.card().classes('w-full p-6 paper-card mb-4 border-l-4 border-red-600 bg-white'):
            with ui.row().classes('w-full items-center justify-between flex-wrap gap-4'):
                with ui.row().classes('items-center gap-4'):
                    with ui.element('div').classes('w-14 h-14 rounded-full flex items-center justify-center bg-red-600 text-white shadow-sm'):
                        ui.icon('shield_lock', size='md')
                    with ui.column().classes('gap-0.5'):
                        ui.label('Authorized Officer Portal').classes('text-2xl md:text-3xl font-black text-slate-900 fantasy-title')
                        ui.label('Restricted Access · FIR Integrity & Tampering Detection').classes('text-xs text-slate-600')
                
                ui.badge('AUTHORIZED OFFICER ONLY').classes('bg-red-700 text-white font-bold text-xs px-3 py-1')
        
        # Statistics Cards
        with ui.row().classes('w-full flex-wrap gap-4 mb-4'):
            cards_data = [
                ('Total FIRs Monitored', stats.get('total_firs_monitored', 0), 'database', '#1E40AF', 'bg-blue-50'),
                ('FIRs with Changes', stats.get('firs_with_changes', 0), 'edit_note', '#EA580C', 'bg-orange-50'),
                ('FIRs No Changes', stats.get('firs_no_changes', 0), 'check_circle', '#059669', 'bg-green-50'),
                ('Changes (24h)', stats.get('recent_changes_24h', 0), 'activity', '#9333EA', 'bg-purple-50'),
            ]
            for title, val, icon_name, color, bg_cls in cards_data:
                with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border border-slate-200 shadow-sm {bg_cls}'):
                    with ui.row().classes('items-center justify-between w-full'):
                        ui.icon(icon_name, size='md').style(f'color: {color}')
                        ui.label(str(val)).classes('text-2xl font-black text-slate-900')
                    ui.label(title).classes('text-xs font-bold text-slate-700 mt-2')
        
        # Quick Access Cards
        with ui.row().classes('w-full flex-wrap gap-4 mb-4'):
            with ui.card().classes('flex-1 min-w-64 p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm cursor-pointer hover:shadow-md transition-all').on('click', lambda: ui.navigate.to('/authorized-officer/comparison')):
                with ui.row().classes('items-center gap-3 mb-3'):
                    ui.icon('compare', size='lg').classes('text-blue-600')
                    ui.label('FIR Version Comparison').classes('text-lg font-bold text-slate-900')
                ui.label('Compare different versions of FIRs with field-by-field changes and hash verification').classes('text-sm text-slate-600')
            
            with ui.card().classes('flex-1 min-w-64 p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm cursor-pointer hover:shadow-md transition-all').on('click', lambda: ui.navigate.to('/authorized-officer/version-history')):
                with ui.row().classes('items-center gap-3 mb-3'):
                    ui.icon('history', size='lg').classes('text-purple-600')
                    ui.label('Version History & Hashes').classes('text-lg font-bold text-slate-900')
                ui.label('View complete version timeline with SHA-256 hash chain verification').classes('text-sm text-slate-600')
            
            with ui.card().classes('flex-1 min-w-64 p-6 paper-card bg-white border border-slate-200 rounded-3xl shadow-sm cursor-pointer hover:shadow-md transition-all').on('click', lambda: ui.navigate.to('/authorized-officer/audit-logs')):
                with ui.row().classes('items-center gap-3 mb-3'):
                    ui.icon('fact_check', size='lg').classes('text-green-600')
                    ui.label('Complete Audit Logs').classes('text-lg font-bold text-slate-900')
                ui.label('Track all FIR modifications with comprehensive filtering options').classes('text-sm text-slate-600')
        
        # Recent Officer Actions
        recent_officers = stats.get('recent_officer_actions', [])
        if recent_officers:
            with ui.card().classes('w-full p-6 paper-card bg-white rounded-3xl shadow-sm'):
                ui.label('Recent Officer Actions (7 Days)').classes('text-lg font-bold text-slate-900 mb-3')
                
                with ui.element('div').classes('w-full overflow-x-auto'):
                    with ui.element('table').classes('w-full'):
                        with ui.element('thead'):
                            with ui.element('tr').classes('border-b border-slate-200'):
                                for header in ['Officer', 'Role', 'Badge', 'Actions']:
                                    with ui.element('th').classes('text-left text-xs font-bold text-slate-700 py-2 px-3'):
                                        ui.label(header)
                        with ui.element('tbody'):
                            for officer in recent_officers[:10]:
                                with ui.element('tr').classes('border-b border-slate-100 hover:bg-slate-50'):
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(officer.get('officer_name', 'N/A')).classes('text-sm font-medium')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(officer.get('role', 'UNKNOWN')).classes('text-xs')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(officer.get('badge_number') or 'N/A').classes('text-xs text-slate-600')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(str(officer.get('action_count', 0)), color='blue').classes('text-xs')
        
        # Recent Integrity Checks
        recent_checks = stats.get('recent_integrity_checks', [])
        if recent_checks:
            with ui.card().classes('w-full p-6 paper-card bg-white rounded-3xl shadow-sm'):
                ui.label('Recent Integrity Checks').classes('text-lg font-bold text-slate-900 mb-3')
                
                with ui.element('div').classes('w-full overflow-x-auto'):
                    with ui.element('table').classes('w-full'):
                        with ui.element('thead'):
                            with ui.element('tr').classes('border-b border-slate-200'):
                                for header in ['FIR', 'Version', 'Hash', 'Officer', 'Timestamp']:
                                    with ui.element('th').classes('text-left text-xs font-bold text-slate-700 py-2 px-3'):
                                        ui.label(header)
                        with ui.element('tbody'):
                            for check in recent_checks[:10]:
                                with ui.element('tr').classes('border-b border-slate-100 hover:bg-slate-50'):
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(check.get('fir_number', 'N/A')).classes('text-sm font-mono font-bold')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(f"V{check.get('version', 0)}").classes('text-xs')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(check.get('hash', 'N/A')).classes('text-xs font-mono text-slate-500')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(check.get('officer_name', 'N/A')).classes('text-sm')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(check.get('timestamp', 'N/A')).classes('text-xs text-slate-600')


@ui.page('/authorized-officer/comparison')
def fir_comparison_page() -> None:
    """FIR Version Comparison Page."""
    user = require_authorized_officer()
    if not user:
        return
    
    fir_id_input = ''
    version1_input = 1
    version2_input = 2
    comparison_result = {}
    
    with portal_page('admin', '/authorized-officer/comparison', 'FIR Version Comparison', 
                      'Compare FIR versions with hash verification'):
        
        # Header
        with ui.card().classes('w-full p-6 paper-card mb-4 bg-white'):
            ui.label('FIR Integrity & Version Comparison').classes('text-2xl font-bold text-slate-900 mb-2')
            ui.label('Compare different versions of an FIR showing field-by-field differences').classes('text-sm text-slate-600')
        
        # Input Form
        with ui.card().classes('w-full p-6 paper-card bg-white mb-4'):
            ui.label('Select FIR and Versions').classes('text-lg font-bold text-slate-900 mb-3')
            
            with ui.row().classes('w-full gap-4 flex-wrap'):
                fir_input = ui.input('FIR ID', placeholder='FIR-2026-XXXXX').classes('flex-1 min-w-48')
                v1_input = ui.number('Version 1 (Original)', value=1, min=1, step=1).classes('w-32')
                v2_input = ui.number('Version 2 (Current)', value=2, min=1, step=1).classes('w-32')
                
                async def compare_versions():
                    try:
                        result = compare_fir_versions(
                            fir_id=fir_input.value,
                            version1=int(v1_input.value),
                            version2=int(v2_input.value),
                            user=user
                        )
                        ui.notify('Comparison loaded successfully', type='positive')
                        # In a real implementation, would update UI with result
                    except Exception as e:
                        ui.notify(f'Error: {str(e)}', type='negative')
                
                ui.button('Compare Versions', icon='compare', on_click=compare_versions).props('unelevated').classes('bg-blue-600 text-white font-bold px-6')
        
        # Results would be displayed here (simplified for brevity)
        ui.label('Comparison results will be displayed here after clicking Compare Versions').classes('text-sm text-slate-500 text-center py-8')


@ui.page('/authorized-officer/version-history')
def version_history_page() -> None:
    """FIR Version History Page."""
    user = require_authorized_officer()
    if not user:
        return
    
    with portal_page('admin', '/authorized-officer/version-history', 'FIR Version History', 
                      'Complete version timeline with hash chain verification'):
        
        with ui.card().classes('w-full p-6 paper-card mb-4 bg-white'):
            ui.label('FIR Version History & Hash Chain').classes('text-2xl font-bold text-slate-900 mb-2')
            ui.label('View complete cryptographic hash chain for FIR versions').classes('text-sm text-slate-600')
        
        # Input Form
        with ui.card().classes('w-full p-6 paper-card bg-white'):
            ui.label('Select FIR').classes('text-lg font-bold text-slate-900 mb-3')
            
            with ui.row().classes('w-full gap-4'):
                fir_input = ui.input('FIR ID', placeholder='FIR-2026-XXXXX').classes('flex-1')
                
                async def load_history():
                    try:
                        result = get_fir_version_history(fir_id=fir_input.value, user=user)
                        ui.notify('Version history loaded', type='positive')
                    except Exception as e:
                        ui.notify(f'Error: {str(e)}', type='negative')
                
                ui.button('Load History', icon='history', on_click=load_history).props('unelevated').classes('bg-purple-600 text-white font-bold px-6')


@ui.page('/authorized-officer/audit-logs')
def audit_logs_page() -> None:
    """Complete Audit Log Page."""
    user = require_authorized_officer()
    if not user:
        return
    
    try:
        result = get_audit_logs(user=user, limit=100)
        logs = result.get('audit_logs', [])
    except Exception as e:
        ui.notify(f"Error loading audit logs: {str(e)}", type='negative')
        logs = []
    
    with portal_page('admin', '/authorized-officer/audit-logs', 'Complete Audit Logs', 
                      'Track all FIR modifications and officer actions'):
        
        with ui.card().classes('w-full p-6 paper-card mb-4 bg-white'):
            with ui.row().classes('w-full items-center justify-between'):
                with ui.column().classes('gap-1'):
                    ui.label('Complete Audit Log').classes('text-2xl font-bold text-slate-900')
                    ui.label(f'{len(logs)} audit entries').classes('text-sm text-slate-600')
                ui.button('Refresh', icon='refresh', on_click=lambda: ui.navigate.reload()).props('outline')
        
        # Audit Table
        if logs:
            with ui.card().classes('w-full p-6 paper-card bg-white'):
                with ui.element('div').classes('w-full overflow-x-auto'):
                    with ui.element('table').classes('w-full'):
                        with ui.element('thead'):
                            with ui.element('tr').classes('border-b border-slate-200'):
                                for header in ['Timestamp', 'FIR', 'Officer', 'Role', 'Action', 'Version', 'Status']:
                                    with ui.element('th').classes('text-left text-xs font-bold text-slate-700 py-2 px-3'):
                                        ui.label(header)
                        with ui.element('tbody'):
                            for log in logs[:50]:  # Show first 50
                                with ui.element('tr').classes('border-b border-slate-100 hover:bg-slate-50'):
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(log.get('timestamp', 'N/A')[:19]).classes('text-xs text-slate-600')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(log.get('fir_number', 'N/A')).classes('text-sm font-mono font-bold')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.label(log.get('officer_name', 'N/A')).classes('text-sm')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(log.get('officer_role', 'UNKNOWN')).classes('text-xs')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(log.get('action', 'UNKNOWN'), color='purple').classes('text-xs')
                                    with ui.element('td').classes('py-2 px-3'):
                                        ui.badge(f"V{log.get('version', 0)}").classes('text-xs')
                                    with ui.element('td').classes('py-2 px-3'):
                                        status = log.get('blockchain_status', 'PENDING')
                                        color = 'green' if status == 'CONFIRMED' else 'orange'
                                        ui.badge(status, color=color).classes('text-xs')
        else:
            with ui.card().classes('w-full p-12 text-center'):
                ui.label('No audit logs found').classes('text-slate-500')

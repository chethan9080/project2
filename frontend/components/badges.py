"""
Badge and Tag UI Components for FIR Status and Blockchain Integrity.
"""

from nicegui import ui


def integrity_badge(status: str, size: str = 'text-xs') -> None:
    """Render standardized cryptographic integrity badge."""
    status_upper = (status or "").upper()
    if status_upper == "VERIFIED":
        with ui.row().classes(f'items-center gap-1.5 px-3 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-300 {size} font-bold shadow-xs'):
            ui.icon('verified', size='xs').classes('text-emerald-600')
            ui.label('🟢 VERIFIED')
    elif status_upper in ("TAMPER_DETECTED", "INTEGRITY_ISSUE", "TAMPERED"):
        with ui.row().classes(f'items-center gap-1.5 px-3 py-1 rounded-full bg-red-50 text-red-800 border border-red-400 {size} font-bold shadow-xs animate-pulse'):
            ui.icon('warning', size='xs').classes('text-red-600')
            ui.label('🔴 TAMPER DETECTED')
    else:
        with ui.row().classes(f'items-center gap-1.5 px-3 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-300 {size} font-bold shadow-xs'):
            ui.icon('pending', size='xs').classes('text-amber-600')
            ui.label('🟡 VERIFICATION PENDING')


def fir_status_badge(status: str) -> None:
    """Render standardized FIR lifecycle status badge."""
    st = (status or "SUBMITTED").upper()
    config = {
        "PENDING_VERIFICATION": ("#FEF3C7", "#92400E", "#F59E0B", "pending_actions", "Pending Verification"),
        "VERIFIED": ("#E0F2FE", "#075985", "#38BDF8", "verified", "Verified"),
        "SUBMITTED": ("#FEF3C7", "#92400E", "#F59E0B", "hourglass_empty", "Submitted"),
        "UNDER_REVIEW": ("#DBEAFE", "#1E40AF", "#93C5FD", "preview", "Under Review"),
        "UNDER_INVESTIGATION": ("#E0E7FF", "#3730A3", "#A5B4FC", "manage_search", "Under Investigation"),
        "CHARGESHEET_FILED": ("#F3E8FF", "#6B21A8", "#D8B4FE", "gavel", "Chargesheet Filed"),
        "RESOLVED": ("#DCFCE7", "#166534", "#86EFAC", "check_circle", "Resolved"),
        "CLOSED": ("#F3F4F6", "#374151", "#D1D5DB", "lock", "Closed"),
    }
    bg, text, border, icon_name, label_text = config.get(st, ("#F3F4F6", "#374151", "#D1D5DB", "info", st))
    with ui.row().classes('items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold').style(
        f'background: {bg}; color: {text}; border: 1px solid {border};'
    ):
        ui.icon(icon_name, size='xs')
        ui.label(label_text)

"""
Citizen Registration Verification Pages (Verification Officer Portal).

- /verification/citizens           live queue of citizen registration applications
- /verification/citizens/{id}      individual application review with secure documents

New applications are pushed to every open queue over the websocket event bus and
appear without a page refresh. Status changes are persisted atomically and the
citizen portal is notified in real time.
"""

import os

from nicegui import background_tasks, ui

from frontend.components.layout import portal_page
from frontend.pages.verification import require_verification_officer
from backend.services.citizen_registration_service import (
    get_alerts,
    get_application_events,
    get_application_stats,
    get_citizen_application,
    get_citizen_applications,
    get_unread_alert_count,
    mark_alerts_read,
    record_application_action,
    status_label,
)
from backend.services.realtime_events import subscribe, unsubscribe
from backend.services.citizen_credentials_service import (
    SENT as DELIVERY_SENT,
    activation_summary,
    retry_delivery,
)


STATUS_STYLES = {
    'PENDING': ('bg-amber-100 text-amber-900 border-amber-300', 'schedule'),
    'UNDER_REVIEW': ('bg-blue-100 text-blue-900 border-blue-300', 'manage_search'),
    'ADDITIONAL_INFO_REQUIRED': ('bg-orange-100 text-orange-900 border-orange-300', 'help_outline'),
    'APPROVED': ('bg-emerald-100 text-emerald-900 border-emerald-300', 'check_circle'),
    'REJECTED': ('bg-red-100 text-red-900 border-red-300', 'cancel'),
}

ACTION_ICONS = {
    'SUBMITTED': 'upload_file',
    'APPROVED': 'verified',
    'REJECTED': 'cancel',
    'ADDITIONAL_INFO_REQUESTED': 'contact_support',
    'REMARK': 'sticky_note_2',
}


def _status_badge(status: str) -> None:
    classes, icon = STATUS_STYLES.get(status or '', ('bg-slate-100 text-slate-800 border-slate-300', 'info'))
    with ui.row().classes(f'items-center gap-1 px-2.5 py-1 rounded-full border font-bold text-[10px] {classes}'):
        ui.icon(icon, size='xs')
        ui.label(status_label(status).upper())


def _format_timestamp(value: str | None) -> str:
    if not value:
        return '—'
    return str(value)[:19].replace('T', ' ') + ' UTC'


def _application_card(application: dict) -> None:
    status = application.get('status', 'PENDING')
    with ui.card().classes(
        'w-full h-full p-5 rounded-2xl bg-white border border-slate-200 shadow-xs '
        'hover:shadow-md hover:-translate-y-0.5 transition-all gap-3'
    ):
        with ui.row().classes('w-full items-start justify-between gap-2'):
            with ui.column().classes('gap-0.5 min-w-0'):
                ui.label(application.get('full_name') or 'Citizen').classes(
                    'text-base font-black text-slate-900 leading-tight truncate'
                )
                ui.label(application.get('reference') or '').classes(
                    'text-[10px] font-mono text-slate-500 tracking-wide'
                )
            _status_badge(status)

        with ui.column().classes('w-full gap-1.5 text-xs text-slate-600'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('event', size='xs').classes('text-slate-400')
                ui.label(f"Submitted: {_format_timestamp(application.get('submitted_at'))}").classes('font-mono text-[10px]')
            with ui.row().classes('items-center gap-2'):
                ui.icon('badge', size='xs').classes('text-slate-400')
                ui.label(f"ID Type: {application.get('gov_id_type') or 'N/A'}").classes('font-semibold')
            with ui.row().classes('items-center gap-2'):
                ui.icon('location_city', size='xs').classes('text-slate-400')
                ui.label(f"{application.get('district') or 'N/A'}, {application.get('state') or 'N/A'}").classes('truncate')

        with ui.row().classes('w-full justify-end pt-2 border-t border-slate-100 mt-auto'):
            ui.button(
                'View Details',
                icon='visibility',
                on_click=lambda app_id=application['id']: ui.navigate.to(f'/verification/citizens/{app_id}'),
            ).props('unelevated size=sm').classes(
                'bg-emerald-800 hover:bg-emerald-900 text-white font-bold rounded-lg px-3 py-1.5 text-[11px]'
            )


@ui.page('/verification/citizens')
def citizen_verification_queue_page() -> None:
    """Live queue of citizen registration applications."""
    user = require_verification_officer()
    if not user:
        return

    unread_alerts = get_unread_alert_count(user['id'])

    with portal_page(
        'verification',
        '/verification/citizens',
        'Citizen Registration Verification',
        'Review new citizen applications in real time — photograph, government ID, and identity details.',
    ):
        with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 mb-2'):
            with ui.row().classes('items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 border border-emerald-200'):
                ui.element('div').classes('w-2 h-2 rounded-full bg-emerald-500 animate-pulse')
                ui.label('Live monitoring active — new applications appear instantly').classes(
                    'text-[11px] font-bold text-emerald-900'
                )
            unread_badge = ui.label(
                f'{unread_alerts} unread alert(s)' if unread_alerts else 'No unread alerts'
            ).classes('text-[11px] font-semibold text-slate-500')

        @ui.refreshable
        def render_queue() -> None:
            stats = get_application_stats()
            applications = get_citizen_applications()
            alerts = get_alerts(user['id'], limit=5)

            with ui.row().classes('w-full flex-wrap gap-3 mb-4'):
                for label, key, icon, color, bg in [
                    ('Pending / In Review', 'open_count', 'pending_actions', '#D97706', 'bg-amber-50/80 border-amber-200'),
                    ('Additional Info', 'info_count', 'help_outline', '#EA580C', 'bg-orange-50/80 border-orange-200'),
                    ('Approved', 'approved_count', 'verified', '#059669', 'bg-emerald-50/80 border-emerald-200'),
                    ('Rejected', 'rejected_count', 'cancel', '#DC2626', 'bg-red-50/80 border-red-200'),
                ]:
                    with ui.card().classes(f'min-w-36 flex-1 p-4 rounded-2xl border shadow-xs {bg}'):
                        with ui.row().classes('items-center justify-between w-full'):
                            ui.icon(icon, size='sm').style(f'color: {color}')
                            ui.label(str(stats.get(key, 0))).classes('text-2xl font-black text-slate-900')
                        ui.label(label).classes('text-[11px] font-bold text-slate-700 mt-1')

            if alerts:
                with ui.card().classes('w-full p-4 rounded-2xl bg-slate-50 border border-slate-200 shadow-xs mb-4'):
                    with ui.row().classes('w-full items-center justify-between mb-2'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('notifications_active', size='sm').classes('text-emerald-800')
                            ui.label('Recent Registration Alerts').classes('text-sm font-bold text-slate-900')
                        if get_unread_alert_count(user['id']) > 0:
                            def mark_all() -> None:
                                mark_alerts_read(user['id'])
                                unread_badge.text = 'No unread alerts'
                                render_queue.refresh()

                            ui.button('Mark all read', on_click=mark_all).props('flat dense no-caps').classes(
                                'text-[10px] font-bold text-emerald-800'
                            )
                    with ui.column().classes('w-full gap-1'):
                        for alert in alerts:
                            unread = not alert.get('is_read')
                            with ui.row().classes(
                                f'w-full items-center gap-2 text-[11px] px-2 py-1 rounded-lg '
                                f'{"bg-white border border-emerald-200" if unread else ""}'
                            ):
                                ui.icon('fiber_new' if unread else 'check', size='xs').classes(
                                    'text-emerald-600' if unread else 'text-slate-400'
                                )
                                ui.label(alert.get('message', '')).classes(
                                    'font-semibold text-slate-700 flex-1 truncate' if unread else 'text-slate-500 flex-1 truncate'
                                )
                                ui.label(_format_timestamp(alert.get('created_at'))).classes('text-[9px] font-mono text-slate-400')

            if not applications:
                with ui.card().classes('w-full p-10 rounded-2xl bg-white border border-slate-200 shadow-xs'):
                    with ui.column().classes('w-full items-center gap-3 text-center'):
                        ui.icon('how_to_reg', size='xl').classes('text-slate-300')
                        ui.label('No citizen registration applications yet.').classes('text-base font-bold text-slate-700')
                        ui.label(
                            'New registrations will appear here automatically the moment they are submitted.'
                        ).classes('text-xs text-slate-500')
                return

            open_applications = [
                a for a in applications
                if a.get('status') in ('PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED')
            ]
            processed_applications = [a for a in applications if a.get('status') in ('APPROVED', 'REJECTED')]

            with ui.row().classes('w-full items-center justify-between flex-wrap gap-2 mb-2'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('how_to_reg', size='sm').classes('text-emerald-800')
                    ui.label('Pending Citizen Verifications').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.badge(f'{len(open_applications)} Open').classes('bg-amber-500 text-slate-950 font-bold text-xs')

            if open_applications:
                with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full mb-6'):
                    for application in open_applications:
                        _application_card(application)
            else:
                with ui.card().classes('w-full p-6 rounded-2xl bg-emerald-50/60 border border-emerald-200 mb-6'):
                    with ui.row().classes('items-center gap-3'):
                        ui.icon('task_alt', size='md').classes('text-emerald-600')
                        ui.label('Every citizen application has been processed.').classes(
                            'text-sm font-bold text-emerald-900'
                        )

            if processed_applications:
                ui.label('Completed Verifications').classes('text-lg font-bold text-slate-900 fantasy-title mt-2 mb-2')
                with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 w-full'):
                    for application in processed_applications:
                        _application_card(application)

        render_queue()

        # ── Live push subscription (no polling) ─────────────────────────
        client = ui.context.client
        event_queue = subscribe()

        async def listen_for_applications() -> None:
            while True:
                event = await event_queue.get()
                if event.get('type') not in (
                    'CITIZEN_APPLICATION_SUBMITTED',
                    'CITIZEN_APPLICATION_UPDATED',
                ):
                    continue
                if not client.has_socket_connection:
                    break
                with client:
                    render_queue.refresh()
                    if event['type'] == 'CITIZEN_APPLICATION_SUBMITTED':
                        ui.notify(
                            f"🔔 New citizen registration: {event.get('full_name')} "
                            f"({event.get('reference')})",
                            type='positive',
                            position='top-right',
                            close_button=True,
                            timeout=8000,
                        )
                        unread_badge.text = 'New registration received'
                    else:
                        ui.notify(
                            f"{event.get('reference')} → {status_label(event.get('status'))}",
                            type='info',
                            position='top-right',
                            close_button=True,
                        )

        task = background_tasks.create(listen_for_applications(), name='citizen-verification-queue')

        def stop_listening() -> None:
            unsubscribe(event_queue)
            task.cancel()

        client.on_disconnect(stop_listening)


def _info_row(label: str, value: str, icon: str) -> None:
    with ui.row().classes('w-full justify-between items-center gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200 flex-wrap'):
        with ui.row().classes('items-center gap-2'):
            ui.icon(icon, size='xs').classes('text-emerald-700')
            ui.label(label).classes('text-xs font-bold text-slate-600')
        ui.label(value or 'Not provided').classes('text-xs font-bold text-slate-900 break-words')


def _credentials_card(application: dict, officer: dict) -> None:
    """Show the login credentials generated by approval and how they were delivered."""
    citizen_id = application.get('citizen_id')
    summary = activation_summary(citizen_id) if citizen_id else None

    with ui.card().classes('w-full p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
        with ui.row().classes('items-center gap-2 mb-4 pb-2 border-b border-slate-100'):
            ui.icon('vpn_key', size='sm').classes('text-emerald-800')
            ui.label('5. Citizen Login Credentials').classes('text-lg font-bold text-slate-900 fantasy-title')

        if not summary:
            ui.label(
                'No login credentials have been issued yet. Approving this application generates a unique '
                'username, a single-use activation link and the citizen notification automatically.'
            ).classes('text-xs text-slate-600')
            return

        with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 gap-3 w-full'):
            _info_row('Issued Username', summary.get('username') or '', 'badge')
            _info_row('Issued By', summary.get('issued_by_name') or 'System', 'military_tech')
            _info_row('Issued At', _format_timestamp(summary.get('issued_at')), 'event')
            _info_row('Account Status', summary.get('account_status') or '—', 'person')
            _info_row('Delivery Channel', summary.get('delivery_channel') or 'NONE', 'send_and_archive')
            _info_row('Delivery Status', summary.get('delivery_status') or 'PENDING', 'local_shipping')
            _info_row('Delivery Attempts', str(summary.get('delivery_attempts') or 0), 'autorenew')
            _info_row('Delivered At', _format_timestamp(summary.get('delivered_at')), 'schedule')
            _info_row('Activation Link', summary.get('link_status') or 'NONE', 'link')
            _info_row('Link Expires', _format_timestamp(summary.get('link_expires_at')), 'timer')
            _info_row(
                'Permanent Password Set',
                ('Yes — ' + _format_timestamp(summary.get('password_set_at')))
                if summary.get('password_set_at') else 'Not yet',
                'lock_reset',
            )
            _info_row('Citizen ID', citizen_id or '', 'fingerprint')

        with ui.column().classes('w-full gap-2 mt-4 p-3 rounded-xl border bg-slate-50 border-slate-200'):
            if summary.get('delivery_status') == DELIVERY_SENT:
                tone = 'text-emerald-800'
                message = (
                    f"Delivered over {summary.get('delivery_channel')}: "
                    f"{summary.get('delivery_detail') or 'provider accepted the notice.'}"
                )
            elif summary.get('delivery_status') == 'NOT_CONFIGURED':
                tone = 'text-amber-800'
                message = (
                    'No email or SMS provider is configured on this server, so the credentials were not sent '
                    'out-of-band. The citizen sees the username and can collect a single-use activation link '
                    'from the registration status page.'
                )
            else:
                tone = 'text-red-800'
                message = (
                    f"Credential delivery did not succeed "
                    f"({summary.get('delivery_status')}): {summary.get('delivery_detail') or 'no provider response.'}. "
                    'The account is verified, but the citizen has not been notified out-of-band.'
                )
            ui.label(message).classes(f'text-xs font-bold {tone}')
            result_label = ui.label('').classes('text-xs font-semibold text-emerald-800')
            error_label = ui.label('').classes('text-xs font-semibold text-red-600')

            def handle_retry() -> None:
                error_label.text = ''
                try:
                    outcome = retry_delivery(citizen_id, officer)
                except Exception as error:
                    error_label.text = f'⚠ Credential retry failed: {error}'
                    return
                if outcome['delivery_status'] == DELIVERY_SENT:
                    result_label.text = (
                        f"Retry accepted via {outcome['delivery_channel']}: {outcome['delivery_detail']}. "
                        f"Attempts so far: {outcome['delivery_attempts']}."
                    )
                else:
                    result_label.text = (
                        f"Retry not delivered ({outcome['delivery_status']}) via "
                        f"{outcome['delivery_channel']}: {outcome['delivery_detail']}. "
                        f"Attempts so far: {outcome['delivery_attempts']}. The citizen can still use the "
                        'secure activation or password reset option on the registration status page.'
                    )
                ui.notify('Credential delivery re-attempted.', type='positive')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                ui.button(
                    'Retry Credential Delivery',
                    icon='forward_to_inbox',
                    on_click=handle_retry,
                ).props('unelevated dense').classes(
                    'bg-blue-900 hover:bg-blue-950 text-white font-bold rounded-xl px-4 py-2 text-xs shadow-sm'
                )
                ui.label(
                    'Each retry mints a fresh single-use link; the previous link stops working immediately.'
                ).classes('text-[10px] text-slate-500 self-center')


def _open_action_dialog(action: str, title: str, description: str, button_label: str,
                        button_class: str, require_remarks: bool, user: dict, application: dict) -> None:
    with ui.dialog() as dialog, ui.card().classes('w-full max-w-lg p-6 rounded-3xl bg-white shadow-2xl gap-4'):
        with ui.row().classes('w-full items-start justify-between'):
            with ui.column().classes('gap-0'):
                ui.label(title).classes('text-xl font-black text-slate-900 fantasy-title')
                ui.label(f"{application.get('full_name')} · {application.get('reference')}").classes(
                    'text-[11px] font-mono text-slate-500'
                )
            ui.button(icon='close', on_click=dialog.close).props('flat round dense').classes('text-slate-400')

        ui.label(description).classes('text-xs text-slate-600 leading-relaxed')

        remarks_input = ui.textarea(
            'Remarks *' if require_remarks else 'Remarks (optional)',
            placeholder='Record the reason for this verification decision...',
        ).props('outlined rows=4').classes('w-full')

        error_label = ui.label('').classes('text-xs text-red-600 font-semibold')

        def submit_action() -> None:
            try:
                updated = record_application_action(
                    application['id'], user, action, remarks_input.value or ''
                ) or {}
                credentials = updated.get('credentials')
                if action == 'APPROVE' and credentials:
                    if credentials.get('delivery_status') == DELIVERY_SENT:
                        ui.notify(
                            f"Application approved. Login username {credentials['username']} issued; "
                            f"the notice was accepted for delivery over {credentials.get('delivery_channel')}.",
                            type='positive',
                        )
                    else:
                        ui.notify(
                            f"Application approved. Login username {credentials['username']} issued, but the "
                            f"credential notice was not delivered ({credentials.get('delivery_status')} via "
                            f"{credentials.get('delivery_channel')}). The secure activation option on the "
                            'citizen status page still works.',
                            type='warning',
                        )
                elif action == 'APPROVE' and updated.get('credentials_error'):
                    error_label.text = f"⚠ Approved, but credential issuance failed: {updated['credentials_error']}"
                    return
                else:
                    ui.notify(
                        f"Application {application.get('reference')} updated: "
                        f"{status_label(application.get('status')) if action == 'REMARK' else title}",
                        type='positive',
                    )
                dialog.close()
                ui.navigate.to(f"/verification/citizens/{application['id']}")
            except PermissionError as error:
                error_label.text = f'⚠ {error}'
            except ValueError as error:
                error_label.text = f'⚠ {error}'
            except Exception as error:
                error_label.text = f'⚠ {error}'

        with ui.row().classes('w-full justify-end gap-2 pt-2'):
            ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-slate-600 font-bold')
            ui.button(button_label, on_click=submit_action).props('unelevated').classes(
                f'{button_class} text-white font-bold rounded-xl px-5 py-2 text-xs shadow-sm'
            )

    dialog.open()


@ui.page('/verification/citizens/{application_id}')
def citizen_application_detail_page(application_id: str) -> None:
    """Individual citizen registration verification page."""
    user = require_verification_officer()
    if not user:
        return

    application = get_citizen_application(application_id)
    if not application:
        with portal_page('verification', '/verification/citizens', 'Application Not Found', ''):
            ui.label('This citizen application could not be found.').classes('text-sm font-bold text-red-600')
            ui.button('Back to Citizen Verification', on_click=lambda: ui.navigate.to('/verification/citizens')).props('flat')
        return

    events = get_application_events(application_id)
    status = application.get('status', 'PENDING')
    is_terminal = status in ('APPROVED', 'REJECTED')

    portal_page_context = portal_page(
        'verification',
        '/verification/citizens',
        f"Citizen Verification — {application.get('reference')}",
        f"Applicant: {application.get('full_name')}",
    )

    with portal_page_context:
        with ui.row().classes('w-full items-center justify-between flex-wrap gap-3'):
            ui.button(
                '← Back to Citizen Verification',
                icon='arrow_back',
                on_click=lambda: ui.navigate.to('/verification/citizens'),
            ).props('flat').classes('text-slate-600 font-bold text-xs')
            _status_badge(status)

        if is_terminal:
            tone = 'bg-emerald-50 border-emerald-200 text-emerald-900' if status == 'APPROVED' else 'bg-red-50 border-red-200 text-red-900'
            with ui.card().classes(f'w-full p-4 rounded-2xl border {tone}'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('verified' if status == 'APPROVED' else 'block', size='sm')
                    ui.label(
                        f"This application is {status_label(status).lower()} and is locked for further decisions. "
                        'Internal remarks can still be recorded.'
                    ).classes('text-xs font-bold')

        # ── 1. Personal Information ─────────────────────────────────────
        with ui.card().classes('w-full p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-4 pb-2 border-b border-slate-100'):
                ui.icon('person', size='sm').classes('text-emerald-800')
                ui.label('1. Personal Information').classes('text-lg font-bold text-slate-900 fantasy-title')
            with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 gap-3 w-full'):
                _info_row('Full Name', application.get('full_name') or '', 'badge')
                _info_row('Date of Birth', application.get('date_of_birth') or 'Not provided', 'cake')
                _info_row('Gender', application.get('gender') or 'Not provided', 'wc')
                _info_row('Mobile Number', application.get('mobile') or '', 'phone')
                _info_row('Email Address', application.get('email') or '', 'email')
                _info_row('District', application.get('district') or '', 'location_city')
                _info_row('State / Union Territory', application.get('state') or '', 'map')
                with ui.column().classes('md:col-span-2 w-full p-3 rounded-xl bg-slate-50 border border-slate-200 gap-1'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('home', size='xs').classes('text-emerald-700')
                        ui.label('Residential Address').classes('text-xs font-bold text-slate-600')
                    ui.label(application.get('address') or 'Not provided').classes('text-xs font-semibold text-slate-900')

        # ── 2. Photograph & 3. Government ID ────────────────────────────
        with ui.row().classes('w-full gap-4 flex-wrap items-stretch'):
            with ui.card().classes('flex-1 min-w-72 p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
                with ui.row().classes('items-center gap-2 mb-4 pb-2 border-b border-slate-100'):
                    ui.icon('photo_camera', size='sm').classes('text-emerald-800')
                    ui.label('2. Citizen Photograph').classes('text-lg font-bold text-slate-900 fantasy-title')
                if application.get('photo_path'):
                    photo_url = f"/api/v1/secure/citizen-applications/{application_id}/photo"
                    ui.image(photo_url).classes('w-full max-w-xs rounded-2xl border border-slate-200 bg-slate-100')
                    ui.label('Captured during registration. Served through an authenticated, non-public endpoint.').classes(
                        'text-[10px] text-slate-500 mt-2'
                    )

                    def open_photo() -> None:
                        with ui.dialog() as dialog, ui.card().classes('p-3 rounded-2xl bg-white max-w-3xl'):
                            ui.image(photo_url).classes('w-full rounded-xl')
                            ui.button('Close', on_click=dialog.close).props('flat').classes('self-end text-slate-600')
                        dialog.open()

                    ui.button('Open Full-Size Preview', icon='zoom_in', on_click=open_photo).props('flat dense no-caps').classes(
                        'text-[11px] font-bold text-emerald-800 mt-2'
                    )
                else:
                    with ui.column().classes('w-full items-center py-8 gap-2'):
                        ui.icon('hide_image', size='xl').classes('text-slate-300')
                        ui.label('No photograph on file.').classes('text-xs text-slate-500')

            with ui.card().classes('flex-1 min-w-72 p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
                with ui.row().classes('items-center gap-2 mb-4 pb-2 border-b border-slate-100'):
                    ui.icon('badge', size='sm').classes('text-emerald-800')
                    ui.label('3. Government Identity Document').classes('text-lg font-bold text-slate-900 fantasy-title')
                _info_row('Document Type', application.get('gov_id_type') or '', 'fingerprint')
                _info_row('Masked ID Number', application.get('gov_id_masked') or '', 'password')
                _info_row('Submission Status', 'Submitted', 'upload_file')
                _info_row('Review Status', status_label(status), 'fact_check')

                document_path = application.get('id_document_path') or ''
                if document_path:
                    document_url = f"/api/v1/secure/citizen-applications/{application_id}/document"
                    extension = os.path.splitext(document_path)[1].lower()
                    if extension == '.pdf':
                        ui.html(
                            f'<iframe src="{document_url}" style="width:100%;height:320px;border:1px solid #e2e8f0;border-radius:0.75rem" '
                            'title="Government ID document preview"></iframe>'
                        ).classes('w-full mt-3')
                    else:
                        ui.image(document_url).classes('w-full max-w-xs rounded-2xl border border-slate-200 bg-slate-100 mt-3')
                    ui.link('Open secure document in new tab ↗', document_url, new_tab=True).classes(
                        'text-[11px] font-bold text-emerald-800 mt-2'
                    )
                    ui.label(
                        f"File: {application.get('id_document_name') or 'Government ID'} · "
                        'Visible only to authorized verification staff.'
                    ).classes('text-[10px] text-slate-500 mt-1')
                else:
                    ui.label('No document uploaded.').classes('text-xs text-slate-500 mt-3')

        # ── 4. Account & Application Details ────────────────────────────
        with ui.card().classes('w-full p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-4 pb-2 border-b border-slate-100'):
                ui.icon('assignment_ind', size='sm').classes('text-emerald-800')
                ui.label('4. Account & Application Details').classes('text-lg font-bold text-slate-900 fantasy-title')
            with ui.element('div').classes('grid grid-cols-1 md:grid-cols-2 gap-3 w-full'):
                _info_row('Preferred Username (Login)', application.get('username') or '', 'account_circle')
                _info_row('Application Reference', application.get('reference') or '', 'tag')
                _info_row('Registration Date & Time', _format_timestamp(application.get('submitted_at')), 'event')
                _info_row('Current Verification Status', status_label(status), 'verified_user')
                _info_row('Reviewed By', application.get('reviewed_by_name') or 'Not reviewed yet', 'military_tech')
                _info_row('Reviewed At', _format_timestamp(application.get('reviewed_at')), 'schedule')
                if application.get('internal_remarks'):
                    with ui.column().classes('md:col-span-2 w-full p-3 rounded-xl bg-amber-50 border border-amber-200 gap-1'):
                        ui.label('Latest Internal Remark').classes('text-[10px] font-bold text-amber-800 uppercase')
                        ui.label(application['internal_remarks']).classes('text-xs text-amber-950 font-medium')

        # ── 5. Citizen Login Credentials ────────────────────────────────
        if status == 'APPROVED':
            _credentials_card(application, user)

        # ── Verification Actions ────────────────────────────────────────
        with ui.card().classes('w-full p-6 rounded-3xl bg-white border-2 border-emerald-800/20 shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-3'):
                ui.icon('gavel', size='sm').classes('text-emerald-800')
                ui.label('Verification Actions').classes('text-lg font-bold text-slate-900 fantasy-title')
            ui.label(
                'Every decision is recorded with your officer identity and a server-side timestamp in the application history.'
            ).classes('text-[11px] text-slate-500 mb-4')

            with ui.row().classes('w-full gap-2 flex-wrap'):
                if not is_terminal:
                    ui.button(
                        'Approve Application',
                        icon='check_circle',
                        on_click=lambda: _open_action_dialog(
                            'APPROVE', 'Approve Citizen Application',
                            'Approving activates the account and issues a unique username, a single-use '
                            'activation link and the citizen notification.',
                            'Approve ✓', 'bg-emerald-700 hover:bg-emerald-800', False, user, application,
                        ),
                    ).props('unelevated').classes('font-bold rounded-xl px-4 py-2 text-xs text-white shadow-sm')

                    ui.button(
                        'Reject Application',
                        icon='cancel',
                        on_click=lambda: _open_action_dialog(
                            'REJECT', 'Reject Citizen Application',
                            'Rejection suspends the account. State a clear reason; it is shared with the applicant.',
                            'Reject ✕', 'bg-red-700 hover:bg-red-800', True, user, application,
                        ),
                    ).props('unelevated').classes('font-bold rounded-xl px-4 py-2 text-xs text-white shadow-sm')

                    ui.button(
                        'Request Additional Information',
                        icon='contact_support',
                        on_click=lambda: _open_action_dialog(
                            'REQUEST_INFO', 'Request Additional Information',
                            'The applicant is notified and the application remains open until re-reviewed.',
                            'Send Request', 'bg-amber-600 hover:bg-amber-700', True, user, application,
                        ),
                    ).props('unelevated').classes('font-bold rounded-xl px-4 py-2 text-xs text-white shadow-sm')

                ui.button(
                    'Add Internal Verification Remarks',
                    icon='sticky_note_2',
                    on_click=lambda: _open_action_dialog(
                        'REMARK', 'Add Internal Verification Remarks',
                        'Internal remarks are stored in the audit history and never shown as a public status change.',
                        'Save Remark', 'bg-slate-700 hover:bg-slate-800', True, user, application,
                    ),
                ).props('unelevated').classes('font-bold rounded-xl px-4 py-2 text-xs text-white shadow-sm')

        # ── Verification History ────────────────────────────────────────
        with ui.card().classes('w-full p-6 rounded-3xl bg-white border border-slate-200 shadow-sm'):
            with ui.row().classes('items-center gap-2 mb-4'):
                ui.icon('history', size='sm').classes('text-emerald-800')
                ui.label('Verification History').classes('text-lg font-bold text-slate-900 fantasy-title')

            if not events:
                ui.label('No verification history recorded.').classes('text-xs text-slate-500')
            else:
                with ui.column().classes('w-full gap-3'):
                    for event in events:
                        with ui.row().classes('w-full items-start gap-3'):
                            with ui.element('div').classes(
                                'w-9 h-9 rounded-full flex-shrink-0 flex items-center justify-center bg-emerald-100 text-emerald-800'
                            ):
                                ui.icon(ACTION_ICONS.get(event.get('action'), 'info'), size='xs')
                            with ui.card().classes('flex-1 p-4 rounded-2xl bg-slate-50 border border-slate-200 shadow-xs'):
                                with ui.row().classes('w-full justify-between items-start flex-wrap gap-1'):
                                    ui.label(
                                        (event.get('action') or '').replace('_', ' ').title()
                                    ).classes('text-sm font-bold text-slate-900')
                                    ui.label(_format_timestamp(event.get('created_at'))).classes(
                                        'text-[10px] text-slate-400 font-mono'
                                    )
                                actor = event.get('actor_name') or 'System'
                                role = (event.get('actor_role') or '').replace('_', ' ').title()
                                badge = event.get('actor_badge')
                                actor_line = f"{role} · {actor}" + (f" ({badge})" if badge and badge != 'N/A' else '')
                                ui.label(actor_line).classes('text-[10px] text-slate-500 font-semibold mt-0.5')
                                if event.get('status_from') or event.get('status_to'):
                                    ui.label(
                                        f"Status: {status_label(event.get('status_from')) if event.get('status_from') else '—'}"
                                        f" → {status_label(event.get('status_to'))}"
                                    ).classes('text-[10px] text-slate-500 font-mono mt-0.5')
                                if event.get('remarks'):
                                    ui.label(event['remarks']).classes('text-xs text-slate-700 mt-1 leading-relaxed')

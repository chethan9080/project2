"""
Public Citizen Registration Application Status Page.

Allows a citizen whose registration is not yet approved to:
- check the live status of their application using the reference plus
  their registered email address or mobile number
- submit additional information requested by a Verification Officer
- see the officer's rejection reason when an application is rejected

This page is intentionally reachable without an approved session because the
citizen is blocked from the dashboard until verification completes.
"""

import os

from nicegui import ui, app as nicegui_app, background_tasks

from frontend.components.navbar import create_public_header
from backend.services.citizen_registration_service import (
    find_application_for_status,
    get_application_events,
    resubmit_additional_information,
    status_label,
)
from backend.services.realtime_events import subscribe, unsubscribe

STATUS_STYLES = {
    'PENDING': ('Pending Review', 'bg-amber-50 border-amber-200', 'hourglass_top', 'text-amber-600'),
    'UNDER_REVIEW': ('Under Review', 'bg-blue-50 border-blue-200', 'manage_search', 'text-blue-600'),
    'ADDITIONAL_INFO_REQUIRED': (
        'Additional Information Required', 'bg-orange-50 border-orange-300', 'contact_support', 'text-orange-600'
    ),
    'APPROVED': ('Approved', 'bg-emerald-50 border-emerald-300', 'verified', 'text-emerald-600'),
    'REJECTED': ('Rejected', 'bg-rose-50 border-rose-200', 'cancel', 'text-rose-600'),
}


def _latest_event(application_id: str):
    events = get_application_events(application_id)
    return events[-1] if events else None


@ui.page('/citizen/application-status')
def citizen_application_status_page() -> None:
    """Public registration status and additional-information submission page."""
    ui.page_title('Application Status | eKSP Online FIR Portal')
    create_public_header()

    storage = nicegui_app.storage.user
    state = {
        'application': None,
        'extra_document': None,
        'extra_photo': None,
    }

    with ui.column().classes('w-full min-h-screen items-center p-6 pt-10 bg-[#F8FAFC]'):
        with ui.card().classes('w-full max-w-2xl p-8 rounded-3xl paper-card border border-slate-200 shadow-md bg-white'):
            with ui.row().classes('items-center justify-between w-full mb-3'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('fact_check', size='sm').classes('text-blue-800')
                    ui.label('CITIZEN REGISTRATION STATUS').classes('font-bold text-xs text-blue-900 tracking-widest')
                ui.badge('NO SIGN-IN REQUIRED').classes('bg-blue-100 text-blue-900 text-[10px] font-bold')

            ui.label('Track Your Registration').classes('text-3xl font-black text-slate-900 fantasy-title')
            ui.label(
                'Portal access is enabled only after a Verification Officer approves your application. '
                'Check your status below using the reference number issued at registration.'
            ).classes('text-xs text-slate-600 mt-1')

            ui.separator().classes('my-4')

            with ui.column().classes('w-full gap-3'):
                ref_input = ui.input(
                    'Application Reference *',
                    value=storage.get('pending_application_reference') or '',
                    placeholder='CVR-YYYYMMDD-XXXXXX',
                ).classes('w-full')
                ident_input = ui.input(
                    'Registered Email or Mobile *',
                    value=storage.get('pending_application_email') or '',
                    placeholder='name@example.com or 10-digit mobile',
                ).classes('w-full')
                lookup_error = ui.label('').classes('text-red-600 text-xs font-semibold')

                def run_lookup(event=None) -> None:
                    reference = (ref_input.value or '').strip()
                    identifier = (ident_input.value or '').strip()
                    if not reference or not identifier:
                        lookup_error.text = '⚠ Enter your application reference and registered email or mobile.'
                        return
                    application = find_application_for_status(reference, identifier)
                    if not application:
                        state['application'] = None
                        lookup_error.text = '⚠ No application matches that reference and email/mobile.'
                        render_result()
                        return
                    lookup_error.text = ''
                    storage['pending_application_reference'] = application['reference']
                    storage['pending_application_email'] = identifier.lower()
                    state['application'] = application
                    render_result()

                with ui.row().classes('w-full gap-2'):
                    ui.button('Check Status', icon='search', on_click=run_lookup).props(
                        'unelevated'
                    ).classes('flex-1 bg-blue-800 hover:bg-blue-900 text-white font-bold rounded-xl py-3 text-sm')
                    ui.button('Clear', icon='refresh', on_click=lambda: _clear_state()).props(
                        'flat'
                    ).classes('text-slate-600 font-semibold')

            def _clear_state() -> None:
                state['application'] = None
                ref_input.value = ''
                ident_input.value = ''
                lookup_error.text = ''
                render_result()

        result_container = ui.column().classes('w-full max-w-2xl mt-4')

        def render_result() -> None:
            result_container.clear()
            application = state['application']
            if not application:
                return
            application_status = (application.get('status') or 'PENDING').upper()
            label, card_style, icon_name, icon_color = STATUS_STYLES.get(
                application_status,
                ('Pending Review', 'bg-slate-50 border-slate-200', 'hourglass_top', 'text-slate-600'),
            )
            latest = _latest_event(application['id'])
            with result_container:
                with ui.card().classes(f'w-full p-6 border rounded-3xl shadow-sm bg-white {card_style}'):
                    with ui.row().classes('w-full items-center justify-between flex-wrap gap-3 pb-3 border-b border-slate-200/70'):
                        with ui.row().classes('items-center gap-3'):
                            with ui.element('div').classes(
                                'w-11 h-11 rounded-xl flex items-center justify-center bg-white border border-slate-200'
                            ):
                                ui.icon(icon_name, size='sm').classes(icon_color)
                            with ui.column().classes('gap-0'):
                                ui.label('Registration Verification').classes('text-base font-bold text-slate-900 fantasy-title')
                                ui.label(f"Reference: {application.get('reference', '—')}").classes(
                                    'text-[11px] text-slate-600 font-mono'
                                )
                        ui.badge(label).classes(
                            'bg-emerald-700 text-white font-bold text-xs px-3 py-1 rounded-full'
                            if application_status == 'APPROVED'
                            else 'bg-rose-700 text-white font-bold text-xs px-3 py-1 rounded-full'
                            if application_status == 'REJECTED'
                            else 'bg-white text-slate-800 border border-slate-300 font-bold text-xs px-3 py-1 rounded-full'
                        )

                    with ui.row().classes('w-full gap-6 flex-wrap pt-3 text-xs'):
                        with ui.column().classes('gap-0.5'):
                            ui.label('Applicant').classes('text-[10px] uppercase tracking-wide text-slate-500 font-bold')
                            ui.label(application.get('full_name', '—')).classes('font-semibold text-slate-800')
                        with ui.column().classes('gap-0.5'):
                            ui.label('Submitted').classes('text-[10px] uppercase tracking-wide text-slate-500 font-bold')
                            ui.label(str(application.get('submitted_at', '—'))[:19].replace('T', ' ')).classes(
                                'font-mono text-slate-800'
                            )
                        with ui.column().classes('gap-0.5'):
                            ui.label('Government ID').classes('text-[10px] uppercase tracking-wide text-slate-500 font-bold')
                            ui.label(
                                f"{application.get('gov_id_type', '—')} · {application.get('gov_id_masked', '—')}"
                            ).classes('font-mono text-slate-800')

                    if application_status == 'APPROVED':
                        ui.label(
                            'Your citizen account has been approved. You can now sign in and use the Citizen Portal.'
                        ).classes('text-xs font-semibold text-emerald-800 mt-4')
                        ui.button(
                            'Sign In to Citizen Portal',
                            icon='login',
                            on_click=lambda: ui.navigate.to('/login'),
                        ).props('unelevated').classes(
                            'mt-3 bg-emerald-700 text-white font-bold rounded-xl px-5 py-2.5 text-xs'
                        )
                    elif application_status == 'REJECTED':
                        ui.label(
                            f"Reason: {(latest or {}).get('remarks') or 'Not provided'}"
                        ).classes('text-xs font-semibold text-rose-800 mt-4')
                        ui.label(
                            'If you believe this decision is incorrect, contact the Verification Desk with your reference number.'
                        ).classes('text-[11px] text-rose-700 mt-1')
                    elif application_status == 'ADDITIONAL_INFO_REQUIRED':
                        ui.label(
                            f"Officer request: {(latest or {}).get('remarks') or 'Please provide the requested details.'}"
                        ).classes('text-xs font-semibold text-orange-800 mt-4')
                        _render_resubmission_form(application, state, render_result)
                    elif application_status == 'UNDER_REVIEW':
                        ui.label(
                            'A Verification Officer is currently reviewing your documents.'
                        ).classes('text-xs font-semibold text-blue-800 mt-4')
                    else:
                        ui.label(
                            'Your application is queued for review by a Verification Officer.'
                        ).classes('text-xs font-semibold text-amber-800 mt-4')

        render_result()

        if state['application'] is None and ref_input.value and ident_input.value:
            run_lookup()

        client = ui.context.client
        event_queue = subscribe()

        async def listen_for_status_changes() -> None:
            while True:
                event = await event_queue.get()
                application = state['application']
                if not application or event.get('citizen_id') != application.get('citizen_id'):
                    continue
                refreshed = find_application_for_status(
                    storage.get('pending_application_reference') or application['reference'],
                    storage.get('pending_application_email') or application.get('email') or '',
                )
                if not refreshed:
                    continue
                state['application'] = refreshed
                with client:
                    render_result()
                    ui.notify(
                        f"Registration status updated: {status_label(refreshed.get('status'))}",
                        type='positive' if refreshed.get('status') == 'APPROVED' else 'info',
                    )

        listener = background_tasks.create(listen_for_status_changes(), name='application-status-watch')
        client.on_disconnect(lambda: (unsubscribe(event_queue), listener.cancel()))


def _render_resubmission_form(application, state, refresh) -> None:
    """Render the additional-information form for an application awaiting a citizen reply."""
    with ui.column().classes('w-full gap-3 mt-4 pt-4 border-t border-orange-200/70'):
        ui.label('Submit the requested information').classes('text-sm font-bold text-slate-900')
        note_input = ui.textarea(
            'Your response *',
            placeholder='Describe or paste the additional information requested by the officer.',
        ).classes('w-full').props('outlined autogrow')

        doc_status = ui.label('No replacement ID document attached (optional).').classes('text-[11px] text-slate-500')
        photo_status = ui.label('No replacement photograph attached (optional).').classes('text-[11px] text-slate-500')
        form_error = ui.label('').classes('text-red-600 text-xs font-semibold')

        async def handle_document_upload(event) -> None:
            try:
                data = await event.file.read()
                extension = os.path.splitext(event.file.name or '')[1].lower()
                if extension not in ('.pdf', '.png', '.jpg', '.jpeg'):
                    doc_status.text = '⚠ Unsupported file type. Upload a PDF, JPG, or PNG.'
                    return
                if not data:
                    doc_status.text = '⚠ The selected document is empty.'
                    return
                state['extra_document'] = (data, extension, event.file.name)
                doc_status.text = f'✅ {event.file.name} attached ({len(data) // 1024} KB).'
            except Exception as error:
                doc_status.text = f'⚠ Could not read the document: {error}'

        async def handle_photo_upload(event) -> None:
            try:
                data = await event.file.read()
                extension = os.path.splitext(event.file.name or '')[1].lower()
                if extension not in ('.png', '.jpg', '.jpeg'):
                    photo_status.text = '⚠ Unsupported file type. Upload a JPG or PNG.'
                    return
                if not data:
                    photo_status.text = '⚠ The selected photograph is empty.'
                    return
                state['extra_photo'] = (data, extension)
                photo_status.text = f'✅ Photograph attached ({len(data) // 1024} KB).'
            except Exception as error:
                photo_status.text = f'⚠ Could not read the photograph: {error}'

        with ui.row().classes('w-full gap-3 flex-wrap'):
            with ui.column().classes('flex-1 min-w-[240px] gap-1'):
                ui.upload(
                    label='Replace ID document (optional)',
                    auto_upload=True,
                    max_files=1,
                    max_file_size=5_000_000,
                    on_upload=handle_document_upload,
                ).props('accept=.pdf,.png,.jpg,.jpeg flat bordered').classes('w-full')
                doc_status
            with ui.column().classes('flex-1 min-w-[240px] gap-1'):
                ui.upload(
                    label='Replace photograph (optional)',
                    auto_upload=True,
                    max_files=1,
                    max_file_size=5_000_000,
                    on_upload=handle_photo_upload,
                ).props('accept=.png,.jpg,.jpeg flat bordered').classes('w-full')
                photo_status

        async def submit_additional_information() -> None:
            note = (note_input.value or '').strip()
            if not note:
                form_error.text = '⚠ Please describe the additional information requested.'
                return
            document = state.get('extra_document')
            photo = state.get('extra_photo')
            try:
                updated = resubmit_additional_information(
                    application['id'],
                    reference=application['reference'],
                    identifier=application.get('email') or '',
                    note=note,
                    document_bytes=document[0] if document else None,
                    document_ext=document[1] if document else None,
                    document_name=document[2] if document else None,
                    photo_bytes=photo[0] if photo else None,
                    photo_ext=photo[1] if photo else None,
                )
            except (ValueError, PermissionError) as error:
                form_error.text = f'⚠ {error}'
                return
            state['application'] = updated
            state['extra_document'] = None
            state['extra_photo'] = None
            ui.notify('Additional information submitted. Your application is back under review.', type='positive')
            refresh()

        ui.button(
            'Submit Additional Information',
            icon='send',
            on_click=submit_additional_information,
        ).props('unelevated').classes(
            'w-full bg-orange-600 hover:bg-orange-700 text-white font-bold rounded-xl py-3 text-sm'
        )
        form_error

    with ui.row().classes('w-full justify-center text-xs text-slate-600 mt-2 gap-1.5'):
        ui.label('Need help?')
        ui.link('Return to Citizen Login', '/login').classes('font-bold text-blue-700 hover:underline')

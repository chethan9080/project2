"""
Real-time case messaging between citizens and their assigned investigating officer.

Routes:
  /citizen/chat, /citizen/chat/{fir_id}, /citizen/complaint-chat/{complaint_id}
  /police/chat,  /police/chat/{fir_id},  /police/complaint-chat/{complaint_id}

Threads are resolved and authorised in ``backend.services.chat_service``: a
citizen only ever reaches the officer assigned to their case, and an officer only
ever reaches the citizens whose cases are assigned to them. New messages reach
open pages through the in-process event bus, so nobody has to refresh.
"""

from typing import Any, Dict, List, Optional

from nicegui import background_tasks, ui

from frontend.i18n import t
from frontend.components.sidebar import create_sidebar
from backend.services.auth_service import (
    get_citizen_access_issue,
    get_current_user,
    get_dev_auto_login_user,
    set_current_user,
)
from backend.services.chat_service import (
    get_conversations,
    get_messages,
    get_thread,
    mark_thread_read,
    send_message,
    unread_total,
)
from backend.services.realtime_events import subscribe, unsubscribe


def _require_active_citizen() -> Optional[Dict[str, Any]]:
    """Return the signed-in citizen only when their registration is approved."""
    user = get_current_user()
    if not user or user.get('role') != 'CITIZEN':
        dev_user = get_dev_auto_login_user()
        if not dev_user:
            ui.navigate.to('/login')
            return None
        set_current_user(dev_user)
        user = dev_user
    if get_citizen_access_issue(user):
        set_current_user(None)
        ui.navigate.to('/login?verification=required')
        return None
    return user


def _require_officer() -> Optional[Dict[str, Any]]:
    user = get_current_user()
    if not user or user.get('role') != 'OFFICER':
        ui.navigate.to('/staff-portal')
        return None
    return user


def _listen(client, task_name: str, is_relevant, refresh) -> None:
    """Re-render the page whenever a chat event addressed to it is published."""
    queue = subscribe()

    async def listen_for_events() -> None:
        while True:
            event = await queue.get()
            event_type = event.get('type')
            if event_type not in ('CHAT_MESSAGE', 'CHAT_READ'):
                if event_type != 'NOTIFICATION_CREATED':
                    continue
                if (event.get('notification') or {}).get('type') != 'CHAT_MESSAGE':
                    continue
            if not is_relevant(event):
                continue
            with client:
                refresh()

    listener = background_tasks.create(listen_for_events(), name=task_name)

    def stop() -> None:
        unsubscribe(queue)
        listener.cancel()

    client.on_disconnect(stop)


def _case_identity(case_number: str, other_name: Optional[str], other_label: str,
                   complaint_reference: Optional[str] = None, is_complaint: bool = False) -> None:
    """Case number with the counterpart identity directly underneath."""
    ui.label(f"{'Complaint' if is_complaint else 'FIR No'}: {case_number}").classes(
        'font-black text-blue-800 text-sm font-mono')
    ui.label(f"{other_label}: {other_name or '—'}").classes('text-[11px] text-slate-500 font-semibold')
    if complaint_reference:
        ui.label(f"Complaint Ref: {complaint_reference}").classes('text-[10px] text-slate-400 font-mono')


# ─────────────────────────────────────────────────────────
# SHARED CHAT THREAD
# ─────────────────────────────────────────────────────────

def _render_chat_thread(case_id: str, current_user: Dict[str, Any], is_complaint: bool,
                        back_url: str) -> None:
    thread = get_thread(case_id, current_user, is_complaint=is_complaint)
    if not thread:
        ui.navigate.to(back_url)
        return

    is_officer = current_user.get('role') == 'OFFICER'
    other_id = thread['participant_id']
    other_label = 'Citizen' if is_officer else 'Officer'
    other_name = (thread.get('citizen_name') if is_officer else thread.get('officer_name')) or other_label

    with ui.row().classes('items-center gap-2 w-full'):
        ui.button(icon='arrow_back', on_click=lambda url=back_url: ui.navigate.to(url)).props(
            'flat round dense').classes('text-blue-700')
        ui.label(f"{t('Chat')} — {thread['case_number']}").classes('text-xl font-black text-slate-900')

    if not thread['can_chat'] or not other_id:
        with ui.card().classes('w-full p-10 rounded-2xl bg-white border border-amber-200 items-center text-center'):
            ui.icon('lock', size='xl').classes('text-amber-500')
            ui.label('Chat is not available yet').classes('text-base font-bold text-slate-800 mt-2')
            ui.label(t('Chat becomes available once an investigating officer is assigned to your case.')).classes(
                'text-xs text-slate-500 max-w-md mt-1')
        return

    mark_thread_read(case_id, current_user['id'], is_complaint)

    with ui.card().classes(
        'w-full px-5 py-3 rounded-t-2xl rounded-b-none border border-b-0 border-slate-200 '
        'bg-gradient-to-r from-blue-900 to-blue-700'
    ):
        with ui.row().classes('items-center gap-3 w-full'):
            with ui.element('div').classes('w-10 h-10 rounded-full bg-white/20 flex items-center justify-center'):
                ui.icon('person' if is_officer else 'local_police', size='sm').classes('text-white')
            with ui.column().classes('gap-0 flex-1'):
                ui.label(other_name).classes('text-white font-bold text-sm')
                ui.label(
                    f"{t(other_label)} · {'Complaint' if is_complaint else 'Case'}: {thread['case_number']}"
                ).classes('text-blue-200 text-xs')
            with ui.row().classes('items-center gap-1.5 px-3 py-1 bg-emerald-800/60 border border-emerald-500/40 rounded-full'):
                with ui.element('div').classes('w-2 h-2 rounded-full bg-emerald-300 animate-pulse'):
                    pass
                ui.label('LIVE').classes('text-emerald-100 text-[10px] font-bold')

    with ui.scroll_area().classes(
        'w-full border border-slate-200 border-t-0 border-b-0 bg-slate-50'
    ).style('height: 420px; min-height: 320px;') as scroll_area:
        messages_col = ui.column().classes('w-full gap-2 p-4')

        @ui.refreshable
        def thread_view() -> None:
            messages: List[Dict[str, Any]] = get_messages(case_id, is_complaint)
            messages_col.clear()
            with messages_col:
                if not messages:
                    with ui.column().classes('w-full items-center justify-center py-16 gap-2'):
                        ui.icon('chat_bubble_outline', size='xl').classes('text-slate-300')
                        ui.label(t('No messages yet.')).classes('text-slate-400 text-sm font-semibold')
                        ui.label(f"{t('Start a conversation regarding case')} {thread['case_number']}").classes(
                            'text-slate-400 text-xs')
                    return
                for msg in messages:
                    is_mine = msg['sender_id'] == current_user['id']
                    with ui.column().classes(f"w-full {'items-end' if is_mine else 'items-start'} gap-0.5"):
                        with ui.element('div').classes(
                            'max-w-[75%] px-4 py-2.5 shadow-sm '
                            + ('bg-blue-700 text-white rounded-2xl rounded-br-md' if is_mine
                               else 'bg-white border border-slate-200 text-slate-800 rounded-2xl rounded-bl-md')
                        ):
                            ui.label(msg['message']).classes('text-sm leading-relaxed')
                        with ui.row().classes('gap-1 items-center px-1'):
                            ui.label(t('You') if is_mine else msg.get('sender_name', other_name)).classes(
                                'text-[10px] text-slate-400 font-semibold')
                            ui.label(f"· {msg['sent_at'][:16].replace('T', ' ')} IST").classes(
                                'text-[10px] text-slate-400')
                            if msg['is_read']:
                                ui.icon('done_all', size='xxs').classes('text-blue-500')

        thread_view()

    with ui.card().classes(
        'w-full px-4 py-3 rounded-t-none rounded-b-2xl border border-t-0 border-slate-200 bg-white'
    ):
        with ui.row().classes('w-full items-end gap-2'):
            msg_input = ui.textarea(
                placeholder=f"Type a message to {other_name}…",
            ).props('rows=2 outlined dense').classes('flex-1 text-sm')

            def send() -> None:
                text = (msg_input.value or '').strip()
                if not text:
                    return
                try:
                    send_message(case_id, current_user, other_id, text, is_complaint=is_complaint)
                except (ValueError, PermissionError) as exc:
                    ui.notify(str(exc), type='negative')
                    return
                msg_input.value = ''
                thread_view.refresh()
                scroll_area.scroll_to(percent=1.0)

            msg_input.on('keydown.enter.ctrl', lambda _: send())
            ui.button(icon='send', on_click=send).props('unelevated round').classes(
                'bg-blue-700 hover:bg-blue-800 text-white w-11 h-11 shadow-md')

    ui.label('🔒 Messages are stored on the case audit trail. Press Ctrl+Enter to send. '
             'Supporting files are shared through the case evidence section, not the chat.').classes(
        'text-[10px] text-slate-400 mt-1 text-center w-full')

    participants = {current_user['id'], other_id, thread.get('citizen_id'), thread.get('assigned_officer_id')}

    def relevant(event: Dict[str, Any]) -> bool:
        case_ref = event.get('fir_id') or event.get('complaint_id')
        if case_ref:
            return case_ref == case_id
        return bool(event.get('user_id') in participants)

    _listen(ui.context.client, f'chat-thread-{case_id}', relevant, thread_view.refresh)
    ui.timer(25.0, thread_view.refresh)


# ─────────────────────────────────────────────────────────
# SHARED CONVERSATION HUB
# ─────────────────────────────────────────────────────────

def _render_conversation_hub(user: Dict[str, Any], role: str) -> None:
    is_officer = role == 'officer'
    create_sidebar('police' if is_officer else 'citizen', '/police/chat' if is_officer else '/citizen/chat')

    with ui.column().classes('w-full max-w-6xl mx-auto p-6 gap-5'):
        with ui.row().classes('items-center gap-3'):
            ui.icon('chat', size='md').classes('text-blue-800')
            with ui.column().classes('gap-0'):
                ui.label('Chat with Citizens' if is_officer else t('Chat with Your Officer')).classes(
                    'text-2xl font-black text-slate-900')
                ui.label(
                    'Conversation with the citizens whose cases are assigned to you.' if is_officer
                    else t('Communicate directly with the officer assigned to your verified case.')
                ).classes('text-xs text-slate-500')

        @ui.refreshable
        def conversations_view() -> None:
            unread = unread_total(user['id'])
            if unread:
                with ui.card().classes('w-full p-3 bg-blue-50 border border-blue-200 rounded-xl'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('mark_chat_unread', size='xs').classes('text-blue-700')
                        ui.label(f"{t('You have')} {unread} unread message{'s' if unread > 1 else ''}.").classes(
                            'text-sm font-bold text-blue-800')

            conversations = get_conversations(user)
            if not conversations:
                with ui.card().classes(
                    'w-full p-10 rounded-2xl bg-white border border-slate-200 shadow items-center text-center'
                ):
                    ui.icon('inbox', size='xl').classes('text-slate-300')
                    ui.label(t('No conversations available yet.')).classes('text-slate-500 font-bold mt-2')
                    ui.label(
                        'Conversations appear here as soon as cases are assigned to you.' if is_officer
                        else t('File an FIR first. Once an investigating officer is assigned to your case, chat becomes available here.')
                    ).classes('text-xs text-slate-400 mt-1 max-w-sm')
                    if not is_officer:
                        ui.button(t('File an FIR'), icon='add_circle',
                                  on_click=lambda: ui.navigate.to('/citizen/submit')).props('unelevated').classes(
                            'mt-4 bg-blue-700 text-white font-bold rounded-xl px-6')
                return

            with ui.row().classes('w-full flex-wrap gap-4'):
                for conv in conversations:
                    can_open = bool(conv['chat_available'])
                    open_url = conv['open_url'] if can_open else ('/police/firs' if is_officer else '/citizen/complaints')
                    is_complaint = conv['kind'] == 'complaint'
                    with ui.card().classes(
                        'flex-1 min-w-[300px] max-w-[420px] p-5 rounded-2xl bg-white border border-slate-200 '
                        'shadow hover:shadow-md'
                    ):
                        with ui.row().classes('items-start justify-between w-full gap-2'):
                            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                                _case_identity(
                                    conv['case_number'], conv.get('other_name'),
                                    'Citizen' if is_officer else 'Officer',
                                    conv.get('complaint_reference'),
                                    is_complaint=is_complaint,
                                )
                                ui.label(conv.get('title') or '—').classes(
                                    'text-xs text-slate-600 font-semibold line-clamp-1')
                            ui.badge(str(conv.get('status') or '').replace('_', ' ').title()).classes(
                                'bg-slate-100 text-slate-700 border border-slate-200 text-[9px] font-bold px-2 rounded-full')

                        with ui.row().classes(
                            'items-center gap-2 w-full mt-3 p-2.5 rounded-xl bg-slate-50 border border-slate-100'
                        ):
                            ui.icon('chat_bubble' if conv.get('last_message') else 'inbox', size='xs').classes(
                                'text-slate-400')
                            with ui.column().classes('gap-0 flex-1 min-w-0'):
                                ui.label(conv.get('last_message') or 'No messages yet').classes(
                                    'text-xs font-medium text-slate-600 truncate w-full')
                                ui.label(
                                    str(conv.get('last_at') or '')[:16].replace('T', ' ') or 'No activity'
                                ).classes('text-[10px] text-slate-400 font-mono')
                            if conv.get('unread'):
                                ui.badge(str(conv['unread'])).classes(
                                    'bg-red-600 text-white text-[10px] font-bold rounded-full')

                        ui.button(
                            t('Open Chat →') if can_open else 'Awaiting officer assignment',
                            icon='chat' if can_open else 'hourglass_empty',
                            on_click=lambda url=open_url: ui.navigate.to(url),
                        ).props('unelevated' if can_open else 'flat').classes(
                            'w-full mt-3 font-bold rounded-xl text-xs py-2 '
                            + ('bg-blue-700 hover:bg-blue-800 text-white' if can_open
                               else 'bg-slate-100 text-slate-400'))

        conversations_view()

        def relevant(event: Dict[str, Any]) -> bool:
            if event.get('type') == 'NOTIFICATION_CREATED':
                return event.get('user_id') == user['id']
            return user['id'] in {event.get('sender_id'), event.get('receiver_id'),
                                  event.get('citizen_id'), event.get('officer_id'), event.get('user_id')}

        _listen(ui.context.client, f'chat-hub-{role}', relevant, conversations_view.refresh)
        ui.timer(25.0, conversations_view.refresh)


# ─────────────────────────────────────────────────────────
# CITIZEN CHAT PAGES
# ─────────────────────────────────────────────────────────

@ui.page('/citizen/chat')
def citizen_chat_page() -> None:
    """Citizen chat hub — every case that already has an assigned officer."""
    ui.page_title(t('Chat with Officer | Citizen Portal'))
    user = _require_active_citizen()
    if not user:
        return
    _render_conversation_hub(user, 'citizen')


@ui.page('/citizen/chat/{fir_id}')
def citizen_chat_thread(fir_id: str) -> None:
    """Citizen ↔ assigned officer thread for one FIR."""
    ui.page_title(t('Chat | Citizen Portal'))
    user = _require_active_citizen()
    if not user:
        return
    create_sidebar('citizen', '/citizen/chat')
    with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-4'):
        _render_chat_thread(fir_id, user, False, '/citizen/chat')


@ui.page('/citizen/complaint-chat/{complaint_id}')
def citizen_complaint_chat_thread(complaint_id: str) -> None:
    """Citizen ↔ assigned officer thread for a complaint that has no FIR yet."""
    ui.page_title(t('Chat | Citizen Portal'))
    user = _require_active_citizen()
    if not user:
        return
    create_sidebar('citizen', '/citizen/complaints')
    with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-4'):
        _render_chat_thread(complaint_id, user, True, '/citizen/complaints')


# ─────────────────────────────────────────────────────────
# OFFICER CHAT PAGES
# ─────────────────────────────────────────────────────────

@ui.page('/police/chat')
def officer_chat_page() -> None:
    """Officer chat hub — every assigned citizen case with its latest message."""
    ui.page_title('Chat with Citizens | Officer Portal')
    user = _require_officer()
    if not user:
        return
    _render_conversation_hub(user, 'officer')


@ui.page('/police/chat/{fir_id}')
def officer_chat_thread(fir_id: str) -> None:
    """Officer ↔ citizen thread for one assigned FIR."""
    ui.page_title('Chat | Officer Portal')
    user = _require_officer()
    if not user:
        return
    create_sidebar('police', '/police/chat')
    with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-4'):
        _render_chat_thread(fir_id, user, False, '/police/chat')


@ui.page('/police/complaint-chat/{complaint_id}')
def officer_complaint_chat_thread(complaint_id: str) -> None:
    """Officer ↔ citizen thread for an assigned complaint without an FIR."""
    ui.page_title('Chat | Officer Portal')
    user = _require_officer()
    if not user:
        return
    create_sidebar('police', '/police/chat')
    with ui.column().classes('w-full max-w-4xl mx-auto p-6 gap-4'):
        _render_chat_thread(complaint_id, user, True, '/police/chat')

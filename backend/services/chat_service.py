"""
Case-scoped conversation service shared by the Citizen and Police portals.

Every message is stored against its FIR (or, before an FIR exists, its
complaint), so a thread stays intact when a case is reassigned: the new
investigating officer inherits the full history and the previous officer loses
access because access follows the current assignment. New messages are pushed
to open pages through the realtime event bus instead of database polling.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from backend.services.db import get_db_connection
from backend.services.notification_service import create_notification


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _publish(event_type: str, case_id: str, is_complaint: bool, **extra) -> None:
    try:
        from backend.services.realtime_events import publish
        publish({
            'type': event_type,
            'fir_id': None if is_complaint else case_id,
            'complaint_id': case_id if is_complaint else None,
            **extra,
        })
    except Exception:
        pass


def _column(is_complaint: bool) -> str:
    return 'complaint_id' if is_complaint else 'fir_id'


def get_thread(case_id: str, user: Dict[str, Any], is_complaint: bool = False) -> Optional[Dict[str, Any]]:
    """Resolve a conversation thread and confirm ``user`` is authorised to open it."""
    col = _column(is_complaint)
    conn = get_db_connection()
    if is_complaint:
        row = conn.execute("""
            SELECT c.id AS case_id, c.reference AS case_number, c.title, c.status,
                   c.citizen_id, c.assigned_officer_id, c.fir_id,
                   cu.name AS citizen_name, cu.phone AS citizen_phone,
                   ou.name AS officer_name, ou.badge_number, ou.rank
            FROM complaints c
            LEFT JOIN users cu ON c.citizen_id = cu.id
            LEFT JOIN users ou ON c.assigned_officer_id = ou.id
            WHERE c.id = ?
        """, (case_id,)).fetchone()
    else:
        row = conn.execute("""
            SELECT f.id AS case_id, f.fir_number AS case_number, f.incident_type AS title, f.status,
                   f.citizen_id, f.assigned_officer_id, f.complaint_id, f.reference_number,
                   cu.name AS citizen_name, cu.phone AS citizen_phone,
                   ou.name AS officer_name, ou.badge_number, ou.rank,
                   c.reference AS complaint_reference
            FROM firs f
            LEFT JOIN users cu ON f.citizen_id = cu.id
            LEFT JOIN users ou ON f.assigned_officer_id = ou.id
            LEFT JOIN complaints c ON f.complaint_id = c.id
            WHERE f.id = ?
        """, (case_id,)).fetchone()
    conn.close()
    if not row:
        return None
    thread = dict(row)
    thread['is_complaint'] = is_complaint
    thread['participant_id'] = None
    thread['can_chat'] = False

    role = user.get('role')
    user_id = user.get('id')
    if role == 'CITIZEN':
        if thread['citizen_id'] != user_id:
            return None
        thread['can_chat'] = bool(thread['assigned_officer_id']) and (
            is_complaint or thread['status'] != 'PENDING_VERIFICATION'
        )
        thread['participant_id'] = thread['assigned_officer_id']
    elif role == 'OFFICER':
        if thread['assigned_officer_id'] != user_id:
            return None
        thread['can_chat'] = bool(thread['citizen_id'])
        thread['participant_id'] = thread['citizen_id']
    elif role == 'ADMIN':
        thread['can_chat'] = False
        thread['participant_id'] = thread['citizen_id']
    return thread


def get_messages(case_id: str, is_complaint: bool = False) -> List[Dict[str, Any]]:
    col = _column(is_complaint)
    conn = get_db_connection()
    rows = [dict(r) for r in conn.execute(f"""
        SELECT m.id, m.sender_id, m.receiver_id, m.sender_role, m.message, m.is_read, m.sent_at,
               u.name AS sender_name
        FROM chat_messages m
        JOIN users u ON m.sender_id = u.id
        WHERE m.{col} = ?
        ORDER BY m.sent_at ASC
    """, (case_id,)).fetchall()]
    conn.close()
    return rows


def mark_thread_read(case_id: str, reader_id: str, is_complaint: bool = False) -> None:
    col = _column(is_complaint)
    conn = get_db_connection()
    changed = conn.execute(
        f"UPDATE chat_messages SET is_read = 1 WHERE {col} = ? AND receiver_id = ? AND is_read = 0",
        (case_id, reader_id),
    ).rowcount
    conn.commit()
    conn.close()
    if changed:
        _publish('CHAT_READ', case_id, is_complaint, reader_id=reader_id)


def send_message(case_id: str, sender: Dict[str, Any], receiver_id: str, text: str,
                 is_complaint: bool = False) -> Dict[str, Any]:
    """Persist one message, alert the receiver and push it to every open thread view."""
    text = (text or '').strip()
    if not text:
        raise ValueError('Type a message before sending.')
    if len(text) > 4000:
        raise ValueError('A message must be 4000 characters or fewer.')
    if not receiver_id:
        raise ValueError('This case has no conversation partner assigned yet.')

    thread = get_thread(case_id, sender, is_complaint=is_complaint)
    if not thread or not thread['can_chat']:
        raise PermissionError('You are not authorised to message on this case.')
    if sender.get('role') == 'CITIZEN' and thread['assigned_officer_id'] != receiver_id:
        raise PermissionError('You can only message the officer assigned to your case.')

    col = _column(is_complaint)
    msg_id = f"msg-{uuid.uuid4().hex[:12]}"
    now = _now()
    conn = get_db_connection()
    conn.execute(f"""
        INSERT INTO chat_messages (id, {col}, sender_id, receiver_id, sender_role, message, is_read, sent_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (msg_id, case_id, sender['id'], receiver_id, sender.get('role'), text, now))
    conn.commit()
    conn.close()

    citizen_name = thread.get('citizen_name') or 'Citizen'
    case_label = f"FIR {thread['case_number']}" if not is_complaint else f"Complaint {thread['case_number']}"
    if sender.get('role') == 'OFFICER':
        title, message = (
            'New Message from Assigned Officer',
            f"Officer {sender.get('name', '')} on {case_label}: \"{text[:120]}\"",
        )
    else:
        title, message = (
            'New Citizen Message',
            f"Citizen {citizen_name} on {case_label}: \"{text[:120]}\"",
        )
    create_notification(
        user_id=receiver_id,
        fir_id=None if is_complaint else case_id,
        complaint_id=case_id if is_complaint else None,
        title=title,
        message=message,
        notification_type='CHAT_MESSAGE',
        event_id=msg_id,
        severity='INFO',
    )
    _publish(
        'CHAT_MESSAGE', case_id, is_complaint,
        sender_id=sender['id'], receiver_id=receiver_id,
        citizen_id=thread.get('citizen_id'), officer_id=thread.get('assigned_officer_id'),
    )
    return {
        'id': msg_id, 'sender_id': sender['id'], 'sender_name': sender.get('name', ''),
        'sender_role': sender.get('role'), 'message': text, 'is_read': 0, 'sent_at': now,
    }


def get_conversations(user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """All threads the user can open, newest activity first, with unread counts."""
    role = user.get('role')
    user_id = user.get('id')
    if role not in ('OFFICER', 'CITIZEN'):
        return []
    conn = get_db_connection()
    if role == 'CITIZEN':
        fir_where, params = "f.citizen_id = ?", [user_id]
        complaint_where, cparams = "c.citizen_id = ?", [user_id]
    else:
        fir_where, params = "f.assigned_officer_id = ?", [user_id]
        complaint_where, cparams = "c.assigned_officer_id = ?", [user_id]

    firs = [dict(r) for r in conn.execute(f"""
        SELECT f.id AS case_id, f.fir_number AS case_number, f.incident_type AS title, f.status,
               f.complaint_id, 'fir' AS kind, f.assigned_officer_id,
               cu.name AS other_name, ou.name AS officer_name,
               cmp.reference AS complaint_reference,
               (SELECT m.message FROM chat_messages m WHERE m.fir_id = f.id ORDER BY m.sent_at DESC LIMIT 1) AS last_message,
               (SELECT m.sent_at FROM chat_messages m WHERE m.fir_id = f.id ORDER BY m.sent_at DESC LIMIT 1) AS last_at,
               (SELECT COUNT(*) FROM chat_messages m WHERE m.fir_id = f.id AND m.receiver_id = ? AND m.is_read = 0) AS unread
        FROM firs f
        LEFT JOIN users cu ON f.citizen_id = cu.id
        LEFT JOIN users ou ON f.assigned_officer_id = ou.id
        LEFT JOIN complaints cmp ON f.complaint_id = cmp.id
        WHERE {fir_where}
          AND (f.assigned_officer_id IS NOT NULL OR EXISTS (SELECT 1 FROM chat_messages m WHERE m.fir_id = f.id))
    """, [user_id, *params]).fetchall()]

    complaints = [dict(r) for r in conn.execute(f"""
        SELECT c.id AS case_id, c.reference AS case_number, c.title, c.status,
               c.fir_id, 'complaint' AS kind, c.assigned_officer_id,
               cu.name AS other_name, c.assigned_officer_name AS officer_name,
               NULL AS complaint_reference,
               (SELECT m.message FROM chat_messages m WHERE m.complaint_id = c.id ORDER BY m.sent_at DESC LIMIT 1) AS last_message,
               (SELECT m.sent_at FROM chat_messages m WHERE m.complaint_id = c.id ORDER BY m.sent_at DESC LIMIT 1) AS last_at,
               (SELECT COUNT(*) FROM chat_messages m WHERE m.complaint_id = c.id AND m.receiver_id = ? AND m.is_read = 0) AS unread
        FROM complaints c
        LEFT JOIN users cu ON c.citizen_id = cu.id
        WHERE {complaint_where}
          AND c.assigned_officer_id IS NOT NULL
          AND (c.fir_id IS NULL OR NOT EXISTS (SELECT 1 FROM firs f WHERE f.complaint_id = c.id))
    """, [user_id, *cparams]).fetchall()]

    threads = firs + complaints
    conn.close()
    for t in threads:
        if role == 'CITIZEN':
            t['other_name'] = t.get('officer_name') or 'Officer not yet assigned'
            t['open_url'] = f"/citizen/chat/{t['case_id']}" if t['kind'] == 'fir' else f"/citizen/complaint-chat/{t['case_id']}"
            t['chat_available'] = t['status'] != 'PENDING_VERIFICATION' if t['kind'] == 'fir' else True
        else:
            t['other_name'] = t.get('other_name') or 'Citizen'
            t['open_url'] = f"/police/chat/{t['case_id']}" if t['kind'] == 'fir' else f"/police/complaint-chat/{t['case_id']}"
            t['chat_available'] = True
    threads.sort(key=lambda t: (t.get('last_at') or ''), reverse=True)
    return threads


def unread_total(user_id: str) -> int:
    conn = get_db_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE receiver_id = ? AND is_read = 0", (user_id,)
    ).fetchone()[0]
    conn.close()
    return count

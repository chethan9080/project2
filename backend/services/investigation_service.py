"""
Investigation workflow for assigned police officers.

Holds the officer-facing stage controls (start / progress / complete), internal
investigation notes and evidence, the milestone credit system, and the data
needed by the police dashboard and the administrator investigation monitor.
Stage history is stored in ``case_tracking``; FIR status changes go through the
versioned blockchain ledger via ``sync_fir_status_for_stage``.
"""

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services.db import get_db_connection
from backend.services.notification_service import create_notification, notify_role
from backend.services.case_tracking_service import (
    CASE_STAGES,
    STAGE_LABELS,
    get_case_tracking_history,
    get_current_case_stage,
    normalize_stage,
    sync_fir_status_for_stage,
)
from backend.services.complaint_evidence_service import (
    MEDIA_TYPES,
    _extension,
    _safe_name,
    validate_upload,
)

CONFIG_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'config', 'officer_credits.json'
))
EVIDENCE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads', 'investigation'
))

# (stage key, officer-facing label, mandatory)
OFFICER_STAGES: List[Tuple[str, str, bool]] = [
    ('OFFICER_ASSIGNED', 'FIR Received', True),
    ('INVESTIGATION_STARTED', 'Investigation Started', True),
    ('EVIDENCE_COLLECTION', 'Evidence Collection', True),
    ('WITNESS_STATEMENTS', 'Witness Statements Recorded', False),
    ('INVESTIGATION_IN_PROGRESS', 'Investigation in Progress', True),
    ('INVESTIGATION_COMPLETED', 'Investigation Completed', True),
    ('CHARGESHEET_PREPARED', 'Report / Charge Sheet Prepared', False),
    ('SUBMITTED_TO_COURT', 'Submitted to Court', False),
    ('CASE_CLOSED', 'Case Closed', True),
]
OFFICER_STAGE_KEYS = [s[0] for s in OFFICER_STAGES]
OFFICER_STAGE_LABELS = {s[0]: s[1] for s in OFFICER_STAGES}
MANDATORY_STAGES = {s[0] for s in OFFICER_STAGES if s[2]}
REQUIRED_UPDATE_STAGES = ('INVESTIGATION_STARTED', 'EVIDENCE_COLLECTION', 'INVESTIGATION_IN_PROGRESS')

PUBLIC_STAGE_TEXT = {
    'INVESTIGATION_STARTED': 'Investigation has started on your case.',
    'EVIDENCE_COLLECTION': 'Evidence collection is in progress.',
    'WITNESS_STATEMENTS': 'Witness statements are being recorded.',
    'INVESTIGATION_IN_PROGRESS': 'The investigation is in progress.',
    'INVESTIGATION_COMPLETED': 'The investigation has been completed.',
    'CHARGESHEET_PREPARED': 'The investigation report / charge sheet has been prepared.',
    'SUBMITTED_TO_COURT': 'The case has been submitted to the competent court.',
    'CASE_CLOSED': 'Your case has been closed.',
}

ACTION_LABELS = {'STARTED': 'Started', 'PROGRESS': 'Progress update', 'COMPLETED': 'Completed'}
EVIDENCE_STATUSES = ['COLLECTED', 'UNDER_ANALYSIS', 'VERIFIED', 'SUBMITTED_TO_COURT', 'RETURNED']
BLOCKED_FIR_STATUSES = ('PENDING_VERIFICATION', 'NEEDS_CORRECTION', 'REJECTED')
ADMIN_STAGE_IDX = CASE_STAGES.index('OFFICER_ASSIGNED')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_investigation_tables() -> None:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS investigation_entries (
            id TEXT PRIMARY KEY,
            fir_id TEXT NOT NULL,
            officer_id TEXT NOT NULL,
            officer_name TEXT NOT NULL,
            entry_type TEXT NOT NULL CHECK(entry_type IN ('NOTE', 'EVIDENCE')),
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            collected_at TEXT,
            evidence_status TEXT,
            file_name TEXT,
            stored_name TEXT,
            content_type TEXT,
            file_size INTEGER,
            sha256 TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (fir_id) REFERENCES firs(id),
            FOREIGN KEY (officer_id) REFERENCES users(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_inv_entries_fir ON investigation_entries(fir_id, created_at)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS officer_credits (
            id TEXT PRIMARY KEY,
            officer_id TEXT NOT NULL,
            fir_id TEXT NOT NULL,
            fir_number TEXT NOT NULL,
            milestone TEXT NOT NULL,
            points INTEGER NOT NULL,
            reason TEXT NOT NULL,
            awarded_at TEXT NOT NULL,
            UNIQUE(officer_id, fir_id, milestone),
            FOREIGN KEY (officer_id) REFERENCES users(id),
            FOREIGN KEY (fir_id) REFERENCES firs(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_credits ON officer_credits(officer_id, awarded_at)")
    conn.commit()
    conn.close()


# ==============================================================================
# ACCESS
# ==============================================================================

def _load_fir(fir_id: str) -> Dict[str, Any]:
    conn = get_db_connection()
    row = conn.execute("""
        SELECT f.*, u.name AS citizen_name, o.name AS officer_name,
               c.reference AS complaint_reference
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        LEFT JOIN complaints c ON f.complaint_id = c.id
        WHERE f.id = ?
    """, (fir_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError('FIR not found.')
    return dict(row)


def can_manage_investigation(user: Optional[Dict[str, Any]], fir: Dict[str, Any]) -> bool:
    """Only the assigned investigating officer (or an administrator) may change a case."""
    if not user:
        return False
    if user.get('role') == 'ADMIN':
        return True
    return user.get('role') == 'OFFICER' and bool(fir.get('assigned_officer_id')) \
        and fir.get('assigned_officer_id') == user.get('id')


def can_view_internal(user: Optional[Dict[str, Any]], fir: Dict[str, Any]) -> bool:
    """Internal notes/evidence: assigned officer, station lead officers and administrators."""
    if not user:
        return False
    if user.get('role') == 'ADMIN':
        return True
    if user.get('role') == 'OFFICER':
        from backend.services.auth_service import can_user_access_fir
        return can_user_access_fir(user, fir)
    return False


def _require_manage(user: Dict[str, Any], fir_id: str) -> Dict[str, Any]:
    fir = _load_fir(fir_id)
    if not can_manage_investigation(user, fir):
        raise PermissionError('Only the assigned investigating officer can update this case.')
    return fir


# ==============================================================================
# STAGE STATE AND TRANSITIONS
# ==============================================================================

def _derived_stage(fir: Dict[str, Any]) -> Optional[str]:
    """Stage implied by the FIR record when no tracking row exists yet."""
    if fir.get('assigned_officer_id'):
        return 'OFFICER_ASSIGNED'
    if fir.get('status') in ('CLOSED', 'RESOLVED'):
        return 'CASE_CLOSED'
    if fir.get('status') != 'PENDING_VERIFICATION':
        return 'FIR_VERIFIED'
    return 'FIR_CREATED'


def _stage_state(fir_id: str, fir: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    history = get_case_tracking_history(fir_id)
    current = normalize_stage(get_current_case_stage(fir_id))
    if not current or current not in CASE_STAGES:
        current = _derived_stage(fir or _load_fir(fir_id))
    cur_action = (history[-1].get('action') or 'STARTED') if history else None
    completed = set()
    started = set()
    for h in history:
        st = h.get('normalized_new_stage')
        if h.get('action') == 'COMPLETED':
            completed.add(st)
        started.add(st)
    cur_idx = CASE_STAGES.index(current) if current in CASE_STAGES else -1
    for st in started:
        if st in CASE_STAGES and CASE_STAGES.index(st) < cur_idx:
            completed.add(st)
    # Administrative stages (up to officer assignment) are complete once reached.
    current_done = cur_idx <= ADMIN_STAGE_IDX or cur_action == 'COMPLETED' or current == 'CASE_CLOSED'
    if current_done and current:
        completed.add(current)
    return {
        'history': history,
        'current': current,
        'current_idx': cur_idx,
        'current_action': cur_action,
        'current_done': current_done,
        'completed': completed,
        'started': started,
    }


def allowed_next_stages(state: Dict[str, Any]) -> List[str]:
    """Stages that may be started next: walk forward, stopping after the first mandatory stage."""
    if not state['current_done'] or state['current'] == 'CASE_CLOSED':
        return []
    result = []
    for key in OFFICER_STAGE_KEYS:
        idx = CASE_STAGES.index(key)
        if idx <= max(state['current_idx'], ADMIN_STAGE_IDX):
            continue
        if key == 'SUBMITTED_TO_COURT' and 'CHARGESHEET_PREPARED' not in state['completed']:
            continue
        if key == 'CASE_CLOSED' and 'INVESTIGATION_COMPLETED' not in state['completed']:
            break
        result.append(key)
        if key in MANDATORY_STAGES:
            break
    return result


def get_investigation_panel(fir_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the officer Investigation Progress section needs, computed server-side."""
    fir = _load_fir(fir_id)
    if not can_view_internal(user, fir):
        raise PermissionError('You are not authorised to view this investigation.')
    state = _stage_state(fir_id, fir)
    can_manage = can_manage_investigation(user, fir) and fir.get('status') not in BLOCKED_FIR_STATUSES
    next_stages = allowed_next_stages(state) if can_manage else []
    rows = []
    for key, label, mandatory in OFFICER_STAGES:
        idx = CASE_STAGES.index(key)
        stage_hist = [h for h in state['history'] if h.get('normalized_new_stage') == key]
        if key == state['current'] and not state['current_done']:
            status = 'IN_PROGRESS'
        elif key in state['completed'] or (idx <= ADMIN_STAGE_IDX and (
                state['current_idx'] >= idx or (key == 'OFFICER_ASSIGNED' and fir.get('assigned_officer_id')))):
            status = 'COMPLETED'
        elif state['current_idx'] > idx:
            status = 'SKIPPED'
        else:
            status = 'PENDING'
        is_current_open = can_manage and key == state['current'] and not state['current_done']
        rows.append({
            'key': key,
            'label': label,
            'optional': not mandatory,
            'status': status,
            'can_start': key in next_stages,
            'can_complete': is_current_open or (key in next_stages and key != 'CASE_CLOSED'),
            'can_progress': is_current_open,
            'can_close': key == 'CASE_CLOSED' and key in next_stages,
            'last_update': stage_hist[-1] if stage_hist else None,
        })
    return {
        'fir': fir,
        'can_manage': can_manage,
        'current_stage': state['current'],
        'current_label': OFFICER_STAGE_LABELS.get(state['current']) or STAGE_LABELS.get(state['current'], 'Not started'),
        'current_action': state['current_action'],
        'stages': rows,
        'history': list(reversed(state['history'])),
    }


def record_investigation_action(
    fir_id: str,
    stage: str,
    action: str,
    officer_user: Dict[str, Any],
    description: str,
    public_note: str = '',
) -> Dict[str, Any]:
    """Validate and persist one officer stage action (STARTED / PROGRESS / COMPLETED)."""
    action = (action or '').upper()
    stage = normalize_stage(stage)
    description = (description or '').strip()
    public_note = (public_note or '').strip()
    if action not in ACTION_LABELS:
        raise ValueError('Unknown investigation action.')
    if stage not in OFFICER_STAGE_KEYS or stage == 'OFFICER_ASSIGNED':
        raise ValueError('This stage cannot be updated by the investigating officer.')
    if len(description) < 10:
        raise ValueError('Please enter a progress description of at least 10 characters.')

    fir = _require_manage(officer_user, fir_id)
    if fir.get('status') in BLOCKED_FIR_STATUSES:
        raise ValueError('This FIR is not registered for investigation yet.')
    if fir.get('status') == 'CLOSED':
        raise ValueError('This case is already closed.')

    state = _stage_state(fir_id, fir)
    next_stages = allowed_next_stages(state)
    is_current = stage == state['current']

    if action == 'STARTED':
        if is_current:
            raise ValueError(f"{OFFICER_STAGE_LABELS[stage]} is already the active stage.")
        if stage not in next_stages:
            raise ValueError(_transition_error(state, stage))
        if stage == 'CASE_CLOSED':
            action = 'COMPLETED'
    elif action == 'PROGRESS':
        if not is_current or state['current_done']:
            raise ValueError('Progress can only be added to the stage that is currently in progress.')
        last = state['history'][-1] if state['history'] else {}
        if (last.get('remarks') or '').strip() == description:
            raise ValueError('This progress update was already saved.')
    else:  # COMPLETED
        if is_current:
            if state['current_done']:
                raise ValueError(f"{OFFICER_STAGE_LABELS[stage]} is already completed.")
        elif stage not in next_stages:
            raise ValueError(_transition_error(state, stage))

    now_iso = _now()
    tracking_id = f"trk-{uuid.uuid4().hex[:12]}"
    default_public_note = PUBLIC_STAGE_TEXT.get(stage, '')
    if action != 'PROGRESS' and not public_note:
        conn = get_db_connection()
        prior = conn.execute("""
            SELECT public_note FROM case_tracking
            WHERE fir_id = ? AND new_stage = ?
              AND public_note IS NOT NULL AND public_note != ?
            ORDER BY timestamp DESC LIMIT 1
        """, (fir_id, stage, default_public_note)).fetchone()
        conn.close()
        # The officer's own wording for this stage outranks the generic stage message.
        public_note = prior['public_note'] if prior else ''
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO case_tracking (
            id, track_id, fir_id, previous_stage, new_stage,
            updated_by_officer_id, updated_by_officer_name, updated_by_officer_badge,
            remarks, timestamp, action, public_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        tracking_id, f"TRK-{datetime.now().strftime('%Y%m%d%H%M%S%f')}", fir_id,
        state['current'], stage, officer_user.get('id'), officer_user.get('name', 'Officer'),
        officer_user.get('badge_number') or 'N/A', description, now_iso, action,
        public_note or (default_public_note if action != 'PROGRESS' else None),
    ))
    conn.commit()
    conn.close()

    label = OFFICER_STAGE_LABELS[stage]
    reason = f"{label} — {ACTION_LABELS[action].lower()}: {description}"
    new_status = sync_fir_status_for_stage(fir, stage, officer_user, reason, now_iso)

    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=officer_user, action_type=f"INVESTIGATION_{action}", fir_id=fir_id,
            fir_number=fir['fir_number'], status_from=fir.get('status'),
            status_to=new_status or fir.get('status'), details=reason,
        )
    except Exception:
        pass

    citizen_text = public_note or PUBLIC_STAGE_TEXT.get(stage, f"{label} updated.")
    if action == 'PROGRESS' and not public_note:
        citizen_text = f"The investigating officer recorded progress on: {label}."
    create_notification(
        user_id=fir['citizen_id'],
        fir_id=fir_id,
        complaint_id=fir.get('complaint_id'),
        title=f"Case Update: {label}",
        message=f"FIR {fir['fir_number']}: {citizen_text}",
        notification_type='CASE_STAGE_UPDATE',
        event_id=f"citizen-{tracking_id}",
        severity='SUCCESS' if action == 'COMPLETED' else 'INFO',
    )
    notify_role(
        "VERIFICATION_OFFICER",
        f"Case Progress: {label}",
        (f"FIR {fir['fir_number']} — {officer_user.get('name', 'Officer')} marked {label} "
         f"as {ACTION_LABELS[action].lower()}."),
        f"investigation-verification-{tracking_id}",
        fir_id=fir_id,
        complaint_id=fir.get('complaint_id'),
        notification_type='INVESTIGATION_UPDATE',
        severity='INFO',
        exclude_user_id=officer_user.get('id'),
    )
    _notify_admins(
        fir,
        title=f"{label} — {ACTION_LABELS[action]}",
        message=(
            f"FIR {fir['fir_number']} (Citizen: {fir.get('citizen_name') or 'Citizen'}) — "
            f"{officer_user.get('name', 'Officer')} marked {label} as {ACTION_LABELS[action].lower()}. "
            f"Remarks: {description[:200]}"
        ),
        event_id=f"admin-{tracking_id}",
        notification_type='INVESTIGATION_UPDATE',
    )

    awarded = _evaluate_credits(fir, officer_user)
    _publish(fir, 'CASE_STAGE_UPDATED', stage=stage)
    return {
        'tracking_id': tracking_id,
        'stage': stage,
        'action': action,
        'fir_status': new_status or fir.get('status'),
        'credits_awarded': awarded,
        'timestamp': now_iso,
    }


def _transition_error(state: Dict[str, Any], stage: str) -> str:
    if not state['current_done']:
        current_label = OFFICER_STAGE_LABELS.get(state['current'], state['current'])
        return f"Complete the current stage ({current_label}) before moving on."
    if stage == 'CASE_CLOSED':
        return 'The investigation must be completed before the case can be closed.'
    if stage == 'SUBMITTED_TO_COURT':
        return 'A report / charge sheet must be prepared before submitting to court.'
    if state['current'] in CASE_STAGES and CASE_STAGES.index(stage) <= state['current_idx']:
        return 'This stage has already passed and cannot be reopened.'
    return 'Required earlier stages must be completed first.'


def _notify_admins(fir: Dict[str, Any], title: str, message: str, event_id: str,
                   notification_type: str) -> None:
    notify_role(
        'ADMIN', title, message, event_id,
        fir_id=fir['id'], notification_type=notification_type,
    )


def _publish(fir: Dict[str, Any], event_type: str, **extra) -> None:
    try:
        from backend.services.realtime_events import publish
        publish({
            'type': event_type,
            'fir_id': fir['id'],
            'fir_number': fir.get('fir_number'),
            'citizen_id': fir.get('citizen_id'),
            'officer_id': fir.get('assigned_officer_id'),
            **extra,
        })
        if event_type != 'INVESTIGATION_UPDATED':
            publish({
                'type': 'INVESTIGATION_UPDATED',
                'fir_id': fir['id'],
                'citizen_id': fir.get('citizen_id'),
                'officer_id': fir.get('assigned_officer_id'),
            })
    except Exception:
        pass


# ==============================================================================
# NOTES AND EVIDENCE (INTERNAL)
# ==============================================================================

def _fir_evidence_dir(fir_id: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', fir_id or ''):
        raise ValueError('Invalid FIR identifier.')
    return os.path.join(EVIDENCE_ROOT, fir_id)


def add_investigation_note(fir_id: str, officer_user: Dict[str, Any], title: str, text: str) -> Dict[str, Any]:
    fir = _require_manage(officer_user, fir_id)
    title, text = (title or '').strip(), (text or '').strip()
    if not title or len(text) < 5:
        raise ValueError('Enter a note title and the note text.')
    return _insert_entry(fir, officer_user, 'NOTE', title, text)


def add_investigation_evidence(
    fir_id: str,
    officer_user: Dict[str, Any],
    title: str,
    description: str,
    collected_at: str,
    evidence_status: str = 'COLLECTED',
    file_name: Optional[str] = None,
    content: Optional[bytes] = None,
    content_type: str = '',
) -> Dict[str, Any]:
    fir = _require_manage(officer_user, fir_id)
    title, description = (title or '').strip(), (description or '').strip()
    if not title or len(description) < 5:
        raise ValueError('Enter the evidence title and a description.')
    if not (collected_at or '').strip():
        raise ValueError('Enter the evidence collection date and time.')
    if evidence_status not in EVIDENCE_STATUSES:
        raise ValueError('Invalid evidence status.')

    file_meta: Dict[str, Any] = {}
    if content is not None:
        validate_upload(file_name or '', len(content))
        safe = _safe_name(file_name)
        stored = f"{uuid.uuid4().hex[:10]}_{safe}"
        folder = _fir_evidence_dir(fir_id)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, stored), 'wb') as handle:
            handle.write(content)
        file_meta = {
            'file_name': safe,
            'stored_name': stored,
            'content_type': content_type or MEDIA_TYPES.get(_extension(safe), 'application/octet-stream'),
            'file_size': len(content),
            'sha256': hashlib.sha256(content).hexdigest(),
        }
    return _insert_entry(fir, officer_user, 'EVIDENCE', title, description,
                         collected_at=collected_at.strip(), evidence_status=evidence_status, **file_meta)


def _insert_entry(fir: Dict[str, Any], officer_user: Dict[str, Any], entry_type: str,
                  title: str, description: str, **fields) -> Dict[str, Any]:
    entry_id = f"inv-{uuid.uuid4().hex[:12]}"
    now_iso = _now()
    row = {
        'id': entry_id, 'fir_id': fir['id'], 'officer_id': officer_user['id'],
        'officer_name': officer_user.get('name', 'Officer'), 'entry_type': entry_type,
        'title': title, 'description': description, 'collected_at': fields.get('collected_at'),
        'evidence_status': fields.get('evidence_status'), 'file_name': fields.get('file_name'),
        'stored_name': fields.get('stored_name'), 'content_type': fields.get('content_type'),
        'file_size': fields.get('file_size'), 'sha256': fields.get('sha256'),
        'created_at': now_iso, 'updated_at': now_iso,
    }
    conn = get_db_connection()
    conn.execute(f"""
        INSERT INTO investigation_entries ({', '.join(row)}) VALUES ({', '.join('?' for _ in row)})
    """, tuple(row.values()))
    conn.commit()
    conn.close()
    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=officer_user, action_type=f"INVESTIGATION_{entry_type}_ADDED", fir_id=fir['id'],
            fir_number=fir['fir_number'], details=f"{entry_type.title()} recorded: {title}"
            + (f" (file {row['file_name']}, SHA-256 {row['sha256'][:16]}…)" if row['sha256'] else ''),
        )
    except Exception:
        pass
    _publish(fir, 'INVESTIGATION_UPDATED')
    return row


def update_evidence_status(entry_id: str, officer_user: Dict[str, Any], new_status: str) -> None:
    if new_status not in EVIDENCE_STATUSES:
        raise ValueError('Invalid evidence status.')
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM investigation_entries WHERE id = ? AND entry_type = 'EVIDENCE'",
                       (entry_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError('Evidence record not found.')
    entry = dict(row)
    fir = _require_manage(officer_user, entry['fir_id'])
    if entry['evidence_status'] == new_status:
        return
    conn = get_db_connection()
    conn.execute("UPDATE investigation_entries SET evidence_status = ?, updated_at = ? WHERE id = ?",
                 (new_status, _now(), entry_id))
    conn.commit()
    conn.close()
    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=officer_user, action_type='EVIDENCE_STATUS_UPDATED', fir_id=fir['id'],
            fir_number=fir['fir_number'], status_from=entry['evidence_status'], status_to=new_status,
            details=f"Evidence '{entry['title']}' status changed.",
        )
    except Exception:
        pass
    _publish(fir, 'INVESTIGATION_UPDATED')


def list_investigation_entries(fir_id: str, user: Dict[str, Any]) -> List[Dict[str, Any]]:
    fir = _load_fir(fir_id)
    if not can_view_internal(user, fir):
        raise PermissionError('Internal investigation records are restricted.')
    conn = get_db_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM investigation_entries WHERE fir_id = ? ORDER BY created_at DESC", (fir_id,)
    ).fetchall()]
    conn.close()
    return rows


def get_evidence_file(entry_id: str, user: Dict[str, Any]) -> Optional[Tuple[bytes, str, str]]:
    """Return (bytes, filename, content type) only for authorised internal viewers."""
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM investigation_entries WHERE id = ?", (entry_id,)).fetchone()
    conn.close()
    if not row or not row['stored_name']:
        return None
    entry = dict(row)
    if not can_view_internal(user, _load_fir(entry['fir_id'])):
        raise PermissionError('Internal evidence is restricted.')
    folder = _fir_evidence_dir(entry['fir_id'])
    path = os.path.abspath(os.path.join(folder, os.path.basename(entry['stored_name'])))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return None
    with open(path, 'rb') as handle:
        return handle.read(), entry['file_name'], entry['content_type'] or 'application/octet-stream'


# ==============================================================================
# CITIZEN-SUBMITTED SUPPORTING DOCUMENTS
# ==============================================================================

def add_citizen_evidence(
    fir_id: str,
    citizen_user: Dict[str, Any],
    file_name: str,
    content: bytes,
    content_type: str = '',
    caption: str = '',
) -> Dict[str, Any]:
    """Store a document the citizen adds to a registered FIR and alert the case officer."""
    fir = _load_fir(fir_id)
    if (not citizen_user or citizen_user.get('role') != 'CITIZEN'
            or fir.get('citizen_id') != citizen_user.get('id')):
        raise PermissionError('This FIR belongs to another citizen.')
    if fir.get('status') in BLOCKED_FIR_STATUSES:
        raise ValueError('Supporting documents open once your FIR is registered.')
    complaint_id = fir.get('complaint_id')
    if not complaint_id:
        raise ValueError('No complaint record is linked to this FIR.')

    from backend.services.complaint_evidence_service import save_complaint_file
    from backend.services.complaint_service import attach_complaint_evidence, get_complaint_by_id

    stored = save_complaint_file(complaint_id, file_name, content, content_type)
    stored.update({
        'caption': (caption or '').strip()[:280],
        'uploaded_by': citizen_user.get('name') or 'Citizen',
        'uploaded_at': _now(),
        'stage': 'CITIZEN_ADDITIONAL',
    })

    complaint = get_complaint_by_id(complaint_id, citizen_id=citizen_user['id'])
    files = json.loads((complaint or {}).get('evidence_files') or '[]')
    files.append(stored)
    attach_complaint_evidence(complaint_id, files)

    label = stored['caption'] or stored['name']
    title = 'Citizen uploaded a supporting document'
    message = (
        f"FIR {fir['fir_number']} (Citizen: {fir.get('citizen_name') or 'Citizen'}): "
        f"new document — {label} ({stored['name']})"
    )
    event_id = f"citizen-evidence-{stored['stored_name']}"
    if fir.get('assigned_officer_id'):
        create_notification(
            user_id=fir['assigned_officer_id'], fir_id=fir_id, complaint_id=complaint_id,
            title=title, message=message, notification_type='INVESTIGATION_UPDATE',
            event_id=event_id, severity='INFO',
        )
    _notify_admins(fir, title, message, event_id, 'INVESTIGATION_UPDATE')

    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=citizen_user, action_type='CITIZEN_EVIDENCE_UPLOADED', fir_id=fir_id,
            fir_number=fir['fir_number'],
            details=f"Supporting document uploaded: {stored['name']} (SHA-256 {stored['sha256'][:16]}…)",
        )
    except Exception:
        pass
    _publish(fir, 'INVESTIGATION_UPDATED', citizen_id=fir.get('citizen_id'))
    return stored


# ==============================================================================
# CREDITS
# ==============================================================================

def load_credit_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def _award(officer_id: str, fir: Dict[str, Any], milestone: str, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    spec = config['milestones'].get(milestone)
    if not spec:
        return None
    conn = get_db_connection()
    cur = conn.execute("""
        INSERT OR IGNORE INTO officer_credits (id, officer_id, fir_id, fir_number, milestone, points, reason, awarded_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (f"crd-{uuid.uuid4().hex[:12]}", officer_id, fir['id'], fir['fir_number'], milestone,
          int(spec['points']), spec['label'], _now()))
    conn.commit()
    inserted = cur.rowcount == 1
    conn.close()
    if not inserted:
        return None
    create_notification(
        user_id=officer_id, fir_id=fir['id'],
        title=f"+{spec['points']} credits earned",
        message=f"{spec['label']} for FIR {fir['fir_number']} (Citizen: {fir.get('citizen_name') or 'Citizen'}).",
        notification_type='OFFICER_CREDIT', event_id=f"credit-{officer_id}-{fir['id']}-{milestone}",
        severity='SUCCESS',
    )
    return {'milestone': milestone, 'points': int(spec['points']), 'reason': spec['label']}


def _evaluate_credits(fir: Dict[str, Any], officer_user: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Award milestone credits to the assigned officer; each milestone once per case."""
    if officer_user.get('role') != 'OFFICER' or fir.get('assigned_officer_id') != officer_user.get('id'):
        return []
    state = _stage_state(fir['id'], fir)
    config = load_credit_config()
    milestones = []
    if 'INVESTIGATION_STARTED' in state['started']:
        milestones.append('CASE_ACCEPTED')
    if all(s in state['completed'] for s in REQUIRED_UPDATE_STAGES):
        milestones.append('REQUIRED_UPDATES_COMPLETED')
    if 'INVESTIGATION_COMPLETED' in state['completed']:
        milestones.append('INVESTIGATION_COMPLETED')
    if 'CHARGESHEET_PREPARED' in state['completed']:
        milestones.append('REPORT_SUBMITTED')
    if 'CASE_CLOSED' in state['completed']:
        milestones.append('CASE_COMPLETED')
    awarded = [a for a in (_award(officer_user['id'], fir, m, config) for m in milestones) if a]
    if awarded:
        try:
            from backend.services.realtime_events import publish
            publish({'type': 'OFFICER_CREDITS_UPDATED', 'officer_id': officer_user['id']})
        except Exception:
            pass
    return awarded


def get_officer_performance(officer_id: str) -> Dict[str, Any]:
    config = load_credit_config()
    conn = get_db_connection()
    history = [dict(r) for r in conn.execute("""
        SELECT c.*, u.name AS citizen_name
        FROM officer_credits c
        LEFT JOIN firs f ON f.id = c.fir_id
        LEFT JOIN users u ON u.id = f.citizen_id
        WHERE c.officer_id = ? ORDER BY c.awarded_at DESC
    """, (officer_id,)).fetchall()]
    assigned = conn.execute(
        "SELECT COUNT(*) FROM firs WHERE assigned_officer_id = ?", (officer_id,)
    ).fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM firs WHERE assigned_officer_id = ? AND status IN ('CLOSED', 'RESOLVED')",
        (officer_id,),
    ).fetchone()[0]
    conn.close()
    total = sum(int(h['points']) for h in history)
    levels = sorted(config['star_levels'], key=lambda lv: lv['min_points'])
    level = levels[0]
    next_level = None
    for lv in levels:
        if total >= lv['min_points']:
            level = lv
        elif next_level is None:
            next_level = lv
    return {
        'total_credits': total,
        'stars': level['stars'],
        'max_stars': max(lv['stars'] for lv in levels),
        'level': level['level'],
        'next_level': next_level,
        'history': history,
        'assigned_count': assigned,
        'completed_count': completed,
    }


# ==============================================================================
# DASHBOARD DATA
# ==============================================================================

def _case_rows(where: str, params: tuple) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = [dict(r) for r in conn.execute(f"""
        SELECT f.id, f.fir_number, f.reference_number, f.status, f.incident_type, f.incident_location,
               f.incident_date, f.police_station, f.citizen_id, f.assigned_officer_id, f.complaint_id,
               f.created_at, f.updated_at,
               u.name AS citizen_name, u.username AS citizen_username, o.name AS officer_name,
               c.reference AS complaint_reference, c.category AS complaint_category,
               (SELECT a.assigned_at FROM officer_assignments a
                 WHERE a.fir_id = f.id AND a.officer_id = f.assigned_officer_id
                 ORDER BY a.assigned_at DESC LIMIT 1) AS assigned_at,
               (SELECT t.new_stage FROM case_tracking t WHERE t.fir_id = f.id
                 ORDER BY t.timestamp DESC LIMIT 1) AS current_stage,
               (SELECT COALESCE(t.action, 'STARTED') FROM case_tracking t WHERE t.fir_id = f.id
                 ORDER BY t.timestamp DESC LIMIT 1) AS current_action,
               (SELECT t.timestamp FROM case_tracking t WHERE t.fir_id = f.id
                 ORDER BY t.timestamp DESC LIMIT 1) AS last_update_at
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        LEFT JOIN complaints c ON f.complaint_id = c.id
        WHERE {where}
        ORDER BY COALESCE(
            (SELECT a.assigned_at FROM officer_assignments a WHERE a.fir_id = f.id
              ORDER BY a.assigned_at DESC LIMIT 1), f.created_at) DESC
    """, params).fetchall()]
    conn.close()
    for r in rows:
        stage = normalize_stage(r.get('current_stage'))
        if stage not in CASE_STAGES:
            stage = _derived_stage(r)
        r['current_stage'] = stage
        r['stage_label'] = OFFICER_STAGE_LABELS.get(stage) or STAGE_LABELS.get(stage, 'Awaiting tracking')
        idx = CASE_STAGES.index(stage) if stage in CASE_STAGES else -1
        r['stage_index'] = idx
        r['is_closed'] = stage == 'CASE_CLOSED' or r.get('status') in ('CLOSED', 'RESOLVED')
        r['stage_done'] = idx <= ADMIN_STAGE_IDX or r.get('current_action') == 'COMPLETED'
        r['is_draft'] = r.get('status') in BLOCKED_FIR_STATUSES
    return rows


def get_officer_cases(officer_id: str) -> List[Dict[str, Any]]:
    return _case_rows("f.assigned_officer_id = ?", (officer_id,))


def compute_case_stats(cases: List[Dict[str, Any]]) -> Dict[str, int]:
    idx = CASE_STAGES.index
    open_cases = [c for c in cases if not c['is_closed']]
    started_idx, progress_idx = idx('INVESTIGATION_STARTED'), idx('INVESTIGATION_IN_PROGRESS')
    return {
        'total': len(cases),
        'new': sum(1 for c in open_cases if c['stage_index'] <= ADMIN_STAGE_IDX),
        'under_investigation': sum(
            1 for c in open_cases if started_idx <= c['stage_index'] <= progress_idx
        ),
        'awaiting_action': sum(
            1 for c in open_cases if c['stage_done'] and c['stage_index'] > ADMIN_STAGE_IDX
        ),
        'evidence': sum(1 for c in open_cases if c['current_stage'] == 'EVIDENCE_COLLECTION' and not c['stage_done']),
        'completed': sum(1 for c in open_cases if c['current_stage'] == 'INVESTIGATION_COMPLETED'),
        'proceedings': sum(1 for c in open_cases if c['current_stage'] in ('CHARGESHEET_PREPARED', 'SUBMITTED_TO_COURT')),
        'closed': sum(1 for c in cases if c['is_closed']),
    }


def get_recent_assignments(officer_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT a.fir_id, a.assigned_at, a.status AS assignment_status,
               f.fir_number, f.incident_type, f.status, u.name AS citizen_name,
               b.name AS assigned_by_name, c.reference AS complaint_reference
        FROM officer_assignments a
        JOIN firs f ON a.fir_id = f.id
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users b ON a.assigned_by = b.id
        LEFT JOIN complaints c ON f.complaint_id = c.id
        WHERE a.officer_id = ? AND a.status = 'ACTIVE'
          AND a.assigned_at = (
              SELECT MAX(a2.assigned_at) FROM officer_assignments a2
              WHERE a2.fir_id = a.fir_id AND a2.officer_id = a.officer_id AND a2.status = 'ACTIVE'
          )
        GROUP BY a.fir_id
        ORDER BY a.assigned_at DESC LIMIT ?
    """, (officer_id, limit)).fetchall()]
    conn.close()
    return rows


def get_recent_activities(officer_id: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Recent stage changes and investigation records on this officer's assigned cases."""
    conn = get_db_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT * FROM (
            SELECT t.timestamp AS at, t.fir_id, f.fir_number, u.name AS citizen_name,
                   t.new_stage AS stage, COALESCE(t.action, 'STARTED') AS action,
                   t.updated_by_officer_name AS actor, 'STAGE' AS kind, NULL AS title
            FROM case_tracking t JOIN firs f ON t.fir_id = f.id
            LEFT JOIN users u ON f.citizen_id = u.id
            WHERE f.assigned_officer_id = ?
            UNION ALL
            SELECT e.created_at, e.fir_id, f.fir_number, u.name, NULL, e.entry_type,
                   e.officer_name, 'ENTRY', e.title
            FROM investigation_entries e JOIN firs f ON e.fir_id = f.id
            LEFT JOIN users u ON f.citizen_id = u.id
            WHERE f.assigned_officer_id = ?
        ) ORDER BY at DESC LIMIT ?
    """, (officer_id, officer_id, limit)).fetchall()]
    conn.close()
    for r in rows:
        if r['kind'] == 'STAGE':
            stage = normalize_stage(r['stage'])
            label = OFFICER_STAGE_LABELS.get(stage) or STAGE_LABELS.get(stage, stage)
            r['summary'] = f"{label} — {ACTION_LABELS.get(r['action'], r['action']).lower()}"
        else:
            r['summary'] = f"{'Evidence' if r['action'] == 'EVIDENCE' else 'Note'} added: {r['title']}"
    return rows


# ==============================================================================
# ADMINISTRATOR MONITOR
# ==============================================================================

def get_admin_investigation_overview() -> List[Dict[str, Any]]:
    rows = _case_rows("f.assigned_officer_id IS NOT NULL", ())
    conn = get_db_connection()
    for r in rows:
        r['milestones_completed'] = conn.execute("""
            SELECT COUNT(DISTINCT new_stage) FROM case_tracking WHERE fir_id = ? AND action = 'COMPLETED'
        """, (r['id'],)).fetchone()[0]
        r['stages_recorded'] = conn.execute(
            "SELECT COUNT(DISTINCT new_stage) FROM case_tracking WHERE fir_id = ?", (r['id'],)
        ).fetchone()[0]
        r['entries_count'] = conn.execute(
            "SELECT COUNT(*) FROM investigation_entries WHERE fir_id = ?", (r['id'],)
        ).fetchone()[0]
    conn.close()
    return rows


# Columns an officer can amend on a registered FIR, worded for the authorized
# modification review. Unknown names fall back to their spaced column name.
FIR_FIELD_LABELS = {
    'incident_type': 'Offence category',
    'incident_date': 'Incident date',
    'incident_time': 'Incident time',
    'incident_location': 'Place of occurrence',
    'description': 'Complaint description',
    'accused_details': 'Accused / suspect details',
    'witness_details': 'Witness details',
    'status': 'FIR status',
    'police_station': 'Police station',
}


def _json_rows(raw: Optional[str], default: Any) -> Any:
    try:
        return json.loads(raw or '') or default
    except (ValueError, TypeError):
        return default


def _diff_rows(event: Dict[str, Any]) -> List[Dict[str, str]]:
    """Previous vs updated value for every field one change event recorded."""
    old_values = _json_rows(event.get('old_values_json'), {})
    new_values = _json_rows(event.get('new_values_json'), {})
    fields = _json_rows(event.get('changed_fields_json'), [])
    diffs = []
    for field in fields:
        diffs.append({
            'field': field,
            'label': FIR_FIELD_LABELS.get(field) or str(field).replace('_', ' ').capitalize(),
            'old': str(old_values.get(field, '') or ''),
            'new': str(new_values.get(field, '') or ''),
        })
    return diffs


def get_admin_case_record(fir_id: str, admin_user: Dict[str, Any]) -> Dict[str, Any]:
    """Complete authorized case record: origin, registration, documents, every
    recorded modification, the SHA-256 hash of each version and closure state.

    Authorized Officers only; hashes and audit detail are not reachable through
    any other role or page.
    """
    if not admin_user or admin_user.get('role') != 'ADMIN':
        raise PermissionError('Authorized Officer access required.')
    cases = _case_rows('f.id = ?', (fir_id,))
    if not cases:
        raise ValueError('FIR not found.')
    case = cases[0]

    conn = get_db_connection()
    citizen = dict(conn.execute("""
        SELECT id, name, username, email, phone, status, role, district, address,
               gov_id_masked, verification_status, verified_at, created_at
        FROM users WHERE id = ?
    """, (case.get('citizen_id'),)).fetchone() or {})
    application = dict(conn.execute("""
        SELECT reference, full_name, submitted_at, status, reviewed_at, reviewed_by,
               reviewed_by_name, district, state, gov_id_type, gov_id_masked, username
        FROM citizen_applications WHERE citizen_id = ?
        ORDER BY reviewed_at DESC, submitted_at DESC LIMIT 1
    """, (case.get('citizen_id'),)).fetchone() or {})
    complaint = dict(conn.execute("""
        SELECT id, reference, category, title, description, location, landmark, area,
               district, state, police_station, incident_date, incident_time,
               submitted_at, status, verification_status, verified_by_name, verified_at,
               verification_remarks, rejection_reason, fir_edited_by_name, fir_edited_at
        FROM complaints WHERE id = ?
    """, (case.get('complaint_id'),)).fetchone() or {})

    # The version-1 row is the registration itself: its author registered the FIR.
    registration = dict(conn.execute("""
        SELECT v.created_at, v.change_reason, v.current_hash, v.previous_hash,
               u.name AS officer_name, u.role AS officer_role,
               u.badge_number AS officer_badge, u.station AS officer_station
        FROM fir_versions v
        LEFT JOIN users u ON v.created_by = u.id
        WHERE v.fir_id = ? AND v.version_number = 1
    """, (fir_id,)).fetchone() or {})
    if not registration:
        registration = {
            'created_at': case.get('created_at'),
            'change_reason': 'FIR registered',
            'officer_name': None,
            'officer_role': 'VERIFICATION_OFFICER',
        }

    documents = [dict(r) for r in conn.execute("""
        SELECT id, document_type, version, file_name, file_path, sha256,
               generated_by_name, generated_at, is_current
        FROM fir_documents WHERE fir_id = ? ORDER BY version DESC, generated_at DESC
    """, (fir_id,)).fetchall()]

    verification_events = [dict(r) for r in conn.execute("""
        SELECT id, action, status_from, status_to, remarks, actor_name, actor_role,
               actor_badge, created_at
        FROM complaint_verification_events WHERE complaint_id = ?
        ORDER BY created_at ASC
    """, (complaint.get('id'),)).fetchall()] if complaint.get('id') else []

    closure = dict(conn.execute("""
        SELECT previous_stage, new_stage, action, remarks, public_note, timestamp,
               updated_by_officer_name, updated_by_officer_badge
        FROM case_tracking WHERE fir_id = ? AND new_stage = 'CASE_CLOSED'
        ORDER BY timestamp DESC LIMIT 1
    """, (fir_id,)).fetchone() or {})
    counts = {
        'complaints': conn.execute(
            "SELECT COUNT(*) FROM complaints WHERE citizen_id = ?", (case.get('citizen_id'),)
        ).fetchone()[0],
        'firs': conn.execute(
            "SELECT COUNT(*) FROM firs WHERE citizen_id = ?", (case.get('citizen_id'),)
        ).fetchone()[0],
    }
    conn.close()

    from backend.services.fir_service import get_fir_changes, get_fir_versions
    from data.integrity import get_hash_chain_status

    versions = get_fir_versions(fir_id, actor_user=admin_user)
    events = get_fir_changes(fir_id, actor_user=admin_user)
    for event in events:
        event['diffs'] = _diff_rows(event)

    return {
        'case': case,
        'citizen': citizen,
        'application': application,
        'counts': counts,
        'complaint': complaint,
        'registration': registration,
        'documents': documents,
        'verification_events': verification_events,
        'verification_changes': [e for e in events if e.get('actor_role') == 'VERIFICATION_OFFICER'],
        # Police staff are stored with role OFFICER; anything not a Verification
        # Officer amendment is shown in the police modification section.
        'officer_changes': [e for e in events if e.get('actor_role') != 'VERIFICATION_OFFICER'],
        'versions': [{
            'version_number': v.get('version_number'),
            'created_at': v.get('created_at'),
            'change_reason': v.get('change_reason'),
            'previous_hash': v.get('previous_hash'),
            'current_hash': v.get('current_hash'),
            'creator_name': v.get('creator_name'),
            'creator_role': v.get('creator_role'),
            'creator_badge': v.get('creator_badge'),
        } for v in versions],
        'chain': get_hash_chain_status(fir_id),
        'closure': closure,
        'is_closed': case.get('is_closed') or bool(closure),
    }


def get_admin_case_detail(fir_id: str, admin_user: Dict[str, Any]) -> Dict[str, Any]:
    if not admin_user or admin_user.get('role') != 'ADMIN':
        raise PermissionError('Administrator access required.')
    case = _case_rows("f.id = ?", (fir_id,))
    if not case:
        raise ValueError('FIR not found.')
    conn = get_db_connection()
    assignments = [dict(r) for r in conn.execute("""
        SELECT a.*, o.name AS officer_name, b.name AS assigned_by_name
        FROM officer_assignments a
        LEFT JOIN users o ON a.officer_id = o.id
        LEFT JOIN users b ON a.assigned_by = b.id
        WHERE a.fir_id = ? ORDER BY a.assigned_at DESC
    """, (fir_id,)).fetchall()]
    credits = [dict(r) for r in conn.execute("""
        SELECT c.*, o.name AS officer_name FROM officer_credits c
        LEFT JOIN users o ON c.officer_id = o.id WHERE c.fir_id = ? ORDER BY c.awarded_at DESC
    """, (fir_id,)).fetchall()]
    conn.close()
    return {
        'case': case[0],
        'history': list(reversed(get_case_tracking_history(fir_id))),
        'entries': list_investigation_entries(fir_id, admin_user),
        'assignments': assignments,
        'credits': credits,
        'record': get_admin_case_record(fir_id, admin_user),
    }


def get_admin_officer_record(officer_id: str, admin_user: Dict[str, Any]) -> Dict[str, Any]:
    """Police Officer verification dossier: identity, account decisions, assignments and cases."""
    if not admin_user or admin_user.get('role') != 'ADMIN':
        raise PermissionError('Authorized Officer access required.')
    conn = get_db_connection()
    row = conn.execute("""
        SELECT id, name, username, email, phone, badge_number, rank, station, district, address,
               status, role, verification_status, verified_at, created_at, updated_at
        FROM users WHERE id = ? AND role = 'OFFICER'
    """, (officer_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError('Police officer account not found.')
    officer = dict(row)
    assignments = [dict(r) for r in conn.execute("""
        SELECT a.*, f.fir_number, f.status AS fir_status, f.incident_type,
               u.name AS citizen_name, b.name AS assigned_by_name
        FROM officer_assignments a
        JOIN firs f ON a.fir_id = f.id
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users b ON a.assigned_by = b.id
        WHERE a.officer_id = ? ORDER BY a.assigned_at DESC
    """, (officer_id,)).fetchall()]
    decisions = [dict(r) for r in conn.execute("""
        SELECT l.id, l.timestamp, l.action, l.details, l.role, l.user_email,
               a.name AS decided_by_name, a.badge_number AS decided_by_badge
        FROM system_audit_logs l
        LEFT JOIN users a ON l.user_id = a.id
        WHERE l.action = 'OFFICER_STATUS_UPDATE' AND l.resource_id = ?
        ORDER BY l.timestamp DESC
    """, (officer_id,)).fetchall()]
    conn.close()
    cases = get_officer_cases(officer_id)
    return {
        'officer': officer,
        'cases': cases,
        'stats': compute_case_stats(cases),
        'assignments': assignments,
        'decisions': decisions,
        'performance': get_officer_performance(officer_id),
    }


def send_officer_instruction(fir_id: str, admin_user: Dict[str, Any], text: str) -> None:
    if not admin_user or admin_user.get('role') != 'ADMIN':
        raise PermissionError('Only administrators can send case instructions.')
    text = (text or '').strip()
    if len(text) < 5:
        raise ValueError('Enter the instruction text.')
    fir = _load_fir(fir_id)
    if not fir.get('assigned_officer_id'):
        raise ValueError('This FIR has no assigned officer.')
    event_id = f"instruction-{uuid.uuid4().hex[:12]}"
    create_notification(
        user_id=fir['assigned_officer_id'], fir_id=fir_id, complaint_id=fir.get('complaint_id'),
        title='Instruction from Administrator',
        message=f"FIR {fir['fir_number']} (Citizen: {fir.get('citizen_name') or 'Citizen'}): {text}",
        notification_type='ADMIN_INSTRUCTION', event_id=event_id, severity='WARNING',
    )
    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=admin_user, action_type='ADMIN_INSTRUCTION', fir_id=fir_id,
            fir_number=fir['fir_number'], details=text[:500],
        )
    except Exception:
        pass


init_investigation_tables()

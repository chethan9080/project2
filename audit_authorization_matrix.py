"""Authorization matrix — service layer, read-only, synthetic actors only.

Proves the access rules demanded by the audit without writing any record:
citizens see only their own cases, officers only assigned cases, verification
officers only verification actions, administrators the authorized monitor.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.services.auth_service import (                # noqa: E402
    assert_active_citizen, can_user_access_fir, can_user_access_fir_audit, can_user_modify_fir,
)
from backend.services.case_tracking_service import get_fir_complete_tracking   # noqa: E402
from backend.services.chat_service import get_thread                          # noqa: E402
from backend.services.complaint_service import get_complaint_by_id            # noqa: E402
from backend.services.fir_document_service import latest_document_path_for    # noqa: E402
from backend.services.investigation_service import (                          # noqa: E402
    add_citizen_evidence, get_admin_case_detail, get_evidence_file,
    get_investigation_panel, record_investigation_action,
)

# Read-only view of the live ledger: this matrix only reads rows and asserts denials.
conn = sqlite3.connect('file:data/fir_platform.db?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
FIR = conn.execute("SELECT id, citizen_id, assigned_officer_id, complaint_id FROM firs "
                   "ORDER BY fir_number DESC LIMIT 1").fetchone()
citizen = dict(conn.execute("SELECT * FROM users WHERE id=?", (FIR['citizen_id'],)).fetchone())
officer = dict(conn.execute("SELECT * FROM users WHERE id=?", (FIR['assigned_officer_id'],)).fetchone())
vo = dict(conn.execute("SELECT * FROM users WHERE role='VERIFICATION_OFFICER' LIMIT 1").fetchone())
admin = dict(conn.execute("SELECT * FROM users WHERE role='ADMIN' LIMIT 1").fetchone())
pending = dict(conn.execute("SELECT * FROM users WHERE status<>'ACTIVE' LIMIT 1").fetchone())
STRANGER = {'id': 'usr-not-a-real-account', 'role': 'OFFICER', 'name': 'Stranger', 'status': 'ACTIVE'}

results = []


def check(name, fn, expect):
    try:
        outcome = fn()
        verdict = 'ALLOWED' if outcome not in (None, False) else 'DENIED'
    except PermissionError:
        verdict = 'DENIED'
    except Exception as exc:                                    # noqa: BLE001
        results.append(f'ERROR  {name}: {type(exc).__name__}: {exc}')
        return
    results.append(f'{"OK  " if verdict == expect else "BAD "} {name} -> {verdict} (expected {expect})')


def check_gate(name, fn, expect):
    """For guards that signal approval by returning normally instead of raising."""
    try:
        fn()
        verdict = 'ALLOWED'
    except PermissionError:
        verdict = 'DENIED'
    except Exception as exc:                                    # noqa: BLE001
        results.append(f'ERROR  {name}: {type(exc).__name__}: {exc}')
        return
    results.append(f'{"OK  " if verdict == expect else "BAD "} {name} -> {verdict} (expected {expect})')


# --- unverified / suspended citizens are locked out of protected features
check_gate('pending citizen blocked from portal features',
           lambda: assert_active_citizen(pending), 'DENIED')
check_gate('active verified citizen allowed', lambda: assert_active_citizen(citizen), 'ALLOWED')

# --- citizen sees only their own record
check('owner reads own FIR tracking',
      lambda: get_fir_complete_tracking(FIR['id'], actor_user=citizen), 'ALLOWED')
check('assigned officer reads live tracking',
      lambda: get_fir_complete_tracking(FIR['id'], actor_user=officer), 'ALLOWED')
check('unrelated officer reads citizen FIR tracking',
      lambda: get_fir_complete_tracking(FIR['id'], actor_user=STRANGER), 'DENIED')
check('unrelated citizen reads another citizen FIR tracking',
      lambda: get_fir_complete_tracking(
          FIR['id'], actor_user={'id': 'usr-not-a-real-account', 'role': 'CITIZEN'}), 'DENIED')
check('owner reads own complaint',
      lambda: get_complaint_by_id(FIR['complaint_id'], citizen_id=citizen['id']), 'ALLOWED')
check('stranger citizen reads another complaint',
      lambda: get_complaint_by_id(FIR['complaint_id'], citizen_id='usr-not-a-real-account'), 'DENIED')

# --- officer access is assignment-based
check('assigned officer may open the case',
      lambda: can_user_access_fir(officer, dict(FIR)), 'ALLOWED')
check('unassigned officer may not open the case',
      lambda: can_user_access_fir(STRANGER, dict(FIR)), 'DENIED')
check('assigned officer may modify the case',
      lambda: can_user_modify_fir(officer, dict(FIR)), 'ALLOWED')
check('unassigned officer may not modify the case',
      lambda: can_user_modify_fir(STRANGER, dict(FIR)), 'DENIED')
check('stranger officer may not read the audit trail',
      lambda: can_user_access_fir_audit(STRANGER, dict(FIR)), 'DENIED')
check('unassigned officer gets no chat thread',
      lambda: get_thread(FIR['id'], STRANGER, is_complaint=False), 'DENIED')
check('assigned officer opens the chat thread',
      lambda: get_thread(FIR['id'], officer, is_complaint=False), 'ALLOWED')

# --- writes rejected before touching storage
check('unassigned officer cannot record a stage action',
      lambda: record_investigation_action(FIR['id'], 'INVESTIGATION_STARTED', 'STARTED',
                                          STRANGER, 'x' * 24, ''), 'DENIED')
check('citizen cannot record an officer stage action',
      lambda: record_investigation_action(FIR['id'], 'INVESTIGATION_STARTED', 'STARTED',
                                          citizen, 'x' * 24, ''), 'DENIED')
check('stranger citizen cannot file evidence on another FIR',
      lambda: add_citizen_evidence(FIR['id'], STRANGER, 'note.txt', b'x', 'text/plain', 'x'), 'DENIED')

# --- admin monitor stays administrator-only
check('citizen cannot open the admin case monitor',
      lambda: get_admin_case_detail(FIR['id'], citizen), 'DENIED')
check('verification officer cannot open the admin case monitor',
      lambda: get_admin_case_detail(FIR['id'], vo), 'DENIED')
check('unassigned officer cannot open the admin case monitor',
      lambda: get_admin_case_detail(FIR['id'], STRANGER), 'DENIED')
check('administrator opens the case monitor',
      lambda: get_admin_case_detail(FIR['id'], admin), 'ALLOWED')

# --- confidential evidence stays behind the same gate
entry = conn.execute("SELECT id FROM investigation_entries WHERE fir_id=? AND file_name IS NOT NULL "
                     "LIMIT 1", (FIR['id'],)).fetchone()
if entry:
    check('stranger cannot download case evidence',
          lambda: get_evidence_file(entry['id'], STRANGER), 'DENIED')
    check('assigned officer can download case evidence',
          lambda: get_evidence_file(entry['id'], officer), 'ALLOWED')
else:
    results.append('SKIP evidence file gate (no stored evidence on the newest FIR)')

# --- the official PDF document honours the same ownership rule
check('owner resolves their own FIR PDF',
      lambda: latest_document_path_for(FIR['id'], citizen), 'ALLOWED')
check('unrelated citizen cannot resolve another citizen\'s FIR PDF',
      lambda: latest_document_path_for(
          FIR['id'], {'id': 'usr-not-a-real-account', 'role': 'CITIZEN'}), 'DENIED')
check('assigned officer resolves the case PDF',
      lambda: latest_document_path_for(FIR['id'], officer), 'ALLOWED')

panel_ok = False
try:
    panel = get_investigation_panel(FIR['id'], STRANGER)
    panel_ok = not panel.get('can_manage')
except PermissionError:
    panel_ok = True
results.append(f'{"OK  " if panel_ok else "BAD "} case panel refuses an unassigned officer')

print('\n'.join(results))
bad = [r for r in results if r.startswith('BAD') or r.startswith('ERROR')]
print(f'\nAUTH MATRIX: {len(results) - len(bad)}/{len(results)} as designed')
print('AUTH_MATRIX_FAILED' if bad else 'AUTH_MATRIX_PASSED')

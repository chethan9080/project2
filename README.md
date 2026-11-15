# Law Enforcement Portal - Portable Source Backup

Complete source archive of the Blockchain-Based Online FIR Management and
Tamper-Evident Audit Platform (NiceGUI + FastAPI + SQLite).

This archive was created on 2026-11-14. It contains source code only: the live
database, private uploads and operator secrets are intentionally excluded.

## 1. Contents

- `app.py` - application entry point (NiceGUI UI + FastAPI router).
- `backend/` - services, REST API, database layer and schema/migrations.
- `frontend/` - pages, components, i18n and static assets.
- `data/` - source modules that live beside the database (`authorized_officer.py`,
  `integrity.py`). The database file and upload folders are not included.
- `config/` - credit configuration and an example environment file.
- `tests/` - automated test suite (isolated temporary databases).
- Root `test_*.py`, `verify_*.py`, `audit_*.py` - legacy workflow scripts.
- `scripts/` - repository tooling.
- `docs/README.md` - full architecture, feature and role documentation.
- `.kiro/specs/` - feature specification documents.

Implemented workflows included in this archive:

- Authorized Officer tampering review with version history, SHA-256 hashes,
  previous vs current values, audit classification and full event history.
- Atomic "Change Officer" reassignment: closes the previous assignment with an
  exact revocation timestamp, creates the new assignment, preserves the FIR
  number, documents, evidence, versions, hashes and chat history.
- Reassignment reasons (Suspected tampering, Unauthorized modification, Security
  concern, Administrative reassignment, Investigation continuity) and internal
  remarks recorded in the audit trail.
- Notifications for the new officer, citizen, previous officer, Authorized
  Officer and active Verification Officers, stored in SQLite.
- Previous officer access revocation enforced in the backend (including the
  station-supervisor fallback), with public-safe citizen messaging.
- Case-tracking continuity: reassignment never resets or rewrites the current
  investigation stage.

## 2. Prerequisites

- Python 3.11 or newer (verified on Python 3.14).
- `pip` and the `venv` module.
- SQLite 3 (bundled with Python).

## 3. Installation

Git Bash / macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 4. Environment setup

Copy the example file and edit it:

```bash
cp .env.example .env
```

Required values:

- `STORAGE_SECRET` - signs login session cookies. The application refuses to start
  without it.
- `VALIDATOR_PRIVATE_KEY` - HMAC key used to sign ledger blocks. Ledger writes
  fail until a key is configured.

Generate strong values:

```bash
python -c "import secrets; print('STORAGE_SECRET=' + secrets.token_hex(32))"
python -c "import secrets; print('VALIDATOR_PRIVATE_KEY=' + secrets.token_hex(32))"
```

Optional values: `PORT` (default 8081), `APP_ENV`, `FIR_DB_PATH` (absolute path to
the SQLite file), SMTP/SMS provider settings, and staff seeding variables
(`SEED_*_USERNAMES`, `SEED_OFFICER_PASSWORD`). No default staff password exists;
seeding is disabled unless `SEED_OFFICER_PASSWORD` is set.

Leave `TEST_MODE` unset in production. Only the exact value `1` enables the
development OTP shortcut and dev auto-login. Never commit `.env`.

## 5. Database initialization and migrations

The default database path is `data/fir_platform.db` relative to the project root.
`app.py` calls `init_database()` and `seed_database()` on startup, so the schema,
Genesis block and required upload directories are created automatically.

To initialize manually:

```bash
PYTHONPATH=. python -c "from backend.services.db import init_database; init_database()"
```

Migrations are idempotent and run from `backend/services/db.py` at every startup.
They add missing columns such as `officer_assignments.reason`,
`officer_assignments.remarks`, `officer_assignments.revoked_at`,
`investigation_entries.updated_at` and complaint verification fields without
rewriting existing rows.

This archive contains no database. On first start an empty database is created.
Restore a database backup separately if you need existing case data.

## 6. Start the application

Git Bash / macOS / Linux:

```bash
PYTHONPATH=. python app.py
```

Windows PowerShell:

```powershell
$env:PYTHONPATH="."; python app.py
```

Open http://localhost:8081. The port can be changed with the `PORT` environment
variable.

## 7. Tests

```bash
PYTHONPATH=. python -m pytest -q
```

The suite points `FIR_DB_PATH` at per-test temporary databases under the OS temp
directory, so it does not modify a local production database. At packaging time
the suite reported 181 passed, 7 subtests passed, 0 failed.

Focused reassignment suite:

```bash
PYTHONPATH=. python -m pytest tests/test_officer_reassignment.py -q
```

## 8. Backup exclusions

The following are intentionally not in this archive:

- `.env` and any populated environment files (only `.env.example` is included).
- `.deps/`, virtual environments and installed packages.
- `.git/` (the source folder was not under Git version control).
- Caches, `__pycache__/`, `.pytest_cache/`, `.nicegui/` local storage and build output.
- The live SQLite database (`*.db`, `*.db-wal`, `*.db-shm`).
- All private uploads under `data/secure_uploads/` (citizen identity documents,
  photographs, FIR evidence, generated PDFs and complaint annexures).
- Certificates/keys and credential files.

Deploy, migrate and seed accounts on the destination machine; then restore any
case data you keep separately.

## 9. Further documentation

See `docs/README.md` for the architecture, role model, tamper-detection design,
case-record details and test coverage descriptions.

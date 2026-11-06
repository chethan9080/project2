# ⚖️ Blockchain-Based Online FIR Management & Tamper-Evident Audit Platform

> **Digital FIR — Secure Reporting & Cryptographic Audit Prototype**  
> *A high-trust, version-controlled, tamper-evident digital FIR ecosystem for citizens and law enforcement.*

---

## 📌 1. System Overview

In traditional FIR systems, record integrity can be susceptible to post-facto modifications, missing change logs, or lack of citizen visibility. This platform solves the integrity challenge by separating:

1. **Private Operational Data**: The complete FIR, citizen contact details, and evidence files reside securely in the application database (SQLite/PostgreSQL) with strict Role-Based Access Control (RBAC).
2. **Cryptographic Integrity Proofs**: Canonical JSON state snapshots are hashed using **SHA-256** and anchored to an immutable **Permissioned Blockchain Ledger**.

Every material change creates a **new immutable version** (e.g. Version 1 → Version 2 → Version 3), computes a new state hash chained to the previous hash (`H_prev`), requires a mandatory written reason, records the officer's identity/badge, and alerts the affected citizen.

---

## 🏛️ 2. Core Architecture

```
                       +-----------------------------------+
                       |        CITIZEN ONLINE PORTAL       |
                       |  - File 7-Step Digital FIR         |
                       |  - View Case Timeline & Diffs      |
                       |  - Receive Change Notifications    |
                       +-----------------+-----------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
|                           REST API & NICEGUI ENGINE                               |
|  - RBAC & Resource-Level Authorization (Citizen / Officer / Admin)                 |
|  - PBKDF2-HMAC-SHA256 Password Hashing                                             |
|  - Deterministic Canonical JSON Serializer                                         |
+-------------------+---------------------------------------+-----------------------+
                    |                                       |
                    v                                       v
+------------------------------------+   +------------------------------------------+
|       APPLICATION DATABASE         |   |      PERMISSIONED BLOCKCHAIN LEDGER      |
|  - users (Citizens & Officers)     |   |  - Blocks (Header, Merkle Root, PoA)     |
|  - firs (Active State)             |   |  - Transactions (recordFIRCreated/Change)|
|  - fir_versions (Snapshots v1..vn) |   |  - Hash Chain: H1 -> H2 -> H3            |
|  - fir_change_events (Diff Logs)   |   |  - Proof Validator Nodes                 |
|  - notifications                   |   +------------------------------------------+
+------------------------------------+
```

---

## 🔑 3. Key Features

### 👤 Citizen Capabilities
* **7-Step Guided FIR Filing Wizard**: Structured intake (Citizen Info → Incident → Accused → Witnesses → Evidence → Review → Blockchain Anchor).
* **Instant Reference Generation**: Issues official `FIR-2026-XXXXXX` and tracking reference `REF-2026-XXXXXX`.
* **Side-by-Side Change Viewer**: Inspect precisely **WHO** changed **WHAT**, **WHEN**, and **WHY** (OLD vs NEW).
* **Targeted Alerts**: Real-time notifications dispatched only to the affected citizen.

### 👮 Police Officer Operations
* **Centralized Station Worklist**: Filterable case queue with real-time integrity badges.
* **Controlled Edit Workflow**: Review screen showing old vs new values before committing, with mandatory written reason.
* **Blockchain Sealing**: Generates SHA-256 state proof and mines block transaction upon modification.
* **Tamper Detection Workbench**: Run verification across all FIRs and simulate database attacks.

### 🛡️ Tamper Detection & Security
* **Live Cryptographic Verification (`verifyFIRIntegrity`)**:
  1. Computes live canonical SHA-256 hash of active database row.
  2. Traverses on-chain transaction history.
  3. Verifies `tx[i].previous_hash == tx[i-1].new_hash` continuity.
  4. Returns **🟢 VERIFIED** or **🔴 TAMPER DETECTED**.
* **Zero PII on Chain**: Only hashes and audit metadata are recorded on the public/permissioned ledger.

---

## 👥 4. Login Roles & Credentials

The application supports exactly four roles:

1. **Citizen** — files and tracks complaints/FIRs.
2. **Police Officer** — works assigned cases and investigation updates.
3. **Verification Officer** — reviews, verifies, and assigns FIRs.
4. **Administrator / Main Monitoring Officer** — state-wide monitoring and audit.

Account credentials are provisioned privately by the system owner and stored only as PBKDF2-HMAC-SHA256 hashes in the database. No demo accounts or plain-text credentials are shipped with the application.

---

## 🚀 5. Quick Start & Execution

### Prerequisites
* Python 3.10+
* SQLite 3

### Running the Web Application
```bash
cd /Users/chethank.n/Documents/Codex
python3 app.py
```
Open your browser at: **`http://localhost:8081`**

### Running the Automated Test Suite
```bash
cd /Users/chethank.n/Documents/Codex
python3 -m unittest discover -s tests
```

---

## 📡 6. REST API Overview

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Register citizen or officer with PBKDF2 hash |
| `POST` | `/api/v1/auth/login` | Authenticate credentials and obtain session |
| `GET` | `/api/v1/auth/me` | Current authenticated user profile |
| `GET` | `/api/v1/firs` | List FIRs accessible to authenticated role |
| `POST` | `/api/v1/firs` | File new online FIR with Genesis block proof |
| `GET` | `/api/v1/firs/{id}` | Get full case file and integrity status |
| `PATCH` | `/api/v1/firs/{id}` | Modify permitted fields with mandatory reason |
| `GET` | `/api/v1/firs/{id}/versions` | Complete immutable version history |
| `GET` | `/api/v1/firs/{id}/changes` | Audit change events with OLD vs NEW diffs |
| `GET` | `/api/v1/firs/{id}/timeline` | Combined chronological lifecycle events |
| `GET` | `/api/v1/firs/{id}/verify-integrity`| Run cryptographic state verification |
| `POST` | `/api/v1/firs/{id}/assign-officer` | Assign lead investigating officer |
| `GET` | `/api/v1/notifications` | User notification inbox |
| `POST` | `/api/v1/blockchain/simulate-tamper` | Simulate unauthorized DB mutation for demo |
| `GET` | `/api/v1/blockchain/ledger` | Inspect mined blocks and transactions |

---

## 🧪 7. Tamper Detection Demonstration Flow

1. Sign in as the Administrator and open **`/admin/blockchain`** (or **`/admin/tampering-audit`**).
2. Every FIR lists its recorded hash next to the hash recomputed from the live row, so intact cases show **VERIFIED**.
3. To exercise the detection path, mutate a row out of band (or call `POST /api/v1/blockchain/simulate-tamper`), then reload the page.
4. The verification engine detects the hash mismatch and raises a **TAMPER DETECTED** alert showing:
   * **Expected Hash** (Blockchain record)
   * **Current Hash** (Database snapshot)
   * **Detected Timestamp**
5. Repair the record with `POST /api/v1/blockchain/restore-fir/{fir_id}`; the ledger appends the correction as a new immutable event.

---

## 🧾 8. Citizen Account Verification, Credential Generation & Notification Workflow

This section documents the complete post-registration workflow and the evidence that it works in the running application.

### 8.1 What happens at each stage

| Stage | Behaviour | Where |
|---|---|---|
| Registration | Details, ID document and photo are saved permanently; a unique application ID (`CVR-YYYYMMDD-XXXXXX`) is issued and the record starts as `PENDING`. No dashboard access is granted before approval. | `backend/services/citizen_registration_service.py` |
| Awaiting approval | The status screen shows the registration ID, submission date, a **Pending** badge and "Your registration is awaiting verification by the Verification Officer." | `frontend/pages/citizen_application_status.py` |
| Officer decision | The Verification Officer queue lists open applications with the submitted profile and uploads. Approve/Reject records the decision, reason (on rejection), officer user ID, officer name and timestamp. Approving twice is not possible — the action controls disappear once a record is decided. | `frontend/pages/citizen_verification.py` |
| Approval → account | One citizen account per approved registration, idempotent: re-approval cannot create a second credential row. The account is marked `VERIFIED`/`ACTIVE` and linked to the registration record. | `backend/services/citizen_credentials_service.py` (`issue_credentials`) |
| Username | Readable name slug plus an unguessable random tail (e.g. `e-citizen-0bedc5`). It never reproduces the registered email or mobile, and uniqueness is checked against both `users` and `citizen_credentials`. | `_generate_username` |
| Activation link | A `secrets.token_urlsafe(24)` single-use link is minted per citizen per purpose; only its SHA-256 digest is stored, with an expiry (`ACTIVATION_LINK_TTL_HOURS`, default 72) and an attempt cap (`ACTIVATION_MAX_ATTEMPTS`, default 5). Issuing a newer link supersedes the live one. | `mint_token` / `resolve_token` |
| Password | The citizen sets their own permanent password on `/activate/{token}` (or via `/citizen/reset-password`). Only a PBKDF2-HMAC-SHA256 hash (600k rounds, per-account salt) is stored. Plaintext passwords never appear in the database, logs, notification history or frontend source. | `backend/services/auth_service.py` (`set_password`), `frontend/pages/citizen_activation.py` |
| Notification | Subject **"Your Citizen Account Has Been Verified"** with the prescribed body, delivered by email/SMS when configured and always saved as a persistent in-app notice linked to the citizen user ID. Delivery is recorded honestly as `SENT`, `FAILED` or `NOT_CONFIGURED` — nothing is reported as sent unless the provider accepted it. Retries reuse the stored attempt counter and deduplicate by event. | `deliver_credentials` / `retry_delivery` |
| Delivery failure | The citizen sees "Your account has been verified, but credential notification delivery failed. Please use the secure account activation option or contact support." and the officer sees a **Retry Credential Delivery** action with the attempt count. | `activation_summary`, `frontend/pages/citizen_application_status.py` |
| Login | Backend validates credentials, re-checks that the account is active *and* verified, opens a session, and redirects to the Citizen Dashboard. Every citizen read is scoped to their own user ID. | `backend/services/auth_service.py`, `frontend/pages/citizen.py` |

Both paths work by design: approval activates the account immediately so the registration password keeps working, while the username, activation link and self-service password reset are issued in parallel — using the link simply overwrites the password.

### 8.2 Real-time and reliability

A newly filed FIR is written to the shared database and pushed over the in-process event bus, so the Verification Officer queue, the Main Authorized Officer oversight list and the assigned Police Officer dashboard update without a manual reload. Police Officers only ever see a case after verification and assignment. Notification records persist with delivery status, retry count and read/unread state; activation tokens are single-use, expiring, and attempt-limited.

### 8.3 Configuration

`.env.example` (and `config/.env.example`) document `SMTP_HOST/PORT/USERNAME/PASSWORD/MAIL_FROM/USE_TLS`, `SMS_GATEWAY_URL/API_KEY/SENDER`, `PUBLIC_BASE_URL`, `ACTIVATION_LINK_TTL_HOURS` and `ACTIVATION_MAX_ATTEMPTS`. With no provider configured, delivery is recorded as `NOT_CONFIGURED` and the citizen is routed to the secure activation/password-reset option.

### 8.4 Test results

**Automated suite** — `python3 -m unittest discover -s tests` → **77 tests, all passing** (includes 34 new tests in `tests/test_citizen_credentials.py` covering one-account-per-citizen, username uniqueness, digest-only token storage, single-use/expired/superseded/attempt-capped links, weak-password refusal, retry accounting, provider-secret containment, and enumeration resistance for unknown identifiers).

**Live browser end-to-end** — Playwright against the running application using the real SQLite database; the 22-step flow in the requirement was walked across four simultaneous sessions (Citizen, Verification Officer, Police Officer, Main Authorized Officer) with separate browser contexts and the system Chrome:

| Run | Coverage | Checks | Result |
|---|---|---|---|
| Part 1 | Registration → pending copy → officer decision record → credential issuance → notification text and delivery status → activation → login | 44 | **all passed** |
| Part 2 | Filing → live VO queue → verify → FIR number + blockchain proof → live assignment → police-only-after-assignment → RBAC denials → stage update with internal vs citizen-visible notes → citizen live pickup → officer instruction | 34 | **all passed** |
| Part 3 | Duplicate-approval refusal, superseded link, expired link, reset by username, old password invalidated, failed-delivery copy, retry after the provider returns, notification history contains no passwords or live tokens, read/unread | 29 | **all passed** |
| Persistence | After a full application restart: verified record, honest delivery copy, username + chosen password login, FIR and stage survival, persistent notices, officer decision and identity recorded, no reappeared Approve action, untouched pending applications | 9 | **all passed** |

116 live assertions plus 77 unit tests, **zero page errors** and no console failures observed during the runs. Email delivery during testing was accepted by a local SMTP capture endpoint standing in for the configured provider — no real mailbox was contacted.

---

## ⚖️ 9. Legal & Safety Notice
*This application is a technical demonstration prototype designed to showcase blockchain-backed integrity verification and role-based workflows for digital legal reporting. It does not represent an official government portal.*

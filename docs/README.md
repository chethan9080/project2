# ⚖️ Blockchain-Based Online FIR Management & Tamper-Evident Audit Platform

> **Digital FIR — Secure Reporting & Cryptographic Audit Prototype**  
> *A high-trust, version-controlled, tamper-evident digital FIR ecosystem for citizens and law enforcement.*

---

## 📌 1. System Overview

In traditional FIR systems, record integrity can be susceptible to post-facto modifications, missing change logs, or lack of citizen visibility. This platform solves the integrity challenge by separating:

1. **Private Operational Data**: The complete FIR, citizen contact details, and evidence files reside securely in the application database (SQLite/PostgreSQL) with strict Role-Based Access Control (RBAC).
2. **Cryptographic Integrity Proofs**: Canonical JSON state snapshots are hashed using **SHA-256** and anchored to an immutable **Permissioned Blockchain Ledger**.

Every material change creates a **new immutable version** (e.g. Version 1 → Version 2 → Version 3), computes a new state hash chained to the previous hash (`H_prev`), records the officer's identity/badge with an optional written reason, and alerts the affected citizen using public-safe wording only.

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
* **Controlled Edit Workflow**: Review screen showing old vs new values before committing, with an optional written reason.
* **Blockchain Sealing**: Generates SHA-256 state proof and mines block transaction upon modification.
* **Tamper Detection Workbench**: Run verification across all FIRs and simulate database attacks.

### 🔍 Verification Officer Operations
* **Pre-Registration FIR Detail Review**: On `/verification/fir-register/{complaint}` the officer corrects the offence category, incident date/time, place, jurisdiction, description, accused and witness details before the FIR exists; corrections are written to the complaint record, attributed to the officer, appended to the verification history and inherited by the registered FIR (`update_fir_details_before_registration`, `create_fir_from_complaint`).
* **Draft Document Review**: **Preview Draft FIR Document** renders the FIR the complaint would become, watermarked *PRE-REGISTRATION DRAFT* with the FIR number shown as `UNREGISTERED`. Nothing is persisted — official documents exist only after registration.
* **Live Desk**: The record card and the review form follow another desk's changes through the event bus plus a 15-second resync.

### 🗂️ Authorized Officer Case Oversight
One centralized case view — `/admin/investigations/{fir_id}` — carries the complete record for a case; no separate hash-report page or duplicate case page is involved. `get_admin_case_record` (`backend/services/investigation_service.py`) is Authorized-Officer-only and is returned inside `get_admin_case_detail`, so the monitor re-reads it on every event-bus refresh and 25-second resync.

* **Case Origin & Registration Record**: citizen name and issued username, registration date, application reference and date, identity-verification date with the approving officer, masked government ID, complaint and FIR counts, the original complaint (reference, submission date, category, description, verifying officer), the **complaint reference labelled separately from the official FIR number**, FIR registration date with the registering Verification Officer's name, role and badge, any pre-registration corrections, and the current status with closure date/officer/remarks once the case is closed.
* **FIR Document & Generated Versions**: every issued PDF with its version, generating officer, timestamp, `CURRENT` marker and SHA-256 digest; **Open** previews the stored file from secure storage.
* **Modifications Made on This Case**: Verification Officer actions (including `FIR_DETAILS_EDITED` pre-registration corrections) followed by the forensic diffs of every amendment — labelled field, **previous value vs updated value**, acting officer with role and badge, timestamp, version transition and the optional reason (`Reason: …` or `No reason recorded`). Police staff are stored with role `OFFICER`, so their amendments are filed in the police section, never in the verification section.
* **Version History & SHA-256 Integrity**: each immutable version with its author, reason, previous hash and full SHA-256 digest, plus the live chain verdict (`VERIFIED` / `INTEGRITY_ISSUE`) computed against the stored FIR row, so real tampering is reported inside the case's own audit section.
* **Citizen Profile Link (§4D)**: clicking the issued username opens `/admin/citizens/{citizen_id}`, which now shows the username, application reference/date, identity-verification date, approving officer and verification status, and per-FIR audit counts with the latest version's SHA-256 and chain verdict. A citizen without an issued username is labelled `USERNAME NOT ISSUED` rather than shown a placeholder value.
* **Verification**: `tests/test_admin_case_record.py` (17 tests) drives the record against an isolated database — role denial for Citizen, Police and Verification actors, registration attribution, document versions and digests, previous-vs-updated diffs with and without a reason, verification actions including pre-registration edits, per-version hash chaining, a genuinely tampered FIR row reported as `INTEGRITY_ISSUE`, closure attribution, and the absence of credentials or identity-document paths in the payload.

### 🎖️ Authorized Officer Police Officer Verification
`/admin/officers` is the single Police Officer Verification section (the existing sidebar entry — no new page or navigation item). It lists **every** police account, including pending and suspended ones, instead of only active accounts with a hardcoded badge.

* **Officer details**: badge/ID, staff username, rank, station, district, email, contact number, postal address, provisioning and last-update timestamps, read from the stored account.
* **Review and verify**: **Verify & Activate**, **Suspend Account** and **Return to Pending** call `update_officer_verification_status` (Authorized Officers only) with an optional reason. Each decision persists `status`, `verification_status` and `verified_at`, writes an `OFFICER_STATUS_UPDATE` row to `system_audit_logs` naming the acting officer, badge, old → new status and remarks, and notifies the officer concerned — never the citizen or the acting desk. `verified_at` is only set when an account is actually verified, so suspending or returning an account to pending cannot invent a verification date.
* **Status and assignment information**: live counters for accounts, verified/active, pending, suspended and active cases held; per-officer active-case and total-assignment counts; the full assignment trail with the assigning officer and `ACTIVE`/`REASSIGNED`/`COMPLETED` state; and the decision history newest first.
* **Access their assigned FIR cases**: every assigned case is listed with its FIR number, the citizen's name, complaint reference, stage and last update, and **Open Case** goes straight to the centralized case view `/admin/investigations/{fir_id}`.
* **Decisions take effect immediately**: staff sign-in requires an `ACTIVE` account, `get_staff_access_issue` re-reads the stored account so an open police session, the REST API and protected file endpoints stop honouring a suspended or unverified officer, and `OFFICER_STATUS_UPDATED` is on the Authorized Officer event list so a second desk sees the change with no reload (30-second resync as a fallback).
* **Verification**: `tests/test_officer_verification.py` (21 tests) covers role denial for reads and decisions, invalid status and non-officer targets, directory visibility of pending/suspended accounts, real case counts including a closed case leaving the active count, persisted status/verification/timestamp behaviour, audit attribution with and without a reason, officer-only notification, refused sign-in and revoked sessions, and the absence of credentials or identity-document paths in the dossier.

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
| `PATCH` | `/api/v1/firs/{id}` | Modify permitted fields, with an optional reason |
| `GET` | `/api/v1/firs/{id}/versions` | Immutable version history — Authorized Officers only |
| `GET` | `/api/v1/firs/{id}/changes` | Audit change events with OLD vs NEW diffs — Authorized Officers only |
| `GET` | `/api/v1/firs/{id}/timeline` | Combined chronological lifecycle events |
| `GET` | `/api/v1/firs/{id}/verify-integrity` | Cryptographic state verification — Authorized Officers only |
| `POST` | `/api/v1/firs/{id}/assign-officer` | Assign lead investigating officer |
| `GET` | `/api/v1/notifications` | User notification inbox |
| `POST` | `/api/v1/blockchain/simulate-tamper` | Simulate DB mutation — Authorized Officers only |
| `GET` | `/api/v1/blockchain/ledger` | Inspect mined blocks and transactions — Authorized Officers only |

Hash values, blockchain metadata and the technical audit trail are served only to
Authorized Officers. Verification Officers, Police Officers and Citizens never receive
them from the API or see them in their portals.

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

**Automated suite** — `python3 -m unittest discover -s tests` → **141 tests, all passing** (34 tests in `tests/test_citizen_credentials.py` covering one-account-per-citizen, username uniqueness, digest-only token storage, single-use/expired/superseded/attempt-capped links, weak-password refusal, retry accounting, provider-secret containment, and enumeration resistance for unknown identifiers, 12 notification-matrix tests in §9.4, 14 pre-registration FIR review tests in §3, 17 centralized case-record tests in §3, and 21 police-officer-verification tests in §3).

**Live browser end-to-end** — Playwright against the running application using the real SQLite database; the 22-step flow in the requirement was walked across four simultaneous sessions (Citizen, Verification Officer, Police Officer, Main Authorized Officer) with separate browser contexts and the system Chrome:

| Run | Coverage | Checks | Result |
|---|---|---|---|
| Part 1 | Registration → pending copy → officer decision record → credential issuance → notification text and delivery status → activation → login | 44 | **all passed** |
| Part 2 | Filing → live VO queue → verify → FIR number + blockchain proof → live assignment → police-only-after-assignment → RBAC denials → stage update with internal vs citizen-visible notes → citizen live pickup → officer instruction | 34 | **all passed** |
| Part 3 | Duplicate-approval refusal, superseded link, expired link, reset by username, old password invalidated, failed-delivery copy, retry after the provider returns, notification history contains no passwords or live tokens, read/unread | 29 | **all passed** |
| Persistence | After a full application restart: verified record, honest delivery copy, username + chosen password login, FIR and stage survival, persistent notices, officer decision and identity recorded, no reappeared Approve action, untouched pending applications | 9 | **all passed** |
| Pre-registration review | VO detail corrections persisted and attributed → live desk sync → draft PDF with no FIR number → registration inherits the corrections → no draft document rows → AO alerted once | 25 | **all passed** |
| Centralized case record | AO case view → police amendment in a second session → AO diff appears with no reload → previous vs updated values, officer identity, optional reason, version transition → per-version SHA-256 and chain verdict → document preview → origin/registration items → username click opens the citizen profile with audit and hash detail → multi-version chain continuity | 46 | **all passed** |
| Police Officer Verification | Directory of all five stored accounts (no hardcoded badge) → unreviewed account shows no invented verification date → officer details, assignment trail and three assigned FIRs → Open Case reaches the case monitor → search filter → second AO desk suspends with a reason → watching desk updates with no reload → open police session refused → correct credentials refused → officer notified → re-verification restores sign-in → both decisions persist after reload → account left ACTIVE & VERIFIED | 52 | **all passed** |

239 live assertions, **zero page errors** and no console failures observed during the runs; the current automated suite stands at the 141 tests reported in §8.4. Email delivery during testing was accepted by a local SMTP capture endpoint standing in for the configured provider — no real mailbox was contacted.

---

## 🔔 9. Centralized Real-Time Notification Delivery Matrix

Every portal alert is produced by one service — `backend/services/notification_service.py` — and written to the single `notifications` table. No page composes its own copy of an event, and the header bell and the notification centre read the same stored rows.

### 9.1 Delivery primitives

| Function | Behaviour |
|---|---|
| `create_notification(user_id, …, event_id)` | Inserts one row for one recipient. A repeat call with the same `user_id + event_id` is dropped, so a retried workflow step cannot alert a user twice. |
| `notify_role(role, …, exclude_user_id)` | Resolves the currently ACTIVE accounts for a role with `get_active_user_ids` and stores one alert per recipient under a per-user key (`event_id-user_id`). The acting officer is excluded by design: their confirmation is the in-page success message, not an inbox row. |
| `get_user_notifications` / `get_unread_count` | Both the bell badge and the inbox list are computed from these reads, so the unread count always equals the unaddressed rows on screen. |
| `mark_notification_read` / `mark_all_read` | Update the stored row and publish a read-state event so the bell badge drops without a refresh. |

### 9.2 Event × role matrix

| Event | Citizen | Verification Officer | Police Officer | Authorized Officer |
|---|---|---|---|---|
| Citizen registration submitted | Application confirmation | New application in the queue | — | New registration record |
| Registration approved / rejected | Status + credential/activation notice | Decision confirmation (in-page) | — | Approval/audit record |
| Complaint submitted | Filing confirmation with complaint reference | New complaint to verify | — | New complaint oversight alert |
| FIR details edited before registration | — | Corrections shown live in the registration desk | — | Audit alert naming the changed fields |
| FIR registered from a complaint | FIR document and case update | FIR registered alert | Assigned FIR (only after assignment) | Registration audit record |
| Investigating officer assigned | Officer assigned | Assignment confirmation | New assignment | Assignment audit record |
| FIR record modified | Public-safe status wording | Record updated alert | Case amended (when edited by another officer) | Full audit details incl. changed fields |
| Investigation stage update | Tracking timeline entry | Case progress alert | Stage confirmation | Full audit details |
| Case closed | Closure notice | Case closed | Closure confirmation | Closure audit record |

Citizen-bound text is curated: internal remarks, officer badge numbers, hashes, blockchain metadata and investigation notes never enter a citizen notification (`PUBLIC_STAGE_TEXT` in `backend/services/investigation_service.py` supplies the approved stage wording used by `update_case_stage`).

### 9.3 Real-time delivery and missed events

Writes publish a `NOTIFICATION_CREATED` event on the in-process bus (`backend/services/realtime_events.py`); each inbox subscribes and refreshes the live list on arrival. Because bus queues are in-memory and drop the oldest event while a tab is reconnecting, every notification page also re-reads the database on a timer — Citizen 30 s, Police Officer 30 s, Verification Officer 20 s, Authorized Officer 25 s — so no stored alert can be permanently missed.

### 9.4 Verification

`tests/test_notification_matrix.py` (12 tests) drives each row of the matrix against an isolated database and asserts the recipient sets, actor exclusion, per-user deduplication, one-alert-per-repeat-event, citizen messages containing no hash or internal-remark text, and that unread count equals inbox length. `/admin/notifications` adds the Authorized Officer inbox with a category filter built from the stored notification types.

`tests/test_fir_draft_review.py` (14 tests) covers the pre-registration row: review-role RBAC, the edit refused once an FIR exists, corrections persisted and attributed, the append-only history entry, required fields that cannot be cleared, columns outside the whitelist ignored, an unchanged save storing no new history row, registration inheriting the reviewed values, and the draft PDF rendering without an official document record.

---

## ⚖️ 10. Legal & Safety Notice
*This application is a technical demonstration prototype designed to showcase blockchain-backed integrity verification and role-based workflows for digital legal reporting. It does not represent an official government portal.*

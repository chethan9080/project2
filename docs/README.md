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
python3 -m unittest tests/test_fir_blockchain.py
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

## ⚖️ 8. Legal & Safety Notice
*This application is a technical demonstration prototype designed to showcase blockchain-backed integrity verification and role-based workflows for digital legal reporting. It does not represent an official government portal.*

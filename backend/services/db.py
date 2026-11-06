"""
SQLite Database Layer for Blockchain-Based Online FIR Management Platform.
Implements relational tables, foreign key constraints, indexes, and migrations.
"""

import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

DB_PATH = os.environ.get('FIR_DB_PATH', os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'fir_platform.db')))


def get_db_connection() -> sqlite3.Connection:
    """Create and return a thread-safe sqlite3 connection with Row factory."""
    db_path = os.environ.get('FIR_DB_PATH', DB_PATH)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_database() -> None:
    """Initialize all database tables, columns, and indexes."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users Table (Citizens, Officers, Verification Officers, Admins)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('CITIZEN', 'OFFICER', 'VERIFICATION_OFFICER', 'ADMIN')),
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'PENDING_VERIFICATION', 'SUSPENDED')),
        badge_number TEXT,
        station TEXT,
        rank TEXT,
        district TEXT,
        address TEXT,
        gov_id_masked TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # 2. FIR Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS firs (
        id TEXT PRIMARY KEY,
        fir_number TEXT UNIQUE NOT NULL,
        reference_number TEXT UNIQUE NOT NULL,
        citizen_id TEXT NOT NULL,
        assigned_officer_id TEXT,
        police_station TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('PENDING_VERIFICATION', 'VERIFIED', 'SUBMITTED', 'UNDER_REVIEW', 'UNDER_INVESTIGATION', 'CHARGESHEET_FILED', 'RESOLVED', 'CLOSED', 'NEEDS_CORRECTION', 'REJECTED')),
        incident_type TEXT NOT NULL,
        incident_date TEXT NOT NULL,
        incident_time TEXT NOT NULL,
        incident_location TEXT NOT NULL,
        description TEXT NOT NULL,
        accused_details TEXT,
        witness_details TEXT,
        evidence_files TEXT,
        current_version INTEGER NOT NULL DEFAULT 1,
        current_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (citizen_id) REFERENCES users(id),
        FOREIGN KEY (assigned_officer_id) REFERENCES users(id)
    );
    """)

    # 3. FIR Version Table (Immutable history of FIR snapshots)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fir_versions (
        id TEXT PRIMARY KEY,
        fir_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        snapshot_json TEXT NOT NULL,
        previous_hash TEXT,
        current_hash TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        change_reason TEXT NOT NULL,
        FOREIGN KEY (fir_id) REFERENCES firs(id),
        FOREIGN KEY (created_by) REFERENCES users(id),
        UNIQUE (fir_id, version_number)
    );
    """)

    # 4. FIR Change Events Table (Forensic-grade immutable audit logs with diffs)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fir_change_events (
        id TEXT PRIMARY KEY,
        event_number TEXT UNIQUE NOT NULL,
        fir_id TEXT NOT NULL,
        version_id TEXT NOT NULL,
        previous_version INTEGER NOT NULL,
        new_version INTEGER NOT NULL,
        actor_id TEXT NOT NULL,
        actor_name TEXT NOT NULL,
        actor_badge TEXT,
        actor_role TEXT NOT NULL,
        event_type TEXT NOT NULL DEFAULT 'AUTHORIZED_FIR_UPDATE',
        changed_fields_json TEXT NOT NULL,
        old_values_json TEXT NOT NULL,
        new_values_json TEXT NOT NULL,
        reason TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'IST (UTC+05:30)',
        ip_address TEXT,
        device_info TEXT,
        previous_hash TEXT,
        new_hash TEXT NOT NULL,
        blockchain_tx_id TEXT NOT NULL,
        blockchain_block INTEGER,
        blockchain_status TEXT NOT NULL DEFAULT 'CONFIRMED',
        event_hash TEXT NOT NULL,
        FOREIGN KEY (fir_id) REFERENCES firs(id),
        FOREIGN KEY (version_id) REFERENCES fir_versions(id),
        FOREIGN KEY (actor_id) REFERENCES users(id)
    );
    """)

    # 5. Notifications Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        fir_id TEXT,
        complaint_id TEXT,
        event_id TEXT,
        type TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        metadata_json TEXT,
        is_read INTEGER NOT NULL DEFAULT 0,
        severity TEXT NOT NULL DEFAULT 'INFO' CHECK(severity IN ('INFO', 'SUCCESS', 'WARNING', 'ALERT')),
        created_at TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (fir_id) REFERENCES firs(id),
        FOREIGN KEY (complaint_id) REFERENCES complaints(id)
    );
    """)

    # 6. Officer Assignments Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS officer_assignments (
        id TEXT PRIMARY KEY,
        fir_id TEXT NOT NULL,
        officer_id TEXT NOT NULL,
        assigned_by TEXT NOT NULL,
        assigned_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'REASSIGNED', 'COMPLETED')),
        FOREIGN KEY (fir_id) REFERENCES firs(id),
        FOREIGN KEY (officer_id) REFERENCES users(id),
        FOREIGN KEY (assigned_by) REFERENCES users(id)
    );
    """)

    # 7. Blockchain Blocks Table (Local Permissioned Cryptographic Ledger)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blockchain_blocks (
        block_index INTEGER PRIMARY KEY,
        previous_block_hash TEXT NOT NULL,
        merkle_root TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        block_hash TEXT NOT NULL UNIQUE,
        validator_node TEXT NOT NULL,
        transactions_count INTEGER NOT NULL DEFAULT 0
    );
    """)

    # 8. Blockchain Transactions Table (Smart Contract State Audit Events)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blockchain_transactions (
        tx_id TEXT PRIMARY KEY,
        block_index INTEGER NOT NULL,
        fir_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        previous_hash TEXT,
        new_hash TEXT NOT NULL,
        actor_hash TEXT NOT NULL,
        event_hash TEXT NOT NULL,
        contract_method TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        tx_hash TEXT NOT NULL UNIQUE,
        FOREIGN KEY (block_index) REFERENCES blockchain_blocks(block_index)
    );
    """)

    # 9. System Audit Logs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_audit_logs (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        user_id TEXT,
        user_email TEXT,
        role TEXT,
        action TEXT NOT NULL,
        resource_type TEXT NOT NULL,
        resource_id TEXT,
        details TEXT,
        ip_address TEXT,
        status TEXT NOT NULL
    );
    """)

    # 9B. Officer Activity Logs (Server-Side Timestamped Case Tracking)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS officer_activity_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        user_name TEXT NOT NULL,
        user_role TEXT NOT NULL,
        action_type TEXT NOT NULL,
        fir_id TEXT NOT NULL,
        fir_number TEXT NOT NULL,
        status_from TEXT,
        status_to TEXT,
        details TEXT,
        timestamp TEXT NOT NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_fir ON officer_activity_logs(fir_id, timestamp);")

    # 10. Officer Authentication & Audit Sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS officer_sessions (
        id TEXT PRIMARY KEY,
        officer_id TEXT NOT NULL,
        officer_name TEXT NOT NULL,
        badge_number TEXT NOT NULL,
        role TEXT NOT NULL,
        station TEXT,
        login_time TEXT NOT NULL,
        logout_time TEXT,
        location_name TEXT,
        latitude REAL,
        longitude REAL,
        ip_address TEXT,
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'LOGGED_OUT', 'EXPIRED')),
        FOREIGN KEY (officer_id) REFERENCES users(id)
    );
    """)

    # 11. Citizen Identity Verifications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_verifications (
        id TEXT PRIMARY KEY,
        citizen_id TEXT NOT NULL,
        gov_id_type TEXT NOT NULL,
        gov_id_masked TEXT NOT NULL,
        mobile TEXT NOT NULL,
        otp_verified INTEGER NOT NULL DEFAULT 0,
        photo_verified INTEGER NOT NULL DEFAULT 0,
        location_verified INTEGER NOT NULL DEFAULT 0,
        location_data_json TEXT,
        status TEXT NOT NULL DEFAULT 'APPROVED' CHECK(status IN ('PENDING', 'APPROVED', 'REJECTED')),
        created_at TEXT NOT NULL,
        FOREIGN KEY (citizen_id) REFERENCES users(id)
    );
    """)

    # 11A. Mobile OTP Sessions (citizen registration step 3)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS otp_sessions (
        id TEXT PRIMARY KEY,
        mobile TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0),
        verified INTEGER NOT NULL DEFAULT 0,
        delivery_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(delivery_status IN ('PENDING', 'SENT', 'TEST_MODE'))
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_sessions_mobile ON otp_sessions(mobile, created_at);")

    # 11B. Citizen Registration Applications (Verification Officer review queue)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_applications (
        id TEXT PRIMARY KEY,
        reference TEXT UNIQUE NOT NULL,
        citizen_id TEXT NOT NULL UNIQUE,
        full_name TEXT NOT NULL,
        date_of_birth TEXT,
        gender TEXT,
        mobile TEXT NOT NULL,
        email TEXT NOT NULL,
        address TEXT,
        state TEXT,
        district TEXT,
        username TEXT,
        gov_id_type TEXT NOT NULL,
        gov_id_masked TEXT NOT NULL,
        id_document_path TEXT,
        id_document_name TEXT,
        photo_path TEXT,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN (
            'PENDING', 'UNDER_REVIEW', 'ADDITIONAL_INFO_REQUIRED', 'APPROVED', 'REJECTED'
        )),
        internal_remarks TEXT,
        submitted_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        reviewed_by TEXT,
        reviewed_by_name TEXT,
        reviewed_at TEXT,
        FOREIGN KEY (citizen_id) REFERENCES users(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_apps_status ON citizen_applications(status, submitted_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_apps_citizen ON citizen_applications(citizen_id);")

    # 11C. Immutable Citizen Application Verification History
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_application_events (
        id TEXT PRIMARY KEY,
        application_id TEXT NOT NULL,
        action TEXT NOT NULL,
        status_from TEXT,
        status_to TEXT,
        remarks TEXT,
        actor_id TEXT,
        actor_name TEXT,
        actor_role TEXT,
        actor_badge TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (application_id) REFERENCES citizen_applications(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_app_events ON citizen_application_events(application_id, created_at);")

    # 11D. Verification Officer / Citizen alerts for registration applications
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_application_alerts (
        id TEXT PRIMARY KEY,
        application_id TEXT NOT NULL,
        recipient_id TEXT NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (application_id) REFERENCES citizen_applications(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_alerts_recipient ON citizen_application_alerts(recipient_id, is_read);")

    # 11E. Issued Citizen Login Credentials
    # One row per approved citizen. The activation token itself is never stored
    # here (see citizen_activation_tokens), and no plaintext password ever is.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_credentials (
        id TEXT PRIMARY KEY,
        citizen_id TEXT NOT NULL UNIQUE,
        application_id TEXT,
        reference TEXT,
        username TEXT NOT NULL UNIQUE,
        issued_at TEXT NOT NULL,
        issued_by TEXT,
        issued_by_name TEXT,
        delivery_channel TEXT NOT NULL DEFAULT 'NONE' CHECK(delivery_channel IN ('NONE', 'IN_APP', 'EMAIL', 'SMS')),
        delivery_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(delivery_status IN ('PENDING', 'SENT', 'FAILED', 'NOT_CONFIGURED')),
        delivery_detail TEXT,
        delivery_attempts INTEGER NOT NULL DEFAULT 0,
        delivered_at TEXT,
        password_set_at TEXT,
        activated_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (citizen_id) REFERENCES users(id),
        FOREIGN KEY (application_id) REFERENCES citizen_applications(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_credentials_delivery ON citizen_credentials(delivery_status, issued_at);")

    # 11F. Single-Use Activation and Password-Reset Tokens
    # Only a hash of the token is stored, so a database copy cannot mint working
    # links. Exactly one live token per citizen per purpose.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS citizen_activation_tokens (
        id TEXT PRIMARY KEY,
        citizen_id TEXT NOT NULL,
        purpose TEXT NOT NULL CHECK(purpose IN ('ACCOUNT_ACTIVATION', 'PASSWORD_RESET')),
        token_hash TEXT NOT NULL UNIQUE,
        issued_by TEXT,
        issued_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 5,
        used_at TEXT,
        superseded_at TEXT,
        FOREIGN KEY (citizen_id) REFERENCES users(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_activation_tokens_lookup ON citizen_activation_tokens(citizen_id, purpose, used_at);")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_activation_tokens_live
        ON citizen_activation_tokens(citizen_id, purpose)
        WHERE used_at IS NULL AND superseded_at IS NULL;
    """)

    # Dynamic migrations for any existing tables
    def add_col_if_missing(table, col_def):
        col_name = col_def.split()[0]
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # Already exists

    add_col_if_missing("fir_change_events", "event_number TEXT")
    add_col_if_missing("fir_change_events", "previous_version INTEGER")
    add_col_if_missing("fir_change_events", "new_version INTEGER")
    add_col_if_missing("fir_change_events", "actor_badge TEXT")
    add_col_if_missing("fir_change_events", "timezone TEXT DEFAULT 'IST (UTC+05:30)'")
    add_col_if_missing("fir_change_events", "ip_address TEXT")
    add_col_if_missing("fir_change_events", "device_info TEXT")
    add_col_if_missing("fir_change_events", "previous_hash TEXT")
    add_col_if_missing("fir_change_events", "new_hash TEXT")
    add_col_if_missing("fir_change_events", "blockchain_block INTEGER")
    add_col_if_missing("notifications", "metadata_json TEXT")

    # Issued login handle + verification outcome for citizens. NULL for staff and
    # for accounts created before credential issuance existed.
    add_col_if_missing("users", "username TEXT")
    add_col_if_missing("users", "verification_status TEXT")
    add_col_if_missing("users", "verified_at TEXT")
    add_col_if_missing("users", "password_changed_at TEXT")
    try:
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL;"
        )
    except sqlite3.IntegrityError:
        # A pre-existing database may already hold duplicate handles. Boot must
        # still succeed; issuance refuses to add a third and reports the clash.
        print("[startup] users.username unique index skipped: duplicate handles already present")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_login_lookup ON users(email, phone, name);")

    # Create Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_number ON firs(fir_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_citizen ON firs(citizen_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_officer ON firs(assigned_officer_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_status ON firs(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_created ON firs(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_versions_fir ON fir_versions(fir_id, version_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_fir ON fir_change_events(fir_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_num ON fir_change_events(event_number);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bc_tx_fir ON blockchain_transactions(fir_id, version);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bc_tx_hash ON blockchain_transactions(tx_hash);")
    # 12. Chat Messages between Citizens and Assigned Officers
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        fir_id TEXT,
        sender_id TEXT NOT NULL,
        receiver_id TEXT NOT NULL,
        sender_role TEXT NOT NULL CHECK(sender_role IN ('CITIZEN', 'OFFICER', 'ADMIN')),
        message TEXT NOT NULL,
        is_read INTEGER NOT NULL DEFAULT 0,
        sent_at TEXT NOT NULL,
        FOREIGN KEY (sender_id) REFERENCES users(id),
        FOREIGN KEY (receiver_id) REFERENCES users(id)
    );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_officer_sessions ON officer_sessions(officer_id, status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citizen_verifs ON citizen_verifications(citizen_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_msgs ON chat_messages(sender_id, receiver_id, sent_at);")

    # 13. Complaints Table (Pre-FIR citizen complaints, linked to FIRs when converted)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS complaints (
        id TEXT PRIMARY KEY,
        reference TEXT UNIQUE NOT NULL,
        citizen_id TEXT NOT NULL,
        applicant_name TEXT,
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT NOT NULL,
        location TEXT NOT NULL,
        landmark TEXT,
        area TEXT,
        district TEXT,
        state TEXT,
        police_station TEXT,
        incident_date TEXT,
        incident_time TEXT,
        evidence_files TEXT NOT NULL DEFAULT '[]',
        rejection_reason TEXT,
        submitted_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK(status IN (
            'SUBMITTED', 'ASSIGNED', 'UNDER_REVIEW', 'VERIFIED', 'ADDITIONAL_INFO_REQUIRED',
            'INVESTIGATION', 'RESOLVED', 'CLOSED', 'FIR_CREATED', 'REJECTED'
        )),
        assigned_officer_id TEXT,
        assigned_officer_name TEXT,
        assigned_at TEXT,
        fir_id TEXT,
        verification_status TEXT NOT NULL DEFAULT 'PENDING',
        verification_remarks TEXT,
        verified_by TEXT,
        verified_by_name TEXT,
        verified_at TEXT,
        FOREIGN KEY (citizen_id) REFERENCES users(id),
        FOREIGN KEY (assigned_officer_id) REFERENCES users(id),
        FOREIGN KEY (fir_id) REFERENCES firs(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_citizen ON complaints(citizen_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_officer ON complaints(assigned_officer_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_ref ON complaints(reference);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);")

    # 13A. Append-only complaint verification history (officer identity, decision, remarks)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS complaint_verification_events (
        id TEXT PRIMARY KEY,
        complaint_id TEXT NOT NULL,
        action TEXT NOT NULL,
        status_from TEXT,
        status_to TEXT,
        remarks TEXT,
        actor_id TEXT,
        actor_name TEXT,
        actor_role TEXT,
        actor_badge TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (complaint_id) REFERENCES complaints(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaint_events ON complaint_verification_events(complaint_id, created_at);")

    # 13B. Generated FIR documents (private storage + append-only version history)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fir_documents (
        id TEXT PRIMARY KEY,
        fir_id TEXT NOT NULL,
        document_type TEXT NOT NULL DEFAULT 'FIR_PDF',
        version INTEGER NOT NULL DEFAULT 1,
        file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        generated_by TEXT,
        generated_by_name TEXT,
        generated_at TEXT NOT NULL,
        is_current INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (fir_id) REFERENCES firs(id),
        UNIQUE (fir_id, document_type, version)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fir_docs ON fir_documents(fir_id, is_current);")

    # Migration: ensure chat_messages has complaint_id column
    add_col_if_missing("chat_messages", "complaint_id TEXT")

    # Migration: ensure firs table has complaint_id column (complaint→FIR traceability)
    add_col_if_missing("firs", "complaint_id TEXT")

    # Migration: complaint verification decision fields (Verification Officer desk)
    add_col_if_missing("complaints", "verification_status TEXT NOT NULL DEFAULT 'PENDING'")
    add_col_if_missing("complaints", "verification_remarks TEXT")
    add_col_if_missing("complaints", "verified_by TEXT")
    add_col_if_missing("complaints", "verified_by_name TEXT")
    add_col_if_missing("complaints", "verified_at TEXT")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_verification ON complaints(verification_status);")

    conn.commit()
    conn.close()


def migrate_fir_status_constraint():
    """
    Migrate existing FIR table to support new statuses: PENDING_VERIFICATION and VERIFIED.
    SQLite doesn't support ALTER TABLE to modify constraints, so we need to:
    1. Create a new table with updated constraints
    2. Copy data from old table
    3. Drop old table
    4. Rename new table
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if migration is needed
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='firs'")
        if not cursor.fetchone():
            conn.close()
            return  # Table doesn't exist yet, no migration needed
        
        # Check if the CHECK constraint already includes PENDING_VERIFICATION.
        # We do this by inspecting the table's CREATE statement stored in sqlite_master.
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='firs'")
        row = cursor.fetchone()
        if row and row[0] and 'NEEDS_CORRECTION' in row[0]:
            # Constraint already includes new statuses — migration already done
            conn.close()
            return
        # Otherwise migration is needed
        
        # Temporarily disable foreign keys for migration
        cursor.execute("PRAGMA foreign_keys = OFF")
        
        # Create temporary table with new constraints
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS firs_new (
            id TEXT PRIMARY KEY,
            fir_number TEXT UNIQUE NOT NULL,
            reference_number TEXT UNIQUE NOT NULL,
            citizen_id TEXT NOT NULL,
            assigned_officer_id TEXT,
            police_station TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('PENDING_VERIFICATION', 'VERIFIED', 'SUBMITTED', 'UNDER_REVIEW', 'UNDER_INVESTIGATION', 'CHARGESHEET_FILED', 'RESOLVED', 'CLOSED', 'NEEDS_CORRECTION', 'REJECTED')),
            incident_type TEXT NOT NULL,
            incident_date TEXT NOT NULL,
            incident_time TEXT NOT NULL,
            incident_location TEXT NOT NULL,
            description TEXT NOT NULL,
            accused_details TEXT,
            witness_details TEXT,
            evidence_files TEXT,
            current_version INTEGER NOT NULL DEFAULT 1,
            current_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)
        
        # Copy existing data
        cursor.execute("""
        INSERT INTO firs_new 
        SELECT * FROM firs
        """)
        
        # Drop old table
        cursor.execute("DROP TABLE IF EXISTS firs")
        
        # Rename new table
        cursor.execute("ALTER TABLE firs_new RENAME TO firs")
        
        # Recreate indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_number ON firs(fir_number);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_citizen ON firs(citizen_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_officer ON firs(assigned_officer_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_status ON firs(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_firs_created ON firs(created_at);")
        
        # Re-enable foreign keys
        cursor.execute("PRAGMA foreign_keys = ON")
        
        conn.commit()
        print("✓ Migration completed: FIR status constraint updated to include PENDING_VERIFICATION and VERIFIED")
        
    except sqlite3.OperationalError as e:
        # Migration already applied or table structure matches
        error_msg = str(e).lower()
        if "duplicate column name" in error_msg or "already exists" in error_msg or "no such table" in error_msg:
            pass
        else:
            print(f"Migration note: {e}")
    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            conn.commit()
        except:
            pass
        conn.close()


def migrate_user_role_constraint():
    """Migrate users table constraint to include VERIFICATION_OFFICER role."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not cursor.fetchone():
            conn.close()
            return
        
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'")
        row = cursor.fetchone()
        if row and row[0] and 'VERIFICATION_OFFICER' in row[0]:
            conn.close()
            return

        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_new (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('CITIZEN', 'OFFICER', 'VERIFICATION_OFFICER', 'ADMIN')),
            status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'PENDING_VERIFICATION', 'SUSPENDED')),
            badge_number TEXT,
            station TEXT,
            rank TEXT,
            district TEXT,
            address TEXT,
            gov_id_masked TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)
        cursor.execute("INSERT INTO users_new SELECT * FROM users")
        cursor.execute("DROP TABLE IF EXISTS users")
        cursor.execute("ALTER TABLE users_new RENAME TO users")
        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        print("✓ Migration completed: User role constraint updated to include VERIFICATION_OFFICER")
    except Exception as e:
        print(f"User role migration note: {e}")
    finally:
        conn.close()



init_database()


def migrate_complaints_status_constraint() -> None:
    """Rebuild the complaints table with the full citizen-filing schema.

    Adds police station / location detail / evidence / rejection columns and the
    ADDITIONAL_INFO_REQUIRED and REJECTED statuses. SQLite cannot alter CHECK
    constraints, so the table is rebuilt and existing rows are copied.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='complaints'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return
        sql = row[0]
        existing_cols = {r[1] for r in cursor.execute("PRAGMA table_info(complaints)")}
        if (
            'rejection_reason' in existing_cols
            and 'police_station' in existing_cols
            and 'evidence_files' in existing_cols
            and 'verification_status' in existing_cols
            and "'VERIFIED'" in sql
            and 'REJECTED' in sql
            and 'ADDITIONAL_INFO_REQUIRED' in sql
        ):
            return

        conn.commit()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("""
        CREATE TABLE complaints_migrated (
            id TEXT PRIMARY KEY,
            reference TEXT UNIQUE NOT NULL,
            citizen_id TEXT NOT NULL,
            applicant_name TEXT,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            location TEXT NOT NULL,
            landmark TEXT,
            area TEXT,
            district TEXT,
            state TEXT,
            police_station TEXT,
            incident_date TEXT,
            incident_time TEXT,
            evidence_files TEXT NOT NULL DEFAULT '[]',
            rejection_reason TEXT,
            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'SUBMITTED' CHECK(status IN (
                'SUBMITTED', 'ASSIGNED', 'UNDER_REVIEW', 'VERIFIED', 'ADDITIONAL_INFO_REQUIRED',
                'INVESTIGATION', 'RESOLVED', 'CLOSED', 'FIR_CREATED', 'REJECTED'
            )),
            assigned_officer_id TEXT,
            assigned_officer_name TEXT,
            assigned_at TEXT,
            fir_id TEXT,
            verification_status TEXT NOT NULL DEFAULT 'PENDING',
            verification_remarks TEXT,
            verified_by TEXT,
            verified_by_name TEXT,
            verified_at TEXT
        )
        """)
        target_cols = [
            'id', 'reference', 'citizen_id', 'applicant_name', 'category', 'title',
            'description', 'location', 'landmark', 'area', 'district', 'state',
            'police_station', 'incident_date', 'incident_time', 'evidence_files',
            'rejection_reason', 'submitted_at', 'updated_at', 'status',
            'assigned_officer_id', 'assigned_officer_name', 'assigned_at', 'fir_id',
            'verification_status', 'verification_remarks', 'verified_by',
            'verified_by_name', 'verified_at',
        ]
        copy_cols = [c for c in target_cols if c in existing_cols]
        col_list = ', '.join(copy_cols)
        cursor.execute(
            f"INSERT INTO complaints_migrated ({col_list}) SELECT {col_list} FROM complaints"
        )
        cursor.execute("DROP TABLE complaints")
        cursor.execute("ALTER TABLE complaints_migrated RENAME TO complaints")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_citizen ON complaints(citizen_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_officer ON complaints(assigned_officer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_ref ON complaints(reference)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_fir ON complaints(fir_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_complaints_verification ON complaints(verification_status)")
        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        print("✓ Migration: complaints table upgraded for citizen filing workflow")
    except Exception as e:
        print(f"Complaints migration note: {e}")
    finally:
        conn.close()


def migrate_notifications_schema() -> None:
    """Allow complaint-only notifications by making fir_id nullable and adding complaint_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='notifications'")
        row = cursor.fetchone()
        if not row or not row[0]:
            return
        existing_cols = {r[1] for r in cursor.execute("PRAGMA table_info(notifications)")}
        if 'complaint_id' in existing_cols and 'metadata_json' in existing_cols:
            return

        conn.commit()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("""
        CREATE TABLE notifications_migrated (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            fir_id TEXT,
            complaint_id TEXT,
            event_id TEXT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata_json TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            severity TEXT NOT NULL DEFAULT 'INFO' CHECK(severity IN ('INFO', 'SUCCESS', 'WARNING', 'ALERT')),
            created_at TEXT NOT NULL
        )
        """)
        cursor.execute("""
            INSERT INTO notifications_migrated (
                id, user_id, fir_id, event_id, type, title, message,
                metadata_json, is_read, severity, created_at
            )
            SELECT id, user_id, fir_id, event_id, type, title, message,
                   NULL, is_read, severity, created_at
            FROM notifications
        """)
        cursor.execute("DROP TABLE notifications")
        cursor.execute("ALTER TABLE notifications_migrated RENAME TO notifications")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, is_read);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_complaint ON notifications(complaint_id);")
        cursor.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        print("✓ Migration: notifications support complaint-only events")
    except Exception as e:
        print(f"Notifications migration note: {e}")
    finally:
        conn.close()


# Run migrations
try:
    migrate_fir_status_constraint()
    migrate_user_role_constraint()
    migrate_complaints_status_constraint()
    migrate_notifications_schema()
except Exception as e:
    print(f"Migration execution error: {e}")

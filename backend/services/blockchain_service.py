"""
Permissioned Blockchain Audit Engine & Smart Contract Service.
Stores cryptographic proofs, state transitions, and audit events in an immutable ledger.
Provides real-time tamper-evident verification.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from backend.services.crypto_service import (
    calculate_sha256,
    canonical_json,
    compute_merkle_root,
    extract_canonical_fir_data,
    sign_block
)
from backend.services.db import get_db_connection

GENESIS_BLOCK_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
VALIDATOR_NODE_ID = "NODE-IN-KA-POLICE-01"


def ensure_genesis_block() -> None:
    """Ensure that the Genesis Block (Block #0) exists in the blockchain table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT block_index FROM blockchain_blocks WHERE block_index = 0")
    row = cursor.fetchone()
    if not row:
        genesis_ts = "2026-08-01T00:00:00Z"
        genesis_merkle = calculate_sha256("GENESIS_MERKLE_ROOT")
        genesis_header = f"0:{GENESIS_BLOCK_HASH}:{genesis_merkle}:{genesis_ts}:{VALIDATOR_NODE_ID}"
        genesis_hash = calculate_sha256(genesis_header)

        cursor.execute("""
            INSERT INTO blockchain_blocks (
                block_index, previous_block_hash, merkle_root, timestamp, block_hash, validator_node, transactions_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (0, GENESIS_BLOCK_HASH, genesis_merkle, genesis_ts, genesis_hash, VALIDATOR_NODE_ID, 0))
        conn.commit()
    conn.close()


def get_latest_block() -> Dict[str, Any]:
    """Retrieve the most recently mined block."""
    ensure_genesis_block()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM blockchain_blocks ORDER BY block_index DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}


def record_fir_created(
    fir_id: str,
    version: int,
    record_hash: str,
    actor_id: str,
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Smart Contract Method: recordFIRCreated(firId, version, recordHash, timestamp)
    Records genesis proof of a newly submitted FIR on the blockchain.
    """
    ensure_genesis_block()
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    actor_hash = calculate_sha256(actor_id)
    event_payload = {
        "firId": fir_id,
        "version": version,
        "recordHash": record_hash,
        "previousHash": None,
        "action": "FIR_CREATED",
        "actorHash": actor_hash,
        "timestamp": timestamp
    }
    event_hash = calculate_sha256(event_payload)
    tx_id = f"tx-{uuid.uuid4().hex[:16]}"
    tx_content = f"{tx_id}:{fir_id}:{version}:{record_hash}:{event_hash}:{timestamp}"
    tx_hash = calculate_sha256(tx_content)

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get latest block to chain next block
    cursor.execute("SELECT block_index, block_hash FROM blockchain_blocks ORDER BY block_index DESC LIMIT 1")
    last_block = cursor.fetchone()
    next_block_index = (last_block["block_index"] + 1) if last_block else 1
    prev_block_hash = last_block["block_hash"] if last_block else GENESIS_BLOCK_HASH

    # Mine block with this transaction
    merkle_root = compute_merkle_root([tx_hash])
    block_header = f"{next_block_index}:{prev_block_hash}:{merkle_root}:{timestamp}:{VALIDATOR_NODE_ID}"
    block_hash = calculate_sha256(block_header)

    cursor.execute("""
        INSERT INTO blockchain_blocks (
            block_index, previous_block_hash, merkle_root, timestamp, block_hash, validator_node, transactions_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (next_block_index, prev_block_hash, merkle_root, timestamp, block_hash, VALIDATOR_NODE_ID, 1))

    cursor.execute("""
        INSERT INTO blockchain_transactions (
            tx_id, block_index, fir_id, version, previous_hash, new_hash, actor_hash,
            event_hash, contract_method, payload_json, timestamp, tx_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        tx_id, next_block_index, fir_id, version, None, record_hash, actor_hash,
        event_hash, "recordFIRCreated", canonical_json(event_payload), timestamp, tx_hash
    ))

    conn.commit()
    conn.close()

    return {
        "tx_id": tx_id,
        "tx_hash": tx_hash,
        "block_index": next_block_index,
        "block_hash": block_hash,
        "event_hash": event_hash,
        "status": "CONFIRMED"
    }


def record_fir_change(
    fir_id: str,
    version: int,
    previous_hash: str,
    new_hash: str,
    actor_id: str,
    event_hash: str,
    reason: str,
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Smart Contract Method: recordFIRChange(firId, version, previousHash, newHash, actorHash, eventHash, timestamp)
    Records an authorized modification to an existing FIR on the blockchain.
    """
    ensure_genesis_block()
    if not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate state transition on-chain: find previous confirmed tx for this FIR
    cursor.execute("""
        SELECT version, new_hash FROM blockchain_transactions
        WHERE fir_id = ?
        ORDER BY version DESC LIMIT 1
    """, (fir_id,))
    last_tx = cursor.fetchone()

    if last_tx:
        if last_tx["new_hash"] != previous_hash:
            conn.close()
            raise ValueError(
                f"Blockchain State Transition Error: previous_hash ({previous_hash[:10]}...) does not match "
                f"last recorded blockchain hash ({last_tx['new_hash'][:10]}...)."
            )

    actor_hash = calculate_sha256(actor_id)
    event_payload = {
        "firId": fir_id,
        "version": version,
        "previousHash": previous_hash,
        "newHash": new_hash,
        "actorHash": actor_hash,
        "eventHash": event_hash,
        "reason": reason,
        "timestamp": timestamp
    }

    tx_id = f"tx-{uuid.uuid4().hex[:16]}"
    tx_content = f"{tx_id}:{fir_id}:{version}:{previous_hash}:{new_hash}:{event_hash}:{timestamp}"
    tx_hash = calculate_sha256(tx_content)

    cursor.execute("SELECT block_index, block_hash FROM blockchain_blocks ORDER BY block_index DESC LIMIT 1")
    last_block = cursor.fetchone()
    next_block_index = (last_block["block_index"] + 1) if last_block else 1
    prev_block_hash = last_block["block_hash"] if last_block else GENESIS_BLOCK_HASH

    merkle_root = compute_merkle_root([tx_hash])
    block_header = f"{next_block_index}:{prev_block_hash}:{merkle_root}:{timestamp}:{VALIDATOR_NODE_ID}"
    block_hash = calculate_sha256(block_header)

    cursor.execute("""
        INSERT INTO blockchain_blocks (
            block_index, previous_block_hash, merkle_root, timestamp, block_hash, validator_node, transactions_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (next_block_index, prev_block_hash, merkle_root, timestamp, block_hash, VALIDATOR_NODE_ID, 1))

    cursor.execute("""
        INSERT INTO blockchain_transactions (
            tx_id, block_index, fir_id, version, previous_hash, new_hash, actor_hash,
            event_hash, contract_method, payload_json, timestamp, tx_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        tx_id, next_block_index, fir_id, version, previous_hash, new_hash, actor_hash,
        event_hash, "recordFIRChange", canonical_json(event_payload), timestamp, tx_hash
    ))

    conn.commit()
    conn.close()

    return {
        "tx_id": tx_id,
        "tx_hash": tx_hash,
        "block_index": next_block_index,
        "block_hash": block_hash,
        "event_hash": event_hash,
        "status": "CONFIRMED"
    }


def verify_fir_integrity(fir_id: str) -> Dict[str, Any]:
    """
    Cryptographic verification algorithm:
    1. Retrieve active FIR row from database.
    2. Canonicalize FIR data and compute SHA-256 hash.
    3. Compare with DB current_hash column.
    4. Retrieve blockchain transactions for this fir_id.
    5. Verify hash chain continuity (tx[i].previous_hash == tx[i-1].new_hash).
    6. Verify current database computed hash matches the latest blockchain record.
    7. Return VERIFIED or TAMPER_DETECTED.
    """
    ensure_genesis_block()
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Fetch active FIR
    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        return {
            "status": "NOT_FOUND",
            "is_valid": False,
            "fir_id": fir_id,
            "message": f"FIR with ID {fir_id} was not found in database."
        }

    fir_dict = dict(fir_row)
    db_current_hash = fir_dict.get("current_hash")
    db_version = fir_dict.get("current_version", 1)

    # 2. Canonicalize active data & compute live hash
    canonical_data = extract_canonical_fir_data(fir_dict)
    calculated_db_hash = calculate_sha256(canonical_data)

    # 3. Retrieve blockchain transactions
    cursor.execute("""
        SELECT * FROM blockchain_transactions
        WHERE fir_id = ?
        ORDER BY version ASC
    """, (fir_id,))
    tx_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    verified_at = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M:%S UTC")

    if not tx_rows:
        return {
            "status": "NO_BLOCKCHAIN_RECORD",
            "is_valid": False,
            "fir_id": fir_id,
            "fir_number": fir_dict.get("fir_number"),
            "version": db_version,
            "database_hash": calculated_db_hash,
            "expected_hash": None,
            "blockchain_tx_id": None,
            "verified_at": verified_at,
            "message": "No cryptographic blockchain audit events recorded for this FIR."
        }

    # 4. Verify chain continuity
    chain_valid = True
    broken_step = None
    for i in range(1, len(tx_rows)):
        prev_tx = tx_rows[i - 1]
        curr_tx = tx_rows[i]
        if curr_tx.get("previous_hash") != prev_tx.get("new_hash"):
            chain_valid = False
            broken_step = (prev_tx.get("version"), curr_tx.get("version"))
            break

    latest_tx = tx_rows[-1]
    expected_blockchain_hash = latest_tx.get("new_hash")
    expected_version = latest_tx.get("version")

    # Mismatch between live DB state and blockchain proof
    if calculated_db_hash != expected_blockchain_hash or db_version != expected_version or not chain_valid:
        return {
            "status": "TAMPER_DETECTED",
            "is_valid": False,
            "fir_id": fir_id,
            "fir_number": fir_dict.get("fir_number"),
            "version": db_version,
            "database_hash": calculated_db_hash,
            "stored_db_hash": db_current_hash,
            "expected_hash": expected_blockchain_hash,
            "blockchain_tx_id": latest_tx.get("tx_id"),
            "blockchain_block": latest_tx.get("block_index"),
            "chain_valid": chain_valid,
            "broken_step": broken_step,
            "verified_at": verified_at,
            "message": (
                f"INTEGRITY ALERT: Current database record for {fir_dict.get('fir_number')} does not match "
                f"the immutable blockchain integrity proof. Expected: {expected_blockchain_hash[:16]}..., "
                f"Calculated: {calculated_db_hash[:16]}..."
            )
        }

    return {
        "status": "VERIFIED",
        "is_valid": True,
        "fir_id": fir_id,
        "fir_number": fir_dict.get("fir_number"),
        "version": db_version,
        "database_hash": calculated_db_hash,
        "blockchain_hash": expected_blockchain_hash,
        "blockchain_tx_id": latest_tx.get("tx_id"),
        "blockchain_block": latest_tx.get("block_index"),
        "chain_length": len(tx_rows),
        "chain_valid": True,
        "verified_at": verified_at,
        "message": f"Cryptographic integrity verified. Database matches on-chain proof (Block #{latest_tx.get('block_index')})."
    }


def get_fir_blockchain_details(fir_id: str) -> Dict[str, Any]:
    """
    Retrieve comprehensive blockchain hashing & cryptographic verification details for an FIR.
    OFFICER USE ONLY - never exposed to citizens.
    """
    ensure_genesis_block()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT f.*, u.name as citizen_name, u.email as citizen_email, u.phone as citizen_phone
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        WHERE f.id = ?
    """, (fir_id,))
    fir_row = cursor.fetchone()
    if not fir_row:
        conn.close()
        return {}

    fir_dict = dict(fir_row)

    # Fetch all blockchain transactions for this FIR
    cursor.execute("""
        SELECT t.*, b.previous_block_hash, b.block_hash, b.timestamp as block_timestamp, b.validator_node
        FROM blockchain_transactions t
        LEFT JOIN blockchain_blocks b ON t.block_index = b.block_index
        WHERE t.fir_id = ?
        ORDER BY t.version ASC
    """, (fir_id,))
    tx_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Calculate live canonical hash
    canonical_data = extract_canonical_fir_data(fir_dict)
    live_sha256_hash = calculate_sha256(canonical_data)

    # Run integrity check
    integrity_result = verify_fir_integrity(fir_id)

    latest_tx = tx_rows[-1] if tx_rows else {}

    return {
        "fir_id": fir_id,
        "fir_number": fir_dict.get("fir_number"),
        "citizen_name": fir_dict.get("citizen_name", "Unknown Citizen"),
        "citizen_email": fir_dict.get("citizen_email", ""),
        "citizen_phone": fir_dict.get("citizen_phone", ""),
        "record_version": fir_dict.get("current_version", 1),
        "status": fir_dict.get("status"),
        "incident_type": fir_dict.get("incident_type"),
        "generated_sha256_hash": live_sha256_hash,
        "stored_db_hash": fir_dict.get("current_hash"),
        "blockchain_block_id": latest_tx.get("block_index"),
        "transaction_id": latest_tx.get("tx_id"),
        "previous_block_hash": latest_tx.get("previous_block_hash") or GENESIS_BLOCK_HASH,
        "current_block_hash": latest_tx.get("block_hash"),
        "previous_hash": latest_tx.get("previous_hash"),
        "current_hash": latest_tx.get("new_hash"),
        "hash_generated_at": latest_tx.get("timestamp") or fir_dict.get("created_at"),
        "last_verification_at": integrity_result.get("verified_at"),
        "integrity_status": integrity_result.get("status"),
        "is_valid": integrity_result.get("is_valid", False),
        "integrity_message": integrity_result.get("message"),
        "chain_length": len(tx_rows),
        "transactions": tx_rows,
    }


def simulate_db_tamper(fir_id: str, field_name: str, malicious_value: str) -> Dict[str, Any]:
    """
    Simulation tool for demonstrations and testing:
    Directly mutates a field in the SQLite database without going through
    the authorized versioning or blockchain audit flow.
    This creates an immediate tamper condition that the verification engine will catch.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"success": False, "message": f"FIR {fir_id} not found."}

    old_val = row[field_name] if field_name in row.keys() else "UNKNOWN"

    cursor.execute(f"UPDATE firs SET {field_name} = ? WHERE id = ?", (malicious_value, fir_id))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "fir_id": fir_id,
        "field": field_name,
        "old_value": old_val,
        "tampered_value": malicious_value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": f"Database field '{field_name}' maliciously altered to '{malicious_value}'. Blockchain proof remains unchanged."
    }


def restore_tampered_fir(fir_id: str) -> Dict[str, Any]:
    """
    Restore an FIR's database record to the snapshot matching its latest authorized version.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT snapshot_json, version_number, current_hash FROM fir_versions
        WHERE fir_id = ?
        ORDER BY version_number DESC LIMIT 1
    """, (fir_id,))
    v_row = cursor.fetchone()
    if not v_row:
        conn.close()
        return {"success": False, "message": "No valid snapshot found to restore."}

    snapshot = json.loads(v_row["snapshot_json"])

    cursor.execute("""
        UPDATE firs SET
            incident_type = ?,
            incident_date = ?,
            incident_time = ?,
            incident_location = ?,
            description = ?,
            accused_details = ?,
            witness_details = ?,
            status = ?,
            current_version = ?,
            current_hash = ?
        WHERE id = ?
    """, (
        snapshot.get("incident_type"),
        snapshot.get("incident_date"),
        snapshot.get("incident_time"),
        snapshot.get("incident_location"),
        snapshot.get("description"),
        snapshot.get("accused_details"),
        snapshot.get("witness_details"),
        snapshot.get("status"),
        v_row["version_number"],
        v_row["current_hash"],
        fir_id
    ))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "fir_id": fir_id,
        "restored_version": v_row["version_number"],
        "message": "FIR database record successfully restored from immutable snapshot."
    }


def get_blockchain_ledger(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve list of mined blocks and transactions."""
    ensure_genesis_block()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, t.tx_id, t.fir_id, t.version, t.contract_method, t.previous_hash, t.new_hash, t.tx_hash
        FROM blockchain_blocks b
        LEFT JOIN blockchain_transactions t ON b.block_index = t.block_index
        ORDER BY b.block_index DESC
        LIMIT ?
    """, (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

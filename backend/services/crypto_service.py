"""
Cryptographic Utilities for Blockchain-Based Online FIR Platform.
Implements:
1. Canonical JSON serialization (deterministic sorting, normalized spacing, utf-8)
2. SHA-256 hashing
3. Merkle tree calculation
4. Secure password hashing with PBKDF2-HMAC-SHA256 (600,000 rounds + 32-byte salt)
5. Digital signature simulation using HMAC-SHA256 with validator private key
"""

import hashlib
import hmac
import json
import os
import secrets
from typing import Any, Dict, List, Optional, Tuple, Union

# Validator node secret used to sign blockchain blocks and transaction proofs.
# It is never stored in the source tree; see .env.example.
VALIDATOR_PRIVATE_KEY_ENV = "VALIDATOR_PRIVATE_KEY"


def get_validator_private_key() -> str:
    """Return the validator signing key, which must come from the environment."""
    key = (os.environ.get(VALIDATOR_PRIVATE_KEY_ENV) or '').strip()
    if not key:
        raise RuntimeError(
            f'{VALIDATOR_PRIVATE_KEY_ENV} is not set, so ledger blocks cannot be signed. '
            'Generate a key and keep it out of version control:\n'
            '  python -c "import secrets; print(\'VALIDATOR_PRIVATE_KEY=\' + secrets.token_hex(32))" >> .env\n'
            'The .env file is gitignored; .env.example documents the variable for fresh installs.'
        )
    return key


def canonical_json(data: Any) -> str:
    """
    Produce a deterministic, canonical JSON string for hashing.
    - Keys are sorted lexicographically
    - No whitespace between delimiters
    - Handles nested dicts, lists, and primitives
    - Datetimes or strings must already be formatted or ISO strings
    """
    if isinstance(data, dict):
        cleaned = {}
        for k in sorted(data.keys()):
            # Filter out non-canonical runtime metadata if any
            if k not in ('_id', 'runtime_id'):
                cleaned[k] = data[k]
        return json.dumps(cleaned, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    elif isinstance(data, (list, tuple)):
        return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    elif isinstance(data, str):
        return data
    else:
        return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def calculate_sha256(data: Union[str, bytes, dict, list]) -> str:
    """Calculate SHA-256 hash string (lowercase hex) for given data."""
    if isinstance(data, (dict, list)):
        payload_str = canonical_json(data)
        return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()
    elif isinstance(data, str):
        return hashlib.sha256(data.encode('utf-8')).hexdigest()
    elif isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    else:
        return hashlib.sha256(str(data).encode('utf-8')).hexdigest()


def compute_merkle_root(tx_hashes: List[str]) -> str:
    """Compute Merkle Tree root for a list of transaction hashes."""
    if not tx_hashes:
        return calculate_sha256("EMPTY_BLOCK")
    
    current_level = [h for h in tx_hashes]
    while len(current_level) > 1:
        next_level = []
        for i in range(0, len(current_level), 2):
            left = current_level[i]
            right = current_level[i + 1] if i + 1 < len(current_level) else left
            combined_hash = calculate_sha256(left + right)
            next_level.append(combined_hash)
        current_level = next_level
    
    return current_level[0]


def sign_block(block_header_str: str) -> str:
    """Sign block header using validator private key and HMAC-SHA256."""
    return hmac.new(
        get_validator_private_key().encode('utf-8'),
        block_header_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hash a password securely using PBKDF2-HMAC-SHA256.
    Returns: (password_hash_hex, salt_hex)
    """
    if not salt:
        salt = secrets.token_hex(32)
    
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        600_000,
        dklen=32
    )
    return key.hex(), salt


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify provided password against stored hash and salt."""
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        600_000,
        dklen=32
    )
    return hmac.compare_digest(key.hex(), stored_hash)


def extract_canonical_fir_data(fir_row_or_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract the core fields of an FIR that form the canonical integrity record.
    Excludes local database primary keys or auto-incrementing fields.
    """
    return {
        "firNumber": str(fir_row_or_dict.get("fir_number") or fir_row_or_dict.get("firNumber") or ""),
        "referenceNumber": str(fir_row_or_dict.get("reference_number") or fir_row_or_dict.get("referenceNumber") or ""),
        "citizenId": str(fir_row_or_dict.get("citizen_id") or fir_row_or_dict.get("citizenId") or ""),
        "policeStation": str(fir_row_or_dict.get("police_station") or fir_row_or_dict.get("policeStation") or ""),
        "incidentType": str(fir_row_or_dict.get("incident_type") or fir_row_or_dict.get("incidentType") or ""),
        "incidentDate": str(fir_row_or_dict.get("incident_date") or fir_row_or_dict.get("incidentDate") or ""),
        "incidentTime": str(fir_row_or_dict.get("incident_time") or fir_row_or_dict.get("incidentTime") or ""),
        "incidentLocation": str(fir_row_or_dict.get("incident_location") or fir_row_or_dict.get("incidentLocation") or ""),
        "description": str(fir_row_or_dict.get("description") or ""),
        "accusedDetails": str(fir_row_or_dict.get("accused_details") or fir_row_or_dict.get("accusedDetails") or ""),
        "witnessDetails": str(fir_row_or_dict.get("witness_details") or fir_row_or_dict.get("witnessDetails") or ""),
        "status": str(fir_row_or_dict.get("status") or ""),
        "versionNumber": int(fir_row_or_dict.get("current_version") or fir_row_or_dict.get("version_number") or 1)
    }

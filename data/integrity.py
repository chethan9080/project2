"""
FIR Integrity and Hash Management
Handles cryptographic hashing and integrity verification for FIR versions
"""

import hashlib
import json
from typing import Dict, Any, Optional
from backend.services.db import get_db_connection


def generate_fir_hash(fir_data: Dict[str, Any]) -> str:
    """
    Generate SHA-256 hash for FIR data using canonical JSON representation.
    
    Args:
        fir_data: Dictionary containing FIR fields
    
    Returns:
        SHA-256 hash as hex string
    """
    from backend.services.crypto_service import calculate_sha256, extract_canonical_fir_data
    canonical_data = extract_canonical_fir_data(fir_data)
    return calculate_sha256(canonical_data)


def verify_fir_hash(fir_data: Dict[str, Any], expected_hash: str) -> bool:
    """
    Verify if FIR data matches the expected hash.
    
    Args:
        fir_data: Dictionary containing FIR fields
        expected_hash: Expected SHA-256 hash
    
    Returns:
        True if hash matches, False otherwise
    """
    computed_hash = generate_fir_hash(fir_data)
    return computed_hash == expected_hash


def get_fir_hashes(fir_id: str) -> list:
    """
    Get all hash records for a specific FIR across all versions.
    
    Args:
        fir_id: FIR identifier
    
    Returns:
        List of hash records with version information
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            v.id,
            v.fir_id,
            v.version_number,
            v.previous_hash,
            v.current_hash,
            v.created_by,
            u.name as created_by_name,
            u.role as created_by_role,
            u.badge_number,
            v.created_at,
            v.change_reason
        FROM fir_versions v
        JOIN users u ON v.created_by = u.id
        WHERE v.fir_id = ?
        ORDER BY v.version_number ASC
    """, (fir_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    hashes = []
    for row in rows:
        hashes.append({
            'version_id': row[0],
            'fir_id': row[1],
            'version_number': row[2],
            'previous_hash': row[3],
            'current_hash': row[4],
            'created_by_id': row[5],
            'created_by_name': row[6],
            'created_by_role': row[7],
            'badge_number': row[8],
            'created_at': row[9],
            'change_reason': row[10]
        })
    
    return hashes


def get_hash_chain_status(fir_id: str) -> Dict[str, Any]:
    """
    Verify the complete hash chain for an FIR and return integrity status.
    
    Args:
        fir_id: FIR identifier
    
    Returns:
        Dictionary with chain status and any integrity issues
    """
    hashes = get_fir_hashes(fir_id)
    
    if not hashes:
        return {
            'status': 'NO_VERSIONS',
            'message': 'No version history found',
            'chain_valid': False,
            'issues': []
        }
    
    issues = []
    
    # Verify hash chain continuity
    for i in range(1, len(hashes)):
        previous_version = hashes[i-1]
        current_version = hashes[i]
        
        # Check if previous_hash matches previous version's current_hash
        if current_version['previous_hash'] != previous_version['current_hash']:
            issues.append({
                'version': current_version['version_number'],
                'type': 'CHAIN_BREAK',
                'message': f"Hash chain broken between V{previous_version['version_number']} and V{current_version['version_number']}",
                'expected': previous_version['current_hash'],
                'actual': current_version['previous_hash']
            })
    
    # Verify current FIR data matches latest hash
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM firs WHERE id = ?", (fir_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        columns = [description[0] for description in cursor.description]
        fir_data = dict(zip(columns, row))
        
        latest_hash = hashes[-1]['current_hash']
        computed_hash = generate_fir_hash(fir_data)
        
        if computed_hash != latest_hash:
            issues.append({
                'version': hashes[-1]['version_number'],
                'type': 'DATA_MISMATCH',
                'message': 'Current FIR data does not match stored hash',
                'expected': latest_hash,
                'actual': computed_hash
            })
    
    chain_valid = len(issues) == 0
    
    return {
        'status': 'VERIFIED' if chain_valid else 'INTEGRITY_ISSUE',
        'message': 'Hash chain verified' if chain_valid else f'{len(issues)} integrity issue(s) detected',
        'chain_valid': chain_valid,
        'total_versions': len(hashes),
        'issues': issues,
        'hashes': hashes
    }


def compare_version_hashes(fir_id: str, version1: int, version2: int) -> Dict[str, Any]:
    """
    Compare hashes between two specific versions of an FIR.
    
    Args:
        fir_id: FIR identifier
        version1: First version number
        version2: Second version number
    
    Returns:
        Comparison result with hash details
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            version_number,
            current_hash,
            previous_hash,
            created_by,
            created_at,
            change_reason
        FROM fir_versions
        WHERE fir_id = ? AND version_number IN (?, ?)
        ORDER BY version_number ASC
    """, (fir_id, version1, version2))
    
    rows = cursor.fetchall()
    conn.close()
    
    if len(rows) < 2:
        return {
            'error': 'One or both versions not found',
            'found_versions': len(rows)
        }
    
    v1_data = {
        'version_number': rows[0][0],
        'hash': rows[0][1],
        'previous_hash': rows[0][2],
        'created_by': rows[0][3],
        'created_at': rows[0][4],
        'change_reason': rows[0][5]
    }
    
    v2_data = {
        'version_number': rows[1][0],
        'hash': rows[1][1],
        'previous_hash': rows[1][2],
        'created_by': rows[1][3],
        'created_at': rows[1][4],
        'change_reason': rows[1][5]
    }
    
    hashes_match = v1_data['hash'] == v2_data['hash']
    
    return {
        'fir_id': fir_id,
        'version1': v1_data,
        'version2': v2_data,
        'hashes_match': hashes_match,
        'comparison_result': 'IDENTICAL' if hashes_match else 'MODIFIED',
        'message': 'FIR content is identical' if hashes_match else 'FIR content was modified between these versions'
    }

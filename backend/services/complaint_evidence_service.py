"""
Private evidence storage for citizen complaints.

Files are staged while the citizen completes the filing wizard, then moved into
``data/secure_uploads/complaints/<complaint_id>/`` when the complaint is saved.
Nothing is served from the public web root: pages read files server-side and
stream them only after enforcing complaint ownership.
"""

import hashlib
import os
import re
import shutil
import uuid
from typing import Any, Dict, List, Optional

SECURE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads', 'complaints'
))
STAGING_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads', 'complaint_staging'
))

ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.mp4', '.txt', '.doc', '.docx'}
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_FILES = 5
# The filing wizard allows MAX_FILES; the citizen may add more while the case runs.
MAX_FILES_PER_COMPLAINT = 10

MEDIA_TYPES = {
    '.pdf': 'application/pdf',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.mp4': 'video/mp4',
    '.txt': 'text/plain',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}


def _safe_name(filename: Optional[str]) -> str:
    """Strip paths and unsafe characters while keeping a readable filename."""
    base = os.path.basename((filename or '').replace('\\', '/'))
    base = re.sub(r'[^A-Za-z0-9._ -]', '_', base).strip() or 'evidence'
    return base[:120]


def _extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def create_staging_token() -> str:
    return uuid.uuid4().hex


def _staging_dir(token: str) -> str:
    if not token or not re.fullmatch(r'[a-f0-9]{32}', token or ''):
        raise ValueError('Invalid upload session.')
    return os.path.join(STAGING_ROOT, token)


def _complaint_dir(complaint_id: str) -> str:
    if not complaint_id or not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', complaint_id or ''):
        raise ValueError('Invalid complaint identifier.')
    return os.path.join(SECURE_ROOT, complaint_id)


def validate_upload(filename: str, size: int) -> None:
    safe = _safe_name(filename)
    extension = _extension(safe)
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            'Unsupported file type. Allowed formats: ' + ', '.join(sorted(ALLOWED_EXTENSIONS))
        )
    if size <= 0:
        raise ValueError('The uploaded file is empty.')
    if size > MAX_FILE_BYTES:
        raise ValueError('Each evidence file must be 25 MB or smaller.')


def save_staged_file(token: str, filename: str, content: bytes,
                     content_type: str = '') -> Dict[str, Any]:
    """Persist one uploaded file in the staging area and return its metadata."""
    validate_upload(filename, len(content))
    folder = _staging_dir(token)
    os.makedirs(folder, exist_ok=True)
    if len([n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]) >= MAX_FILES:
        raise ValueError(f'You can attach up to {MAX_FILES} evidence files.')

    safe = _safe_name(filename)
    stored_name = f"{uuid.uuid4().hex[:8]}_{safe}"
    with open(os.path.join(folder, stored_name), 'wb') as handle:
        handle.write(content)

    return {
        'name': safe,
        'stored_name': stored_name,
        'size': len(content),
        'content_type': content_type or MEDIA_TYPES.get(_extension(safe), 'application/octet-stream'),
    }


def list_staged_files(token: str) -> List[Dict[str, Any]]:
    """Return staged files for this upload session, using on-disk metadata."""
    folder = _staging_dir(token)
    if not os.path.isdir(folder):
        return []
    result = []
    for stored_name in sorted(os.listdir(folder)):
        path = os.path.join(folder, stored_name)
        if not os.path.isfile(path):
            continue
        display_name = stored_name.split('_', 1)[1] if '_' in stored_name else stored_name
        result.append({
            'name': display_name,
            'stored_name': stored_name,
            'size': os.path.getsize(path),
            'content_type': MEDIA_TYPES.get(_extension(stored_name), 'application/octet-stream'),
        })
    return result


def staged_file_path(token: str, stored_name: str) -> Optional[str]:
    folder = _staging_dir(token)
    path = os.path.abspath(os.path.join(folder, os.path.basename(stored_name)))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return None
    return path


def remove_staged_file(token: str, stored_name: str) -> None:
    path = staged_file_path(token, stored_name)
    if path:
        os.remove(path)


def move_staged_files_to_complaint(token: str, complaint_id: str) -> List[Dict[str, Any]]:
    """Move every staged file into the complaint's private directory."""
    staged = list_staged_files(token)
    if not staged:
        return []
    source_dir = _staging_dir(token)
    target_dir = _complaint_dir(complaint_id)
    os.makedirs(target_dir, exist_ok=True)

    moved = []
    for item in staged:
        source = os.path.join(source_dir, item['stored_name'])
        target = os.path.join(target_dir, item['stored_name'])
        shutil.move(source, target)
        moved.append(item)

    try:
        os.rmdir(source_dir)
    except OSError:
        pass
    return moved


def save_complaint_file(complaint_id: str, filename: str, content: bytes,
                        content_type: str = '') -> Dict[str, Any]:
    """Store one file directly in the complaint's private folder (no staging session)."""
    validate_upload(filename, len(content))
    folder = _complaint_dir(complaint_id)
    os.makedirs(folder, exist_ok=True)
    existing = [n for n in os.listdir(folder) if os.path.isfile(os.path.join(folder, n))]
    if len(existing) >= MAX_FILES_PER_COMPLAINT:
        raise ValueError(f'A case can hold at most {MAX_FILES_PER_COMPLAINT} evidence files.')

    safe = _safe_name(filename)
    stored_name = f"{uuid.uuid4().hex[:8]}_{safe}"
    with open(os.path.join(folder, stored_name), 'wb') as handle:
        handle.write(content)

    return {
        'name': safe,
        'stored_name': stored_name,
        'size': len(content),
        'content_type': content_type or MEDIA_TYPES.get(_extension(safe), 'application/octet-stream'),
        'sha256': hashlib.sha256(content).hexdigest(),
    }


def evidence_file_path(complaint_id: str, stored_name: str) -> Optional[str]:
    """Resolve a stored evidence file, refusing any path outside the complaint folder."""
    folder = _complaint_dir(complaint_id)
    path = os.path.abspath(os.path.join(folder, os.path.basename(stored_name)))
    if not path.startswith(folder + os.sep) or not os.path.isfile(path):
        return None
    return path


def evidence_bytes(complaint_id: str, stored_name: str) -> Optional[bytes]:
    path = evidence_file_path(complaint_id, stored_name)
    if not path:
        return None
    with open(path, 'rb') as handle:
        return handle.read()

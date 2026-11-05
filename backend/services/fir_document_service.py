"""
Official FIR document generation and private delivery.

Generates one printable First Information Report PDF from the *persisted* FIR
record using reportlab. The document is written to private storage, hashed,
attached to the FIR in ``fir_documents`` with an append-only version history,
and made available only to the citizen, the assigned investigating officer, and
authorised verification/administrative staff.

Repeated generation requests return the existing current document, so a double
click can never produce two different PDFs for the same FIR.
"""

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from backend.services.db import get_db_connection
from backend.services.realtime_events import publish

SECURE_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'data', 'secure_uploads', 'fir_documents'
))
DOCUMENT_TYPE = 'FIR_PDF'
GENERATOR_ROLES = ('VERIFICATION_OFFICER', 'ADMIN')

DRAFT_NOTICE = (
    'DRAFT FOR AUTHORISED APPROVAL — System-generated from the registered FIR record. '
    'Case-specific legal sections, officer signature and station seal must be completed '
    'and approved by the authorised Station House Officer.'
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_filename(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]', '_', value or 'FIR')


def _doc_dir(fir_id: str) -> str:
    if not fir_id or not re.fullmatch(r'[A-Za-z0-9_-]{4,64}', fir_id or ''):
        raise ValueError('Invalid FIR identifier.')
    return os.path.join(SECURE_ROOT, fir_id)


def resolve_document_file(relative_path: Optional[str]) -> Optional[str]:
    if not relative_path:
        return None
    absolute = os.path.abspath(os.path.join(SECURE_ROOT, relative_path))
    if not absolute.startswith(SECURE_ROOT + os.sep):
        raise ValueError('Invalid document path.')
    return absolute if os.path.isfile(absolute) else None


def _load_fir(fir_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT f.*,
               u.name AS citizen_name, u.phone AS citizen_phone, u.email AS citizen_email,
               u.address AS citizen_address, u.gov_id_masked,
               o.name AS officer_name, o.rank AS officer_rank, o.badge_number AS officer_badge,
               o.station AS officer_station, o.phone AS officer_phone,
               c.reference AS complaint_reference, c.district AS complaint_district,
               c.state AS complaint_state, c.landmark, c.area,
               c.verified_by_name, c.verified_at, c.verification_remarks
        FROM firs f
        LEFT JOIN users u ON f.citizen_id = u.id
        LEFT JOIN users o ON f.assigned_officer_id = o.id
        LEFT JOIN complaints c ON f.complaint_id = c.id
        WHERE f.id = ?
    """, (fir_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def can_view_fir_document(user: Optional[Dict[str, Any]], fir: Optional[Dict[str, Any]]) -> bool:
    if not user or not fir:
        return False
    role = user.get('role')
    if role in ('VERIFICATION_OFFICER', 'ADMIN'):
        return True
    if role == 'CITIZEN':
        return fir.get('citizen_id') == user.get('id')
    if role == 'OFFICER':
        return fir.get('assigned_officer_id') == user.get('id')
    return False


def get_current_document(fir_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM fir_documents
        WHERE fir_id = ? AND document_type = ? AND is_current = 1
        ORDER BY version DESC LIMIT 1
    """, (fir_id, DOCUMENT_TYPE))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_documents(fir_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM fir_documents
        WHERE fir_id = ? AND document_type = ?
        ORDER BY version DESC
    """, (fir_id, DOCUMENT_TYPE))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def read_document_bytes(document: Dict[str, Any]) -> Optional[bytes]:
    path = resolve_document_file(document.get('file_path'))
    if not path:
        return None
    with open(path, 'rb') as handle:
        return handle.read()


def _format_ist(value: Optional[str]) -> str:
    if not value:
        return 'Not recorded'
    text = str(value).replace('T', ' ')
    return text[:19] + ' UTC' if len(text) >= 19 else text


def _display(value: Any, fallback: str = 'Not recorded') -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _evidence_summary(raw: Optional[str]) -> str:
    if not raw:
        return 'No property or evidence attached to the complaint record.'
    try:
        items = json.loads(raw)
    except (TypeError, ValueError):
        return 'No structured property or evidence metadata recorded.'
    if not isinstance(items, list) or not items:
        return 'No property or evidence attached to the complaint record.'
    lines = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        name = _display(item.get('name'), 'Evidence file')
        size = item.get('size')
        size_text = ''
        if isinstance(size, int):
            size_text = f" ({size / 1024:.0f} KB)" if size >= 1024 else f" ({size} B)"
        lines.append(f"{index}. {name}{size_text} — stored in secure police evidence storage")
    return '<br/>'.join(escape(line) for line in lines) or 'No property or evidence recorded.'


def _styles():
    sample = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'FIRTitle', parent=sample['Title'], fontName='Helvetica-Bold',
            fontSize=18, leading=22, alignment=TA_CENTER, spaceAfter=2,
            textColor=colors.HexColor('#0F2B1F'),
        ),
        'subtitle': ParagraphStyle(
            'FIRSubtitle', parent=sample['Normal'], fontName='Helvetica',
            fontSize=9, leading=12, alignment=TA_CENTER,
            textColor=colors.HexColor('#334155'), spaceAfter=2,
        ),
        'draft': ParagraphStyle(
            'FIRDraft', parent=sample['Normal'], fontName='Helvetica-Bold',
            fontSize=7.5, leading=10, alignment=TA_CENTER,
            textColor=colors.HexColor('#991B1B'),
        ),
        'section': ParagraphStyle(
            'FIRSection', parent=sample['Normal'], fontName='Helvetica-Bold',
            fontSize=9.5, leading=12, spaceBefore=7, spaceAfter=3,
            textColor=colors.HexColor('#0F3D2E'),
        ),
        'body': ParagraphStyle(
            'FIRBody', parent=sample['Normal'], fontName='Helvetica',
            fontSize=8.6, leading=11.6, alignment=TA_LEFT,
        ),
        'label': ParagraphStyle(
            'FIRLabel', parent=sample['Normal'], fontName='Helvetica-Bold',
            fontSize=8, leading=10.5, textColor=colors.HexColor('#475569'),
        ),
        'value': ParagraphStyle(
            'FIRValue', parent=sample['Normal'], fontName='Helvetica',
            fontSize=8.6, leading=11.5,
        ),
        'small': ParagraphStyle(
            'FIRSmall', parent=sample['Normal'], fontName='Helvetica-Oblique',
            fontSize=7, leading=9, textColor=colors.HexColor('#64748B'),
        ),
    }


def _field_table(rows: List[Tuple[str, str]], styles: Dict[str, ParagraphStyle]) -> Table:
    data = []
    for label, value in rows:
        data.append([
            Paragraph(escape(label), styles['label']),
            Paragraph(escape(value), styles['value']),
        ])
    table = Table(data, colWidths=[42 * mm, 128 * mm])
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#CBD5E1')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F1F5F9')),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    return table


def _build_pdf(fir: Dict[str, Any], actor_user: Dict[str, Any]) -> bytes:
    from io import BytesIO

    styles = _styles()
    buffer = BytesIO()
    fir_number = _display(fir.get('fir_number'), 'UNREGISTERED')
    station = _display(fir.get('police_station'), 'Police station not recorded')
    district = _display(fir.get('complaint_district'), 'District not recorded')

    def draw_header(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor('#0F3D2E'))
        canvas.setLineWidth(1.2)
        canvas.line(18 * mm, A4[1] - 16 * mm, A4[0] - 18 * mm, A4[1] - 16 * mm)
        canvas.setFont('Helvetica-Bold', 7.5)
        canvas.setFillColor(colors.HexColor('#334155'))
        canvas.drawString(18 * mm, A4[1] - 14 * mm, 'STATE POLICE DEPARTMENT · FIR RECORD (SYSTEM-GENERATED)')
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 14 * mm, f"{fir_number} · {station}")
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#64748B'))
        canvas.drawString(18 * mm, 12 * mm, DRAFT_NOTICE[:150])
        canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=22 * mm, bottomMargin=18 * mm,
        title=f"FIR {fir_number}", author='State Police Department',
        subject='First Information Report',
    )

    story: List[Any] = []
    story.append(Paragraph('FIRST INFORMATION REPORT', styles['title']))
    story.append(Paragraph(
        'Statutory framework: Section 173, Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023 '
        '— registration of First Information Report',
        styles['subtitle'],
    ))
    story.append(Spacer(1, 4))
    draft_table = Table([[Paragraph(DRAFT_NOTICE, styles['draft'])]], colWidths=[170 * mm])
    draft_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.7, colors.HexColor('#DC2626')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#FEF2F2')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(draft_table)
    story.append(Spacer(1, 8))

    registration = [
        ('FIR Number', fir_number),
        ('Complaint Reference', _display(fir.get('complaint_reference'))),
        ('Police Station', station),
        ('District', district),
        ('State / UT', _display(fir.get('complaint_state'))),
        ('Date & Time of Registration', _format_ist(fir.get('created_at'))),
        ('Current FIR Status', _display(fir.get('status'))),
    ]
    story.append(_field_table(registration, styles))

    story.append(Paragraph('1. Complainant / Informant', styles['section']))
    story.append(_field_table([
        ('Full Name', _display(fir.get('citizen_name'), 'Name not recorded')),
        ('Mobile Number', _display(fir.get('citizen_phone'))),
        ('Email Address', _display(fir.get('citizen_email'))),
        ('Government ID (masked)', _display(fir.get('gov_id_masked'))),
        ('Residential Address', _display(fir.get('citizen_address'))),
    ], styles))

    story.append(Paragraph('2. Incident Details', styles['section']))
    story.append(_field_table([
        ('Offence Category', _display(fir.get('incident_type'))),
        ('Date of Incident', _display(fir.get('incident_date'))),
        ('Time of Incident', _display(fir.get('incident_time'))),
        ('Place of Occurrence', _display(fir.get('incident_location'))),
        ('Area / Landmark', _display(fir.get('area') or fir.get('landmark'))),
        ('Police Station / Jurisdiction', station),
    ], styles))

    story.append(Paragraph('3. Complaint / Incident Information', styles['section']))
    description = escape(_display(fir.get('description'), 'No description recorded.'))
    story.append(Paragraph(description.replace('\n', '<br/>'), styles['body']))

    story.append(Paragraph('4. Details of Accused / Suspects', styles['section']))
    story.append(Paragraph(
        escape(_display(fir.get('accused_details'), 'No accused details recorded at registration.')),
        styles['body'],
    ))

    story.append(Paragraph('5. Details of Witnesses', styles['section']))
    story.append(Paragraph(
        escape(_display(fir.get('witness_details'), 'No witness details recorded at registration.')),
        styles['body'],
    ))

    story.append(Paragraph('6. Property / Evidence Details', styles['section']))
    story.append(Paragraph(_evidence_summary(fir.get('evidence_files')), styles['body']))

    story.append(Paragraph('7. Applicable Legal Sections', styles['section']))
    story.append(_field_table([
        ('Case-specific sections', 'Not recorded. To be entered only by an authorised officer after legal scrutiny.'),
        ('Verification remarks', _display(fir.get('verification_remarks'), 'No verification remarks recorded.')),
        ('Verified by', _display(fir.get('verified_by_name'), 'Verification officer details not recorded.')),
        ('Verified at', _format_ist(fir.get('verified_at'))),
    ], styles))

    officer_name = fir.get('officer_name')
    story.append(Paragraph('8. Investigating Officer', styles['section']))
    story.append(_field_table([
        ('Officer Name', _display(officer_name, 'No investigating officer assigned at registration.')),
        ('Rank', _display(fir.get('officer_rank'))),
        ('Badge Number', _display(fir.get('officer_badge'))),
        ('Police Station', _display(fir.get('officer_station') or fir.get('police_station'))),
        ('Contact Number', _display(fir.get('officer_phone'))),
    ], styles))

    story.append(Paragraph('9. Authorised Officer & Signature', styles['section']))
    story.append(_field_table([
        ('Document generated by', f"{_display(actor_user.get('name'), 'Verification Officer')} "
                                  f"({_display(actor_user.get('role'), 'VERIFICATION_OFFICER')})"),
        ('Generated at', _format_ist(_now())),
        ('Authorising Officer Name', '________________________________________'),
        ('Designation', '________________________________________'),
        ('Signature', '________________________________________'),
        ('Station Seal', '________________________________________'),
        ('Date', '________________________________________'),
    ], styles))

    story.append(Spacer(1, 10))
    story.append(Paragraph(
        'This document was generated from the FIR and linked complaint records stored in the '
        'police database. Fields shown as "Not recorded" were not entered by an authorised '
        'officer and must not be inferred. The document is not a substitute for the signed '
        'station copy.',
        styles['small'],
    ))

    doc.build(story, onFirstPage=draw_header, onLaterPages=draw_header)
    return buffer.getvalue()


def generate_fir_pdf(fir_id: str, actor_user: Dict[str, Any], force: bool = False) -> Dict[str, Any]:
    """Generate and register the FIR PDF; reuse the current version unless forced."""
    if not actor_user or actor_user.get('role') not in GENERATOR_ROLES:
        raise PermissionError('Only Verification Officers or Administrators may generate FIR documents.')

    fir = _load_fir(fir_id)
    if not fir:
        raise ValueError('FIR not found.')
    if not fir.get('fir_number'):
        raise ValueError('The FIR has no registered number yet.')

    existing = get_current_document(fir_id)
    if not force and existing and resolve_document_file(existing.get('file_path')):
        return {
            'document': existing,
            'created': False,
            'file_path': resolve_document_file(existing.get('file_path')),
        }

    pdf_bytes = _build_pdf(fir, actor_user)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    now = _now()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COALESCE(MAX(version), 0) AS max_version FROM fir_documents "
        "WHERE fir_id = ? AND document_type = ?",
        (fir_id, DOCUMENT_TYPE),
    )
    version = int(cursor.fetchone()['max_version'] or 0) + 1

    folder = _doc_dir(fir_id)
    os.makedirs(folder, exist_ok=True)
    filename = f"{_safe_filename(fir['fir_number'])}-v{version}.pdf"
    absolute_path = os.path.join(folder, filename)
    with open(absolute_path, 'wb') as handle:
        handle.write(pdf_bytes)
    relative_path = f"{fir_id}/{filename}"

    doc_id = f"fdoc-{uuid.uuid4().hex[:12]}"
    cursor.execute(
        "UPDATE fir_documents SET is_current = 0 WHERE fir_id = ? AND document_type = ?",
        (fir_id, DOCUMENT_TYPE),
    )
    cursor.execute("""
        INSERT INTO fir_documents (
            id, fir_id, document_type, version, file_name, file_path, sha256,
            generated_by, generated_by_name, generated_at, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        doc_id, fir_id, DOCUMENT_TYPE, version, filename, relative_path, digest,
        actor_user.get('id'), actor_user.get('name'), now,
    ))
    conn.commit()
    cursor.execute("SELECT * FROM fir_documents WHERE id = ?", (doc_id,))
    document = dict(cursor.fetchone())
    conn.close()

    try:
        from backend.services.fir_service import log_officer_activity
        log_officer_activity(
            user=actor_user,
            action_type='FIR_DOCUMENT_GENERATED',
            fir_id=fir_id,
            fir_number=fir['fir_number'],
            details=f'Generated official FIR PDF v{version} ({digest[:16]}…) for download.',
        )
    except Exception as exc:
        print(f"FIR document audit log error: {exc}")

    _notify_document_available(fir, version)
    publish({
        'type': 'FIR_DOCUMENT_GENERATED',
        'fir_id': fir_id,
        'fir_number': fir['fir_number'],
        'citizen_id': fir.get('citizen_id'),
        'officer_id': fir.get('assigned_officer_id'),
        'version': version,
    })
    return {'document': document, 'created': True, 'file_path': absolute_path}


def _notify_document_available(fir: Dict[str, Any], version: int) -> None:
    from backend.services.notification_service import create_notification

    fir_number = fir.get('fir_number')
    create_notification(
        user_id=fir['citizen_id'],
        fir_id=fir['id'],
        title='FIR Document Available',
        message=(
            f"The official FIR document for {fir_number} is now available in your portal. "
            'You can view and download the PDF from your FIR details page.'
        ),
        notification_type='FIR_DOCUMENT',
        severity='SUCCESS',
        event_id=f"fir-document-citizen-{fir['id']}-v{version}",
    )
    officer_id = fir.get('assigned_officer_id')
    if officer_id:
        create_notification(
            user_id=officer_id,
            fir_id=fir['id'],
            title='FIR Document Available for Assigned Case',
            message=(
                f"The official FIR document for {fir_number} has been generated and is "
                'available in your assigned case file for authorised download.'
            ),
            notification_type='FIR_DOCUMENT',
            severity='INFO',
            event_id=f"fir-document-officer-{fir['id']}-v{version}",
        )


def latest_document_path_for(fir_id: str, user: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return (absolute path, download filename) when the user may read the document."""
    fir = _load_fir(fir_id)
    if not can_view_fir_document(user, fir):
        return None
    document = get_current_document(fir_id)
    if not document:
        return None
    path = resolve_document_file(document.get('file_path'))
    if not path:
        return None
    return path, document.get('file_name') or f"{_safe_filename(fir.get('fir_number'))}.pdf"

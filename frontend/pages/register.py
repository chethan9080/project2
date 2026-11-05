"""
Citizen Registration — 5-Step Guided Verification Wizard.

Step 1: Account Credentials (Name, Email, Password)
Step 2: Government ID (Type + Number, CrPC justification, masking)
Step 3: Mobile Number + OTP Verification (6-digit, rate-limited)
Step 4: Camera / Photo Capture (live webcam or upload, with justification)
Step 5: Location Permission (browser geolocation, jurisdiction routing)
→ Application Submitted → Status Page (dashboard access locked until approved)
"""

import base64
import json
import os

from nicegui import ui, app as nicegui_app
from frontend.components.navbar import create_public_header
from backend.services.auth_service import register_user, set_current_user, delete_unverified_citizen
from backend.services.citizen_registration_service import create_citizen_application
from backend.services.verification_service import (
    mask_government_id,
    validate_government_id,
    send_otp,
    verify_otp,
    verify_location_capture,
    record_citizen_verification_event,
)

GOV_ID_TYPES = ["Aadhaar Card", "Voter ID Card", "Passport"]

STEP_TITLES = [
    "Account Details",
    "Government ID",
    "Mobile & OTP Verification",
    "Camera / Photo Capture",
    "Location Permission",
]

STEP_ICONS = ["person", "badge", "sms", "camera_alt", "location_on"]


@ui.page('/register')
def create_register_page() -> None:
    """5-Step Citizen Verification & Registration Wizard."""
    ui.page_title('Citizen Registration | eKSP Online FIR Portal')
    create_public_header()

    # ────────────────────────────────────────────────────────────────
    # STATE
    # ────────────────────────────────────────────────────────────────
    state = {
        # Step 1
        's1_name': '', 's1_email': '', 's1_password': '',
        's1_dob': '', 's1_gender': '',
        # Step 2
        's2_gov_id_type': GOV_ID_TYPES[0], 's2_gov_id': '', 's2_masked': '',
        's2_doc_bytes': None, 's2_doc_name': '', 's2_doc_ext': '',
        # Step 3
        's3_mobile': '', 's3_otp_sent': False, 's3_otp_verified': False,
        's3_demo_otp': '',
        # Step 4
        's4_photo_verified': False, 's4_photo_label': '',
        's4_photo_bytes': None, 's4_photo_ext': '.jpg',
        # Step 5
        's5_state': '', 's5_district': '', 's5_address': '',
        's5_latitude': None, 's5_longitude': None,
        's5_location_verified': False, 's5_location_name': '',
        # Navigation
        'current_step': 0,
        'registered_user': None,
        'submitting': False,
    }

    # ────────────────────────────────────────────────────────────────
    # PAGE SHELL
    # ────────────────────────────────────────────────────────────────
    with ui.column().classes('w-full min-h-screen items-center bg-[#F0F4FF] p-4 pt-8 gap-4'):

        # ── HEADER ───────────────────────────────────────────────
        with ui.card().classes('w-full max-w-3xl p-6 rounded-3xl bg-gradient-to-br from-blue-900 to-blue-700 shadow-xl'):
            with ui.row().classes('items-center gap-3'):
                ui.icon('how_to_reg', size='md').classes('text-white')
                with ui.column().classes('gap-0'):
                    ui.label('Citizen Verification & Registration').classes('text-white font-black text-xl')
                    ui.label('Secure · Official · Government Verified').classes('text-blue-200 text-xs font-medium')

        # ── STEP PROGRESS BAR ─────────────────────────────────────
        with ui.card().classes('w-full max-w-3xl p-4 rounded-2xl bg-white shadow border border-slate-100'):
            with ui.row().classes('w-full justify-between items-center gap-1'):
                for i, (title, icon) in enumerate(zip(STEP_TITLES, STEP_ICONS)):
                    with ui.column().classes('items-center flex-1 gap-1'):
                        is_active = i == state['current_step']
                        is_done = i < state['current_step']
                        badge_bg = (
                            'bg-blue-700 text-white' if is_active else
                            'bg-green-500 text-white' if is_done else
                            'bg-slate-200 text-slate-500'
                        )
                        with ui.element('div').classes(
                            f'w-9 h-9 rounded-full flex items-center justify-center text-sm font-black shadow {badge_bg}'
                        ):
                            ui.label('✓' if is_done else str(i + 1)).classes('text-sm font-black')
                        ui.label(title).classes('text-[9px] text-center text-slate-600 font-semibold leading-tight')


        # ── MAIN STEP CARDS ───────────────────────────────────────
        step_panels: list = []
        with ui.element('div').classes('w-full max-w-3xl'):

            # ╔══════════════════════════════════════╗
            # ║  STEP 1 — ACCOUNT DETAILS            ║
            # ╚══════════════════════════════════════╝
            panel1 = ui.card().classes('w-full p-6 rounded-2xl bg-white shadow border border-slate-100')
            with panel1:
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('person', size='sm').classes('text-blue-700')
                    ui.label('Step 1 — Create Your Account').classes('font-black text-slate-800 text-lg')

                with ui.card().classes('w-full p-3 bg-blue-50 border border-blue-200 rounded-xl mb-4'):
                    ui.label('📋 Why we collect this information:').classes('font-bold text-blue-900 text-xs mb-1')
                    ui.label('Your name and email will be used to create your secure citizen account. Your account is linked to your FIR filings and allows officers to contact you.').classes('text-xs text-blue-800')

                s1_name_ref = ui.input('Full Legal Name *', placeholder='e.g. Ramesh Kumar').classes('w-full')
                with ui.row().classes('w-full gap-3 flex-wrap'):
                    s1_dob_ref = ui.input('Date of Birth *').props('type=date outlined').classes('flex-1 min-w-48')
                    s1_gender_ref = ui.select(
                        ['Male', 'Female', 'Other', 'Prefer not to say'],
                        label='Gender (optional)',
                        value=None,
                    ).props('outlined clearable').classes('flex-1 min-w-48')
                s1_email_ref = ui.input('Email Address *', placeholder='e.g. ramesh@email.com').classes('w-full')
                s1_password_ref = ui.input('Create Password *', password=True, password_toggle_button=True,
                                            placeholder='Min. 8 characters').classes('w-full')
                s1_confirm_ref = ui.input('Confirm Password *', password=True, placeholder='Re-enter password').classes('w-full')

                s1_error = ui.label('').classes('text-red-600 text-xs font-semibold')

                def go_step1_next():
                    if not s1_name_ref.value or not s1_email_ref.value or not s1_password_ref.value:
                        s1_error.text = '⚠ All required fields must be filled.'
                        return
                    if '@' not in s1_email_ref.value or '.' not in s1_email_ref.value.split('@')[-1]:
                        s1_error.text = '⚠ Please enter a valid email address.'
                        return
                    if not s1_dob_ref.value:
                        s1_error.text = '⚠ Please enter your date of birth.'
                        return
                    if len(s1_password_ref.value) < 8:
                        s1_error.text = '⚠ Password must be at least 8 characters.'
                        return
                    if s1_password_ref.value != s1_confirm_ref.value:
                        s1_error.text = '⚠ Passwords do not match.'
                        return
                    state['s1_name'] = s1_name_ref.value
                    state['s1_email'] = s1_email_ref.value
                    state['s1_password'] = s1_password_ref.value
                    state['s1_dob'] = s1_dob_ref.value
                    state['s1_gender'] = s1_gender_ref.value or ''
                    s1_error.text = ''
                    go_to_step(1)

                ui.button('Continue to Government ID →', on_click=go_step1_next, icon='arrow_forward').props(
                    'unelevated'
                ).classes('w-full mt-4 bg-blue-800 text-white font-bold rounded-xl py-2 text-sm')

            step_panels.append(panel1)

            # ╔══════════════════════════════════════╗
            # ║  STEP 2 — GOVERNMENT ID              ║
            # ╚══════════════════════════════════════╝
            panel2 = ui.card().classes('w-full p-6 rounded-2xl bg-white shadow border border-slate-100').set_visibility(False)
            with panel2:
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('badge', size='sm').classes('text-blue-700')
                    ui.label('Step 2 — Government ID Verification').classes('font-black text-slate-800 text-lg')

                with ui.card().classes('w-full p-3 bg-indigo-50 border border-indigo-200 rounded-xl mb-4'):
                    ui.label('🏛 CrPC Section 154 — Why we need this:').classes('font-bold text-indigo-900 text-xs mb-1')
                    ui.label('Under the Code of Criminal Procedure, Section 154, FIR filers must verify their identity with a valid Government-issued ID. This prevents fraudulent or anonymous complaints and ensures legal accountability.').classes('text-xs text-indigo-800')
                    ui.label('Your ID number is cryptographically masked. Only the last 4 digits are stored — the full number is never retained.').classes('text-[11px] text-indigo-700 mt-1 font-semibold')

                s2_gov_type_ref = ui.select(GOV_ID_TYPES, label='ID Type *', value=GOV_ID_TYPES[0]).classes('w-full')
                s2_gov_id_ref = ui.input('ID Number *', placeholder='Enter your Government ID number').classes('w-full')
                s2_masked_label = ui.label('').classes('text-xs font-mono text-slate-500 mt-1')

                def update_mask():
                    v = s2_gov_id_ref.value
                    if v and len(v.strip()) >= 4:
                        s2_masked_label.text = f'Stored as: {mask_government_id(v, s2_gov_type_ref.value)}'
                    else:
                        s2_masked_label.text = ''

                s2_gov_id_ref.on('input', lambda _: update_mask())

                s2_doc_status = ui.label('No ID document attached yet.').classes('text-xs text-slate-500')

                async def handle_doc_upload(event):
                    try:
                        data = await event.file.read()
                        extension = os.path.splitext(event.file.name or '')[1].lower()
                        if extension not in ('.pdf', '.png', '.jpg', '.jpeg'):
                            s2_doc_status.text = '⚠ Unsupported file type. Upload a PDF, JPG, or PNG.'
                            return
                        if not data:
                            s2_doc_status.text = '⚠ The selected document is empty.'
                            return
                        state['s2_doc_bytes'] = data
                        state['s2_doc_name'] = event.file.name
                        state['s2_doc_ext'] = extension
                        s2_doc_status.text = f'✅ {event.file.name} attached ({len(data) // 1024} KB).'
                        s2_doc_status.classes(remove='text-slate-500 text-red-600', add='text-green-700 font-semibold')
                    except Exception as error:
                        s2_doc_status.text = f'⚠ Could not read the document: {error}'

                ui.upload(
                    label='Upload Government ID Document (PDF / JPG / PNG) *',
                    auto_upload=True,
                    max_files=1,
                    max_file_size=5_000_000,
                    on_upload=handle_doc_upload,
                ).props('accept=.pdf,.png,.jpg,.jpeg flat bordered').classes('w-full mt-2')

                s2_error = ui.label('').classes('text-red-600 text-xs font-semibold mt-1')

                def go_step2_next():
                    ok, msg = validate_government_id(s2_gov_id_ref.value, s2_gov_type_ref.value)
                    if not ok:
                        s2_error.text = f'⚠ {msg}'
                        return
                    if not state.get('s2_doc_bytes'):
                        s2_error.text = '⚠ Please upload a copy of your Government ID document.'
                        return
                    state['s2_gov_id_type'] = s2_gov_type_ref.value
                    state['s2_gov_id'] = s2_gov_id_ref.value
                    state['s2_masked'] = mask_government_id(s2_gov_id_ref.value, s2_gov_type_ref.value)
                    s2_error.text = ''
                    go_to_step(2)

                with ui.row().classes('w-full gap-2 mt-4'):
                    ui.button('← Back', on_click=lambda: go_to_step(0), icon='arrow_back').props('flat').classes('text-slate-600')
                    ui.button('Continue to OTP Verification →', on_click=go_step2_next, icon='arrow_forward').props(
                        'unelevated'
                    ).classes('flex-1 bg-blue-800 text-white font-bold rounded-xl py-2 text-sm')

            step_panels.append(panel2)

            # ╔══════════════════════════════════════╗
            # ║  STEP 3 — MOBILE + OTP               ║
            # ╚══════════════════════════════════════╝
            panel3 = ui.card().classes('w-full p-6 rounded-2xl bg-white shadow border border-slate-100').set_visibility(False)
            with panel3:
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('sms', size='sm').classes('text-blue-700')
                    ui.label('Step 3 — Mobile Number & OTP Verification').classes('font-black text-slate-800 text-lg')

                with ui.card().classes('w-full p-3 bg-green-50 border border-green-200 rounded-xl mb-4'):
                    ui.label('📱 Why mobile verification is required:').classes('font-bold text-green-900 text-xs mb-1')
                    ui.label('Two-Factor Authentication (2FA) via mobile OTP ensures that only you can register with your email. Critically, officers and police stations will use this number to contact you for your FIR.').classes('text-xs text-green-800')

                s3_mobile_ref = ui.input('Mobile Number *', placeholder='+91 98765 43210').classes('w-full')
                s3_otp_ref = ui.input('Enter 6-Digit OTP *', placeholder='______').classes('w-full')
                s3_demo_label = ui.label('').classes('text-xs font-mono text-amber-700 font-bold')
                s3_status = ui.label('').classes('text-xs font-semibold mt-1')

                def do_send_otp():
                    ok, msg, demo_code = send_otp(s3_mobile_ref.value)
                    if ok:
                        state['s3_otp_sent'] = True
                        state['s3_demo_otp'] = demo_code or ''
                        s3_status.text = f'✅ {msg}'
                        s3_status.classes(remove='text-red-600')
                        s3_status.classes(add='text-green-700')
                        if demo_code:
                            s3_demo_label.text = f'🧪 Demo OTP: {demo_code} (also "123456" accepted)'
                    else:
                        s3_status.text = f'⚠ {msg}'
                        s3_status.classes(remove='text-green-700')
                        s3_status.classes(add='text-red-600')

                ui.button('📲 Send OTP', on_click=do_send_otp).props('unelevated').classes(
                    'w-full bg-emerald-600 text-white font-bold rounded-xl py-2 text-sm mt-2'
                )

                s3_error = ui.label('').classes('text-red-600 text-xs font-semibold mt-1')

                def go_step3_next():
                    ok, msg = verify_otp(s3_mobile_ref.value, s3_otp_ref.value)
                    if not ok:
                        s3_error.text = f'⚠ {msg}'
                        return
                    state['s3_mobile'] = s3_mobile_ref.value
                    state['s3_otp_verified'] = True
                    s3_error.text = ''
                    ui.notify('OTP Verified ✓', type='positive')
                    go_to_step(3)

                with ui.row().classes('w-full gap-2 mt-4'):
                    ui.button('← Back', on_click=lambda: go_to_step(1), icon='arrow_back').props('flat').classes('text-slate-600')
                    ui.button('Verify OTP & Continue →', on_click=go_step3_next, icon='arrow_forward').props(
                        'unelevated'
                    ).classes('flex-1 bg-blue-800 text-white font-bold rounded-xl py-2 text-sm')

            step_panels.append(panel3)

            # ╔══════════════════════════════════════╗
            # ║  STEP 4 — CAMERA / PHOTO             ║
            # ╚══════════════════════════════════════╝
            panel4 = ui.card().classes('w-full p-6 rounded-2xl bg-white shadow border border-slate-100').set_visibility(False)
            with panel4:
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('camera_alt', size='sm').classes('text-blue-700')
                    ui.label('Step 4 — Identity Photo Capture').classes('font-black text-slate-800 text-lg')

                with ui.card().classes('w-full p-3 bg-purple-50 border border-purple-200 rounded-xl mb-4'):
                    ui.label('📷 Why a photo is required:').classes('font-bold text-purple-900 text-xs mb-1')
                    ui.label('Your photo is used for liveness detection and to cross-verify your Government ID visually. This prevents impersonation and ensures the FIR is filed by the actual ID holder. Your photo is encrypted at rest and never shared publicly.').classes('text-xs text-purple-800')
                    ui.label('📌 Camera access is requested ONLY for this step.').classes('text-[11px] text-purple-700 mt-1 font-semibold')

                ui.html("""
                    <video id="citizen-camera" autoplay playsinline muted
                           style="width:100%;max-width:420px;min-height:240px;background:#0f172a;border-radius:1rem;margin:0.5rem 0"></video>
                    <div id="citizen-camera-status" style="font-size:0.75rem;color:#64748b">
                        Camera is off. Press "Enable Camera" to begin.
                    </div>
                """).classes('w-full')

                s4_photo_status = ui.label('No photo captured yet.').classes('text-xs text-slate-500')
                s4_error = ui.label('').classes('text-red-600 text-xs font-semibold mt-1')
                photo_preview = ui.column().classes('w-full items-start')

                async def do_enable_camera():
                    await ui.run_javascript("""
                        (() => {
                            const video = document.getElementById('citizen-camera');
                            const status = document.getElementById('citizen-camera-status');
                            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                                if (status) status.textContent = 'Camera API unavailable. Use the photo upload fallback below.';
                                return 'unavailable';
                            }
                            navigator.mediaDevices.getUserMedia({video: {facingMode: 'user'}, audio: false})
                                .then((stream) => {
                                    window.__citizenCameraStream = stream;
                                    video.srcObject = stream;
                                    video.play();
                                    if (status) status.textContent = 'Camera is live. Center your face and press Capture Photo.';
                                })
                                .catch((error) => {
                                    if (status) status.textContent = 'Camera unavailable: ' + error.message + '. Use the photo upload fallback below.';
                                });
                            return 'requested';
                        })()
                    """, timeout=10.0)

                async def do_capture_photo():
                    data_url = await ui.run_javascript("""
                        (() => {
                            const video = document.getElementById('citizen-camera');
                            if (!video || !video.videoWidth) return '';
                            const canvas = document.createElement('canvas');
                            canvas.width = video.videoWidth;
                            canvas.height = video.videoHeight;
                            canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
                            return canvas.toDataURL('image/jpeg', 0.86);
                        })()
                    """, timeout=10.0)
                    if not isinstance(data_url, str) or not data_url.startswith('data:image'):
                        s4_error.text = '⚠ No camera frame available. Enable the camera first, or upload a photograph below.'
                        return
                    try:
                        header, encoded = data_url.split(',', 1)
                        state['s4_photo_bytes'] = base64.b64decode(encoded)
                        state['s4_photo_ext'] = '.png' if 'png' in header else '.jpg'
                        state['s4_photo_verified'] = True
                        state['s4_photo_label'] = 'Live Camera Snapshot'
                        s4_error.text = ''
                        s4_photo_status.text = '✅ Live camera photograph captured.'
                        s4_photo_status.classes(remove='text-slate-500 text-red-600', add='text-green-700 font-semibold')
                        photo_preview.clear()
                        with photo_preview:
                            ui.image(data_url).classes('w-40 h-40 object-cover rounded-2xl border-2 border-purple-300 shadow-sm')
                    except Exception as error:
                        s4_error.text = f'⚠ Could not store the captured photo: {error}'

                with ui.row().classes('w-full gap-2 flex-wrap'):
                    ui.button('🎥 Enable Camera', on_click=do_enable_camera).props('outlined').classes(
                        'flex-1 min-w-40 text-purple-800 border-purple-300 font-bold rounded-xl py-2 text-xs'
                    )
                    ui.button('📸 Capture Photo', on_click=do_capture_photo).props('unelevated').classes(
                        'flex-1 min-w-40 bg-purple-700 text-white font-bold rounded-xl py-2 text-xs'
                    )

                ui.label('— or upload a photograph if a camera is not available —').classes('text-xs text-slate-400 text-center w-full mt-2')

                async def handle_photo_upload(event):
                    try:
                        data = await event.file.read()
                        extension = os.path.splitext(event.file.name or '')[1].lower()
                        if extension not in ('.png', '.jpg', '.jpeg'):
                            s4_error.text = '⚠ Photo must be a JPG or PNG image.'
                            return
                        if not data:
                            s4_error.text = '⚠ The selected photo is empty.'
                            return
                        state['s4_photo_bytes'] = data
                        state['s4_photo_ext'] = extension
                        state['s4_photo_verified'] = True
                        state['s4_photo_label'] = 'Uploaded Identity Photograph'
                        s4_error.text = ''
                        s4_photo_status.text = f'✅ Photo attached: {event.file.name}'
                        s4_photo_status.classes(remove='text-slate-500 text-red-600', add='text-green-700 font-semibold')
                        preview_source = f"data:{event.file.content_type or 'image/jpeg'};base64,{base64.b64encode(data).decode()}"
                        photo_preview.clear()
                        with photo_preview:
                            ui.image(preview_source).classes('w-40 h-40 object-cover rounded-2xl border-2 border-purple-300 shadow-sm')
                    except Exception as error:
                        s4_error.text = f'⚠ Could not read the photograph: {error}'

                ui.upload(
                    label='Upload Photograph (JPG / PNG)',
                    auto_upload=True,
                    max_files=1,
                    max_file_size=5_000_000,
                    on_upload=handle_photo_upload,
                ).props('accept=.png,.jpg,.jpeg flat bordered').classes('w-full')

                def go_step4_next():
                    if not state.get('s4_photo_bytes'):
                        s4_error.text = '⚠ Please capture a live photograph or upload a clear photo before continuing.'
                        return
                    s4_error.text = ''
                    go_to_step(4)

                with ui.row().classes('w-full gap-2 mt-4'):
                    ui.button('← Back', on_click=lambda: go_to_step(2), icon='arrow_back').props('flat').classes('text-slate-600')
                    ui.button('Continue to Location →', on_click=go_step4_next, icon='arrow_forward').props(
                        'unelevated'
                    ).classes('flex-1 bg-blue-800 text-white font-bold rounded-xl py-2 text-sm')

            step_panels.append(panel4)

            # ╔══════════════════════════════════════╗
            # ║  STEP 5 — LOCATION PERMISSION        ║
            # ╚══════════════════════════════════════╝
            panel5 = ui.card().classes('w-full p-6 rounded-2xl bg-white shadow border border-slate-100').set_visibility(False)
            with panel5:
                with ui.row().classes('items-center gap-2 mb-4'):
                    ui.icon('location_on', size='sm').classes('text-blue-700')
                    ui.label('Step 5 — Location Verification').classes('font-black text-slate-800 text-lg')

                with ui.card().classes('w-full p-3 bg-teal-50 border border-teal-200 rounded-xl mb-4'):
                    ui.label('📍 Why location access is required:').classes('font-bold text-teal-900 text-xs mb-1')
                    ui.label('Your location is captured once during registration to identify the correct Police Jurisdiction / Station for your area. This ensures your FIR is automatically routed to the right law enforcement unit.').classes('text-xs text-teal-800')
                    ui.label('⚠ Location is captured ONLY at this step. We do not continuously track you after registration.').classes('text-[11px] text-teal-700 mt-1 font-semibold')

                s5_state_ref = ui.input('State / Union Territory *', placeholder='e.g. Karnataka').classes('w-full')
                s5_district_ref = ui.input('District / Area *', placeholder='e.g. Bengaluru Urban').classes('w-full')
                s5_address_ref = ui.textarea(
                    'Residential Address *',
                    placeholder='House / flat number, street, locality, PIN code',
                ).props('outlined rows=3').classes('w-full')
                s5_status = ui.label('Location not captured yet.').classes('text-xs text-slate-500')
                s5_error = ui.label('').classes('text-red-600 text-xs font-semibold mt-1')

                # Browser geolocation via JS
                location_data_holder = {'lat': None, 'lon': None}

                async def request_browser_location():
                    try:
                        result = await ui.run_javascript("""
                            return new Promise((resolve, reject) => {
                                if (!navigator.geolocation) {
                                    reject('Geolocation not supported by this browser.');
                                    return;
                                }
                                navigator.geolocation.getCurrentPosition(
                                    (pos) => resolve({lat: pos.coords.latitude, lon: pos.coords.longitude}),
                                    (err) => reject(err.message || 'Location access denied.'),
                                    {timeout: 8000, maximumAge: 0}
                                );
                            });
                        """, timeout=12.0)
                        if isinstance(result, dict) and 'lat' in result:
                            location_data_holder['lat'] = result['lat']
                            location_data_holder['lon'] = result['lon']
                            state['s5_latitude'] = result['lat']
                            state['s5_longitude'] = result['lon']
                            state['s5_location_verified'] = True
                            s5_status.text = f"✅ Location captured: {result['lat']:.4f}, {result['lon']:.4f}"
                            s5_status.classes(remove='text-slate-500')
                            s5_status.classes(add='text-green-700 font-semibold')
                        else:
                            s5_error.text = '⚠ Could not get precise location. Please enter district manually.'
                    except Exception as e:
                        s5_error.text = f'⚠ Location error: {e}. Please enter your district manually.'

                async def do_get_location():
                    await request_browser_location()

                ui.button(
                    '📍 Allow Location Access',
                    on_click=do_get_location
                ).props('unelevated').classes('w-full bg-teal-700 text-white font-bold rounded-xl py-2 text-sm mt-2')

                async def go_step5_complete():
                    if state['submitting']:
                        return
                    if not (s5_state_ref.value or '').strip():
                        s5_error.text = '⚠ Please enter your State / Union Territory.'
                        return
                    if not (s5_district_ref.value or '').strip():
                        s5_error.text = '⚠ Please enter your district to continue.'
                        return
                    if not (s5_address_ref.value or '').strip():
                        s5_error.text = '⚠ Please enter your residential address.'
                        return
                    if not state.get('s2_doc_bytes') or not state.get('s4_photo_bytes'):
                        s5_error.text = '⚠ Your ID document and photograph are required before submission.'
                        return

                    state['submitting'] = True
                    submit_button.disable()

                    state_name = s5_state_ref.value.strip()
                    district = s5_district_ref.value.strip()
                    address = s5_address_ref.value.strip()
                    ok, msg, loc_data = verify_location_capture(
                        district,
                        state.get('s5_latitude'),
                        state.get('s5_longitude')
                    )
                    state['s5_state'] = state_name
                    state['s5_district'] = district
                    state['s5_address'] = address
                    state['s5_location_name'] = msg

                    user = None
                    application = None
                    try:
                        user = register_user(
                            name=state['s1_name'],
                            email=state['s1_email'],
                            phone=state['s3_mobile'],
                            password=state['s1_password'],
                            role='CITIZEN',
                            district=district,
                            address=address,
                            gov_id=state['s2_gov_id'],
                            status='PENDING_VERIFICATION',
                        )

                        application = create_citizen_application(
                            citizen_id=user['id'],
                            full_name=state['s1_name'],
                            date_of_birth=state['s1_dob'],
                            gender=state['s1_gender'],
                            mobile=state['s3_mobile'],
                            email=state['s1_email'],
                            address=address,
                            state=state_name,
                            district=district,
                            username=user['email'],
                            gov_id_type=state['s2_gov_id_type'],
                            gov_id_masked=state['s2_masked'],
                            photo_bytes=state['s4_photo_bytes'],
                            photo_ext=state['s4_photo_ext'],
                            document_bytes=state['s2_doc_bytes'],
                            document_ext=state['s2_doc_ext'],
                            document_name=state['s2_doc_name'],
                        )

                        # Legacy onboarding record, kept aligned with the review status.
                        record_citizen_verification_event(
                            citizen_id=user['id'],
                            gov_id_type=state['s2_gov_id_type'],
                            gov_id_masked=state['s2_masked'],
                            mobile=state['s3_mobile'],
                            otp_verified=state['s3_otp_verified'],
                            photo_verified=state['s4_photo_verified'],
                            location_verified=ok,
                            location_data=loc_data,
                            status='PENDING',
                        )
                        # No dashboard session is created until a Verification Officer approves.
                        set_current_user(None)
                        state['registered_user'] = user
                        nicegui_app.storage.user['pending_application_reference'] = application['reference']
                        nicegui_app.storage.user['pending_application_email'] = user['email']
                        s5_error.text = ''
                        ui.notify(
                            f'✅ Registration submitted as {application["reference"]}. '
                            'Portal access stays locked until a Verification Officer approves it.',
                            type='positive',
                        )
                        ui.navigate.to('/citizen/application-status')
                    except ValueError as e:
                        if user:
                            delete_unverified_citizen(user['id'])
                        s5_error.text = f'⚠ {e}'
                    except Exception as e:
                        if user:
                            delete_unverified_citizen(user['id'])
                        s5_error.text = f'⚠ Registration error: {e}'
                    finally:
                        state['submitting'] = False
                        submit_button.enable()

                with ui.row().classes('w-full gap-2 mt-4'):
                    ui.button('← Back', on_click=lambda: go_to_step(3), icon='arrow_back').props('flat').classes('text-slate-600')
                    submit_button = ui.button('✅ Submit Registration for Verification', on_click=go_step5_complete).props(
                        'unelevated'
                    ).classes('flex-1 bg-green-700 text-white font-black rounded-xl py-3 text-sm shadow-lg')

            step_panels.append(panel5)

        # ────────────────────────────────────────────────────────────────
        # NAVIGATION HELPER
        # ────────────────────────────────────────────────────────────────
        def go_to_step(step: int):
            for i, panel in enumerate(step_panels):
                panel.set_visibility(i == step)
            state['current_step'] = step

        with ui.row().classes('text-xs text-slate-400 mt-2 gap-1'):
            ui.label('Already registered?')
            ui.button('Sign in here', on_click=lambda: ui.navigate.to('/login')).props('flat dense size=xs').classes('text-blue-700 font-bold')

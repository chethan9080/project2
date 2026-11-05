"""
Landing Page - Blockchain-Based Online FIR Management & Tamper-Evident Audit Platform.
"""

from nicegui import ui
from frontend.i18n import t
from frontend.components.navbar import create_public_header


def create_home_page() -> None:
    """Render the official landing page for the Digital FIR Platform with Citizen-First Hierarchy."""
    ui.page_title(t('Online FIR Portal · Government of Karnataka'))
    create_public_header(show_language_switcher=True)

    with ui.column().classes('w-full min-h-screen justify-between bg-[#F8FAFC]'):
        # =========================================================================
        # 1. MAIN HERO — CITIZEN-FOCUSED
        # =========================================================================
        with ui.column().classes('w-full items-center px-6 py-16 text-center md:py-24 shadow-md relative').style(
            'background: linear-gradient(135deg, #0A192F 0%, #1B365D 50%, #0D244D 100%); '
            'border-bottom: 3px solid #D97706;'
        ):
            # Official Government Badge
            with ui.row().classes('items-center gap-2 px-4 py-1.5 rounded-full border border-amber-400/40 bg-amber-500/10 mb-4'):
                ui.icon('verified', size='xs').classes('text-amber-400')
                ui.label(t('GOVERNMENT OF KARNATAKA · DIGITAL CITIZEN POLICE SERVICES')).classes('text-amber-300 font-bold text-xs tracking-widest')

            # Main Headline
            ui.label(t('Online FIR')).classes('text-4xl md:text-6xl font-black text-white tracking-tight')
            ui.label(t('Secure. Transparent. Traceable.')).classes('text-2xl md:text-4xl font-bold text-amber-400 mt-2 fantasy-title')

            # Supporting Text
            ui.label(
                t('Submit, track, and manage official First Information Reports (FIRs) digitally with real-time updates and tamper-evident blockchain-backed audit trails.')
            ).classes('mt-5 max-w-3xl text-base md:text-xl text-slate-200 leading-relaxed font-medium')

            # Primary Citizen CTAs (Citizen Login)
            with ui.column().classes('mt-8 items-center gap-3'):
                ui.button(
                    t('CITIZEN LOGIN'),
                    icon='login',
                    on_click=lambda: ui.navigate.to('/login')
                ).props('unelevated').style(
                    'background: white; color: #1e3a5f; font-weight: 900; '
                    'border-radius: 1rem; padding: 1rem 3rem; '
                    'font-size: 0.95rem; letter-spacing: 0.05em; '
                    'box-shadow: 0 8px 24px rgba(0,0,0,0.2);'
                )
                # Direct Citizen Registration & Flow Helper Link
                with ui.row().classes('items-center gap-1.5 text-xs text-slate-300 mt-1'):
                    ui.label(t('First time here?'))
                    ui.link(t('Create Citizen Account →'), '/register').classes('text-amber-300 font-bold hover:text-amber-100 hover:underline')




        # =========================================================================
        # 2. CITIZEN ACCOUNT & FIR LIFECYCLE FLOW
        # =========================================================================
        with ui.column().classes('w-full max-w-6xl mx-auto px-6 py-16 gap-10'):
            with ui.column().classes('gap-2 text-center w-full items-center'):
                ui.badge('CITIZEN WORKFLOW').classes('bg-emerald-100 text-emerald-900 text-xs font-bold px-3 py-1 rounded-full')
                ui.label('How Citizens File & Manage FIRs Online').classes('text-3xl md:text-4xl font-black text-slate-900 fantasy-title')
                ui.label('A straightforward 4-step digital journey from initial registration to verified case resolution.').classes('text-sm md:text-base text-slate-600 max-w-2xl')

            with ui.row().classes('w-full flex-wrap gap-6 justify-center'):
                flow_steps = [
                    ('1', 'Create Citizen Account', 'person_add', 'Register your profile using your Government ID (Aadhaar / Voter ID) for authentic verification.'),
                    ('2', 'Citizen Login & 7-Step Filing', 'edit_document', 'Fill the structured 7-step wizard with incident details, accused info, witnesses, and evidence.'),
                    ('3', 'Receive Reference & Track Case', 'track_changes', 'Get your instant FIR number (FIR-2026-XXXXXX) and monitor live investigation milestones.'),
                    ('4', 'Inspect Sealed Audit Proofs', 'verified_user', 'Receive instant alerts on status changes and verify cryptographic proofs on the public ledger.')
                ]
                for num, title, icon, desc in flow_steps:
                    with ui.card().classes('min-w-64 max-w-72 flex-1 p-6 paper-card border border-slate-200 bg-white rounded-2xl shadow-sm hover:shadow-md transition-shadow'):
                        with ui.row().classes('items-center justify-between w-full mb-3'):
                            ui.icon(icon, size='md').classes('text-emerald-700')
                            ui.badge(f"Step {num}").classes('bg-emerald-100 text-emerald-900 font-bold text-xs')
                        ui.label(title).classes('text-base font-bold text-slate-900')
                        ui.label(desc).classes('text-xs text-slate-600 mt-2 leading-relaxed')

        # =========================================================================
        # 3. CITIZEN CORE SERVICES & BENEFITS
        # =========================================================================
        with ui.column().classes('w-full py-16 px-6 bg-slate-100 border-y border-slate-200'):
            with ui.column().classes('w-full max-w-6xl mx-auto gap-10'):
                with ui.column().classes('gap-2 text-center w-full items-center'):
                    ui.badge('CITIZEN CAPABILITIES').classes('bg-blue-100 text-blue-900 text-xs font-bold px-3 py-1 rounded-full')
                    ui.label('Key Citizen Portal Services').classes('text-3xl md:text-4xl font-black text-slate-900 fantasy-title')
                    ui.label('Complete transparency, official documentation, and guaranteed tamper-protection.').classes('text-sm text-slate-600 max-w-2xl')

                with ui.row().classes('w-full flex-wrap gap-6 justify-center'):
                    citizen_features = [
                        ('Instant FIR & Tracking Reference', 'pin', 'Unique reference numbers (FIR-2026-XXXXXX and REF-2026-XXXXXX) are generated immediately upon filing.'),
                        ('Official Police Station Routing', 'account_balance', 'FIRs are automatically mapped to local station jurisdictions (Koramangala, Indiranagar, Cyber Crime, etc.).'),
                        ('Real-Time Status Notifications', 'notifications_active', 'Receive immediate in-portal notices whenever investigating officers update your case status.'),
                        ('Official PDF Acknowledgement', 'picture_as_pdf', 'Download legally certified PDF acknowledgements stamped with verification timestamps and reference IDs.'),
                        ('Case Progress Timeline', 'timeline', 'Inspect the public progression of your FIR from Submission to Investigation, Charge Sheet, and Closure.'),
                        ('Dedicated Citizen Profile', 'badge', 'Manage your registered contact details, verified government ID mask, and past filed complaints.')
                    ]
                    for title, icon, desc in citizen_features:
                        with ui.card().classes('min-w-72 max-w-80 flex-1 p-6 bg-white border border-slate-200 rounded-2xl shadow-xs'):
                            with ui.row().classes('items-center gap-3 mb-2'):
                                ui.icon(icon, size='sm').classes('text-blue-900')
                                ui.label(title).classes('text-sm font-bold text-slate-900')
                            ui.label(desc).classes('text-xs text-slate-600 leading-relaxed')

        # =========================================================================
        # 4. WHY BLOCKCHAIN FOR FIR INTEGRITY
        # =========================================================================
        with ui.column().classes('w-full py-16 px-6 bg-slate-900 text-white'):
            with ui.column().classes('max-w-6xl mx-auto w-full gap-10'):
                with ui.column().classes('gap-2 text-center w-full items-center'):
                    ui.badge('CRYPTOGRAPHIC SECURITY').classes('bg-emerald-900 text-emerald-300 text-xs font-bold px-3 py-1 rounded-full')
                    ui.label('Why Blockchain for FIR Management?').classes('text-3xl md:text-4xl font-black text-white fantasy-title')
                    ui.label('Preventing unauthorized tampering and ensuring legal accountability with immutable mathematics.').classes('text-sm md:text-base text-slate-400 max-w-2xl')

                with ui.row().classes('w-full flex-wrap gap-6 justify-center'):
                    reasons = [
                        ('Tamper-Evident Hashing', 'gpp_good', 'Every record has a canonical SHA-256 hash. Any unauthorized database tampering creates an immediate alert.'),
                        ('Immutable Version Snapshots', 'history_edu', 'Material changes increment versions (v1 → v2 → v3). Historic snapshots are never erased.'),
                        ('Mandatory Officer Reasons', 'assignment_turned_in', 'Officers cannot alter FIR fields without providing a mandatory written reason and badge credentials.'),
                        ('Independent Ledger Verification', 'verified', 'Anyone can verify database records against on-chain block proofs in real time.')
                    ]
                    for title, icon, text in reasons:
                        with ui.card().classes('min-w-64 max-w-64 flex-1 p-6 rounded-2xl bg-slate-800/90 border border-slate-700'):
                            ui.icon(icon, size='md').classes('text-amber-400 mb-2')
                            ui.label(title).classes('text-base font-bold text-white')
                            ui.label(text).classes('text-xs text-slate-300 mt-2 leading-relaxed')

        # =========================================================================
        # 5. AUTHORIZED PERSONNEL SECTION (POSITIONED BELOW MAIN CONTENT)
        # =========================================================================
        with ui.column().classes('w-full max-w-6xl mx-auto px-6 py-14 items-center'):
            with ui.card().classes(
                'w-full max-w-4xl p-8 rounded-3xl border border-slate-300 bg-gradient-to-r from-slate-50 to-blue-50/60 shadow-sm'
            ):
                with ui.row().classes('w-full items-center justify-between flex-wrap gap-6'):
                    with ui.column().classes('gap-1 flex-1 min-w-72'):
                        with ui.row().classes('items-center gap-2 mb-1'):
                            ui.icon('shield', size='sm').classes('text-blue-900')
                            ui.label('AUTHORIZED PERSONNEL').classes('font-bold text-xs text-blue-900 tracking-widest')
                            ui.badge('RESTRICTED ACCESS').classes('bg-blue-100 text-blue-900 font-bold text-[10px]')

                        ui.label('Police & Authorized Staff Portal').classes('text-2xl font-black text-slate-900 fantasy-title')
                        ui.label(
                            'Official workspace for investigating officers, station supervisors (SHOs), and forensic administrators to review case queues, manage investigations, and execute blockchain integrity audits.'
                        ).classes('text-xs text-slate-600 leading-relaxed mt-1')

                    with ui.column().classes('items-start md:items-end gap-2'):
                        ui.button(
                            'POLICE / OFFICER LOGIN',
                            icon='local_police',
                            on_click=lambda: ui.navigate.to('/staff-portal')
                        ).props('unelevated size=md').classes(
                            'bg-blue-900 hover:bg-blue-950 text-white font-bold rounded-xl px-6 py-3 shadow-md text-xs tracking-wider'
                        )
                        ui.label('Requires registered departmental credentials').classes('text-[11px] text-slate-500 italic')

        # =========================================================================
        # 6. OFFICIAL FOOTER
        # =========================================================================
        with ui.element('footer').classes('w-full bg-[#0A192F] border-t border-slate-800 py-10 px-6 text-slate-400 text-center'):
            with ui.column().classes('w-full max-w-5xl mx-auto items-center gap-4'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('balance', size='sm').classes('text-amber-400')
                    ui.label('Government of Karnataka · Digital FIR & Blockchain Audit Platform').classes('text-sm font-bold text-white')

                ui.label(
                    'Online digital FIR filing portal providing citizen-centric police services and cryptographic accountability for public safety.'
                ).classes('text-xs text-slate-400 max-w-2xl leading-relaxed')

                with ui.row().classes('gap-5 mt-2 text-xs font-semibold flex-wrap justify-center'):
                    ui.link('File Online FIR', '/citizen/submit').classes('text-amber-400 hover:underline')
                    ui.link('Citizen Portal', '/citizen').classes('text-amber-400 hover:underline')
                    ui.link('Citizen Login', '/login').classes('text-amber-400 hover:underline')
                    ui.link('Create Account', '/register').classes('text-amber-400 hover:underline')
                    ui.link('Authorized Staff Portal', '/staff-portal').classes('text-slate-400 hover:text-white hover:underline')

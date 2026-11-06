"""
Landing Page — public entry point for the Online FIR Portal.

One full-screen hero that introduces the portal in words, then three sections
that explain what it does and where each audience signs in. The header anchor
links smooth-scroll between them; the page carries no images and no animations.
"""

from nicegui import ui

from frontend.components.navbar import create_public_header

# Section headings, in the order they appear on the page. The header renders the
# same list as anchor links, so the two stay in step automatically.
SECTIONS = [
    'How It Works',
    'Portal Services',
    'Access',
]

_HERO_BG = 'background: linear-gradient(135deg, #0A192F 0%, #1B365D 50%, #0D244D 100%);'
_CARD = 'w-full p-5 rounded-2xl glass-card'

_HERO_TITLE = 'Your Safety. Your Voice. Our Responsibility.'
_HERO_DESCRIPTION = (
    'A secure digital platform for citizens to submit complaints, register FIRs, '
    'track investigation progress and communicate with authorized police officers.'
)
_HERO_FEATURES = [
    'Secure Citizen Registration.',
    'Online Complaint and FIR Services.',
    'Transparent FIR Tracking.',
    'Real-Time Notifications.',
    'Direct Communication with Investigating Officers.',
    'Blockchain-Based Tamper-Evident Records.',
]


def _grid_card(index: int, extra: str):
    """A glass card that fades up into view, staggered by its position."""
    return ui.card().classes(f'{_CARD} {extra} reveal').style(f'--reveal-delay: {index * 90}ms')


def _section_heading(kicker: str, title: str, subtitle: str) -> None:
    with ui.column().classes('reveal w-full items-center gap-2 text-center'):
        ui.badge(kicker).classes('kicker-badge')
        ui.label(title).classes('section-title font-black text-slate-900 fantasy-title')
        ui.label(subtitle).classes('text-sm text-slate-600 max-w-2xl leading-relaxed')


def _render_hero() -> None:
    """The first screen: what the portal is for, what it offers, and how to get in."""
    with ui.column().classes(
        'hero-screen w-full gap-5 px-5 py-10 border-b-[3px] border-amber-600 items-center'
    ).style(_HERO_BG):
        with ui.row().classes(
            'reveal flex-nowrap items-center gap-2 px-3 py-1 rounded-full '
            'border border-amber-400/40 bg-amber-500/10'
        ):
            ui.icon('verified', size='xs').classes('text-amber-400 shrink-0')
            ui.label('GOVERNMENT OF KARNATAKA · DIGITAL CITIZEN POLICE SERVICES').classes(
                'text-amber-300 font-bold text-[9px] tracking-widest'
            )

        with ui.column().classes('reveal w-full max-w-3xl items-center gap-2 text-center'):
            ui.label(_HERO_TITLE).classes('hero-title font-black text-white tracking-tight')
            ui.label('Secure. Transparent. Traceable.').classes(
                'hero-sub font-bold text-amber-400 fantasy-title'
            )
            ui.label(_HERO_DESCRIPTION).classes(
                'hero-lede max-w-2xl text-slate-200 leading-relaxed font-medium'
            ).style('--reveal-delay: 90ms')

        with ui.element('div').classes('reveal flow-grid w-full max-w-3xl').style(
            '--flow-min: 17rem; --reveal-delay: 180ms;'
        ):
            for feature in _HERO_FEATURES:
                with ui.element('div').classes('flex flex-nowrap items-start gap-2 min-w-0'):
                    ui.icon('check_circle', size='xs').classes('text-amber-400 shrink-0 mt-0.5')
                    ui.label(feature).classes('text-[13px] font-semibold text-slate-100 text-left min-w-0')

        with ui.column().classes('reveal items-center gap-2 pt-1').style('--reveal-delay: 270ms;'):
            ui.button(
                'Citizen Login', icon='login', on_click=lambda: ui.navigate.to('/login')
            ).props('unelevated no-caps').classes('cta-glow').style(
                'background: #FFFFFF !important; color: #0A192F !important; font-weight: 900; '
                'border-radius: 0.9rem; padding: 0.85rem 2.5rem; font-size: 0.95rem; '
                'letter-spacing: 0.05em; box-shadow: 0 8px 24px rgba(0,0,0,0.25);'
            )
            with ui.row().classes(
                'flex-wrap items-center justify-center gap-x-2 gap-y-1 text-xs text-slate-300'
            ):
                ui.label('First time here?').classes('font-medium')
                ui.link('Create an Account →', '/register').classes(
                    'text-amber-300 font-bold hover:text-amber-100 hover:underline whitespace-nowrap'
                )
                ui.element('div').classes('h-3.5 w-px bg-white/25 mx-1')
                ui.link('Staff Login →', '/staff-portal').classes(
                    'text-amber-300 font-bold hover:text-amber-100 hover:underline whitespace-nowrap'
                )


def _render_steps() -> None:
    """The citizen journey, from registration to a tracked case."""
    steps = [
        ('1', 'person_add', 'Create Citizen Account',
         'Register your profile using your Government ID (Aadhaar / Voter ID) for authentic verification.'),
        ('2', 'edit_document', 'File Your Complaint Online',
         'Complete the guided complaint form with incident details, witnesses and supporting evidence.'),
        ('3', 'track_changes', 'Receive Reference & Track Case',
         'Follow every stage from submission to closure and get notified whenever officers act on your case.'),
    ]
    with ui.column().classes('section-anchor w-full max-w-6xl mx-auto px-5 py-12 gap-8'):
        _section_heading('CITIZEN WORKFLOW', 'How It Works',
                         'Three steps from registration to a tracked, verified case.')

        with ui.element('div').classes('flow-grid flow-grid-cards w-full'):
            for index, (number, icon_name, title, description) in enumerate(steps):
                with _grid_card(index, 'gap-2 items-start'):
                    with ui.row().classes('w-full items-center gap-3'):
                        with ui.element('div').classes(
                            'gov-step-orb w-9 h-9 shrink-0 rounded-full flex items-center '
                            'justify-center text-white text-sm font-black'
                        ):
                            ui.label(number)
                        ui.label(title).classes('text-sm font-bold text-slate-900 min-w-0')
                        ui.icon(icon_name, size='sm').classes('text-blue-900 ml-auto shrink-0')
                    ui.label(description).classes('text-xs text-slate-600 leading-relaxed')


def _render_services() -> None:
    """What a verified citizen can do once signed in."""
    services = [
        ('pin', 'Instant FIR & Tracking Reference',
         'A reference number is issued immediately when your complaint is recorded.'),
        ('notifications_active', 'Real-Time Status Notifications',
         'Receive immediate in-portal notices whenever investigating officers update your case status.'),
        ('picture_as_pdf', 'Official PDF Acknowledgement',
         'Download PDF acknowledgements stamped with verification timestamps and reference IDs.'),
        ('gpp_good', 'Tamper-Evident Records',
         'Every record has a canonical SHA-256 hash, so unauthorized database tampering creates an immediate alert.'),
    ]
    with ui.column().classes(
        'section-anchor w-full py-12 px-5 bg-slate-100 border-y border-slate-200 gap-8'
    ):
        _section_heading('CITIZEN CAPABILITIES', 'Portal Services',
                         'Official documentation, live case visibility and tamper protection.')

        with ui.element('div').classes('flow-grid flow-grid-services w-full max-w-6xl mx-auto'):
            for index, (icon_name, title, description) in enumerate(services):
                with _grid_card(index, 'gap-1.5 items-start'):
                    ui.icon(icon_name, size='sm').classes('text-blue-900')
                    ui.label(title).classes('text-sm font-bold text-slate-900')
                    ui.label(description).classes('text-xs text-slate-600 leading-relaxed')


def _render_access() -> None:
    """Where each audience signs in."""
    with ui.column().classes('section-anchor w-full max-w-6xl mx-auto px-5 py-12 gap-8'):
        _section_heading('PORTAL ACCESS', 'Access',
                         'Citizens and departmental staff use separate, role-scoped sign-in pages.')

        with ui.element('div').classes('flow-grid flow-grid-wide w-full'):
            with ui.card().classes('w-full p-6 gap-3 items-start rounded-2xl glass-card reveal'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('how_to_reg', size='sm').classes('text-emerald-700')
                    ui.label('Citizen Portal').classes('text-lg font-bold text-slate-900 fantasy-title')
                ui.label(
                    'File a complaint, track your own FIRs, message the investigating officer '
                    'and keep your verified profile up to date.'
                ).classes('text-xs text-slate-600 leading-relaxed')
                with ui.row().classes('flex-wrap items-center gap-2 pt-1'):
                    ui.button(
                        'Citizen Login', icon='login', on_click=lambda: ui.navigate.to('/login')
                    ).props('unelevated no-caps').classes('cta-glow').style(
                        'background: linear-gradient(120deg, #047857 0%, #059669 100%) !important; '
                        'color: #FFFFFF !important; font-weight: 700; border-radius: 0.75rem; '
                        'padding: 0.5rem 1.25rem; font-size: 0.75rem;'
                    )
                    ui.button(
                        'Create Account', icon='person_add', on_click=lambda: ui.navigate.to('/register')
                    ).props('outline no-caps').classes(
                        'text-emerald-800 font-bold rounded-xl px-4 py-2 text-xs'
                    )

            with ui.card().classes(
                'w-full p-6 gap-3 items-start rounded-2xl glass-dark reveal'
            ).style('--reveal-delay: 120ms'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('local_police', size='sm').classes('text-amber-300')
                    ui.label('Police & Authorized Staff Portal').classes(
                        'text-lg font-bold text-white fantasy-title'
                    )
                ui.label(
                    'Official workspace for investigating officers, verification officers and '
                    'administrators to review case queues and manage investigations.'
                ).classes('text-xs text-slate-200 leading-relaxed')
                with ui.row().classes('flex-wrap items-center gap-2 pt-1'):
                    ui.button(
                        'POLICE / OFFICER LOGIN', icon='shield',
                        on_click=lambda: ui.navigate.to('/staff-portal')
                    ).props('unelevated no-caps').classes('cta-glow').style(
                        'background: linear-gradient(120deg, #1D4ED8 0%, #2563EB 100%) !important; '
                        'color: #FFFFFF !important; font-weight: 700; border-radius: 0.75rem; '
                        'padding: 0.5rem 1.25rem; font-size: 0.75rem;'
                    )
                    ui.label('Requires registered departmental credentials').classes(
                        'text-[11px] text-slate-300 italic'
                    )


def _render_footer() -> None:
    with ui.element('footer').classes(
        'w-full bg-[#0A192F] border-t border-slate-800 px-5 py-7 text-center text-slate-400'
    ):
        with ui.column().classes('w-full max-w-4xl mx-auto items-center gap-2'):
            with ui.row().classes('flex-wrap items-center justify-center gap-2'):
                ui.icon('balance', size='sm').classes('text-amber-400')
                ui.label('Government of Karnataka · Digital FIR & Blockchain Audit Platform').classes(
                    'text-xs font-bold text-white'
                )
            ui.label(
                'Prototype demonstration of digital FIR filing with cryptographic accountability. '
                'Not an official government portal.'
            ).classes('text-[11px] text-slate-400 max-w-2xl leading-relaxed')


def create_home_page() -> None:
    """Render the landing page: content hero, then the reference sections."""
    ui.page_title('Online FIR Portal · Government of Karnataka')
    create_public_header(
        show_language_switcher=True,
        nav_sections=SECTIONS,
        show_staff_link=False,
    )

    with ui.column().classes('w-full gap-0 bg-[#F8FAFC]'):
        _render_hero()
        _render_steps()
        _render_services()
        _render_access()
        _render_footer()

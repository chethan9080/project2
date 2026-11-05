"""
Handcrafted Layout System for e-FIR Law Enforcement Portal
Inspired by classic Japanese animated fantasy artwork:
Watercolor paper texture, soft pastoral glow, and organic sketchbook containers.
Enhanced with Web & iOS Mobile Safe Areas, PWA Manifest, and Viewport Meta Tags.
"""

from contextlib import contextmanager
from collections.abc import Generator

from nicegui import ui

from frontend.components.navbar import create_topbar
from frontend.components.sidebar import create_sidebar
from frontend.components.styles import COLORS, TYPOGRAPHY

# Global Head HTML for PWA & iOS Mobile Optimization
GLOBAL_IOS_PWA_HEAD = """
<link rel="manifest" href="/static/manifest.json">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="e-FIR Sanctuary">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

    body {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
        background-color: #F5EBE0;
        background-image: 
            radial-gradient(circle at 15% 15%, rgba(132, 169, 140, 0.15), transparent 45%),
            radial-gradient(circle at 85% 85%, rgba(224, 122, 95, 0.10), transparent 45%),
            radial-gradient(circle at 50% 50%, rgba(255, 253, 247, 0.8), rgba(245, 235, 224, 0.95));
        background-attachment: fixed;
        color: #2A302E;
        padding-top: env(safe-area-inset-top);
        padding-bottom: env(safe-area-inset-bottom);
        padding-left: env(safe-area-inset-left);
        padding-right: env(safe-area-inset-right);
        -webkit-tap-highlight-color: transparent;
    }

    .fantasy-title {
        font-family: 'Georgia', 'Cinzel', serif;
        letter-spacing: -0.015em;
    }

    .paper-card {
        background: linear-gradient(135deg, #FFFDF7 0%, #F5EBE0 100%);
        border: 2px solid rgba(82, 121, 111, 0.22);
        box-shadow: 0 10px 30px rgba(45, 90, 63, 0.07);
        border-radius: 1.25rem;
        transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
    }

    .paper-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 14px 36px rgba(45, 90, 63, 0.12);
        border-color: rgba(45, 90, 63, 0.35);
    }

    .organic-badge {
        border-radius: 9999px;
        padding: 0.25rem 0.85rem;
        font-weight: 600;
        font-size: 0.75rem;
        letter-spacing: 0.03em;
    }

    /* iOS Mobile Viewport Safe Inset Tweaks */
    @media (max-width: 768px) {
        .nicegui-content {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
        }
    }
</style>
"""

# Register head metadata
ui.add_head_html(GLOBAL_IOS_PWA_HEAD, shared=True)


@contextmanager
def portal_page(portal: str, active_path: str, title: str, subtitle: str = '') -> Generator[None, None, None]:
    """Create the handcrafted navigation shell around a portal page."""
    ui.page_title(f'{title} | e-FIR Portal')

    # Topbar & Sidebar Navigation
    create_topbar(f'e-FIR • {portal.title()} Portal')
    create_sidebar(portal, active_path)

    # Main content canvas with organic rounded container
    with ui.column().classes('w-full max-w-7xl mx-auto gap-6 p-4 md:p-8 pb-16 rounded-3xl flex flex-col').style(
        'background: linear-gradient(135deg, rgba(255,253,247,0.92) 0%, rgba(245,235,224,0.85) 100%); '
        'border: 2px solid rgba(82,121,111,0.2); '
        'box-shadow: 0 12px 40px rgba(45,90,63,0.08);'
    ):
        # Page Title Banner
        with ui.row().classes('w-full items-center justify-between border-b pb-4').style('border-color: rgba(82,121,111,0.2)'):
            with ui.column().classes('gap-1'):
                ui.label(title).classes('text-2xl md:text-4xl font-bold text-[#1F3A2B] fantasy-title')
                if subtitle:
                    ui.label(subtitle).classes('text-xs md:text-base text-[#52796F]')

        yield


@contextmanager
def magical_workspace():
    """Create the handcrafted studio workspace layout"""
    with ui.column().classes('flex-1 overflow-hidden'):
        yield
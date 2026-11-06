"""
Main Application Entry Point for Blockchain-Based Online FIR Platform.
Starts the NiceGUI Web Application and mounts the FastAPI REST API layer.
"""

import os

from dotenv import load_dotenv

# Operator secrets (STORAGE_SECRET, VALIDATOR_PRIVATE_KEY, TEST_MODE) live in the gitignored .env.
load_dotenv()

from nicegui import ui, app as nicegui_app, run
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from frontend.i18n import set_language  # ensure i18n is loaded


from backend.api import api_router
from frontend.pages.home import create_home_page
from frontend.pages import admin, citizen, chat, login, police, register, staff_login, verification, citizen_verification, citizen_application_status, citizen_activation, authorized_officer_ng, officer_audit
from backend.services.db import init_database
from backend.services.seed_data import seed_database
from backend.services.staff_accounts import ensure_seed_staff_accounts

# Initialize database and populate seed data if empty
init_database()
seed_database()

_staff = ensure_seed_staff_accounts()
if _staff['created'] or _staff['existing']:
    print(
        f"[startup] staff accounts: {len(_staff['created'])} created, "
        f"{len(_staff['existing'])} already provisioned"
    )
if _staff['skipped']:
    print(
        f"[startup] staff accounts {', '.join(_staff['skipped'])} not provisioned: "
        "set SEED_OFFICER_PASSWORD to enable seeding"
    )

# Register the landing page
ui.page('/')(create_home_page)

# Mount shared REST API router on FastAPI backend
nicegui_app.include_router(api_router)

# Mount static directory for PWA manifest & service worker
static_dir = os.path.join(os.path.dirname(__file__), 'frontend', 'static')
if os.path.exists(static_dir):
    nicegui_app.mount('/static', StaticFiles(directory=static_dir), name='static')

# Configure CORS for mobile & external requests
nicegui_app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


def configure_runtime() -> None:
    original_setup = run.setup

    def setup_with_fallback() -> None:
        try:
            original_setup()
        except PermissionError:
            run.process_pool = None

    run.setup = setup_with_fallback


def start_application(port: int = None) -> None:
    configure_runtime()
    selected_port = port or int(os.getenv('PORT', '8081'))
    storage_secret = (os.getenv('STORAGE_SECRET') or '').strip()
    if not storage_secret:
        raise RuntimeError(
            'STORAGE_SECRET is not set, so signed login sessions cannot be created. '
            'Generate a key and keep it out of version control:\n'
            '  python -c "import secrets; print(\'STORAGE_SECRET=\' + secrets.token_hex(32))" >> .env'
        )
    ui.run(
        title='Online FIR Portal · Blockchain Tamper-Evident Platform',
        favicon='⚖️',
        reload=False,
        port=selected_port,
        storage_secret=storage_secret,
    )


if __name__ in {'__main__', '__mp_main__'}:
    start_application()

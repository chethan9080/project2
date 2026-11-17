"""
Custom 404 Error Page for eKSP Online FIR Portal.
Renders an accessible, official government-styled error response with Home and Login links,
ensuring raw HTTPException traces are never exposed to citizens or visitors.
"""

import html
import logging
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

logger = logging.getLogger('portal.errors')


def render_404_html(path: str) -> str:
    safe_path = html.escape(path or '')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>404 — Page Not Found | Online FIR Portal · Government of Karnataka</title>
    <link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>⚖️</text></svg>">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #0A192F 0%, #1B365D 50%, #0D244D 100%);
            color: #F8FAFC;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem 1rem;
        }}
        .fantasy-title {{
            font-family: 'Cinzel', 'Georgia', serif;
            letter-spacing: -0.015em;
        }}
        .card {{
            background: rgba(255, 253, 247, 0.98);
            color: #0F172A;
            border: 2px solid rgba(217, 119, 6, 0.35);
            box-shadow: 0 20px 45px rgba(10, 25, 47, 0.45);
            border-radius: 1.5rem;
            max-width: 38rem;
            width: 100%;
            padding: 2.5rem 2rem;
            text-align: center;
            margin: auto;
        }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: #FEF3C7;
            color: #92400E;
            font-weight: 800;
            font-size: 0.85rem;
            padding: 0.4rem 1rem;
            border-radius: 9999px;
            margin-bottom: 1.25rem;
            border: 1px solid #FDE68A;
        }}
        h1 {{
            font-size: 2.25rem;
            font-weight: 800;
            color: #0F2B5C;
            margin-bottom: 0.5rem;
            line-height: 1.2;
        }}
        .multilingual {{
            font-size: 1rem;
            font-weight: 600;
            color: #475569;
            margin-bottom: 1.25rem;
        }}
        p.desc {{
            font-size: 0.95rem;
            color: #334155;
            line-height: 1.6;
            margin-bottom: 1.5rem;
        }}
        .path-box {{
            background: #F1F5F9;
            border: 1px solid #CBD5E1;
            border-radius: 0.75rem;
            padding: 0.6rem 0.9rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.85rem;
            color: #64748B;
            word-break: break-all;
            margin-bottom: 1.75rem;
        }}
        .button-group {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            justify-content: center;
        }}
        .btn {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
            padding: 0.75rem 1.35rem;
            font-size: 0.9rem;
            font-weight: 700;
            border-radius: 0.85rem;
            text-decoration: none;
            transition: all 0.2s ease;
            cursor: pointer;
            border: none;
        }}
        .btn-primary {{
            background: #D97706;
            color: #0F172A;
            box-shadow: 0 4px 12px rgba(217, 119, 6, 0.35);
        }}
        .btn-primary:hover {{
            background: #B45309;
            color: #FFFFFF;
            transform: translateY(-1px);
        }}
        .btn-secondary {{
            background: #0F2B5C;
            color: #FFFFFF;
            box-shadow: 0 4px 12px rgba(15, 43, 92, 0.25);
        }}
        .btn-secondary:hover {{
            background: #091D3E;
            transform: translateY(-1px);
        }}
        .btn-outline {{
            background: transparent;
            color: #0F2B5C;
            border: 1.5px solid #CBD5E1;
        }}
        .btn-outline:hover {{
            background: #F8FAFC;
            border-color: #94A3B8;
        }}
        footer {{
            text-align: center;
            font-size: 0.78rem;
            color: #94A3B8;
            margin-top: 2rem;
            line-height: 1.5;
        }}
        @media (max-width: 640px) {{
            .card {{
                padding: 1.75rem 1.25rem;
            }}
            h1 {{
                font-size: 1.75rem;
            }}
            .button-group {{
                flex-direction: column;
            }}
            .btn {{
                width: 100%;
            }}
        }}
    </style>
</head>
<body>
    <header style="margin-bottom: 1.5rem; text-align: center;">
        <div style="display: flex; align-items: center; justify-content: center; gap: 0.6rem;">
            <span style="font-size: 1.75rem;">⚖️</span>
            <div>
                <div class="fantasy-title" style="font-size: 1.2rem; font-weight: 700; color: #FFFFFF; letter-spacing: 0.05em;">Digital FIR Portal</div>
                <div style="font-size: 0.72rem; color: #FDE68A; text-transform: uppercase; letter-spacing: 0.12em;">Government of Karnataka · Law Enforcement</div>
            </div>
        </div>
    </header>

    <main class="card">
        <div class="badge">
            <span>⚠</span>
            <span>ERROR 404</span>
        </div>
        
        <h1 class="fantasy-title">Page Not Found</h1>
        <div class="multilingual">ಪುಟ ಕಂಡುಬಂದಿಲ್ಲ · पृष्ठ नहीं मिला</div>
        
        <p class="desc">
            The page, document or resource you requested could not be found. 
            It may have been moved, renamed, or requires authorized sign-in.
        </p>

        <div class="path-box">
            Requested URL: {safe_path}
        </div>

        <div class="button-group">
            <a href="/" class="btn btn-primary">
                <span>🏛</span>
                <span>Return to Home</span>
            </a>
            <a href="/login" class="btn btn-secondary">
                <span>👤</span>
                <span>Citizen Login</span>
            </a>
            <a href="/citizen/application-status" class="btn btn-outline">
                <span>📋</span>
                <span>Track Status</span>
            </a>
        </div>
    </main>

    <footer>
        Online FIR Portal · Digital Law Enforcement Platform<br>
        Verified by Karnataka State Police · Tamper-Evident Ledger
    </footer>
</body>
</html>"""


async def handle_404_error(request: Request, exc: Exception) -> HTMLResponse | JSONResponse:
    """Safe, structured 404 handler that prevents raw HTTPException leakage."""
    path = request.url.path
    client_host = request.client.host if request.client else "unknown"
    logger.warning(f"[404 Not Found] {request.method} {path} from client {client_host}")

    if path.startswith("/api/"):
        return JSONResponse(
            {
                "status": 404,
                "error": "Not Found",
                "message": f"API endpoint '{path}' does not exist.",
            },
            status_code=404,
        )

    return HTMLResponse(content=render_404_html(path), status_code=404)

"""
Design System for e-FIR Law Enforcement Portal
Inspired by classic Japanese animated fantasy artwork:
Pastoral forest greens, soft sage, warm cream, paper beige, gentle sky blues, and organic paper surfaces.
"""

# Unified Global Color System
COLORS = {
    'primary': '#2D5A3F',          # Pastoral Forest Green
    'primary-dark': '#1F3A2B',     # Deep Forest Green
    'secondary': '#52796F',        # Moss Green
    'sage': '#84A98C',             # Soft Sage
    'sky': '#70A288',              # Sky Blue-Green
    'cloud': '#E0F2F1',            # Soft Cloud Tint
    'cream': '#FFFDF7',            # Warm Cream
    'paper': '#F5EBE0',            # Paper Beige
    'paper-dark': '#EBE0D0',       # Soft Weathered Paper
    'earth': '#6B4D3E',            # Earth Brown
    'terracotta': '#E07A5F',       # Muted Terracotta Red
    'gold': '#D97706',             # Soft Sunlight Gold
    'citizen': '#2D5A3F',          # Pastoral Green for Citizen Portal
    'police': '#3B5998',           # Deep Gentle Blue for Police Portal
    'admin': '#6B4D3E',            # Warm Earth Brown for Admin Portal
    'text-main': '#2A302E',        # Soft Charcoal Text
    'text-muted': '#5C6B66',       # Muted Moss Text
}

# Unified Typography Tokens
TYPOGRAPHY = {
    'font-family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    'heading': {
        'font-family': 'Georgia, "Times New Roman", serif',
        'font-weight': '700',
        'letter-spacing': '-0.015em'
    },
    'body': {
        'font-family': '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        'font-weight': '400',
        'line-height': '1.6'
    },
    'decorative': {
        'heading_font': 'Georgia, "Times New Roman", serif'
    }
}

# Component Surfaces & Cards
COMPONENTS = {
    'card': {
        'border-radius': '1.25rem',
        'padding': '1.5rem',
        'border': '2px solid rgba(82, 121, 111, 0.18)',
        'background': 'linear-gradient(135deg, #FFFDF7 0%, #F5EBE0 100%)',
        'shadow': '0 8px 24px rgba(45, 90, 63, 0.06)'
    },
    'button': {
        'border-radius': '0.75rem',
        'padding': '0.625rem 1.25rem',
        'font-weight': '600'
    },
    'input': {
        'border-radius': '0.75rem',
        'padding': '0.625rem 1rem',
        'border': '2px solid rgba(82, 121, 111, 0.25)',
        'background': '#FFFDF7'
    }
}

# Organic Status Colors
STATUS_COLORS = {
    'submitted': '#D97706',           # Sunlight Gold
    'under_review': '#3B5998',        # Soft Blue
    'approved': '#2D5A3F',            # Pastoral Green
    'rejected': '#E07A5F',            # Muted Terracotta
    'under_investigation': '#52796F', # Moss Green
    'resolved': '#2D5A3F',            # Pastoral Green
    'closed': '#5C6B66'               # Muted Earth
}

# Priority Colors
PRIORITY_COLORS = {
    'high': '#E07A5F',     # Muted Terracotta Red
    'medium': '#D97706',   # Sunlight Gold
    'low': '#52796F'       # Moss Green
}

# Enchanted theme compatibility exports
ENCHANTED_COLORS = {
    'primary': '#2D5A3F',
    'primary_variant': '#1F3A2B',
    'primary_contrast': '#1F3A2B',
    'moss_green': '#52796F',
    'crystal_blue': '#457B9D',
    'golden_honey': '#D97706',
    'cream': '#FFFDF7',
    'paper_cream': '#F5EBE0',
    'status': {
        'under_investigation': '#E0F2F1',
        'under_review': '#E0F2FE',
        'pending': '#FEF3C7',
        'approved': '#D1FAE5',
        'resolved': '#E6F4EA',
        'rejected': '#FEE2E2',
    },
    'priority': {
        'low': {'border': '#84A98C'},
        'medium': {'border': '#D97706'},
        'high': {'border': '#E07A5F'},
    }
}

ENCHANTED_TYPOGRAPHY = TYPOGRAPHY



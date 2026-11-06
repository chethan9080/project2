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


# ==========================================
# GOVTECH SURFACE LAYER (public landing header + landing page)
# ==========================================
# NiceGUI ships no animation runtime, and its class compiler does not emit
# Tailwind breakpoint variants, so the surface language lives here: scroll
# reveals, glassmorphism and the hover lift.
GOVTECH_HEAD = """
<style>
    /* --- glass surfaces --- */
    .glass-card {
        background: rgba(255, 255, 255, .82);
        -webkit-backdrop-filter: blur(12px) saturate(150%);
        backdrop-filter: blur(12px) saturate(150%);
        border: 1px solid rgba(148, 163, 184, .38);
        box-shadow: 0 10px 30px rgba(15, 42, 79, .07);
        transition: box-shadow .38s cubic-bezier(.16, 1, .3, 1), border-color .38s ease, translate .38s cubic-bezier(.16, 1, .3, 1);
    }
    .glass-card:hover {
        /* `translate` is a separate property from the reveal's `transform`,
           so the lift still works on a card that faded up into view. */
        translate: 0 -6px;
        box-shadow: 0 24px 52px rgba(23, 62, 115, .17);
        border-color: rgba(217, 119, 6, .6);
    }
    .glass-dark {
        background: linear-gradient(150deg, rgba(10, 25, 47, .92) 0%, rgba(23, 49, 84, .86) 100%);
        -webkit-backdrop-filter: blur(14px) saturate(140%);
        backdrop-filter: blur(14px) saturate(140%);
        border: 1px solid rgba(148, 197, 255, .22);
        box-shadow: 0 22px 60px rgba(2, 12, 27, .45);
        transition: box-shadow .38s cubic-bezier(.16, 1, .3, 1), border-color .38s ease, translate .38s cubic-bezier(.16, 1, .3, 1);
    }
    .glass-dark:hover {
        translate: 0 -6px;
        border-color: rgba(251, 191, 36, .55);
        box-shadow: 0 26px 64px rgba(2, 12, 27, .55);
    }
    /* Section kickers: the small pill above each heading replaces the old rule. */
    .kicker-badge {
        background: #DBEAFE;
        color: #1E3A8A;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .08em;
        text-transform: uppercase;
        border-radius: 9999px;
        padding: .3rem .8rem;
    }
    .gov-step-orb {
        background: linear-gradient(135deg, #0A192F 0%, #1B365D 100%);
        box-shadow: 0 6px 16px rgba(10, 25, 47, .25);
        transition: transform .38s cubic-bezier(.16, 1, .3, 1);
    }
    .glass-card:hover .gov-step-orb { transform: scale(1.08) rotate(-4deg); }

    /* --- CTA glow sweep --- */
    .cta-glow { position: relative; overflow: hidden; transition: transform .3s ease, box-shadow .3s ease; }
    .cta-glow::after {
        content: ''; position: absolute; top: 0; right: 0; bottom: 0; left: 0;
        background: linear-gradient(115deg, transparent 25%, rgba(255,255,255,.6) 50%, transparent 75%);
        transform: translateX(-130%); transition: transform .75s ease; pointer-events: none;
    }
    .cta-glow:hover::after { transform: translateX(130%); }
    .cta-glow:hover {
        transform: translateY(-2px);
        /* Quasar owns the inline shadow, so the lift glow has to outrank it. */
        box-shadow: 0 16px 34px rgba(251, 191, 36, .34) !important;
    }
    .cta-glow:focus-visible, .glass-card:focus-visible {
        outline: 2px solid #FCD34D; outline-offset: 3px;
    }

    /* --- sticky glass header --- */
    .nav-glass { transition: background-color .45s ease, box-shadow .45s ease; }
    .nav-glass.is-scrolled {
        background: rgba(10, 25, 47, .78) !important;
        -webkit-backdrop-filter: blur(16px) saturate(150%);
        backdrop-filter: blur(16px) saturate(150%);
        box-shadow: 0 10px 34px rgba(2, 12, 27, .4);
    }

    /* --- scroll reveal --- */
    .reveal {
        opacity: 0;
        transform: translate3d(0, 34px, 0);
        transition-property: opacity, transform, translate, box-shadow, border-color;
        transition-duration: .75s, .75s, .38s, .38s, .38s;
        transition-timing-function: ease, cubic-bezier(.16, 1, .3, 1), cubic-bezier(.16, 1, .3, 1), ease, ease;
        transition-delay: var(--reveal-delay, 0ms), var(--reveal-delay, 0ms), 0ms, 0ms, 0ms;
    }
    .reveal.is-visible { opacity: 1; transform: none; }

    @media (prefers-reduced-motion: reduce) {
        .reveal { opacity: 1; transform: none; transition: none; }
        .glass-card, .glass-card:hover, .cta-glow, .cta-glow:hover {
            transition: none; transform: none; translate: none;
        }
    }
</style>
<script>
    (function () {
        var reduceMotion = function () {
            return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        };
        var reveal = function (nodes) {
            for (var i = 0; i < nodes.length; i++) { nodes[i].classList.add('is-visible'); }
        };
        var observer = null;

        function watchReveals() {
            var nodes = document.querySelectorAll('.reveal:not(.is-visible)');
            if (!nodes.length) { return; }
            if (reduceMotion() || !window.IntersectionObserver) { reveal(nodes); return; }
            if (!observer) {
                observer = new IntersectionObserver(function (entries) {
                    entries.forEach(function (entry) {
                        if (!entry.isIntersecting) { return; }
                        entry.target.classList.add('is-visible');
                        observer.unobserve(entry.target);
                    });
                }, { threshold: 0.12, rootMargin: '0px 0px -8% 0px' });
            }
            for (var i = 0; i < nodes.length; i++) { observer.observe(nodes[i]); }
        }

        // The header swaps background once the page has scrolled off the hero.
        var bar = null;
        function syncGlass() {
            var node = document.querySelector('.nav-glass');
            if (!node) { bar = null; return; }
            if (node !== bar) { bar = node; }
            node.classList.toggle('is-scrolled', window.pageYOffset > 24);
        }

        function onScroll() {
            syncGlass();
        }

        var queued = false;
        function schedule() {
            if (queued) { return; }
            queued = true;
            requestAnimationFrame(function () { queued = false; watchReveals(); });
        }

        function start() {
            if (!document.body) { setTimeout(start, 60); return; }
            watchReveals();
            syncGlass();
            new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
            window.addEventListener('scroll', onScroll, { passive: true });
            window.addEventListener('resize', onScroll, { passive: true });
            // Watchdog: anything already on screen must never stay transparent.
            setTimeout(function () {
                var nodes = document.querySelectorAll('.reveal:not(.is-visible)');
                Array.prototype.forEach.call(nodes, function (node) {
                    var box = node.getBoundingClientRect();
                    if (box.top < window.innerHeight && box.bottom > 0) { node.classList.add('is-visible'); }
                });
            }, 1200);
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', start);
        } else {
            start();
        }
    })();
</script>
"""


# ==========================================
# SHARED VIEWPORT / SCROLL BEHAVIOUR
# ==========================================
# Injected on the public pages (through the shared header) and on the portal
# pages (through the portal shell), so anchor navigation and the first-screen
# hero sizing behave the same everywhere.
SCROLL_SYSTEM_HEAD = """
<style>
    html {
        scroll-behavior: smooth;
        /* `clip` (not `hidden`) so no ancestor becomes a scroll container —
           `overflow-x: hidden` computes overflow-y to auto and kills sticky. */
        overflow-x: clip;
    }
    body {
        overflow-x: clip;
    }
    @media (prefers-reduced-motion: reduce) {
        html { scroll-behavior: auto; }
        .paper-card, .paper-card:hover { transition: none; transform: none; }
    }
    @media (max-width: 768px) {
        /* A fixed background repaints on every scroll frame on mobile GPUs. */
        body { background-attachment: scroll; }
    }

    /* Full-viewport hero that stops exactly at the bottom of the fixed header.
       The extra 1rem is the top padding NiceGUI gives .nicegui-content. */
    .hero-screen {
        min-height: calc(100vh - var(--header-h, 4.5rem) - 1rem);
        min-height: calc(100svh - var(--header-h, 4.5rem) - 1rem);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }

    /* Anchored sections keep clear of the fixed header when scrolled to. */
    .section-anchor { scroll-margin-top: calc(var(--header-h, 4.5rem) + 1rem); }

    /* NiceGUI's class compiler emits base and hover utilities but not the
       Tailwind sm:/md:/lg: variants, so responsive behaviour lives here. */
    .flow-grid {
        display: grid;
        width: 100%;
        gap: 1rem;
        grid-template-columns: repeat(auto-fit, minmax(var(--flow-min, 16rem), 1fr));
    }
    .flow-grid-tiles { --flow-min: 8.5rem; }
    .flow-grid-services { --flow-min: 14rem; }
    .flow-grid-cards { --flow-min: 16rem; }
    .flow-grid-wide { --flow-min: 20rem; }
    @media (max-width: 944px) { .hide-compact { display: none !important; } }
    @media (max-width: 599px) { .hide-tight { display: none !important; } }

    /* Phones: the brand and the action cluster each take a full row, so the
       title can never paint over the login button or the language switcher. */
    @media (max-width: 599px) {
        .nav-brand { flex: 1 1 100%; }
        .nav-actions { flex: 1 1 100%; margin-left: 0; }
    }

    @media (max-width: 1023px) {
        .hero-title { font-size: 2rem; line-height: 1.2; }
        .hero-sub { font-size: 1.05rem; line-height: 1.35; }
        .hero-lede { font-size: 0.92rem; line-height: 1.6; }
        .section-title { font-size: 1.35rem; line-height: 1.3; }
    }
    @media (min-width: 1024px) {
        .hero-title { font-size: 3rem; line-height: 1.15; }
        .hero-sub { font-size: 1.45rem; line-height: 1.3; }
        .hero-lede { font-size: 1.05rem; line-height: 1.65; }
        .section-title { font-size: 1.75rem; line-height: 1.25; }
    }
</style>
<script>
    (function () {
        var header = null;
        var observer = null;
        var queued = false;

        function measure(node) {
            document.documentElement.style.setProperty('--header-h', (node.offsetHeight || 0) + 'px');
        }

        function sync() {
            queued = false;
            var node = document.querySelector('.q-header');
            if (!node) { return; }
            if (node === header) { measure(node); return; }
            header = node;
            if (observer) { observer.disconnect(); }
            measure(node);
            if (window.ResizeObserver) {
                observer = new ResizeObserver(function () { measure(node); });
                observer.observe(node);
            }
        }

        function schedule() {
            if (queued) { return; }
            queued = true;
            requestAnimationFrame(sync);
        }

        // A page-level navigation replaces the header element, so watch for the swap.
        function start() {
            schedule();
            if (!document.body) { setTimeout(start, 50); return; }
            new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
            window.addEventListener('resize', schedule);
            window.addEventListener('orientationchange', schedule);
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', start);
        } else {
            start();
        }

        // Scroll to the nth landing section, keeping its heading below the header.
        window.scrollToSection = function (index) {
            var sections = document.querySelectorAll('.section-anchor');
            var target = sections[index < 0 ? 0 : index];
            if (!target) { return false; }
            var bar = document.querySelector('.q-header');
            var offset = (bar ? bar.offsetHeight : 0) + 12;
            var top = target.getBoundingClientRect().top + window.pageYOffset - offset;
            var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            window.scrollTo({ top: top > 0 ? top : 0, behavior: reduce ? 'auto' : 'smooth' });
            return true;
        };
    })();
</script>
"""



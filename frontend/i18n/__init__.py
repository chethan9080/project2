"""
Internationalization (i18n) Module.
Provides centralized translation and global language switching across the entire application.
Supported Languages:
- en: English (Default)
- kn: ಕನ್ನಡ (Kannada)
- hi: हिन्दी (Hindi)
"""

import json
import os
import re
from typing import Dict, Any, Union
from nicegui import ui, app
from nicegui.element import Element
from nicegui.elements.mixins.text_element import TextElement

_TRANSLATIONS_DIR = os.path.join(os.path.dirname(__file__), 'translations')
_loaded: Dict[str, Dict[str, str]] = {}
_file_mtimes: Dict[str, float] = {}
SUPPORTED_LANGUAGES = ('en', 'kn', 'hi')


def _clean_postprocess(text: str, lang: str) -> str:
    """Eliminate all remaining English abbreviations and terms from Kannada and Hindi translations."""
    if not text or not isinstance(text, str):
        return text or ''
    if lang == 'kn':
        text = re.sub(r'e-FIR|eFIR', 'ಇ-ಎಫ್‌ಐಆರ್', text, flags=re.I)
        text = re.sub(r'FIRಗಳು|FIRs', 'ಎಫ್‌ಐಆರ್‌ಗಳು', text)
        text = re.sub(r'FIRಗೆ', 'ಎಫ್‌ಐಆರ್‌ಗೆ', text)
        text = re.sub(r'FIRಯನ್ನು', 'ಎಫ್‌ಐಆರ್ ಅನ್ನು', text)
        text = re.sub(r'FIRನಲ್ಲಿ', 'ಎಫ್‌ಐಆರ್‌ನಲ್ಲಿ', text)
        text = re.sub(r'FIRನ', 'ಎಫ್‌ಐಆರ್‌ನ', text)
        text = re.sub(r'\bFIR\b', 'ಎಫ್‌ಐಆರ್', text)
        text = re.sub(r'Bengaluru Urban', 'ಬೆಂಗಳೂರು ನಗರ', text, flags=re.I)
        text = re.sub(r'Bengaluru Rural', 'ಬೆಂಗಳೂರು ಗ್ರಾಮಾಂತರ', text, flags=re.I)
        text = re.sub(r'Indiranagar', 'ಇಂದಿರಾನಗರ', text, flags=re.I)
        text = re.sub(r'Koramangala', 'ಕೋರಮಂಗಲ', text, flags=re.I)
        text = re.sub(r'Cyber Crime', 'ಸೈಬರ್ ಅಪರಾಧ', text, flags=re.I)
        text = text.replace(' & ', ' ಮತ್ತು ')
        text = text.replace('ADMIN ONLY', 'ಕೇವಲ ನಿರ್ವಾಹಕರಿಗೆ')
        text = text.replace('AUTHORIZED OFFICER ONLY', 'ಅಧಿಕೃತ ಅಧಿಕಾರಿಗೆ ಮಾತ್ರ')
    elif lang == 'hi':
        text = re.sub(r'e-FIR|eFIR', 'ई-प्राथमिकी', text, flags=re.I)
        text = re.sub(r'FIRें|FIRs', 'प्राथमिकियां', text)
        text = re.sub(r'FIRों', 'प्राथमिकियों', text)
        text = re.sub(r'\bFIR\b', 'प्राथमिकी', text)
        text = re.sub(r'Bengaluru Urban', 'बेंगलुरु शहरी', text, flags=re.I)
        text = re.sub(r'Bengaluru Rural', 'बेंगलुरु ग्रामीण', text, flags=re.I)
        text = re.sub(r'Indiranagar', 'इंदिरानगर', text, flags=re.I)
        text = re.sub(r'Koramangala', 'कोरमंगला', text, flags=re.I)
        text = re.sub(r'Cyber Crime', 'साइबर अपराध', text, flags=re.I)
        text = text.replace(' & ', ' और ')
        text = text.replace('ADMIN ONLY', 'केवल व्यवस्थापक')
        text = text.replace('AUTHORIZED OFFICER ONLY', 'केवल अधिकृत अधिकारी')
    return text


def _load(lang: str) -> Dict[str, str]:
    """Load translations for a language code ('en', 'kn', 'hi') with automatic cache busting on file change."""
    path = os.path.join(_TRANSLATIONS_DIR, f"{lang}.json")
    if not os.path.isfile(path):
        path = os.path.join(_TRANSLATIONS_DIR, "en.json")
        if not os.path.isfile(path):
            return {}
    try:
        mtime = os.path.getmtime(path)
        if lang in _loaded and _file_mtimes.get(lang) == mtime:
            return _loaded[lang]
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _file_mtimes[lang] = mtime
        _loaded[lang] = data
        return data
    except Exception as e:
        print(f"Error loading translation file {path}: {e}")
        return _loaded.get(lang, {})


def get_language() -> str:
    """Get current language from persistent user session storage. Defaults to 'en'."""
    try:
        lang = app.storage.user.get('lang', 'en')
        if lang in SUPPORTED_LANGUAGES:
            return lang
        return 'en'
    except Exception:
        return 'en'


def t(key: Any, default: str = "") -> str:
    """Translate key using current language with intelligent emoji/prefix/count matching."""
    if key is None:
        return ""
    if not isinstance(key, str):
        return str(key)
    if not key:
        return ""

    lang = get_language()
    if lang == 'en':
        return key

    translations = _load(lang)

    # 1. Exact match
    if key in translations:
        return _clean_postprocess(translations[key], lang)

    # 2. Trimmed match
    stripped = key.strip()
    if stripped in translations:
        val = _clean_postprocess(translations[stripped], lang)
        # Preserve original leading/trailing whitespace
        leading = key[:len(key) - len(key.lstrip())]
        trailing = key[len(key.rstrip()):]
        return f"{leading}{val}{trailing}"

    # 3. Strip leading/trailing symbols, emojis, bullets, numbers
    m = re.match(r'^([\s\d\.\-\–\—\:\✦\🔒\📍\🧪\📸\📋\⚡\🔔\🔴\🚨\🛡\🔑\🔍\📲\📱\📌\💬\·\*\#\(\)]*)(.*?)([\s\:\*\.\-\–\—\→\←\✦\💬\(\)\d]*)$', key)
    if m:
        prefix, core, suffix = m.groups()
        core_trimmed = core.strip()
        if core_trimmed and core_trimmed in translations:
            return prefix + _clean_postprocess(translations[core_trimmed], lang) + suffix
        if core_trimmed and core_trimmed.lower() in translations:
            return prefix + _clean_postprocess(translations[core_trimmed.lower()], lang) + suffix

    # 4. Trailing count like 'Notifications (5)' or 'Cases (0)'
    m_count = re.match(r'^(.*?)\s*\((\d+)\)$', stripped)
    if m_count:
        base, count = m_count.groups()
        if base.strip() in translations:
            return f"{_clean_postprocess(translations[base.strip()], lang)} ({count})"

    # 5. Check 'Step X' patterns
    m_step = re.match(r'^(Step|step)\s+(\d+)(.*)$', stripped)
    if m_step:
        _, num, rest = m_step.groups()
        step_word = 'ಹಂತ' if lang == 'kn' else 'चरण'
        rest_trans = t(rest.strip()) if rest.strip() else ""
        return f"{step_word} {num} {rest_trans}".strip()

    # 6. Fallback with comprehensive postprocess (never leave mixed FIR / & / etc.)
    return _clean_postprocess(default or key, lang)


def set_language(lang: str) -> None:
    """Set global language preference in user storage and immediately update page."""
    if lang not in SUPPORTED_LANGUAGES:
        lang = 'en'
    try:
        app.storage.user['lang'] = lang
    except Exception as e:
        print(f"Error saving language to user storage: {e}")
    # Immediately set cookie and reload page without manual browser refresh
    try:
        ui.run_javascript(f"document.cookie = 'app_lang={lang}; path=/; max-age=31536000'; window.location.reload();")
    except Exception as e:
        print(f"Error reloading window: {e}")


# ---------------------------------------------------------------------------
# Automatic UI element translation monkey-patches
# ---------------------------------------------------------------------------

_original_label = ui.label
def _translated_label(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_label(translated, *args, **kwargs)
ui.label = _translated_label

_original_button = ui.button
def _translated_button(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_button(translated, *args, **kwargs)
ui.button = _translated_button

_original_link = ui.link
def _translated_link(text: str = '', target: str = '#', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_link(translated, target, *args, **kwargs)
ui.link = _translated_link

_original_badge = ui.badge
def _translated_badge(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_badge(translated, *args, **kwargs)
ui.badge = _translated_badge

_original_notify = ui.notify
def _translated_notify(key: str = '', *args, **kwargs):
    message = t(key) if key and isinstance(key, str) else key
    return _original_notify(message, *args, **kwargs)
ui.notify = _translated_notify

_original_page_title = ui.page_title
def _translated_page_title(title: str = '', *args, **kwargs):
    translated = t(title) if title and isinstance(title, str) else title
    return _original_page_title(translated, *args, **kwargs)
ui.page_title = _translated_page_title

_original_input = ui.input
def _translated_input(*args, **kwargs):
    new_args = list(args)
    if new_args and isinstance(new_args[0], str):
        new_args[0] = t(new_args[0])
    elif 'label' in kwargs and isinstance(kwargs['label'], str):
        kwargs['label'] = t(kwargs['label'])
    if 'placeholder' in kwargs and isinstance(kwargs['placeholder'], str):
        kwargs['placeholder'] = t(kwargs['placeholder'])
    return _original_input(*new_args, **kwargs)
ui.input = _translated_input

_original_textarea = ui.textarea
def _translated_textarea(*args, **kwargs):
    new_args = list(args)
    if new_args and isinstance(new_args[0], str):
        new_args[0] = t(new_args[0])
    elif 'label' in kwargs and isinstance(kwargs['label'], str):
        kwargs['label'] = t(kwargs['label'])
    if 'placeholder' in kwargs and isinstance(kwargs['placeholder'], str):
        kwargs['placeholder'] = t(kwargs['placeholder'])
    return _original_textarea(*new_args, **kwargs)
ui.textarea = _translated_textarea

_original_select = ui.select
def _translated_select(*args, **kwargs):
    new_args = list(args)
    if new_args and isinstance(new_args[0], (list, tuple)):
        if all(isinstance(x, str) for x in new_args[0]):
            new_args[0] = {opt: t(opt) for opt in new_args[0]}
    elif 'options' in kwargs and isinstance(kwargs['options'], (list, tuple)):
        if all(isinstance(x, str) for x in kwargs['options']):
            kwargs['options'] = {opt: t(opt) for opt in kwargs['options']}
    elif 'options' in kwargs and isinstance(kwargs['options'], dict):
        kwargs['options'] = {k: t(v) for k, v in kwargs['options'].items()}
    if len(new_args) > 1 and isinstance(new_args[1], str):
        new_args[1] = t(new_args[1])
    elif 'label' in kwargs and isinstance(kwargs['label'], str):
        kwargs['label'] = t(kwargs['label'])
    if 'placeholder' in kwargs and isinstance(kwargs['placeholder'], str):
        kwargs['placeholder'] = t(kwargs['placeholder'])
    return _original_select(*new_args, **kwargs)
ui.select = _translated_select

_original_radio = ui.radio
def _translated_radio(*args, **kwargs):
    new_args = list(args)
    if new_args and isinstance(new_args[0], (list, tuple)):
        if all(isinstance(x, str) for x in new_args[0]):
            new_args[0] = {opt: t(opt) for opt in new_args[0]}
    elif 'options' in kwargs and isinstance(kwargs['options'], (list, tuple)):
        if all(isinstance(x, str) for x in kwargs['options']):
            kwargs['options'] = {opt: t(opt) for opt in kwargs['options']}
    return _original_radio(*new_args, **kwargs)
ui.radio = _translated_radio

_original_checkbox = ui.checkbox
def _translated_checkbox(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_checkbox(translated, *args, **kwargs)
ui.checkbox = _translated_checkbox

_original_switch = ui.switch
def _translated_switch(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_switch(translated, *args, **kwargs)
ui.switch = _translated_switch

_original_step = ui.step
def _translated_step(name: str, title: str = None, *args, **kwargs):
    trans_title = t(title) if title else t(name)
    return _original_step(name, trans_title, *args, **kwargs)
ui.step = _translated_step

_original_tab = ui.tab
def _translated_tab(name: str, label: str = None, icon: str = None, *args, **kwargs):
    trans_label = t(label) if label else t(name)
    return _original_tab(name, trans_label, icon, *args, **kwargs)
ui.tab = _translated_tab

_original_tooltip = ui.tooltip
def _translated_tooltip(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_tooltip(translated, *args, **kwargs)
ui.tooltip = _translated_tooltip

_original_chat_message = ui.chat_message
def _translated_chat_message(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    return _original_chat_message(translated, *args, **kwargs)
ui.chat_message = _translated_chat_message

_original_expansion = ui.expansion
def _translated_expansion(text: str = '', *args, **kwargs):
    translated = t(text) if text and isinstance(text, str) else text
    if 'caption' in kwargs and isinstance(kwargs['caption'], str):
        kwargs['caption'] = t(kwargs['caption'])
    return _original_expansion(translated, *args, **kwargs)
ui.expansion = _translated_expansion

_original_table = ui.table
def _translated_table(*args, **kwargs):
    if 'columns' in kwargs and isinstance(kwargs['columns'], list):
        for col in kwargs['columns']:
            if isinstance(col, dict) and 'label' in col and isinstance(col['label'], str):
                col['label'] = t(col['label'])
    return _original_table(*args, **kwargs)
ui.table = _translated_table

_orig_set_text = TextElement.set_text
def _translated_set_text(self, text: str):
    trans = t(text) if isinstance(text, str) else text
    return _orig_set_text(self, trans)
TextElement.set_text = _translated_set_text

_orig_element_setattr = Element.__setattr__
def _custom_element_setattr(self, name, value):
    if name == 'text' and isinstance(value, str):
        value = t(value)
    return _orig_element_setattr(self, name, value)
Element.__setattr__ = _custom_element_setattr

__all__ = ['ui', 't', 'set_language', 'get_language', 'SUPPORTED_LANGUAGES']

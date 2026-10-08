"""Localization helpers for standards documents.

Provides ISO 15924 script code lookups, BCP 47 tag construction, and
language-to-direction mapping used in standards document rendering.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# ISO 15924 script codes
# ---------------------------------------------------------------------------

#: Mapping from ISO 639-1 language code to the default ISO 15924 script code.
#: Languages that use the Latin script are *not* listed here — they fall back
#: to ``"Latn"`` via :func:`get_script_code`.
SCRIPT_CODES: dict[str, str] = {
    "ar": "Arab",  # Arabic
    "zh": "Hans",  # Simplified Chinese (default; Traditional = Hant)
    "ja": "Jpan",  # Japanese (Han + Hiragana/Katakana)
    "ko": "Kore",  # Korean (Hangul + Han)
    "ru": "Cyrl",  # Russian / Cyrillic
    "uk": "Cyrl",  # Ukrainian
    "bg": "Cyrl",  # Bulgarian
    "sr": "Cyrl",  # Serbian (Cyrillic)
    "he": "Hebr",  # Hebrew
    "hi": "Deva",  # Hindi / Devanagari
    "mr": "Deva",  # Marathi / Devanagari
    "ne": "Deva",  # Nepali / Devanagari
    "th": "Thai",  # Thai
    "ka": "Geor",  # Georgian
    "am": "Ethi",  # Amharic / Ethiopic
    "el": "Grek",  # Greek
    "fa": "Arab",  # Persian / Arabic script
    "ur": "Arab",  # Urdu / Arabic script
    "yi": "Hebr",  # Yiddish / Hebrew script
    "km": "Khmr",  # Khmer
    "lo": "Laoo",  # Lao
    "my": "Mymr",  # Burmese / Myanmar
    "si": "Sinh",  # Sinhala
    "ta": "Taml",  # Tamil
    "te": "Telu",  # Telugu
    "kn": "Knda",  # Kannada
    "ml": "Mlym",  # Malayalam
    "gu": "Gujr",  # Gujarati
    "pa": "Guru",  # Punjabi / Gurmukhi
    "bn": "Beng",  # Bengali
    "hy": "Armn",  # Armenian
    "mn": "Cyrl",  # Mongolian (default Cyrillic script in modern use)
    "ti": "Ethi",  # Tigrinya / Ethiopic
}


def get_script_code(lang: str) -> str:
    """Return the ISO 15924 script code for a language.

    For languages not in :data:`SCRIPT_CODES`, returns ``"Latn"`` (Latin
    script, the most common script for languages not explicitly listed).

    Args:
        lang: ISO 639-1 language code (e.g. ``"ar"``, ``"zh"``, ``"en"``).

    Returns:
        ISO 15924 four-letter script code (e.g. ``"Arab"``, ``"Hans"``,
        ``"Latn"``).

    Examples::

        >>> get_script_code("ar")
        'Arab'
        >>> get_script_code("en")
        'Latn'
        >>> get_script_code("zh")
        'Hans'
    """
    return SCRIPT_CODES.get(lang, "Latn")


# ---------------------------------------------------------------------------
# BCP 47 tag helpers
# ---------------------------------------------------------------------------


def get_bcp47_tag(lang: str, script: str | None = None) -> str:
    """Return a BCP 47 language tag, appending the script subtag only when needed.

    The script subtag is omitted when *script* is the default script for
    *lang* (per :data:`SCRIPT_CODES`), following the BCP 47 principle of
    omitting redundant subtags.

    Args:
        lang: ISO 639-1 language code (e.g. ``"zh"``, ``"en"``).
        script: ISO 15924 script code, or ``None`` to omit the script
            subtag entirely.

    Returns:
        BCP 47 tag string, e.g. ``"zh-Hant"``, ``"zh"``, ``"en"``.

    Examples::

        >>> get_bcp47_tag("en")
        'en'
        >>> get_bcp47_tag("zh", "Hant")
        'zh-Hant'
        >>> get_bcp47_tag("zh", "Hans")
        'zh'
        >>> get_bcp47_tag("ar", "Arab")
        'ar'
    """
    if script is None:
        return lang

    default_script = get_script_code(lang)
    if script == default_script:
        # Script is the default for this language — omit it (BCP 47 §4.1)
        return lang

    return f"{lang}-{script}"


# ---------------------------------------------------------------------------
# RTL language detection
# ---------------------------------------------------------------------------

#: Language codes that use right-to-left base direction.
RTL_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur", "yi", "dv", "ps"})


def is_rtl(lang: str) -> bool:
    """Return ``True`` if *lang* is a right-to-left language.

    Args:
        lang: ISO 639-1 language code.

    Returns:
        ``True`` for Arabic, Hebrew, Persian, Urdu, Yiddish, Divehi, and
        Pashto; ``False`` for all others.
    """
    return lang in RTL_LANGS

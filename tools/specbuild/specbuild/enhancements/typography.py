"""Smart typography: curly quotes, em-dashes, ellipsis, non-breaking spaces."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TYPOGRAPHY_ENABLED_DEFAULT = True

# Tags whose text content must not be touched
_SKIP_TAGS = frozenset({"pre", "code", "script", "style", "math", "svg"})

# ---------------------------------------------------------------------------
# Substitution helpers
# ---------------------------------------------------------------------------

# Straight double-quote → open/close detection.
# Open: preceded by start-of-string, whitespace, or opening punctuation.
# Using a lookbehind so the preceding char is NOT consumed.
_OPEN_DQUOTE_RE = re.compile(r'(?:(?<=[\s(\[{])|(?:^))"(?=\S)', re.MULTILINE)
# Close: preceded by non-whitespace, followed by whitespace, punctuation, or end.
_CLOSE_DQUOTE_RE = re.compile(r'(?<=\S)"(?=[\s)\]},.:;!?]|$)', re.MULTILINE)

# Single open/close quote around a word: 'word' (not contractions).
# Open: preceded by start-of-string, whitespace, or opening punctuation.
_OPEN_SQUOTE_RE = re.compile(r"(?:(?<=[\s(\[{])|^)'(?=\S)", re.MULTILINE)
# Close: preceded by non-whitespace, followed by whitespace, punctuation, or end.
_CLOSE_SQUOTE_RE = re.compile(r"(?<=\S)'(?=[\s)\]},.:;!?]|$)", re.MULTILINE)

# Apostrophe in contractions and possessives: n't, 's, 'd, 'll, 've, 're, 'm
_APOSTROPHE_RE = re.compile(r"([A-Za-z])'([A-Za-z])")

# Em-dash patterns
_SPACED_DASH_RE = re.compile(r" -- ")
_WORDWORD_DASH_RE = re.compile(r"(\w)--(\w)")

# Ellipsis
_ELLIPSIS_RE = re.compile(r"\.\.\.")

# Multiplication: digit × digit (handles optional whitespace)
_MULTIPLY_RE = re.compile(r"(\d)\s*[xX]\s*(\d)")

# Non-breaking space before French punctuation
_FRENCH_PUNCT_RE = re.compile(r" ([:;?!])")


def _apply_typography(text: str, french_spacing: bool = False) -> str:
    """Apply all typographic substitutions to a plain text string.

    Args:
        text: Raw text content to transform.
        french_spacing: If True, insert non-breaking spaces before :;?!

    Returns:
        Transformed text with smart typography applied.
    """
    # 1. Straight double-quotes → curly open/close
    # Open quote: preceded by start/space/open-paren (lookbehind, no capture)
    text = _OPEN_DQUOTE_RE.sub("\u201c", text)
    # Close quote: followed by space/punct/end (lookahead, no capture)
    text = _CLOSE_DQUOTE_RE.sub("\u201d", text)
    # Any remaining straight double quotes → close quote (conservative fallback)
    text = text.replace('"', "\u201d")

    # 2. Apostrophes in contractions / possessives (before single quotes)
    text = _APOSTROPHE_RE.sub(lambda m: m.group(1) + "\u2019" + m.group(2), text)

    # 3. Single quotes around words → open/close
    text = _OPEN_SQUOTE_RE.sub("\u2018", text)
    text = _CLOSE_SQUOTE_RE.sub("\u2019", text)

    # 4. Spaced double-hyphen → em-dash with spaces
    text = _SPACED_DASH_RE.sub(" \u2014 ", text)

    # 5. Word--word → em-dash without spaces
    text = _WORDWORD_DASH_RE.sub(lambda m: m.group(1) + "\u2014" + m.group(2), text)

    # 6. Ellipsis
    text = _ELLIPSIS_RE.sub("\u2026", text)

    # 7. Non-breaking space before French punctuation (optional)
    if french_spacing:
        text = _FRENCH_PUNCT_RE.sub(lambda m: "\u00a0" + m.group(1), text)

    # 8. Multiplication sign: digit x digit → digit × digit
    text = _MULTIPLY_RE.sub(lambda m: m.group(1) + "\u00d7" + m.group(2), text)

    return text


# ---------------------------------------------------------------------------
# Soup-level transformer
# ---------------------------------------------------------------------------


def process_typography_soup(
    soup: BeautifulSoup,
    french_spacing: bool = False,
) -> int:
    """Apply smart typography to all prose text nodes in *soup*.

    Scans all text nodes inside ``<body>``, skipping nodes that are
    descendants of ``<pre>``, ``<code>``, ``<script>``, ``<style>``,
    ``<math>``, or ``<svg>``.

    Args:
        soup: BeautifulSoup document (mutated in place).
        french_spacing: If True, insert non-breaking spaces before :;?!

    Returns:
        Number of text nodes that were modified.
    """
    from bs4 import NavigableString

    body = soup.find("body")
    if not body:
        log.debug("No <body> element found; skipping typography pass.")
        return 0

    modified_count = 0
    text_nodes: list[NavigableString] = []

    for node in body.find_all(string=True):
        # Skip descendants of protected tags
        if any(getattr(p, "name", None) in _SKIP_TAGS for p in node.parents if hasattr(p, "name")):
            continue
        text_nodes.append(node)

    for node in text_nodes:
        original = str(node)
        transformed = _apply_typography(original, french_spacing=french_spacing)
        if transformed != original:
            node.replace_with(NavigableString(transformed))
            modified_count += 1

    log.debug("Typography: %d text node(s) modified.", modified_count)
    return modified_count


# ---------------------------------------------------------------------------
# Unit spacing
# ---------------------------------------------------------------------------

# Non-breaking space between a number and an SI/technical unit symbol.
# Units ordered longest-first to prevent partial matches.
_UNIT_RE = re.compile(
    r"(\d)\s+"
    r"(MHz|GHz|kHz|THz|Mbps|Gbps|kbps|Tbps|"
    r"MiB|GiB|KiB|TiB|MB|GB|KB|TB|"
    r"ms|µs|ns|ps|"
    r"km|cm|mm|nm|µm|"
    r"kg|mg|µg|"
    r"kPa|MPa|GPa|"
    r"kW|MW|GW|mW|"
    r"kJ|MJ|GJ|mJ|"
    r"kV|MV|mV|"
    r"kA|mA|µA|"
    r"dB|dBm|dBFS|"
    r"fps|ppi|dpi|"
    r"m/s|km/h|"
    r"lm|lx|cd|"
    r"mol|mmol|"
    r"Hz|Pa|Wb|Gy|Sv|kat|"
    r"rad|sr|"
    r"bit|byte|"
    r"px|pt|em|rem|vw|vh|"
    r"m|s|g|A|K|V|W|J|F|H|\u03a9|"
    r"in|ft|yd|mi|lb|oz|fl oz|gal)"
    r"\b",
)


def inject_unit_spacing_soup(soup: BeautifulSoup) -> int:
    """Insert non-breaking spaces between numbers and unit symbols in prose text.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of text nodes modified.
    """
    from bs4 import NavigableString

    body = soup.find("body")
    if not body:
        return 0

    modified_count = 0
    for node in list(body.find_all(string=True)):
        if any(getattr(p, "name", None) in _SKIP_TAGS for p in node.parents if hasattr(p, "name")):
            continue
        original = str(node)
        transformed = _UNIT_RE.sub(lambda m: m.group(1) + "\u00a0" + m.group(2), original)
        if transformed != original:
            node.replace_with(NavigableString(transformed))
            modified_count += 1

    log.debug("Unit spacing: %d text node(s) modified.", modified_count)
    return modified_count

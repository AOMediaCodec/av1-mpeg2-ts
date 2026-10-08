"""Standard mathematical and technical symbol substitution."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Symbol table
# ---------------------------------------------------------------------------

# Each entry is (ascii_sequence, unicode_replacement, boundary_mode).
# boundary_mode:
#   "space"  — require whitespace (or string boundary) on both sides
#   "paren"  — parenthetical form: only require non-alphanumeric after the
#               closing paren (i.e. (c), (r), (tm) may appear after a word)
#
# Order matters: longer sequences must appear before shorter shared prefixes
# (e.g. "<=>" before "<=", "=>" before "->").
_SYMBOL_TABLE: list[tuple[str, str, str]] = [
    # Must come first — longer sequences before substrings
    ("<=>", "\u21d4", "space"),  # ⇔
    (">=", "\u2265", "space"),  # ≥
    ("<=", "\u2264", "space"),  # ≤
    ("!=", "\u2260", "space"),  # ≠
    ("=>", "\u21d2", "space"),  # ⇒
    # Arrows
    ("->", "\u2192", "space"),  # →
    ("<-", "\u2190", "space"),  # ←
    # Math
    ("+-", "\u00b1", "space"),  # ±
    ("~=", "\u2248", "space"),  # ≈
    # IP / legal — parenthetical form; may appear directly after a word char
    ("(c)", "\u00a9", "paren"),  # ©
    ("(r)", "\u00ae", "paren"),  # ®
    ("(tm)", "\u2122", "paren"),  # ™
]

# Tags whose content must never be modified
_SKIP_TAGS = frozenset(
    {
        "pre",
        "code",
        "script",
        "style",
        "math",
        "svg",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)

# Tags in which substitutions are allowed
_PROSE_TAGS = frozenset(
    {
        "p",
        "li",
        "dd",
        "dt",
        "td",
        "th",
        "figcaption",
        "blockquote",
        "span",
        "div",
        "section",
        "article",
    }
)

# ---------------------------------------------------------------------------
# Regex builder
# ---------------------------------------------------------------------------

# Whitespace-bounded boundary pattern:
#   left side: start-of-string OR preceded by whitespace/punctuation
#   right side: end-of-string OR followed by whitespace/punctuation
_WS_LEFT = r"(?:^|(?<=[\s,.({\[]))"
_WS_RIGHT = r"(?=[\s,.)}\]!?;]|$)"

# Parenthetical boundary: opening paren may be preceded by anything;
# closing paren only requires non-word or end after it.
_PAREN_RIGHT = r"(?=[^\w]|$)"

_WS_LEFT = r"(?:^|(?<=[\s,.({\[]))"
_WS_RIGHT = r"(?=[\s,.)}\]!?;]|$)"

# Parenthetical boundary: opening paren may be preceded by anything;
# closing paren only requires non-word or end after it.
_PAREN_RIGHT = r"(?=[^\w]|$)"

# Pre-compile (ascii_sequence, replacement, regex) triples once at import time.
_COMPILED: list[tuple[str, str, re.Pattern[str]]] = []
for _ascii, _uni, _mode in _SYMBOL_TABLE:
    _pat = re.escape(_ascii)
    if _mode == "paren":
        # No restriction on left side; require word-boundary-like end
        _re = re.compile(_pat + _PAREN_RIGHT)
    else:
        # Require whitespace/punctuation context on both sides
        _re = re.compile(_WS_LEFT + _pat + _WS_RIGHT)
    _COMPILED.append((_ascii, _uni, _re))


# ---------------------------------------------------------------------------
# Soup-level transformer
# ---------------------------------------------------------------------------


def process_math_symbols_soup(soup: BeautifulSoup) -> int:
    """Substitute ASCII symbol sequences with Unicode equivalents in prose.

    Operates only on text nodes inside ``<p>``, ``<li>``, ``<dd>``,
    ``<dt>``, ``<td>``, ``<th>``, and similar prose containers.  Never
    modifies content inside ``<pre>``, ``<code>``, ``<script>``,
    ``<style>``, ``<math>``, ``<svg>``, or heading tags.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Total number of symbol substitutions made across all text nodes.
    """
    from bs4 import NavigableString

    body = soup.find("body")
    if not body:
        log.debug("No <body> element found; skipping math-symbols pass.")
        return 0

    total_substitutions = 0

    for node in list(body.find_all(string=True)):
        # Must be inside a direct prose container
        parent = node.parent
        if parent is None or getattr(parent, "name", None) not in _PROSE_TAGS:
            continue

        # Must not be a descendant of any skip tag
        if any(getattr(p, "name", None) in _SKIP_TAGS for p in node.parents if hasattr(p, "name")):
            continue

        original = str(node)
        result = original
        count = 0

        for _ascii, _uni, _re in _COMPILED:
            new_result, n = _re.subn(_uni, result)
            if n:
                result = new_result
                count += n

        if count:
            node.replace_with(NavigableString(result))
            total_substitutions += count

    log.debug("Math symbols: %d substitution(s) made.", total_substitutions)
    return total_substitutions

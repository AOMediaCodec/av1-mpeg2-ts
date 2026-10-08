"""Requirement keyword highlighter: visually distinguish RFC 2119 keywords."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

# RFC 2119 / RFC 8174 keywords
_RFC_KEYWORDS = [
    "MUST NOT",
    "MUST",
    "SHALL NOT",
    "SHALL",
    "SHOULD NOT",
    "SHOULD",
    "REQUIRED",
    "RECOMMENDED",
    "NOT RECOMMENDED",
    "MAY",
    "OPTIONAL",
]

# Build regex pattern: match keywords that appear in ALL CAPS in prose.
# Use negative lookbehind/ahead for word boundaries and avoid matching
# inside HTML tags or attributes.
_KEYWORD_RE = re.compile(
    r"(?<![A-Z])(" + "|".join(re.escape(kw) for kw in _RFC_KEYWORDS) + r")(?![A-Z])"
)


def highlight_keywords(html_path: Path) -> int:
    """Wrap RFC 2119/8174 keywords in <span class="rfc-keyword"> elements.

    File-based wrapper around :func:`highlight_keywords_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Number of keywords highlighted.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping keyword highlighting")
        return 0

    logging.debug(f"Highlighting RFC 2119 keywords in {html_path.name}")
    soup = read_html(html_path)
    result = highlight_keywords_soup(soup)
    write_html(html_path, soup)
    return result


def highlight_keywords_soup(soup: BeautifulSoup) -> int:
    """Highlight RFC 2119/8174 keywords on a pre-parsed soup object.

    Only processes text inside paragraph-like elements (p, li, dd, td)
    to avoid modifying headings, code blocks, or metadata.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of keywords highlighted.
    """
    from bs4 import NavigableString

    # Only process prose elements
    prose_tags = {"p", "li", "dd", "dt", "td", "th"}
    # Skip elements inside these containers
    skip_parents = {"pre", "code", "script", "style", "mjx-container"}

    count = 0
    # Collect text nodes in a single pass, deduplicating by identity
    seen_nodes = set()
    text_nodes = []

    for text_node in soup.find_all(string=True):
        if id(text_node) in seen_nodes:
            continue
        # Check that nearest element ancestor is a prose tag
        parent = text_node.parent
        if not parent or parent.name not in prose_tags:
            continue
        # Skip if inside code/pre/script
        if any(p.name in skip_parents for p in text_node.parents if hasattr(p, "name")):
            continue
        if _KEYWORD_RE.search(str(text_node)):
            seen_nodes.add(id(text_node))
            text_nodes.append(text_node)

    for text_node in text_nodes:
        original = str(text_node)
        parts = _KEYWORD_RE.split(original)

        if len(parts) <= 1:
            continue

        # Build replacement fragments
        parent = text_node.parent
        if parent is None:
            continue

        new_elements = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Regular text
                if part:
                    new_elements.append(NavigableString(part))
            else:
                # Keyword match — wrap in span
                # Skip if already inside an rfc-keyword span
                if parent.name == "span" and "rfc-keyword" in parent.get("class", []):
                    new_elements.append(NavigableString(part))
                    continue
                span = soup.new_tag("span", **{"class": "rfc-keyword"})
                span.string = part
                new_elements.append(span)
                count += 1

        # Replace the text node with the new fragments
        for new_elem in reversed(new_elements):
            text_node.insert_after(new_elem)
        text_node.extract()

    if count > 0:
        _inject_keyword_css(soup)

    logging.info(f"Highlighted {count} RFC 2119 keywords")
    return count


def _inject_keyword_css(soup: BeautifulSoup) -> None:
    """Inject CSS for RFC keyword highlighting."""
    t = THEME
    css = f"""
/* RFC 2119 Keyword Highlighting */
.rfc-keyword {{
  font-weight: bold;
  font-variant: small-caps;
  font-size: {t.keyword_font_size};
  color: {t.keyword_color};
  letter-spacing: 0.02em;
}}
"""
    inject_css(soup, "rfc-keyword-css", css)

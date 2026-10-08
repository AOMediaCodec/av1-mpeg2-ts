"""Passthrough blocks: raw HTML/XML injection that bypasses sanitization.

Bikeshed and most HTML pipelines sanitize or mangle raw XML.  This module
detects placeholder ``<div>`` elements that carry a ``data-passthrough``
attribute and replaces each one with its raw content verbatim.

Authoring pattern in ``.bs`` source
------------------------------------

Simple passthrough (HTML entities are unescaped and injected directly)::

    <div data-passthrough="true">
      &lt;math xmlns="http://www.w3.org/1998/Math/MathML"&gt;&lt;/math&gt;
    </div>

With a type hint for typed injection::

    <div data-passthrough="math">
      &lt;math xmlns="..."&gt;...&lt;/math&gt;
    </div>

    <div data-passthrough="svg">
      &lt;svg xmlns="..."&gt;...&lt;/svg&gt;
    </div>
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# Passthrough type values that trigger special handling
_TYPE_MATH = "math"
_TYPE_SVG = "svg"


def process_passthrough_soup(soup: BeautifulSoup) -> int:
    """Replace ``<div data-passthrough>`` elements with their raw content.

    For each matching div:

    * The element's text content is HTML-entity-unescaped.
    * If ``data-passthrough="math"``, the unescaped content is wrapped in
      ``<span class="passthrough-math">``.
    * For ``data-passthrough="svg"`` and ``data-passthrough="true"`` (or any
      other value), the content is injected verbatim as a parsed HTML fragment.
    * Empty content divs are left unchanged (counted as 0).

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of passthrough blocks successfully processed.
    """
    from bs4 import BeautifulSoup as BS4
    from bs4 import NavigableString

    divs = soup.find_all("div", attrs={"data-passthrough": True})
    if not divs:
        log.debug("No passthrough blocks found.")
        return 0

    processed = 0
    for div in divs:
        passthrough_type: str = (div.get("data-passthrough") or "true").lower().strip()

        # Retrieve raw text and unescape HTML entities
        raw_text = div.get_text()
        unescaped = html.unescape(raw_text).strip()

        if not unescaped:
            log.debug("Passthrough block is empty — skipping.")
            continue

        if passthrough_type == _TYPE_MATH:
            # Wrap in a span with a distinguishing class by building HTML directly
            wrapped_html = f'<span class="passthrough-math">{unescaped}</span>'
            fragment = BS4(wrapped_html, "html.parser")
            _frag_body = fragment.find("body") or fragment
            _children = list(_frag_body.children)
            if _children:
                for _child in reversed(_children):
                    div.insert_after(_child)
                div.decompose()
            else:
                div.replace_with(NavigableString(unescaped))
        else:
            # "svg", "true", or any other value — inject verbatim
            fragment = BS4(unescaped, "html.parser")
            _frag_body = fragment.find("body") or fragment
            _children = list(_frag_body.children)
            if _children:
                for _child in reversed(_children):
                    div.insert_after(_child)
                div.decompose()
            else:
                div.replace_with(NavigableString(unescaped))

        processed += 1
        log.debug("Passthrough block (type=%r) processed.", passthrough_type)

    log.debug("Passthrough: %d block(s) processed.", processed)
    return processed

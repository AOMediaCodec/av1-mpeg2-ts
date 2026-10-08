"""Table of contents depth control via CSS injection.

Hides ToC entries and section numbers below the configured depth threshold,
giving users a clean multi-level ToC without modifying the HTML structure.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import inject_css


def apply_toc_depth_soup(soup: BeautifulSoup, depth: int = 3) -> bool:
    """Inject CSS that hides ToC entries deeper than *depth*.

    Bikeshed generates a ``<ul>`` ToC with nested ``<li>`` elements.
    Level 1 = top-level h2, level 2 = h3, etc.  A depth of 3 shows
    headings h2–h4 and hides h5/h6 entries.

    Args:
        soup:  Parsed BeautifulSoup document.
        depth: Maximum heading level to show in the ToC (1–6).

    Returns:
        True if CSS was injected, False if nothing to do.
    """
    depth = max(1, min(6, depth))
    if depth >= 6:
        return False

    # Bikeshed ToC structure: #toc > ul > li (h2), each li > ul > li (h3), etc.
    # Build a selector that targets the (depth+1)-th nesting level and hides it.
    selector_parts = ["#toc"]
    for _ in range(depth):
        selector_parts.append("> ul > li")
    selector_parts.append("> ul")
    hide_selector = " ".join(selector_parts)
    css = f"{hide_selector} {{ display: none; }}"

    inject_css(soup, "toc-depth-css", css)
    logging.info(f"ToC depth limited to {depth} level(s)")
    return True

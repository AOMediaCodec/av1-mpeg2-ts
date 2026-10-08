"""Figure source attribution styling.

Detects ``[Source: ...]`` or ``Source:`` text inside ``<figcaption>`` elements
and wraps it in a styled ``<span class="figure-source">`` for distinct rendering.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import inject_css

_SOURCE_CSS = """
/* Figure source attribution */
figcaption .figure-source {
  display: block;
  font-size: 0.88em;
  color: #555;
  margin-top: 0.3em;
  font-style: italic;
}
figcaption .figure-source::before {
  content: "";
}
"""

_SOURCE_RE = re.compile(r"(?i)([\[(\s]?)(Source\s*:\s*)(.+?)(\s*[\])]?\s*)$")
_SOURCE_LINE_RE = re.compile(r"(?i)^(\s*)(Source\s*:\s*)(.+)$")


def process_figure_sources_soup(soup: BeautifulSoup) -> int:
    """Wrap 'Source: ...' attribution text in figcaptions with a styled span.

    Matches patterns like:
    - ``[Source: ISO/IEC 14496-10:2022, Figure 3.1]``
    - ``Source: Author, 2024``

    Returns count of attributions styled.
    """
    from bs4 import NavigableString

    count = 0
    for cap in soup.find_all("figcaption"):
        if cap.find("span", class_="figure-source"):
            continue

        # Walk text nodes looking for source attribution
        for child in list(cap.children):
            if not isinstance(child, NavigableString):
                continue
            text = str(child)
            m = _SOURCE_LINE_RE.search(text)
            if not m:
                m = _SOURCE_RE.search(text)
            if not m:
                continue

            # Split into prefix text and source attribution
            start = m.start()
            prefix = text[:start]
            source_text = text[start:].strip().lstrip("[").rstrip("]").strip()

            span = soup.new_tag("span", **{"class": "figure-source"})
            span.string = source_text

            child.replace_with(NavigableString(prefix))
            cap.append(span)
            count += 1
            break

    if count:
        inject_css(soup, "figure-source-css", _SOURCE_CSS)

    return count

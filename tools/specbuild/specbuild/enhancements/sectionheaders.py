"""Section-aware running headers for PDF generation and §N.N permalink anchors."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

_SECTION_NUM_RE = re.compile(r"^(\d[\d.]*)\s")

_PERMALINK_CSS_ID = "section-permalink-css"
_PERMALINK_CSS = """\
.section-permalink {
  display: inline-block;
  margin-left: 0.35em;
  font-size: 0.75em;
  color: #999;
  text-decoration: none;
  vertical-align: middle;
  opacity: 0;
  transition: opacity 0.15s;
}
:is(h2,h3,h4,h5,h6):hover .section-permalink,
:is(h2,h3,h4,h5,h6):focus-within .section-permalink {
  opacity: 1;
}
"""


def inject_section_permalinks(html_path: Path) -> int:
    """Add §N.N anchor links to every numbered heading. File-based wrapper.

    Returns the number of permalinks injected.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping section permalinks")
        return 0

    soup = read_html(html_path)
    count = inject_section_permalinks_soup(soup)
    if count:
        write_html(html_path, soup)
    return count


def inject_section_permalinks_soup(soup: object) -> int:
    """Add §N.N anchor links to every numbered heading in a soup object.

    Scans ``h2``–``h6`` elements for a leading numeric section number
    (e.g. "7.3.2 Title") and appends a small ``<a class="section-permalink">``
    link so readers can copy a direct URL to the section.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of permalink anchors injected.
    """
    count = 0
    for heading in soup.find_all(re.compile(r"^h[2-6]$")):
        hid = heading.get("id")
        if not hid:
            continue
        # Skip if a permalink is already present
        if heading.find(class_="section-permalink"):
            continue
        text = heading.get_text(" ", strip=True)
        m = _SECTION_NUM_RE.match(text)
        label = f"§{m.group(1)}" if m else "§"
        a_tag = soup.new_tag(
            "a",
            attrs={
                "class": "section-permalink",
                "href": f"#{hid}",
                "aria-label": f"Permalink to {text[:60]}",
                "title": f"Link to {label}",
            },
        )
        a_tag.string = label
        heading.append(a_tag)
        count += 1

    if count:
        inject_css(soup, _PERMALINK_CSS_ID, _PERMALINK_CSS)
        logging.info(f"Injected {count} section permalink anchor(s)")

    return count


def inject_section_headers(html_path: Path, *, use_weasyprint: bool = False) -> None:
    """Inject running section headers into the HTML for PDF generation.

    File-based wrapper around :func:`inject_section_headers_soup`.

    Uses CSS Named Strings (``string-set`` / ``string()``) which WeasyPrint
    supports natively, producing true per-page running headers that update
    as the reader moves through sections.

    Chrome headless does not support CSS Named Strings, so this feature
    is only effective with ``--weasyprint``.

    Args:
        html_path: Path to the PDF working copy HTML file.
        use_weasyprint: Whether the PDF will be generated with WeasyPrint.
    """
    if not use_weasyprint:
        logging.info(
            "Section headers require --weasyprint (Chrome does not "
            "support CSS Named Strings); skipping"
        )
        return

    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping section headers")
        return

    soup = read_html(html_path)
    inject_section_headers_soup(soup, use_weasyprint=use_weasyprint)
    write_html(html_path, soup)


def inject_section_headers_soup(soup: object, *, use_weasyprint: bool = False) -> None:
    """Inject running section headers on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
        use_weasyprint: Whether the PDF will be generated with WeasyPrint.
    """
    if not use_weasyprint:
        logging.info(
            "Section headers require --weasyprint (Chrome does not "
            "support CSS Named Strings); skipping"
        )
        return

    logging.info("Injecting section-aware running headers (WeasyPrint mode)")
    _inject_weasyprint_headers(soup)
    logging.info("Section-aware running headers injected")


def _inject_weasyprint_headers(soup: object) -> None:
    """Inject CSS Named Strings for WeasyPrint running headers."""
    t = THEME
    css = f"""
/* Section-Aware Running Headers (WeasyPrint) */
h2.heading.settled:not(.no-num) {{
  string-set: current-section content();
}}

@page {{
  @top-center {{
    content: string(current-section, first);
    font-size: {t.section_header_font_size};
    font-family: {t.font_sans};
    color: {t.section_header_color};
    font-style: italic;
    max-width: 80%;
    text-overflow: ellipsis;
    overflow: hidden;
    white-space: nowrap;
  }}
}}

/* Suppress header on first page and TOC pages */
@page :first {{
  @top-center {{
    content: none;
  }}
}}
"""
    inject_css(soup, "section-headers-css", css)

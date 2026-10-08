"""PDF watermark: overlay text on every page."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html


def inject_watermark(html_path: Path, watermark: str) -> None:
    """Add a diagonal watermark overlay to every printed page.

    File-based wrapper around :func:`inject_watermark_soup`.

    Args:
        html_path: Path to the HTML file.
        watermark: Either a predefined name ('draft', 'confidential',
            'review', 'obsolete') or custom text to use as the watermark.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping watermark")
        return

    soup = read_html(html_path)
    inject_watermark_soup(soup, watermark)
    write_html(html_path, soup)


def inject_watermark_soup(soup: BeautifulSoup, watermark: str) -> None:
    """Add a diagonal watermark overlay on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
        watermark: Either a predefined name or custom text.
    """
    t = THEME
    presets = t.watermark_presets

    # Resolve predefined styles or use custom text
    if watermark.lower() in presets:
        preset = presets[watermark.lower()]
        text = preset.text
        color = preset.color
        font_size = preset.font_size
    else:
        text = watermark
        color = t.watermark_default_color
        font_size = t.watermark_default_font_size

    logging.info(f"Injecting watermark: '{text}'")

    # Insert a watermark div at the top of <body>
    body = soup.find("body")
    if not body:
        logging.warning("No <body> found, cannot inject watermark")
        return

    # Remove Bikeshed's W3C watermark stylesheet (e.g. W3C-UD for
    # "Unofficial Draft" status) to avoid duplicate watermarks.
    _suppress_w3c_watermark(soup)

    wm_div = soup.new_tag("div", id="watermark", **{"class": "watermark"})
    wm_div.string = text
    body.insert(0, wm_div)

    css = f"""
/* PDF Watermark */
/* Suppress Bikeshed/W3C built-in watermark backgrounds */
:root {{
  --unofficial-watermark: none !important;
}}
body {{
  background-image: none !important;
}}
.watermark {{
  display: none;
}}
@media print {{
  .watermark {{
    display: block;
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%) rotate(-45deg);
    font-size: {font_size};
    font-family: {t.font_sans};
    font-weight: {t.watermark_font_weight};
    color: {color};
    white-space: nowrap;
    pointer-events: none;
    z-index: 9999;
    letter-spacing: {t.watermark_letter_spacing};
  }}
}}
@page {{
  /* Ensure watermark doesn't affect page margins */
  background: none !important;
}}
"""
    inject_css(soup, "watermark-css", css)
    logging.info(f"Watermark '{text}' injected")


def _suppress_w3c_watermark(soup: BeautifulSoup) -> None:
    """Remove Bikeshed's external W3C watermark stylesheet link."""
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href", "")
        if "w3.org/StyleSheets/TR/" in href and "W3C-" in href:
            logging.info(f"Removing W3C watermark stylesheet: {href}")
            link.decompose()


def suppress_all_watermarks(html_path: Path) -> None:
    """Remove all watermarks — both Bikeshed's built-in and any custom ones.

    File-based wrapper around :func:`suppress_all_watermarks_soup`.

    Args:
        html_path: Path to the HTML file.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping watermark removal")
        return

    soup = read_html(html_path)
    suppress_all_watermarks_soup(soup)
    write_html(html_path, soup)


def suppress_all_watermarks_soup(soup: BeautifulSoup) -> None:
    """Remove all watermarks on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    logging.info("Removing all watermarks")
    _suppress_w3c_watermark(soup)

    css = """
/* Suppress all watermarks */
:root {
  --unofficial-watermark: none !important;
}
body {
  background-image: none !important;
}
@page {
  background: none !important;
}
"""
    inject_css(soup, "watermark-css", css)
    logging.info("All watermarks removed")

"""Cover page customization for PDF generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html


def inject_cover_page(
    html_path: Path,
    *,
    title: str = None,
    subtitle: str = None,
    doc_number: str = None,
    date: str = None,
    version: str = None,
    logo_path: str = None,
    organization: str = None,
) -> None:
    """Insert a styled cover page at the beginning of the document.

    File-based wrapper around :func:`inject_cover_page_soup`.

    Args:
        html_path: Path to the HTML file.
        title: Document title (auto-detected from <title> if None).
        subtitle: Optional subtitle line.
        doc_number: Document/standard number (e.g. "ISO/IEC 23094-1").
        date: Date string (e.g. "March 2026").
        version: Version/draft string (e.g. "Working Draft 3").
        logo_path: Path to a logo image file.
        organization: Organization name (e.g. "Alliance for Open Media").
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping cover page")
        return

    soup = read_html(html_path)
    inject_cover_page_soup(
        soup,
        title=title,
        subtitle=subtitle,
        doc_number=doc_number,
        date=date,
        version=version,
        logo_path=logo_path,
        organization=organization,
    )
    write_html(html_path, soup)


def inject_cover_page_soup(
    soup: BeautifulSoup,
    *,
    title: str = None,
    subtitle: str = None,
    doc_number: str = None,
    date: str = None,
    version: str = None,
    logo_path: str = None,
    organization: str = None,
) -> None:
    """Insert a styled cover page on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
        title: Document title (auto-detected from <title> if None).
        subtitle: Optional subtitle line.
        doc_number: Document/standard number.
        date: Date string.
        version: Version/draft string.
        logo_path: Path to a logo image file.
        organization: Organization name.
    """
    logging.info("Injecting custom cover page")

    # Auto-detect title from document
    if title is None:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            title = CONFIG.spec_full_name

    # Build cover page elements
    cover = soup.new_tag("div", id="cover-page", **{"class": "cover-page"})

    # Logo
    if logo_path and Path(logo_path).exists():
        logo_div = soup.new_tag("div", **{"class": "cover-logo"})
        logo_img = soup.new_tag("img", src=logo_path, alt="Logo", **{"class": "cover-logo-img"})
        logo_div.append(logo_img)
        cover.append(logo_div)

    # Organization
    if organization:
        org_div = soup.new_tag("div", **{"class": "cover-organization"})
        org_div.string = organization
        cover.append(org_div)

    # Spacer
    spacer = soup.new_tag("div", **{"class": "cover-spacer"})
    cover.append(spacer)

    # Title
    title_div = soup.new_tag("h1", **{"class": "cover-title"})
    title_div.string = title
    cover.append(title_div)

    # Subtitle
    if subtitle:
        sub_div = soup.new_tag("div", **{"class": "cover-subtitle"})
        sub_div.string = subtitle
        cover.append(sub_div)

    # Document number
    if doc_number:
        num_div = soup.new_tag("div", **{"class": "cover-doc-number"})
        num_div.string = doc_number
        cover.append(num_div)

    # Version and date block
    meta_div = soup.new_tag("div", **{"class": "cover-meta"})
    if version:
        ver_span = soup.new_tag("div", **{"class": "cover-version"})
        ver_span.string = version
        meta_div.append(ver_span)
    if date:
        date_span = soup.new_tag("div", **{"class": "cover-date"})
        date_span.string = date
        meta_div.append(date_span)
    if version or date:
        cover.append(meta_div)

    # Insert cover page at the beginning of <body>
    body = soup.find("body")
    if not body:
        logging.warning("No <body> found, cannot inject cover page")
        return

    body.insert(0, cover)

    _inject_cover_css(soup)
    logging.info("Custom cover page injected")


def _inject_cover_css(soup: BeautifulSoup) -> None:
    """Inject CSS for the cover page."""
    t = THEME
    css = f"""
/* Cover Page */
.cover-page {{
  display: none;
}}
@media print {{
  .cover-page {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    page-break-after: always;
    text-align: center;
    padding: 2cm;
    box-sizing: border-box;
  }}
  .cover-logo {{
    margin-bottom: 2em;
  }}
  .cover-logo-img {{
    max-width: {t.cover_logo_max_width};
    max-height: {t.cover_logo_max_height};
  }}
  .cover-organization {{
    font-size: {t.cover_org_font_size};
    font-family: {t.font_sans};
    color: {t.cover_org_color};
    text-transform: uppercase;
    letter-spacing: 0.15em;
    margin-bottom: 1em;
  }}
  .cover-spacer {{
    flex: 1;
  }}
  .cover-title {{
    font-size: {t.cover_title_font_size};
    font-family: {t.font_sans};
    font-weight: bold;
    color: {t.cover_title_color};
    line-height: 1.2;
    margin: 0 0 0.5em 0;
    max-width: 80%;
  }}
  .cover-subtitle {{
    font-size: {t.cover_subtitle_font_size};
    font-family: {t.font_sans};
    color: {t.cover_subtitle_color};
    margin-bottom: 1em;
  }}
  .cover-doc-number {{
    font-size: {t.cover_doc_number_font_size};
    font-family: {t.font_mono};
    color: {t.cover_doc_number_color};
    margin-bottom: 2em;
  }}
  .cover-meta {{
    margin-top: auto;
    padding-top: 3em;
  }}
  .cover-version {{
    font-size: {t.cover_version_font_size};
    font-family: {t.font_sans};
    color: {t.cover_version_color};
    margin-bottom: 0.5em;
  }}
  .cover-date {{
    font-size: {t.cover_date_font_size};
    font-family: {t.font_sans};
    color: {t.cover_date_color};
  }}
}}
"""
    inject_css(soup, "cover-page-css", css)

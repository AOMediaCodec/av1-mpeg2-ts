"""Page numbering styles for PDF output.

Supports two modes:

- ``dual``: roman numerals for front matter, arabic (restarting at 1) for
  body and back matter.
- ``arabic``: standard arabic numerals throughout (the default from
  print.css; no extra injection needed).

The module is organised into three sections:

1. **Injection** — mark page zones and inject CSS ``@page`` rules for the
   chosen numbering style.
2. **Re-marking** — re-apply zone markers after late DOM insertions
   (e.g. LOF/LOT injected after initial numbering).
3. **Post-processing** — rewrite absolute page numbers in the TOC, LOF,
   and LOT so they reflect the dual roman/arabic scheme.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.theme import THEME
from specbuild.utils import get_bs4, inject_css, read_html, write_html

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

# Valid style names exposed to the CLI.
PAGE_NUMBER_STYLES = ("dual", "arabic")


# ------------------------------------------------------------------
# Section 1: Injection — zone marking and CSS @page rule insertion
# ------------------------------------------------------------------


def inject_page_numbering(
    html_path: Path, *, style: str = "dual", use_weasyprint: bool = False
) -> None:
    """Inject CSS page numbering into the HTML file.

    File-based wrapper around :func:`inject_page_numbering_soup`.

    Args:
        html_path: Path to the HTML file.
        style: ``'dual'`` for roman front-matter / arabic body, or
            ``'arabic'`` for plain arabic throughout.
        use_weasyprint: Whether WeasyPrint will be used for PDF generation.
    """
    if style == "arabic":
        logging.debug("Page numbering: arabic throughout (default from print.css)")
        return

    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping page numbering")
        return

    soup = read_html(html_path)
    inject_page_numbering_soup(soup, style=style, use_weasyprint=use_weasyprint)
    write_html(html_path, soup)


def inject_page_numbering_soup(
    soup: BeautifulSoup, *, style: str = "dual", use_weasyprint: bool = False
) -> None:
    """Inject CSS page numbering on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (mutated in place).
        style: ``'dual'`` for roman front-matter / arabic body.
        use_weasyprint: Whether WeasyPrint will be used for PDF generation.
    """
    logging.debug("Injecting dual page numbering (roman front-matter, arabic body)")

    _mark_page_zones(soup)

    if use_weasyprint:
        _inject_weasyprint_numbering(soup)
    else:
        _inject_chrome_numbering(soup)

    logging.debug("Page numbering styles injected")


def _mark_page_zones(soup: BeautifulSoup) -> None:
    """Mark front-matter and body zones with CSS Named Page properties.

    Sets ``page: body-pages`` on ``<body>`` so the default is arabic
    numbering.  Then marks every direct child of ``<body>`` that appears
    *before* ``<main>`` as ``page: front-matter`` (roman numerals).
    Elements after ``<main>`` (bibliography, index) inherit arabic from
    ``<body>``.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    body = soup.find("body")
    if not body:
        return

    # Default: arabic numbering for everything
    _add_page_style(body, "body-pages")
    logging.debug("Set <body> to page: body-pages")

    # Mark pre-<main> children as front-matter
    main = soup.find("main")
    if not main:
        logging.warning("No <main> element found; all pages will use arabic")
        return

    for child in body.children:
        if child is main:
            break
        if hasattr(child, "name") and child.name:
            _add_page_style(child, "front-matter")
            tag_id = child.get("id", child.name)
            logging.debug("Set <%s> to page: front-matter", tag_id)

    logging.debug("Marked page zones: pre-<main>=front-matter, body+=body-pages")


# ------------------------------------------------------------------
# Section 2: Re-marking — re-apply zones after late DOM insertions
# ------------------------------------------------------------------


def remark_front_matter(html_path: Path) -> None:
    """Re-mark any new elements before ``<main>`` as front-matter.

    File-based wrapper around :func:`remark_front_matter_soup`.

    Call this after injecting LOF/LOT or other elements into the HTML
    so they inherit the correct page numbering zone.  Only operates
    when dual numbering is active.

    Args:
        html_path: Path to the HTML file.
    """
    try:
        get_bs4()
    except ImportError:
        return

    soup = read_html(html_path)
    marked = remark_front_matter_soup(soup)
    if marked:
        write_html(html_path, soup)


def remark_front_matter_soup(soup: BeautifulSoup) -> int:
    """Re-mark new elements before ``<main>`` as front-matter on a pre-parsed soup.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of elements newly marked.
    """
    if not has_dual_numbering(soup):
        return 0

    body = soup.find("body")
    main = soup.find("main")
    if not body or not main:
        return 0

    marked = 0
    for child in body.children:
        if child is main:
            break
        if hasattr(child, "name") and child.name:
            style = child.get("style", "")
            if "page:" not in style:
                _add_page_style(child, "front-matter")
                marked += 1

    if marked:
        logging.info(f"Re-marked {marked} new front-matter elements")
    return marked


def _add_page_style(element: Tag, page_name: str) -> None:
    """Add a CSS ``page:`` property to an element's inline style.

    Args:
        element: HTML element to modify.
        page_name: CSS Named Page value (e.g. ``'front-matter'``,
            ``'body-pages'``).
    """
    existing = element.get("style", "")
    if existing and not existing.rstrip().endswith(";"):
        existing += "; "
    element["style"] = existing + f"page: {page_name};"


def _inject_weasyprint_numbering(soup: BeautifulSoup) -> None:
    """Inject CSS page numbering for WeasyPrint.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    _inject_dual_numbering_css(soup, use_important=False)


def _inject_chrome_numbering(soup: BeautifulSoup) -> None:
    """Inject CSS page numbering for Chrome headless.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    _inject_dual_numbering_css(soup, use_important=True)


def _inject_dual_numbering_css(soup: BeautifulSoup, *, use_important: bool = False) -> None:
    """Inject unified CSS page numbering for dual mode.

    Uses ``counter(page, lower-roman)`` for front-matter pages and a
    custom ``bodypage`` counter (incremented per body page) for body
    pages.  Neither Chrome nor WeasyPrint can reliably reset the
    built-in ``page`` counter between named page sequences, so the
    custom counter approach works for both engines.

    Args:
        soup: BeautifulSoup document.
        use_important: Add ``!important`` to override existing @page
            rules (needed for Chrome which has default rules from
            print.css).
    """
    theme = THEME
    important = " !important" if use_important else ""
    prefix = theme.page_number_prefix
    css = f"""
/* Page Numbering — Dual (roman front-matter, arabic body) */

/* Front matter: lowercase roman numerals using built-in page counter */
@page front-matter {{
  @bottom-right {{
    content: "{prefix}" counter(page, lower-roman){important};
    font-size: {theme.footer_font_size}pt;
    font-family: {theme.font_sans};
    color: {theme.color_muted};
  }}
}}

/* Body pages: arabic numerals using custom bodypage counter.
   The built-in page counter cannot be reliably reset, so we use a
   separate counter that starts at 0 on <main> and increments per
   body page. */
@page body-pages {{
  counter-increment: bodypage;
  @bottom-right {{
    content: "{prefix}" counter(bodypage){important};
    font-size: {theme.footer_font_size}pt;
    font-family: {theme.font_sans};
    color: {theme.color_muted};
  }}
}}

/* Suppress page number on cover/first page */
@page :first {{
  @bottom-left {{
    content: none{important};
  }}
  @bottom-center {{
    content: none{important};
  }}
  @bottom-right {{
    content: none{important};
  }}
}}
"""
    inject_css(soup, "page-numbering-css", css)


# ------------------------------------------------------------------
# Section 3: Post-processing — restyle TOC / LOF / LOT page numbers
# ------------------------------------------------------------------

# Standard roman numeral decomposition: (value, symbol) pairs in
# descending order, including subtractive forms (e.g. 900 = 'cm').
_ROMAN_VALUES = (1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1)
_ROMAN_SYMBOLS = ("m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i")


def to_roman(n: int) -> str:
    """Convert a positive integer to a lowercase roman numeral string.

    Args:
        n: Positive integer to convert.

    Returns:
        Lowercase roman numeral representation (e.g. 4 -> ``'iv'``).
    """
    result: list[str] = []
    for value, symbol in zip(_ROMAN_VALUES, _ROMAN_SYMBOLS):
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)


def restyle_toc_page_numbers(html_path: Path) -> None:
    """Convert absolute page numbers in TOC/LOF/LOT to dual-style numbers.

    File-based wrapper around :func:`restyle_toc_page_numbers_soup`.

    After the two-pass TOC system injects absolute PDF page numbers, this
    function rewrites them so that:

    - Targets in front matter (before ``<main>``) → lowercase roman numerals
    - Targets in body or back matter (``<main>`` and after) → arabic,
      offset so the first body page is 1.

    Only runs when dual page numbering is active (detected by the presence
    of ``page: front-matter`` in the HTML).

    Args:
        html_path: Path to the PDF working-copy HTML file.
    """
    try:
        get_bs4()
    except ImportError:
        return

    soup = read_html(html_path)
    restyled = restyle_toc_page_numbers_soup(soup)
    if restyled:
        write_html(html_path, soup)


def restyle_toc_page_numbers_soup(soup: BeautifulSoup) -> int:
    """Convert absolute page numbers in TOC/LOF/LOT to dual-style numbers.

    Soup-based core of :func:`restyle_toc_page_numbers`.

    Args:
        soup: BeautifulSoup document (mutated in place).

    Returns:
        Number of page numbers restyled, or 0 if dual numbering is not active.
    """
    if not has_dual_numbering(soup):
        return 0

    main = soup.find("main")
    if not main:
        return 0

    body_ids = collect_body_ids(soup, main)
    spans_with_pages = _collect_page_number_spans(soup)

    if not spans_with_pages:
        return 0

    # Determine the boundary: the lowest absolute page number that belongs
    # to the body zone tells us how many front-matter pages precede it.
    body_abs_pages = [p for _, p, tid in spans_with_pages if tid in body_ids]
    if not body_abs_pages:
        return 0

    front_matter_pages = min(body_abs_pages) - 1
    logging.info(f"Dual page numbering: {front_matter_pages} front-matter pages")

    restyled = 0
    for span, abs_page, target_id in spans_with_pages:
        if target_id in body_ids:
            # Body/back-matter: offset so first body page is 1
            styled = str(abs_page - front_matter_pages)
        else:
            # Front matter: lowercase roman numerals
            styled = to_roman(abs_page) if abs_page > 0 else "?"
        span.string = styled
        restyled += 1

    logging.info(f"Restyled {restyled} TOC/LOF/LOT page numbers for dual numbering")
    return restyled


# Mapping of (container CSS selector, span class) for each navigation
# list that contains page-number spans inserted by the two-pass TOC system.
_PAGE_NUMBER_SPAN_SELECTORS: list[tuple[str, str]] = [
    ("nav#toc", "toc-page-number"),
    ("nav#lof", "lof-page-number"),
    ("nav#lot", "lot-page-number"),
]


def _collect_page_number_spans(
    soup: BeautifulSoup,
) -> list[tuple[Tag, int, str]]:
    """Collect all page-number ``<span>`` elements from TOC, LOF, and LOT.

    Each returned tuple contains:

    - The ``<span>`` element itself.
    - The absolute (1-based) page number parsed from its text.
    - The ``id`` of the target element the span links to (from
      ``data-target`` attribute or the parent ``<a>`` href).

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        List of ``(span, abs_page, target_id)`` tuples.
    """
    results: list[tuple[Tag, int, str]] = []

    for container_sel, span_class in _PAGE_NUMBER_SPAN_SELECTORS:
        # Parse simple "tag#id" selector
        tag_name, _, sel_id = container_sel.partition("#")
        container = soup.find(tag_name, id=sel_id) if sel_id else soup.find(tag_name)
        if not container:
            continue

        for span in container.find_all("span", class_=span_class):
            text = span.string
            if not (text and text.strip().isdigit()):
                continue
            abs_page = int(text.strip())
            # Resolve the target element ID from the span or its parent <a>
            target_id = span.get("data-target", "")
            if not target_id:
                parent_a = span.find_parent("a", href=True)
                if parent_a:
                    target_id = parent_a["href"].lstrip("#")
            results.append((span, abs_page, target_id))

    return results


def has_dual_numbering(soup: BeautifulSoup) -> bool:
    """Check whether the HTML has dual page numbering styles applied.

    Detection is based on the presence of an inline ``page: front-matter``
    style, which is set by :func:`_mark_page_zones`.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        ``True`` if at least one element has a ``page: front-matter``
        inline style.
    """
    for el in soup.find_all(style=True):
        if "page: front-matter" in el.get("style", ""):
            return True
    return False


# ------------------------------------------------------------------
# Section 4: Print layout CSS — page-break control and print polish
# ------------------------------------------------------------------


def inject_print_css_soup(soup: BeautifulSoup) -> None:
    """Inject print-specific CSS for page-break control and layout polish.

    Injects an ``@media print`` block that prevents undesirable page breaks
    inside tables, figures, and admonition blocks; controls widows/orphans;
    hides navigation chrome; and expands ``<details>`` elements.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    css = """
@media print {
    /* Prevent page breaks inside tables, figures, code blocks */
    table, figure, pre, blockquote { page-break-inside: avoid; }

    /* Prevent orphaned headings */
    h1, h2, h3, h4, h5, h6 { page-break-after: avoid; }

    /* Widow/orphan control */
    p { orphans: 3; widows: 3; }

    /* Keep requirement/admonition blocks together */
    .requirement, .permission, .recommendation,
    .caution, .warning, .important, .note, .tip {
        page-break-inside: avoid;
    }

    /* Force page break before major sections */
    section.annex { page-break-before: always; }

    /* Don't print navigation elements */
    .back-to-toc, .toc-nav, .copy-btn, .code-lang-label { display: none; }

    /* Expand collapsed details */
    details { display: block; }
    details summary::after { content: ""; }
}
"""
    inject_css(soup, "print-layout-css", css)
    logging.info("Injected print layout CSS")


def inject_figure_print_css(soup: BeautifulSoup) -> None:
    """Inject print CSS for figure and caption rendering.

    Ensures figures scale correctly on print and captions are centred.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    css = """
@media print {
    figure img, figure svg { max-width: 100% !important; }
    figcaption { font-size: 0.9em; text-align: center; }
}
"""
    inject_css(soup, "figure-print-css", css)
    logging.info("Injected figure print CSS")


def collect_body_ids(soup: BeautifulSoup, main: Tag) -> set[str]:
    """Collect all element IDs inside ``<main>`` and after it in ``<body>``.

    These IDs represent the "body zone" — any TOC entry whose target is
    in this set will receive arabic page numbering; all others receive
    roman numerals.

    Args:
        soup: BeautifulSoup document (read-only).
        main: The ``<main>`` element that marks the start of body content.

    Returns:
        Set of element ID strings belonging to the body/back-matter zone.
    """
    ids = set()

    # IDs inside <main>
    if main.get("id"):
        ids.add(main["id"])
    for el in main.find_all(id=True):
        ids.add(el["id"])

    # IDs in siblings after <main>
    for sibling in main.next_siblings:
        if hasattr(sibling, "name") and sibling.name:
            if sibling.get("id"):
                ids.add(sibling["id"])
            for el in sibling.find_all(id=True):
                ids.add(el["id"])

    return ids

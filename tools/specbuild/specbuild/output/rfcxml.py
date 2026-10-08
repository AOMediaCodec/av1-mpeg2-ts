"""RFC XML v3 (RFC 7991) export.

Generates XML following the IETF RFC 7991 format from compiled HTML.
Uses only :mod:`xml.etree.ElementTree` (stdlib).

RFC XML v3 is the standard input format for IETF RFC publication.  It is
processed by the ``xml2rfc`` tool to produce the final text/HTML/PDF output.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# XML namespace used on the root <rfc> element.
_XI_NS = "http://www.w3.org/2001/XInclude"

# Pattern for bibliography / references headings.
_BIB_RE = re.compile(r"(?i)^(normative\s+references|informative\s+references|references)")

# Pattern to detect an RFC reference: "RFC 2119" or "RFC2119".
_RFC_REF_RE = re.compile(r"\bRFC\s*(\d+)\b", re.IGNORECASE)

# Pattern to detect an Internet-Draft reference.
_ID_REF_RE = re.compile(r"\b(draft-[a-z0-9][a-z0-9-]*)\b", re.IGNORECASE)

# Pattern for detecting month names in date strings.
_MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_MONTH_RE = re.compile(
    r"\b(" + "|".join(_MONTH_NAMES) + r")\b",
    re.IGNORECASE,
)

# Pattern for four-digit year.
_YEAR_RE = re.compile(r"\b((?:19|20)\d{2})\b")

# Language detection for <pre> code blocks from class attributes.
_CODE_LANG_RE = re.compile(r"language-(\w+)|highlight-(\w+)|lang-(\w+)")

# Pseudocode class names that map to artwork rather than sourcecode.
_PSEUDOCODE_CLASSES = frozenset(("pseudocode", "pseudo-code", "algorithm"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def export_rfc_xml(
    html_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    soup: BeautifulSoup | None = None,
) -> Path | None:
    """Convert compiled HTML to RFC XML v3.

    Args:
        html_path: Path to compiled index.html.
        output_path: Destination XML path.
        metadata: Document metadata dict (see module docstring for keys).
        soup: Pre-parsed BeautifulSoup tree (avoids re-reading disk if provided).

    Returns:
        Path to the generated XML file, or ``None`` on failure.
    """
    if soup is None:
        try:
            from specbuild.utils import read_html

            soup = read_html(html_path)
        except Exception:
            logging.error("Failed to read HTML for RFC XML export")
            return None

    xml_str = export_rfc_xml_soup(soup, metadata)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logging.info(f"RFC XML v3 written to {output_path}")
    return output_path


def export_rfc_xml_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
) -> str:
    """Convert parsed HTML soup to RFC XML v3 string.

    Args:
        soup: Parsed BeautifulSoup document.
        metadata: Document metadata dict.

    Returns:
        RFC XML v3 document as a UTF-8 string.
    """
    rfc = Element("rfc")
    rfc.set("xmlns:xi", _XI_NS)
    rfc.set("version", "3")

    doc_name = metadata.get("doc_name", "")
    if doc_name:
        rfc.set("docName", doc_name)

    category = metadata.get("category", "info")
    rfc.set("category", category)

    rfc.set("submissionType", "IETF")
    rfc.set("ipr", metadata.get("ipr", "trust200902"))
    rfc.set("xml:lang", metadata.get("language", "en"))

    _build_front(rfc, metadata)
    _build_middle(rfc, soup)
    _build_back(rfc, soup)

    indent(rfc, space="  ")
    xml_bytes = tostring(rfc, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def _build_front(rfc: Element, metadata: dict[str, str]) -> None:
    """Build the ``<front>`` element."""
    front = SubElement(rfc, "front")

    # Title
    title_text = metadata.get("title", metadata.get("title_main", ""))
    title_el = SubElement(front, "title")
    abbrev = metadata.get("title_abbrev", "")
    if abbrev:
        title_el.set("abbrev", abbrev)
    title_el.text = title_text

    # Series info
    doc_name = metadata.get("doc_name", "")
    if doc_name:
        series_info = SubElement(front, "seriesInfo")
        series_info.set("name", "Internet-Draft")
        series_info.set("value", doc_name)

    # Authors
    authors = metadata.get("authors") or []
    if isinstance(authors, str):
        authors = [{"name": authors}]
    for author_dict in authors:
        _build_author(front, author_dict)
    if not authors:
        # Emit a placeholder author element so the document is valid
        _build_author(front, {})

    # Date
    copyright_year = metadata.get("copyright_year", "")
    date_el = SubElement(front, "date")
    if copyright_year:
        date_el.set("year", str(copyright_year))

    # Abstract
    abstract_text = metadata.get("abstract", "")
    if abstract_text:
        abstract_el = SubElement(front, "abstract")
        t_el = SubElement(abstract_el, "t")
        t_el.text = abstract_text

    _build_boilerplate(front, metadata)


def _build_boilerplate(front: Element, metadata: dict[str, str]) -> None:
    """Emit RFC 7322 standard boilerplate (Trust Legal Provisions + copyright)."""
    year = str(metadata.get("copyright_year", ""))
    ipr = metadata.get("ipr", "trust200902")

    boilerplate = SubElement(front, "boilerplate")

    # BCP 78/79 conformance note
    section1 = SubElement(boilerplate, "section", anchor="status-of-memo")
    t1 = SubElement(section1, "t")
    t1.text = (
        "This Internet-Draft is submitted in full conformance with the "
        "provisions of BCP 78 and BCP 79."
    )

    # Copyright notice
    section2 = SubElement(boilerplate, "section", anchor="copyright")
    t2 = SubElement(section2, "t")
    year_str = f"{year} " if year else ""
    if "trust200902" in ipr:
        t2.text = (
            f"Copyright (c) {year_str}IETF Trust and the persons identified "
            "as the document authors. All rights reserved."
        )
    else:
        t2.text = f"Copyright (c) {year_str}The IETF Trust. All rights reserved."


def _build_author(front: Element, author: dict) -> None:
    """Emit one ``<author>`` element."""
    author_el = SubElement(front, "author")

    fullname = author.get("name", "")
    initials = author.get("initials", "")
    surname = author.get("surname", "")

    if fullname:
        author_el.set("fullname", fullname)
    if initials:
        author_el.set("initials", initials)
    if surname:
        author_el.set("surname", surname)

    org = author.get("org", "")
    if org:
        org_el = SubElement(author_el, "organization")
        org_el.text = org

    email = author.get("email", "")
    if email:
        addr_el = SubElement(author_el, "address")
        email_el = SubElement(addr_el, "email")
        email_el.text = email


# ---------------------------------------------------------------------------
# Middle (body sections)
# ---------------------------------------------------------------------------


def _build_middle(rfc: Element, soup: BeautifulSoup) -> None:
    """Build the ``<middle>`` element from HTML body sections."""
    middle = SubElement(rfc, "middle")

    body = soup.find("body")
    if body is None:
        return

    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue
        text = heading.get_text(" ", strip=True)

        # References sections go to <back>
        if _BIB_RE.match(text):
            continue

        _rfc_section(middle, section)


# ---------------------------------------------------------------------------
# Back matter
# ---------------------------------------------------------------------------


def _build_back(rfc: Element, soup: BeautifulSoup) -> None:
    """Build the ``<back>`` element with references."""
    body = soup.find("body")
    if body is None:
        return

    ref_sections: list = []
    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue
        text = heading.get_text(" ", strip=True)
        if _BIB_RE.match(text):
            ref_sections.append(section)

    if not ref_sections:
        return

    back = SubElement(rfc, "back")

    # Wrap all reference sections under a single top-level <references> when
    # there are multiple; emit directly when there is only one.
    if len(ref_sections) == 1:
        _convert_ref_section(back, ref_sections[0])
    else:
        outer = SubElement(back, "references")
        outer.set("anchor", "refs")
        name_el = SubElement(outer, "name")
        name_el.text = "References"
        for section in ref_sections:
            _convert_ref_section(outer, section)


def _convert_ref_section(parent: Element, section: object) -> None:
    """Convert a references HTML section to a ``<references>`` element."""
    heading = section.find(HEADING_RE)
    heading_text = heading.get_text(" ", strip=True) if heading else "References"
    sec_id = section.get("id", "references")

    refs_el = SubElement(parent, "references")
    refs_el.set("anchor", str(sec_id))

    name_el = SubElement(refs_el, "name")
    name_el.text = heading_text

    for i, li in enumerate(section.find_all("li"), start=1):
        _rfc_reference(refs_el, li, i)


# ---------------------------------------------------------------------------
# Section conversion
# ---------------------------------------------------------------------------


def _rfc_section(parent: Element, section_html: object) -> None:
    """Convert one HTML ``<section>`` to an RFC XML ``<section>``.

    Nested ``<section>`` elements become nested ``<section>`` children.
    """
    sec_id = section_html.get("id", "")
    sec_el = SubElement(parent, "section")
    sec_el.set("numbered", "true")
    if sec_id:
        sec_el.set("anchor", sec_id)

    heading = section_html.find(HEADING_RE)
    if heading:
        # Strip leading section number like "1 " or "A.2 "
        raw = heading.get_text(" ", strip=True)
        title_text = re.sub(r"^[A-Z]?\d+(?:\.\d+)*\s+", "", raw).strip()
        if not title_text:
            title_text = raw
        name_el = SubElement(sec_el, "name")
        name_el.text = title_text

    _rfc_section_children(sec_el, section_html)


def _rfc_section_children(parent: Element, section_html: object) -> None:
    """Convert direct children of a section element into RFC XML."""
    for child in section_html.children:
        if not hasattr(child, "name") or child.name is None:
            continue

        name = child.name

        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            # Already handled as the section <name>
            continue

        if name == "section":
            _rfc_section(parent, child)

        elif name == "p":
            _rfc_para(parent, child)

        elif name in ("ul", "ol"):
            _rfc_list(parent, child)

        elif name == "dl":
            _rfc_dl(parent, child)

        elif name == "pre":
            _rfc_pre(parent, child)

        elif name == "table":
            _rfc_table(parent, child)

        elif name == "figure":
            _rfc_figure(parent, child)

        elif name == "aside":
            aside = SubElement(parent, "aside")
            _rfc_section_children(aside, child)

        elif name == "blockquote":
            bq = SubElement(parent, "blockquote")
            for p in child.find_all("p"):
                _rfc_para(bq, p)

        elif name == "div":
            classes = child.get("class", [])
            if any(c in classes for c in ("note", "warning", "caution", "important", "tip")):
                aside = SubElement(parent, "aside")
                for p in child.find_all("p"):
                    _rfc_para(aside, p)
            else:
                # Generic div — recurse
                _rfc_section_children(parent, child)


# ---------------------------------------------------------------------------
# Paragraph and inline content
# ---------------------------------------------------------------------------


def _rfc_para(parent: Element, p_elem: object) -> Element:
    """Convert a ``<p>`` element to RFC XML ``<t>`` with inline content."""
    t_el = SubElement(parent, "t")
    _rfc_inline(t_el, p_elem)
    return t_el


def _append_text(parent: Element, text: str, children: list[Element]) -> None:
    """Append *text* to the appropriate text/tail slot of *parent*."""
    if not text:
        return
    if not children:
        parent.text = (parent.text or "") + text
    else:
        last = children[-1]
        last.tail = (last.tail or "") + text


def _rfc_inline(xml_el: Element, html_el: object) -> None:
    """Recursively copy inline HTML content into an RFC XML element.

    Handles: text nodes, ``<a href>`` → ``<eref>``/``<xref>``, ``<strong>``
    → ``<strong>``, ``<em>`` → ``<em>``, ``<code>``/``<tt>`` → ``<tt>``,
    ``<sup>``, ``<sub>``, display math → ``<artwork type="math">``, inline
    math → ``<tt>``.
    """
    children_added: list[Element] = []

    for child in html_el.children:
        if not hasattr(child, "name") or child.name is None:
            text = str(child)
            if text:
                _append_text(xml_el, text, children_added)
            continue

        tag = child.name

        if tag == "a":
            href = child.get("href", "")
            link_text = child.get_text(strip=True)
            if href.startswith("#"):
                inner = SubElement(xml_el, "xref")
                inner.set("target", href[1:])
                inner.text = link_text or None
            elif href:
                inner = SubElement(xml_el, "eref")
                inner.set("target", href)
                inner.text = link_text or None
            else:
                _rfc_inline(xml_el, child)
                continue
            children_added.append(inner)

        elif tag in ("strong", "b"):
            inner = SubElement(xml_el, "strong")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag in ("em", "i"):
            inner = SubElement(xml_el, "em")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag in ("code", "tt"):
            inner = SubElement(xml_el, "tt")
            inner.text = child.get_text()
            children_added.append(inner)

        elif tag == "sup":
            inner = SubElement(xml_el, "sup")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag == "sub":
            inner = SubElement(xml_el, "sub")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag == "u":
            inner = SubElement(xml_el, "u")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag in ("del", "s"):
            inner = SubElement(xml_el, "s")
            _rfc_inline(inner, child)
            children_added.append(inner)

        elif tag == "span":
            classes = child.get("class", [])
            if any(c in classes for c in ("math", "formula", "inline-math")):
                # Inline math → <tt> with TeX fallback
                tex = child.get("data-tex", "")
                if not tex:
                    ann = child.find("annotation", {"encoding": "application/x-tex"})
                    if ann:
                        tex = ann.get_text(strip=True)
                inner = SubElement(xml_el, "tt")
                inner.text = tex if tex else child.get_text(strip=True)
                children_added.append(inner)
            else:
                _rfc_inline(xml_el, child)

        else:
            _rfc_inline(xml_el, child)


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def _rfc_list(parent: Element, list_elem: object) -> None:
    """Convert ``<ul>`` / ``<ol>`` to RFC XML ``<ul>`` / ``<ol>``."""
    tag = "ul" if list_elem.name == "ul" else "ol"
    list_el = SubElement(parent, tag)
    if tag == "ul":
        list_el.set("spacing", "normal")

    for li in list_elem.find_all("li", recursive=False):
        li_el = SubElement(list_el, "li")
        # If the li contains block children, preserve them; otherwise inline
        has_block = any(
            hasattr(c, "name") and c.name in ("p", "ul", "ol", "dl", "pre", "table")
            for c in li.children
        )
        if has_block:
            _rfc_section_children(li_el, li)
        else:
            _rfc_inline(li_el, li)


def _rfc_dl(parent: Element, dl_elem: object) -> None:
    """Convert ``<dl>`` to RFC XML ``<dl>``."""
    dl_el = SubElement(parent, "dl")
    for dt in dl_elem.find_all("dt", recursive=False):
        dt_el = SubElement(dl_el, "dt")
        _rfc_inline(dt_el, dt)
        dd = dt.find_next_sibling("dd")
        if dd:
            dd_el = SubElement(dl_el, "dd")
            _rfc_inline(dd_el, dd)


# ---------------------------------------------------------------------------
# Code / pre blocks
# ---------------------------------------------------------------------------


def _code_language(pre_elem: object) -> str:
    """Extract programming language from ``<pre>`` or ``<code>`` class attribute."""
    for elem in (pre_elem, pre_elem.find("code") if hasattr(pre_elem, "find") else None):
        if elem is None:
            continue
        classes = " ".join(elem.get("class", []))
        m = _CODE_LANG_RE.search(classes)
        if m:
            return m.group(1) or m.group(2) or m.group(3) or ""
    return ""


def _is_pseudocode(pre_elem: object) -> bool:
    """Return True when the element carries a pseudocode class."""
    classes = set(pre_elem.get("class", []))
    code_inner = pre_elem.find("code")
    if code_inner:
        classes.update(code_inner.get("class", []))
    return bool(classes & _PSEUDOCODE_CLASSES)


def _rfc_pre(parent: Element, pre_elem: object) -> None:
    """Convert a ``<pre>`` block to ``<sourcecode>`` or ``<artwork>``."""
    code_text = pre_elem.get_text()

    if _is_pseudocode(pre_elem):
        art = SubElement(parent, "artwork")
        art.set("type", "pseudocode")
        art.text = code_text
    else:
        sc = SubElement(parent, "sourcecode")
        lang = _code_language(pre_elem)
        if lang:
            sc.set("type", lang)
        sc.text = code_text


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


def _extract_cell_attrs(cell: object) -> dict[str, str]:
    """Extract colspan/rowspan/align from an HTML table cell element."""
    attrs: dict[str, str] = {}
    if cell.get("colspan"):
        attrs["colspan"] = str(cell["colspan"])
    if cell.get("rowspan"):
        attrs["rowspan"] = str(cell["rowspan"])
    if cell.get("align"):
        attrs["align"] = cell["align"]
    return attrs


def _rfc_table(parent: Element, table: object) -> None:
    """Convert an HTML ``<table>`` to an RFC XML ``<table>``."""
    table_id = table.get("id", "")
    attrs: dict[str, str] = {}
    if table_id:
        attrs["anchor"] = table_id

    table_el = SubElement(parent, "table", **attrs)

    # Optional caption → <name>
    caption_el = table.find("caption")
    if caption_el:
        name_el = SubElement(table_el, "name")
        name_el.text = caption_el.get_text(strip=True)

    thead = table.find("thead")
    if thead:
        thead_el = SubElement(table_el, "thead")
        for tr in thead.find_all("tr"):
            row_el = SubElement(thead_el, "tr")
            for cell in tr.find_all(["th", "td"]):
                cell_tag = "th" if cell.name == "th" else "td"
                cell_el = SubElement(row_el, cell_tag, **_extract_cell_attrs(cell))
                _rfc_inline(cell_el, cell)

    tbody_source = table.find("tbody") or table
    tbody_el = SubElement(table_el, "tbody")
    for tr in tbody_source.find_all("tr"):
        if thead and tr.parent and tr.parent.name == "thead":
            continue
        row_el = SubElement(tbody_el, "tr")
        for cell in tr.find_all(["th", "td"]):
            cell_tag = "th" if cell.name == "th" else "td"
            cell_el = SubElement(row_el, cell_tag, **_extract_cell_attrs(cell))
            _rfc_inline(cell_el, cell)


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------


def _rfc_figure(parent: Element, figure: object) -> None:
    """Convert an HTML ``<figure>`` to an RFC XML ``<figure>``."""
    fig_id = figure.get("id", "")
    attrs: dict[str, str] = {}
    if fig_id:
        attrs["anchor"] = fig_id

    fig_el = SubElement(parent, "figure", **attrs)

    figcaption = figure.find("figcaption")
    if figcaption:
        name_el = SubElement(fig_el, "name")
        name_el.text = figcaption.get_text(strip=True)

    img = figure.find("img")
    if img:
        src = img.get("src", "")
        art = SubElement(fig_el, "artwork")
        art.set("type", "svg" if src.endswith(".svg") else "binary-art")
        if src:
            art.set("src", src)
        alt = img.get("alt", "")
        if alt:
            art.set("alt", alt)


# ---------------------------------------------------------------------------
# Bibliography / references
# ---------------------------------------------------------------------------


def _rfc_reference(refs_el: Element, li_elem: object, index: int) -> None:
    """Convert one bibliography ``<li>`` to a ``<reference>`` element.

    Handles RFC references, Internet-Draft references, and generic entries.
    """
    raw_text = li_elem.get_text(strip=True)
    li_id = li_elem.get("id", "")

    # Derive the anchor from the li id (strip "ref-" prefix if present) or
    # fall back to generating one from the RFC number / text content.
    if li_id:
        # Normalise "ref-RFC2119" → "RFC2119", etc.
        anchor = re.sub(r"^ref-", "", li_id, flags=re.IGNORECASE)
    else:
        anchor = f"ref-{index}"

    ref_el = SubElement(refs_el, "reference")
    ref_el.set("anchor", anchor)

    # Inner <front> required by RFC 7991
    inner_front = SubElement(ref_el, "front")

    # --- RFC reference ---
    rfc_m = _RFC_REF_RE.search(raw_text)
    if rfc_m:
        rfc_num = rfc_m.group(1)
        # Title: everything after the RFC nnnn, pattern
        title_text = re.sub(r"\bRFC\s*\d+[,\s]*", "", raw_text, flags=re.IGNORECASE).strip()
        # Strip leading/trailing punctuation
        title_text = title_text.strip(".,;: \t")
        if not title_text:
            title_text = f"Request for Comments {rfc_num}"

        title_el = SubElement(inner_front, "title")
        title_el.text = title_text

        _extract_author_date(inner_front, raw_text)

        series_bcp = SubElement(ref_el, "seriesInfo")
        series_bcp.set("name", "RFC")
        series_bcp.set("value", rfc_num)
        return

    # --- Internet-Draft reference ---
    id_m = _ID_REF_RE.search(raw_text)
    if id_m:
        draft_name = id_m.group(1)
        title_text = re.sub(re.escape(draft_name), "", raw_text, flags=re.IGNORECASE).strip()
        title_text = title_text.strip(".,;: \t") or draft_name

        title_el = SubElement(inner_front, "title")
        title_el.text = title_text

        _extract_author_date(inner_front, raw_text)

        series_id = SubElement(ref_el, "seriesInfo")
        series_id.set("name", "Internet-Draft")
        series_id.set("value", draft_name)
        return

    # --- Generic reference ---
    title_el = SubElement(inner_front, "title")
    title_el.text = raw_text

    _extract_author_date(inner_front, raw_text)

    refcontent = SubElement(ref_el, "refcontent")
    refcontent.text = raw_text


def _extract_author_date(front_el: Element, text: str) -> None:
    """Attempt to extract author initials/surname and date from reference text.

    Emits minimal ``<author>`` and ``<date>`` child elements.  When parsing
    fails the placeholders are left empty so the document remains schema-valid.
    """
    # Heuristic: look for "Initial. Surname" patterns before the first comma
    # that is not inside an RFC/I-D number.  This covers the common RFC style
    # "S. Bradner, ..." or "A. Author and B. Coauthor, ...".
    author_pattern = re.compile(r"\b([A-Z]\.[A-Z]?\.?\s+[A-Z][a-z]+)")
    for m in author_pattern.finditer(text):
        parts = m.group(1).split()
        if len(parts) >= 2:
            initials = parts[0]
            surname = parts[-1]
            author_el = SubElement(front_el, "author")
            author_el.set("initials", initials)
            author_el.set("surname", surname)
            break  # one author element is sufficient for basic compliance

    # Date extraction
    date_el = SubElement(front_el, "date")
    yr_m = _YEAR_RE.search(text)
    if yr_m:
        date_el.set("year", yr_m.group(1))
    mo_m = _MONTH_RE.search(text)
    if mo_m:
        date_el.set("month", mo_m.group(1).capitalize())

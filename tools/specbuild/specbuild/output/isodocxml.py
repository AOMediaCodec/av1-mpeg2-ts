"""IsoDoc-compatible XML export.

Generates XML following a subset of the Metanorma IsoDoc schema from
compiled HTML.  Uses only :mod:`xml.etree.ElementTree` (stdlib).
"""

from __future__ import annotations

import copy
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, tostring

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, NavigableString, Tag

    from specbuild.standards.flavors import FlavorSpec

# MathML namespace
_MML_NS = "http://www.w3.org/1998/Math/MathML"

# Module-level reference to current soup (for footnote lookup)
_current_soup: object = None


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def export_isodoc_xml(
    html_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
    soup: BeautifulSoup | None = None,
) -> Path | None:
    """Convert compiled HTML to IsoDoc XML."""
    if soup is None:
        try:
            from specbuild.utils import read_html

            soup = read_html(html_path)
        except Exception:
            logging.error("Failed to read HTML for IsoDoc XML export")
            return None

    xml_str = export_isodoc_xml_soup(soup, metadata, flavor)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logging.info(f"IsoDoc XML written to {output_path}")
    return output_path


def export_isodoc_xml_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> str:
    """Convert parsed HTML soup to IsoDoc XML string."""
    global _current_soup

    # Work on a copy so we can sectionalize without mutating the shared soup
    working_soup = copy.deepcopy(soup)
    _ensure_section_wrappers(working_soup)
    _current_soup = working_soup

    lang = metadata.get("language", "en")
    root_tag = _flavor_root_tag(flavor)
    root = Element(root_tag)
    root.set("xmlns", "https://www.metanorma.org/ns/iso")
    root.set("xmlns:mml", _MML_NS)
    root.set("xml:lang", lang)

    _build_bibdata(root, metadata, flavor)
    _build_preface(root, working_soup)
    _build_sections(root, working_soup, flavor)
    _build_annexes(root, working_soup, flavor)
    _build_bibliography(root, working_soup, flavor)

    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


# ---------------------------------------------------------------------------
# Sectionalization for flat Bikeshed HTML
# ---------------------------------------------------------------------------


def _ensure_section_wrappers(soup: BeautifulSoup) -> None:
    """Wrap flat h2 headings in <section> elements if not already wrapped.

    Bikeshed outputs flat <h2 class="heading settled" data-level="N">
    headings without <section> wrappers.  This function groups each
    content-level h2 with its following siblings into a <section> element
    so that downstream ISO processing can find section boundaries.
    Preface headings (no-toc, no-num) are left outside any section.
    Operates on <main> if present (Bikeshed puts content there), else <body>.
    """
    container = soup.find("main") or soup.find("body")
    if container is None or container.find("section", recursive=False):
        return  # already sectioned

    children = list(container.children)
    for elem in children:
        elem.extract()  # detach without destroying

    current_sec = None
    for elem in children:
        tag_name = getattr(elem, "name", None)
        is_content_h2 = (
            tag_name == "h2"
            and "heading" in elem.get("class", [])
            and "settled" in elem.get("class", [])
            and "no-toc" not in elem.get("class", [])
        )
        if is_content_h2:
            sec_id = elem.get("id", "")
            current_sec = soup.new_tag("section", id=sec_id)
            current_sec.append(elem)
            container.append(current_sec)
        elif current_sec is not None:
            current_sec.append(elem)
        else:
            container.append(elem)


# ---------------------------------------------------------------------------
# Flavor / root tag
# ---------------------------------------------------------------------------


def _flavor_root_tag(flavor: FlavorSpec | None) -> str:
    if flavor is None:
        return "standard-document"
    name = flavor.name.lower()
    if name in ("iso", "iec"):
        return "iso-standard"
    if name in ("itu-t", "itu"):
        return "itu-standard"
    if name == "ietf":
        return "ietf-standard"
    return f"{name}-standard"


# ---------------------------------------------------------------------------
# Bibdata (document metadata)
# ---------------------------------------------------------------------------


def _build_bibdata(
    root: Element,
    metadata: dict[str, str],
    flavor: FlavorSpec | None,
) -> None:
    bibdata = SubElement(root, "bibdata", type=metadata.get("doc_type", "standard"))

    lang = metadata.get("language", "en")

    for key, t_type in (
        ("title_main", "main"),
        ("title_intro", "title-intro"),
        ("title_part", "title-part"),
    ):
        val = metadata.get(key, "")
        if val:
            SubElement(bibdata, "title", type=t_type, language=lang).text = val

    # Additional language titles (e.g. title_main_fr, title_main_de)
    for extra_lang in ("fr", "de", "es", "ru", "zh", "ar"):
        for key, t_type in (
            (f"title_main_{extra_lang}", "main"),
            (f"title_intro_{extra_lang}", "title-intro"),
            (f"title_part_{extra_lang}", "title-part"),
        ):
            val = metadata.get(key, "")
            if val:
                SubElement(bibdata, "title", type=t_type, language=extra_lang).text = val

    docnumber = metadata.get("docnumber", "")
    if docnumber:
        flavor_name = flavor.display_name if flavor else ""
        prefix = f"{flavor_name} " if flavor_name else ""
        partnumber = metadata.get("partnumber", "")
        ident_text = f"{prefix}{docnumber}"
        if partnumber:
            ident_text += f"-{partnumber}"
        SubElement(bibdata, "docidentifier", type=flavor_name or "ISO").text = ident_text
        SubElement(bibdata, "docnumber").text = docnumber

    # Contributor (author org)
    if flavor:
        contrib = SubElement(bibdata, "contributor")
        SubElement(contrib, "role", type="author")
        org = SubElement(SubElement(contrib, "organization"), "name")
        org.text = flavor.display_name

    edition = metadata.get("edition", "")
    if edition:
        SubElement(bibdata, "edition").text = edition

    SubElement(bibdata, "language").text = lang
    SubElement(bibdata, "script").text = "Latn"

    stage = metadata.get("stage", "")
    if stage:
        status = SubElement(bibdata, "status")
        SubElement(status, "stage").text = stage
        substage = metadata.get("substage", "")
        if substage:
            SubElement(status, "substage").text = substage

    copyright_year = metadata.get("copyright_year", "")
    if copyright_year:
        cr = SubElement(bibdata, "copyright")
        SubElement(cr, "from").text = copyright_year
        if flavor:
            owner_org = SubElement(SubElement(cr, "owner"), "organization")
            SubElement(owner_org, "name").text = flavor.display_name

    tc = metadata.get("technical_committee", "")
    if tc:
        eg = SubElement(bibdata, "editorialgroup")
        tc_num = metadata.get("technical_committee_number", "")
        tc_type = metadata.get("technical_committee_type", "TC")
        tc_el = SubElement(eg, "technical-committee", type=tc_type)
        if tc_num:
            tc_el.set("number", tc_num)
        tc_el.text = tc

        sc = metadata.get("subcommittee", "")
        sc_num = metadata.get("subcommittee_number", "")
        if sc or sc_num:
            sc_el = SubElement(eg, "subcommittee", type="SC")
            if sc_num:
                sc_el.set("number", sc_num)
            sc_el.text = sc or f"SC {sc_num}"

        wg = metadata.get("workgroup", "")
        wg_num = metadata.get("workgroup_number", "")
        if wg or wg_num:
            wg_el = SubElement(eg, "workgroup", type="WG")
            if wg_num:
                wg_el.set("number", wg_num)
            wg_el.text = wg or f"WG {wg_num}"

    ics = metadata.get("ics", "")
    if ics:
        for code in ics.split(";"):
            code = code.strip()
            if code:
                SubElement(SubElement(bibdata, "ics"), "code").text = code


# ---------------------------------------------------------------------------
# Preface (Foreword, Introduction)
# ---------------------------------------------------------------------------

_PREFACE_RE = re.compile(r"(?i)^(foreword|introduction|abstract|preface|acknowledgements?)")


def _build_preface(root: Element, soup: BeautifulSoup) -> None:
    body = soup.find("main") or soup.find("body")
    if body is None:
        return

    preface_sections = []
    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading and _PREFACE_RE.match(heading.get_text(strip=True)):
            preface_sections.append(section)

    if not preface_sections:
        return

    preface_el = SubElement(root, "preface")
    for section in preface_sections:
        heading = section.find(HEADING_RE)
        text = heading.get_text(strip=True) if heading else ""
        sec_id = section.get("id", "")
        tag = "foreword" if re.match(r"(?i)^foreword", text) else "introduction"
        attrs: dict[str, str] = {}
        if sec_id:
            attrs["id"] = sec_id
        el = SubElement(preface_el, tag, **attrs)
        if text:
            SubElement(el, "title").text = text
        _convert_children(el, section)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

_ANNEX_RE = re.compile(r"(?i)^(annex|appendix)")
_BIB_RE = re.compile(r"(?i)^(bibliography|informative\s+references?)")
_NORM_REFS_RE = re.compile(r"(?i)^normative\s+references?")


def _build_sections(
    root: Element,
    soup: BeautifulSoup,
    flavor: FlavorSpec | None,
) -> None:
    sections_el = SubElement(root, "sections")

    body = soup.find("main") or soup.find("body")
    if body is None:
        return

    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue

        text = heading.get_text(strip=True)
        if _PREFACE_RE.match(text) or _ANNEX_RE.match(text) or _BIB_RE.match(text):
            continue

        if _NORM_REFS_RE.match(text):
            # Normative references live inside <sections> as <references>
            sec_id = section.get("id", "normative-references")
            refs_el = SubElement(sections_el, "references", id=sec_id, obligation="normative")
            SubElement(refs_el, "title").text = text
            _convert_bib_entries(refs_el, section)
            continue

        _convert_section(sections_el, section)


# ---------------------------------------------------------------------------
# Annexes
# ---------------------------------------------------------------------------


def _build_annexes(
    root: Element,
    soup: BeautifulSoup,
    flavor: FlavorSpec | None,
) -> None:
    body = soup.find("main") or soup.find("body")
    if body is None:
        return

    annex_re = re.compile(r"(?i)^(annex|appendix)\s+([A-Z])")

    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue

        text = heading.get_text(strip=True)
        m = annex_re.match(text)
        if not m:
            continue

        obligation = "normative" if "(normative)" in text.lower() else "informative"
        sec_id = section.get("id", f"annex-{m.group(2).lower()}")
        annex_el = SubElement(root, "annex", id=sec_id, obligation=obligation)
        SubElement(annex_el, "title").text = text
        _convert_children(annex_el, section)


# ---------------------------------------------------------------------------
# Bibliography
# ---------------------------------------------------------------------------


def _build_bibliography(
    root: Element,
    soup: BeautifulSoup,
    flavor: FlavorSpec | None,
) -> None:
    body = soup.find("main") or soup.find("body")
    if body is None:
        return

    bib_sections = []
    for section in body.find_all("section", recursive=False):
        heading = section.find(HEADING_RE)
        if heading and _BIB_RE.match(heading.get_text(strip=True)):
            bib_sections.append(section)

    if not bib_sections:
        return

    bib_el = SubElement(root, "bibliography")
    for section in bib_sections:
        heading = section.find(HEADING_RE)
        text = heading.get_text(strip=True) if heading else ""
        sec_id = section.get("id", "bibliography")
        refs = SubElement(bib_el, "references", id=sec_id, obligation="informative")
        SubElement(refs, "title").text = text
        _convert_bib_entries(refs, section)


def _convert_bib_entries(refs_el: Element, section: Tag) -> None:
    """Populate a <references> element from <dd id="biblio-..."> entries."""
    # Entries from * [[[REF,name]]] style: <dd id="biblio-slug">text</dd>
    for dd in section.find_all("dd"):
        dd_id = dd.get("id", "")
        bibitem_id = dd_id[len("biblio-") :] if dd_id.startswith("biblio-") else dd_id
        if not bibitem_id:
            continue
        bibitem = SubElement(refs_el, "bibitem", id=bibitem_id)
        _parse_bibitem_content(bibitem, dd)

    # Entries from [[[REF,name]]] direct style: <dt id="biblio-slug">[REF]</dt><dd>text</dd>
    for dt in section.find_all("dt"):
        dt_id = dt.get("id", "")
        if not dt_id.startswith("biblio-"):
            continue
        bibitem_id = dt_id[len("biblio-") :]
        bibitem = SubElement(refs_el, "bibitem", id=bibitem_id)
        dd = dt.find_next_sibling("dd")
        node = dd if dd else dt
        _parse_bibitem_content(bibitem, node)


def _parse_bibitem_content(bibitem: Element, html_node: Tag) -> None:
    """Parse a bibliography entry node into structured <bibitem> children."""
    full_text = html_node.get_text(strip=True)

    # Try to split "DOCID:YEAR, title text" or "DOCID, title text"
    m = re.match(
        r"^([A-Z][A-Za-z0-9/. :+-]{2,}?(?::\d{4})?)\s*,\s*(.+)$",
        full_text,
        re.DOTALL,
    )
    if m:
        docid_str = m.group(1).strip()

        # Extract year from "DOCID:YYYY"
        year_m = re.search(r":(\d{4})$", docid_str)
        if year_m:
            date_el = SubElement(bibitem, "date", type="published")
            SubElement(date_el, "on").text = year_m.group(1)
            docid_str = docid_str[: year_m.start()]

        # Detect identifier type
        if docid_str.startswith(("ISO", "IEC")):
            id_type = "ISO"
        elif docid_str.startswith(("ITU", "Rec.")):
            id_type = "ITU-T"
        elif docid_str.startswith("RFC"):
            id_type = "IETF"
        elif docid_str.startswith("SMPTE"):
            id_type = "SMPTE"
        else:
            id_type = "other"

        SubElement(bibitem, "docidentifier", type=id_type).text = docid_str

        # Title with inline markup preserved
        title_el = SubElement(bibitem, "title")
        # Find the matching node in HTML for rich title
        _set_mixed_content_after_comma(title_el, html_node)
    else:
        # Fallback: store as plain title
        title_el = SubElement(bibitem, "title")
        _set_mixed_content(title_el, html_node)


def _set_mixed_content_after_comma(xml_el: Element, html_node: Tag) -> None:
    """Set mixed content from the part of html_node after the first comma."""
    from bs4 import NavigableString

    # Collect all children, skip up to and including first text containing ","
    found_comma = False
    for child in html_node.children:
        if not found_comma:
            if isinstance(child, NavigableString):
                text = str(child)
                idx = text.find(",")
                if idx >= 0:
                    found_comma = True
                    remainder = text[idx + 1 :].lstrip()
                    if remainder:
                        xml_el.text = (xml_el.text or "") + remainder
            # tag before comma — skip
        else:
            _append_child_to_xml(xml_el, child)

    if not found_comma:
        # No comma found — just copy all content
        _set_mixed_content(xml_el, html_node)


# ---------------------------------------------------------------------------
# Section / clause conversion
# ---------------------------------------------------------------------------

_TERMS_RE = re.compile(r"(?i)^(?:\d[\d.]*\s+)?terms?\s+(and|&|,)\s+definitions?")
_SCOPE_RE = re.compile(r"(?i)^(?:\d[\d.]*\s+)?scope\s*$")


def _convert_section(parent: Element, section: Tag) -> None:
    heading = section.find(HEADING_RE)
    text = heading.get_text(strip=True) if heading else ""

    sec_id = section.get("id", "")
    attrs: dict[str, str] = {}
    if sec_id:
        attrs["id"] = sec_id

    if _TERMS_RE.match(text):
        clause = SubElement(parent, "terms", **attrs)
        SubElement(clause, "title").text = text
        _convert_terms_section(clause, section)
        return

    if _SCOPE_RE.match(text):
        attrs["type"] = "scope"

    clause = SubElement(parent, "clause", **attrs)
    if text:
        SubElement(clause, "title").text = text
    _convert_children(clause, section)


def _convert_terms_section(terms_el: Element, section: Tag) -> None:
    """Convert terms-and-definitions clause into per-term <term> elements."""
    for child in section.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue

        if child.name == "section":
            # Each sub-section under Terms is one term (its heading is the term name)
            heading = child.find(HEADING_RE)
            term_text = heading.get_text(strip=True) if heading else ""
            term_id = child.get("id", "")
            term_attrs: dict[str, str] = {"id": term_id} if term_id else {}
            term_el = SubElement(terms_el, "term", **term_attrs)

            pref = SubElement(SubElement(term_el, "preferred"), "expression")
            SubElement(pref, "name").text = term_text

            defn_el = SubElement(term_el, "definition")
            verbal_el = SubElement(defn_el, "verbal-definition")

            for defn_child in child.children:
                if not hasattr(defn_child, "name") or defn_child.name is None:
                    continue
                if defn_child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                    continue
                if defn_child.name == "p":
                    p_el = SubElement(verbal_el, "p")
                    _set_mixed_content(p_el, defn_child)
                elif defn_child.name == "div":
                    classes = defn_child.get("class", [])
                    if "note" in classes:
                        note_el = SubElement(term_el, "termnote")
                        for p in defn_child.find_all("p"):
                            np = SubElement(note_el, "p")
                            _set_mixed_content(np, p)
                elif defn_child.name in ("ul", "ol"):
                    _convert_list(verbal_el, defn_child)

        elif child.name == "p":
            # Intro paragraph for the terms clause (before individual terms)
            p_el = SubElement(terms_el, "p")
            _set_mixed_content(p_el, child)


# ---------------------------------------------------------------------------
# Children dispatcher
# ---------------------------------------------------------------------------


def _convert_children(parent: Element, section: Tag) -> None:
    for child in section.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue

        if child.name == "section":
            _convert_section(parent, child)

        elif child.name == "p":
            p_el = SubElement(parent, "p")
            elem_lang = child.get("lang", "")
            if elem_lang:
                p_el.set("xml:lang", elem_lang)
            _set_mixed_content(p_el, child)

        elif child.name == "table":
            _convert_table(parent, child)

        elif child.name == "figure":
            _convert_figure(parent, child)

        elif child.name in ("ul", "ol"):
            _convert_list(parent, child)

        elif child.name == "dl":
            _convert_dl(parent, child)

        elif child.name == "pre":
            src = SubElement(parent, "sourcecode")
            lang = child.get("highlight") or child.get("data-highlight") or ""
            if lang:
                src.set("language", lang)
            src.text = child.get_text()

        elif child.name == "div":
            classes = child.get("class", [])
            if "note" in classes:
                note_el = SubElement(parent, "note")
                _convert_div_content(note_el, child)
            elif "example" in classes:
                ex_el = SubElement(parent, "example")
                _convert_div_content(ex_el, child)
            elif "advisement" in classes:
                adm = SubElement(parent, "admonition", type="warning")
                _convert_div_content(adm, child)
            elif "equation-wrapper" in classes:
                _convert_formula(parent, child)
            else:
                # Generic div — recurse
                _convert_children(parent, child)

        elif child.name == "section":
            # Skip footnote sections — content inlined as <fn>
            section_classes = child.get("class", [])
            if "footnotes" in section_classes:
                continue
            _convert_section(parent, child)

        elif child.name == "hr":
            pass  # ignore horizontal rules


def _convert_div_content(xml_el: Element, html_div: Tag) -> None:
    """Convert the content of a note/example/advisement <div>."""
    for child in html_div.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name == "p":
            p_el = SubElement(xml_el, "p")
            _set_mixed_content(p_el, child)
        elif child.name in ("ul", "ol"):
            _convert_list(xml_el, child)
        elif child.name == "dl":
            _convert_dl(xml_el, child)
        elif child.name == "pre":
            SubElement(xml_el, "sourcecode").text = child.get_text()


# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------


def _convert_table(parent: Element, html_table: Tag) -> None:
    tbl_id = html_table.get("id", "")
    attrs: dict[str, str] = {}
    if tbl_id:
        attrs["id"] = tbl_id
    tbl = SubElement(parent, "table", **attrs)

    cap = html_table.find("caption")
    if cap:
        SubElement(tbl, "name").text = cap.get_text(strip=True)

    for section_tag in ("thead", "tbody", "tfoot"):
        html_section = html_table.find(section_tag)
        if html_section:
            sec_el = SubElement(tbl, section_tag)
            for tr in html_section.find_all("tr", recursive=False):
                tr_el = SubElement(sec_el, "tr")
                for cell in tr.find_all(["th", "td"], recursive=False):
                    cell_attrs: dict[str, str] = {}
                    colspan = cell.get("colspan")
                    if colspan:
                        cell_attrs["colspan"] = str(colspan)
                    rowspan = cell.get("rowspan")
                    if rowspan:
                        cell_attrs["rowspan"] = str(rowspan)
                    style = cell.get("style", "")
                    if "center" in style:
                        cell_attrs["align"] = "center"
                    elif "right" in style:
                        cell_attrs["align"] = "right"
                    tag = "th" if cell.name == "th" else "td"
                    cell_el = SubElement(tr_el, tag, **cell_attrs)
                    _set_mixed_content(cell_el, cell)


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------


def _convert_figure(parent: Element, html_figure: Tag) -> None:
    fig_id = html_figure.get("id", "")
    attrs: dict[str, str] = {}
    if fig_id:
        attrs["id"] = fig_id
    fig_el = SubElement(parent, "figure", **attrs)

    cap = html_figure.find("figcaption")
    if cap:
        SubElement(fig_el, "name").text = cap.get_text(strip=True)

    img = html_figure.find("img")
    if img:
        src = img.get("src", "")
        img_attrs: dict[str, str] = {"src": src}
        alt = img.get("alt", "")
        if alt:
            img_attrs["alt"] = alt
        # Infer mimetype from extension
        ext = src.rsplit(".", 1)[-1].lower() if "." in src else ""
        img_attrs["mimetype"] = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "svg": "image/svg+xml",
            "gif": "image/gif",
            "tif": "image/tiff",
            "tiff": "image/tiff",
        }.get(ext, "image/png")
        SubElement(fig_el, "image", **img_attrs)


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------


def _convert_list(parent: Element, html_list: Tag) -> None:
    list_el = SubElement(parent, html_list.name)
    for li in html_list.find_all("li", recursive=False):
        item = SubElement(list_el, "li")
        # A list item may contain nested lists or just inline content
        has_block = any(
            hasattr(c, "name") and c.name in ("ul", "ol", "p", "pre", "table", "figure")
            for c in li.children
        )
        if has_block:
            _convert_children(item, li)
        else:
            _set_mixed_content(item, li)


def _convert_dl(parent: Element, html_dl: Tag) -> None:
    dl_el = SubElement(parent, "dl")
    for dt in html_dl.find_all("dt", recursive=False):
        dt_el = SubElement(dl_el, "dt")
        _set_mixed_content(dt_el, dt)
        dd = dt.find_next_sibling("dd")
        if dd:
            dd_el = SubElement(dl_el, "dd")
            _set_mixed_content(dd_el, dd)


# ---------------------------------------------------------------------------
# Mixed-content helper (inline markup preservation)
# ---------------------------------------------------------------------------


def _set_mixed_content(xml_el: Element, bs_node: Tag) -> None:
    """Copy mixed text+inline-markup from a BeautifulSoup node to an XML element."""
    from bs4 import NavigableString

    last_xml_child: Element | None = None

    for child in bs_node.children:
        if isinstance(child, NavigableString):
            text = str(child)
            if not text:
                continue
            if last_xml_child is None:
                xml_el.text = (xml_el.text or "") + text
            else:
                last_xml_child.tail = (last_xml_child.tail or "") + text
        elif hasattr(child, "name") and child.name:
            inline_el = _convert_inline_tag(child)
            if inline_el is not None:
                xml_el.append(inline_el)
                last_xml_child = inline_el
            else:
                # Unknown tag — extract text
                text = child.get_text()
                if text:
                    if last_xml_child is None:
                        xml_el.text = (xml_el.text or "") + text
                    else:
                        last_xml_child.tail = (last_xml_child.tail or "") + text


def _append_child_to_xml(xml_el: Element, bs_child: Tag | NavigableString) -> None:
    """Append a single BS child (tag or string) to an XML element."""
    from bs4 import NavigableString

    if isinstance(bs_child, NavigableString):
        text = str(bs_child)
        if text:
            children = list(xml_el)
            if children:
                children[-1].tail = (children[-1].tail or "") + text
            else:
                xml_el.text = (xml_el.text or "") + text
    elif hasattr(bs_child, "name") and bs_child.name:
        inline_el = _convert_inline_tag(bs_child)
        if inline_el is not None:
            xml_el.append(inline_el)
        else:
            text = bs_child.get_text()
            if text:
                children = list(xml_el)
                if children:
                    children[-1].tail = (children[-1].tail or "") + text
                else:
                    xml_el.text = (xml_el.text or "") + text


def _convert_inline_tag(bs_tag: Tag) -> Element | None:
    """Convert an HTML inline tag to its ISO XML equivalent."""
    name = bs_tag.name

    if name in ("em", "i"):
        el = Element("em")
        _set_mixed_content(el, bs_tag)
        return el

    if name in ("strong", "b"):
        el = Element("strong")
        _set_mixed_content(el, bs_tag)
        return el

    if name == "code":
        el = Element("tt")
        _set_mixed_content(el, bs_tag)
        return el

    if name in ("sup", "sub"):
        # Detect footnote reference: <sup><a href="#fn-N" class="footnote-ref">
        if name == "sup":
            for inner_child in bs_tag.children:
                if hasattr(inner_child, "name") and inner_child.name == "a":
                    classes = inner_child.get("class", [])
                    href = inner_child.get("href", "")
                    if "footnote-ref" in classes and href.startswith("#fn-"):
                        fn_id = href[1:]
                        fn_text = _resolve_footnote_text(fn_id)
                        fn_el = Element("fn")
                        ref_num = re.sub(r"[^0-9]", "", fn_id) or fn_id
                        fn_el.set("reference", ref_num)
                        p_el = SubElement(fn_el, "p")
                        p_el.text = fn_text
                        return fn_el
        el = Element(name)
        _set_mixed_content(el, bs_tag)
        return el

    if name == "a":
        href = bs_tag.get("href", "")
        if href.startswith("#biblio-"):
            bibitemid = href[len("#biblio-") :]
            el = Element("eref", bibitemid=bibitemid)
            _set_mixed_content(el, bs_tag)
            return el
        if href.startswith("#"):
            target = href[1:]
            el = Element("xref", target=target)
            _set_mixed_content(el, bs_tag)
            return el
        # External URL
        el = Element("link", target=href)
        _set_mixed_content(el, bs_tag)
        return el

    if name == "span":
        classes = bs_tag.get("class", [])
        if "math-expr" in classes:
            mml_et = _extract_mml_et(bs_tag)
            if mml_et is not None:
                el = Element("stem", type="MathML")
                el.append(mml_et)
                return el
            el = Element("stem", type="AsciiMath")
            el.text = bs_tag.get_text()
            return el

    # All other tags — return None (caller will extract plain text)
    return None


# ---------------------------------------------------------------------------
# Footnote helpers
# ---------------------------------------------------------------------------


def _resolve_footnote_text(fn_id: str) -> str:
    """Look up footnote text by id in the current soup."""
    import copy as _copy

    global _current_soup
    if _current_soup is None:
        return ""
    fn_elem = _current_soup.find(id=fn_id)
    if fn_elem is None:
        return ""
    # Work on a shallow copy so the live soup tree is not mutated
    fn_copy = _copy.copy(fn_elem)
    for backref in fn_copy.find_all("a", class_="footnote-backref"):
        backref.decompose()
    return fn_copy.get_text(strip=True)


# ---------------------------------------------------------------------------
# MathML helpers
# ---------------------------------------------------------------------------

_MML_SKIP_TAGS = {"svg", "annotation"}


def _bs4_mml_to_et(bs_elem: object) -> Element | None:
    """Recursively convert a BS4 <math> element to an ET Element with MathML namespace."""

    def _is_mjx(tag: str) -> bool:
        return tag.startswith("mjx-")

    def _convert(elem: object, parent_ns: str | None) -> Element | None:
        tag = elem.name  # type: ignore[attr-defined]
        if tag is None:
            return None
        if tag in _MML_SKIP_TAGS or _is_mjx(tag):
            return None

        explicit_xmlns = elem.get("xmlns", "")  # type: ignore[attr-defined]
        if explicit_xmlns == _MML_NS or parent_ns == _MML_NS or tag == "math":
            ns = _MML_NS
        else:
            ns = parent_ns or ""

        clark_tag = f"{{{ns}}}{tag}" if ns else tag

        attribs: dict[str, str] = {}
        for k, v in (elem.attrs or {}).items():  # type: ignore[union-attr]
            if k == "xmlns":
                continue
            if isinstance(v, list):
                v = " ".join(v)
            attribs[k] = str(v)

        et_el = Element(clark_tag, attribs)

        pending_text: list[str] = []
        last_child_et: Element | None = None

        for node in elem.children:  # type: ignore[attr-defined]
            if not hasattr(node, "name") or node.name is None:
                pending_text.append(str(node))
                continue

            child_et = _convert(node, ns)
            if child_et is None:
                pending_text.append(node.get_text())
                continue

            text_str = "".join(pending_text)
            pending_text = []
            if last_child_et is None:
                et_el.text = (et_el.text or "") + text_str if text_str else et_el.text
            else:
                last_child_et.tail = (
                    (last_child_et.tail or "") + text_str if text_str else last_child_et.tail
                )
            et_el.append(child_et)
            last_child_et = child_et

        text_str = "".join(pending_text)
        if text_str:
            if last_child_et is None:
                et_el.text = (et_el.text or "") + text_str
            else:
                last_child_et.tail = (last_child_et.tail or "") + text_str

        return et_el

    return _convert(bs_elem, None)  # type: ignore[return-value]


def _extract_mml_et(container_elem: object) -> Element | None:
    """Find a <math> element inside container_elem and convert it to ET."""
    try:
        math_bs = container_elem.find("math")  # type: ignore[attr-defined]
        if math_bs is None:
            return None
        et_el = _bs4_mml_to_et(math_bs)
        if et_el is not None and "MathML" in et_el.tag:
            return et_el
    except Exception as exc:
        logging.debug(f"MathML parse failed for element: {exc}")
    return None


# ---------------------------------------------------------------------------
# Display formula converter
# ---------------------------------------------------------------------------


def _convert_formula(parent: Element, wrapper_div: object) -> None:
    """Convert a div.equation-wrapper to IsoDoc <formula>."""
    num_span = wrapper_div.find("span", class_="equation-number")  # type: ignore[attr-defined]
    eq_id = num_span.get("id", "") if num_span else ""

    # Extract TeX source
    tex = wrapper_div.get("data-tex", "")  # type: ignore[attr-defined]
    if not tex:
        ann = wrapper_div.find("annotation", {"encoding": "application/x-tex"})  # type: ignore[attr-defined]
        if ann:
            tex = ann.get_text(strip=True)
    if not tex:
        for p in wrapper_div.find_all("p"):  # type: ignore[attr-defined]
            text = p.get_text(strip=True)
            m = re.match(r"^\$\$(.+?)\$\$\s*$", text, re.DOTALL)
            if m:
                tex = m.group(1).strip()
                break

    attrs: dict[str, str] = {}
    if eq_id:
        attrs["id"] = eq_id
    formula_el = SubElement(parent, "formula", **attrs)

    mml_et = _extract_mml_et(wrapper_div)
    if mml_et is not None:
        stem = SubElement(formula_el, "stem", type="MathML")
        stem.append(mml_et)
    elif tex:
        SubElement(formula_el, "stem", type="AsciiMath").text = tex
    else:
        # Fallback: plain text content
        SubElement(formula_el, "stem", type="AsciiMath").text = wrapper_div.get_text(strip=True)  # type: ignore[attr-defined]

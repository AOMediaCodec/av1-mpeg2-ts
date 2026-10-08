"""NISO STS (Standards Tag Suite) XML export.

Generates XML following the NISO Z39.102 STS Interchange Tag Set from
compiled HTML.  Uses only :mod:`xml.etree.ElementTree` (stdlib).

STS XML is the format used by ISO's internal document management systems.
It differs from IsoDoc XML (see :mod:`specbuild.output.isodocxml`) in its
use of ``<sec>`` with ``sec-type`` attributes, TBX terminology markup,
``<fig>``/``<table-wrap>`` wrappers, and ``<app-group>`` for annexes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, register_namespace, tostring

from specbuild.utils import HEADING_RE

# Register the MathML prefix so ElementTree serializes Clark-notation MathML
# elements as ``mml:math`` (matching the STS DTD) and emits a single
# ``xmlns:mml`` declaration, instead of an auto-generated ``ns0:`` prefix.
register_namespace("mml", "http://www.w3.org/1998/Math/MathML")

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec

# TBX namespace used for terminology entries (NISO STS interchange DTD fixes
# this to the ed-1 URN).
_TBX_NS = "urn:iso:std:iso:30042:ed-1"
_XLINK_NS = "http://www.w3.org/1999/xlink"
_MML_NS = "http://www.w3.org/1998/Math/MathML"

# Section number pattern: "1", "1.2", "A.3.1", etc.
_SECNO_RE = re.compile(r"^([A-Z]?\d+(?:\.\d+)*)\s+")

# Pattern for annex headings.
_ANNEX_RE = re.compile(r"(?i)^(?:annex|appendix)\s+([A-Z])")

# Pattern for bibliography / references headings.
_BIB_RE = re.compile(
    r"(?i)^(bibliography|normative\s+references|informative\s+references|references)"
)

# Pattern for the terms-and-definitions heading.
_TERMS_RE = re.compile(r"(?i)^(?:\d+\s+)?terms\s+(?:and|,)\s+definitions$")

# Pattern for the scope heading.
_SCOPE_RE = re.compile(r"(?i)^(?:\d+\s+)?scope$")

# Pattern for the normative references heading.
_NORMREFS_RE = re.compile(r"(?i)^(?:\d+\s+)?normative\s+references$")

# Bibliography entry patterns to detect SDO document IDs.
_STD_BIB_RE = re.compile(
    r"^((?:ISO|IEC|ISO/IEC|ITU|ITU-T|IEEE|IETF|RFC\s*\d|MPEG|AOM)[^\s,;]*\s*(?:[\d:]+)?)\s*[,\u2014\u2013\-]+\s*(.*)",
    re.IGNORECASE,
)

# Language detection for <pre> code blocks from class attributes.
_CODE_LANG_RE = re.compile(r"language-(\w+)|highlight-(\w+)|lang-(\w+)")

# Display math delimiter pattern.
_DISPLAY_MATH_RE = re.compile(r"^\s*\$\$(.+?)\$\$\s*$", re.DOTALL)


class _NoteCounters:
    """Per-clause counters for notes and examples (reset per top-level section)."""

    __slots__ = ("notes", "examples", "equations")

    def __init__(self) -> None:
        self.notes = 0
        self.examples = 0
        self.equations = 0


def export_sts_xml(
    html_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
    soup: BeautifulSoup | None = None,
) -> Path | None:
    """Convert compiled HTML to NISO STS XML.

    Args:
        html_path: Path to compiled index.html.
        output_path: Destination XML path.
        metadata: Resolved standards metadata dict.
        flavor: Active standards flavor (optional).
        soup: Pre-parsed BeautifulSoup tree (avoids re-reading disk if provided).

    Returns:
        Path to generated XML file, or ``None`` on failure.
    """
    if soup is None:
        try:
            from specbuild.utils import read_html

            soup = read_html(html_path)
        except Exception:
            logging.error("Failed to read HTML for STS XML export")
            return None

    xml_str = export_sts_xml_soup(soup, metadata, flavor)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logging.info(f"NISO STS XML written to {output_path}")
    return output_path


# Bundled NISO STS 1.2 interchange (MathML3) DTD entry point, relative to either
# the consumer workspace or PROJECT_ROOT (see resolve_asset_file).
_STS_DTD_REL = "schema/niso-sts-1.2-mathml3/NISO-STS-interchange-1-mathml3.dtd"


def validate_sts_xml(xml_path: Path) -> list[str]:
    """Validate an STS XML file against the bundled NISO STS 1.2 DTD.

    Args:
        xml_path: Path to the STS XML file to validate.

    Returns:
        A list of human-readable error strings (empty if the document is
        valid). A single-element list is returned when validation cannot be
        performed (lxml or the DTD is unavailable, or the file is missing).
    """
    try:
        from lxml import etree
    except ImportError:
        return ["lxml is required to validate STS XML (pip install lxml)"]

    if not xml_path.exists():
        return [f"STS file not found: {xml_path}"]

    from specbuild.utils import resolve_asset_file

    dtd_path = resolve_asset_file(_STS_DTD_REL)
    if not dtd_path.exists():
        return [f"bundled NISO STS DTD not found: {dtd_path}"]

    try:
        dtd = etree.DTD(str(dtd_path))
        tree = etree.parse(str(xml_path), etree.XMLParser(resolve_entities=True))
    except Exception as exc:  # noqa: BLE001 — surface parse/DTD-load failures
        return [f"could not parse STS or DTD: {exc}"]

    if dtd.validate(tree):
        return []
    return [f"line {e.line}: {e.message}" for e in dtd.error_log]



def _collect_footnotes(soup: BeautifulSoup) -> dict[str, str]:
    """Collect footnote content indexed by anchor ID.

    Searches for:
    - ``<li class="footnote" id="fn-N">`` anywhere in the document
    - ``<li id="fn-N">`` inside a ``<section class="footnotes">`` or
      ``<div class="footnotes">``

    Returns a dict mapping ``"fn-N"`` to the inner HTML of the ``<li>``
    (excluding the back-reference link ``<a class="footnote-backref">``).
    """
    footnotes: dict[str, str] = {}

    # Collect from <li class="footnote" id="fn-N"> anywhere
    for li in soup.find_all("li", class_="footnote"):
        fn_id = li.get("id", "")
        if fn_id:
            footnotes[fn_id] = _footnote_inner_html(li)

    # Also collect from <li id="fn-N"> inside a footnotes container
    for container in soup.find_all(["section", "div"], class_=lambda c: c and "footnotes" in c):
        for li in container.find_all("li"):
            fn_id = li.get("id", "")
            if fn_id and fn_id not in footnotes:
                footnotes[fn_id] = _footnote_inner_html(li)

    return footnotes


def _footnote_inner_html(li: object) -> str:
    """Return footnote paragraph text, excluding back-reference links."""
    paragraphs: list[str] = []
    for p in li.find_all("p"):  # type: ignore[attr-defined]
        # Build text skipping backref links
        parts: list[str] = []
        for node in p.children:  # type: ignore[attr-defined]
            if hasattr(node, "name") and node.name == "a":
                classes = node.get("class", [])
                if "footnote-backref" in classes:
                    continue
            parts.append(str(node))
        paragraphs.append(f"<p>{''.join(parts).strip()}</p>")
    if paragraphs:
        return "".join(paragraphs)
    # Fall back: all text content
    text = li.get_text(strip=True)  # type: ignore[attr-defined]
    return f"<p>{text}</p>" if text else ""


def export_sts_xml_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> str:
    """Convert parsed HTML soup to NISO STS XML string."""
    root = Element("standard")
    # xmlns:mml is emitted automatically via the registered "mml" prefix when a
    # MathML element is present; declaring it here too would duplicate the attr.
    root.set("xmlns:xlink", _XLINK_NS)
    root.set("xmlns:tbx", _TBX_NS)
    root.set("xml:lang", metadata.get("language", "en"))
    root.set("dtd-version", "1.2")

    # Pre-collect footnotes so they can be inlined as <fn> elements.
    footnote_map = _collect_footnotes(soup)
    lang = metadata.get("language", "en")

    _build_front(root, metadata, flavor)
    _build_body(root, soup, flavor, footnote_map, lang=lang)
    _build_back(root, soup, metadata, flavor, footnote_map)

    _sanitize_ids(root)

    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    doctype = (
        "<!DOCTYPE standard PUBLIC "
        '"-//NISO//DTD NISO STS Interchange Tag Set (NISO STS) v1.2 20221031//EN" '
        '"NISO-STS-interchange-1-2-MathML3.dtd">'
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{doctype}\n{xml_bytes}\n'


# Attributes whose values are ID references and must be rewritten in lockstep
# with sanitized ``id`` values.
_IDREF_ATTRS = ("rid", "rids")


def _sanitize_ids(root: Element) -> None:
    """Rewrite ``id`` values to valid XML names and fix references in lockstep.

    XML ``ID``/``IDREF`` values must be valid names (NCName) — they cannot begin
    with a digit. Bikeshed can emit ids like ``11-7-subtitle`` or ``29``; STS
    validation then rejects both the ``id`` and any ``rid`` that points to it.
    Build a remap of offending ids, apply it to every ``id`` and to all
    IDREF-bearing attributes so cross-references keep resolving.
    """
    remap: dict[str, str] = {}
    for el in root.iter():
        cur = el.get("id")
        if cur and not _is_xml_name(cur):
            remap.setdefault(cur, "id-" + cur)
    if not remap:
        return
    for el in root.iter():
        cur = el.get("id")
        if cur in remap:
            el.set("id", remap[cur])
        for attr in _IDREF_ATTRS:
            val = el.get(attr)
            if not val:
                continue
            el.set(attr, " ".join(remap.get(tok, tok) for tok in val.split()))


def _is_xml_name(value: str) -> bool:
    """True if *value* is a valid XML Name (safe as an ID; no leading digit)."""
    return bool(re.match(r"^[A-Za-z_][\w.\-]*$", value))


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------


def _build_front(
    root: Element,
    metadata: dict[str, str],
    flavor: FlavorSpec | None,
) -> None:
    """Build the ``<front>`` element with ``<iso-meta>``."""
    front = SubElement(root, "front")
    iso_meta = SubElement(front, "iso-meta")

    # --- title-wrap ---
    lang = metadata.get("language", "en")
    title_wrap = SubElement(iso_meta, "title-wrap")
    title_wrap.set("xml:lang", lang)

    title_main = metadata.get("title_main", "")
    title_intro = metadata.get("title_intro", "")
    title_part = metadata.get("title_part", "")

    # STS <title-wrap> child order is fixed: intro?, main?, compl?.
    if title_intro:
        intro_el = SubElement(title_wrap, "intro")
        intro_el.text = title_intro
    if title_main:
        main_el = SubElement(title_wrap, "main")
        main_el.text = title_main
    if title_part:
        compl_el = SubElement(title_wrap, "compl")
        compl_el.text = title_part

    # Additional language title wraps (e.g. French parallel text)
    for extra_lang in ("fr", "de", "es", "ru", "zh", "ar"):
        extra_main = metadata.get(f"title_main_{extra_lang}", "")
        if not extra_main:
            continue
        tw2 = SubElement(iso_meta, "title-wrap")
        tw2.set("xml:lang", extra_lang)
        intro2 = metadata.get(f"title_intro_{extra_lang}", "")
        if intro2:
            SubElement(tw2, "intro").text = intro2
        SubElement(tw2, "main").text = extra_main
        compl2 = metadata.get(f"title_part_{extra_lang}", "")
        if compl2:
            SubElement(tw2, "compl").text = compl2

    # --- doc-ident ---
    doc_ident = SubElement(iso_meta, "doc-ident")
    sdo_name = flavor.display_name if flavor else "ISO"
    sdo_el = SubElement(doc_ident, "sdo")
    sdo_el.text = sdo_name

    docnumber = metadata.get("docnumber", "")
    partnumber = metadata.get("partnumber", "")
    proj_id = SubElement(doc_ident, "proj-id")
    proj_text = f"{sdo_name} {docnumber}" if docnumber else sdo_name
    if partnumber:
        proj_text += f"-{partnumber}"
    proj_id.text = proj_text

    lang_el = SubElement(doc_ident, "language")
    lang_el.text = lang

    stage = metadata.get("stage", "")
    release_ver = SubElement(doc_ident, "release-version")
    release_ver.text = stage if stage else "IS"

    # --- std-ident ---
    std_ident = SubElement(iso_meta, "std-ident")

    originator_el = SubElement(std_ident, "originator")
    originator_el.text = sdo_name

    doc_type = metadata.get("doc_type", "is")
    doc_type_el = SubElement(std_ident, "doc-type")
    doc_type_el.text = doc_type.lower()

    if docnumber:
        doc_num_el = SubElement(std_ident, "doc-number")
        doc_num_el.text = docnumber

    if partnumber:
        part_num_el = SubElement(std_ident, "part-number")
        part_num_el.text = partnumber

    edition = metadata.get("edition", "")
    if edition:
        edition_el = SubElement(std_ident, "edition")
        edition_el.text = edition

    copyright_year = metadata.get("copyright_year", "")
    if copyright_year:
        version_el = SubElement(std_ident, "version")
        version_el.text = copyright_year

    # --- comm-ref ---
    tc = metadata.get("technical_committee", "")
    if tc:
        comm_ref = SubElement(iso_meta, "comm-ref")
        comm_ref.text = tc

    # --- secretariat ---
    secretariat = metadata.get("secretariat", "")
    if secretariat:
        sec_el = SubElement(iso_meta, "secretariat")
        sec_el.text = secretariat

    # --- permissions (copyright) ---
    if copyright_year:
        permissions = SubElement(iso_meta, "permissions")
        holder_name = sdo_name
        stmt = SubElement(permissions, "copyright-statement")
        stmt.text = f"\u00a9 {holder_name} {copyright_year}"
        yr_el = SubElement(permissions, "copyright-year")
        yr_el.text = copyright_year
        holder_el = SubElement(permissions, "copyright-holder")
        holder_el.text = holder_name

    # --- pub-date ---
    pub_date_str = metadata.get("publication_date", "")
    if pub_date_str:
        pub_date = SubElement(iso_meta, "pub-date")
        pub_date.set("pub-type", "pub")
        parts = pub_date_str.split("-")
        yr_el2 = SubElement(pub_date, "year")
        yr_el2.text = parts[0]
        if len(parts) >= 2:
            month_el = SubElement(pub_date, "month")
            month_el.text = parts[1]
        if len(parts) >= 3:
            day_el = SubElement(pub_date, "day")
            day_el.text = parts[2]


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def _build_body(
    root: Element,
    soup: BeautifulSoup,
    flavor: FlavorSpec | None,
    footnote_map: dict[str, str] | None = None,
    lang: str = "en",
) -> None:
    """Build the ``<body>`` element from HTML body content."""
    body_el = SubElement(root, "body")

    body = soup.find("body")
    if body is None:
        return

    fn_map = footnote_map or {}

    for section in _top_level_sections(soup):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue

        text = heading.get_text(" ", strip=True)

        # Skip annexes and bibliography — handled in <back>
        if _ANNEX_RE.match(text) or _BIB_RE.match(text):
            continue

        _convert_section(body_el, section, footnote_map=fn_map, lang=lang)


def _top_level_sections(soup: BeautifulSoup) -> list:
    """Return the document's top-level ``<section>`` elements.

    Looks under ``<main>`` (where Bikeshed places content) and falls back to
    ``<body>``. Bikeshed emits a flat ``<hN>`` + sibling stream with no
    ``<section>`` wrappers; when none are found, the headings are grouped into
    nested ``<section>`` trees in place (idempotent — subsequent calls reuse
    them). Shared by ``_build_body`` and ``_build_back`` so both see the same
    structure.
    """
    body = soup.find("body")
    if body is None:
        return []
    container = soup.find("main") or body
    sections = container.find_all("section", recursive=False)
    if not sections:
        _sectionize_headings(soup, container)
        sections = container.find_all("section", recursive=False)
    return sections


def _sectionize_headings(soup: BeautifulSoup, container: object) -> int:
    """Wrap a flat ``<hN>`` + following-sibling stream into nested ``<section>``.

    Bikeshed output is not sectioned; STS conversion is section-driven. This
    groups each heading and the content that follows it (until the next heading
    of the same or shallower level) into a ``<section>`` nested by heading
    level. Returns the number of sections created. No-op if *container* has no
    headings.
    """
    from bs4 import NavigableString, Tag

    def _level(node: object) -> int | None:
        if isinstance(node, Tag) and node.name and len(node.name) == 2 and node.name[0] == "h":
            try:
                return int(node.name[1])
            except ValueError:
                return None
        return None

    nodes = [n for n in container.children if isinstance(n, (Tag, NavigableString))]
    for n in nodes:
        n.extract()

    top: list = []
    stack: list[tuple[int, Tag]] = []  # (level, section)
    created = 0
    for node in nodes:
        lv = _level(node)
        if lv is not None:
            while stack and stack[-1][0] >= lv:
                stack.pop()
            sec = soup.new_tag("section")
            created += 1
            hid = node.get("id") if isinstance(node, Tag) else None
            if hid:
                sec["id"] = hid
            (stack[-1][1] if stack else _TopSink(top)).append(sec)
            sec.append(node)
            stack.append((lv, sec))
        else:
            (stack[-1][1] if stack else _TopSink(top)).append(node)

    for n in top:
        container.append(n)
    return created


class _TopSink:
    """Collect top-level (pre-heading / un-nested) nodes into a list."""

    def __init__(self, lst: list) -> None:
        self._lst = lst

    def append(self, node: object) -> None:
        self._lst.append(node)


def _extract_label(heading_text: str) -> tuple[str, str]:
    """Extract the clause number label and clean title from heading text.

    Returns ``(label, title)`` where *label* may be empty.
    """
    m = _SECNO_RE.match(heading_text)
    if m:
        return m.group(1), heading_text[m.end() :].strip()
    return "", heading_text


def _sec_type_for(heading_text: str) -> str | None:
    """Return the ``sec-type`` attribute value for known section types."""
    if _SCOPE_RE.match(heading_text):
        return "scope"
    if _NORMREFS_RE.match(heading_text):
        return "norm-refs"
    if _TERMS_RE.match(heading_text):
        return "terms"
    return None


def _infer_ref_type(rid: str) -> str:
    """Infer STS ``ref-type`` from an anchor ID."""
    rid_lower = rid.lower()
    if rid_lower.startswith(("table-", "tbl-", "tab-")):
        return "table"
    if rid_lower.startswith(("fig-", "figure-")):
        return "fig"
    if rid_lower.startswith(("eq-",)):
        return "disp-formula"
    if rid_lower.startswith(("req-",)):
        return "other"
    if rid_lower.startswith(("term-", "dfn-")):
        # Terms are emitted as <def-item> inside <def-list> within a <sec>;
        # NISO STS ref-types has no "term" value, so reference them as "sec".
        return "sec"
    return "sec"


def _term_anchor_id(dts: list) -> str:
    """Return the cross-reference anchor id for a term entry.

    The id may sit directly on a ``<dt>`` or on a descendant carrying the
    anchor (``<span id="term-…">``, ``<dfn id="…">``). Prefers an explicit
    ``term-*``/``dfn-*`` id; otherwise falls back to the first id found.
    """
    fallback = ""
    for dt in dts:
        candidates = [dt]
        if hasattr(dt, "find_all"):
            candidates += dt.find_all(["span", "dfn"], recursive=True)
        for el in candidates:
            eid = el.get("id", "") if hasattr(el, "get") else ""
            if not eid:
                continue
            if eid.startswith(("term-", "dfn-")):
                return eid
            fallback = fallback or eid
    return fallback


def _code_language(pre_elem: object) -> str:
    """Extract programming language from <pre> or <code> class attribute."""
    for elem in (pre_elem, pre_elem.find("code") if hasattr(pre_elem, "find") else None):
        if elem is None:
            continue
        classes = " ".join(elem.get("class", []))
        m = _CODE_LANG_RE.search(classes)
        if m:
            return m.group(1) or m.group(2) or m.group(3) or ""
    return ""


# ---------------------------------------------------------------------------
# Inline content helpers
# ---------------------------------------------------------------------------


def _append_text(parent: Element, text: str, children: list[Element]) -> None:
    """Append *text* to the appropriate text/tail slot of *parent*."""
    if not text:
        return
    if not children:
        parent.text = (parent.text or "") + text
    else:
        last = children[-1]
        last.tail = (last.tail or "") + text


def _fill_inline(
    xml_el: Element,
    html_el: object,
    footnote_map: dict[str, str] | None = None,
) -> None:
    """Recursively copy inline HTML content into an XML element.

    Handles: text nodes, <a href> → <xref>/<ext-link>, <strong> → <bold>,
    <em> → <italic>, <code>/<tt> → <code>, <sup>, <sub>, <span>.

    Footnote references (<a class="footnote-ref" href="#fn-N">) are converted
    to inline ``<fn id="fn-N">`` elements using *footnote_map*.  The ``<sup>``
    wrapper around footnote refs is suppressed so that STS handles numbering.
    """
    fn_map = footnote_map or {}
    children_added: list[Element] = []

    for child in html_el.children:
        if not hasattr(child, "name") or child.name is None:
            text = str(child)
            if text:
                _append_text(xml_el, text, children_added)
            continue

        name = child.name

        if name == "a":
            href = child.get("href", "")
            classes = child.get("class", [])

            # Footnote reference: <a class="footnote-ref" href="#fn-N">
            # Emit a reference-only <fn rid="fn-N"/>; content goes in <fn-group>
            if "footnote-ref" in classes and href.startswith("#"):
                fn_id = href[1:]
                fn_el = SubElement(xml_el, "fn")
                fn_el.set("rid", fn_id)
                children_added.append(fn_el)

            elif href.startswith("#"):
                rid = href[1:]
                # Navigation chrome (self-links, "back to ToC", etc.) are not
                # real cross-references and have no STS target — emit their text
                # only, so we don't produce dangling <xref rid="toc">.
                _nav = {"toc", "contents", "top"}
                _nav_classes = {"self-link", "back-to-top", "toc-backref", "back-to-toc"}
                if rid in _nav or (set(classes) & _nav_classes):
                    _append_text(xml_el, child.get_text(strip=True), children_added)
                else:
                    inner = SubElement(xml_el, "xref")
                    inner.set("ref-type", _infer_ref_type(rid))
                    inner.set("rid", rid)
                    inner.text = child.get_text(strip=True)
                    children_added.append(inner)
            elif href:
                inner = SubElement(xml_el, "ext-link")
                inner.set("xlink:href", href)
                inner.set("ext-link-type", "uri")
                inner.text = child.get_text(strip=True)
                children_added.append(inner)
            else:
                _fill_inline(xml_el, child, fn_map)

        elif name in ("strong", "b"):
            inner = SubElement(xml_el, "bold")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name in ("em", "i"):
            inner = SubElement(xml_el, "italic")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name in ("code", "tt"):
            inner = SubElement(xml_el, "monospace")
            inner.text = child.get_text()
            children_added.append(inner)

        elif name == "sup":
            # Detect pattern: <sup><a href="#fn-N">N</a></sup>
            # Suppress the <sup> wrapper; emit <fn> instead.
            a_child = None
            for node in child.children:
                if hasattr(node, "name") and node.name == "a":
                    a_child = node
                    break
            if a_child is not None:
                a_href = a_child.get("href", "")
                if a_href.startswith("#fn-"):
                    fn_id = a_href[1:]
                    fn_el = SubElement(xml_el, "fn")
                    fn_el.set("rid", fn_id)
                    children_added.append(fn_el)
                    continue
            inner = SubElement(xml_el, "sup")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name == "sub":
            inner = SubElement(xml_el, "sub")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name == "img":
            inline_graphic = SubElement(xml_el, "inline-graphic")
            src = child.get("src", "")
            if src:
                inline_graphic.set("xlink:href", src)
            alt = child.get("alt", "")
            if alt:
                inline_graphic.set("xlink:title", alt)
            children_added.append(inline_graphic)

        elif name in ("abbr", "acronym"):
            abbrev_el = SubElement(xml_el, "abbrev")
            abbrev_el.text = child.get_text()
            title = child.get("title", "")
            if title:
                def_el = SubElement(abbrev_el, "def")
                def_p = SubElement(def_el, "p")
                def_p.text = title
            children_added.append(abbrev_el)

        elif name == "dfn":
            inner = SubElement(xml_el, "term")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name == "ins":
            inner = SubElement(xml_el, "styled-content")
            inner.set("style", "change-type:addition")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name == "del":
            inner = SubElement(xml_el, "styled-content")
            inner.set("style", "change-type:deletion")
            _fill_inline(inner, child, fn_map)
            children_added.append(inner)

        elif name == "span":
            classes = child.get("class", [])
            # Inline math span with data-tex
            if any(c in classes for c in ("math", "formula", "inline-math", "math-expr")):
                tex = child.get("data-tex", "")
                if not tex:
                    # Try extracting from MathML annotation
                    ann = child.find("annotation", {"encoding": "application/x-tex"})
                    if ann:
                        tex = ann.get_text(strip=True)
                if not tex:
                    # Fall back to text content (math-expr spans store raw math text)
                    tex = child.get_text(strip=True)
                if tex:
                    inner = SubElement(xml_el, "inline-formula")
                    tex_el = SubElement(inner, "tex-math")
                    tex_el.text = tex
                    # Emit MathML alongside TeX when available (NISO STS 1.2)
                    mml_et = _extract_mml_et(child)
                    if mml_et is not None:
                        inner.append(mml_et)
                    children_added.append(inner)
                    continue
            _fill_inline(xml_el, child, fn_map)

        else:
            _fill_inline(xml_el, child, fn_map)


def _convert_p(
    parent: Element,
    p_elem: object,
    footnote_map: dict[str, str] | None = None,
) -> Element:
    """Convert a ``<p>`` element to STS ``<p>``, preserving inline markup."""
    req_id = p_elem.get("data-req-id", "")
    req_global = p_elem.get("data-req-global", "")

    if req_id:
        named = SubElement(parent, "named-content")
        named.set("content-type", "requirement")
        named.set("id", req_id)
        if req_global:
            named.set("specific-use", req_global)
        subject = p_elem.get("data-req-subject", "")
        if subject:
            named.set("subject", subject)
        verification = p_elem.get("data-req-verification", "")
        if verification:
            named.set("{http://www.w3.org/XML/1998/namespace}lang", "en")
            label_el = SubElement(named, "label")
            label_el.set("specific-use", f"verification-{verification}")
            label_el.text = req_id
        p_el = SubElement(named, "p")
    else:
        p_el = SubElement(parent, "p")

    elem_lang = p_elem.get("lang", "")
    if elem_lang:
        p_el.set("xml:lang", elem_lang)

    _fill_inline(p_el, p_elem, footnote_map)
    return p_el


# ---------------------------------------------------------------------------
# Section conversion
# ---------------------------------------------------------------------------


def _convert_section(
    parent: Element,
    section: object,
    counters: _NoteCounters | None = None,
    footnote_map: dict[str, str] | None = None,
    lang: str = "en",
) -> None:
    """Convert an HTML ``<section>`` to an STS ``<sec>``."""
    heading = section.find(HEADING_RE)
    raw_text = heading.get_text(" ", strip=True) if heading else ""

    label, title_text = _extract_label(raw_text)
    sec_type = _sec_type_for(raw_text)

    sec_id = section.get("id", "")
    attrs: dict[str, str] = {}
    if sec_id:
        attrs["id"] = sec_id
    if sec_type:
        attrs["sec-type"] = sec_type

    if sec_type == "terms":
        _convert_terms_section(parent, section, attrs, label, title_text, lang=lang)
        return

    sec_el = SubElement(parent, "sec", **attrs)

    sec_lang = section.get("lang", "")
    if sec_lang:
        sec_el.set("xml:lang", sec_lang)

    if label:
        label_el = SubElement(sec_el, "label")
        label_el.text = label

    if title_text:
        title_el = SubElement(sec_el, "title")
        title_el.text = title_text

    # Top-level sections own their own note/example counters
    own_counters = counters if counters is not None else _NoteCounters()
    _convert_children(sec_el, section, own_counters, footnote_map=footnote_map or {}, lang=lang)


def _convert_terms_section(
    parent: Element,
    section: object,
    attrs: dict[str, str],
    label: str,
    title_text: str,
    lang: str = "en",
) -> None:
    """Convert a terms-and-definitions section with TBX markup."""
    sec_el = SubElement(parent, "sec", **attrs)

    if label:
        label_el = SubElement(sec_el, "label")
        label_el.text = label

    if title_text:
        title_el = SubElement(sec_el, "title")
        title_el.text = title_text

    for child in section.children:
        if not hasattr(child, "name") or child.name is None:
            continue
        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue

        if child.name == "section":
            sub_heading = child.find(HEADING_RE)
            sub_text = sub_heading.get_text(" ", strip=True) if sub_heading else ""
            sub_label, sub_title = _extract_label(sub_text)
            sub_id = child.get("id", "")

            term_sec_attrs: dict[str, str] = {}
            if sub_id:
                term_sec_attrs["id"] = sub_id

            term_sec = SubElement(sec_el, "term-sec", **term_sec_attrs)

            if sub_label:
                lbl = SubElement(term_sec, "label")
                lbl.text = sub_label

            tbx_entry = SubElement(term_sec, "tbx:termEntry")
            lang_set = SubElement(tbx_entry, "tbx:langSet")
            lang_set.set("xml:lang", lang)

            # STS TBX subset: <langSet> is (definition | crossReference | ...)*
            # followed by <tig>+. The definition is a <tbx:definition> sibling
            # that precedes the <tig> (which holds only the term + grammar).
            defn_p = child.find("p")
            if defn_p:
                definition = SubElement(lang_set, "tbx:definition")
                _fill_inline(definition, defn_p)

            tig = SubElement(lang_set, "tbx:tig")
            term_el = SubElement(tig, "tbx:term")
            term_el.text = sub_title

        elif child.name == "p":
            p_el = SubElement(sec_el, "p")
            _fill_inline(p_el, child)

        elif child.name == "dl":
            dts = child.find_all("dt", recursive=False)
            for dt in dts:
                term_sec = SubElement(sec_el, "term-sec")
                tbx_entry = SubElement(term_sec, "tbx:termEntry")
                lang_set = SubElement(tbx_entry, "tbx:langSet")
                lang_set.set("xml:lang", lang)

                tig = SubElement(lang_set, "tbx:tig")
                term_el = SubElement(tig, "tbx:term")
                term_el.text = dt.get_text(strip=True)

                dd = dt.find_next_sibling("dd")
                if dd:
                    descrip_grp = SubElement(lang_set, "tbx:descripGrp")
                    descrip = SubElement(descrip_grp, "tbx:descrip")
                    descrip.set("type", "definition")
                    _fill_inline(descrip, dd)


# ---------------------------------------------------------------------------
# Back matter
# ---------------------------------------------------------------------------


def _build_back(
    root: Element,
    soup: BeautifulSoup,
    metadata: dict[str, str],
    flavor: FlavorSpec | None,
    footnote_map: dict[str, str] | None = None,
) -> None:
    """Build the ``<back>`` element with annexes and bibliography."""
    body = soup.find("body")
    if body is None:
        return

    fn_map = footnote_map or {}
    lang = metadata.get("language", "en")

    annexes: list = []
    bib_sections: list = []

    for section in _top_level_sections(soup):
        heading = section.find(HEADING_RE)
        if heading is None:
            continue
        text = heading.get_text(" ", strip=True)

        if _ANNEX_RE.match(text):
            annexes.append(section)
        elif _BIB_RE.match(text):
            bib_sections.append(section)

    if not annexes and not bib_sections and not fn_map:
        return

    back = SubElement(root, "back")

    # --- Annexes ---
    if annexes:
        app_group = SubElement(back, "app-group")
        for section in annexes:
            heading = section.find(HEADING_RE)
            text = heading.get_text(" ", strip=True) if heading else ""
            m = _ANNEX_RE.match(text)

            content_type = "informative"
            if "(normative)" in text.lower():
                content_type = "normative"

            sec_id = section.get("id", "")
            if not sec_id and m:
                sec_id = f"annex-{m.group(1).lower()}"

            app_attrs: dict[str, str] = {"content-type": content_type}
            if sec_id:
                app_attrs["id"] = sec_id

            app_el = SubElement(app_group, "app", **app_attrs)

            if m:
                lbl = SubElement(app_el, "label")
                lbl.text = f"Annex {m.group(1)}"

            title_el = SubElement(app_el, "title")
            title_el.text = text

            _convert_children(app_el, section, _NoteCounters(), footnote_map=fn_map, lang=lang)

    # --- Bibliography ---
    if bib_sections:
        for section in bib_sections:
            heading = section.find(HEADING_RE)
            text = heading.get_text(" ", strip=True) if heading else ""

            sec_id = section.get("id", "references")
            content_type = "bibl"
            if re.match(r"(?i)normative", text):
                content_type = "norm-refs"

            ref_list_attrs: dict[str, str] = {"content-type": content_type}
            if sec_id:
                ref_list_attrs["id"] = sec_id

            ref_list = SubElement(back, "ref-list", **ref_list_attrs)

            title_el = SubElement(ref_list, "title")
            title_el.text = text

            for i, li in enumerate(section.find_all("li"), start=1):
                # Try to use a Bikeshed-generated ID on the li element
                li_id = li.get("id", f"ref-{i}")
                ref_attrs: dict[str, str] = {"id": li_id}
                ref_el = SubElement(ref_list, "ref", **ref_attrs)
                _convert_bib_item(ref_el, li)

    # --- Footnote group ---
    # Collect all fn content from the footnote_map and emit a single <fn-group>
    # at the end of <back>. Inline <fn rid="..."/> elements reference these.
    if fn_map:
        from bs4 import BeautifulSoup as _BS

        fn_group = SubElement(back, "fn-group")
        for i, (fn_id, fn_content) in enumerate(fn_map.items(), start=1):
            fn_el = SubElement(fn_group, "fn")
            fn_el.set("id", fn_id)
            lbl = SubElement(fn_el, "label")
            lbl.text = str(i)
            if fn_content:
                frag = _BS(fn_content, "html.parser")
                for p in frag.find_all("p"):
                    p_inner = SubElement(fn_el, "p")
                    _fill_inline(p_inner, p, fn_map)


def _convert_bib_item(ref_el: Element, li: object) -> None:
    """Convert a bibliography ``<li>`` to STS ``<std>`` or ``<mixed-citation>``.

    When the ``<li>`` carries ``data-relaton-*`` attributes (injected by
    :func:`~specbuild.standards.relaton.enrich_bibliography_soup`), those are
    used to build a richer ``<std>`` element.  Falls back to text-parsing for
    plain entries.
    """
    # --- Relaton-enriched path ---
    relaton_title = li.get("data-relaton-title", "")
    if relaton_title:
        text = li.get_text(strip=True)
        docid = li.get("data-relaton-docid", "") or (text.split()[0] if text else "")
        std = SubElement(ref_el, "std")
        std_id = SubElement(std, "std-id")
        std_id.set("std-id-type", _classify_docid(docid))
        std_id.text = docid
        std_ref = SubElement(std, "std-ref")
        std_ref.text = docid
        title_el = SubElement(std, "title")
        title_el.text = relaton_title
        year = li.get("data-relaton-year", "")
        if year:
            pub_date = SubElement(std, "pub-date")
            pub_date.set("pub-type", "pub")
            yr_el = SubElement(pub_date, "year")
            yr_el.text = year
        url = li.get("data-relaton-url", "")
        if url:
            uri_el = SubElement(std, "uri")
            uri_el.text = url
        return

    # --- Text-parse fallback ---
    raw_text = li.get_text(strip=True)
    m = _STD_BIB_RE.match(raw_text)
    if m:
        docid = m.group(1).strip()
        remainder = m.group(2).strip()
        std = SubElement(ref_el, "std")
        std_id = SubElement(std, "std-id")
        std_id.set("std-id-type", _classify_docid(docid))
        std_id.text = docid
        std_ref = SubElement(std, "std-ref")
        std_ref.text = docid
        if remainder:
            title_el = SubElement(std, "title")
            title_text = re.sub(r"\s*\(\d{4}\)\s*$", "", remainder).strip()
            title_el.text = title_text
            yr_m = re.search(r"\((\d{4})\)\s*$", remainder)
            if yr_m:
                pub_date = SubElement(std, "pub-date")
                pub_date.set("pub-type", "pub")
                yr_el = SubElement(pub_date, "year")
                yr_el.text = yr_m.group(1)
    else:
        citation = SubElement(ref_el, "mixed-citation")
        citation.text = raw_text


def _classify_docid(docid: str) -> str:
    """Return the ``std-id-type`` for a document ID string."""
    upper = docid.upper()
    if upper.startswith(("ISO", "IEC")):
        return "iso"
    if upper.startswith("ITU"):
        return "itu"
    if upper.startswith("IEEE"):
        return "ieee"
    if upper.startswith(("RFC", "IETF")):
        return "ietf"
    return "other"


# ---------------------------------------------------------------------------
# Child element conversion
# ---------------------------------------------------------------------------


def _convert_list(parent_el: Element, list_html: object, fn_map: dict[str, str]) -> None:
    """Recursively convert an HTML ``<ul>``/``<ol>`` to an STS ``<list>``.

    Each ``<li>`` is converted to a ``<list-item>`` containing a ``<p>`` for
    its inline/text content.  Any directly-nested ``<ul>``/``<ol>`` elements
    are recursed into and appended after the ``<p>``.
    """
    list_el = SubElement(parent_el, "list")
    list_el.set("list-type", "bullet" if list_html.name == "ul" else "order")
    for li in list_html.find_all("li", recursive=False):
        item = SubElement(list_el, "list-item")
        _convert_p(item, li, footnote_map=fn_map)
        for nested in li.find_all(["ul", "ol"], recursive=False):
            _convert_list(item, nested, fn_map)


def _convert_children(
    parent: Element,
    section: object,
    counters: _NoteCounters,
    footnote_map: dict[str, str] | None = None,
    lang: str = "en",
) -> None:
    """Convert child elements of a section to STS XML."""
    fn_map = footnote_map or {}

    for child in section.children:
        if not hasattr(child, "name") or child.name is None:
            continue

        if child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue

        if child.name == "p":
            _convert_p(parent, child, footnote_map=fn_map)

        elif child.name == "section":
            # Skip footnote sections — they are already inlined as <fn>
            classes = child.get("class", [])
            if "footnotes" in classes:
                continue
            _convert_section(parent, child, counters, footnote_map=fn_map, lang=lang)

        elif child.name == "table":
            _convert_table(parent, child)

        elif child.name == "figure":
            _convert_figure(parent, child)

        elif child.name in ("ul", "ol"):
            _convert_list(parent, child, fn_map)

        elif child.name == "dl":
            def_list = SubElement(parent, "def-list")
            # A definition entry may have several <dt> before its <dd>
            # (e.g. ISO terms: one <dt> for the number, one for the term name).
            # Group consecutive <dt> siblings together, carry the entry's anchor
            # id (preferring a term-*/dfn-* id on the <dt> or a descendant) onto
            # <def-item>, and join the <dt> texts into a single <term>.
            entries: list[tuple[list, object]] = []
            pending: list = []
            for node in child.find_all(["dt", "dd"], recursive=False):
                if node.name == "dt":
                    pending.append(node)
                else:  # dd closes the current group
                    entries.append((pending, node))
                    pending = []
            if pending:  # trailing <dt> with no <dd>
                entries.append((pending, None))

            for dts, dd in entries:
                def_item = SubElement(def_list, "def-item")
                item_id = _term_anchor_id(dts)
                if item_id:
                    def_item.set("id", item_id)
                term_el = SubElement(def_item, "term")
                term_el.text = " ".join(dt.get_text(" ", strip=True) for dt in dts).strip()
                if dd is not None:
                    def_el = SubElement(def_item, "def")
                    _convert_p(def_el, dd, footnote_map=fn_map)

        elif child.name == "blockquote":
            disp = SubElement(parent, "disp-quote")
            attrib = child.get("cite", "")
            if attrib:
                disp.set("specific-use", attrib)
            _convert_children(disp, child, counters, footnote_map=fn_map, lang=lang)

        elif child.name == "aside":
            boxed = SubElement(parent, "boxed-text")
            classes = child.get("class", [])
            if classes:
                boxed.set("content-type", " ".join(classes))
            _convert_children(boxed, child, counters, footnote_map=fn_map, lang=lang)

        elif child.name == "details":
            boxed = SubElement(parent, "boxed-text")
            boxed.set("content-type", "collapsible")
            summary = child.find("summary")
            if summary:
                title_el = SubElement(boxed, "caption")
                title_p = SubElement(title_el, "title")
                title_p.text = summary.get_text(strip=True)
            _convert_children(boxed, child, counters, footnote_map=fn_map, lang=lang)

        elif child.name == "pre":
            classes = child.get("class", [])
            code_lang = _code_language(child)
            if not code_lang and any(c in classes for c in ("sdl", "sdl-code", "sdl-syntax")):
                code_lang = "sdl"
            code = SubElement(parent, "code")
            # NISO STS <code> has no @preformat-type (that belongs to
            # <preformat>); it does allow @xml:space and @language/@code-type.
            code.set("xml:space", "preserve")
            if code_lang:
                code.set("language", code_lang)
            code.text = child.get_text()

        elif child.name == "ins":
            _convert_children(parent, child, counters, footnote_map=fn_map, lang=lang)

        elif child.name == "del":
            # Deleted content: wrap in milestone to preserve change semantics
            ms_start = SubElement(parent, "milestone-start")
            ms_start.set("rationale", "deletion")
            _convert_children(parent, child, counters, footnote_map=fn_map, lang=lang)
            ms_end = SubElement(parent, "milestone-end")
            ms_end.set("rationale", "deletion")

        elif child.name == "div":
            classes = child.get("class", [])

            # Skip footnotes containers — already inlined as <fn>
            if "footnotes" in classes:
                continue

            if "equation-wrapper" in classes:
                _convert_disp_formula(parent, child, counters)

            elif "normative-note" in classes:
                norm_note = SubElement(parent, "normative-note")
                lbl = SubElement(norm_note, "label")
                lbl.text = "NOTE"
                for p in child.find_all("p"):
                    _convert_p(norm_note, p, footnote_map=fn_map)

            elif "note" in classes:
                counters.notes += 1
                non_norm = SubElement(parent, "non-normative-note")
                lbl = SubElement(non_norm, "label")
                lbl.text = f"NOTE {counters.notes}" if counters.notes > 1 else "NOTE"
                for p in child.find_all("p"):
                    _convert_p(non_norm, p, footnote_map=fn_map)

            elif "example" in classes:
                counters.examples += 1
                non_norm = SubElement(parent, "non-normative-example")
                lbl = SubElement(non_norm, "label")
                lbl.text = f"EXAMPLE {counters.examples}" if counters.examples > 1 else "EXAMPLE"
                for p in child.find_all("p"):
                    _convert_p(non_norm, p, footnote_map=fn_map)

            elif "admonition" in classes or "warning" in classes:
                # Warning/admonition boxes → non-normative-note with type
                non_norm = SubElement(parent, "non-normative-note")
                note_type = next(
                    (c for c in classes if c in ("warning", "caution", "important", "tip")),
                    "note",
                )
                non_norm.set("content-type", note_type)
                lbl = SubElement(non_norm, "label")
                lbl.text = note_type.upper()
                for p in child.find_all("p"):
                    _convert_p(non_norm, p, footnote_map=fn_map)

            else:
                # Generic div — recurse into children
                _convert_children(parent, child, counters, footnote_map=fn_map, lang=lang)


def _bs4_elem_to_et(bs_elem: object) -> Element:
    """Recursively convert a BS4 element to an :class:`xml.etree.ElementTree.Element`.

    Rules applied during conversion:
    - The root ``<math>`` element is tagged with the MathML namespace in Clark
      notation: ``{http://www.w3.org/1998/Math/MathML}math``.
    - All descendant MathML elements receive the same MathML namespace.
    - ``<svg>``, ``<mjx-*>``, and ``<annotation>`` children are skipped
      (SVG is display-only; annotation carries the TeX source we already have).
    - An explicit ``xmlns`` attribute whose value is the MathML namespace URI
      is dropped from the attrib dict (it becomes the Clark-notation namespace).
    """
    _SKIP_TAGS = {"svg", "annotation"}

    def _is_mjx(tag: str) -> bool:
        return tag.startswith("mjx-")

    def _convert(elem: object, parent_ns: str | None) -> Element | None:
        tag = elem.name  # type: ignore[attr-defined]
        if tag is None:
            return None
        if tag in _SKIP_TAGS or _is_mjx(tag):
            return None

        # Determine namespace for this element: use MathML NS for math elements
        explicit_xmlns = elem.get("xmlns", "")  # type: ignore[attr-defined]
        if explicit_xmlns == _MML_NS or parent_ns == _MML_NS or tag == "math":
            ns = _MML_NS
        else:
            ns = parent_ns or ""

        clark_tag = f"{{{ns}}}{tag}" if ns else tag

        # Build attribute dict, stripping xmlns (handled via Clark notation)
        attribs: dict[str, str] = {}
        for k, v in (elem.attrs or {}).items():  # type: ignore[union-attr]
            if k == "xmlns":
                continue
            if isinstance(v, list):
                v = " ".join(v)
            attribs[k] = str(v)

        et_el = Element(clark_tag, attribs)

        # Collect children, interleaving text nodes (tail handling via ET model)
        pending_text: list[str] = []
        last_child_et: Element | None = None

        for node in elem.children:  # type: ignore[attr-defined]
            if not hasattr(node, "name") or node.name is None:
                # Text node
                pending_text.append(str(node))
                continue

            child_et = _convert(node, ns)
            if child_et is None:
                # Skipped element — its text content becomes pending text
                pending_text.append(node.get_text())
                continue

            # Flush pending_text as text/tail
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

        # Flush remaining text
        text_str = "".join(pending_text)
        if text_str:
            if last_child_et is None:
                et_el.text = (et_el.text or "") + text_str
            else:
                last_child_et.tail = (last_child_et.tail or "") + text_str

        return et_el

    return _convert(bs_elem, None)  # type: ignore[return-value]


def _extract_mml_et(container_elem: object) -> Element | None:
    """Search *container_elem* for a ``<math>`` element and convert it to ET.

    Handles both direct ``<math>`` children and MathJax's
    ``<mjx-container> > <math>`` nesting.  Returns ``None`` if no MathML is
    found or if conversion raises an exception.
    """
    try:
        # Direct <math> child first; then descend into mjx-container
        math_bs = container_elem.find("math")  # type: ignore[attr-defined]
        if math_bs is None:
            return None
        et_el = _bs4_elem_to_et(math_bs)
        # Sanity-check: tag must include MathML namespace
        if et_el is not None and "MathML" in et_el.tag:
            return et_el
        return None
    except Exception:
        return None


def _convert_disp_formula(parent: Element, wrapper_div: object, counters: _NoteCounters) -> None:
    """Convert an equation-wrapper ``<div>`` to STS ``<disp-formula>``."""
    # Get the equation ID from the number span
    num_span = wrapper_div.find("span", class_="equation-number")
    eq_id = num_span.get("id", "") if num_span else ""
    label_text = num_span.get_text(strip=True) if num_span else ""

    tex = wrapper_div.get("data-tex", "")
    if not tex:
        # Try MathML annotation inside mjx-container
        ann = wrapper_div.find("annotation", {"encoding": "application/x-tex"})
        if ann:
            tex = ann.get_text(strip=True)
    if not tex:
        # Fall back to $$...$$ paragraph text
        for p in wrapper_div.find_all("p"):
            text = p.get_text(strip=True)
            m = _DISPLAY_MATH_RE.match(text)
            if m:
                tex = m.group(1).strip()
                break

    counters.equations += 1
    attrs: dict[str, str] = {}
    if eq_id:
        attrs["id"] = eq_id

    formula_el = SubElement(parent, "disp-formula", **attrs)
    if label_text:
        lbl = SubElement(formula_el, "label")
        lbl.text = label_text

    if tex:
        tex_el = SubElement(formula_el, "tex-math")
        tex_el.text = tex
    else:
        # No TeX source available — emit empty tex-math
        SubElement(formula_el, "tex-math")

    # Emit MathML alongside TeX when available (NISO STS 1.2 supports both)
    mml_et = _extract_mml_et(wrapper_div)
    if mml_et is not None:
        formula_el.append(mml_et)


def _extract_cell_attrs(cell: object) -> dict[str, str]:
    """Extract colspan/rowspan/align/scope from an HTML table cell element."""
    attrs: dict[str, str] = {}
    if cell.get("colspan"):
        attrs["colspan"] = str(cell["colspan"])
    if cell.get("rowspan"):
        attrs["rowspan"] = str(cell["rowspan"])
    if cell.get("align"):
        attrs["align"] = cell["align"]
    if cell.get("scope"):
        attrs["scope"] = cell["scope"]
    return attrs


def _convert_table(parent: Element, table: object) -> None:
    """Convert an HTML ``<table>`` to an STS ``<table-wrap>`` with full content."""
    # Anchor id may live on the <table> or, per ISO/STS convention, on its
    # <caption> (Bikeshed/specbuild places table ids on the caption).
    caption_for_id = table.find("caption")
    table_id = table.get("id", "") or (caption_for_id.get("id", "") if caption_for_id else "")
    classes = table.get("class", [])
    attrs: dict[str, str] = {}
    if table_id:
        attrs["id"] = table_id
    if any(c in classes for c in ("sdl-syntax-table", "sdl-table", "sdl")):
        attrs["content-type"] = "sdl-syntax"

    table_wrap = SubElement(parent, "table-wrap", **attrs)

    caption_el = table.find("caption")
    if caption_el:
        caption_text = caption_el.get_text(strip=True)
        table_label_re = re.match(
            r"(Table\s+[\dA-Z]+(?:\.\d+)*)\s*[:\u2014\u2013\-]?\s*(.*)", caption_text
        )
        if table_label_re:
            lbl = SubElement(table_wrap, "label")
            lbl.text = table_label_re.group(1)
            remainder = table_label_re.group(2).strip()
            if remainder:
                cap = SubElement(table_wrap, "caption")
                title_el = SubElement(cap, "title")
                title_el.text = remainder
        else:
            cap = SubElement(table_wrap, "caption")
            title_el = SubElement(cap, "title")
            title_el.text = caption_text

    tbl_el = SubElement(table_wrap, "table")

    thead = table.find("thead")
    if thead:
        thead_el = SubElement(tbl_el, "thead")
        for tr in thead.find_all("tr", recursive=False):
            row_el = SubElement(thead_el, "tr")
            for cell in tr.find_all(["th", "td"], recursive=False):
                cell_tag = "th" if cell.name == "th" else "td"
                cell_el = SubElement(row_el, cell_tag, **_extract_cell_attrs(cell))
                _fill_inline(cell_el, cell)

    tbody_source = table.find("tbody") or table
    tbody_el = SubElement(tbl_el, "tbody")
    for tr in tbody_source.find_all("tr", recursive=False):
        if thead and tr.parent and tr.parent.name == "thead":
            continue
        row_el = SubElement(tbody_el, "tr")
        for cell in tr.find_all(["th", "td"], recursive=False):
            cell_tag = "th" if cell.name == "th" else "td"
            cell_el = SubElement(row_el, cell_tag, **_extract_cell_attrs(cell))
            _fill_inline(cell_el, cell)

    # Table footer notes
    tfoot = table.find("tfoot")
    if tfoot:
        for p in tfoot.find_all("p"):
            fn = SubElement(table_wrap, "table-wrap-foot")
            fn_p = SubElement(fn, "p")
            _fill_inline(fn_p, p)
            break  # one foot element is sufficient


def _convert_figure(parent: Element, figure: object) -> None:
    """Convert an HTML ``<figure>`` to an STS ``<fig>``."""
    fig_id = figure.get("id", "")
    attrs: dict[str, str] = {}
    if fig_id:
        attrs["id"] = fig_id

    fig_el = SubElement(parent, "fig", **attrs)

    figcaption = figure.find("figcaption")
    if figcaption:
        caption_text = figcaption.get_text(strip=True)
        fig_label_re = re.match(
            r"(Figure\s+[\dA-Z]+(?:\.\d+)*)\s*[:\u2014\u2013\-]?\s*(.*)", caption_text
        )
        if fig_label_re:
            lbl = SubElement(fig_el, "label")
            lbl.text = fig_label_re.group(1)
            remainder = fig_label_re.group(2).strip()
            if remainder:
                cap = SubElement(fig_el, "caption")
                title_el = SubElement(cap, "title")
                title_el.text = remainder
        else:
            cap = SubElement(fig_el, "caption")
            title_el = SubElement(cap, "title")
            title_el.text = caption_text

    # Image element
    img = figure.find("img")
    if img:
        graphic = SubElement(fig_el, "graphic")
        src = img.get("src", "")
        if src:
            graphic.set("xlink:href", src)
        alt = img.get("alt", "")
        if alt:
            # STS has no @alt on <graphic>; alternate text goes in <alt-text>.
            alt_el = SubElement(graphic, "alt-text")
            alt_el.text = alt

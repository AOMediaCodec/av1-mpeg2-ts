"""TBX (TermBase eXchange, ISO 30042) terminology export.

Extracts terms and definitions from compiled HTML and serialises them as
ISO 30042 TBX-Basic XML.  Uses only :mod:`xml.etree.ElementTree` (stdlib).

TBX is the standard interchange format for terminological data used by ISO,
OASIS, and other SDOs.  The generated files conform to TBX-Basic (the
recommended minimal dialect) with the ``dca`` (data-category as attribute)
style.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, tostring

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# TBX namespace URI (ISO 30042:2019 ed-2)
_TBX_NS = "urn:iso:std:iso:30042:ed-2"

# Pattern that matches a Terms and definitions heading
_TERMS_HEADING_RE = re.compile(r"(?i)(?:^\d+\s+)?terms?\s+and\s+definitions|^3\s+terms?$")

# Pattern to strip SOURCE: prefix and optional surrounding brackets
_SOURCE_PREFIX_RE = re.compile(r"^\[?SOURCE:\s*(.+?)\]?\s*$", re.IGNORECASE | re.DOTALL)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TbxTerm:
    """A single terminological entry for TBX serialisation."""

    term_id: str
    term: str
    definition: str
    part_of_speech: str = "noun"
    source: str = ""
    admitted_terms: list[str] = field(default_factory=list)
    deprecated_terms: list[str] = field(default_factory=list)
    term_number: str = ""
    # --- Extended fields (Feature 2: domain / hierarchy / multilingual / scope) ---
    domain: str = ""
    """Domain classification, e.g. 'Video Coding'."""
    parent_term_id: str = ""
    """ID of the parent concept (for hierarchical terms)."""
    alt_lang_terms: dict[str, str] = field(default_factory=dict)
    """Additional language renderings: {lang_tag: term_text}, e.g. {'fr': 'terme'}."""
    scope_note: str = ""
    """Usage/scope note from <dd class="scope-note">."""


# ---------------------------------------------------------------------------
# Extraction from BeautifulSoup HTML
# ---------------------------------------------------------------------------


def extract_terms_from_soup(soup: BeautifulSoup) -> list[TbxTerm]:
    """Extract :class:`TbxTerm` objects from a compiled HTML soup.

    Searches for the Terms and Definitions section (identified by its
    heading text), then iterates over ``<dt>`` / ``<dd>`` pairs in that
    section.

    Args:
        soup: Parsed HTML document.

    Returns:
        List of :class:`TbxTerm` instances, one per ``<dt>`` element found.
        Returns an empty list when no Terms section is present.
    """
    terms_section = _find_terms_section(soup)
    if terms_section is None:
        return []

    terms: list[TbxTerm] = []

    for dl in terms_section.find_all("dl"):
        # Detect domain from closest enclosing section heading
        section_domain = _detect_domain_from_section(dl)

        for dt in dl.find_all("dt", recursive=False):
            # Skip admitted / deprecated variant <dt> elements — they are
            # associated with the preceding preferred-term entry.
            dt_classes = dt.get("class", [])
            if isinstance(dt_classes, str):
                dt_classes = dt_classes.split()

            if "admitted-term" in dt_classes or "deprecated-term" in dt_classes:
                continue

            term_text = _extract_preferred_term(dt)
            if not term_text:
                continue

            term_id = dt.get("id", "") or _make_id(term_text)
            term_number = dt.get("data-term-number", "")

            dd = dt.find_next_sibling("dd")
            definition = _extract_definition(dd) if dd else ""
            source = _extract_source_attr_or_dd(dt, dd) if dd else dt.get("data-source", "")

            # Collect admitted and deprecated variants that follow this <dt>
            admitted: list[str] = []
            deprecated: list[str] = []
            _collect_variants(dt, admitted, deprecated)

            # Also check for inline <span class="admitted"> / <span class="deprecated">
            for span in dt.find_all("span"):
                span_classes = span.get("class", [])
                if isinstance(span_classes, str):
                    span_classes = span_classes.split()
                span_text = span.get_text(strip=True)
                if span_text:
                    if "admitted" in span_classes:
                        admitted.append(span_text)
                    elif "deprecated" in span_classes:
                        deprecated.append(span_text)

            # --- Extended fields ---

            # Domain: data-domain attr on <dt> > section heading inference
            domain = dt.get("data-domain", "") or section_domain

            # Parent term: data-parent-term attr or <dd class="parent-term">
            parent_term_id = dt.get("data-parent-term", "")
            if not parent_term_id and dd is not None:
                parent_term_id = _extract_parent_term(dd)

            # Multilingual terms: <span lang="xx"> inside <dt>
            alt_lang_terms = _extract_alt_lang_terms(dt)

            # Source (may come from data-source on <dt> too)
            if not source and dt.get("data-source"):
                source = dt.get("data-source", "")

            # Scope note: <dd class="scope-note">
            scope_note = _extract_scope_note(dd) if dd else ""

            terms.append(
                TbxTerm(
                    term_id=term_id,
                    term=term_text,
                    definition=definition,
                    source=source,
                    admitted_terms=admitted,
                    deprecated_terms=deprecated,
                    term_number=term_number,
                    domain=domain,
                    parent_term_id=parent_term_id,
                    alt_lang_terms=alt_lang_terms,
                    scope_note=scope_note,
                )
            )

    return terms


def _find_terms_section(soup: BeautifulSoup) -> object | None:
    """Return the ``<section>`` element that contains Terms and Definitions."""
    from specbuild.utils import HEADING_RE

    for heading in soup.find_all(HEADING_RE):
        heading_text = heading.get_text(strip=True)
        if _TERMS_HEADING_RE.search(heading_text):
            # Walk up to the enclosing <section>
            section = heading.find_parent("section")
            if section is not None:
                return section
    return None


def _extract_preferred_term(dt: object) -> str:
    """Return the preferred term text from a ``<dt>`` element.

    Prefers the text inside a ``<dfn>`` child; falls back to the full
    element text.
    """
    dfn = dt.find("dfn")  # type: ignore[union-attr]
    if dfn is not None:
        return dfn.get_text(strip=True)
    return dt.get_text(strip=True)  # type: ignore[union-attr]


def _extract_definition(dd: object) -> str:
    """Return the definition string from a ``<dd>`` element.

    Uses the first ``<p>`` child when present; otherwise falls back to the
    full text of the ``<dd>``.
    """
    first_p = dd.find("p")  # type: ignore[union-attr]
    if first_p is not None:
        # Skip source paragraphs
        p_classes = first_p.get("class", [])
        if isinstance(p_classes, str):
            p_classes = p_classes.split()
        if "source" not in p_classes:
            return first_p.get_text(strip=True)
        # If first <p> is a source paragraph, look for the next <p>
        for p in dd.find_all("p"):  # type: ignore[union-attr]
            p_cls = p.get("class", [])
            if isinstance(p_cls, str):
                p_cls = p_cls.split()
            if "source" not in p_cls:
                return p.get_text(strip=True)
    return dd.get_text(strip=True)  # type: ignore[union-attr]


def _extract_source(dd: object) -> str:
    """Return the source citation string from a ``<dd>`` element, if present.

    Handles these authoring patterns inside the ``<dd>``:

    * ``<p class="source">SOURCE: ISO 14496-10:2022, 3.1</p>``
    * ``<p class="source">[SOURCE: RFC 2119]</p>``
    * ``<span class="source">SOURCE: …</span>``
    * ``<dl class="term-source"><dt>Source</dt><dd>…</dd>``
    * Any ``<dt>Source</dt>`` / ``<dd>…</dd>`` pair in the definition block.

    The ``SOURCE:`` prefix and surrounding brackets are stripped before
    returning.
    """
    # 1. <p class="source"> or <span class="source">
    for tag_name in ("p", "span"):
        for el in dd.find_all(tag_name):  # type: ignore[union-attr]
            el_classes = el.get("class", [])
            if isinstance(el_classes, str):
                el_classes = el_classes.split()
            if "source" in el_classes:
                raw = el.get_text(strip=True)
                m = _SOURCE_PREFIX_RE.match(raw)
                if m:
                    return m.group(1).strip()
                return raw

    # 2. <dl class="term-source"> or <dt>Source</dt><dd>…</dd>
    for dl in dd.find_all("dl"):  # type: ignore[union-attr]
        dl_classes = dl.get("class", [])
        if isinstance(dl_classes, str):
            dl_classes = dl_classes.split()
        for dt_el in dl.find_all("dt"):
            if dt_el.get_text(strip=True).lower() == "source":
                src_dd = dt_el.find_next_sibling("dd")
                if src_dd:
                    return src_dd.get_text(strip=True)

    # 3. Plain text starting with SOURCE: anywhere in the <dd> text
    raw_text = dd.get_text(separator="\n")  # type: ignore[union-attr]
    for line in raw_text.splitlines():
        line = line.strip()
        m = _SOURCE_PREFIX_RE.match(line)
        if m:
            return m.group(1).strip()

    return ""


def _collect_variants(
    preferred_dt: object,
    admitted: list[str],
    deprecated: list[str],
) -> None:
    """Collect admitted / deprecated ``<dt>`` siblings that follow *preferred_dt*."""
    sibling = preferred_dt.find_next_sibling()  # type: ignore[union-attr]
    while sibling is not None:
        if not hasattr(sibling, "name") or sibling.name is None:
            sibling = sibling.find_next_sibling()
            continue
        # Stop at the next non-variant <dt> or any element that isn't a <dt>/<dd>
        if sibling.name == "dt":
            classes = sibling.get("class", [])
            if isinstance(classes, str):
                classes = classes.split()
            if "admitted-term" in classes:
                text = sibling.get_text(strip=True)
                if text:
                    admitted.append(text)
            elif "deprecated-term" in classes:
                text = sibling.get_text(strip=True)
                if text:
                    deprecated.append(text)
            else:
                # Another preferred term — stop scanning
                break
        elif sibling.name != "dd":
            break
        sibling = sibling.find_next_sibling()


def _make_id(term_text: str) -> str:
    """Derive a safe XML id from *term_text*."""
    safe = re.sub(r"[^a-z0-9]+", "-", term_text.lower()).strip("-")
    return f"term-{safe}"


# ---------------------------------------------------------------------------
# Extended extraction helpers (domain, hierarchy, multilingual, scope)
# ---------------------------------------------------------------------------


def _detect_domain_from_section(dl: object) -> str:
    """Infer a domain label from the nearest enclosing subsection heading.

    Walks up from *dl* looking for a ``<section>`` that is a sub-section of
    the Terms section (e.g. "3.1 Video coding terms"), and returns its
    heading text.  Returns ``""`` when no sub-heading is found.
    """
    from specbuild.utils import HEADING_RE  # type: ignore[attr-defined]

    parent = dl.find_parent("section")  # type: ignore[union-attr]
    if parent is None:
        return ""
    heading = parent.find(HEADING_RE)
    if heading is None:
        return ""
    text = heading.get_text(strip=True)
    # Skip the top-level "Terms and definitions" heading itself
    if _TERMS_HEADING_RE.search(text):
        return ""
    # Strip leading clause number (e.g. "3.1 Video coding" → "Video coding")
    text = re.sub(r"^\d+(?:\.\d+)*\s*", "", text).strip()
    return text


def _extract_parent_term(dd: object) -> str:
    """Extract a parent-term ID from ``<dd class="parent-term">`` element."""
    for el in dd.find_all(  # type: ignore[union-attr]
        ["dd", "p", "span"],
    ):
        el_classes = el.get("class", [])
        if isinstance(el_classes, str):
            el_classes = el_classes.split()
        if "parent-term" in el_classes:
            # Return the href anchor or raw text as the parent ID
            link = el.find("a")
            if link and link.get("href", "").startswith("#"):
                return link["href"][1:]
            return _make_id(el.get_text(strip=True))
    return ""


def _extract_alt_lang_terms(dt: object) -> dict[str, str]:
    """Extract alternative-language renderings from ``<span lang="xx">`` inside *dt*.

    Returns a mapping ``{lang_tag: term_text}``, e.g.
    ``{"fr": "terme", "zh": "术语"}``.
    """
    alt: dict[str, str] = {}
    for span in dt.find_all("span"):  # type: ignore[union-attr]
        lang = span.get("lang", "") or span.get("xml:lang", "")
        if lang:
            text = span.get_text(strip=True)
            if text:
                alt[lang] = text
    return alt


def _extract_scope_note(dd: object) -> str:
    """Extract a scope/usage note from ``<dd class="scope-note">`` descendants."""
    for el in dd.find_all(["dd", "p", "span", "div"]):  # type: ignore[union-attr]
        el_classes = el.get("class", [])
        if isinstance(el_classes, str):
            el_classes = el_classes.split()
        if "scope-note" in el_classes or "usageNote" in el_classes:
            return el.get_text(strip=True)
    return ""


def _extract_source_attr_or_dd(dt: object, dd: object) -> str:
    """Return source from data-source attribute on dt, or dd element analysis."""
    # Check data-source on the <dt> first
    data_src = dt.get("data-source", "")  # type: ignore[union-attr]
    if data_src:
        return data_src
    return _extract_source(dd)


# ---------------------------------------------------------------------------
# Conversion from plain dict (e.g. from termdb.py)
# ---------------------------------------------------------------------------


def terms_from_dict(
    terms_dict: dict[str, str],
    id_prefix: str = "term",
) -> list[TbxTerm]:
    """Convert a ``{term: definition}`` mapping to a list of :class:`TbxTerm`.

    Sequential IDs are generated as ``{id_prefix}-001``, ``{id_prefix}-002``,
    etc.

    Args:
        terms_dict: Mapping of term string to definition string.
        id_prefix: Prefix for generated IDs (default ``"term"``).

    Returns:
        Ordered list of :class:`TbxTerm` instances.
    """
    result: list[TbxTerm] = []
    for idx, (term, definition) in enumerate(terms_dict.items(), start=1):
        result.append(
            TbxTerm(
                term_id=f"{id_prefix}-{idx:03d}",
                term=term,
                definition=definition,
            )
        )
    return result


# ---------------------------------------------------------------------------
# XML serialisation
# ---------------------------------------------------------------------------


def build_tbx_xml(
    terms: list[TbxTerm],
    title: str = "Terminology",
    lang: str = "en",
) -> str:
    """Serialise a list of :class:`TbxTerm` objects to a TBX-Basic XML string.

    The generated XML conforms to ISO 30042 ed-2, TBX-Basic dialect, ``dca``
    (data-category as attribute) style.

    Args:
        terms: Terminology entries to serialise.
        title: Document title for the ``<tbxHeader>``.
        lang:  BCP 47 language tag for the primary language (default ``"en"``).

    Returns:
        Well-formed XML string including an XML declaration.
    """
    # --- root <TBX> ---
    root = Element("TBX")
    root.set("type", "TBX-Basic")
    root.set("style", "dca")
    root.set("xml:lang", lang)
    root.set("xmlns", _TBX_NS)

    # --- <tbxHeader> ---
    header = SubElement(root, "tbxHeader")
    file_desc = SubElement(header, "fileDesc")

    title_stmt = SubElement(file_desc, "titleStmt")
    title_el = SubElement(title_stmt, "title")
    title_el.text = title

    source_desc = SubElement(file_desc, "sourceDesc")
    source_p = SubElement(source_desc, "p")
    source_p.text = "Exported from specbuild"

    # --- <text><body> ---
    text_el = SubElement(root, "text")
    body_el = SubElement(text_el, "body")

    for tbx_term in terms:
        _append_term_entry(body_el, tbx_term, lang)

    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


def _append_term_entry(
    body_el: Element,
    tbx_term: TbxTerm,
    lang: str,
) -> None:
    """Append a single ``<termEntry>`` to *body_el*.

    Emits the primary language block, then optional additional ``<langSet>``
    blocks for any alternative-language terms found on the entry.
    """
    entry = SubElement(body_el, "termEntry")
    entry.set("id", tbx_term.term_id)

    # --- Concept-level notes (domain, parent, scope) ---
    if tbx_term.domain:
        domain_note = SubElement(entry, "descrip")
        domain_note.set("type", "subjectField")
        domain_note.text = tbx_term.domain

    if tbx_term.parent_term_id:
        ref_el = SubElement(entry, "ref")
        ref_el.set("type", "partitiveEquivalent")
        ref_el.set("target", tbx_term.parent_term_id)
        ref_el.text = tbx_term.parent_term_id

    # --- Primary language block ---
    lang_set = SubElement(entry, "langSet")
    lang_set.set("xml:lang", lang)

    # preferred term
    tig = SubElement(lang_set, "tig")
    term_el = SubElement(tig, "term")
    term_el.text = tbx_term.term

    if tbx_term.part_of_speech:
        pos_note = SubElement(tig, "termNote")
        pos_note.set("type", "partOfSpeech")
        pos_note.text = tbx_term.part_of_speech

    # definition + source + scope note
    has_descrip = tbx_term.definition or tbx_term.source or tbx_term.scope_note
    if has_descrip:
        descrip_grp = SubElement(lang_set, "descripGrp")
        if tbx_term.definition:
            defn_el = SubElement(descrip_grp, "descrip")
            defn_el.set("type", "definition")
            defn_el.text = tbx_term.definition
        if tbx_term.source:
            src_el = SubElement(descrip_grp, "descrip")
            src_el.set("type", "source")
            src_el.text = tbx_term.source
        if tbx_term.scope_note:
            scope_el = SubElement(descrip_grp, "termNote")
            scope_el.set("type", "usageNote")
            scope_el.text = tbx_term.scope_note

    # admitted variants
    for admitted_text in tbx_term.admitted_terms:
        adm_tig = SubElement(lang_set, "tig")
        adm_term = SubElement(adm_tig, "term")
        adm_term.set("type", "admitted")
        adm_term.text = admitted_text

    # deprecated variants
    for deprecated_text in tbx_term.deprecated_terms:
        dep_tig = SubElement(lang_set, "tig")
        dep_term = SubElement(dep_tig, "term")
        dep_term.text = deprecated_text
        dep_note = SubElement(dep_tig, "termNote")
        dep_note.set("type", "administrativeStatus")
        dep_note.text = "deprecated"

    # --- Additional language blocks ---
    for alt_lang, alt_text in sorted(tbx_term.alt_lang_terms.items()):
        if alt_lang == lang:
            continue  # already in primary block
        alt_lang_set = SubElement(entry, "langSet")
        alt_lang_set.set("xml:lang", alt_lang)
        alt_tig = SubElement(alt_lang_set, "tig")
        alt_term_el = SubElement(alt_tig, "term")
        alt_term_el.text = alt_text


# ---------------------------------------------------------------------------
# Top-level export function
# ---------------------------------------------------------------------------


def export_tbx(
    soup: BeautifulSoup,
    output_path: Path,
    title: str = "Terminology",
    language: list[str] | None = None,
) -> Path | None:
    """Extract terms from *soup* and write a TBX XML file to *output_path*.

    Args:
        soup:        Parsed HTML document (the compiled spec).
        output_path: Destination path for the ``.tbx`` file.
        title:       Document title embedded in the TBX header.
        language:    List of BCP 47 language tags to include.  The first entry
                     is used as the primary ``xml:lang`` for the TBX root and
                     ``<langSet>`` elements.  Defaults to ``["en"]``.

    Returns:
        *output_path* on success, or ``None`` when no terms were found.
    """
    if language is None:
        language = ["en"]
    primary_lang = language[0] if language else "en"

    terms = extract_terms_from_soup(soup)
    if not terms:
        logging.debug("export_tbx: no terms found in document")
        return None

    xml_str = build_tbx_xml(terms, title=title, lang=primary_lang)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logging.info(f"TBX export written to {output_path} ({len(terms)} term(s))")
    return output_path

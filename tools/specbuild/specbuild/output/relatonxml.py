"""Relaton XML export.

Generates Relaton XML (https://www.relaton.org/) from compiled HTML.
Relaton XML is used by Metanorma and ISO's internal toolchain as an
interoperable bibliographic exchange format.

Two outputs are supported:
- **Document record** (``<bibdata type="standard">``) — the metadata of the
  specification being built.
- **Bibliography collection** (``<relaton-collection>``) — all normative and
  informative reference entries extracted from the compiled HTML.
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

    from specbuild.standards.flavors import FlavorSpec


_RELATON_NS = "https://www.relaton.org/schema/bibdata"

# Pattern for bibliography / references headings
_BIB_RE = re.compile(
    r"(?i)^(bibliography|normative\s+references?|informative\s+references?|references?)"
)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def export_relaton_xml(
    html_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
    soup: BeautifulSoup | None = None,
) -> Path | None:
    """Write Relaton XML (document bibdata + bibliography) to *output_path*.

    Args:
        html_path:   Path to the compiled index.html (used to read soup if not provided).
        output_path: Destination ``.xml`` path.
        metadata:    Resolved standards metadata dict.
        flavor:      Active standards flavor (optional).
        soup:        Pre-parsed BeautifulSoup tree (avoids re-reading disk).

    Returns:
        Path to the generated file, or ``None`` on failure.
    """
    if soup is None:
        try:
            from specbuild.utils import read_html

            soup = read_html(html_path)
        except Exception:
            logging.error("Failed to read HTML for Relaton XML export")
            return None

    xml_str = export_relaton_xml_soup(soup, metadata, flavor)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(xml_str, encoding="utf-8")
    logging.info(f"Relaton XML written to {output_path}")
    return output_path


def export_relaton_xml_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> str:
    """Convert parsed HTML soup to Relaton XML string.

    Returns a ``<relaton-collection>`` that contains the document's own
    ``<bibdata>`` record as the first entry, followed by every bibliography
    item extracted from the HTML.
    """
    root = Element("relaton-collection")
    root.set("xmlns", _RELATON_NS)

    # --- Document record ---
    doc_rel = SubElement(root, "relation", type="hasMember")
    bibdata = SubElement(doc_rel, "bibdata", type="standard")
    _fill_bibdata(bibdata, metadata, flavor)

    # --- Bibliography entries ---
    entries = _collect_bib_entries(soup)
    for entry in entries:
        rel = SubElement(root, "relation", type="hasMember")
        item = SubElement(rel, "bibitem", type="standard")
        _fill_bibitem(item, entry)

    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


def export_relaton_bibdata(
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> str:
    """Return a standalone Relaton ``<bibdata>`` XML string for this document."""
    root = Element("bibdata", type="standard")
    root.set("xmlns", _RELATON_NS)
    _fill_bibdata(root, metadata, flavor)
    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_bytes}\n'


# ---------------------------------------------------------------------------
# bibdata builder
# ---------------------------------------------------------------------------


def _fill_bibdata(
    bibdata: Element,
    metadata: dict[str, str],
    flavor: FlavorSpec | None,
) -> None:
    """Populate a ``<bibdata>`` element from spec metadata."""
    lang = metadata.get("language", "en")
    sdo_name = flavor.display_name if flavor else metadata.get("sdo", "ISO")

    # --- Titles ---
    for key, title_type in (
        ("title_main", "main"),
        ("title_intro", "title-intro"),
        ("title_part", "title-part"),
    ):
        val = metadata.get(key, "")
        if val:
            title_el = SubElement(bibdata, "title")
            title_el.set("language", lang)
            title_el.set("format", "text/plain")
            title_el.set("type", title_type)
            title_el.text = val

    # --- Identifier ---
    docnumber = metadata.get("docnumber", "")
    partnumber = metadata.get("partnumber", "")
    if docnumber:
        ident_text = f"{sdo_name} {docnumber}"
        if partnumber:
            ident_text += f"-{partnumber}"
        docid_el = SubElement(bibdata, "docidentifier")
        docid_el.set("type", sdo_name)
        docid_el.text = ident_text
        SubElement(bibdata, "docnumber").text = docnumber

    # --- Dates ---
    revdate = metadata.get("revdate", "") or metadata.get("copyright_year", "")
    if revdate:
        date_el = SubElement(bibdata, "date", type="published")
        # Normalise to just the year if it's a full date
        year_m = re.search(r"\b(\d{4})\b", revdate)
        SubElement(date_el, "on").text = year_m.group(1) if year_m else revdate

    # --- Contributor (publisher / author) ---
    if sdo_name:
        contrib = SubElement(bibdata, "contributor")
        SubElement(contrib, "role", type="publisher")
        org = SubElement(contrib, "organization")
        SubElement(org, "name").text = sdo_name
        abbrev = metadata.get("sdo_abbrev", "")
        if abbrev:
            SubElement(org, "abbreviation").text = abbrev

    # --- Edition ---
    edition = metadata.get("edition", "")
    if edition:
        SubElement(bibdata, "edition").text = edition

    # --- Language / script ---
    SubElement(bibdata, "language").text = lang
    SubElement(bibdata, "script").text = "Latn"

    # --- Status ---
    stage = metadata.get("stage", "")
    if stage:
        status = SubElement(bibdata, "status")
        SubElement(status, "stage").text = stage
        substage = metadata.get("substage", "")
        if substage:
            SubElement(status, "substage").text = substage

    # --- Copyright ---
    copyright_year = metadata.get("copyright_year", "")
    if copyright_year:
        cr = SubElement(bibdata, "copyright")
        SubElement(cr, "from").text = copyright_year
        if sdo_name:
            owner = SubElement(cr, "owner")
            org2 = SubElement(owner, "organization")
            SubElement(org2, "name").text = sdo_name

    # --- ICS codes ---
    ics = metadata.get("ics", "")
    if ics:
        for code in ics.split(";"):
            code = code.strip()
            if code:
                SubElement(SubElement(bibdata, "ics"), "code").text = code

    # --- Technical committee ---
    tc = metadata.get("technical_committee", "")
    if tc:
        ext = SubElement(bibdata, "ext")
        eg = SubElement(ext, "editorialgroup")
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


# ---------------------------------------------------------------------------
# Bibliography extraction
# ---------------------------------------------------------------------------


def _collect_bib_entries(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Extract bibliography entries from all reference sections in the HTML."""
    body = soup.find("body")
    if body is None:
        return []

    entries: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    # Search direct children of <body>, then also inside <main> which is where
    # Bikeshed places bibliography sections in many output templates.
    direct_sections = list(body.find_all("section", recursive=False))
    main_el = body.find("main")
    if main_el:
        main_sections = list(main_el.find_all("section", recursive=False))
    else:
        main_sections = []
    all_sections = direct_sections + [s for s in main_sections if s not in direct_sections]

    for section in all_sections:
        heading = section.find(HEADING_RE)
        if heading is None:
            continue
        if not _BIB_RE.match(heading.get_text(strip=True)):
            continue

        normative = bool(re.search(r"(?i)normative", heading.get_text()))

        # Entries as <dd id="biblio-...">
        for dd in section.find_all("dd"):
            dd_id = dd.get("id", "")
            item_id = dd_id[len("biblio-") :] if dd_id.startswith("biblio-") else ""
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            entries.append(_parse_bib_entry(item_id, dd.get_text(strip=True), normative))

        # Entries as <dt id="biblio-..."><dd>
        for dt in section.find_all("dt"):
            dt_id = dt.get("id", "")
            item_id = dt_id[len("biblio-") :] if dt_id.startswith("biblio-") else ""
            if not item_id or item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            dd = dt.find_next_sibling("dd")
            text = dd.get_text(strip=True) if dd else dt.get_text(strip=True)
            entries.append(_parse_bib_entry(item_id, text, normative))

        # Entries as <li id="ref-...">
        for idx, li in enumerate(section.find_all("li")):
            li_id = li.get("id", "")
            item_id = li_id[len("ref-") :] if li_id.startswith("ref-") else li_id
            if not item_id:
                item_id = f"anon-{idx}"
            if item_id in seen_ids:
                continue
            seen_ids.add(item_id)
            entries.append(_parse_bib_entry(item_id, li.get_text(strip=True), normative))

    return entries


def _parse_bib_entry(entry_id: str, full_text: str, normative: bool) -> dict[str, str]:
    """Parse a bibliography entry string into a structured dict."""
    entry: dict[str, str] = {
        "id": entry_id,
        "normative": "true" if normative else "false",
        "docidentifier": "",
        "id_type": "other",
        "title": full_text,
        "year": "",
    }

    # Try: "DOCID:YEAR, Title text" or "DOCID, Title text"
    m = re.match(
        r"^([A-Z][A-Za-z0-9/. :+-]{2,}?(?::\d{4})?)\s*[,\u2014\u2013]\s*(.+)$",
        full_text,
        re.DOTALL,
    )
    if m:
        docid_str = m.group(1).strip()
        title_str = m.group(2).strip()

        year_m = re.search(r":(\d{4})$", docid_str)
        if year_m:
            entry["year"] = year_m.group(1)
            docid_str = docid_str[: year_m.start()].strip()

        if re.match(r"^(ISO|IEC|ISO/IEC)", docid_str, re.IGNORECASE):
            entry["id_type"] = "ISO"
        elif re.match(r"^(ITU|Rec\.)", docid_str, re.IGNORECASE):
            entry["id_type"] = "ITU-T"
        elif re.match(r"^RFC", docid_str, re.IGNORECASE):
            entry["id_type"] = "IETF"
        elif re.match(r"^SMPTE", docid_str, re.IGNORECASE):
            entry["id_type"] = "SMPTE"
        elif re.match(r"^IEEE", docid_str, re.IGNORECASE):
            entry["id_type"] = "IEEE"

        entry["docidentifier"] = docid_str
        entry["title"] = title_str

    return entry


def _fill_bibitem(item: Element, entry: dict[str, str]) -> None:
    """Populate a ``<bibitem>`` element from a parsed bibliography entry."""
    # Identifier
    docid = entry.get("docidentifier", "")
    id_type = entry.get("id_type", "other")
    if docid:
        docid_el = SubElement(item, "docidentifier")
        docid_el.set("type", id_type)
        docid_el.text = docid

    # Title
    title_text = entry.get("title", "")
    if title_text:
        title_el = SubElement(item, "title")
        title_el.set("format", "text/plain")
        title_el.text = title_text

    # Date
    year = entry.get("year", "")
    if year:
        date_el = SubElement(item, "date", type="published")
        SubElement(date_el, "on").text = year

    # Note normative/informative status
    normative = entry.get("normative", "false")
    if normative == "true":
        SubElement(item, "note", type="normative-reference")

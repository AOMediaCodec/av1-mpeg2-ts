"""Export document bibliography as Relaton XML/JSON.

Produces Relaton-compatible output for interoperability with the Relaton
ecosystem (Metanorma, ISO TC document management systems).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from xml.etree.ElementTree import Element, SubElement, indent, tostring

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.relaton import RelatonEntry  # noqa: F401


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class RelatonDocumentRecord:
    """Self-describing Relaton record for a single document (not a reference)."""

    docid: str  # e.g. "ISO/IEC 23094-1:2022"
    docid_type: str  # "ISO", "IETF", "IEEE", etc.
    title: str
    publisher: str
    year: int | None
    stage: str  # "WD", "CD", "DIS", "FDIS", "IS", etc.
    language: list[str]  # ["en", "fr"]
    abstract: str | None
    contributors: list[dict]  # [{"role": "author", "name": "..."}]
    relations: list[dict]  # [{"type": "supersedes", "bibitem": {"docid": "..."}}]
    copyright_holder: str
    copyright_year: int | None


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------


def build_relaton_record(
    soup: BeautifulSoup,
    metadata: dict,
    flavor: str | None = None,
) -> RelatonDocumentRecord:
    """Build a Relaton record from soup + build metadata.

    Extracts available information from the compiled HTML (title, abstract,
    author meta tags) and merges with the resolved standards metadata dict.

    Args:
        soup:     Compiled HTML document (BeautifulSoup).
        metadata: Resolved standards metadata dict (from
                  :func:`~specbuild.standards.metadata.resolve_metadata`).
        flavor:   Active standards flavor (e.g. ``"iso"``, ``"ietf"``).

    Returns:
        A populated :class:`RelatonDocumentRecord`.
    """
    # --- title ---
    title = _extract_title(soup, metadata)

    # --- docid / publisher ---
    docid = metadata.get("docnumber", "") or metadata.get("doc_id", "")
    publisher, docid_type = _infer_publisher(docid, flavor, metadata)

    # --- year ---
    year = _extract_year(metadata)

    # --- stage ---
    stage = metadata.get("stage", "") or "WD"

    # --- language ---
    lang_raw = metadata.get("language", "en")
    language = [lg.strip() for lg in lang_raw.split(",")] if lang_raw else ["en"]

    # --- abstract ---
    abstract = _extract_abstract(soup)

    # --- contributors ---
    contributors = _extract_contributors(soup, metadata)

    # --- copyright ---
    copyright_holder = publisher or docid_type or "Unknown"
    copyright_year = year

    return RelatonDocumentRecord(
        docid=docid,
        docid_type=docid_type,
        title=title,
        publisher=publisher,
        year=year,
        stage=stage,
        language=language,
        abstract=abstract,
        contributors=contributors,
        relations=[],
        copyright_holder=copyright_holder,
        copyright_year=copyright_year,
    )


# ---------------------------------------------------------------------------
# JSON / XML export
# ---------------------------------------------------------------------------


def export_relaton_json(
    record: RelatonDocumentRecord,
    output_path: Path,
) -> Path:
    """Write Relaton JSON (bibdata format used by Metanorma).

    Args:
        record:      A :class:`RelatonDocumentRecord` to serialise.
        output_path: Destination ``.json`` file path.

    Returns:
        *output_path* after writing.
    """
    data = {
        "bibdata": {
            "type": "standard",
            "docid": [{"id": record.docid, "type": record.docid_type}],
            "title": [
                {
                    "content": record.title,
                    "language": "en",
                    "format": "text/plain",
                }
            ],
            "date": ([{"type": "published", "value": str(record.year)}] if record.year else []),
            "contributor": record.contributors,
            "abstract": (
                [{"content": record.abstract, "language": "en"}] if record.abstract else []
            ),
            "status": {"stage": record.stage},
            "language": record.language,
            "copyright": [
                {
                    "from": record.copyright_year,
                    "owner": [{"name": record.copyright_holder}],
                }
            ],
            "relation": record.relations,
        }
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.debug(f"Relaton JSON written to {output_path}")
    return output_path


def export_relaton_xml(
    record: RelatonDocumentRecord,
    output_path: Path,
) -> Path:
    """Write Relaton XML (bibdata format used by Metanorma).

    Args:
        record:      A :class:`RelatonDocumentRecord` to serialise.
        output_path: Destination ``.xml`` file path.

    Returns:
        *output_path* after writing.
    """
    root = Element("bibdata", type="standard")

    # docid
    docid_el = SubElement(root, "docidentifier", type=record.docid_type)
    docid_el.text = record.docid

    # title
    title_el = SubElement(root, "title", language="en", format="text/plain")
    title_el.text = record.title

    # date
    if record.year:
        date_el = SubElement(root, "date", type="published")
        on_el = SubElement(date_el, "on")
        on_el.text = str(record.year)

    # contributor
    for contrib in record.contributors:
        contrib_el = SubElement(root, "contributor")
        role = contrib.get("role", "")
        if role:
            role_el = SubElement(contrib_el, "role", type=role)
            role_el.text = role
        name_val = contrib.get("name") or contrib.get("person", {}).get("name", "")
        if name_val:
            person = SubElement(contrib_el, "person")
            name_el = SubElement(person, "name")
            completename = SubElement(name_el, "completename")
            completename.text = name_val

    # status
    status = SubElement(root, "status")
    stage_el = SubElement(status, "stage")
    stage_el.text = record.stage

    # language
    for lang in record.language:
        lang_el = SubElement(root, "language")
        lang_el.text = lang

    # abstract
    if record.abstract:
        abs_el = SubElement(root, "abstract", language="en", format="text/plain")
        abs_el.text = record.abstract

    # copyright
    copy_el = SubElement(root, "copyright")
    from_el = SubElement(copy_el, "from")
    from_el.text = str(record.copyright_year or "")
    owner = SubElement(copy_el, "owner")
    org = SubElement(owner, "organization")
    name_el = SubElement(org, "name")
    name_el.text = record.copyright_holder

    indent(root, space="  ")
    xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes,
        encoding="utf-8",
    )
    logging.debug(f"Relaton XML written to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Bibliography export
# ---------------------------------------------------------------------------


def export_relaton_bibliography(
    soup: BeautifulSoup,
    output_path: Path,
    format: str = "json",
) -> Path | None:
    """Extract bibliography entries and export as Relaton format.

    Scans ``<ol>``/``<ul>`` in the normative/informative references section
    and exports each reference as a Relaton bibitem entry.

    Args:
        soup:        Parsed HTML document.
        output_path: Output file path (``.json`` or ``.xml``).
        format:      ``"json"`` or ``"xml"``.

    Returns:
        *output_path* on success, or ``None`` when no bibliography entries
        were found.
    """
    entries = _extract_bibliography_entries(soup)
    if not entries:
        logging.debug("export_relaton_bibliography: no bibliography entries found")
        return None

    if format == "xml":
        root = Element("references")
        for entry in entries:
            item = SubElement(root, "bibitem", id=_safe_id(entry.get("docid", "")))
            docid_el = SubElement(item, "docidentifier")
            docid_el.text = entry.get("docid", "")
            title_el = SubElement(item, "title")
            title_el.text = entry.get("title", "")
            if entry.get("publisher"):
                contrib_el = SubElement(item, "contributor")
                role_el = SubElement(contrib_el, "role", type="publisher")
                role_el.text = "publisher"
                org = SubElement(contrib_el, "organization")
                name_el = SubElement(org, "name")
                name_el.text = entry["publisher"]
            if entry.get("year"):
                date_el = SubElement(item, "date", type="published")
                on_el = SubElement(date_el, "on")
                on_el.text = str(entry["year"])
        indent(root, space="  ")
        xml_bytes = tostring(root, encoding="unicode", xml_declaration=False)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n' + xml_bytes,
            encoding="utf-8",
        )
    else:
        data = {
            "references": [
                {
                    "docid": [{"id": e.get("docid", ""), "type": e.get("docid_type", "")}],
                    "title": [{"content": e.get("title", ""), "language": "en"}],
                    "date": (
                        [{"type": "published", "value": str(e["year"])}] if e.get("year") else []
                    ),
                    "contributor": (
                        [
                            {
                                "role": [{"type": "publisher"}],
                                "organization": {"name": e["publisher"]},
                            }
                        ]
                        if e.get("publisher")
                        else []
                    ),
                }
                for e in entries
            ]
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    logging.info(
        f"Relaton bibliography ({format}) written to {output_path} ({len(entries)} entries)"
    )
    return output_path


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

_SDO_RE = re.compile(
    r"^(ISO(?:/IEC)?|IEC|ITU(?:-T|-R)?|IEEE|IETF|RFC\s*\d|NIST|ETSI|3GPP|MPEG|JCT-VC|JVET)",
    re.IGNORECASE,
)

_REFS_HEADING_RE = re.compile(
    r"(?i)(normative|informative)?\s*references?",
)

# Maps first word of docid to a docid_type label
_SDO_TYPE_MAP: dict[str, str] = {
    "iso": "ISO",
    "iec": "IEC",
    "itu": "ITU",
    "ieee": "IEEE",
    "ietf": "IETF",
    "rfc": "IETF",
    "nist": "NIST",
    "etsi": "ETSI",
    "3gpp": "3GPP",
    "mpeg": "MPEG",
    "jvet": "JVET",
}


def _extract_title(soup: BeautifulSoup, metadata: dict) -> str:
    """Return document title from metadata or HTML <title>/<h1>."""
    title = metadata.get("title", "")
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)
    return title


def _infer_publisher(
    docid: str,
    flavor: str | None,
    metadata: dict,
) -> tuple[str, str]:
    """Return (publisher_name, docid_type) from docid or flavor."""
    publisher = metadata.get("publisher", "")
    docid_type = ""

    if docid:
        first = re.split(r"[\s/]", docid)[0].lower()
        docid_type = _SDO_TYPE_MAP.get(first, first.upper())

    if not publisher and flavor:
        flavor_lower = flavor.lower()
        if "iso" in flavor_lower:
            publisher = "ISO"
            docid_type = docid_type or "ISO"
        elif "ietf" in flavor_lower:
            publisher = "IETF"
            docid_type = docid_type or "IETF"
        elif "ieee" in flavor_lower:
            publisher = "IEEE"
            docid_type = docid_type or "IEEE"
        elif "itu" in flavor_lower:
            publisher = "ITU"
            docid_type = docid_type or "ITU"
        else:
            publisher = flavor.upper()
            docid_type = docid_type or flavor.upper()

    return publisher, docid_type or "SDO"


def _extract_year(metadata: dict) -> int | None:
    """Extract a 4-digit year from metadata."""
    for key in ("copyright_year", "year", "date", "edition"):
        val = metadata.get(key, "")
        if val:
            m = re.search(r"\d{4}", str(val))
            if m:
                return int(m.group())
    return None


def _extract_abstract(soup: BeautifulSoup) -> str | None:
    """Extract abstract from <meta name="description"> or first <p> in scope section."""
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"]

    for heading in soup.find_all(re.compile(r"h[1-6]")):
        if re.search(r"^\d*\s*scope\b", heading.get_text(strip=True), re.IGNORECASE):
            section = heading.find_parent("section")
            if section:
                p = section.find("p")
                if p:
                    return p.get_text(strip=True)[:500]
    return None


def _extract_contributors(soup: BeautifulSoup, metadata: dict) -> list[dict]:
    """Extract contributor list from <meta name="editor"> tags or metadata."""
    contributors: list[dict] = []

    # Try HTML meta tags
    for tag in soup.find_all("meta"):
        name = tag.get("name", "").lower()
        content = tag.get("content", "")
        if not content:
            continue
        if name in ("editor", "author"):
            role = "editor" if name == "editor" else "author"
            for person in content.split(","):
                person = person.strip()
                if person:
                    contributors.append({"role": role, "name": person})

    # Fall back to metadata dict
    if not contributors:
        for key in ("editor", "author", "editors", "authors"):
            val = metadata.get(key, "")
            if val:
                role = "editor" if "editor" in key else "author"
                for person in str(val).split(","):
                    person = person.strip()
                    if person:
                        contributors.append({"role": role, "name": person})

    return contributors


def _extract_bibliography_entries(soup: BeautifulSoup) -> list[dict]:
    """Return a list of dicts for each recognisable standards reference found."""
    entries: list[dict] = []

    # Find references sections
    ref_sections = []
    for heading in soup.find_all(re.compile(r"h[1-6]")):
        if _REFS_HEADING_RE.search(heading.get_text(strip=True)):
            section = heading.find_parent("section")
            if section:
                ref_sections.append(section)

    if not ref_sections:
        return entries

    for section in ref_sections:
        for li in section.find_all("li"):
            text = li.get_text(separator=" ", strip=True)
            if not _SDO_RE.match(text):
                continue
            m = re.match(r"([A-Z][^\s,;\u2014\u2013]+(?:\s+\d[\d\-:]*)?)", text, re.IGNORECASE)
            if not m:
                continue
            docid = m.group(1).strip()
            first = re.split(r"[\s/]", docid)[0].lower()
            docid_type = _SDO_TYPE_MAP.get(first, first.upper())

            # Try to pull title from data attributes (if relaton-enriched)
            title = li.get("data-relaton-title", "") or _guess_title(text, docid)
            publisher = li.get("data-relaton-publisher", "")
            year_str = li.get("data-relaton-year", "")
            year = int(year_str) if year_str and year_str.isdigit() else _year_from_text(text)

            entries.append(
                {
                    "docid": docid,
                    "docid_type": docid_type,
                    "title": title,
                    "publisher": publisher,
                    "year": year,
                }
            )

    return entries


def _guess_title(text: str, docid: str) -> str:
    """Attempt to extract a short title substring from the reference text."""
    rest = text[len(docid) :].strip().lstrip(".,;:—–-").strip()
    # Often the title is the first sentence or up to a year marker
    m = re.match(r"^(.+?)(?:\s+\d{4}|\.|$)", rest)
    if m:
        return m.group(1).strip()
    return rest[:80]


def _year_from_text(text: str) -> int | None:
    """Find a 4-digit year in text, preferring colon-separated ones like ':2022'."""
    m = re.search(r":(\d{4})\b", text)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(19|20)\d{2}\b", text)
    if m:
        return int(m.group())
    return None


def _safe_id(text: str) -> str:
    """Convert a docid to a safe XML id."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "ref"

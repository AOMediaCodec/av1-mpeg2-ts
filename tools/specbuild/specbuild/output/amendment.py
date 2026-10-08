"""Amendment and corrigendum document generation.

Supports generating formal amendment documents that reference a base standard,
show only changed sections, and use proper amendment numbering and cover page.
"""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE, inject_css

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec


_AMENDMENT_DOC_TYPES = frozenset(
    {
        "amendment",
        "corrigendum",
        "technical-corrigendum",
    }
)

_ISO_STAGE_MAP: dict[str, str] = {
    "amendment": "Amd",
    "corrigendum": "Cor",
    "technical-corrigendum": "Cor",
}


def is_amendment_type(doc_type: str) -> bool:
    """Check if a document type is an amendment or corrigendum."""
    return doc_type.lower() in _AMENDMENT_DOC_TYPES


def format_amendment_identifier(
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> str:
    """Build a formatted amendment document identifier.

    Examples:
        ``ISO/IEC 14496-10:2022/Amd 1:2024``
        ``ITU-T H.265 (2021) Cor. 1 (2023)``
    """
    doc_type = metadata.get("doc_type", "amendment")
    base_doc = metadata.get("base_document", "")
    amendment_number = metadata.get("amendment_number", "1")
    amendment_year = metadata.get("copyright_year", "")

    if not base_doc:
        return ""

    flavor_name = ""
    if flavor:
        flavor_name = flavor.name.lower()

    if flavor_name in ("iso", "iec"):
        abbr = _ISO_STAGE_MAP.get(doc_type, "Amd")
        ident = f"{base_doc}/{abbr} {amendment_number}"
        if amendment_year:
            ident += f":{amendment_year}"
        return ident

    if flavor_name in ("itu-t", "itu"):
        abbr = "Cor." if "corrigendum" in doc_type else "Amd."
        ident = f"{base_doc} {abbr} {amendment_number}"
        if amendment_year:
            ident += f" ({amendment_year})"
        return ident

    return f"{base_doc} {doc_type.title()} {amendment_number}"


def inject_amendment_cover_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
    flavor: FlavorSpec | None = None,
) -> bool:
    """Inject an amendment-specific cover page into the document.

    Returns True if the cover was injected.
    """
    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    body = soup.find("body")
    if body is None:
        return False

    doc_type = metadata.get("doc_type", "amendment")
    if not is_amendment_type(doc_type):
        return False

    base_doc = metadata.get("base_document", "")
    amendment_id = format_amendment_identifier(metadata, flavor)
    title_main = metadata.get("title_main", "")
    committee = metadata.get("technical_committee", "")
    copyright_year = metadata.get("copyright_year", "")
    display_name = flavor.display_name if flavor else "ISO/IEC"

    doc_type_display = {
        "amendment": "AMENDMENT",
        "corrigendum": "TECHNICAL CORRIGENDUM",
        "technical-corrigendum": "TECHNICAL CORRIGENDUM",
    }.get(doc_type, doc_type.upper())

    cover_html = '<div class="amendment-cover-page">\n'
    if amendment_id:
        cover_html += f'  <p class="amendment-id"><strong>{amendment_id}</strong></p>\n'
    cover_html += f'  <p class="amendment-type">{doc_type_display}</p>\n'
    if base_doc:
        cover_html += f'  <p class="amendment-base">to {base_doc}</p>\n'
    if title_main:
        cover_html += f'  <p class="amendment-title"><strong>{title_main}</strong></p>\n'
    if committee:
        cover_html += f'  <p class="amendment-committee">{committee}</p>\n'
    if copyright_year:
        cover_html += (
            f'  <p class="amendment-copyright">&copy; {display_name} {copyright_year}</p>\n'
        )
    cover_html += "</div>\n"

    _cover_doc = BS(cover_html, "html.parser")
    cover_div = _cover_doc.find("div", class_="amendment-cover-page") or next(
        (c for c in (_cover_doc.find("body") or _cover_doc).children if getattr(c, "name", None)),
        None,
    )
    if cover_div is None:
        logging.warning("Amendment cover HTML produced no insertable element")
        return False
    first_child = next((c for c in body.children if getattr(c, "name", None) is not None), None)
    if first_child:
        first_child.insert_before(cover_div)
        first_child.insert_before(NavigableString("\n"))
    else:
        body.append(cover_div)

    logging.info(f"Injected {doc_type} cover page: {amendment_id}")
    return True


def mark_changed_sections_soup(
    soup: BeautifulSoup,
    changed_sections: list[str] | None = None,
) -> int:
    """Mark sections as changed for amendment display.

    If *changed_sections* is provided (list of section IDs or heading
    patterns), only those sections are marked. Otherwise all sections
    are included (full amendment).

    Returns the number of sections marked.
    """
    count = 0
    for section in soup.find_all("section"):
        sec_id = section.get("id", "")
        heading = section.find(HEADING_RE)
        heading_text = heading.get_text(strip=True) if heading else ""

        is_changed = True
        if changed_sections:
            is_changed = sec_id in changed_sections or any(
                re.match(p, heading_text, re.IGNORECASE) for p in changed_sections
            )

        classes = section.get("class", [])
        if is_changed:
            if "amendment-changed" not in classes:
                section["class"] = classes + ["amendment-changed"]
                count += 1
        else:
            if "amendment-unchanged" not in classes:
                section["class"] = classes + ["amendment-unchanged"]

    if count:
        logging.info(f"Marked {count} section(s) as changed for amendment")
    return count


def generate_amendment_toc_soup(
    soup: BeautifulSoup,
    metadata: dict[str, str],
) -> bool:
    """Generate a table of changes for the amendment.

    Inserts a "Changes" section listing which clauses were modified.
    Returns True if the TOC was generated.
    """
    from bs4 import BeautifulSoup as BS
    from bs4 import NavigableString

    changed = soup.find_all(class_="amendment-changed")
    if not changed:
        return False

    entries = []
    for section in changed:
        heading = section.find(HEADING_RE)
        if heading:
            text = heading.get_text(strip=True)
            sec_id = section.get("id", "")
            if sec_id:
                entries.append(f'<li><a href="#{sec_id}">{text}</a></li>')
            else:
                entries.append(f"<li>{text}</li>")

    if not entries:
        return False

    doc_type = metadata.get("doc_type", "amendment")
    title = "Changes" if doc_type == "amendment" else "Corrections"

    toc_html = (
        f'<section id="amendment-changes" class="amendment-toc">\n'
        f"  <h2>{title}</h2>\n"
        f"  <p>This {doc_type} contains changes to the following clauses:</p>\n"
        f"  <ol>\n    {''.join(entries)}\n  </ol>\n"
        f"</section>\n"
    )

    body = soup.find("body")
    if body is None:
        return False

    _toc_doc = BS(toc_html, "html.parser")
    toc_div = next(
        (c for c in (_toc_doc.find("body") or _toc_doc).children if getattr(c, "name", None)),
        None,
    )
    if toc_div is None:
        return False
    cover = body.find(class_="amendment-cover-page")
    if cover is not None:
        # Skip NavigableString siblings
        sib = cover.next_sibling
        while sib is not None and not hasattr(sib, "insert_before"):
            sib = sib.next_sibling
        insert_point = sib
    else:
        insert_point = next(
            (c for c in body.children if getattr(c, "name", None) is not None), None
        )
    if insert_point:
        insert_point.insert_before(NavigableString("\n"))
        insert_point.insert_before(toc_div)
    else:
        body.append(toc_div)

    logging.info(f"Generated amendment {title.lower()} list with {len(entries)} entries")
    return True


def inject_amendment_css_soup(soup: BeautifulSoup) -> None:
    """Inject CSS for amendment/corrigendum styling."""
    css = """
.amendment-cover-page {
  text-align: center;
  padding: 2em 0;
  margin-bottom: 2em;
  border-bottom: 2px solid #333;
  page-break-after: always;
}
.amendment-id { font-size: 1.5em; margin-bottom: 0.5em; }
.amendment-type { font-size: 1.2em; text-transform: uppercase; letter-spacing: 0.1em; }
.amendment-base { font-style: italic; margin: 0.5em 0; }
.amendment-title { font-size: 1.3em; margin: 1em 0; }
.amendment-changed { border-left: 3px solid #0066cc; padding-left: 0.5em; }
.amendment-unchanged { opacity: 0.4; }
.amendment-toc { margin: 1em 0 2em; }
@media print {
  .amendment-unchanged { display: none; }
  .amendment-changed { border-left: none; padding-left: 0; }
}
"""
    inject_css(soup, "amendment-styles", css)


def inject_change_markup_css(soup: BeautifulSoup) -> None:
    """Inject CSS for ins/del change markup styling."""
    inject_css(
        soup,
        "change-markup-styles",
        """
ins.change-ins {
  display: block;
  background: #e6ffe6;
  border-left: 3px solid #28a745;
  padding-left: 0.5em;
  text-decoration: none;
}
del.change-del {
  display: block;
  background: #ffe6e6;
  border-left: 3px solid #dc3545;
  text-decoration: line-through;
  padding-left: 0.5em;
}
""",
    )


def inject_change_markup(
    soup: BeautifulSoup,
    inserted_ids: set,
    deleted_ids: set,
) -> int:
    """Wrap section contents in semantic ins/del change markup.

    Returns count of sections marked.
    """
    from bs4 import BeautifulSoup as BS

    count = 0
    for section in soup.find_all("section"):
        sec_id = section.get("id", "")
        if sec_id in inserted_ids:
            tag_name, css_class = "ins", "change-ins"
        elif sec_id in deleted_ids:
            tag_name, css_class = "del", "change-del"
        else:
            continue

        wrapper = BS(f'<{tag_name} class="{css_class}"></{tag_name}>', "html.parser").find(tag_name)
        for child in list(section.children):
            child.extract()
            wrapper.append(child)
        section.append(wrapper)
        count += 1

    if count:
        inject_change_markup_css(soup)
        logging.info(f"Applied change markup to {count} section(s)")
    return count


def generate_amendment_foreword(
    base_document: str,
    amendment_number: str = "1",
    year: str = "",
) -> str:
    """Generate ISO amendment foreword boilerplate text.

    Args:
        base_document: The base document reference (e.g. "ISO/IEC 14496-10:2022")
        amendment_number: Amendment number (e.g. "1")
        year: Publication year

    Returns:
        HTML string for the foreword section
    """
    amd_ref = f"Amendment {amendment_number}"
    if year:
        amd_ref += f":{year}"

    return (
        f'<section id="foreword" class="foreword">\n'
        f"<h1>Foreword</h1>\n"
        f"<p>ISO (the International Organization for Standardization) and IEC (the International\n"
        f"Electrotechnical Commission) form the specialized system for worldwide standardization.</p>\n"
        f"<p>{base_document}/{amd_ref} was prepared by the relevant technical committee.</p>\n"
        f"<p>This document constitutes {amd_ref} to {base_document}.</p>\n"
        f"</section>"
    )


def generate_clause_change_table(changes: list[dict]) -> str:
    """Generate an HTML table listing clause-by-clause changes.

    Each change dict has: clause (str), change_type (str: add/modify/delete),
    description (str).
    """
    rows = ""
    for ch in changes:
        clause = html.escape(str(ch.get("clause", "")))
        change_type = html.escape(str(ch.get("change_type", "")))
        description = html.escape(str(ch.get("description", "")))
        rows += f"<tr><td>{clause}</td><td>{change_type}</td><td>{description}</td></tr>\n"
    return (
        '<table class="clause-changes">\n'
        "<thead><tr><th>Clause</th><th>Change type</th><th>Description</th></tr></thead>\n"
        f"<tbody>{rows}</tbody>\n"
        "</table>"
    )

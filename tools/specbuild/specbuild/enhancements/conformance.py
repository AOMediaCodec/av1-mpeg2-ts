"""Conformance requirement anchoring and tracking.

Wraps normative statements (containing RFC 2119 keywords) in requirement
anchors and optionally injects a conformance summary table.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from specbuild.analysis.compliance import RFC2119_RE
from specbuild.utils import get_parent_clause_number

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


def inject_conformance_soup(soup: BeautifulSoup) -> int:
    """Add conformance requirement anchors to normative statements.

    Wraps paragraphs containing RFC 2119 keywords in ``<span>`` elements
    with ``class="req"`` and ``id="req-<section>-<NNN>"``.

    Returns the number of requirements anchored.
    """
    count = 0
    section_counters: dict[str, int] = {}

    for p in soup.find_all("p"):
        text = p.get_text()
        if not RFC2119_RE.search(text):
            continue

        if p.find_parent(class_="note") or p.find_parent(class_="example"):
            continue

        section_id = _get_section_id(p)
        section_counters[section_id] = section_counters.get(section_id, 0) + 1
        req_num = section_counters[section_id]

        req_id = f"req-{section_id}-{req_num:03d}"

        if not p.get("id"):
            p["id"] = req_id

        classes = p.get("class", [])
        if "req" not in classes:
            p["class"] = classes + ["req"]

        p["data-req-id"] = req_id
        count += 1

    if count:
        logging.info(f"Anchored {count} conformance requirement(s)")

    return count


def _get_section_id(tag: Tag) -> str:
    """Get the section number for a tag by walking up to its section."""
    clause = get_parent_clause_number(tag)
    if clause:
        return clause.replace(".", "-")
    for parent in tag.parents:
        if parent.name == "section":
            sec_id = parent.get("id", "")
            if sec_id:
                return sec_id
    return "0"

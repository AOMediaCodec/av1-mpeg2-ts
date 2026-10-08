"""Structured requirement, permission, and recommendation blocks.

Detects and enhances elements with class='requirement', 'permission',
or 'recommendation', assigning stable IDs and building a requirement
registry for export.
"""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import get_parent_clause_number

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


_REQ_CLASSES = {"requirement", "permission", "recommendation"}
_REQ_TYPE_MAP = {
    "requirement": "REQ",
    "permission": "PER",
    "recommendation": "REC",
}

# Mapping of normalised DL key labels to metadata field names.
_DL_KEY_MAP: dict[str, str] = {
    "subject": "subject",
    "classification": "classification",
    "category": "classification",
    "verification": "verification",
    "test method": "verification",
    "test": "verification",
}


def _extract_req_metadata(element: Tag) -> dict[str, str]:
    """Extract subject/classification/verification metadata from a requirement block.

    Supports two authoring conventions:
    - DL method: ``<dl class="req-meta"><dt>Subject</dt><dd>encoder</dd>…</dl>``
    - Span method: ``<span class="req-subject">…</span>`` etc.

    DL method takes priority over the span method.  Missing fields default to ``""``.
    """
    meta: dict[str, str] = {"subject": "", "classification": "", "verification": ""}

    # --- DL method (priority) ---
    dl = element.find("dl", class_="req-meta")
    if dl:
        dts = dl.find_all("dt")
        for dt in dts:
            key = dt.get_text(strip=True).lower()
            field = _DL_KEY_MAP.get(key)
            if field:
                dd = dt.find_next_sibling("dd")
                if dd:
                    meta[field] = dd.get_text(strip=True)
        return meta

    # --- Span method (fallback) ---
    for span_class, field in (
        ("req-subject", "subject"),
        ("req-classification", "classification"),
        ("req-verification", "verification"),
    ):
        span = element.find("span", class_=span_class)
        if span:
            meta[field] = span.get_text(strip=True)

    return meta


def process_requirement_blocks_soup(soup: BeautifulSoup) -> int:
    """Process structured requirement blocks in the document.

    Scans for elements with class 'requirement', 'permission', or
    'recommendation'. For each:
    - Assigns a stable ID: REQ-<clause>-<NNN>, PER-<clause>-<NNN>, REC-<clause>-<NNN>
    - Adds data attributes: data-req-type, data-req-id, data-req-clause
    - Adds a visible label span if not already present
    - Builds cross-reference targets

    Returns the number of blocks processed.
    """
    count = 0
    counters: dict[str, dict[str, int]] = {
        "requirement": {},
        "permission": {},
        "recommendation": {},
    }

    for element in soup.find_all(class_=_REQ_CLASSES):
        # Determine which type
        classes = element.get("class", [])
        req_type = None
        for cls in classes:
            if cls in _REQ_CLASSES:
                req_type = cls
                break
        if not req_type:
            continue

        clause = get_parent_clause_number(element) or "0"
        clause_key = clause.replace(".", "-")

        type_counters = counters[req_type]
        type_counters[clause_key] = type_counters.get(clause_key, 0) + 1
        n = type_counters[clause_key]

        prefix = _REQ_TYPE_MAP[req_type]
        req_id = f"{prefix}-{clause_key}-{n:03d}"

        if not element.get("id"):
            element["id"] = req_id
        element["data-req-type"] = req_type
        element["data-req-id"] = req_id
        element["data-req-clause"] = clause

        # Extract and inject semantic metadata attributes
        meta = _extract_req_metadata(element)
        if meta["subject"]:
            element["data-req-subject"] = meta["subject"]
        if meta["classification"]:
            element["data-req-classification"] = meta["classification"]
        if meta["verification"]:
            element["data-req-verification"] = meta["verification"]

        # Add visible label if not present
        existing_label = element.find(class_="req-label")
        if not existing_label:
            from bs4 import NavigableString

            label = soup.new_tag("span", attrs={"class": "req-label"})
            label.string = f"[{req_id}]"
            element.insert(0, label)
            element.insert(1, NavigableString(" "))

        count += 1

    if count:
        _inject_requirement_css(soup)
        link_count = _link_requirement_hierarchy(soup)
        logging.info(
            f"Processed {count} structured requirement block(s), "
            f"{link_count} parent-child relationship(s) established"
        )

    return count


def generate_requirement_summary_soup(soup: BeautifulSoup) -> str | None:
    """Generate an HTML summary table of all requirement blocks.

    Returns HTML string or None if no requirements found.
    """
    blocks = soup.find_all(attrs={"data-req-type": True})
    if not blocks:
        return None

    rows = []
    for block in blocks:
        req_id = html.escape(block.get("data-req-id", ""))
        req_type = html.escape(block.get("data-req-type", ""))
        clause = html.escape(block.get("data-req-clause", ""))
        subject = html.escape(block.get("data-req-subject", ""))
        classification = html.escape(block.get("data-req-classification", ""))
        verification = html.escape(block.get("data-req-verification", ""))
        block_id = html.escape(block.get("id", ""))
        text = html.escape(block.get_text(strip=True)[:120])
        if len(block.get_text(strip=True)) > 120:
            text += "..."

        type_class = f"req-type-{req_type}"
        rows.append(
            f'<tr class="{type_class}">'
            f'<td><a href="#{block_id}">{req_id}</a></td>'
            f"<td>{req_type.title()}</td>"
            f"<td>{clause}</td>"
            f"<td>{subject}</td>"
            f"<td>{classification}</td>"
            f"<td>{verification}</td>"
            f"<td>{text}</td>"
            f"</tr>"
        )

    return (
        '<table class="requirement-summary">\n'
        "<thead><tr>"
        "<th>ID</th><th>Type</th><th>Clause</th>"
        "<th>Subject</th><th>Classification</th><th>Verification</th>"
        "<th>Text</th>"
        "</tr></thead>\n"
        "<tbody>\n" + "\n".join(rows) + "\n</tbody>\n"
        "</table>"
    )


def generate_requirement_registry(soup: BeautifulSoup) -> list[dict]:
    """Return a structured list of all requirement blocks with semantic metadata.

    Each entry contains: id, type, clause, subject, classification,
    verification, and the first 200 characters of the block's prose text
    (stripped of the visible label and metadata markup).
    """
    from bs4 import BeautifulSoup as _BeautifulSoup

    registry: list[dict] = []
    for block in soup.find_all(attrs={"data-req-type": True}):
        # Re-parse the block HTML into an isolated tree so we can safely
        # strip label/metadata nodes without touching the live document.
        work = _BeautifulSoup(str(block), "html.parser")
        for t in work.find_all(class_="req-label"):
            t.decompose()
        dl = work.find("dl", class_="req-meta")
        if dl:
            dl.decompose()
        for span_cls in ("req-subject", "req-classification", "req-verification"):
            for t in work.find_all("span", class_=span_cls):
                t.decompose()

        raw_text = work.get_text(separator=" ", strip=True)
        text_snippet = raw_text[:200]

        registry.append(
            {
                "id": block.get("data-req-id", ""),
                "type": block.get("data-req-type", ""),
                "clause": block.get("data-req-clause", ""),
                "subject": block.get("data-req-subject", ""),
                "classification": block.get("data-req-classification", ""),
                "verification": block.get("data-req-verification", ""),
                "text": text_snippet,
            }
        )
    return registry


_REQ_REF_RE = re.compile(r"\b((?:REQ|PER|REC)-[\w-]+)\b")


def autolink_requirement_ids(soup: BeautifulSoup) -> int:
    """Convert bare REQ-/PER-/REC- IDs in text nodes to hyperlinks.

    Scans all text nodes.  If a text node contains e.g. "REQ-3-2-001"
    and an element with ``id="REQ-3-2-001"`` exists in the document,
    wraps the text in ``<a href="#REQ-3-2-001">``.  Skips text already
    inside ``<a>`` elements.

    Returns the number of links created.
    """
    from bs4 import NavigableString

    # Collect all req IDs that exist as element IDs
    existing_ids: set[str] = {
        el.get("id") for el in soup.find_all(attrs={"data-req-id": True}) if el.get("id")
    }
    existing_ids.update(el["id"] for el in soup.find_all(id=_REQ_REF_RE) if el.get("id"))

    count = 0
    for text_node in soup.find_all(string=_REQ_REF_RE):
        parent = text_node.parent
        if parent is None or parent.name == "a":
            continue
        if parent.find_parent("a"):
            continue

        text = str(text_node)
        parts = _REQ_REF_RE.split(text)
        if len(parts) == 1:
            continue

        new_nodes = []
        for i, part in enumerate(parts):
            if i % 2 == 1 and part in existing_ids:
                a_tag = soup.new_tag("a", href=f"#{part}")
                a_tag.string = part
                new_nodes.append(a_tag)
                count += 1
            elif part:
                new_nodes.append(NavigableString(part))

        if new_nodes:
            for node in new_nodes:
                text_node.insert_before(node)
            text_node.extract()

    if count:
        logging.info(f"Auto-linked {count} requirement ID reference(s)")
    return count


def _link_requirement_hierarchy(soup: BeautifulSoup) -> int:
    """Link parent/child requirement blocks with data attributes.

    For each outer requirement block that contains nested requirement blocks,
    sets ``data-req-children`` on the outer (space-separated list of child
    req IDs) and ``data-req-parent`` on each direct child.

    Returns the number of parent-child relationships established.
    """
    count = 0
    for outer in soup.find_all(class_=lambda c: c and any(rc in c for rc in _REQ_CLASSES)):
        outer_id = outer.get("data-req-id", "")
        if not outer_id:
            continue
        child_ids = []
        for inner in outer.find_all(class_=lambda c: c and any(rc in c for rc in _REQ_CLASSES)):
            inner_id = inner.get("data-req-id", "")
            if not inner_id or inner_id == outer_id:
                continue
            # Skip grandchildren — only link inner blocks whose nearest req ancestor is outer.
            nearest_req_parent = inner.find_parent(
                class_=lambda c: c and any(rc in c for rc in _REQ_CLASSES)
            )
            if nearest_req_parent is not outer:
                continue
            inner["data-req-parent"] = outer_id
            child_ids.append(inner_id)
            count += 1
        if child_ids:
            outer["data-req-children"] = " ".join(child_ids)
    return count


def _inject_requirement_css(soup: BeautifulSoup) -> None:
    from specbuild.utils import inject_css

    css = """
.requirement, .permission, .recommendation {
  border-left: 3px solid; padding: 0.5em 0.75em; margin: 0.75em 0;
  background: var(--color-bg-subtle, #f8f9fa);
}
.requirement { border-color: #c00; }
.permission { border-color: #069; }
.recommendation { border-color: #960; }
.req-label { font-family: monospace; font-size: 0.85em; color: #666; }
.req-type-requirement td:nth-child(2) { color: #c00; font-weight: bold; }
.req-type-permission td:nth-child(2) { color: #069; }
.req-type-recommendation td:nth-child(2) { color: #960; }
"""
    inject_css(soup, "requirement-block-styles", css)

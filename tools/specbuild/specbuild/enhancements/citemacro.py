"""Cite macro processing — {{cite:DocID}} → bibliography links."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


_CITE_MACRO_RE = re.compile(r"\{\{cite:([^}]+)\}\}")


def _normalize_doc_id(doc_id: str) -> str:
    """Normalise a document ID for bibliography anchor lookup.

    Lowercases, strips whitespace, and replaces spaces and slashes with hyphens
    to match the ``ref-*`` anchor naming convention.
    """
    return re.sub(r"[\s/]+", "-", doc_id.strip()).lower()


def _build_bib_anchor_map(soup: BeautifulSoup) -> dict[str, str]:
    """Return a mapping of normalised doc-id → anchor id (without 'ref-' prefix).

    Scans all ``<li id="ref-*">`` and ``<dt id="ref-*">`` elements.
    """
    anchors: dict[str, str] = {}
    for el in soup.find_all(["li", "dt"], id=re.compile(r"^ref-", re.IGNORECASE)):
        anchor_id: str = el["id"]
        # Strip the leading "ref-" prefix, then normalise
        raw = anchor_id[4:]  # everything after "ref-"
        key = raw.lower()
        anchors[key] = anchor_id
    return anchors


def process_cite_macros_soup(soup: BeautifulSoup) -> int:
    """Replace {{cite:DocID}} macros with bibliography anchor links.

    Scans all text nodes in the document body. When it finds {{cite:DocID}},
    replaces it with <a href="#ref-DocID" class="cite-ref">DocID</a> if a
    matching bibliography anchor exists (id="ref-DocID" or matching text).
    Falls back to a <cite> element if no anchor found.

    Returns:
        Number of macro replacements made.
    """
    from bs4 import NavigableString

    bib_map = _build_bib_anchor_map(soup)

    # Collect all text nodes containing at least one cite macro
    # (collect first to avoid mutating the tree while iterating)
    text_nodes = list(soup.find_all(string=_CITE_MACRO_RE))

    total = 0

    for text_node in text_nodes:
        original = str(text_node)
        parts = _CITE_MACRO_RE.split(original)
        # split produces [text, group1, text, group1, ...] where odd indices are captures
        if len(parts) <= 1:
            continue

        parent = text_node.parent
        if parent is None:
            continue

        new_nodes: list = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                # Plain text segment
                if part:
                    new_nodes.append(NavigableString(part))
            else:
                # part is the captured DocID
                doc_id = part
                norm = _normalize_doc_id(doc_id)
                # Try exact key, then try matching by normalised ref- id
                anchor_id: str | None = None
                if norm in bib_map:
                    anchor_id = bib_map[norm]
                else:
                    # Fallback: search for any key that starts with norm or vice versa
                    for key, val in bib_map.items():
                        if key == norm or norm.startswith(key) or key.startswith(norm):
                            anchor_id = val
                            break

                if anchor_id:
                    link = soup.new_tag("a", href=f"#{anchor_id}", **{"class": "cite-ref"})
                    link.string = doc_id
                    new_nodes.append(link)
                else:
                    cite_el = soup.new_tag("cite", **{"class": "cite-ref"})
                    cite_el.string = doc_id
                    new_nodes.append(cite_el)

                total += 1

        # Replace the original text node with the new sequence of nodes
        for node in reversed(new_nodes):
            text_node.insert_after(node)
        text_node.extract()

    return total

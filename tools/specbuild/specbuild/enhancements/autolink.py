"""Auto-link cross-reference patterns in compiled HTML body text.

Scans paragraph, list-item and table-cell containers for clause, figure,
table, annex and equation reference patterns and converts matching text to
hyperlinks pointing at elements already in the document.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import get_bs4, inject_css, read_html, write_html

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_AUTO_XREF_CSS = (
    ".auto-xref { text-decoration: none; border-bottom: 1px dotted #0066cc; color: inherit; }"
)

_CSS_ID = "auto-xref-css"

# ---------------------------------------------------------------------------
# Patterns for cross-reference text
# ---------------------------------------------------------------------------

# Each entry: (compiled regex, label-builder callable)
# The label-builder takes the match object and returns the canonical lookup key.

_XREF_PATTERNS: list[tuple[re.Pattern, Callable[[re.Match], str]]] = [
    # Clause / Section / Sub-clause  e.g. "Clause 7.3.2" / "Section 4" / "Subclause 2.1"
    (
        re.compile(
            r"(?:Clause|Section|Sub-?clause)\s+(\d+(?:\.\d+)*)",
            re.IGNORECASE,
        ),
        lambda m: f"Clause {m.group(1)}",
    ),
    # Table  e.g. "Table 3" / "Table A.1"
    (
        re.compile(r"Table\s+(\w[\w.\-]*)", re.IGNORECASE),
        lambda m: f"Table {m.group(1)}",
    ),
    # Figure / Fig.  e.g. "Figure 3" / "Fig. 3.1"
    (
        re.compile(r"(?:Figure|Fig\.?)\s+(\w[\w.\-]*)", re.IGNORECASE),
        lambda m: f"Figure {m.group(1)}",
    ),
    # Annex  e.g. "Annex A"
    (
        re.compile(r"Annex\s+([A-Z])\b", re.IGNORECASE),
        lambda m: f"Annex {m.group(1).upper()}",
    ),
    # Equation  e.g. "(7-1)" or "(A-3)"
    (
        re.compile(r"\((\d+[-\.]\d+)\)"),
        lambda m: f"({m.group(1)})",
    ),
]

# Tags whose content we scan for xref patterns
_CONTAINER_TAGS = frozenset({"p", "li", "td"})
_CONTAINER_TAGS_LIST = list(_CONTAINER_TAGS)  # cached for find_all()

# Tags that, when an ancestor, mean we skip the text node
_SKIP_ANCESTOR_TAGS = frozenset({"pre", "code", "a", "h1", "h2", "h3", "h4", "h5", "h6"})


# ---------------------------------------------------------------------------
# Anchor-map builder
# ---------------------------------------------------------------------------


def build_anchor_map(soup: BeautifulSoup) -> dict[str, str]:
    """Build a ``{display_text: anchor_id}`` map from the document.

    Collects headings (h2–h6), figures, tables, annexes and equations.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        Dictionary mapping canonical label strings to element ``id`` values.
    """
    anchor_map: dict[str, str] = {}

    # --- Headings h2–h6 ---
    heading_re = re.compile(r"^h[2-6]$")
    for tag in soup.find_all(heading_re):
        hid = tag.get("id")
        if not hid:
            continue
        text = tag.get_text(strip=True)

        # Look for a numeric section prefix e.g. "7.3.2 Title" or "A.1 Title"
        m = re.match(r"^(\d+(?:\.\d+)*)\b", text)
        if m:
            num = m.group(1)
            anchor_map[f"Clause {num}"] = hid
            anchor_map[f"Section {num}"] = hid
            anchor_map[num] = hid

        # Annex headings: "Annex A …"
        m_annex = re.match(r"Annex\s+([A-Z])\b", text, re.IGNORECASE)
        if m_annex:
            letter = m_annex.group(1).upper()
            anchor_map[f"Annex {letter}"] = hid
            anchor_map[letter] = hid

    # --- Figures ---
    fig_num_re = re.compile(r"Figure\s+(\w[\w.\-]*)", re.IGNORECASE)
    # <figure id="...">
    for fig in soup.find_all("figure"):
        fid = fig.get("id")
        if not fid:
            continue
        caption = fig.find("figcaption")
        if caption:
            cap_text = caption.get_text(strip=True)
            m = fig_num_re.search(cap_text)
            if m:
                num = m.group(1)
                anchor_map[f"Figure {num}"] = fid
                anchor_map[f"Fig. {num}"] = fid
                anchor_map[f"Fig {num}"] = fid
    # <p id="fig-...">
    for p in soup.find_all("p", id=re.compile(r"^fig-")):
        fid = p.get("id")
        cap_text = p.get_text(strip=True)
        m = fig_num_re.search(cap_text)
        if m:
            num = m.group(1)
            anchor_map[f"Figure {num}"] = fid
            anchor_map[f"Fig. {num}"] = fid
            anchor_map[f"Fig {num}"] = fid

    # --- Tables ---
    tbl_num_re = re.compile(r"Table\s+(\w[\w.\-]*)", re.IGNORECASE)
    for tbl in soup.find_all("table"):
        # Accept id on the table itself or id containing "table-"
        tid = tbl.get("id")
        if not tid:
            continue
        caption = tbl.find("caption")
        if caption:
            cap_text = caption.get_text(strip=True)
            m = tbl_num_re.search(cap_text)
            if m:
                num = m.group(1)
                anchor_map[f"Table {num}"] = tid
    # Elements with id containing "table-"
    for el in soup.find_all(id=re.compile(r"table-")):
        if el.name == "table":
            continue  # already handled above
        tid = el.get("id")
        cap_text = el.get_text(strip=True)
        m = tbl_num_re.search(cap_text)
        if m:
            num = m.group(1)
            anchor_map.setdefault(f"Table {num}", tid)

    # --- Equations ---
    eq_id_re = re.compile(r"^eq-")
    eq_label_re = re.compile(r"\((\d+[-\.]\d+)\)")
    for el in soup.find_all(id=eq_id_re):
        eid = el.get("id")
        text = el.get_text(strip=True)
        m = eq_label_re.search(text)
        if m:
            anchor_map[f"({m.group(1)})"] = eid
        else:
            # Derive label from the id itself: "eq-7-1" → "(7-1)"
            id_m = re.search(r"eq-(\d+[-\.]?\d*)", eid)
            if id_m:
                raw = id_m.group(1).replace("-", ".")
                anchor_map.setdefault(f"({raw})", eid)

    return anchor_map


# ---------------------------------------------------------------------------
# Auto-linker
# ---------------------------------------------------------------------------


def auto_link_xrefs_soup(
    soup: BeautifulSoup,
    anchor_map: dict[str, str] | None = None,
) -> int:
    """Scan prose containers and wrap cross-reference patterns in ``<a>`` links.

    Args:
        soup: BeautifulSoup document (mutated in place).
        anchor_map: Pre-built map of ``{label: anchor_id}``.  If *None*,
            :func:`build_anchor_map` is called automatically.

    Returns:
        Number of links created.
    """
    from bs4 import NavigableString

    if anchor_map is None:
        anchor_map = build_anchor_map(soup)

    if not anchor_map:
        return 0

    total = 0

    for container in soup.find_all(_CONTAINER_TAGS_LIST):
        # Skip if any ancestor is in the skip-set
        skip = False
        for ancestor in container.parents:
            if getattr(ancestor, "name", None) in _SKIP_ANCESTOR_TAGS:
                skip = True
                break
        if skip:
            continue

        # Collect plain text nodes that are not inside skipped sub-elements
        text_nodes: list = []
        for node in list(container.descendants):
            if not isinstance(node, NavigableString):
                continue
            if any(
                getattr(p, "name", None) in _SKIP_ANCESTOR_TAGS
                for p in node.parents
                if p is not container
            ):
                continue
            text_nodes.append(node)

        # Process first matching xref per container
        linked_in_container = False
        for text_node in text_nodes:
            if linked_in_container:
                break
            text = str(text_node)
            for pattern, label_fn in _XREF_PATTERNS:
                m = pattern.search(text)
                if not m:
                    continue
                label = label_fn(m)
                anchor_id = anchor_map.get(label)
                if anchor_id is None:
                    continue
                # Build replacement: split around the match
                pre_text = text[: m.start()]
                match_text = text[m.start() : m.end()]
                post_text = text[m.end() :]

                parent = text_node.parent
                if parent is None:
                    continue

                a_tag = soup.new_tag("a", href=f"#{anchor_id}", **{"class": "auto-xref"})
                a_tag.string = match_text

                fragments: list = []
                if pre_text:
                    fragments.append(NavigableString(pre_text))
                fragments.append(a_tag)
                if post_text:
                    fragments.append(NavigableString(post_text))

                for frag in reversed(fragments):
                    text_node.insert_after(frag)
                text_node.extract()

                total += 1
                linked_in_container = True
                break

    if total > 0 and not soup.find("style", id=_CSS_ID):
        inject_css(soup, _CSS_ID, _AUTO_XREF_CSS)

    log.info("auto_link_xrefs_soup: created %d cross-reference links", total)
    return total


# ---------------------------------------------------------------------------
# File-based wrapper
# ---------------------------------------------------------------------------


def auto_link_xrefs(html_path: Path) -> int:
    """Read an HTML file, auto-link cross-references, and write it back.

    Args:
        html_path: Path to an HTML file produced by Bikeshed.

    Returns:
        Number of links created.
    """
    try:
        get_bs4()
    except ImportError:
        log.warning("BeautifulSoup not available, skipping auto-link xrefs")
        return 0

    soup = read_html(html_path)
    count = auto_link_xrefs_soup(soup)
    if count:
        write_html(html_path, soup)
    return count

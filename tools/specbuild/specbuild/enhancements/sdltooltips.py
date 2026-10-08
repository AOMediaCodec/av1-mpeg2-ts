"""SDL syntax element tooltips — semantic descriptions on hover.

Scans the compiled HTML for SDL syntax tables and attaches ``data-tooltip``
attributes to variable-name cells whose names appear in the document prose
with a semantic description (typically introduced with ``**name**``).

Usage::

    from specbuild.enhancements.sdltooltips import add_syntax_tooltips_soup
    count = add_syntax_tooltips_soup(soup)
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import inject_css, inject_js

# Tag names to scan for semantic descriptions, in priority order.
# ``dfn`` first so formal definitions win over casual bold references.
_DESCRIPTION_TAGS = ("dfn", "b", "strong")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _normalise_var_name(raw: str) -> str:
    """Normalise a variable name for fuzzy matching against descriptions.

    Preserves underscores to avoid false-positive collisions between
    similarly-named variables (e.g. ``delta_q_y_dc`` vs ``delta_qy_dc``).
    """
    name = re.sub(r"\[.*?\]", "", raw)
    name = name.strip().rstrip(";").strip()
    return name.lower().replace("-", "")


# ---------------------------------------------------------------------------
# Description extraction
# ---------------------------------------------------------------------------


def _extract_descriptions(soup: BeautifulSoup, target_names: frozenset[str]) -> dict[str, str]:
    """Build a map of variable name → semantic description from document prose.

    Only extracts descriptions for names in *target_names* (the normalised
    variable names found in SDL tables), avoiding unnecessary DOM traversal
    for irrelevant bold/dfn tags.

    Args:
        soup: BeautifulSoup document.
        target_names: Frozenset of normalised variable names to look up.

    Returns:
        Dict mapping normalised variable names to short description strings.
    """
    descriptions: dict[str, str] = {}

    for tag_name in _DESCRIPTION_TAGS:
        for tag in soup.find_all(tag_name):
            name = tag.get_text(strip=True)
            if not name or " " in name:
                continue

            norm = name.lower().replace("-", "")
            if norm not in target_names or norm in descriptions:
                continue

            parent = tag.find_parent(["p", "li", "dd"])
            if not parent:
                continue

            full_text = parent.get_text(separator=" ", strip=True)
            full_text = re.sub(r"\s+", " ", full_text)
            if len(full_text) > 200:
                full_text = full_text[:197] + "..."

            descriptions[norm] = full_text

    logging.debug(
        f"Extracted {len(descriptions)} syntax element descriptions "
        f"(from {len(target_names)} target names)"
    )
    return descriptions


# ---------------------------------------------------------------------------
# Tooltip attachment
# ---------------------------------------------------------------------------


def add_syntax_tooltips_soup(
    soup: BeautifulSoup, css: str | None = None, js: str | None = None
) -> int:
    """Attach tooltip data attributes to SDL syntax table variable cells.

    Args:
        soup: BeautifulSoup document (mutated in place).
        css: Pre-read CSS content for tooltip styling (optional).
        js: Pre-read JS content for tooltip behaviour (optional).

    Returns:
        Number of tooltip attributes added.
    """
    tables = soup.find_all("table", class_="sdl-syntax-table")
    if not tables:
        logging.debug("No SDL syntax tables found; skipping syntax tooltips")
        return 0

    # Phase 1: Collect all variable names from SDL tables (cheap).
    var_cells_by_norm: dict[str, list] = {}
    for table in tables:
        for cell in table.find_all("td", class_="sdl-var-with-descriptor"):
            span = cell.find("span")
            if not span:
                continue
            raw_text = span.get_text(strip=True)
            if not raw_text:
                continue
            norm = _normalise_var_name(raw_text)
            if norm:
                var_cells_by_norm.setdefault(norm, []).append(cell)

    if not var_cells_by_norm:
        return 0

    # Phase 2: Search prose only for the names we actually need.
    descriptions = _extract_descriptions(soup, frozenset(var_cells_by_norm))
    if not descriptions:
        logging.debug("No syntax element descriptions found in prose")
        return 0

    # Phase 3: Attach tooltips.
    count = 0
    for norm, desc in descriptions.items():
        for cell in var_cells_by_norm[norm]:
            cell["data-tooltip"] = desc
            classes = cell.get("class", [])
            if "has-syntax-tooltip" not in classes:
                cell["class"] = classes + ["has-syntax-tooltip"]
            count += 1

    if count > 0:
        if css:
            inject_css(soup, "syntax-tooltips-css", css)
        else:
            logging.warning("syntax-tooltips.css not provided; skipping CSS")
        if js:
            inject_js(soup, "syntax-tooltips-js", js)
        else:
            logging.warning("syntax-tooltips.js not provided; skipping JS")

        logging.debug(
            f"Attached {count} syntax element tooltip(s) across {len(tables)} SDL table(s)"
        )

    return count

"""Structured contributor/editor block rendering.

Parses ``<meta name="editor">``, ``<meta name="author">``, and
``<meta name="contributor">`` tags from the document ``<head>`` and renders
them as a properly structured HTML block with a ``<table>`` or ``<dl>``.

Authoring example in the Bikeshed source::

    <meta name="editor" content="Alice Smith, ACME Corp">
    <meta name="editor" content="Bob Jones (Chair), ISO TC/SC">
    <meta name="author" content="Carol White <carol@example.com>, W3C">

The rendered output replaces (or augments) any bare editor paragraph list
emitted by Bikeshed with a proper contributors table.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

from specbuild.utils import inject_css

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_META_NAMES: tuple[str, ...] = ("editor", "author", "contributor")

# Regex to extract inline email: "Name <email@example.com>"
_EMAIL_RE = re.compile(r"^(.*?)\s*<([^>]+)>\s*(.*)$")

# Regex to extract inline role: "Name (Role)"
_ROLE_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)\s*(.*)$")

_CONTRIBUTOR_CSS = """\
/* Contributor block */
.contributors-table { border-collapse: collapse; margin: 1em 0; font-size: 0.9em; }
.contributors-table th, .contributors-table td { padding: 0.3em 0.8em; text-align: left; border-bottom: 1px solid #ddd; }
.contributors-table th { font-weight: 600; background: #f5f5f5; }
.contributors-section { margin: 1em 0 2em; }
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_contributor_value(value: str, default_role: str) -> dict[str, str]:
    """Parse a single meta tag *value* string into contributor fields.

    Supported formats (in order of detection):
    - ``"Name <email>, Affiliation"``
    - ``"Name (Role), Affiliation"``
    - ``"Name, Affiliation"``

    Args:
        value: Raw content attribute string.
        default_role: Role string to assign when not encoded in the value
            (typically the meta tag name: ``"editor"``, ``"author"``,
            ``"contributor"``).

    Returns:
        Dict with keys ``name``, ``affiliation``, ``role``, ``email``.
    """
    value = value.strip()
    name = ""
    affiliation = ""
    role = default_role
    email = ""

    # Try to extract email first
    email_match = _EMAIL_RE.match(value)
    if email_match:
        name_part = email_match.group(1).strip()
        email = email_match.group(2).strip()
        rest = email_match.group(3).strip()
        # rest might be ", Affiliation" or just "Affiliation"
        affiliation = rest.lstrip(",").strip()
        name = name_part
    else:
        # Split on first comma to get name vs affiliation
        parts = value.split(",", 1)
        name = parts[0].strip()
        affiliation = parts[1].strip() if len(parts) > 1 else ""

    # Try to extract role from name (e.g. "Bob Jones (Chair)")
    role_match = _ROLE_RE.match(name)
    if role_match:
        name = role_match.group(1).strip()
        role = role_match.group(2).strip()

    return {"name": name, "affiliation": affiliation, "role": role, "email": email}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_contributors(soup: BeautifulSoup) -> list[dict[str, str]]:
    """Return parsed contributor dicts from meta tags in *soup*.

    Reads ``<meta name="editor">``, ``<meta name="author">``, and
    ``<meta name="contributor">`` tags in document order.

    Returns:
        List of ``{"name": ..., "affiliation": ..., "role": ..., "email": ...}``
        dicts suitable for use by other modules (e.g. Relaton export).
    """
    contributors: list[dict[str, str]] = []
    for meta_name in _META_NAMES:
        for meta in soup.find_all("meta", attrs={"name": meta_name}):
            content = meta.get("content", "").strip()
            if not content:
                continue
            entry = _parse_contributor_value(content, default_role=meta_name)
            contributors.append(entry)
    return contributors


def inject_contributor_css(soup: BeautifulSoup) -> None:
    """Inject contributor-table CSS into *soup* if not already present."""
    if not soup.find("style", id="contributor-css"):
        inject_css(soup, "contributor-css", _CONTRIBUTOR_CSS)


def process_contributor_block_soup(soup: BeautifulSoup) -> int:
    """Parse editor/author/contributor meta tags and render structured block.

    Reads ``<meta name="editor">``, ``<meta name="author">``, and
    ``<meta name="contributor">`` tags.

    Finds an existing ``.head``, ``#abstract``, or ``<section>`` with class
    ``"editors"`` or ``"contributors"``, or a heading matching ``"Editors?"``
    or ``"Authors?"``.  If found, replaces any bare paragraph list with a
    proper ``<table>`` or ``<dl>``.  If not found, inserts a
    ``<section class="contributors">`` block after the document title element
    (``<h1>``) in the body.

    Uses a ``<table class="contributors-table">`` when multiple columns are
    populated; falls back to a ``<dl class="contributors-list">`` when only
    names are present.

    Returns:
        Number of contributors rendered.
    """
    contributors = extract_contributors(soup)
    if not contributors:
        return 0

    # Build the contributor block element
    block = _build_contributor_block(soup, contributors)

    # Try to find an existing section to replace / augment
    target = _find_existing_contributor_section(soup)
    if target is not None:
        _replace_with_block(soup, target, block)
    else:
        _insert_after_title(soup, block)

    inject_contributor_css(soup)
    logging.info(f"Rendered {len(contributors)} contributor(s)")
    return len(contributors)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _has_multiple_columns(contributors: list[dict[str, str]]) -> bool:
    """Return True if any contributor has a non-empty affiliation or role."""
    return any(c.get("affiliation") or c.get("email") for c in contributors)


def _build_contributor_block(soup: BeautifulSoup, contributors: list[dict[str, str]]) -> Tag:
    """Build and return the contributor block as a ``<section>`` Tag."""
    section: Tag = soup.new_tag("section", **{"class": "contributors-section"})

    heading: Tag = soup.new_tag("h2")
    heading.string = "Contributors"
    section.append(heading)

    if _has_multiple_columns(contributors):
        section.append(_build_table(soup, contributors))
    else:
        section.append(_build_dl(soup, contributors))

    return section


def _build_table(soup: BeautifulSoup, contributors: list[dict[str, str]]) -> Tag:
    """Build a ``<table class="contributors-table">`` from *contributors*."""
    table: Tag = soup.new_tag("table", **{"class": "contributors-table"})

    # Header row
    thead: Tag = soup.new_tag("thead")
    header_row: Tag = soup.new_tag("tr")
    for col in ("Name", "Affiliation", "Role"):
        th: Tag = soup.new_tag("th")
        th.string = col
        header_row.append(th)
    thead.append(header_row)
    table.append(thead)

    # Body rows
    tbody: Tag = soup.new_tag("tbody")
    for contrib in contributors:
        tr: Tag = soup.new_tag("tr")
        for field in ("name", "affiliation", "role"):
            td: Tag = soup.new_tag("td")
            td.string = contrib.get(field, "")
            tr.append(td)
        tbody.append(tr)
    table.append(tbody)

    return table


def _build_dl(soup: BeautifulSoup, contributors: list[dict[str, str]]) -> Tag:
    """Build a ``<dl class="contributors-list">`` from *contributors*."""
    dl: Tag = soup.new_tag("dl", **{"class": "contributors-list"})
    for contrib in contributors:
        dt: Tag = soup.new_tag("dt")
        dt.string = contrib.get("name", "")
        dl.append(dt)
        role = contrib.get("role", "")
        if role:
            dd: Tag = soup.new_tag("dd")
            dd.string = role
            dl.append(dd)
    return dl


def _find_existing_contributor_section(soup: BeautifulSoup) -> Tag | None:
    """Return an existing contributor/editor section element, or ``None``."""
    # Check for section with class "editors" or "contributors"
    for cls in ("editors", "contributors"):
        section = soup.find("section", class_=cls)
        if section is not None:
            return section  # type: ignore[return-value]

    # Check for heading text matching "Editors?" or "Authors?"
    _heading_re = re.compile(r"^(Editors?|Authors?)$", re.IGNORECASE)
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if _heading_re.match(tag.get_text(strip=True)):
            parent = tag.parent
            if parent and parent.name == "section":
                return parent  # type: ignore[return-value]

    # Check for .head or #abstract
    for selector_id in ("abstract",):
        el = soup.find(id=selector_id)
        if el is not None:
            return None  # Found but use insertion after title, not replacement

    head_div = soup.find(class_="head")
    if head_div is not None:
        return None  # Found .head, use insertion strategy

    return None


def _replace_with_block(soup: BeautifulSoup, target: Tag, block: Tag) -> None:
    """Remove bare paragraph lists from *target* and append the *block* content."""
    import copy

    # Remove bare <p> children that look like contributor entries (flat list)
    for p in target.find_all("p", recursive=False):
        p.decompose()

    # Append the table/dl from block into the target section
    for child in list(block.children):
        # Skip the "Contributors" heading we generated; keep the existing one
        if hasattr(child, "name") and child.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            continue
        target.append(copy.copy(child))


def _insert_after_title(soup: BeautifulSoup, block: Tag) -> None:
    """Insert *block* after the first ``<h1>`` in the document body."""
    body = soup.find("body")
    if body is None:
        return

    h1 = body.find("h1")
    if h1 is not None:
        h1.insert_after(block)
    else:
        # Fall back: prepend to body
        body.insert(0, block)

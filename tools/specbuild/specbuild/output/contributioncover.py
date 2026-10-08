"""Contribution cover page generator for JVET/MPEG/AOM standards contributions.

Generates an HTML cover page styled for the target SDO, injected as the first
section of the compiled spec for submission-ready documents.
"""

from __future__ import annotations

import html as _html
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class ContributionMetadata:
    """Metadata for a standards contribution cover page."""

    input_doc: str = ""
    meeting: str = ""
    title: str = ""
    authors: list[str] = field(default_factory=list)
    affiliation: str = ""
    status: str = "Input"
    abstract: str = ""
    date: str = ""


# ---------------------------------------------------------------------------
# Cover page builders
# ---------------------------------------------------------------------------


def build_cover_page(meta: ContributionMetadata, flavor: str = "jvet") -> str:
    """Build an HTML cover page fragment for *meta*.

    Args:
        meta:   Contribution metadata.
        flavor: SDO style: ``"jvet"``, ``"mpeg"``, or ``"aom"``.

    Returns:
        HTML string (a ``<section>`` element) ready to prepend to the spec body.
    """
    flavor = flavor.lower()
    if flavor in ("mpeg", "iso"):
        return _build_mpeg_cover(meta)
    if flavor == "aom":
        return _build_aom_cover(meta)
    return _build_jvet_cover(meta)


def inject_cover_page_soup(
    soup: object,
    meta: ContributionMetadata,
    flavor: str = "jvet",
) -> bool:
    """Prepend a contribution cover page to the HTML document body.

    The cover page is inserted as the first ``<section>`` child of
    ``<main>`` (or ``<body>`` if no ``<main>`` exists), before the TOC
    and scope sections.

    Args:
        soup:   BeautifulSoup document (mutated in place).
        meta:   Contribution metadata.
        flavor: SDO style passed to :func:`build_cover_page`.

    Returns:
        ``True`` if the cover page was injected successfully.
    """
    try:
        from bs4 import BeautifulSoup as BS4

        cover_html = build_cover_page(meta, flavor)
        _cover_doc = BS4(cover_html, "html.parser")
        cover_frag = _cover_doc.find("section", class_="contribution-cover") or next(
            (c for c in (_cover_doc.body or _cover_doc).children if getattr(c, "name", None)),
            None,
        )
        if cover_frag is None:
            logging.warning("Cover page HTML produced no insertable element")
            return False

        target = soup.find("main") or soup.find("body")
        if target is None:
            logging.warning("No <main> or <body> element found; cover page not injected")
            return False

        first_child = next(
            (c for c in target.children if getattr(c, "name", None) is not None),
            None,
        )
        if first_child:
            first_child.insert_before(cover_frag)
        else:
            target.append(cover_frag)

        logging.info(f"Contribution cover page injected ({flavor} style)")
        return True
    except Exception as exc:
        logging.error(f"Failed to inject cover page: {exc}")
        return False


def load_contribution_metadata_from_config(config_data: dict) -> ContributionMetadata:
    """Load :class:`ContributionMetadata` from a TOML config dict.

    Expected TOML structure::

        [standards.contribution]
        input_doc = "JVET-AJ0123"
        meeting = "123rd JVET Meeting, Geneva, January 2026"
        status = "Input"
        authors = ["Alexis Tourapis", "..."]
        affiliation = "Apple Inc."
        abstract = "This contribution proposes ..."
    """
    contrib = config_data.get("standards", {}).get("contribution", {})
    authors = contrib.get("authors", [])
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(",") if a.strip()]

    return ContributionMetadata(
        input_doc=contrib.get("input_doc", ""),
        meeting=contrib.get("meeting", ""),
        title=contrib.get("title", ""),
        authors=authors,
        affiliation=contrib.get("affiliation", ""),
        status=contrib.get("status", "Input"),
        abstract=contrib.get("abstract", ""),
        date=contrib.get("date", ""),
    )


# ---------------------------------------------------------------------------
# SDO-flavored templates
# ---------------------------------------------------------------------------

_CSS = """
<style>
.contribution-cover {
  font-family: Arial, Helvetica, sans-serif;
  border: 1px solid #ccc;
  padding: 1.5em 2em;
  margin-bottom: 2em;
  page-break-after: always;
}
.contribution-cover table {
  border-collapse: collapse;
  width: 100%;
  font-size: 0.92em;
}
.contribution-cover th, .contribution-cover td {
  border: 1px solid #aaa;
  padding: 0.4em 0.8em;
  vertical-align: top;
}
.contribution-cover th {
  background: #f0f0f0;
  font-weight: bold;
  width: 22%;
  white-space: nowrap;
}
.cover-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1.5em;
}
.cover-doc-id {
  font-size: 1.2em;
  font-weight: bold;
  color: #003366;
}
.cover-title {
  font-size: 1.1em;
  font-weight: bold;
  text-align: center;
  margin: 1em 0;
  color: #003366;
}
.cover-status-badge {
  display: inline-block;
  padding: 2px 10px;
  background: #003366;
  color: #fff;
  border-radius: 3px;
  font-size: 0.85em;
}
.cover-abstract {
  margin-top: 1em;
  font-size: 0.9em;
  border-top: 1px solid #ddd;
  padding-top: 0.75em;
}
</style>
"""


def _escape(text: str) -> str:
    return _html.escape(text)


def _build_abstract_block(meta: ContributionMetadata) -> str:
    if not meta.abstract:
        return ""
    return f'<div class="cover-abstract"><strong>Abstract:</strong> {_escape(meta.abstract)}</div>'


def _authors_str(meta: ContributionMetadata) -> str:
    authors = meta.authors if meta.authors else ["—"]
    joined = ", ".join(_escape(a) for a in authors)
    if meta.affiliation:
        joined += f" ({_escape(meta.affiliation)})"
    return joined


def _build_jvet_cover(meta: ContributionMetadata) -> str:
    date_cell = _escape(meta.date) if meta.date else "—"
    abstract_block = _build_abstract_block(meta)

    return f"""{_CSS}
<section id="contribution-cover" class="contribution-cover">
<div class="cover-header">
  <div>
    <span class="cover-doc-id">{_escape(meta.input_doc)}</span>
  </div>
  <div style="text-align:right">
    <span class="cover-status-badge">{_escape(meta.status)}</span><br/>
    <small>{date_cell}</small>
  </div>
</div>
<div class="cover-title">{_escape(meta.title)}</div>
<table>
  <tr><th>Meeting</th><td>{_escape(meta.meeting)}</td></tr>
  <tr><th>Document</th><td>{_escape(meta.input_doc)}</td></tr>
  <tr><th>Author(s)</th><td>{_authors_str(meta)}</td></tr>
  <tr><th>Status</th><td>{_escape(meta.status)}</td></tr>
  <tr><th>Date</th><td>{date_cell}</td></tr>
</table>
{abstract_block}
</section>
"""


def _build_mpeg_cover(meta: ContributionMetadata) -> str:
    date_cell = _escape(meta.date) if meta.date else "—"
    abstract_block = _build_abstract_block(meta)

    return f"""{_CSS}
<section id="contribution-cover" class="contribution-cover">
<div class="cover-header">
  <div>
    <span class="cover-doc-id">{_escape(meta.input_doc)}</span><br/>
    <small style="color:#666">ISO/IEC JTC 1/SC 29</small>
  </div>
  <div style="text-align:right">
    <span class="cover-status-badge">{_escape(meta.status)}</span><br/>
    <small>{date_cell}</small>
  </div>
</div>
<div class="cover-title">{_escape(meta.title)}</div>
<table>
  <tr><th>Source</th><td>{_authors_str(meta)}</td></tr>
  <tr><th>Status</th><td>{_escape(meta.status)}</td></tr>
  <tr><th>Meeting</th><td>{_escape(meta.meeting)}</td></tr>
  <tr><th>Document No.</th><td>{_escape(meta.input_doc)}</td></tr>
  <tr><th>Date</th><td>{date_cell}</td></tr>
</table>
{abstract_block}
</section>
"""


def _build_aom_cover(meta: ContributionMetadata) -> str:
    date_cell = _escape(meta.date) if meta.date else "—"
    abstract_block = _build_abstract_block(meta)

    return f"""{_CSS}
<section id="contribution-cover" class="contribution-cover"
  style="border-top: 4px solid #00a94f;">
<div class="cover-header">
  <div>
    <span class="cover-doc-id" style="color:#00a94f;">{_escape(meta.input_doc)}</span>
  </div>
  <div style="text-align:right">
    <span class="cover-status-badge" style="background:#00a94f;">{_escape(meta.status)}</span><br/>
    <small>{date_cell}</small>
  </div>
</div>
<div class="cover-title" style="color:#00a94f;">{_escape(meta.title)}</div>
<table>
  <tr><th>Author(s)</th><td>{_authors_str(meta)}</td></tr>
  <tr><th>Meeting</th><td>{_escape(meta.meeting)}</td></tr>
  <tr><th>Document</th><td>{_escape(meta.input_doc)}</td></tr>
  <tr><th>Date</th><td>{date_cell}</td></tr>
</table>
{abstract_block}
</section>
"""

"""Build context shared across all plugin phases.

The :class:`BuildContext` dataclass carries all state that plugins may need.
Each plugin's ``func`` receives a single ``ctx: BuildContext`` argument and
extracts whatever it needs — the underlying module functions keep their
existing signatures.

Usage in a plugin::

    @register_quality_check(
        name='check-images',
        cli_flags=['--check-images', '--check-images-strict'],
        description='Check for broken image references.',
    )
    def check_images(ctx: BuildContext):
        from specbuild.checks.imagecheck import check_images_soup, report_missing_images
        issues = check_images_soup(ctx.soup, ctx.html_path.parent)
        if ctx.report is not None:
            ctx.report.broken_images = issues
        report_missing_images(issues, ctx.html_path,
                              strict=ctx.args.check_images_strict)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bs4 import BeautifulSoup
    from bs4.element import Tag

    from specbuild.analysis.buildreport import BuildReportData
    from specbuild.standards.flavors import FlavorSpec


def compute_lookup_maps(soup: BeautifulSoup | None) -> dict[str, Any]:
    """Build O(1) lookup maps over a BeautifulSoup document.

    Walks the soup once and produces:

    - ``ids_by_id``: ``{id_value: element}`` for every element with an ``id``
      attribute.  When multiple elements share an id (rare/invalid HTML) the
      first occurrence in document order wins, matching ``soup.find(id=...)``.
    - ``links_by_href``: ``{href_value: [<a>, ...]}`` grouping every
      ``<a href="...">`` by its href, preserving document order.

    Plugins that previously called ``soup.find(id=...)`` or
    ``soup.find_all("a", href=True)`` repeatedly can read these maps from
    ``ctx.precomputed`` to avoid re-walking the tree on every check.

    Args:
        soup: BeautifulSoup document, or ``None``.

    Returns:
        Dict with keys ``"ids_by_id"`` and ``"links_by_href"``.  Both are
        empty when *soup* is ``None``.
    """
    ids_by_id: dict[str, Tag] = {}
    links_by_href: dict[str, list[Tag]] = {}
    if soup is None:
        return {"ids_by_id": ids_by_id, "links_by_href": links_by_href}

    for elem in soup.find_all(True):
        elem_id = elem.get("id") if hasattr(elem, "get") else None
        if elem_id and elem_id not in ids_by_id:
            ids_by_id[elem_id] = elem
        if getattr(elem, "name", None) == "a":
            href = elem.get("href")
            if href:
                links_by_href.setdefault(href, []).append(elem)

    return {"ids_by_id": ids_by_id, "links_by_href": links_by_href}


def resolve_lookup_maps(
    soup: BeautifulSoup | None, ctx: BuildContext | None
) -> tuple[dict[str, Tag], dict[str, list[Tag]]]:
    """Return ``(ids_by_id, links_by_href)`` from *ctx* or compute on demand.

    Plugins that accept an optional ``ctx`` parameter use this helper to read
    from the precomputed maps when available and fall back to a fresh walk
    when called outside the build pipeline (e.g. from a test harness).
    """
    if ctx is not None and ctx.precomputed:
        ids_by_id = ctx.precomputed.get("ids_by_id")
        links_by_href = ctx.precomputed.get("links_by_href")
        if ids_by_id is not None and links_by_href is not None:
            return ids_by_id, links_by_href
    maps = compute_lookup_maps(soup)
    return maps["ids_by_id"], maps["links_by_href"]


@dataclass
class BuildContext:
    """Shared state container for the build pipeline.

    Created once in ``_run_build()`` and passed to every plugin.
    Quality checks treat ``soup`` as read-only; enhancements may mutate it
    and set ``dirty = True``.
    """

    # --- Core state ---
    args: argparse.Namespace
    html_path: Path
    target_dir: Path

    # --- Parsed HTML (set before enhancement / quality-check phases) ---
    soup: BeautifulSoup | None = None

    # --- Build report (populated by quality checks) ---
    report: BuildReportData | None = None

    # --- Pre-computed I/O data (populated before enhancement phase) ---
    precomputed: dict[str, Any] = field(default_factory=dict)

    # --- Mutation tracking (enhancements set this to True) ---
    dirty: bool = False

    # --- Build identity ---
    branch_name: str = ""
    sha: str = ""
    spec_date: str = ""

    # --- Front-matter order (from manifest, used by PDF generation) ---
    front_matter_order: list[str] | None = None

    # --- Standards flavor (set when a standards body is selected) ---
    standards_flavor: FlavorSpec | None = None

    # --- Plugin metadata (arbitrary key→value store for inter-plugin communication) ---
    metadata: dict = field(default_factory=dict)

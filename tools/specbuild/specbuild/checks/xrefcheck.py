"""Cross-reference validation with Metanorma-compatible error codes.

Provides three error categories analogous to Metanorma's METANORMA_1/2/3:

- **XREF-1** — unresolved internal anchor (``#target`` not found in document)
- **XREF-2** — broken cross-part reference (``../partN/index.html#anchor`` not found)
- **XREF-3** — unresolved external bibliography reference
  (``<a href="#biblio-key">`` or ``<a href="#ref-key">`` without a matching
  bibliography entry)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import find_nearest_heading

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.context import BuildContext


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_xrefs_soup(
    soup: BeautifulSoup,
    *,
    parts_dir: Path | None = None,
    check_erefs: bool = True,
    ctx: BuildContext | None = None,
) -> list[dict]:
    """Run all three cross-reference checks and return a unified issue list.

    Each issue dict contains:

    - ``code``  — ``"XREF-1"``, ``"XREF-2"``, or ``"XREF-3"``
    - ``href``  — raw href attribute value that triggered the issue
    - ``text``  — visible link text (may be empty)
    - ``issue`` — human-readable description
    - ``context`` — nearest heading for localisation (may be empty)

    Args:
        soup:         BeautifulSoup document (read-only).
        parts_dir:    If provided, XREF-2 checks resolve cross-part paths
                      relative to this directory.
        check_erefs:  Whether to run the XREF-3 bibliography-eref check.
        ctx:          Optional :class:`BuildContext` carrying prebuilt
                      ``ids_by_id``/``links_by_href`` lookup maps in
                      ``ctx.precomputed``.
    """
    ids_by_id, links_by_href = _resolve_lookup_maps(soup, ctx)
    all_ids: set[str] = set(ids_by_id.keys())

    issues: list[dict] = []
    issues.extend(_check_xref1(soup, all_ids, links_by_href))
    issues.extend(_check_xref2(soup, parts_dir))
    if check_erefs:
        issues.extend(_check_xref3(soup, all_ids, links_by_href))
    return issues


def report_xref_issues(
    issues: list[dict],
    *,
    strict: bool = False,
) -> None:
    """Log cross-reference issues and optionally exit on errors.

    Args:
        issues: List as returned by :func:`check_xrefs_soup`.
        strict: Raise :class:`SystemExit` (1) if any issues are found.
    """
    if not issues:
        logging.info("Cross-reference check: all OK")
        return

    by_code: dict[str, list[dict]] = {}
    for issue in issues:
        by_code.setdefault(issue["code"], []).append(issue)

    for code, items in sorted(by_code.items()):
        for item in items:
            ctx = f" (near: {item['context']})" if item.get("context") else ""
            logging.warning(
                "%s: %s — %s%s",
                code,
                item["href"],
                item["issue"],
                ctx,
            )

    counts = ", ".join(f"{code}: {len(v)}" for code, v in sorted(by_code.items()))
    logging.warning(f"Cross-reference check: {len(issues)} issue(s) [{counts}]")

    if strict:
        raise SystemExit(1)


def _resolve_lookup_maps(
    soup: BeautifulSoup, ctx: BuildContext | None
) -> tuple[dict[str, object], dict[str, list[object]]]:
    """Return ``(ids_by_id, links_by_href)`` from *ctx* or build them locally."""
    if ctx is not None and ctx.precomputed:
        ids_by_id = ctx.precomputed.get("ids_by_id")
        links_by_href = ctx.precomputed.get("links_by_href")
        if ids_by_id is not None and links_by_href is not None:
            return ids_by_id, links_by_href
    from specbuild.context import compute_lookup_maps

    maps = compute_lookup_maps(soup)
    return maps["ids_by_id"], maps["links_by_href"]


# ---------------------------------------------------------------------------
# XREF-1: unresolved internal anchor
# ---------------------------------------------------------------------------


def _check_xref1(
    soup: BeautifulSoup,
    all_ids: set[str],
    links_by_href: dict[str, list[object]] | None = None,
) -> list[dict]:
    """XREF-1 — fragment link targets a non-existent element ID."""
    issues: list[dict] = []
    # Iterate <a> elements in document order to keep output ordering stable
    # and identical to the original walk; the prebuilt ``all_ids`` set still
    # turns each lookup into O(1).  When a prebuilt ``links_by_href`` map is
    # provided we honour it (saves the find_all scan), otherwise fall back.
    if links_by_href is not None:
        link_pairs: list[tuple[str, object]] = [
            (href, link) for href, link_list in links_by_href.items() for link in link_list
        ]
    else:
        link_pairs = [(link["href"], link) for link in soup.find_all("a", href=True)]
    for href, link in link_pairs:
        if not href.startswith("#"):
            continue
        target = href[1:]
        if not target:
            continue
        # Skip bibliography/ref IDs — those are covered by XREF-3
        if target.startswith(("biblio-", "ref-")):
            continue
        if target not in all_ids:
            issues.append(
                {
                    "code": "XREF-1",
                    "href": href,
                    "text": link.get_text(strip=True)[:80],
                    "issue": f"anchor #{target!r} not found in document",
                    "context": find_nearest_heading(link),
                }
            )
    return issues


# ---------------------------------------------------------------------------
# XREF-2: broken cross-part reference
# ---------------------------------------------------------------------------


def _check_xref2(soup: BeautifulSoup, parts_dir: Path | None) -> list[dict]:
    """XREF-2 — cross-part ``<a class='cross-part-ref'>`` not resolvable."""
    from specbuild.checks.xpartcheck import check_cross_part_refs_soup

    raw = check_cross_part_refs_soup(soup, parts_dir)
    return [
        {
            "code": "XREF-2",
            "href": item["href"],
            "text": item.get("text", ""),
            "issue": item["issue"],
            "context": "",
        }
        for item in raw
    ]


# ---------------------------------------------------------------------------
# XREF-3: unresolved bibliography eref
# ---------------------------------------------------------------------------


def _check_xref3(
    soup: BeautifulSoup,
    all_ids: set[str],
    links_by_href: dict[str, list[object]] | None = None,
) -> list[dict]:
    """XREF-3 — link to ``#biblio-*`` or ``#ref-*`` with no matching entry.

    Bikeshed/specbuild renders bibliography citation links as
    ``<a href="#biblio-key">`` or ``<a href="#ref-key">``.  This check
    verifies that every such href has a corresponding element with the
    matching ``id`` attribute.
    """
    bib_ids = {eid for eid in all_ids if eid.startswith(("biblio-", "ref-"))}

    issues: list[dict] = []
    seen_broken: set[str] = set()

    if links_by_href is not None:
        link_pairs: list[tuple[str, object]] = [
            (href, link) for href, link_list in links_by_href.items() for link in link_list
        ]
    else:
        link_pairs = [(link["href"], link) for link in soup.find_all("a", href=True)]

    for href, link in link_pairs:
        if not href.startswith("#"):
            continue
        target = href[1:]
        if not target.startswith(("biblio-", "ref-")):
            continue
        if target in bib_ids:
            continue
        if target in seen_broken:
            continue
        seen_broken.add(target)
        issues.append(
            {
                "code": "XREF-3",
                "href": href,
                "text": link.get_text(strip=True)[:80],
                "issue": f"bibliography entry #{target!r} not defined",
                "context": find_nearest_heading(link),
            }
        )

    return issues

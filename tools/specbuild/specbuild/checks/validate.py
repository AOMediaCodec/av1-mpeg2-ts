"""Cross-reference validation for compiled HTML specifications."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def validate_cross_references(html_path: Path) -> list[dict]:
    """Check that all internal ``#anchor`` links resolve to existing IDs.

    File-based wrapper around :func:`validate_cross_references_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        A list of dicts describing broken references, each with keys
        ``href``, ``text``, and ``context`` (nearest heading).
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping cross-reference validation")
        return []

    logging.info(f"Validating cross-references in {html_path.name}")
    soup = read_html(html_path)
    return validate_cross_references_soup(soup)


def validate_cross_references_soup(soup: object, ctx: BuildContext | None = None) -> list[dict]:
    """Check cross-references on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``ids_by_id`` / ``links_by_href`` maps in ``ctx.precomputed``.

    Returns:
        A list of dicts describing broken references.
    """
    ids_by_id, links_by_href = resolve_lookup_maps(soup, ctx)

    # Detect duplicate IDs by walking once via the soup directly (the
    # precomputed map keeps only the first occurrence per id, so we still
    # need a second pass when ctx is None — keep the local walk here so
    # behavior is unchanged whether ctx is used or not).
    all_ids: set[str] = set(ids_by_id.keys())
    id_counts: dict[str, int] = {}
    for elem in soup.find_all(id=True):
        eid = elem["id"]
        id_counts[eid] = id_counts.get(eid, 0) + 1

    max_dup_display = 20  # cap on duplicate IDs shown in log output
    duplicates = {eid: count for eid, count in id_counts.items() if count > 1}
    if duplicates:
        logging.warning(f"Found {len(duplicates)} duplicate IDs:")
        for eid, count in sorted(duplicates.items())[:max_dup_display]:
            logging.warning(f"  #{eid} appears {count} times")

    # Find all internal links and check targets via the prebuilt map.
    broken: list[dict] = []
    checked = 0

    max_text_len = 80  # truncation limit for link text in reports
    for href, link_list in links_by_href.items():
        # Only check internal fragment links
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if not target_id:
            continue

        for link in link_list:
            checked += 1

            if target_id not in all_ids:
                # Find nearest heading for context
                context = _find_nearest_heading(link)
                broken.append(
                    {
                        "href": href,
                        "text": link.get_text(strip=True)[:max_text_len],
                        "context": context,
                    }
                )

    logging.info(f"Checked {checked} internal links against {len(all_ids)} IDs")
    return broken


def _find_nearest_heading(element: object) -> str:
    """Walk up the DOM to find the nearest heading for context.

    Args:
        element: A BeautifulSoup Tag whose ancestor headings are searched.

    Returns:
        Truncated text of the nearest heading, or ``"(unknown section)"``.
    """
    _HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")
    max_heading_len = 60  # truncation limit for heading text in context
    for parent in element.parents:
        if parent is None:
            break
        # Check previous siblings for headings
        for sibling in parent.previous_siblings:
            if hasattr(sibling, "name") and sibling.name in _HEADING_TAGS:
                return sibling.get_text(strip=True)[:max_heading_len]
        # Check if parent itself is under a heading
        if hasattr(parent, "name") and parent.name in ("section", "div"):
            heading = parent.find(list(_HEADING_TAGS))
            if heading:
                return heading.get_text(strip=True)[:max_heading_len]
    return "(unknown section)"


def report_broken_refs(broken: list[dict], html_path: Path, *, strict: bool = False) -> None:
    """Log broken cross-references.

    Args:
        broken: List of broken reference dicts from :func:`validate_cross_references`.
        html_path: Path shown in log messages.
        strict: If True, exit with error code when broken refs are found.
    """
    if not broken:
        logging.info("All cross-references are valid")
        return

    logging.warning(f"Found {len(broken)} broken cross-reference(s) in {html_path.name}:")
    for ref in broken:
        logging.warning(f'  {ref["href"]} (text: "{ref["text"]}") near: {ref["context"]}')

    if strict:
        raise SystemExit(1)

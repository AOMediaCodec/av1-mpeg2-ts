"""Orphan reference detector: find uncited bibliography entries and missing cited refs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def detect_orphan_references(html_path: Path) -> dict:
    """Detect uncited bibliography entries and missing cited references.

    File-based wrapper around :func:`detect_orphan_references_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Dict with keys:
        - ``uncited``: list of bibliography entry IDs never referenced
        - ``missing``: list of citation hrefs with no matching bibliography entry
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping orphan reference detection")
        return {"uncited": [], "missing": []}

    logging.info(f"Detecting orphan references in {html_path.name}")
    soup = read_html(html_path)
    return detect_orphan_references_soup(soup)


def detect_orphan_references_soup(soup: object, ctx: BuildContext | None = None) -> dict:
    """Detect orphan references on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx:  Optional :class:`BuildContext` carrying prebuilt
              ``ids_by_id``/``links_by_href`` lookup maps for O(1) reuse.
              When ``None`` the maps are walked locally.

    Returns:
        Dict with ``uncited`` and ``missing`` lists.
    """

    ids_by_id, links_by_href = resolve_lookup_maps(soup, ctx)

    # Collect bibliography entry IDs
    # Bikeshed bibliography entries typically have IDs like "biblio-rfc2119"
    biblio_ids = {
        eid
        for eid, elem in ids_by_id.items()
        if eid.startswith("biblio-") and getattr(elem, "name", None) == "dt"
    }

    # Collect all citation links in the document body
    # Bikeshed citations look like <a href="#biblio-rfc2119">[RFC2119]</a>
    cited_ids: set[str] = set()
    for href in links_by_href:
        if href.startswith("#biblio-"):
            cited_ids.add(href[1:])

    # Find uncited: in bibliography but never linked to
    uncited = sorted(biblio_ids - cited_ids)

    # Find missing: linked to but not in bibliography
    missing = sorted(cited_ids - biblio_ids)

    if uncited:
        logging.info(f"Found {len(uncited)} uncited bibliography entries")
    if missing:
        logging.warning(f"Found {len(missing)} citations to missing bibliography entries")
    if not uncited and not missing:
        logging.info("All bibliography references are properly cited")

    return {"uncited": uncited, "missing": missing}


def report_orphan_references(result: dict, *, strict: bool = False) -> None:
    """Log orphan reference findings.

    Args:
        result: Dict from :func:`detect_orphan_references`.
        strict: If True, exit with error when missing citations are found.
    """
    uncited = result.get("uncited", [])
    missing = result.get("missing", [])

    if not uncited and not missing:
        logging.info("Reference check passed: no orphan references found")
        return

    if uncited:
        logging.info(f"Uncited bibliography entries ({len(uncited)}):")
        for ref_id in uncited:
            # Strip "biblio-" prefix for display
            display = ref_id.replace("biblio-", "", 1).upper()
            logging.info(f"  [{display}] is defined but never cited")

    if missing:
        logging.warning(f"Missing bibliography entries ({len(missing)}):")
        for ref_id in missing:
            display = ref_id.replace("biblio-", "", 1).upper()
            logging.warning(f"  [{display}] is cited but has no bibliography entry")

    if strict and missing:
        raise SystemExit(1)

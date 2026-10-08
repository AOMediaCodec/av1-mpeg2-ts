"""Term/definition consistency checker: verify ``<dfn>`` usage throughout the spec.

Checks that:
- Every defined term (``<dfn>``) is referenced at least once
- Terms used in normative text have matching definitions
- No duplicate definitions exist for the same term
- Definition terms match their reference text consistently

Complements the :mod:`orphanrefs` module (bibliography) and the
:mod:`terminology` module (synonym detection).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import find_nearest_heading, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def check_dfn_consistency(html_path: Path) -> dict:
    """File-based wrapper around :func:`check_dfn_consistency_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Dict with ``unreferenced``, ``undefined``, ``duplicates`` lists.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping dfn consistency check")
        return {"unreferenced": [], "undefined": [], "duplicates": []}

    logging.info(f"Checking definition consistency in {html_path.name}")
    soup = read_html(html_path)
    return check_dfn_consistency_soup(soup)


def check_dfn_consistency_soup(soup: object, ctx: BuildContext | None = None) -> dict:
    """Check definition/reference consistency on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        ctx:  Optional :class:`BuildContext` carrying prebuilt
              ``ids_by_id``/``links_by_href`` lookup maps in
              ``ctx.precomputed``.  When absent (e.g. direct test calls),
              the maps are built locally so the result is identical.

    Returns:
        Dict with keys:

        - ``unreferenced``: list of dicts for defined terms never referenced
          (keys: ``term``, ``id``, ``context``)
        - ``undefined``: list of dicts for referenced terms with no definition
          (keys: ``term``, ``href``, ``context``)
        - ``duplicates``: list of dicts for terms defined more than once
          (keys: ``term``, ``count``, ``ids``)
        - ``used_before_defined``: list of dicts for terms referenced before
          their definition appears in document order
          (keys: ``term``, ``href``, ``ref_context``, ``dfn_context``)
    """
    ids_by_id, links_by_href = resolve_lookup_maps(soup, ctx)

    # Assign a document-order index to every element that has an id.
    # find_all(id=True) visits only the subset with ids — much faster than
    # find_all(True) which walks every element in the document.
    order: dict[str, int] = {}
    for idx, el in enumerate(soup.find_all(id=True)):
        order[el["id"]] = idx

    # --- Collect all definitions ---
    definitions: dict[str, list[str]] = {}  # normalized_term -> [id1, id2, ...]
    dfn_ids: set[str] = set()

    for dfn in soup.find_all("dfn"):
        dfn_id = dfn.get("id", "")
        term = dfn.get_text(strip=True).lower()
        if not term:
            continue
        if not dfn_id:
            continue
        dfn_ids.add(dfn_id)
        definitions.setdefault(term, []).append(dfn_id)

    # --- Collect all references to definitions ---
    # Bikeshed links to definitions via href="#dfn-term-name" or similar.
    # Walk <a> elements in document order so ``referenced_terms`` (and
    # therefore ``undefined``/``used_before_defined``) match the original
    # ordering exactly.  The prebuilt ``links_by_href`` map is reused below
    # for O(1) "first link with href" lookups.
    referenced_ids: set[str] = set()
    referenced_terms: list[dict] = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        referenced_ids.add(target_id)
        text = link.get_text(strip=True).lower()
        if text:
            referenced_terms.append(
                {
                    "term": text,
                    "href": href,
                    "target_id": target_id,
                }
            )

    # --- Find unreferenced definitions ---
    unreferenced = []
    for term, ids in definitions.items():
        for dfn_id in ids:
            if dfn_id and dfn_id not in referenced_ids:
                unreferenced.append(
                    {
                        "term": term,
                        "id": dfn_id,
                        "context": _find_dfn_context(soup, dfn_id, ids_by_id),
                    }
                )

    # --- Find duplicate definitions ---
    duplicates = []
    for term, ids in definitions.items():
        if len(ids) > 1:
            duplicates.append(
                {
                    "term": term,
                    "count": len(ids),
                    "ids": ids,
                }
            )

    # --- Find undefined references ---
    # Look for links that target dfn-* IDs but have no matching definition
    undefined = []
    seen_undefined: set[str] = set()
    for ref in referenced_terms:
        target = ref["target_id"]
        if target.startswith("dfn-") and target not in dfn_ids:
            if target not in seen_undefined:
                seen_undefined.add(target)
                undefined.append(
                    {
                        "term": ref["term"],
                        "href": ref["href"],
                        "context": _find_link_context(soup, ref["href"], links_by_href),
                    }
                )

    # --- Find used-before-defined ---
    # For each link to a dfn-* target, check whether the reference appears
    # in document order before the definition element.
    used_before_defined = []
    seen_ubd: set[str] = set()
    for ref in referenced_terms:
        target = ref["target_id"]
        if not target.startswith("dfn-") or target not in dfn_ids:
            continue
        # Find the document-order index of the referencing <a> element
        # (first occurrence with this href, matching the original semantics).
        candidates = links_by_href.get(ref["href"]) or []
        link_el = candidates[0] if candidates else None
        if link_el is None:
            continue
        # Walk up to get the nearest id-bearing ancestor to establish position
        link_pos = None
        for ancestor in [link_el, *link_el.parents]:
            anc_id = getattr(ancestor, "get", lambda _: None)("id")
            if anc_id and anc_id in order:
                link_pos = order[anc_id]
                break
        if link_pos is None:
            continue
        dfn_pos = order.get(target)
        if dfn_pos is None:
            continue
        if link_pos < dfn_pos and target not in seen_ubd:
            seen_ubd.add(target)
            used_before_defined.append(
                {
                    "term": ref["term"],
                    "href": ref["href"],
                    "ref_context": _find_link_context(soup, ref["href"], links_by_href),
                    "dfn_context": _find_dfn_context(soup, target, ids_by_id),
                }
            )

    _log_results(unreferenced, undefined, duplicates, used_before_defined)

    return {
        "unreferenced": unreferenced,
        "undefined": undefined,
        "duplicates": duplicates,
        "used_before_defined": used_before_defined,
    }


def report_dfn_consistency(result: dict, *, strict: bool = False) -> None:
    """Log definition consistency findings.

    Args:
        result: Dict from :func:`check_dfn_consistency`.
        strict: If True, exit with error on undefined references.
    """
    unreferenced = result.get("unreferenced", [])
    undefined = result.get("undefined", [])
    duplicates = result.get("duplicates", [])
    used_before_defined = result.get("used_before_defined", [])

    if not unreferenced and not undefined and not duplicates and not used_before_defined:
        logging.info("Definition consistency check passed")
        return

    if unreferenced:
        logging.info(f"Unreferenced definitions ({len(unreferenced)}):")
        for item in unreferenced[:20]:
            logging.info(f"  <dfn> '{item['term']}' (#{item['id']}) near: {item['context']}")

    if duplicates:
        logging.warning(f"Duplicate definitions ({len(duplicates)}):")
        for item in duplicates:
            logging.warning(
                f"  '{item['term']}' defined {item['count']} times "
                f"(IDs: {', '.join(item['ids'][:5])})"
            )

    if undefined:
        logging.warning(f"Undefined term references ({len(undefined)}):")
        for item in undefined:
            logging.warning(f"  '{item['term']}' -> {item['href']} near: {item['context']}")

    if used_before_defined:
        logging.warning(f"Terms used before definition ({len(used_before_defined)}):")
        for item in used_before_defined:
            logging.warning(
                f"  '{item['term']}' referenced near '{item['ref_context']}' "
                f"but defined near '{item['dfn_context']}'"
            )

    if strict and (undefined or used_before_defined):
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_dfn_context(soup: object, dfn_id: str, ids_by_id: dict[str, object] | None = None) -> str:
    """Find the section context for a definition by its ID."""
    elem = ids_by_id.get(dfn_id) if ids_by_id is not None else soup.find(id=dfn_id)
    if elem is None:
        return "(unknown)"
    return find_nearest_heading(elem)


def _find_link_context(
    soup: object, href: str, links_by_href: dict[str, list[object]] | None = None
) -> str:
    """Find the section context for the first link with this href."""
    if links_by_href is not None:
        candidates = links_by_href.get(href) or []
        link = candidates[0] if candidates else None
    else:
        link = soup.find("a", href=href)
    if link is None:
        return "(unknown)"
    return find_nearest_heading(link)


def _log_results(
    unreferenced: list, undefined: list, duplicates: list, used_before_defined: list
) -> None:
    """Log a summary of findings."""
    total = len(unreferenced) + len(undefined) + len(duplicates) + len(used_before_defined)
    if total == 0:
        logging.info("Definition consistency check passed: all terms are defined and referenced")
        return

    parts = []
    if unreferenced:
        parts.append(f"{len(unreferenced)} unreferenced")
    if undefined:
        parts.append(f"{len(undefined)} undefined")
    if duplicates:
        parts.append(f"{len(duplicates)} duplicate(s)")
    if used_before_defined:
        parts.append(f"{len(used_before_defined)} used-before-defined")
    logging.info(f"Definition consistency: {', '.join(parts)}")

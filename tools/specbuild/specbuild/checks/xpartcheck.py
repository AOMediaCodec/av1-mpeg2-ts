"""Cross-part reference validation for multi-part standards.

Checks that ``<a class="cross-part-ref">`` links injected by
:mod:`specbuild.multipart` resolve to valid anchors in their target parts.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


def check_cross_part_refs_soup(
    soup: BeautifulSoup,
    parts_dir: Path | None = None,
) -> list[dict]:
    """Check that cross-part references resolve to valid anchors.

    Scans all ``<a class="cross-part-ref">`` elements in *soup*.  For each
    link that contains a fragment identifier (``#anchor``):

    - If *parts_dir* is given, attempts to locate the target HTML file and
      verifies that the referenced anchor ID exists inside it.
    - If *parts_dir* is ``None``, only syntactic checks are performed (href
      must be non-empty).

    Args:
        soup: Parsed BeautifulSoup document to inspect.
        parts_dir: Optional base directory for resolving ``../part-N/index.html``
            relative paths.  When provided, the check verifies anchor existence.

    Returns:
        List of issue dicts, each containing:

        - ``href`` — the raw href attribute value
        - ``text`` — visible link text
        - ``issue`` — human-readable description of the problem
    """
    issues: list[dict] = []

    for a_tag in soup.find_all("a", class_="cross-part-ref"):
        href = a_tag.get("href", "").strip()
        text = a_tag.get_text(strip=True)

        if not href:
            issues.append({"href": href, "text": text, "issue": "empty href"})
            continue

        # Split href into file path and optional anchor
        if "#" in href:
            file_part, anchor = href.split("#", 1)
        else:
            file_part = href
            anchor = ""

        if parts_dir is None:
            # Syntactic-only check: href must look plausible
            if not file_part:
                issues.append(
                    {
                        "href": href,
                        "text": text,
                        "issue": "href has no file component",
                    }
                )
            continue

        # Resolve target HTML path relative to parts_dir
        # hrefs are typically "../part-N/index.html" or similar
        target_html = (parts_dir / file_part).resolve()
        if not target_html.exists():
            issues.append(
                {
                    "href": href,
                    "text": text,
                    "issue": f"target HTML not found: {target_html}",
                }
            )
            continue

        # If there's an anchor, verify it exists in the target document
        if anchor:
            try:
                from bs4 import BeautifulSoup as BS

                content = target_html.read_text(encoding="utf-8", errors="replace")
                target_soup = BS(content, "html.parser")
            except OSError as exc:
                issues.append(
                    {
                        "href": href,
                        "text": text,
                        "issue": f"could not read target HTML: {exc}",
                    }
                )
                continue

            if not target_soup.find(id=anchor):
                issues.append(
                    {
                        "href": href,
                        "text": text,
                        "issue": f"anchor #{anchor!r} not found in {target_html.name}",
                    }
                )

    return issues


def report_cross_part_ref_issues(
    issues: list[dict],
    strict: bool = False,
) -> None:
    """Log cross-part reference issues and optionally raise on errors.

    Args:
        issues: List of issue dicts as returned by :func:`check_cross_part_refs_soup`.
        strict: If ``True``, raise :class:`SystemExit` (code 1) when any
            issues are found.
    """
    if not issues:
        logging.info("Cross-part references: all OK")
        return

    for item in issues:
        logging.warning(
            "cross-part-ref issue: %s — %s (%s)",
            item.get("href", ""),
            item.get("issue", ""),
            item.get("text", ""),
        )

    logging.warning(f"Cross-part references: {len(issues)} issue(s) found")

    if strict:
        raise SystemExit(1)

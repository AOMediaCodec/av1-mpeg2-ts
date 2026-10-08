"""Accessibility audit: scan compiled HTML for WCAG compliance issues.

Checks for common accessibility problems in specification documents:
- Missing ``alt`` text on images
- Empty or missing table headers
- Missing ``<caption>`` elements on data tables
- Heading level skips (e.g. h2 -> h4)
- Empty links and buttons
- Missing language attribute on ``<html>``

Results are returned as structured data for build reports and logging.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import HEADING_TAGS, find_nearest_heading, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext

_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}

_HEADING_TAGS_ALL = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})

# ---------------------------------------------------------------------------
# ARIA role injection
# ---------------------------------------------------------------------------


def inject_aria_roles(soup: object) -> int:
    """Add WCAG 2.1-compliant ARIA landmark roles and semantic attributes.

    Modifies the soup in-place. Does not overwrite existing ``role`` attributes.

    Returns:
        Number of elements modified.
    """
    modified = 0
    _id_counters: dict[str, int] = {}

    def _ensure_id(element, prefix: str) -> str:
        """Assign an id to *element* if it lacks one, then return the id."""
        existing = element.get("id")
        if existing:
            return existing
        _id_counters[prefix] = _id_counters.get(prefix, 0) + 1
        new_id = f"{prefix}-{_id_counters[prefix]}"
        element["id"] = new_id
        return new_id

    def _set_role(element, role: str) -> bool:
        if element.get("role"):
            return False
        element["role"] = role
        return True

    # body → role="document"
    body = soup.find("body")
    if body and _set_role(body, "document"):
        modified += 1

    # <nav> → role="navigation"
    for el in soup.find_all("nav"):
        if _set_role(el, "navigation"):
            modified += 1

    # <header> → role="banner"
    for el in soup.find_all("header"):
        if _set_role(el, "banner"):
            modified += 1

    # <footer> → role="contentinfo"
    for el in soup.find_all("footer"):
        if _set_role(el, "contentinfo"):
            modified += 1

    # <main> → role="main"
    for el in soup.find_all("main"):
        if _set_role(el, "main"):
            modified += 1

    # <div id="main-content"> → role="main"
    for el in soup.find_all("div", id="main-content"):
        if _set_role(el, "main"):
            modified += 1

    # <section> → aria-labelledby pointing to first heading child
    for section in soup.find_all("section"):
        heading = section.find(_HEADING_TAGS_ALL)
        if heading:
            hid = _ensure_id(heading, "heading")
            if not section.get("aria-labelledby"):
                section["aria-labelledby"] = hid
                modified += 1

    # <figure> → aria-labelledby pointing to <figcaption>
    for figure in soup.find_all("figure"):
        figcaption = figure.find("figcaption")
        if figcaption and not figure.get("aria-labelledby"):
            fcid = _ensure_id(figcaption, "figcaption")
            figure["aria-labelledby"] = fcid
            modified += 1

    # <table> → aria-describedby pointing to <caption>
    for table in soup.find_all("table"):
        caption = table.find("caption")
        if caption and not table.get("aria-describedby"):
            capid = _ensure_id(caption, "caption")
            table["aria-describedby"] = capid
            modified += 1

    # <img> without alt → alt="" role="presentation"
    for img in soup.find_all("img"):
        if img.get("alt") is None:
            img["alt"] = ""
            img["role"] = "presentation"
            modified += 1

    return modified


def audit_accessibility(html_path: Path) -> list[dict]:
    """File-based wrapper around :func:`audit_accessibility_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        List of issue dicts with keys: ``rule``, ``severity``, ``message``,
        ``context``, ``element``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping accessibility audit")
        return []

    logging.info(f"Running accessibility audit on {html_path.name}")
    soup = read_html(html_path)
    return audit_accessibility_soup(soup)


def audit_accessibility_soup(
    soup: object, *, inject: bool = False, ctx: BuildContext | None = None
) -> list[dict]:
    """Run accessibility checks on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only unless inject=True).
        inject: If True, call :func:`inject_aria_roles` before running checks.
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``links_by_href`` map in ``ctx.precomputed``.

    Returns:
        List of issue dicts.
    """
    if inject:
        inject_aria_roles(soup)
    issues: list[dict] = []

    # --- Check 1: Missing alt text on images ---
    for img in soup.find_all("img"):
        alt = img.get("alt")
        src = img.get("src", "(no src)")
        if alt is None:
            issues.append(
                {
                    "rule": "img-alt-missing",
                    "severity": "error",
                    "message": f"Image missing alt attribute: {src[:80]}",
                    "context": find_nearest_heading(img),
                    "element": "img",
                }
            )
        elif alt.strip() == "" and not _is_decorative(img):
            issues.append(
                {
                    "rule": "img-alt-empty",
                    "severity": "warning",
                    "message": f"Image has empty alt text: {src[:80]}",
                    "context": find_nearest_heading(img),
                    "element": "img",
                }
            )

    # --- Check 2: Table accessibility ---
    for table in soup.find_all("table"):
        # Skip layout tables (role="presentation" or role="none")
        role = table.get("role", "")
        if role in ("presentation", "none"):
            continue

        # Check for caption
        caption = table.find("caption")
        if not caption:
            issues.append(
                {
                    "rule": "table-caption-missing",
                    "severity": "warning",
                    "message": "Data table missing <caption> element",
                    "context": find_nearest_heading(table),
                    "element": "table",
                }
            )

        # Check for empty th elements and whether any th exists
        has_th = False
        for th in table.find_all("th"):
            has_th = True
            text = th.get_text(strip=True)
            if not text:
                issues.append(
                    {
                        "rule": "table-th-empty",
                        "severity": "warning",
                        "message": "Table header cell is empty",
                        "context": find_nearest_heading(table),
                        "element": "th",
                    }
                )
                break  # One per table is sufficient

        # Check if table has any th at all
        if not has_th:
            issues.append(
                {
                    "rule": "table-th-missing",
                    "severity": "warning",
                    "message": "Data table has no header cells (<th>)",
                    "context": find_nearest_heading(table),
                    "element": "table",
                }
            )

    # --- Check 3: Heading level skips ---
    headings = soup.find_all(list(HEADING_TAGS))
    prev_level = 0
    for heading in headings:
        level = _HEADING_LEVELS[heading.name]
        if prev_level > 0 and level > prev_level + 1:
            issues.append(
                {
                    "rule": "heading-skip",
                    "severity": "warning",
                    "message": (
                        f"Heading level skips from h{prev_level} to "
                        f'h{level}: "{heading.get_text(strip=True)[:60]}"'
                    ),
                    "context": heading.get_text(strip=True)[:60],
                    "element": heading.name,
                }
            )
        prev_level = level

    # --- Check 4: Empty links ---
    _, links_by_href = resolve_lookup_maps(soup, ctx)
    for href, link_list in links_by_href.items():
        for link in link_list:
            # Skip self-link anchors (Bikeshed convention)
            if "self-link" in (link.get("class") or []):
                continue
            text = link.get_text(strip=True)
            has_img = link.find("img")
            aria_label = link.get("aria-label", "").strip()
            if not text and not has_img and not aria_label:
                issues.append(
                    {
                        "rule": "link-empty",
                        "severity": "warning",
                        "message": f'Empty link: href="{link["href"][:60]}"',
                        "context": find_nearest_heading(link),
                        "element": "a",
                    }
                )

    # --- Check 5: Missing lang attribute ---
    html_tag = soup.find("html")
    if html_tag and not html_tag.get("lang"):
        issues.append(
            {
                "rule": "html-lang-missing",
                "severity": "error",
                "message": "<html> element missing lang attribute",
                "context": "(document root)",
                "element": "html",
            }
        )

    _log_summary(issues)
    return issues


def report_accessibility(issues: list[dict], *, strict: bool = False) -> None:
    """Log accessibility audit findings.

    Args:
        issues: List from :func:`audit_accessibility`.
        strict: If True, exit with error when any errors are found.
    """
    if not issues:
        logging.info("Accessibility audit passed: no issues found")
        return

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    logging.warning(f"Accessibility audit: {len(errors)} error(s), {len(warnings)} warning(s)")
    for issue in issues:
        level = logging.ERROR if issue["severity"] == "error" else logging.WARNING
        logging.log(level, f"  [{issue['rule']}] {issue['message']} (near: {issue['context']})")

    if strict and errors:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_decorative(img) -> bool:
    """Heuristic: check if an image is likely decorative."""
    role = img.get("role", "")
    if role == "presentation" or role == "none":
        return True
    # Very small images are often spacers/decorative
    width = img.get("width", "")
    height = img.get("height", "")
    try:
        if width and height and int(width) <= 1 and int(height) <= 1:
            return True
    except (ValueError, TypeError):
        pass
    return False


def _log_summary(issues: list[dict]) -> None:
    """Log a summary of findings by rule."""
    if not issues:
        logging.info("Accessibility audit passed: no issues found")
        return

    by_rule: dict[str, int] = {}
    for issue in issues:
        by_rule[issue["rule"]] = by_rule.get(issue["rule"], 0) + 1

    logging.info(
        f"Accessibility audit found {len(issues)} issue(s): "
        + ", ".join(f"{rule}={count}" for rule, count in sorted(by_rule.items()))
    )

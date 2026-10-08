"""Check that tables and figures use the referenceable format.

A *referenceable* table has a ``<caption>`` child with an ``id`` attribute
so the build system can number it and cross-references can link to it.

A *referenceable* figure has an ``id`` attribute on the ``<figure>`` element
and a ``<figcaption>`` child.

Tables and figures that lack these attributes cannot be numbered, included
in the List of Tables / List of Figures, or cross-referenced.

SDL syntax tables (``class="sdl-syntax-table"``) and presentational tables
(``class="table-nohead"``) are excluded because they are intentionally
unnumbered.
"""

from __future__ import annotations

import logging
from pathlib import Path

from specbuild.utils import find_nearest_heading, get_bs4, read_html

# ---------------------------------------------------------------------------
# Soup-based checks (used by the plugin system)
# ---------------------------------------------------------------------------


def check_referenceable_soup(soup: object) -> list[dict]:
    """Find tables and figures that are not referenceable.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        List of issue dicts with ``rule``, ``element``, ``detail``,
        ``context``, and ``suggestion`` keys.
    """
    issues: list[dict] = []

    # --- Tables ---
    for table in soup.find_all("table"):
        cls = table.get("class", [])
        # Skip auto-generated tables (SDL syntax, striped code blocks)
        # and presentational tables (e.g. operator definitions with no header)
        if "sdl-syntax-table" in cls or "code-table" in cls or "table-nohead" in cls:
            continue
        # Skip tables inside TOC, boilerplate, navigation, or header/footer
        if table.find_parent(["nav", "details", "header", "footer"]):
            continue

        table_id = table.get("id", "")
        context = find_nearest_heading(table)
        caption = table.find("caption")

        if not caption:
            issues.append(
                {
                    "rule": "table-not-referenceable",
                    "element": "table",
                    "detail": "Table has no <caption> — cannot be numbered or cross-referenced",
                    "context": context,
                    "table_id": table_id,
                    "suggestion": (
                        'Add <caption id="table-DESCRIPTION">Caption text</caption> '
                        "as the first child of the <table>."
                    ),
                }
            )
        elif not caption.get("id"):
            caption_text = caption.get_text(strip=True)[:50]
            issues.append(
                {
                    "rule": "table-caption-no-id",
                    "element": "table",
                    "detail": "Table caption has no id attribute — cannot be cross-referenced",
                    "context": context,
                    "table_id": table_id,
                    "caption_text": caption_text,
                    "suggestion": ('Add an id to the caption: <caption id="table-DESCRIPTION">...'),
                }
            )

    # --- Figures ---
    for figure in soup.find_all("figure"):
        fig_id = figure.get("id", "")
        context = find_nearest_heading(figure)
        figcaption = figure.find("figcaption")

        if not figcaption and not fig_id:
            issues.append(
                {
                    "rule": "figure-not-referenceable",
                    "element": "figure",
                    "detail": "Figure has no <figcaption> and no id — cannot be numbered or cross-referenced",
                    "context": context,
                    "fig_id": fig_id,
                    "suggestion": (
                        "Add id to the <figure> and a <figcaption>: "
                        '<figure id="fig-DESCRIPTION"> ... '
                        "<figcaption>Caption text</figcaption></figure>"
                    ),
                }
            )
        elif not figcaption:
            issues.append(
                {
                    "rule": "figure-no-figcaption",
                    "element": "figure",
                    "detail": "Figure has no <figcaption> — will not appear in List of Figures",
                    "context": context,
                    "fig_id": fig_id,
                    "suggestion": (
                        "Add <figcaption>Caption text</figcaption> inside the <figure>."
                    ),
                }
            )
        elif not fig_id:
            caption_text = figcaption.get_text(strip=True)[:50]
            issues.append(
                {
                    "rule": "figure-no-id",
                    "element": "figure",
                    "detail": "Figure has no id attribute — cannot be cross-referenced",
                    "context": context,
                    "fig_id": "",
                    "caption_text": caption_text,
                    "suggestion": ('Add an id to the <figure>: <figure id="fig-DESCRIPTION">'),
                }
            )

    return issues


# ---------------------------------------------------------------------------
# File-based wrapper
# ---------------------------------------------------------------------------


def check_referenceable(html_path: Path) -> list[dict]:
    """File-based wrapper around :func:`check_referenceable_soup`.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        List of issue dicts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping referenceable check")
        return []

    logging.info("Checking tables/figures for referenceable format in %s", html_path.name)
    soup = read_html(html_path)
    return check_referenceable_soup(soup)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_referenceable(
    issues: list[dict],
    *,
    strict: bool = False,
) -> None:
    """Log referenceable-format findings with suggestions.

    Args:
        issues: List from :func:`check_referenceable_soup`.
        strict: If True, exit with error when issues are found.
    """
    if not issues:
        logging.info(
            "Referenceable check passed: all tables/figures can be numbered and cross-referenced"
        )
        return

    tables = [i for i in issues if i["element"] == "table"]
    figures = [i for i in issues if i["element"] == "figure"]

    logging.warning(
        "Referenceable check: %d issue(s) (%d table(s), %d figure(s))",
        len(issues),
        len(tables),
        len(figures),
    )
    for issue in issues:
        logging.warning("  [%s] %s (near: %s)", issue["rule"], issue["detail"], issue["context"])
        logging.warning("    Fix: %s", issue["suggestion"])

    if strict:
        raise SystemExit(1)

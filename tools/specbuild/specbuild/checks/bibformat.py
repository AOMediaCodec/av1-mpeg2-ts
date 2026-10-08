"""ISO 690 bibliography format checking.

Validates that bibliography entries have the expected structure for the
active flavor's citation style.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec

_ISO690_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
_ISO690_BRACKET_REF = re.compile(r"^\[.+\]")


def check_bibliography_format_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
) -> list[dict[str, str]]:
    """Check bibliography entry formatting per the flavor's style.

    Currently supports ``iso690`` and ``ieee`` styles.

    Returns a list of issue dicts with keys ``level``, ``rule``, ``message``.
    """
    issues: list[dict[str, str]] = []
    style = flavor.bibliography.style

    bib_headings = _find_bibliography_sections(soup, flavor)
    for heading in bib_headings:
        section = heading.find_parent("section")
        if section is None:
            continue

        entries = _extract_entries(section)
        for i, entry_text in enumerate(entries, 1):
            entry_issues = _check_single_entry(entry_text, style, i)
            issues.extend(entry_issues)

    return issues


def _find_bibliography_sections(soup: BeautifulSoup, flavor: FlavorSpec) -> list:
    """Find heading elements for bibliography / references sections."""
    targets = [
        flavor.bibliography.normative_heading,
        flavor.bibliography.informative_heading,
    ]
    results = []
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        for target in targets:
            if re.match(re.escape(target), text, re.IGNORECASE):
                results.append(tag)
                break
    return results


def _extract_entries(section) -> list[str]:
    """Extract bibliography entries from a section (from <ol>, <ul>, <dl>, or <p>)."""
    entries = []

    for li in section.find_all("li"):
        text = li.get_text(strip=True)
        if text:
            entries.append(text)

    if entries:
        return entries

    for dt in section.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        text = ""
        if dd:
            text = f"{dt.get_text(strip=True)} {dd.get_text(strip=True)}"
        else:
            text = dt.get_text(strip=True)
        if text:
            entries.append(text)

    if entries:
        return entries

    for p in section.find_all("p"):
        text = p.get_text(strip=True)
        if _ISO690_BRACKET_REF.match(text):
            entries.append(text)

    return entries


def _check_single_entry(
    text: str,
    style: str,
    index: int,
) -> list[dict[str, str]]:
    """Check a single bibliography entry."""
    issues: list[dict[str, str]] = []

    if not _ISO690_YEAR_PATTERN.search(text):
        issues.append(
            {
                "level": "warning",
                "rule": "bib-missing-year",
                "message": f"Bibliography entry {index} may be missing a year.",
                "section": "Bibliography",
            }
        )

    if style in ("iso690", "ieee"):
        if len(text) < 20:
            issues.append(
                {
                    "level": "warning",
                    "rule": "bib-incomplete",
                    "message": (
                        f"Bibliography entry {index} appears incomplete (very short text)."
                    ),
                    "section": "Bibliography",
                }
            )

    return issues

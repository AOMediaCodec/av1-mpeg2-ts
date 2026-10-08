"""Standards structure validation checks.

Validates that a document conforms to the structural rules of the active
standards flavor — mandatory sections, section ordering, metadata
completeness, annex classification, and terms section structure.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.standards.flavors import FlavorSpec


def _heading_texts(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (heading_text, tag_name) pairs for all h1-h6 in document order."""
    results = []
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        if text:
            results.append((text, tag.name))
    return results


def validate_structure_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    headings: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Check that mandatory sections exist.

    Args:
        soup: Parsed HTML document.
        flavor: Active standards flavor.
        headings: Pre-extracted (text, tag_name) pairs from :func:`_heading_texts`.
            Pass this to avoid re-scanning the DOM when calling multiple
            validation functions on the same document.
    """
    issues: list[dict[str, str]] = []
    if headings is None:
        headings = _heading_texts(soup)
    heading_texts = [h[0] for h in headings]

    for rule in flavor.sections:
        if not rule.mandatory:
            continue
        if not rule.heading_pattern:
            continue
        pattern = re.compile(rule.heading_pattern)
        found = any(pattern.match(t) for t in heading_texts)
        if not found:
            issues.append(
                {
                    "level": "error",
                    "rule": "mandatory-section",
                    "message": f"Mandatory section '{rule.name}' is missing.",
                    "section": rule.name,
                }
            )
    return issues


def validate_section_order_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    headings: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Check that sections appear in the order prescribed by the flavor.

    Args:
        soup: Parsed HTML document.
        flavor: Active standards flavor.
        headings: Pre-extracted (text, tag_name) pairs from :func:`_heading_texts`.
    """
    issues: list[dict[str, str]] = []
    if headings is None:
        headings = _heading_texts(soup)
    heading_texts = [h[0] for h in headings]

    found_order: list[tuple[int, str]] = []
    for rule in sorted(flavor.sections, key=lambda s: s.order):
        if not rule.heading_pattern:
            continue
        pattern = re.compile(rule.heading_pattern)
        for idx, text in enumerate(heading_texts):
            if pattern.match(text):
                found_order.append((idx, rule.name))
                break

    for i in range(len(found_order) - 1):
        cur_idx, cur_name = found_order[i]
        nxt_idx, nxt_name = found_order[i + 1]
        if cur_idx > nxt_idx:
            issues.append(
                {
                    "level": "warning",
                    "rule": "section-order",
                    "message": (
                        f"Section '{cur_name}' appears after '{nxt_name}', "
                        f"but should come before it."
                    ),
                    "section": cur_name,
                }
            )
    return issues


def validate_metadata_completeness(
    metadata: dict[str, str],
    flavor: FlavorSpec,
) -> list[dict[str, str]]:
    """Check that all required metadata fields are present."""
    from specbuild.standards.metadata import validate_metadata

    return validate_metadata(metadata, flavor)


def validate_bibliography_format_soup(
    soup: BeautifulSoup,
    flavor: FlavorSpec,
    headings: list[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Check bibliography entries conform to the flavor's citation style.

    Args:
        soup: Parsed HTML document.
        flavor: Active standards flavor.
        headings: Pre-extracted (text, tag_name) pairs from :func:`_heading_texts`.
    """
    issues: list[dict[str, str]] = []

    if not flavor.bibliography.require_classification:
        return issues

    norm_heading = flavor.bibliography.normative_heading
    info_heading = flavor.bibliography.informative_heading

    if headings is None:
        headings = _heading_texts(soup)
    heading_texts = [h[0] for h in headings]

    norm_re = re.compile(re.escape(norm_heading), re.IGNORECASE)
    info_re = re.compile(re.escape(info_heading), re.IGNORECASE)
    has_normative = any(norm_re.match(t) for t in heading_texts)
    has_informative = any(info_re.match(t) for t in heading_texts)

    refs_sections = soup.find_all("section")
    has_any_refs = False
    for sec in refs_sections:
        if sec.find("dl") or sec.find("ol"):
            heading = sec.find(HEADING_RE)
            if heading:
                text = heading.get_text(strip=True).lower()
                if "reference" in text or "bibliography" in text:
                    has_any_refs = True
                    break

    if has_any_refs and not has_normative and not has_informative:
        issues.append(
            {
                "level": "warning",
                "rule": "bibliography-classification",
                "message": (
                    f"Bibliography sections should be classified as "
                    f"'{norm_heading}' (normative) or '{info_heading}' (informative)."
                ),
                "section": "Bibliography",
            }
        )

    return issues


def validate_annex_classification_soup(
    soup: BeautifulSoup,
) -> list[dict[str, str]]:
    """Check that annexes are classified as normative or informative."""
    issues: list[dict[str, str]] = []
    annex_pattern = re.compile(r"(?i)^annex\s+[A-Z]")

    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        if annex_pattern.match(text):
            lower = text.lower()
            if "(normative)" not in lower and "(informative)" not in lower:
                issues.append(
                    {
                        "level": "warning",
                        "rule": "annex-classification",
                        "message": (
                            f"Annex heading '{text}' should include "
                            f"'(normative)' or '(informative)'."
                        ),
                        "section": text,
                    }
                )
    return issues


def validate_terms_section_soup(
    soup: BeautifulSoup,
) -> list[dict[str, str]]:
    """Check Terms and definitions section structure."""
    issues: list[dict[str, str]] = []
    terms_pattern = re.compile(r"(?i)^(?:\d+(?:\.\d+)*\s+)?terms\s+(and|,)\s+definitions$")

    terms_heading = None
    for tag in soup.find_all(HEADING_RE):
        text = tag.get_text(strip=True)
        if terms_pattern.match(text):
            terms_heading = tag
            break

    if terms_heading is None:
        return issues

    section = terms_heading.find_parent("section")
    if section is None:
        return issues

    dl = section.find("dl")
    sub_headings = section.find_all(re.compile(r"^h[3-6]$"))

    if not dl and not sub_headings:
        issues.append(
            {
                "level": "warning",
                "rule": "terms-structure",
                "message": (
                    "Terms and definitions section has no definition list (<dl>) "
                    "or sub-headings for individual terms."
                ),
                "section": "Terms and definitions",
            }
        )

    return issues


def validate_normative_refs_cited_soup(
    soup: BeautifulSoup,
) -> list[dict[str, str]]:
    """Check that every normative reference is cited at least once in the body.

    Looks for a "Normative references" section, extracts reference identifiers
    (e.g. ``[AVC]``, ``[RFC2119]``) from list items, then verifies each
    identifier appears in the document body text.
    """
    issues: list[dict[str, str]] = []
    norm_pattern = re.compile(r"(?i)normative\s+references?")

    # Find the normative references section
    norm_section = None
    for tag in soup.find_all(HEADING_RE):
        if norm_pattern.search(tag.get_text(strip=True)):
            norm_section = tag.find_parent("section")
            break

    if norm_section is None:
        return issues

    # Extract reference IDs: prefer bracketed text [ID], fallback to element id
    # stripped of any "ref-" prefix
    ref_ids: list[str] = []
    bracket_re = re.compile(r"^\s*\[([^\]]+)\]")
    for li in norm_section.find_all("li"):
        text = li.get_text(strip=True)
        m = bracket_re.match(text)
        if m:
            ref_ids.append(m.group(1))
        else:
            li_id = li.get("id", "")
            if li_id:
                # Strip common "ref-" prefix convention
                ref_ids.append(li_id.removeprefix("ref-"))

    if not ref_ids:
        return issues

    # Collect body text excluding the normative references section itself
    body = soup.find("body") or soup
    # Get full body text minus the normative-references section.  norm_section is
    # often nested inside <main> or another wrapper, so iterating direct children
    # of <body> and comparing identity wouldn't catch it.  Subtract the section
    # text from the full body text instead.
    norm_text = norm_section.get_text(" ")
    body_text = body.get_text(" ").replace(norm_text, "", 1)

    for ref_id in ref_ids:
        # Compile once per ref_id; match both [ID] and bare ID
        escaped = re.escape(ref_id)
        cited = bool(re.search(rf"\[{escaped}\]", body_text)) or bool(
            re.search(rf"\b{escaped}\b", body_text)
        )
        if not cited:
            issues.append(
                {
                    "level": "warning",
                    "rule": "normative-ref-uncited",
                    "message": f"Normative reference '{ref_id}' is not cited in the document body.",
                    "section": "Normative references",
                }
            )

    return issues


def report_standards_validation(
    issues: list[dict[str, str]],
    *,
    strict: bool = False,
) -> None:
    """Log validation issues; exit if strict and errors found."""
    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    for issue in warnings:
        logging.warning(f"[{issue['rule']}] {issue['message']}")

    for issue in errors:
        logging.error(f"[{issue['rule']}] {issue['message']}")

    if issues:
        logging.info(f"Standards validation: {len(errors)} error(s), {len(warnings)} warning(s)")

    if strict and errors:
        import sys

        logging.error("Standards validation failed (--standards-strict)")
        sys.exit(1)

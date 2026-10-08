"""Bibliography reference validation against a known standards database.

Validates that bibliography entries in compiled HTML cite standards that
exist, are current, and follow the expected citation format.  This fills
a Metanorma feature gap by catching outdated or withdrawn references at
build time without requiring external API access.

Usage::

    from specbuild.checks.refvalidate import validate_references_soup

    issues = validate_references_soup(soup)
    report_reference_validation(issues)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.utils import HEADING_RE, get_bs4, read_html

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag

    from specbuild.standards.flavors import FlavorSpec

# ---------------------------------------------------------------------------
# Public file-based entry point
# ---------------------------------------------------------------------------


def validate_references(html_path: Path, *, flavor: object | None = None) -> list[dict]:
    """Validate bibliography references in a compiled HTML specification.

    File-based wrapper around :func:`validate_references_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        flavor: Optional standards flavor for format checking.

    Returns:
        List of issue dicts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping reference validation")
        return []

    logging.info(f"Validating bibliography references in {html_path.name}")
    soup = read_html(html_path)
    return validate_references_soup(soup, flavor=flavor)


# ---------------------------------------------------------------------------
# Core soup-based validation
# ---------------------------------------------------------------------------

#: Headings that introduce reference / bibliography sections.
_REF_HEADING_RE = re.compile(
    r"(?i)(?:normative\s+)?references|bibliography|informative\s+references",
)

#: Headings that are specifically normative reference sections.
_NORMATIVE_HEADING_RE = re.compile(
    r"(?i)normative\s+references",
)

#: Headings that are specifically informative / bibliography sections.
_INFORMATIVE_HEADING_RE = re.compile(
    r"(?i)(?:informative\s+references|bibliography)",
)


def validate_references_soup(
    soup: BeautifulSoup,
    *,
    flavor: FlavorSpec | None = None,
    online: bool = False,
    cache_path: Path | None = None,
) -> list[dict]:
    """Run all reference validation checks on a pre-parsed soup.

    Args:
        soup: BeautifulSoup document (read-only).
        flavor: Optional standards flavor for format-specific checks.
        online: If ``True``, supplement static validation with online
            API lookups (IETF, CrossRef).  Results are cached locally.
        cache_path: Path to the online reference cache file.  Only used
            when *online* is ``True``.

    Returns:
        List of issue dicts, each with keys ``level``, ``rule``,
        ``message``, ``section``, and ``reference``.
    """
    from specbuild.standards.refdb import (
        extract_cited_year,
        extract_doc_identifier,
        lookup_standard,
    )

    issues: list[dict] = []

    # Parse bibliography sections
    sections = _find_reference_sections(soup)
    if not sections:
        logging.info("No bibliography sections found; skipping reference validation")
        return issues

    all_entries: list[tuple[str, str, str]] = []  # (entry_text, section_heading, section_type)

    for heading_text, section_tag, section_type in sections:
        entries = _extract_entries(section_tag)
        for entry_text in entries:
            all_entries.append((entry_text, heading_text, section_type))

    if not all_entries:
        logging.info("No bibliography entries found; skipping reference validation")
        return issues

    logging.info(f"Found {len(all_entries)} bibliography entries across {len(sections)} section(s)")

    for entry_text, section_heading, section_type in all_entries:
        doc_id = extract_doc_identifier(entry_text)

        # --- Format validation ---
        fmt_issues = validate_reference_format(entry_text, flavor)
        for issue in fmt_issues:
            issue["section"] = section_heading
            issue["reference"] = entry_text[:120]
        issues.extend(fmt_issues)

        if not doc_id:
            continue

        # --- Existence check ---
        ref = lookup_standard(doc_id)
        exist_issues = validate_reference_exists(doc_id, ref)
        for issue in exist_issues:
            issue["section"] = section_heading
            issue["reference"] = entry_text[:120]
        issues.extend(exist_issues)

        if ref is None:
            continue

        # --- Currency check ---
        cited_year = extract_cited_year(entry_text)
        currency_issues = validate_reference_current(doc_id, cited_year, ref)
        for issue in currency_issues:
            issue["section"] = section_heading
            issue["reference"] = entry_text[:120]
        issues.extend(currency_issues)

        # --- Status check ---
        status_issues = validate_reference_status(doc_id, ref)
        for issue in status_issues:
            issue["section"] = section_heading
            issue["reference"] = entry_text[:120]
        issues.extend(status_issues)

    # --- Normative / informative split check ---
    split_issues = check_normative_informative_split(all_entries, flavor)
    issues.extend(split_issues)

    # --- Online validation (opt-in) ---
    if online:
        entry_texts = [e[0] for e in all_entries]
        _validate_with_online(entry_texts, issues, cache_path=cache_path)

    return issues


def _validate_with_online(
    entries: list[str],
    issues: list[dict],
    cache_path: Path | None = None,
) -> None:
    """Supplement static validation with online lookups.

    Imports :func:`~specbuild.standards.onlinerefs.validate_references_online`
    and appends any online-only issues to *issues*.

    Args:
        entries: List of bibliography entry text strings.
        issues: Mutable list of issue dicts to extend.
        cache_path: Optional path to the online reference cache file.
    """
    try:
        from specbuild.standards.onlinerefs import validate_references_online
    except ImportError:
        logging.warning("Online reference module not available; skipping online validation")
        return

    online_issues = validate_references_online(entries, cache_path=cache_path)
    issues.extend(online_issues)
    if online_issues:
        logging.info(f"Online reference validation found {len(online_issues)} issue(s)")
    else:
        logging.info("Online reference validation: no additional issues found")


# ---------------------------------------------------------------------------
# Individual validation functions
# ---------------------------------------------------------------------------


def validate_reference_format(
    entry_text: str,
    flavor: FlavorSpec | None = None,
) -> list[dict]:
    """Check that a bibliography entry follows the expected citation format.

    Args:
        entry_text: Raw text of the bibliography entry.
        flavor: Optional flavor for format-specific rules.

    Returns:
        List of issue dicts (may be empty).
    """
    issues: list[dict] = []

    text = entry_text.strip()
    if not text:
        return issues

    # Check for minimal content
    if len(text) < 10:
        issues.append(
            {
                "level": "warning",
                "rule": "ref-format-short",
                "message": f"Bibliography entry is very short ({len(text)} chars) and may be incomplete.",
                "section": "",
                "reference": text[:120],
            }
        )

    # ISO-style entries should have a title after the document number
    iso_match = re.search(r"ISO/?IEC\s+\d[\d.-]+", text)
    if iso_match:
        # Check there is a title component (comma or dash after the docnumber)
        after_num = text[iso_match.end() :]
        if not after_num.strip() or not re.search(r"[,:\-]", after_num[:30]):
            issues.append(
                {
                    "level": "warning",
                    "rule": "ref-format-missing-title",
                    "message": "ISO/IEC reference may be missing a title after the document number.",
                    "section": "",
                    "reference": text[:120],
                }
            )

    # RFC entries should include "RFC NNNN" and a title
    rfc_match = re.search(r"RFC\s*(\d{3,5})", text, re.IGNORECASE)
    if rfc_match:
        # Check for a title following the RFC number
        after_rfc = text[rfc_match.end() :]
        if not after_rfc.strip() or len(after_rfc.strip()) < 5:
            issues.append(
                {
                    "level": "warning",
                    "rule": "ref-format-missing-title",
                    "message": "RFC reference may be missing a title.",
                    "section": "",
                    "reference": text[:120],
                }
            )

    return issues


def validate_reference_exists(
    doc_id: str,
    ref: object | None,
) -> list[dict]:
    """Check if a referenced standard exists in the known database.

    Args:
        doc_id: Extracted document identifier.
        ref: Looked-up :class:`~specbuild.standards.refdb.StandardRef`
            or ``None``.

    Returns:
        List with one warning if the standard is unknown, else empty.
    """
    if ref is not None:
        return []
    return [
        {
            "level": "warning",
            "rule": "ref-unknown",
            "message": f"Standard '{doc_id}' is not in the known reference database.",
            "section": "",
            "reference": "",
        }
    ]


def validate_reference_current(
    doc_id: str,
    cited_year: str | None,
    ref: object,
) -> list[dict]:
    """Warn if citing an outdated edition of a known standard.

    Args:
        doc_id: Extracted document identifier.
        cited_year: Year cited in the bibliography entry (may be None).
        ref: :class:`~specbuild.standards.refdb.StandardRef`.

    Returns:
        List with one warning if the edition is outdated, else empty.
    """
    from specbuild.standards.refdb import StandardRef

    if not isinstance(ref, StandardRef):
        return []
    if not cited_year or not ref.current_year:
        return []
    if cited_year < ref.current_year:
        return [
            {
                "level": "warning",
                "rule": "ref-outdated",
                "message": (
                    f"'{doc_id}' cites year {cited_year}, but the "
                    f"current edition is {ref.current_year}."
                ),
                "section": "",
                "reference": "",
            }
        ]
    return []


def validate_reference_status(
    doc_id: str,
    ref: object,
) -> list[dict]:
    """Warn if the referenced standard is withdrawn or superseded.

    Args:
        doc_id: Extracted document identifier.
        ref: :class:`~specbuild.standards.refdb.StandardRef`.

    Returns:
        List with one warning/error if the status is problematic.
    """
    from specbuild.standards.refdb import StandardRef

    if not isinstance(ref, StandardRef):
        return []
    if ref.status == "withdrawn":
        return [
            {
                "level": "error",
                "rule": "ref-withdrawn",
                "message": f"'{doc_id}' has been withdrawn.",
                "section": "",
                "reference": "",
            }
        ]
    if ref.status == "superseded":
        successor_msg = f" (superseded by {ref.successor})" if ref.successor else ""
        return [
            {
                "level": "warning",
                "rule": "ref-superseded",
                "message": f"'{doc_id}' has been superseded{successor_msg}.",
                "section": "",
                "reference": "",
            }
        ]
    return []


def check_normative_informative_split(
    entries: list[tuple[str, str, str]],
    flavor: FlavorSpec | None = None,
) -> list[dict]:
    """Verify that normative references are truly normative.

    Heuristic: RFC 2119 and certain foundational standards are typically
    normative.  Other informational RFCs or background standards should
    be in the informative section.

    Args:
        entries: List of ``(entry_text, section_heading, section_type)``
            tuples.
        flavor: Optional standards flavor (unused currently, reserved
            for flavor-specific rules).

    Returns:
        List of issue dicts.
    """
    from specbuild.standards.refdb import extract_doc_identifier, lookup_standard

    # Standards that are almost always normative
    _TYPICALLY_NORMATIVE = {
        "IETF RFC 2119",
        "IETF RFC 8174",
    }

    issues: list[dict] = []

    for entry_text, section_heading, section_type in entries:
        doc_id = extract_doc_identifier(entry_text)
        if not doc_id:
            continue

        ref = lookup_standard(doc_id)

        # Check if a typically-normative standard is in an informative section
        if section_type == "informative" and ref is not None:
            lookup_key = f"{ref.body} {ref.docnumber}".upper()
            if lookup_key in _TYPICALLY_NORMATIVE:
                issues.append(
                    {
                        "level": "warning",
                        "rule": "ref-normative-split",
                        "message": (
                            f"'{doc_id}' is typically a normative reference "
                            f"but appears in '{section_heading}' (informative)."
                        ),
                        "section": section_heading,
                        "reference": entry_text[:120],
                    }
                )

    return issues


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_reference_validation(
    issues: list[dict],
    *,
    strict: bool = False,
) -> None:
    """Log reference validation issues.

    Args:
        issues: List of issue dicts from :func:`validate_references_soup`.
        strict: If True, exit with error on any errors.
    """
    if not issues:
        logging.info("Reference validation passed: all bibliography entries are valid")
        return

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    for issue in warnings:
        logging.warning(f"[{issue['rule']}] {issue['message']}")

    for issue in errors:
        logging.error(f"[{issue['rule']}] {issue['message']}")

    logging.info(f"Reference validation: {len(errors)} error(s), {len(warnings)} warning(s)")

    if strict and errors:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_reference_sections(
    soup: BeautifulSoup,
) -> list[tuple[str, Tag, str]]:
    """Find bibliography / reference sections in the document.

    Returns:
        List of ``(heading_text, section_tag, section_type)`` where
        ``section_type`` is ``"normative"`` or ``"informative"``.
    """
    results: list[tuple[str, Tag, str]] = []

    for heading in soup.find_all(HEADING_RE):
        text = heading.get_text(strip=True)
        if not _REF_HEADING_RE.search(text):
            continue

        # Determine section type
        if _NORMATIVE_HEADING_RE.search(text):
            section_type = "normative"
        else:
            section_type = "informative"

        # Find the containing section element
        section = heading.find_parent("section")
        if section is None:
            # Fall back to the heading's parent
            section = heading.parent

        if section is not None:
            results.append((text, section, section_type))

    return results


def _extract_entries(section_tag: Tag) -> list[str]:
    """Extract individual bibliography entries from a section.

    Handles common patterns:
    - ``<dl>`` (Bikeshed default): ``<dt>``/``<dd>`` pairs
    - ``<ol>``/``<ul>``: ``<li>`` items
    - ``<p>`` elements with reference content

    Args:
        section_tag: BeautifulSoup tag for the reference section.

    Returns:
        List of entry text strings.
    """
    entries: list[str] = []

    # Try <dl> first (Bikeshed default bibliography format)
    for dl in section_tag.find_all("dl"):
        for dd in dl.find_all("dd"):
            text = dd.get_text(strip=True)
            if text:
                # Also prepend the <dt> text if available
                dt = dd.find_previous_sibling("dt")
                if dt:
                    dt_text = dt.get_text(strip=True)
                    text = f"{dt_text} {text}"
                entries.append(text)

    if entries:
        return entries

    # Try <ol>/<ul>
    for lst in section_tag.find_all(["ol", "ul"]):
        for li in lst.find_all("li"):
            text = li.get_text(strip=True)
            if text:
                entries.append(text)

    if entries:
        return entries

    # Fall back to <p> elements
    for p in section_tag.find_all("p"):
        text = p.get_text(strip=True)
        # Filter out headings and very short text
        if text and len(text) > 15:
            entries.append(text)

    return entries

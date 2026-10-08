"""RFC 2119 keyword usage validator.

Checks that normative keywords (MUST, SHOULD, etc.) are used appropriately
within the spec:

1. Keywords in informative sections — severity ``warning``.
2. ALL-CAPS keywords not wrapped in ``<em>`` or ``<strong>`` — severity ``warning``.
3. Spec claims RFC 2119 (text contains "RFC 2119") but zero keyword instances found
   — severity ``error``.
4. Mixed-case inconsistency: a keyword appears in ALL-CAPS somewhere but also as
   lowercase in a nearby sentence — severity ``warning``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from specbuild.utils import find_nearest_heading

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

RFC2119_KEYWORDS = frozenset(
    {
        "MUST",
        "MUST NOT",
        "REQUIRED",
        "SHALL",
        "SHALL NOT",
        "SHOULD",
        "SHOULD NOT",
        "RECOMMENDED",
        "MAY",
        "OPTIONAL",
    }
)

# All-caps pattern (multi-word keywords matched longest first).
_KW_PATTERN = re.compile(
    r"\b(MUST NOT|SHALL NOT|SHOULD NOT|MUST|REQUIRED|SHALL|SHOULD|RECOMMENDED|MAY|OPTIONAL)\b"
)
# Same keywords in lowercase.
_KW_LOWER_PATTERN = re.compile(
    r"\b(must not|shall not|should not|must|required|shall|should|recommended|may|optional)\b"
)

# Tags to skip when walking text nodes.
_SKIP_TAGS = frozenset({"script", "style", "pre", "code"})
# Tags that signal an informative section.
_INFORMATIVE_MARKERS = frozenset({"non-normative", "informative", "note", "example"})


def _is_informative(element) -> bool:
    """Return True if *element* is inside an informative section."""
    for parent in element.parents:
        classes = set(parent.get("class") or [])
        if classes & _INFORMATIVE_MARKERS:
            return True
        note_id = (parent.get("id") or "").lower()
        if "informative" in note_id or "non-normative" in note_id:
            return True
    return False


def _wrapped_in_em_strong(node) -> bool:
    """Return True if *node* is a direct child of ``<em>`` or ``<strong>``."""
    parent = node.parent
    if parent is None:
        return False
    return parent.name in ("em", "strong")


def check_rfc2119_usage_soup(soup: BeautifulSoup, flavor: str | None = None) -> list[dict]:
    """Analyse RFC 2119 keyword usage and return a list of issue dicts.

    Each issue dict has keys:
        ``section``, ``text_snippet``, ``issue``, ``severity``

    Args:
        soup: Parsed HTML document.
        flavor: Optional standards flavor (currently unused; reserved for
            future flavor-specific rules).

    Returns:
        List of issue dicts, one per detected problem.
    """
    issues: list[dict] = []
    all_text_nodes: list[tuple[object, str]] = []  # (node, text)

    # Collect all text nodes outside skip tags.
    for node in soup.find_all(string=True):
        if node.parent and node.parent.name in _SKIP_TAGS:
            continue
        text = str(node)
        if not text.strip():
            continue
        all_text_nodes.append((node, text))

    # --- Check 1 & 2: per keyword occurrence ---
    total_keyword_hits = 0

    for node, text in all_text_nodes:
        for m in _KW_PATTERN.finditer(text):
            total_keyword_hits += 1
            kw = m.group(0)
            snippet = text[max(0, m.start() - 30) : m.end() + 30].strip()
            section = find_nearest_heading(node)

            # Check 1: keyword in informative section.
            if _is_informative(node):
                issues.append(
                    {
                        "section": section,
                        "text_snippet": snippet,
                        "issue": "informative_keyword",
                        "severity": "warning",
                        "keyword": kw,
                    }
                )

            # Check 2: keyword not wrapped in <em> or <strong>.
            if not _wrapped_in_em_strong(node):
                issues.append(
                    {
                        "section": section,
                        "text_snippet": snippet,
                        "issue": "unwrapped_keyword",
                        "severity": "warning",
                        "keyword": kw,
                    }
                )

    # --- Check 3: claims RFC 2119 but no keywords found ---
    full_text = soup.get_text()
    claims_rfc2119 = "RFC 2119" in full_text or "rfc2119" in full_text.lower()
    if claims_rfc2119 and total_keyword_hits == 0:
        issues.append(
            {
                "section": "",
                "text_snippet": "Spec references RFC 2119 but no keywords found",
                "issue": "missing_keywords",
                "severity": "error",
                "keyword": "",
            }
        )

    # --- Check 4: inconsistent case (MUST somewhere, 'must' elsewhere) ---
    caps_keywords: set[str] = set()
    lower_keywords: set[str] = set()
    _sentence_end_re = re.compile(r"[.!?]\s*$")
    for _node, text in all_text_nodes:
        for m in _KW_PATTERN.finditer(text):
            caps_keywords.add(m.group(0).upper())
        for m in _KW_LOWER_PATTERN.finditer(text):
            # Skip sentence-initial occurrences — those are ordinary prose, not RFC 2119 usage
            prefix = text[max(0, m.start() - 2) : m.start()]
            if m.start() == 0 or _sentence_end_re.search(prefix):
                continue
            lower_keywords.add(m.group(0).upper())

    inconsistent = caps_keywords & lower_keywords
    if inconsistent:
        for kw in sorted(inconsistent):
            issues.append(
                {
                    "section": "",
                    "text_snippet": f"Keyword '{kw}' used in both ALL-CAPS and lowercase",
                    "issue": "inconsistent_case",
                    "severity": "warning",
                    "keyword": kw,
                }
            )

    return issues


def report_rfc2119_validation(issues: list[dict], strict: bool = False) -> None:
    """Log issues; raise ``SystemExit(1)`` if *strict* and any errors present.

    Args:
        issues: Issue list from :func:`check_rfc2119_usage_soup`.
        strict: Exit with error code 1 when any ``error``-severity issue exists.
    """
    if not issues:
        log.info("RFC 2119 validation: no issues found")
        return

    errors = 0
    for issue in issues:
        sev = issue.get("severity", "warning")
        kw = issue.get("keyword", "")
        section = issue.get("section", "")
        snippet = issue.get("text_snippet", "")
        kind = issue.get("issue", "")
        loc = f" [{section}]" if section else ""
        msg = f"RFC 2119 {sev}: {kind} — {kw!r}{loc} — {snippet!r}"
        if sev == "error":
            log.error(msg)
            errors += 1
        else:
            log.warning(msg)

    log.info("RFC 2119 validation: %d issue(s) found", len(issues))
    if strict and errors:
        raise SystemExit(1)

"""Terminology consistency checker: flag concepts referred to by different names."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.utils import get_bs4, read_html

# Common synonym groups in technical specifications.
# Each group maps canonical_term -> [variant1, variant2, ...].
# Users can extend this via a config file in the future.
_DEFAULT_SYNONYM_GROUPS = {
    "frame": ["picture", "image"],
    "block": ["coding unit", "CU"],
    "pixel": ["pel", "sample"],
    "flag": ["indicator", "signal"],
    "syntax element": ["syntax_element"],
    "bitstream": ["bit stream", "bit-stream"],
    "decoder": ["decoding process"],
    "encoder": ["encoding process"],
}


def _compile_word_pattern(term: str) -> re.Pattern:
    """Compile a case-insensitive word-boundary pattern with optional plural."""
    return re.compile(r"\b" + re.escape(term.lower()) + r"(?:s|es)?\b")


# Pre-compile patterns for all default terms
_COMPILED_PATTERNS: dict[str, tuple[re.Pattern, list[tuple[str, re.Pattern]]]] = {}
for _canonical, _variants in _DEFAULT_SYNONYM_GROUPS.items():
    _COMPILED_PATTERNS[_canonical] = (
        _compile_word_pattern(_canonical),
        [(_v, _compile_word_pattern(_v)) for _v in _variants],
    )


def check_terminology(
    html_path: Path,
    custom_groups: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Check for terminology inconsistencies in the specification.

    File-based wrapper around :func:`check_terminology_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        custom_groups: Optional mapping of canonical_term -> [variants].

    Returns:
        List of dicts with keys: canonical, variant, canonical_count,
        variant_count, examples (list of short context strings).
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping terminology check")
        return []

    logging.info(f"Checking terminology consistency in {html_path.name}")
    soup = read_html(html_path)
    return check_terminology_soup(soup, custom_groups=custom_groups)


def check_terminology_soup(
    soup: object,
    custom_groups: dict[str, list[str]] | None = None,
) -> list[dict]:
    """Check terminology consistency on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        custom_groups: Optional mapping of canonical_term -> [variants].

    Returns:
        List of terminology inconsistency dicts.
    """

    # Build pattern set: pre-compiled defaults + any custom groups
    patterns = {k: (v[0], list(v[1])) for k, v in _COMPILED_PATTERNS.items()}
    if custom_groups:
        for canonical, variants in custom_groups.items():
            if canonical not in patterns:
                patterns[canonical] = (
                    _compile_word_pattern(canonical),
                    [(_v, _compile_word_pattern(_v)) for _v in variants],
                )
            else:
                # Extend existing group with new variants
                existing_canon_pat, existing_variants = patterns[canonical]
                for v in variants:
                    existing_variants.append((v, _compile_word_pattern(v)))

    # Collect all prose text from paragraphs and list items
    # Use recursive=False on <main> children, then find_all within each,
    # to avoid double-counting nested prose elements
    main = soup.find("main") or soup.find("body") or soup
    prose_elements = main.find_all(["p", "li", "dd", "dt"], recursive=True)
    full_text = "\n".join(elem.get_text() for elem in prose_elements)
    full_text_lower = full_text.lower()

    issues = []

    for canonical, (canonical_pattern, variant_pairs) in patterns.items():
        canonical_count = len(canonical_pattern.findall(full_text_lower))

        for variant, variant_pattern in variant_pairs:
            variant_count = len(variant_pattern.findall(full_text_lower))

            # Only flag if both canonical and variant appear
            if canonical_count > 0 and variant_count > 0:
                # Find a few example contexts
                context_margin = 30  # chars of surrounding text per example
                max_examples = 3  # cap on examples per issue
                examples = []
                for match in variant_pattern.finditer(full_text_lower):
                    start = max(0, match.start() - context_margin)
                    end = min(len(full_text), match.end() + context_margin)
                    context = full_text[start:end].replace("\n", " ").strip()
                    examples.append(f"...{context}...")
                    if len(examples) >= max_examples:
                        break

                issues.append(
                    {
                        "canonical": canonical,
                        "variant": variant,
                        "canonical_count": canonical_count,
                        "variant_count": variant_count,
                        "examples": examples,
                    }
                )

    if issues:
        logging.warning(f"Found {len(issues)} terminology inconsistencies")
    else:
        logging.info("No terminology inconsistencies found")

    return issues


def report_terminology_issues(issues: list[dict]) -> None:
    """Log terminology inconsistency findings.

    Args:
        issues: List of issue dicts from :func:`check_terminology`.
    """
    if not issues:
        logging.info("Terminology check passed: no inconsistencies found")
        return

    logging.warning(f"Terminology consistency: {len(issues)} potential issue(s):")
    for issue in issues:
        logging.warning(
            f"  '{issue['canonical']}' ({issue['canonical_count']}x) vs "
            f"'{issue['variant']}' ({issue['variant_count']}x)"
        )
        for ex in issue["examples"][:2]:
            logging.warning(f"    Example: {ex[:80]}")

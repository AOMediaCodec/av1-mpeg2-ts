"""Domain-aware spelling and terminology linter.

Checks prose text for common misspellings and terminology violations
using a configurable dictionary.  The linter focuses on:

- Common misspellings of domain-specific terms
- Inconsistent capitalization of standard names
- Deprecated terminology (with suggested replacements)
- Custom patterns from a user-provided dictionary file

The default dictionary covers video coding, standards, and specification
terminology.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.utils import find_nearest_heading, get_bs4, read_html

# ---------------------------------------------------------------------------
# Default terminology rules
# ---------------------------------------------------------------------------

# Each rule: (pattern, message, suggestion)
# Patterns are compiled as case-insensitive word-boundary matches.
_DEFAULT_RULES: list[tuple[str, str, str]] = [
    # Common misspellings
    (r"\bbitsteam\b", 'Misspelling of "bitstream"', "bitstream"),
    (r"\bdecorder\b", 'Misspelling of "decoder"', "decoder"),
    (r"\bencorder\b", 'Misspelling of "encoder"', "encoder"),
    (r"\bparmeter\b", 'Misspelling of "parameter"', "parameter"),
    (r"\bparamater\b", 'Misspelling of "parameter"', "parameter"),
    (r"\bquanitization\b", 'Misspelling of "quantization"', "quantization"),
    (r"\bquantisation\b", 'Use "quantization" (US spelling)', "quantization"),
    (r"\boptimisation\b", 'Use "optimization" (US spelling)', "optimization"),
    (r"\bcolour\b", 'Use "color" (US spelling)', "color"),
    (r"\bneighbour\b", 'Use "neighbor" (US spelling)', "neighbor"),
    (r"\bbehaviour\b", 'Use "behavior" (US spelling)', "behavior"),
    (r"\bluminence\b", 'Misspelling of "luminance"', "luminance"),
    (r"\bchromanance\b", 'Misspelling of "chrominance"', "chrominance"),
    # Inconsistent capitalization
    (r"\bAv1\b", "Incorrect capitalization", "AV1"),
    (r"\bAv2\b", "Incorrect capitalization", "AV2"),
    (r"\bHevc\b", "Incorrect capitalization", "HEVC"),
    (r"\bVvc\b", "Incorrect capitalization", "VVC"),
    # Deprecated terminology
    (r"\bmacroblocks?\b", "Deprecated term in modern codecs", "coding unit / block"),
    # Common misspellings — general
    (r"\brecieve\b", 'Misspelling of "receive"', "receive"),
    (r"\boccured\b", 'Misspelling of "occurred"', "occurred"),
    (r"\bseperate\b", 'Misspelling of "separate"', "separate"),
    (r"\bdefinately\b", 'Misspelling of "definitely"', "definitely"),
    (r"\bexistance\b", 'Misspelling of "existence"', "existence"),
    (r"\baccomodate\b", 'Misspelling of "accommodate"', "accommodate"),
    (r"\baquire\b", 'Misspelling of "acquire"', "acquire"),
    (r"\bbeleive\b", 'Misspelling of "believe"', "believe"),
    (
        r"\bcalender\b",
        'Misspelling of "calendar" (unless "calender" the machine is intended)',
        "calendar",
    ),
    (r"\bcommitee\b", 'Misspelling of "committee"', "committee"),
    (r"\bconcious\b", 'Misspelling of "conscious"', "conscious"),
    (r"\bdependant\b", 'Use "dependent" (adjective form in technical writing)', "dependent"),
    (r"\benviroment\b", 'Misspelling of "environment"', "environment"),
    (r"\bindependant\b", 'Use "independent"', "independent"),
    (r"\bmaintainance\b", 'Misspelling of "maintenance"', "maintenance"),
    (r"\bneccessary\b", 'Misspelling of "necessary"', "necessary"),
    (r"\bpersistant\b", 'Misspelling of "persistent"', "persistent"),
    (r"\bpublically\b", 'Misspelling of "publicly"', "publicly"),
    (r"\brelavant\b", 'Misspelling of "relevant"', "relevant"),
    (r"\btechnicaly\b", 'Misspelling of "technically"', "technically"),
    # Commonly confused pairs
    (
        r"\beffect\b(?=\s+(?:the|a|an|this|that|these|those|its|our|their)\b)",
        'Possible confusion: "effect" (noun) vs "affect" (verb) — verify intent',
        "affect (verb) / effect (noun)",
    ),
    (
        r"\bprinciple\b(?=\s+(?:engineer|investigator|component|architect|office)\b)",
        'Possible confusion: "principle" (rule) vs "principal" (main/person)',
        "principal",
    ),
    (
        r"\bcompliment\b",
        'Possible confusion: "compliment" (praise) vs "complement" (complete/enhance) — verify intent',
        "complement",
    ),
    # Standards writing verbosity
    (r"\bin order to\b", 'Wordy phrasing; prefer "to"', "to"),
    (r"\bdue to the fact that\b", 'Wordy phrasing; prefer "because"', "because"),
    (r"\bin the event that\b", 'Wordy phrasing; prefer "if"', "if"),
    # Tech-specific usage
    (r"\bclick on\b", 'Prefer "click" (without "on")', "click"),
    (r"\binput in\b", 'Prefer "input into"', "input into"),
]

_COMPILED_RULES: list[tuple[re.Pattern, str, str]] | None = None
_DEFAULT_COMBINED: re.Pattern | None = None  # cached combined regex for the default rule set
_DEFAULT_META: dict[str, tuple[str, str]] | None = None


def _get_rules() -> list[tuple[re.Pattern, str, str]]:
    """Return compiled default rules (lazy-initialized)."""
    global _COMPILED_RULES
    if _COMPILED_RULES is None:
        _COMPILED_RULES = [
            (re.compile(pattern, re.IGNORECASE), msg, suggestion)
            for pattern, msg, suggestion in _DEFAULT_RULES
        ]
    return _COMPILED_RULES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

# Tags whose content is not prose — skip spelling checks inside these.
SKIP_TAGS: frozenset[str] = frozenset({"code", "pre", "script", "style", "kbd", "samp"})

# Prose container elements to check.
SPELLING_PROSE_TAGS: frozenset[str] = frozenset(
    {"p", "li", "dd", "dt", "td", "th", "figcaption", "span", "div", "blockquote"}
)


def check_spelling(html_path: Path, *, custom_dict: Path | None = None) -> list[dict]:
    """File-based wrapper around :func:`check_spelling_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        custom_dict: Optional path to a custom dictionary file.

    Returns:
        List of issue dicts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping spell check")
        return []

    logging.info(f"Spell-checking {html_path.name}")
    soup = read_html(html_path)
    extra_rules = load_custom_dict(custom_dict) if custom_dict else []
    return check_spelling_soup(soup, extra_rules=extra_rules)


def _build_combined(
    rules: list[tuple[re.Pattern, str, str]],
) -> tuple[re.Pattern | None, dict[str, tuple[str, str]]]:
    """Build a single named-alternation regex from *rules*.

    Returns ``(combined_pattern, meta_by_name)`` or ``(None, {})`` when
    *rules* is empty.
    """
    parts: list[str] = []
    meta: list[tuple[str, str, str]] = []
    for idx, (pattern, msg, suggestion) in enumerate(rules):
        gname = f"r{idx}"
        meta.append((gname, msg, suggestion))
        parts.append(f"(?P<{gname}>{pattern.pattern})")
    if not parts:
        return None, {}
    return re.compile("|".join(parts), re.IGNORECASE), {
        gname: (msg, suggestion) for gname, msg, suggestion in meta
    }


def check_spelling_soup(
    soup: object,
    *,
    extra_rules: list[tuple[re.Pattern, str, str]] | None = None,
) -> list[dict]:
    """Check prose text in the HTML for spelling/terminology issues.

    Args:
        soup: BeautifulSoup document (read-only).
        extra_rules: Additional compiled rules to check.

    Returns:
        List of issue dicts with ``word``, ``message``, ``suggestion``,
        ``context`` keys.
    """
    rules = _get_rules()
    if extra_rules:
        rules = rules + extra_rules

    # Build one combined alternation regex — rebuild only when extra_rules
    # changes the rule set; cache the default-only version at module level.
    global _DEFAULT_COMBINED, _DEFAULT_META
    if extra_rules:
        combined, meta_by_name = _build_combined(rules)
    else:
        if _DEFAULT_COMBINED is None:
            _DEFAULT_COMBINED, _DEFAULT_META = _build_combined(rules)
        combined, meta_by_name = _DEFAULT_COMBINED, _DEFAULT_META  # type: ignore[assignment]

    if combined is None:
        return []

    issues: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (lower_word, context) dedup

    for elem in soup.find_all(SPELLING_PROSE_TAGS):
        # Skip if inside a code/pre block
        if any(p.name in SKIP_TAGS for p in elem.parents if hasattr(p, "name")):
            continue

        # Get direct text (not from child code elements)
        text = _get_prose_text(elem)
        if not text:
            continue

        context = find_nearest_heading(elem)

        for match in combined.finditer(text):
            gname = match.lastgroup
            if gname is None or gname not in meta_by_name:
                continue
            msg, suggestion = meta_by_name[gname]
            word = match.group(0)
            key = (word.lower(), context)
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                {
                    "word": word,
                    "message": msg,
                    "suggestion": suggestion,
                    "context": context,
                }
            )

    return issues


def report_spelling(issues: list[dict], *, strict: bool = False) -> None:
    """Log spelling check findings.

    Args:
        issues: List from :func:`check_spelling`.
        strict: If True, exit with error when issues are found.
    """
    if not issues:
        logging.info("Spelling check passed: no issues found")
        return

    logging.warning(f"Spelling check: {len(issues)} issue(s)")
    for issue in issues:
        logging.warning(
            f'  "{issue["word"]}" — {issue["message"]} '
            f"(suggestion: {issue['suggestion']}, "
            f"near: {issue['context']})"
        )

    if strict:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_prose_text(elem: object) -> str:
    """Extract text from an element, excluding child code/pre blocks."""
    parts: list[str] = []
    for child in elem.children:
        if hasattr(child, "name"):
            if child.name in ("code", "pre", "kbd", "samp", "var"):
                continue
            parts.append(child.get_text())
        else:
            parts.append(str(child))
    return " ".join(parts)


def load_custom_dict(dict_path: Path) -> list[tuple[re.Pattern, str, str]]:
    """Load a custom dictionary file.

    Format: one rule per line, tab-separated:
        pattern<TAB>message<TAB>suggestion

    Lines starting with # are comments. Empty lines are skipped.

    Args:
        dict_path: Path to the dictionary file.

    Returns:
        List of compiled rule tuples.
    """
    rules: list[tuple[re.Pattern, str, str]] = []
    try:
        lines = dict_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        logging.warning(f"Custom dictionary not found: {dict_path}")
        return []
    except (OSError, UnicodeDecodeError) as exc:
        logging.warning(f"Cannot read custom dictionary {dict_path}: {exc}")
        return []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            logging.warning(f"Skipping malformed dictionary line: {line}")
            continue
        try:
            pattern = re.compile(parts[0], re.IGNORECASE)
            rules.append((pattern, parts[1], parts[2]))
        except re.error as e:
            logging.warning(f"Invalid regex in dictionary: {parts[0]} — {e}")

    logging.info(f"Loaded {len(rules)} custom spelling rules from {dict_path}")
    return rules

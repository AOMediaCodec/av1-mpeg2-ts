"""Editorial consistency checker for specification HTML.

Checks for style/editorial consistency issues beyond spelling:

- Mixed compound word spellings (e.g. "bitstream" vs "bit stream")
- Inconsistent capitalization of defined terms (``<dfn>`` text vs ``<a>``
  reference text)
- Configurable rules from a TOML file

This is **different** from :mod:`terminology` (which checks synonym groups)
and :mod:`spellingcheck` (which catches misspellings).  The editorial checker
targets *style* consistency — cases where both variants are correct but mixing
them is undesirable.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.context import resolve_lookup_maps
from specbuild.utils import find_nearest_heading, get_bs4, read_html

if TYPE_CHECKING:
    from specbuild.context import BuildContext

# ---------------------------------------------------------------------------
# Default built-in rules
# ---------------------------------------------------------------------------

_DEFAULT_RULES: list[dict] = [
    {
        "name": "compound-bitstream",
        "preferred": "bitstream",
        "pattern_a": r"\bbitstream\b",
        "pattern_b": r"\bbit[- ]stream\b",
        "message": "Inconsistent: prefer 'bitstream' (one word)",
    },
    {
        "name": "compound-codestream",
        "preferred": "codestream",
        "pattern_a": r"\bcodestream\b",
        "pattern_b": r"\bcode[- ]stream\b",
        "message": "Inconsistent: prefer 'codestream' (one word)",
    },
    {
        "name": "compound-macroblock",
        "preferred": "macroblock",
        "pattern_a": r"\bmacroblock\b",
        "pattern_b": r"\bmacro[- ]block\b",
        "message": "Inconsistent: prefer 'macroblock' (one word)",
    },
    {
        "name": "double-space",
        "preferred": None,
        "pattern_a": r"(?<=[.!?])\s{2,}",
        "pattern_b": None,
        "message": "Double space after punctuation",
    },
]

# Tags whose content should be skipped during editorial checks.
_SKIP_TAGS: frozenset[str] = frozenset({"code", "pre", "script", "style"})

# Prose container elements to inspect.
_PROSE_TAGS: frozenset[str] = frozenset(
    {"p", "li", "dd", "dt", "td", "th", "figcaption", "span", "div", "blockquote"}
)


# ---------------------------------------------------------------------------
# TOML rule loading
# ---------------------------------------------------------------------------


def load_editorial_rules(path: Path) -> list[dict]:
    """Load editorial rules from a TOML configuration file.

    The TOML file should contain one or more ``[[rules]]`` tables::

        [[rules]]
        name = "compound-bitstream"
        preferred = "bitstream"
        pattern_a = "\\\\bbitstream\\\\b"
        pattern_b = "\\\\bbit[- ]stream\\\\b"
        message = "Prefer 'bitstream' (one word)"

    Args:
        path: Path to the TOML file.

    Returns:
        List of rule dicts suitable for passing to :func:`check_editorial_soup`.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logging.warning(f"Editorial rules file not found: {path}")
        return []

    # Python 3.11+ ships tomllib; fall back to tomli for older versions.
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        logging.warning(
            "Neither tomllib nor tomli available — cannot load editorial rules from TOML"
        )
        return []

    try:
        data = tomllib.loads(raw)
    except Exception as exc:
        logging.error(f"Failed to parse editorial rules TOML: {exc}")
        return []

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        logging.warning("Expected [[rules]] array in TOML file")
        return []

    valid: list[dict] = []
    for entry in rules:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "(unnamed)")
        if "pattern_a" not in entry:
            logging.warning(f"Editorial rule '{name}' missing pattern_a — skipped")
            continue
        valid.append(
            {
                "name": name,
                "preferred": entry.get("preferred"),
                "pattern_a": entry["pattern_a"],
                "pattern_b": entry.get("pattern_b"),
                "message": entry.get("message", f"Editorial issue: {name}"),
            }
        )

    logging.info(f"Loaded {len(valid)} editorial rules from {path}")
    return valid


# ---------------------------------------------------------------------------
# Public API — file wrapper + soup core
# ---------------------------------------------------------------------------


def check_editorial(
    html_path: Path,
    *,
    custom_rules: list[dict] | None = None,
    rules_toml: Path | None = None,
) -> list[dict]:
    """Check for editorial consistency issues in the specification.

    File-based wrapper around :func:`check_editorial_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        custom_rules: Optional list of rule dicts (same shape as
            :data:`_DEFAULT_RULES`).
        rules_toml: Optional path to a TOML file with extra rules.

    Returns:
        List of issue dicts.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping editorial check")
        return []

    logging.info(f"Checking editorial consistency in {html_path.name}")
    soup = read_html(html_path)

    extra: list[dict] = []
    if rules_toml:
        extra.extend(load_editorial_rules(rules_toml))
    if custom_rules:
        extra.extend(custom_rules)

    return check_editorial_soup(soup, extra_rules=extra or None)


def check_editorial_soup(
    soup: object,
    *,
    extra_rules: list[dict] | None = None,
    ctx: BuildContext | None = None,
) -> list[dict]:
    """Check editorial consistency on a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).
        extra_rules: Additional rule dicts to merge with the defaults.
        ctx: Optional :class:`BuildContext` carrying prebuilt
             ``links_by_href`` map for the dfn-capitalization scan.

    Returns:
        List of issue dicts.  Each dict has keys:

        - ``rule`` (str): Rule name.
        - ``message`` (str): Human-readable description.
        - ``severity`` (``'warning'`` or ``'error'``): Issue severity.
        - ``instances`` (list[dict]): Each with ``text`` and ``context``.
    """
    rules = list(_DEFAULT_RULES)
    if extra_rules:
        # Merge: extra rules override defaults with the same name.
        existing_names = {r["name"] for r in rules}
        for er in extra_rules:
            if er["name"] in existing_names:
                rules = [r if r["name"] != er["name"] else er for r in rules]
            else:
                rules.append(er)

    issues: list[dict] = []

    # --- Compound-word / pattern rules ---
    issues.extend(_check_pattern_rules(soup, rules))

    # --- Dfn capitalization ---
    issues.extend(_check_dfn_capitalization(soup, ctx))

    return issues


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report_editorial_issues(issues: list[dict], *, strict: bool = False) -> None:
    """Log editorial consistency findings and optionally exit on error.

    Args:
        issues: List of issue dicts from :func:`check_editorial`.
        strict: If True, exit with code 1 when any issues are found.
    """
    if not issues:
        logging.info("Editorial consistency check passed: no issues found")
        return

    total_instances = sum(len(iss["instances"]) for iss in issues)
    logging.warning(
        f"Editorial consistency: {len(issues)} rule(s) triggered, "
        f"{total_instances} instance(s) total"
    )

    for issue in issues:
        level = logging.ERROR if issue["severity"] == "error" else logging.WARNING
        logging.log(
            level, f"  [{issue['rule']}] {issue['message']} ({len(issue['instances'])} instance(s))"
        )
        for inst in issue["instances"][:5]:
            logging.log(level, f'    "{inst["text"]}" — near: {inst["context"]}')
        remaining = len(issue["instances"]) - 5
        if remaining > 0:
            logging.log(level, f"    ... and {remaining} more")

    if strict:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal: pattern-based rules
# ---------------------------------------------------------------------------


def _get_prose_text(elem: object) -> str:
    """Extract text from an element, excluding child code/pre/script/style."""
    parts: list[str] = []
    for child in elem.children:
        if hasattr(child, "name"):
            if child.name in _SKIP_TAGS:
                continue
            parts.append(child.get_text())
        else:
            parts.append(str(child))
    return "".join(parts)


def _check_pattern_rules(soup: object, rules: list[dict]) -> list[dict]:
    """Run compound-word and regex pattern rules against prose text.

    For rules with both ``pattern_a`` and ``pattern_b``: only flag if *both*
    variants appear in the document.  Instances of the non-preferred variant
    are reported.

    For rules with only ``pattern_a`` (``pattern_b`` is None): every match is
    reported directly.
    """
    # Compile patterns
    compiled: list[dict] = []
    for rule in rules:
        try:
            pat_a = re.compile(rule["pattern_a"], re.IGNORECASE)
        except re.error as exc:
            logging.warning(f"Invalid regex in rule '{rule['name']}' pattern_a: {exc}")
            continue
        pat_b = None
        if rule.get("pattern_b"):
            try:
                pat_b = re.compile(rule["pattern_b"], re.IGNORECASE)
            except re.error as exc:
                logging.warning(f"Invalid regex in rule '{rule['name']}' pattern_b: {exc}")
                continue
        compiled.append({**rule, "_pat_a": pat_a, "_pat_b": pat_b})

    # Collect prose elements
    main = soup.find("main") or soup.find("body") or soup
    prose_elements = main.find_all(list(_PROSE_TAGS), recursive=True)

    # For compound rules (both patterns), first do a whole-document scan to
    # determine whether both variants are present.
    full_text = "\n".join(_get_prose_text(el) for el in prose_elements)

    issues: list[dict] = []

    for rule in compiled:
        pat_a = rule["_pat_a"]
        pat_b = rule["_pat_b"]

        if pat_b is not None:
            # Compound-word rule: flag only if both variants occur
            has_a = bool(pat_a.search(full_text))
            has_b = bool(pat_b.search(full_text))
            if not (has_a and has_b):
                continue

            # Collect instances of the non-preferred variant
            # The non-preferred variant is whichever pattern does NOT match
            # the preferred spelling.
            if rule.get("preferred"):
                # Test which pattern matches the preferred form
                if pat_a.search(rule["preferred"]):
                    non_preferred_pat = pat_b
                else:
                    non_preferred_pat = pat_a
            else:
                # No preferred form — flag pattern_b occurrences by convention
                non_preferred_pat = pat_b

            instances = _collect_instances(prose_elements, non_preferred_pat)
            if instances:
                issues.append(
                    {
                        "rule": rule["name"],
                        "message": rule["message"],
                        "severity": "warning",
                        "instances": instances,
                    }
                )
        else:
            # Single-pattern rule (e.g. double-space): flag every match
            instances = _collect_instances(prose_elements, pat_a)
            if instances:
                issues.append(
                    {
                        "rule": rule["name"],
                        "message": rule["message"],
                        "severity": "warning",
                        "instances": instances,
                    }
                )

    return issues


def _collect_instances(prose_elements: list, pattern: re.Pattern) -> list[dict]:
    """Scan prose elements for pattern matches, returning instance dicts."""
    instances: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for elem in prose_elements:
        # Skip elements nested inside code/pre/script/style
        if any(p.name in _SKIP_TAGS for p in elem.parents if hasattr(p, "name")):
            continue

        text = _get_prose_text(elem)
        if not text:
            continue

        for match in pattern.finditer(text):
            matched_text = match.group(0)
            context = find_nearest_heading(elem)
            key = (matched_text.lower(), context)
            if key in seen:
                continue
            seen.add(key)
            instances.append(
                {
                    "text": matched_text,
                    "context": context,
                }
            )

    return instances


# ---------------------------------------------------------------------------
# Internal: dfn capitalization check
# ---------------------------------------------------------------------------


def _check_dfn_capitalization(soup: object, ctx: BuildContext | None = None) -> list[dict]:
    """Check that ``<a>`` references use the same capitalization as their ``<dfn>``.

    Collects all ``<dfn>`` elements and their canonical text, then inspects
    ``<a>`` links whose ``href`` targets a dfn ID.  If the link text differs
    in capitalization from the definition text, an instance is recorded.
    """
    # Build map: dfn id -> canonical text (preserving case)
    dfn_map: dict[str, str] = {}  # id -> text

    for dfn in soup.find_all("dfn"):
        dfn_id = dfn.get("id", "")
        if not dfn_id:
            continue
        text = dfn.get_text(strip=True)
        if text:
            dfn_map[dfn_id] = text

    if not dfn_map:
        return []

    # Scan <a> references via the prebuilt {href: [<a>, ...]} map.
    _, links_by_href = resolve_lookup_maps(soup, ctx)
    instances: list[dict] = []
    seen: set[tuple[str, str]] = set()

    for href, link_list in links_by_href.items():
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if target_id not in dfn_map:
            continue

        for link in link_list:
            # Skip links inside code/pre/script/style
            if any(p.name in _SKIP_TAGS for p in link.parents if hasattr(p, "name")):
                continue

            ref_text = link.get_text(strip=True)
            dfn_text = dfn_map[target_id]

            if not ref_text:
                continue

            # Compare: same letters but different case?
            if ref_text.lower() == dfn_text.lower() and ref_text != dfn_text:
                context = find_nearest_heading(link)
                key = (ref_text, context)
                if key in seen:
                    continue
                seen.add(key)
                instances.append(
                    {
                        "text": (f"<a> '{ref_text}' vs <dfn> '{dfn_text}' (#{target_id})"),
                        "context": context,
                    }
                )

    if not instances:
        return []

    return [
        {
            "rule": "dfn-capitalization",
            "message": ("Inconsistent capitalization between <dfn> definitions and <a> references"),
            "severity": "warning",
            "instances": instances,
        }
    ]

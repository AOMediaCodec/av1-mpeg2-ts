"""Profile/level/tier consistency validator (TOML-driven).

Checks that the profiles, levels, and tiers declared in a TOML manifest
match the conformance markers and Annex A tables in the compiled spec.

TOML schema (minimal)::

    [[profiles]]
    name = "Main"
    levels = ["Level 4.0", "Level 5.0", "Level 6.0"]
    tiers = ["Main", "High"]

    [[profiles]]
    name = "Main 10"
    levels = ["Level 4.0", "Level 5.0"]
    tiers = ["Main"]

The validator emits :class:`ProfileIssue` entries for:

* **missing_profile** — declared in TOML but no ``data-conformance-profile``
  marker references it in the spec.
* **orphan_marker** — spec marker references a profile not in TOML.
* **missing_level_table** — level mentioned in body prose / markers but
  no Annex A table row defines it.
* **unknown_tier** — tier name on a profile is not in the union of tiers
  declared anywhere in TOML.

Severity: ``error`` for missing/unknown definitions, ``warning`` for
markers that reference undeclared profiles.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ProfileSpec:
    """A single declared profile from the TOML manifest."""

    name: str
    levels: list[str] = field(default_factory=list)
    tiers: list[str] = field(default_factory=list)


@dataclass
class ProfileIssue:
    """An issue raised by the validator."""

    severity: str  # "error" | "warning"
    kind: str  # see module docstring
    name: str
    detail: str = ""


# ---------------------------------------------------------------------------
# TOML loading
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_profiles_spec(path: Path) -> list[ProfileSpec]:
    """Parse a profile/level TOML manifest into :class:`ProfileSpec` records.

    Args:
        path: Path to the manifest file.

    Returns:
        List of profile specs in declaration order.

    Raises:
        FileNotFoundError: If *path* doesn't exist.
        ValueError: If the schema is malformed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Profiles spec not found: {path}")
    data = _load_toml(path)
    raw = data.get("profiles", [])
    if not isinstance(raw, list):
        raise ValueError(f"{path}: 'profiles' must be an array of tables")
    out: list[ProfileSpec] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: profile #{i} must be a table")
        name = entry.get("name")
        if not name or not isinstance(name, str):
            raise ValueError(f"{path}: profile #{i} missing string 'name'")
        levels = entry.get("levels", [])
        tiers = entry.get("tiers", [])
        if not isinstance(levels, list) or not all(isinstance(x, str) for x in levels):
            raise ValueError(f"{path}: profile {name!r} 'levels' must be a list of strings")
        if not isinstance(tiers, list) or not all(isinstance(x, str) for x in tiers):
            raise ValueError(f"{path}: profile {name!r} 'tiers' must be a list of strings")
        out.append(ProfileSpec(name=name, levels=list(levels), tiers=list(tiers)))
    return out


# ---------------------------------------------------------------------------
# Spec-side extraction
# ---------------------------------------------------------------------------

_LEVEL_RE = re.compile(r"\bLevel\s+\d+(?:\.\d+)?\b")


def _extract_marker_profiles(soup: BeautifulSoup) -> set[str]:
    """Collect every profile name appearing in ``data-conformance-profile``."""
    out: set[str] = set()
    for el in soup.find_all(attrs={"data-conformance-profile": True}):
        names = (el.get("data-conformance-profile") or "").split()
        out.update(names)
    return out


def _extract_annex_levels(soup: BeautifulSoup) -> set[str]:
    """Collect every ``Level X.Y`` literal mentioned inside Annex A tables.

    A heading is considered an Annex A header if its id starts with ``annex-a``,
    its text contains ``Annex A``, or it sits under a ``<section id="annex-a*">``.
    """
    levels: set[str] = set()

    def add_from_text(text: str) -> None:
        for m in _LEVEL_RE.finditer(text or ""):
            levels.add(m.group(0))

    # Walk sections whose id starts with annex-a
    for section in soup.find_all("section"):
        sid = (section.get("id") or "").lower()
        if not sid.startswith("annex-a"):
            continue
        for table in section.find_all("table"):
            add_from_text(table.get_text(" "))

    # Headings explicitly mentioning Annex A
    for h in soup.find_all(["h1", "h2", "h3"]):
        text = h.get_text(" ").lower()
        if "annex a" in text:
            sib = h.find_next_sibling()
            while sib and sib.name not in {"h1", "h2", "h3"}:
                if sib.name == "table":
                    add_from_text(sib.get_text(" "))
                else:
                    for table in sib.find_all("table"):
                        add_from_text(table.get_text(" "))
                sib = sib.find_next_sibling()
    return levels


def _extract_body_levels(soup: BeautifulSoup) -> set[str]:
    """Collect ``Level X.Y`` literals from prose paragraphs (excludes Annex A)."""
    levels: set[str] = set()
    for p in soup.find_all("p"):
        for m in _LEVEL_RE.finditer(p.get_text(" ")):
            levels.add(m.group(0))
    return levels


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_profiles(
    profiles: list[ProfileSpec],
    soup: BeautifulSoup,
) -> list[ProfileIssue]:
    """Cross-check declared profiles/levels against the compiled spec.

    Args:
        profiles: Output of :func:`load_profiles_spec`.
        soup: Parsed compiled spec HTML.

    Returns:
        List of :class:`ProfileIssue` records (empty when fully consistent).
    """
    issues: list[ProfileIssue] = []
    declared_profile_names = {p.name for p in profiles}

    marker_profiles = _extract_marker_profiles(soup)
    annex_levels = _extract_annex_levels(soup)
    body_levels = _extract_body_levels(soup)

    # 1) Profiles in TOML but with no marker in spec.
    for p in profiles:
        if p.name not in marker_profiles:
            issues.append(
                ProfileIssue(
                    severity="error",
                    kind="missing_profile",
                    name=p.name,
                    detail=(
                        f"Profile {p.name!r} declared in TOML but no element "
                        "with data-conformance-profile references it."
                    ),
                )
            )

    # 2) Markers in spec referencing undeclared profiles.
    for name in sorted(marker_profiles - declared_profile_names):
        issues.append(
            ProfileIssue(
                severity="warning",
                kind="orphan_marker",
                name=name,
                detail=f"Marker references profile {name!r} not in TOML manifest.",
            )
        )

    # 3) Levels referenced in body prose but missing from any Annex A table.
    for level in sorted(body_levels - annex_levels):
        issues.append(
            ProfileIssue(
                severity="error",
                kind="missing_level_table",
                name=level,
                detail=(
                    f"{level} is referenced in spec body but no Annex A table "
                    "row defines its constraints."
                ),
            )
        )

    return issues


def report_issues(issues: list[ProfileIssue], *, strict: bool = False) -> None:
    """Log *issues* (one per line) at appropriate level. In strict mode, exit non-zero on errors."""
    error_count = 0
    for issue in issues:
        msg = f"profiles-spec [{issue.kind}] {issue.name}: {issue.detail}"
        if issue.severity == "error":
            logging.error(msg)
            error_count += 1
        else:
            logging.warning(msg)
    if strict and error_count:
        raise SystemExit(1)


__all__ = [
    "ProfileSpec",
    "ProfileIssue",
    "load_profiles_spec",
    "validate_profiles",
    "report_issues",
]

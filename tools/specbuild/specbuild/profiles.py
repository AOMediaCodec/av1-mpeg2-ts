"""Build profiles: predefined flag combinations for common build scenarios."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Each profile maps to a dict of argparse attribute overrides.
# Values here override the CLI defaults when a profile is selected.
PROFILES = {
    "quick": {
        # Fast build — HTML only, no enhancements
        "_description": "Fast HTML-only build with no enhancements",
    },
    "draft": {
        # Working draft — equations, keywords, basic validation
        "_description": "Working draft with equations and keyword highlighting",
        "number_equations": True,
        "highlight_keywords": True,
        "validate_refs": True,
        "figure_table_tooltips": True,
        "syntax_tooltips": True,
    },
    "review": {
        # Review build — all quality checks, change bars
        "_description": "Review build with all quality checks and change bars",
        "number_equations": True,
        "highlight_keywords": True,
        "validate_refs": True,
        "check_terminology": True,
        "check_orphan_refs": True,
        "change_bars": "auto",
        "figure_table_tooltips": True,
        "syntax_tooltips": True,
    },
    "publication": {
        # Full publication build — everything enabled, PDF output
        "_description": "Full publication build with PDF, LOF, LOT, and all enhancements",
        "number_equations": True,
        "highlight_keywords": True,
        "validate_refs": True,
        "check_orphan_refs": True,
        "pdf": True,
        "lof": True,
        "lot": True,
        "toc_leaders": "css",
        "figure_table_tooltips": True,
        "syntax_tooltips": True,
        "pwa": True,
    },
    "publication-html": {
        # Same as publication but no PDF — for fast HTML iteration during development
        "_description": "Publication-grade HTML build without PDF (fast dev iteration)",
        "number_equations": True,
        "highlight_keywords": True,
        "validate_refs": True,
        "check_orphan_refs": True,
        "revision_history": True,
        "lof": True,
        "lot": True,
        "toc_leaders": "css",
        "figure_table_tooltips": True,
        "syntax_tooltips": True,
    },
    "pdf-draft": {
        # Quick PDF — minimal enhancements
        "_description": "Quick PDF generation with equations only",
        "number_equations": True,
        "pdf": True,
    },
    "pdf-final": {
        # Full PDF — all bells and whistles
        "_description": "Final PDF with all enhancements, LOF, LOT, revision history",
        "number_equations": True,
        "highlight_keywords": True,
        "revision_history": True,
        "pdf": True,
        "lof": True,
        "lot": True,
        "toc_leaders": "css",
    },
    # --- Standards profiles ---
    "iso-draft": {
        "_description": "ISO working draft with structure validation and boilerplate",
        "standards_flavor": "iso",
        "validate_standards": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "draft",
        "page_size": "a4",
    },
    "iso-publication": {
        "_description": "ISO publication-ready build with all checks, PDF, DOCX, and XML",
        "standards_flavor": "iso",
        "validate_standards": True,
        "standards_strict": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "format_bibliography": True,
        "conformance_requirements": True,
        "highlight_keywords": True,
        "number_equations": True,
        "validate_references": True,
        "pdf": True,
        "iso_docx": True,
        "isodoc_xml": True,
        "sts_xml": True,
        "page_size": "a4",
        "cover_page": True,
        "lof": True,
        "lot": True,
        "all_checks": True,
    },
    "iso-dis": {
        "_description": "ISO Draft International Standard submission",
        "standards_flavor": "iso",
        "standards_stage": "DIS",
        "validate_standards": True,
        "standards_strict": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "format_bibliography": True,
        "conformance_requirements": True,
        "highlight_keywords": True,
        "number_equations": True,
        "validate_references": True,
        "pdf": True,
        "iso_docx": True,
        "page_size": "a4",
        "cover_page": True,
    },
    "itu-draft": {
        "_description": "ITU-T working draft with structure validation",
        "standards_flavor": "itu-t",
        "validate_standards": True,
        "inject_boilerplate": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "draft",
        "page_size": "a4",
    },
    "ietf-draft": {
        "_description": "IETF Internet-Draft build",
        "standards_flavor": "ietf",
        "validate_standards": True,
        "highlight_keywords": True,
        "number_equations": True,
    },
    "ieee-draft": {
        "_description": "IEEE working draft with structure validation",
        "standards_flavor": "ieee",
        "validate_standards": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "draft",
        "page_size": "letter",
    },
    "3gpp-draft": {
        "_description": "3GPP working draft with structure validation",
        "standards_flavor": "3gpp",
        "validate_standards": True,
        "inject_boilerplate": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "draft",
        "page_size": "a4",
    },
    # --- Video codec profiles ---
    "iso-video-draft": {
        "_description": "ISO/IEC video codec working draft",
        "standards_flavor": "iso-video",
        "validate_standards": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "highlight_keywords": True,
        "number_equations": True,
        "validate_references": True,
        "watermark": "draft",
        "page_size": "a4",
    },
    "iso-video-publication": {
        "_description": "ISO/IEC video codec publication-ready build",
        "standards_flavor": "iso-video",
        "validate_standards": True,
        "standards_strict": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "format_bibliography": True,
        "conformance_requirements": True,
        "highlight_keywords": True,
        "number_equations": True,
        "validate_references": True,
        "pdf": True,
        "iso_docx": True,
        "isodoc_xml": True,
        "sts_xml": True,
        "page_size": "a4",
        "cover_page": True,
        "lof": True,
        "lot": True,
        "all_checks": True,
    },
    "aom-draft": {
        "_description": "Alliance for Open Media spec draft (AV1/AV2)",
        "standards_flavor": "aom",
        "validate_standards": True,
        "inject_boilerplate": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "draft",
        "page_size": "letter",
    },
    # --- Amendment profiles ---
    "iso-amendment": {
        "_description": "ISO/IEC amendment document",
        "standards_flavor": "iso",
        "amendment": True,
        "validate_standards": True,
        "inject_boilerplate": True,
        "iso_numbering": True,
        "highlight_keywords": True,
        "number_equations": True,
        "pdf": True,
        "iso_docx": True,
        "page_size": "a4",
        "cover_page": True,
    },
    "itu-amendment": {
        "_description": "ITU-T amendment/corrigendum document",
        "standards_flavor": "itu-t",
        "amendment": True,
        "validate_standards": True,
        "highlight_keywords": True,
        "number_equations": True,
        "watermark": "none",
        "page_size": "a4",
    },
}


def apply_profile(
    args: argparse.Namespace, profile_name: str, parser_defaults: dict[str, object] | None = None
) -> None:
    """Apply a build profile's settings to the parsed arguments.

    Profile settings only override default values — explicit CLI flags
    always take precedence.  Detection works by comparing the current
    value against the parser default; if they match, the user didn't
    set it explicitly.

    Args:
        args: The argparse.Namespace from parse_args().
        profile_name: Name of the profile to apply.
        parser_defaults: Dict of parser defaults (from parser.parse_args([])).
            If None, profile values are applied unconditionally.
    """
    if profile_name not in PROFILES:
        logging.error(f"Unknown profile: '{profile_name}'. Available: {', '.join(PROFILES.keys())}")
        raise SystemExit(1)

    profile = PROFILES[profile_name]
    desc = profile.get("_description", "")
    logging.info(f"Applying build profile: '{profile_name}' — {desc}")

    for key, value in profile.items():
        if key.startswith("_"):
            continue
        if not hasattr(args, key):
            continue
        # Only apply if the user didn't explicitly set this flag
        if parser_defaults is not None:
            current = getattr(args, key)
            default = parser_defaults.get(key)
            if current != default:
                logging.debug(
                    f"Profile '{profile_name}': skipping '{key}' (explicitly set to {current!r})"
                )
                continue
        setattr(args, key, value)


def list_profiles() -> str:
    """Return a formatted string listing all available profiles."""
    lines = ["Available build profiles:"]
    for name, profile in PROFILES.items():
        desc = profile.get("_description", "")
        flags = [k for k in profile if not k.startswith("_")]
        lines.append(f"  {name:14s} — {desc}")
        if flags:
            lines.append(f"{'':16s}   Enables: {', '.join(flags)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# TOML-based profile loading
# ---------------------------------------------------------------------------


def load_profiles_from_file(path: Path) -> dict[str, dict]:
    """Load build profiles from a TOML configuration file.

    The TOML file should have ``[profiles.<name>]`` sections::

        [profiles.ci]
        _description = "CI pipeline build"
        validate_refs_strict = true
        check_images_strict = true

    Args:
        path: Path to the TOML file.

    Returns:
        Dict mapping profile names to setting dicts.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        logging.warning(f"Profiles file not found: {path}")
        return {}

    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        logging.warning("Neither tomllib nor tomli available — cannot load profiles from TOML")
        return {}

    try:
        data = tomllib.loads(raw)
    except Exception as exc:
        logging.error(f"Failed to parse profiles TOML: {exc}")
        return {}

    profiles_section = data.get("profiles", {})
    if not isinstance(profiles_section, dict):
        logging.warning("Expected [profiles.<name>] sections in TOML file")
        return {}

    result: dict[str, dict] = {}
    for name, settings in profiles_section.items():
        if not isinstance(settings, dict):
            logging.warning(f"Profile '{name}' in TOML file is not a table; skipping")
            continue
        result[name] = settings

    logging.info(f"Loaded {len(result)} profile(s) from {path}")
    return result


def get_merged_profiles(custom_path: Path | None = None) -> dict[str, dict]:
    """Return built-in profiles merged with custom profiles from a TOML file.

    Custom profiles override built-in profiles with the same name.
    New names are added.

    Args:
        custom_path: Path to a TOML file.  If None, only built-ins are returned.

    Returns:
        Merged profile dict.
    """
    merged = dict(PROFILES)
    if custom_path is not None:
        custom = load_profiles_from_file(custom_path)
        merged.update(custom)
    return merged

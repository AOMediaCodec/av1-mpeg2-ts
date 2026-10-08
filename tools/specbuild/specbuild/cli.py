"""Shared CLI argument definitions and parser construction.

The :func:`add_common_args` function adds arguments that are shared across
build modes (single-page and multipage).  :func:`build_parser` constructs
the full argument parser for the main ``compile.py`` driver.
"""

from __future__ import annotations

import argparse
import logging
import sys
from argparse import BooleanOptionalAction
from pathlib import Path

#: Default path to the manifest file that controls chapter ordering.
DEFAULT_MANIFEST_PATH = "bikeshed/manifest.txt"

#: Valid Bikeshed ``--die-on`` error levels.
BIKESHED_DIE_ON_CHOICES = [
    "nothing",
    "message",
    "lint",
    "warning",
    "link-error",
    "fatal",
]


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """Add CLI arguments shared across build modes (single-page and multipage).

    The following argument groups are added:

    * **Config** — ``--config``
    * **Build identity** — ``--branch``, ``--date``
    * **Source options** — ``--sdl``, ``--compact``, ``--remove_editor_notes``,
      ``--striped_code_blocks``, ``--manifest``, ``--no-manifest``,
      ``--bikeshed-die-on``
    * **Logging** — ``--log_level``

    Args:
        parser: The argument parser to extend.
    """
    # --- Config ---
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a specbuild.toml config file. "
        "If not given, looks for specbuild.toml or "
        "[tool.specbuild] in pyproject.toml.",
    )

    # --- Build identity ---
    parser.add_argument("--branch", type=str, help="Override auto-detected branch name.")
    parser.add_argument("--date", type=str, help="Override commit date (YYYY-MM-DD).")

    # --- Source options ---
    parser.add_argument(
        "--sdl",
        action="store_false",
        dest="convert_sdl",
        help="Disable SDL syntax table conversion (SDL tables are enabled by default).",
    )
    parser.add_argument(
        "--compact", action="store_true", help="Extract Section 9 tables to .h files."
    )
    parser.add_argument("--remove_editor_notes", action="store_true", help="Remove editor notes.")
    parser.add_argument(
        "--striped_code_blocks",
        action="store_true",
        help="Convert code blocks to tables with alternating row colors.",
    )
    parser.add_argument(
        "--auto-indent-code",
        action=BooleanOptionalAction,
        default=False,
        help="Auto-indent C/C++ code blocks based on brace depth.",
    )
    parser.add_argument(
        "--line-anchors",
        action=BooleanOptionalAction,
        default=False,
        help="Add deep-linkable line number anchors to highlighted code blocks.",
    )
    parser.add_argument(
        "--manifest",
        nargs="?",
        const=DEFAULT_MANIFEST_PATH,
        default=DEFAULT_MANIFEST_PATH,
        metavar="FILE",
        help="Manifest file to control chapter ordering "
        f"(default: {DEFAULT_MANIFEST_PATH} if it exists).",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Disable manifest; fall back to numeric filename ordering.",
    )
    parser.add_argument(
        "--include-sections",
        type=str,
        default=None,
        metavar="PATTERNS",
        help="Comma-separated list of section filename patterns to include "
        "(e.g. 'header,scope,terms,annex_*'). "
        "Only matching .bs files are merged. Supports shell-style globs.",
    )
    parser.add_argument(
        "--exclude-sections",
        type=str,
        default=None,
        metavar="PATTERNS",
        help="Comma-separated list of section filename patterns to exclude "
        "(e.g. 'annex_*,bibliography'). "
        "Matching .bs files are skipped during merge. Supports shell-style globs.",
    )
    parser.add_argument(
        "--bikeshed-die-on",
        type=str,
        default="nothing",
        choices=BIKESHED_DIE_ON_CHOICES,
        metavar="LEVEL",
        help="Bikeshed error level that causes a build failure (default: nothing).",
    )

    # --- Logging ---
    parser.add_argument(
        "--log_level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO).",
    )


def resolve_manifest(args: argparse.Namespace) -> Path | None:
    """Validate and return the manifest path from parsed CLI args.

    Returns a validated :class:`Path` to the manifest file, or ``None``
    if the manifest is disabled, not specified, or the default is missing.
    Exits with an error if an explicitly-provided manifest path does not exist.

    Args:
        args: Parsed CLI namespace (must contain ``no_manifest`` and
              ``manifest`` attributes from :func:`add_common_args`).

    Returns:
        Resolved manifest path, or ``None``.
    """
    if args.no_manifest or args.manifest is None:
        return None

    # When using the default manifest path, resolve against CONFIG.bikeshed_dir
    # so that --config with a different bikeshed_dir finds the right manifest.
    if args.manifest == DEFAULT_MANIFEST_PATH:
        from specbuild.config import CONFIG

        config_manifest = Path(CONFIG.bikeshed_dir) / "manifest.txt"
        if config_manifest.exists():
            if str(config_manifest) != DEFAULT_MANIFEST_PATH:
                logging.info(f"Using manifest from configured bikeshed_dir: {config_manifest}")
            return config_manifest
        logging.debug("No manifest file found; using numeric filename ordering")
        return None

    manifest_path = Path(args.manifest)
    if manifest_path.exists():
        return manifest_path

    logging.error(f"Manifest file not found: {manifest_path}")
    sys.exit(1)


#: Quality-check argument names enabled by ``--all-checks``.
_ALL_CHECK_FLAGS: list[str] = [
    "validate_refs",
    "validate_sdl_refs",
    "check_tables",
    "check_images",
    "check_links",
    "check_duplicates",
    "check_dfn",
    "check_orphan_refs",
    "check_referenceable",
    "editorial",
    "accessibility_audit",
    "spellcheck",
    "check_terminology",
    "validate_standards",
    "validate_references",
    "completeness",
    "validate_rfc2119",
    "check_xpart_refs",
]


def expand_all_checks(args: argparse.Namespace) -> None:
    """Expand ``--all-checks`` into individual quality-check flags.

    Sets every quality-check boolean on *args* to ``True`` unless the
    user explicitly provided it on the command line.  This allows
    ``--all-checks --no-spellcheck`` style overrides (argparse processes
    flags left-to-right, but since we only set falsy values, explicit
    ``True`` values from the CLI are preserved).
    """
    if not getattr(args, "all_checks", False):
        return
    for flag in _ALL_CHECK_FLAGS:
        if not getattr(args, flag, False):
            setattr(args, flag, True)


# ---------------------------------------------------------------------------
# Full parser for compile.py
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the CLI argument parser for ``compile.py``.

    This defines every flag accepted by the main build driver, organized
    into logical groups: build workflow, diff, PDF/export, quality checks,
    document enhancements, output, and multipage.
    """
    parser = argparse.ArgumentParser(
        description="A helper script to build a Bikeshed specification."
    )

    # --- Shared args (config, build identity, source options, logging) ---
    add_common_args(parser)

    # --- Build workflow ---
    parser.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="Apply a build profile (predefined flag set). "
        "Use --list-profiles to see available profiles.",
    )
    parser.add_argument(
        "--list-profiles", action="store_true", help="List available build profiles and exit."
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Print system diagnostic report (dependency status, environment) and exit.",
    )
    parser.add_argument(
        "--bib-enrich",
        metavar="FILE",
        help="Auto-enrich a bibliography file (TOML/YAML) using DOI/arXiv lookups.",
    )
    parser.add_argument(
        "--provenance",
        action="store_true",
        help="Write provenance.json (input hashes + tool versions) next to build output.",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available spec templates and exit.",
    )
    parser.add_argument(
        "--new-from-template",
        type=str,
        default=None,
        metavar="NAME",
        help="Create a new spec project from a template.",
    )
    parser.add_argument(
        "--help-features", action="store_true", help="List all available build features and exit."
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Skip bikeshed compilation if source files are unchanged since the last build.",
    )
    parser.add_argument(
        "--timing", action="store_true", help="Show a timing report for each build step."
    )
    parser.add_argument(
        "--watch", action="store_true", help="Watch for source file changes and auto-rebuild."
    )
    parser.add_argument(
        "--watch-interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Polling interval for watch mode (default: 1.0s).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Build, serve on localhost, and watch for changes (implies --watch).",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=8080,
        metavar="PORT",
        help="Port for --serve (default: 8080).",
    )
    parser.add_argument(
        "--parallel-outputs",
        action=BooleanOptionalAction,
        default=True,
        help="Run independent output steps (PDF, DOCX, standalone, "
        "image optimization) concurrently (default: enabled; "
        "use --no-parallel-outputs to run serially).",
    )

    # --- Diff options ---
    parser.add_argument("--diff", action="store_true", help="Create diff")
    parser.add_argument(
        "--diff_viewer",
        action="store_true",
        help="Generate three-pane diff viewer (implies --diff)",
    )
    parser.add_argument(
        "--diff_explorer",
        action="store_true",
        help="Generate interactive diff explorer with search, "
        "filtering, and change navigation (implies --diff)",
    )
    parser.add_argument("--diff_sha", type=str, help="SHA to use when creating a diff.")
    parser.add_argument(
        "--no_clone", action="store_true", help="Don't clone the repo for the diff mode."
    )

    # --- PDF options ---
    # WeasyPrint is the default engine: no browser required, runs in CI/CD,
    # produces accurate TOC page numbers via box-tree traversal.  Chrome is
    # opt-in for cases where the headless-browser path is preferred.
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Generate PDF (WeasyPrint by default; pass --chrome-pdf to use Chrome instead).",
    )
    parser.add_argument(
        "--weasyprint",
        action="store_true",
        help="Force WeasyPrint engine.  Equivalent to --pdf when --chrome-pdf is not set. "
        "Requires: pip install weasyprint (plus Cairo/Pango system libraries).",
    )
    parser.add_argument(
        "--chrome-pdf",
        action="store_true",
        help="Use Chrome headless for PDF generation instead of WeasyPrint. "
        "Requires Chrome/Chromium installed on PATH.",
    )
    parser.add_argument(
        "--no-pdf",
        dest="no_pdf",
        action="store_true",
        help="Skip PDF generation, overriding any --pdf/--weasyprint/--pdfa "
        "set by a profile. Useful for fast HTML iteration with publication-grade profiles.",
    )
    parser.add_argument(
        "--docx",
        action="store_true",
        help="Export specification as a Word document (.docx). "
        "Requires: pandoc on PATH, pip install python-docx",
    )
    parser.add_argument(
        "--docx-template",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a Word reference template (.docx) for styling the exported document.",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Generate a standalone HTML file with all CSS, JS, "
        "and images inlined as data URIs. Produces a single "
        "self-contained file for easy distribution.",
    )
    parser.add_argument(
        "--page-size",
        choices=["letter", "a4", "legal"],
        default="letter",
        help="PDF page size: 'letter' (default), 'a4', or 'legal'.",
    )
    parser.add_argument(
        "--pdf-font-increase",
        type=int,
        default=0,
        metavar="N",
        help="Increase PDF font sizes by N points (1-3 recommended).",
    )
    parser.add_argument(
        "--toc-leaders",
        choices=["none", "css", "table"],
        default="css",
        help="TOC leader dot style: 'css' (default), 'none', or 'table'.",
    )
    parser.add_argument(
        "--lof", action="store_true", help="Generate List of Figures with page numbers in PDF."
    )
    parser.add_argument(
        "--no-lof", action="store_true", help="Disable List of Figures even if manifest enables it."
    )
    parser.add_argument(
        "--lot", action="store_true", help="Generate List of Tables with page numbers in PDF."
    )
    parser.add_argument(
        "--no-lot", action="store_true", help="Disable List of Tables even if manifest enables it."
    )
    parser.add_argument(
        "--equation-font",
        choices=[
            "default",
            "stix",  # STIX Two Math — gold standard for scientific/standards docs
            "latin-modern",  # Latin Modern Math — classic TeX look, excellent quality
            "xits",  # XITS Math — open-source STIX variant
            "libertinus",  # Libertinus Math — elegant open-source font
            "tex-gyre-termes",  # TeX Gyre Termes Math — Times-compatible, open-source
            "tex-gyre-pagella",  # TeX Gyre Pagella Math — Palatino-style, open-source
            "cambria",  # Cambria Math — Microsoft system font
            "times-new-roman",  # Times New Roman — system fallback
            "georgia",  # Georgia — system fallback
        ],
        default="stix",
        help=(
            "Font for mathematical equations in PDF. "
            "Recommended: stix (best for technical/standards docs), "
            "latin-modern (classic TeX), tex-gyre-termes (Times-style open-source). "
            "The dedicated math fonts (stix, latin-modern, xits, libertinus, tex-gyre-*) "
            "require the font to be installed on the system."
        ),
    )
    parser.add_argument(
        "--equation-scale",
        type=float,
        default=1.0,
        metavar="SCALE",
        help="Scale factor for equations (1.0 = same as text, 1.2 = 120%%).",
    )
    parser.add_argument(
        "--optimize-pdf",
        action="store_true",
        help="Optimize PDF with Ghostscript after generation "
        "(font subsetting, image deduplication, stream compression). "
        "Also disables PDF tagging (implies --no-pdf-tags). "
        "Requires: gs (Ghostscript) on PATH.",
    )
    parser.add_argument(
        "--no-pdf-tags",
        action="store_true",
        help="Disable PDF accessibility tagging in Chrome output. "
        "Removes the StructElem tree and marked-content operators, "
        "reducing raw PDF size by ~50-60%% for large specs.",
    )
    parser.add_argument(
        "--section-headers",
        action="store_true",
        help="Add running section titles in PDF page headers. Best results with --weasyprint.",
    )
    parser.add_argument(
        "--watermark",
        type=str,
        default="bikeshed",
        metavar="TEXT",
        help="Watermark mode. 'bikeshed' (default) uses "
        "Bikeshed's built-in watermark from the spec "
        "status. 'none' removes all watermarks. "
        "Presets: 'draft', 'confidential', 'review', "
        "'obsolete', or any custom text.",
    )
    parser.add_argument(
        "--cover-page", action="store_true", help="Add a styled cover page to the PDF."
    )
    parser.add_argument(
        "--cover-title",
        type=str,
        default=None,
        metavar="TITLE",
        help="Custom title for the cover page.",
    )
    parser.add_argument(
        "--cover-subtitle",
        type=str,
        default=None,
        metavar="TEXT",
        help="Subtitle for the cover page.",
    )
    parser.add_argument(
        "--cover-doc-number",
        type=str,
        default=None,
        metavar="NUM",
        help="Document number for the cover page.",
    )
    parser.add_argument(
        "--cover-organization",
        type=str,
        default=None,
        metavar="ORG",
        help="Organization name for the cover page.",
    )
    parser.add_argument(
        "--cover-logo",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a logo image for the cover page.",
    )
    parser.add_argument(
        "--page-numbers",
        nargs="?",
        const="dual",
        default="dual",
        metavar="STYLE",
        choices=["dual", "arabic", "none"],
        help="Page numbering style: 'dual' (roman front "
        "matter, arabic body — the default), 'arabic' "
        "(arabic throughout), or 'none' (no page "
        "numbers).",
    )

    # --- Quality & validation options ---
    parser.add_argument(
        "--all-checks",
        action="store_true",
        help="Enable all quality checks (equivalent to specifying every --check-* and "
        "--validate-* flag plus --editorial, --accessibility-audit, --spellcheck, "
        "and --check-terminology).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Skip compilation and run all quality checks against an existing build output. "
        "Exits with code 1 if any checks report issues. "
        "Use --validate-path to specify the HTML file; "
        "otherwise the most-recent output directory is used.",
    )
    parser.add_argument(
        "--validate-path",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to the compiled index.html to validate (used with --validate-only). "
        "Defaults to auto-detecting the most-recent output directory.",
    )
    parser.add_argument(
        "--validate-refs",
        action="store_true",
        help="Validate that all internal cross-references resolve.",
    )
    parser.add_argument(
        "--validate-refs-strict",
        action="store_true",
        help="Like --validate-refs but exit with error on broken refs.",
    )
    parser.add_argument(
        "--validate-sdl-refs",
        action="store_true",
        help="Validate that function calls in SDL tables reference defined SDL elements.",
    )
    parser.add_argument(
        "--validate-sdl-refs-strict",
        action="store_true",
        help="Like --validate-sdl-refs but exit with error on unresolved references.",
    )
    parser.add_argument(
        "--check-sdl-syntax",
        action="store_true",
        help="Validate SDL code blocks against the MPEG SDL grammar "
        "(via @mpeggroup/mpeg-sdl-parser).  Requires Node.js + "
        "`npm install` in the SpecBuild root.",
    )
    parser.add_argument(
        "--strict-sdl-syntax",
        action="store_true",
        help="Like --check-sdl-syntax but exit with error on any SDL syntax error.",
    )
    parser.add_argument(
        "--check-images",
        action="store_true",
        help="Check for broken image references in the compiled HTML.",
    )
    parser.add_argument(
        "--check-images-strict",
        action="store_true",
        help="Like --check-images but exit with error on broken images.",
    )
    parser.add_argument(
        "--accessibility-audit",
        action="store_true",
        help="Run WCAG accessibility audit on the compiled HTML.",
    )
    parser.add_argument(
        "--accessibility-audit-strict",
        action="store_true",
        help="Like --accessibility-audit but exit with error on accessibility errors.",
    )
    parser.add_argument(
        "--check-dfn",
        action="store_true",
        help="Check that all <dfn> terms are referenced and "
        "no references point to undefined definitions.",
    )
    parser.add_argument(
        "--check-dfn-strict",
        action="store_true",
        help="Like --check-dfn but exit with error on undefined references.",
    )
    parser.add_argument(
        "--change-summary",
        nargs="?",
        const="auto",
        default=None,
        metavar="REF",
        help="Generate a summary of spec changes since REF (default: auto-detect main branch).",
    )
    parser.add_argument(
        "--optimize-images",
        action="store_true",
        help="Optimize PNG and SVG images in the build output.",
    )
    parser.add_argument(
        "--check-links",
        action="store_true",
        help="Check that external URLs in the spec are reachable.",
    )
    parser.add_argument(
        "--check-internal-links",
        action="store_true",
        help="Check that internal #fragment links resolve to existing IDs.",
    )
    parser.add_argument(
        "--autolink-req-ids",
        action="store_true",
        help="Auto-link bare REQ-ID references in prose to their definitions.",
    )
    parser.add_argument(
        "--strip-reviewer-notes",
        action="store_true",
        help="Strip reviewer-only notes/comments before output (use for publication).",
    )
    parser.add_argument(
        "--section-permalinks",
        action="store_true",
        help="Add clickable § permalink anchors to section headings.",
    )
    parser.add_argument(
        "--check-links-strict",
        action="store_true",
        help="Like --check-links but exit with error on broken links.",
    )
    parser.add_argument(
        "--check-links-allowlist",
        nargs="*",
        default=None,
        metavar="PREFIX",
        help="URL prefixes to skip during link checking.",
    )
    parser.add_argument(
        "--spec-metrics",
        action="store_true",
        help="Collect and output specification metrics (word count, sections, tables, etc.).",
    )
    parser.add_argument(
        "--search-index",
        action="store_true",
        help="Generate a client-side search index with Ctrl+K/Cmd+K overlay UI.",
    )
    parser.add_argument(
        "--check-tables",
        action="store_true",
        help="Validate table structure (column counts, thead/tbody, scope, captions).",
    )
    parser.add_argument(
        "--check-tables-strict",
        action="store_true",
        help="Like --check-tables but exit with error on issues.",
    )
    parser.add_argument(
        "--check-referenceable",
        action="store_true",
        help="Check that tables have <caption id> and figures have id + <figcaption>.",
    )
    parser.add_argument(
        "--check-referenceable-strict",
        action="store_true",
        help="Like --check-referenceable but exit with error on issues.",
    )
    parser.add_argument(
        "--spellcheck", action="store_true", help="Run domain-aware spelling/terminology check."
    )
    parser.add_argument(
        "--spellcheck-strict",
        action="store_true",
        help="Like --spellcheck but exit with error on issues.",
    )
    parser.add_argument(
        "--spellcheck-dict",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a custom dictionary file for spell checking.",
    )
    parser.add_argument(
        "--pdfa", action="store_true", help="Generate a PDF/A-compliant output with metadata."
    )
    parser.add_argument(
        "--xref-report",
        action="store_true",
        help="Generate a cross-reference report showing inter-section link relationships.",
    )
    parser.add_argument(
        "--compliance-matrix",
        action="store_true",
        help="Extract RFC 2119 normative statements into a structured compliance matrix.",
    )
    parser.add_argument(
        "--attribution",
        action="store_true",
        help="Generate contributor attribution from git blame.",
    )
    parser.add_argument(
        "--stability",
        action="store_true",
        help="Analyze section stability and inject badges for new/active sections.",
    )
    parser.add_argument(
        "--check-duplicates",
        action="store_true",
        help="Detect near-duplicate paragraphs across sections.",
    )
    parser.add_argument(
        "--check-duplicates-strict",
        action="store_true",
        help="Like --check-duplicates but exit with error on duplicates found.",
    )
    parser.add_argument(
        "--duplicate-threshold",
        type=float,
        default=0.7,
        metavar="FLOAT",
        help="Similarity threshold for duplicate detection (0.0–1.0, default: 0.7).",
    )
    parser.add_argument(
        "--latex", action="store_true", help="Export specification as a LaTeX document."
    )
    parser.add_argument(
        "--editorial",
        action="store_true",
        help="Run editorial consistency check (compound words, dfn capitalization).",
    )
    parser.add_argument(
        "--editorial-strict",
        action="store_true",
        help="Like --editorial but exit with error on issues.",
    )
    parser.add_argument(
        "--editorial-rules",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a TOML file with custom editorial rules.",
    )
    parser.add_argument(
        "--dfn-index",
        action="store_true",
        help="Generate a definition cross-reference index (glossary with usage mapping).",
    )
    parser.add_argument(
        "--pr-summary",
        nargs="?",
        const="auto",
        default=None,
        metavar="REF",
        help="Generate a PR summary against REF (default: auto-detect main branch).",
    )
    parser.add_argument(
        "--regression",
        nargs="?",
        const="auto",
        default=None,
        metavar="PATH",
        help="Build regression check. With a PATH, compares "
        "against that HTML file. Without a path, uses "
        "the saved baseline (.specbuild_baseline.json).",
    )
    parser.add_argument(
        "--regression-strict",
        action="store_true",
        help="Exit with error if structural regressions detected.",
    )
    parser.add_argument(
        "--save-baseline",
        action="store_true",
        help="Save a structural baseline snapshot of the "
        "current build for future --regression checks.",
    )
    parser.add_argument(
        "--impact",
        action="store_true",
        help="Compare current build against a previous build and report impact by section type.",
    )
    parser.add_argument(
        "--impact-base",
        type=str,
        default=None,
        metavar="PATH",
        help="Base HTML to compare against for --impact (defaults to latest previous build dir).",
    )
    parser.add_argument(
        "--completeness",
        action="store_true",
        help="Check spec for TODO/TBD markers, empty sections, and unfilled editor notes.",
    )
    parser.add_argument(
        "--completeness-strict",
        action="store_true",
        help="Exit 1 if any error-severity completeness issues are found.",
    )
    parser.add_argument(
        "--slides",
        action="store_true",
        help="Generate a meeting contribution presentation (.pptx) from the built spec.",
    )
    parser.add_argument(
        "--slides-sections",
        type=str,
        default=None,
        metavar="IDS",
        help="Comma-separated section IDs to include in --slides (default: all top-level).",
    )
    parser.add_argument(
        "--relaton-enrich",
        action="store_true",
        help="Enrich bibliography entries with structured metadata from the Relaton API.",
    )
    parser.add_argument(
        "--relaton-data-dir",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a local relaton-data repository for offline bibliography enrichment.",
    )
    parser.add_argument(
        "--ballot-comments",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a ballot comment XLSX or CSV file to generate an interactive tracker.",
    )
    parser.add_argument(
        "--contribution-cover",
        action="store_true",
        help="Inject a contribution cover page using [standards.contribution] TOML config.",
    )
    parser.add_argument(
        "--xpart-manifest",
        action="store_true",
        help="Write xpart_refs.json listing all outgoing cross-part references.",
    )
    parser.add_argument(
        "--requirements-json",
        action="store_true",
        help="Export requirements manifest JSON for build-to-build diffing (with --requirement-ids).",
    )
    parser.add_argument(
        "--tbx-export",
        action="store_true",
        help="Export Terms and Definitions as ISO 30042 TBX XML alongside the HTML output.",
    )
    parser.add_argument(
        "--boilerplate-lang",
        default="en",
        metavar="LANG",
        choices=["en", "fr", "both"],
        help="Boilerplate language: 'en' (default), 'fr' (French only), or 'both' (bilingual grid).",
    )
    parser.add_argument(
        "--boilerplate-stage",
        default=None,
        metavar="STAGE",
        help="Document stage for stage-specific boilerplate templates (e.g. 'wd', 'cd', 'dis', 'fdis', 'is').",
    )
    parser.add_argument(
        "--callouts",
        action="store_true",
        help="Process code callout markers (/* <1> */ patterns and <co> elements).",
    )
    parser.add_argument(
        "--subfigures",
        action="store_true",
        help="Process compound figures: inject (a)/(b)/(c) subfigure labels.",
    )
    parser.add_argument(
        "--admonitions",
        action="store_true",
        help="Process admonition blocks (caution/warning/important/tip divs): inject labels and CSS.",
    )
    parser.add_argument(
        "--rfc-xml",
        action="store_true",
        help="Export RFC 7991 XML (IETF RFC v3 format) alongside the HTML output.",
    )
    parser.add_argument(
        "--ats-export",
        action="store_true",
        help="Export an Abstract Test Suite (ATS) XML for OGC/ISO conformance specifications.",
    )
    parser.add_argument(
        "--cite-macros",
        action="store_true",
        help="Process {{cite:DocID}} macros into bibliography anchor links.",
    )
    parser.add_argument(
        "--typography",
        action="store_true",
        help="Apply smart typography: curly quotes, em-dashes, ellipsis, multiplication sign.",
    )
    parser.add_argument(
        "--french-spacing",
        action="store_true",
        help="Insert non-breaking spaces before French punctuation (use with --typography).",
    )
    parser.add_argument(
        "--math-symbols",
        action="store_true",
        help="Replace ASCII math approximations with Unicode symbols (<=, >=, ->, !=, etc.).",
    )
    parser.add_argument(
        "--passthrough",
        action="store_true",
        help="Inject raw HTML/XML content from data-passthrough elements.",
    )
    parser.add_argument(
        "--term-links",
        action="store_true",
        help="Auto-link term occurrences to their definition anchors within the document.",
    )
    parser.add_argument(
        "--smart-xrefs",
        action="store_true",
        help="Rewrite generic cross-reference anchor text to include Figure/Table/Clause labels.",
    )
    parser.add_argument(
        "--iso-body-numbering",
        action="store_true",
        help="Apply sequential body figure/table numbering (Figure 1, 2, …; Annex A: Figure A.1, …).",
    )
    parser.add_argument(
        "--inject-aria",
        action="store_true",
        help="Inject WCAG 2.1 ARIA landmark roles on structural HTML elements.",
    )
    parser.add_argument(
        "--epub",
        action="store_true",
        help="Export specification as an EPUB3 package for e-reader distribution.",
    )
    parser.add_argument(
        "--errata",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a CSV or JSON errata file; inject errata markers and generate HTML tracker.",
    )
    parser.add_argument(
        "--bibformat-normalize",
        action="store_true",
        help="Normalize and deduplicate bibliography entries per the active flavor's citation style.",
    )
    parser.add_argument(
        "--pseudocode",
        action="store_true",
        help="Style pseudocode/algorithm blocks with ISO-style line numbering and formatting.",
    )
    parser.add_argument(
        "--figure-sources",
        action="store_true",
        help="Style 'Source: ...' attribution text in figure captions.",
    )
    parser.add_argument(
        "--doc-language",
        type=str,
        default="en",
        metavar="LANG",
        help="Document language for boilerplate labels (en, fr, de, zh, ja, ko, ru, ar, es). Default: en.",
    )
    parser.add_argument(
        "--inject-rtl",
        action="store_true",
        help="Inject RTL CSS for right-to-left document languages (Arabic, Hebrew).",
    )
    parser.add_argument(
        "--mathml-a11y",
        action="store_true",
        help="Add ARIA labels and display attributes to MathML elements for accessibility.",
    )
    parser.add_argument(
        "--line-numbers",
        choices=["none", "gutter", "inline"],
        default="none",
        help="Add line numbers to source code blocks: 'gutter' (CSS margin) or 'inline' (text prefix).",
    )
    parser.add_argument(
        "--copy-code-buttons",
        action="store_true",
        help="Add copy-to-clipboard buttons to source code blocks.",
    )
    parser.add_argument(
        "--validate-rfc2119",
        action="store_true",
        help="Validate RFC 2119 keyword usage (MUST, SHOULD, etc.) in normative/informative sections.",
    )
    parser.add_argument(
        "--validate-rfc2119-strict",
        action="store_true",
        help="Like --validate-rfc2119 but exit with error on error-severity issues.",
    )
    parser.add_argument(
        "--math-lint",
        action="store_true",
        help="Lint math/equation fragments for paren balance and symbol consistency.",
    )
    parser.add_argument(
        "--math-lint-strict",
        action="store_true",
        help="Like --math-lint but exit with error if any math issues are found.",
    )
    parser.add_argument(
        "--relaton-export",
        nargs="?",
        const="json",
        default=None,
        metavar="FORMAT",
        choices=["json", "xml"],
        help="Export document as Relaton JSON or XML for Metanorma interoperability.",
    )
    parser.add_argument(
        "--relaton-bib",
        action="store_true",
        default=False,
        help="Export bibliography as a Relaton XML collection (relaton-bibliography.xml).",
    )
    parser.add_argument(
        "--error-log",
        action="store_true",
        default=False,
        help="Write build warnings and errors to <output>/<spec>.err.html (equivalent to Metanorma .err.html).",
    )
    parser.add_argument(
        "--profiles-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to a TOML file with custom build profiles.",
    )
    parser.add_argument(
        "--build-report",
        nargs="?",
        const="html",
        default=None,
        metavar="FORMAT",
        choices=["html", "json", "both"],
        help="Generate a build report. Format: 'html' (default), 'json', or 'both'.",
    )
    parser.add_argument(
        "--number-equations",
        action=BooleanOptionalAction,
        default=True,
        help="Automatically number display equations as (section.N). Enabled by default.",
    )
    parser.add_argument(
        "--change-bars",
        nargs="?",
        const="auto",
        default=None,
        metavar="REF",
        help="Add change bars marking text changed since REF "
        "(default: auto-detect latest tag or main).",
    )
    parser.add_argument(
        "--table-of-changes",
        nargs="?",
        const="auto",
        default=None,
        metavar="REF",
        help="Insert a Table of Changes listing modified sections "
        "since REF (default: auto-detect latest tag or main).",
    )
    parser.add_argument(
        "--toc-depth",
        type=int,
        default=None,
        metavar="N",
        help="Table of contents depth (1–6). Overrides config toc_depth (default: 3).",
    )
    parser.add_argument(
        "--svg-accessibility",
        action="store_true",
        help="Add ARIA roles, title/desc, and viewBox normalization to inline SVG elements.",
    )
    parser.add_argument(
        "--note-numbers",
        action="store_true",
        help="Number NOTE and EXAMPLE blocks sequentially per top-level clause (NOTE 1, NOTE 2…).",
    )
    parser.add_argument(
        "--abbreviations",
        action="store_true",
        help="Auto-extract abbreviations from <abbr> tags and inline patterns, populate Abbreviations section.",
    )
    parser.add_argument(
        "--checklists",
        action="store_true",
        help="Convert [ ] / [x] checklist items to HTML checkboxes.",
    )
    parser.add_argument(
        "--contributor-block",
        action="store_true",
        help="Render structured contributor/editor table from document metadata.",
    )
    parser.add_argument(
        "--code-attribution",
        action="store_true",
        help="Render source attribution for code blocks with data-source or preceding source paragraph.",
    )
    parser.add_argument(
        "--html-lang",
        action="store_true",
        help="Inject lang attribute on <html> element from document language metadata.",
    )
    parser.add_argument(
        "--term-crossrefs",
        action="store_true",
        help="Auto-link first occurrence of defined terms in body text to their definitions.",
    )
    parser.add_argument(
        "--autolink",
        action="store_true",
        help="Auto-link 'Clause N', 'Table N', 'Figure N', 'Annex A' references to anchors.",
    )
    parser.add_argument(
        "--seo",
        action="store_true",
        help="Inject SEO meta tags (og:title, og:description, twitter:card, keywords, canonical).",
    )
    parser.add_argument(
        "--code-lang-labels",
        action="store_true",
        help="Inject language labels above code blocks (Python, C++, JavaScript, etc.).",
    )
    parser.add_argument(
        "--print-css",
        action="store_true",
        help="Inject print-optimised CSS (page breaks, widows/orphans, nav hiding).",
    )
    parser.add_argument(
        "--bib-links",
        action="store_true",
        help="Inject hyperlinks for DOI, RFC, Internet-Draft, and W3C spec identifiers in bibliography.",
    )
    parser.add_argument(
        "--unit-spacing",
        action="store_true",
        help="Insert non-breaking spaces between numbers and SI/technical unit symbols.",
    )
    parser.add_argument(
        "--verification-matrix",
        action="store_true",
        help="Generate a conformance verification matrix linking requirements to verification methods.",
    )
    parser.add_argument(
        "--testvector-manifest",
        metavar="FILE",
        help="Path to test-vector manifest TOML; validates files+hashes and emits coverage report.",
    )
    parser.add_argument(
        "--testvector-no-hashes",
        action="store_true",
        help="Skip sha256 verification when validating the test-vector manifest.",
    )
    parser.add_argument(
        "--codesync",
        nargs=2,
        metavar=("CPP_FILE", "OUTPUT_HTML"),
        help="Compare C++ syntax-function macros against SDL tables in the spec; "
        "emit HTML diff report.",
    )
    parser.add_argument(
        "--syntax-diff",
        nargs=2,
        metavar=("PREV_BS", "CURR_BS"),
        default=None,
        help="Bitstream-syntax crosswalk between two SDL-tagged spec sources. "
        "Writes syntax_diff.html and syntax_diff.json into the build target dir.",
    )
    parser.add_argument(
        "--export-sdl",
        type=str,
        default=None,
        metavar="OUTPUT_DIR",
        help="One-shot: extract SDL syntax tables from the compiled HTML and "
        "emit C++ decoder skeletons into OUTPUT_DIR (one .h per syntax function "
        "plus decoder_stubs.cpp). Exits after running.",
    )
    parser.add_argument(
        "--profiles-spec",
        type=str,
        default=None,
        metavar="FILE",
        help="TOML manifest of profiles/levels/tiers; cross-checked against "
        "data-conformance-profile markers and Annex A tables in the soup.",
    )
    parser.add_argument(
        "--profiles-spec-strict",
        action="store_true",
        help="Like --profiles-spec but exit non-zero on validation errors.",
    )
    parser.add_argument(
        "--new-clause",
        nargs=2,
        metavar=("TYPE", "TITLE"),
        default=None,
        help="One-shot: emit a clause-level Bikeshed snippet of TYPE "
        "(syntax|process|profile|sei|annex). Prints to stdout unless "
        "--new-clause-file is given. Exits after running.",
    )
    parser.add_argument(
        "--new-clause-file",
        type=str,
        default=None,
        metavar="PATH",
        help="Write the --new-clause output to PATH instead of stdout.",
    )
    parser.add_argument(
        "--testvector-crosswalk",
        nargs=2,
        metavar=("OLD_MANIFEST", "NEW_MANIFEST"),
        default=None,
        help="Cross-spec test-vector coverage migration: classify each OLD "
        "vector as unchanged / retargeted / retired against NEW clause IDs. "
        "Writes testvector_crosswalk.html into the build target dir.",
    )
    parser.add_argument(
        "--testvector-clause-map",
        type=str,
        default=None,
        metavar="PATH",
        help="Optional TOML clause-rename map for --testvector-crosswalk.",
    )
    parser.add_argument(
        "--backport-errata",
        type=str,
        default=None,
        metavar="FILE",
        help="Path to an errata TOML manifest. With --target-branch, generates "
        "per-erratum .patch files plus errata_backport_note.md in the build dir.",
    )
    parser.add_argument(
        "--target-branch",
        type=str,
        default=None,
        metavar="BRANCH",
        help="Target branch for --backport-errata patches.",
    )

    # --- AI-assisted review (opt-in; reads local files only) ---
    parser.add_argument(
        "--ai-review",
        action="store_true",
        help="OPT-IN: run AI-assisted review of recent changes; writes ai_review.md "
        "to the build output dir. Reads local files only (current spec + git diff "
        "vs baseline) and makes a single Anthropic API call. Requires ANTHROPIC_API_KEY.",
    )
    parser.add_argument(
        "--ai-review-baseline",
        default="auto",
        metavar="REF",
        help="Git ref to diff against for --ai-review (default: auto-detect via "
        "tags / origin/main / main).",
    )
    parser.add_argument(
        "--ai-review-dry-run",
        action="store_true",
        help="Print the AI review prompt without calling the LLM (for testing/debugging).",
    )

    # --- Document enhancement options ---
    parser.add_argument(
        "--revision-history",
        action="store_true",
        help="Insert a revision history table from git tags/commits.",
    )
    parser.add_argument(
        "--index",
        choices=["bikeshed", "alphabetical", "none"],
        default="bikeshed",
        help="Index style: 'bikeshed' (default), "
        "'alphabetical' (grouped by letter), "
        "or 'none' (remove index).",
    )
    parser.add_argument(
        "--check-terminology",
        action="store_true",
        help="Check for terminology inconsistencies (same concept, different names).",
    )
    parser.add_argument(
        "--check-orphan-refs",
        action="store_true",
        help="Detect uncited bibliography entries and missing citations.",
    )
    parser.add_argument(
        "--check-orphan-refs-strict",
        action="store_true",
        help="Like --check-orphan-refs but exit with error on missing citations.",
    )
    parser.add_argument(
        "--highlight-keywords",
        action="store_true",
        help="Visually highlight RFC 2119 keywords (MUST, SHALL, etc.).",
    )
    parser.add_argument(
        "--figure-table-tooltips",
        action=BooleanOptionalAction,
        default=True,
        help="Add hover tooltips for figure and table cross-reference links (default: enabled).",
    )
    parser.add_argument(
        "--syntax-tooltips",
        action=BooleanOptionalAction,
        default=True,
        help="Add hover tooltips on SDL syntax table "
        "elements showing semantic descriptions "
        "(default: enabled).",
    )
    parser.add_argument(
        "--toc-bold-primary-only",
        action=BooleanOptionalAction,
        default=True,
        help="Only bold top-level TOC entries; secondary "
        "levels use normal weight (default: enabled).",
    )
    parser.add_argument(
        "--pwa",
        action="store_true",
        help="Generate Progressive Web App files for offline viewing (manifest, service worker).",
    )
    parser.add_argument(
        "--no-pwa",
        dest="no_pwa",
        action="store_true",
        help="Skip PWA/service-worker generation, overriding any --pwa set by a "
        "profile. Useful when the spec is served from a shared path where a "
        "cache-first service worker would mask newer content.",
    )
    parser.add_argument(
        "--spec-compare",
        type=str,
        default=None,
        metavar="PATH",
        help="Generate a spec version comparison dashboard against the baseline HTML at PATH.",
    )
    parser.add_argument(
        "--normative-deps",
        action="store_true",
        help="Generate a normative dependency graph showing cross-section requirement references.",
    )
    parser.add_argument(
        "--requirement-ids",
        action="store_true",
        help="Assign stable requirement IDs (REQ-<section>-<NNN>) to normative statements. "
        "Outputs JSON, CSV, and HTML.",
    )
    parser.add_argument(
        "--issue-traceability",
        nargs="?",
        const="auto",
        default=None,
        metavar="REF",
        help="Map issues referenced in git commits to changed spec sections. "
        "REF is the baseline git ref (default: auto-detect main branch).",
    )
    parser.add_argument(
        "--ext-spec-deps",
        action="store_true",
        help="Track external specification dependencies and cross-references.",
    )
    parser.add_argument(
        "--metrics-trend",
        nargs="?",
        const="auto",
        default=None,
        metavar="BASELINE",
        help="Spec metrics trend analysis with per-section growth warnings. "
        "BASELINE is a path to a previous build's HTML (default: auto).",
    )
    parser.add_argument(
        "--release",
        type=str,
        default=None,
        metavar="TAG",
        help="Run the release workflow: save baseline, generate changelog, and create git tag TAG.",
    )
    parser.add_argument(
        "--content-width",
        type=str,
        default=None,
        metavar="WIDTH",
        help="Constrain HTML content width on screen "
        "(e.g. '60em', '900px', '80ch'). "
        "Use 'none' to disable. "
        "Default: theme value (%(default)s).",
    )

    # --- Output options ---
    parser.add_argument("--zip", action="store_true", help="Create a ZIP archive of the output.")
    parser.add_argument("--syntax_browser", action="store_true", help="Generate syntax browser.")
    parser.add_argument(
        "--externalize_resources",
        action="store_true",
        help="Externalize CSS and JavaScript to separate files.",
    )
    parser.add_argument(
        "--minify", action="store_true", help="Minify HTML by removing unnecessary whitespace."
    )
    parser.add_argument(
        "--mobile_optimized",
        action="store_true",
        help="Add collapsible sections for mobile optimization.",
    )
    parser.add_argument(
        "--links", action="store_true", help="Add links banner (PDF, diff, syntax browser)."
    )
    parser.add_argument(
        "--x86-python",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to an x86_64 Python for WeasyPrint on Apple Silicon Macs.",
    )

    # --- Multipage options ---
    mp_group = parser.add_argument_group("Multipage options")
    mp_group.add_argument(
        "--multipage",
        action="store_true",
        help="Generate multipage HTML output (per-section files with navigation).",
    )
    mp_group.add_argument("--no_sidebar", action="store_true", help="Disable sidebar TOC.")
    mp_group.add_argument("--no_breadcrumb", action="store_true", help="Disable breadcrumb trail.")
    mp_group.add_argument(
        "--sidebar_position",
        choices=["left", "right"],
        default="left",
        help="Sidebar position (default: left).",
    )

    # --- Standards document options ---
    std_group = parser.add_argument_group("Standards document options")
    std_group.add_argument(
        "--standards-flavor",
        type=str,
        default=None,
        metavar="FLAVOR",
        choices=[
            "iso",
            "itu-t",
            "itu",
            "ietf",
            "iec",
            "nist",
            "ogc",
            "cc",
            "bipm",
            "bsi",
            "cen",
            "cenelec",
            "ieee",
            "jis",
            "unece",
            "un",
            "3gpp",
            "jvet",
            "mpeg",
            "iso-video",
            "itu-video",
            "aom",
            "av1",
            "av2",
            "gb",
            "etsi",
            "smpte",
        ],
        help="Standards body flavor for document structure and formatting (iso, itu-t, ietf, iec).",
    )
    std_group.add_argument(
        "--standards-strict",
        action="store_true",
        help="Exit with error on standards structure violations.",
    )
    std_group.add_argument(
        "--standards-stage",
        type=str,
        default=None,
        metavar="STAGE",
        help="Document stage (e.g. WD, CD, DIS, FDIS, IS for ISO).",
    )
    std_group.add_argument(
        "--iso-docnumber",
        type=str,
        default=None,
        metavar="NUM",
        help="ISO/IEC document number (e.g. '23094-1').",
    )
    std_group.add_argument(
        "--validate-standards",
        action="store_true",
        help="Run standards structure validation checks.",
    )
    std_group.add_argument(
        "--validate-references",
        action="store_true",
        help="Validate bibliography references against a known standards database "
        "(checks for outdated editions, withdrawn standards, format issues).",
    )
    std_group.add_argument(
        "--validate-references-strict",
        action="store_true",
        help="Like --validate-references but exit with error on validation errors.",
    )
    std_group.add_argument(
        "--online-refs",
        action="store_true",
        help="Validate references against online APIs (IETF, CrossRef). "
        "Results are cached locally in .specbuild_ref_cache.json.",
    )
    std_group.add_argument(
        "--inject-boilerplate",
        action="store_true",
        help="Inject boilerplate sections (foreword, scope, etc.) per the active flavor.",
    )
    std_group.add_argument(
        "--iso-numbering",
        action="store_true",
        help="Apply ISO-compliant clause and annex numbering.",
    )
    std_group.add_argument(
        "--format-bibliography",
        action="store_true",
        help="Reformat bibliography per the active flavor's citation style.",
    )
    std_group.add_argument(
        "--isodoc-xml",
        action="store_true",
        help="Export IsoDoc-compatible XML.",
    )
    std_group.add_argument(
        "--sts-xml",
        action="store_true",
        help="Export NISO STS XML for ISO document management.",
    )
    std_group.add_argument(
        "--validate-sts",
        action="store_true",
        help="Validate the exported STS XML against the bundled NISO STS 1.2 "
        "interchange DTD; the build fails if it is invalid (implies --sts-xml).",
    )
    std_group.add_argument(
        "--iso-docx",
        action="store_true",
        help="Export ISO-styled Word document.",
    )
    std_group.add_argument(
        "--conformance-requirements",
        action="store_true",
        help="Add conformance requirement anchors and summary table.",
    )
    std_group.add_argument(
        "--structured-requirements",
        action="store_true",
        help="Process structured requirement/permission/recommendation blocks.",
    )
    std_group.add_argument(
        "--reviewer-notes",
        action="store_true",
        help="Process reviewer annotation blocks as styled comments.",
    )
    std_group.add_argument(
        "--auto-expand-refs",
        action="store_true",
        help="Auto-expand short bibliography references to full citations.",
    )
    std_group.add_argument(
        "--import-terms",
        action="store_true",
        help="Auto-import term definitions from external terminology databases.",
    )
    std_group.add_argument(
        "--load-terms-from",
        nargs="+",
        metavar="PATH",
        help="Load external term databases from TBX (.tbx) or YAML (.yaml/.yml) files before importing terms.",
    )
    std_group.add_argument(
        "--amendment",
        action="store_true",
        help="Generate amendment/corrigendum document with change-only formatting.",
    )
    std_group.add_argument(
        "--base-document",
        type=str,
        default=None,
        metavar="DOC",
        help="Base document identifier for amendment (e.g. 'ISO/IEC 14496-10:2022').",
    )
    std_group.add_argument(
        "--amendment-number",
        type=str,
        default=None,
        metavar="NUM",
        help="Amendment number (default: 1).",
    )
    std_group.add_argument(
        "--collection-toc",
        action="store_true",
        help="Generate multi-part standard collection table of contents.",
    )
    std_group.add_argument(
        "--cross-part-links",
        action="store_true",
        help="Resolve and link cross-part references (requires [standards.multipart] config).",
    )
    std_group.add_argument(
        "--compile-collection",
        action="store_true",
        help="Compile multi-part collection into single navigable document.",
    )
    std_group.add_argument(
        "--check-xpart-refs",
        action="store_true",
        help="Validate that cross-part references resolve to existing anchors.",
    )
    std_group.add_argument(
        "--check-xpart-refs-strict",
        action="store_true",
        help="Like --check-xpart-refs but exit with error on unresolved references.",
    )
    std_group.add_argument(
        "--check-xrefs",
        action="store_true",
        help="Validate all cross-references: internal anchors (XREF-1), cross-part links (XREF-2), and bibliography erefs (XREF-3).",
    )
    std_group.add_argument(
        "--check-xrefs-strict",
        action="store_true",
        help="Like --check-xrefs but exit with error on any unresolved reference.",
    )
    std_group.add_argument(
        "--doc-relations",
        action="store_true",
        help="Extract and inject document relation metadata (supersedes, amends, etc.).",
    )
    std_group.add_argument(
        "--conformance-levels",
        type=str,
        default=None,
        metavar="LEVELS",
        help="Comma-separated conformance levels for compliance matrix "
        "(e.g. 'Main,Main 10,High Tier').",
    )

    # --- Import options ---
    import_group = parser.add_argument_group("Import options")
    import_group.add_argument(
        "--import-docx",
        type=str,
        default=None,
        metavar="PATH",
        help="Import a Word document (.docx) and convert to Bikeshed sources.",
    )
    import_group.add_argument(
        "--import-pdf",
        type=str,
        default=None,
        metavar="PATH",
        help="Import a PDF and convert to Bikeshed sources (lower fidelity than DOCX).",
    )
    import_group.add_argument(
        "--import-output-dir",
        type=str,
        default=None,
        metavar="DIR",
        help="Output directory for imported Bikeshed files (default: bikeshed/).",
    )
    import_group.add_argument(
        "--import-flavor",
        type=str,
        default=None,
        metavar="FLAVOR",
        help="Standards flavor to use for the imported spec.",
    )
    import_group.add_argument(
        "--import-split-level",
        type=int,
        default=1,
        metavar="N",
        help="Split at Heading N level (default: 1 = major sections).",
    )
    import_group.add_argument(
        "--import-detect-sdl",
        action="store_true",
        default=True,
        help="Auto-detect SDL syntax tables in the source document (default: enabled).",
    )
    import_group.add_argument(
        "--import-extract-symbols",
        action="store_true",
        default=True,
        help="Extract constants/symbols for symbols.bs (default: enabled).",
    )
    import_group.add_argument(
        "--import-syntax-format",
        type=str,
        default="table",
        choices=["table", "sdl"],
        help="Format for syntax tables: 'table' preserves as HTML tables "
        "(H.265 style), 'sdl' converts to SDL fenced code blocks. "
        "Default: table.",
    )
    import_group.add_argument(
        "--source",
        type=str,
        default=None,
        metavar="PATH",
        help="Source project path (directory or main file). "
        "Accepts Metanorma/AsciiDoc (.adoc) or Bikeshed (.bs) projects. "
        "Format is auto-detected; Metanorma projects are converted transparently "
        "before compilation. If omitted, the current directory is used.",
    )
    import_group.add_argument(
        "--source-format",
        type=str,
        default=None,
        choices=["auto", "bikeshed", "metanorma"],
        metavar="FORMAT",
        help="Override source format detection: 'bikeshed', 'metanorma', or 'auto' "
        "(default: auto).",
    )

    return parser

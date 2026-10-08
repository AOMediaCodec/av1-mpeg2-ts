"""Built-in plugin registrations for the specbuild pipeline.

Each plugin is registered with the decorator API from :mod:`specbuild.plugins`
and receives a :class:`~specbuild.context.BuildContext` argument.  The actual
implementation modules keep their existing function signatures — the closures
here serve as adapters.

Importing this module populates the plugin registry.  The build driver in
``compile.py`` queries :func:`~specbuild.plugins.get_enabled_plugins` to
discover and invoke enabled plugins for each pipeline phase.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild.plugins import (
    register_enhancement,
    register_output_task,
    register_quality_check,
)

if TYPE_CHECKING:
    from specbuild.context import BuildContext


def _soup_or_file(soup_fn, file_fn, soup, html_path, ctx=None):
    """Try ``soup_fn(soup, ctx=ctx)`` first; fall back to ``file_fn(html_path)``
    when soup is unavailable.

    The optional *ctx* is forwarded to *soup_fn* when it accepts a ``ctx``
    keyword (so plugins can read ``ctx.precomputed`` lookup maps).  Plugins
    that haven't been refactored yet ignore the kwarg via the default
    ``ctx=None`` parameter on their public function.
    """
    import inspect

    if soup is not None:
        if ctx is not None and "ctx" in inspect.signature(soup_fn).parameters:
            result = soup_fn(soup, ctx=ctx)
        else:
            result = soup_fn(soup)
        if result is not None:
            return result
    return file_fn(html_path)


# ═══════════════════════════════════════════════════════════════════════════
# Quality checks (read-only, concurrent on soup)
# ═══════════════════════════════════════════════════════════════════════════


@register_quality_check(
    name="validate-refs",
    cli_flags=["--validate-refs", "--validate-refs-strict"],
    description="Validate internal cross-references resolve.",
)
def _qc_validate_refs(ctx: BuildContext):
    from specbuild.checks.validate import report_broken_refs, validate_cross_references_soup

    broken = validate_cross_references_soup(ctx.soup, ctx=ctx)
    if ctx.report is not None:
        ctx.report.broken_refs = broken
    report_broken_refs(broken, ctx.html_path, strict=ctx.args.validate_refs_strict)


@register_quality_check(
    name="validate-sdl-refs",
    cli_flags=["--validate-sdl-refs", "--validate-sdl-refs-strict"],
    description="Validate SDL function call references.",
)
def _qc_validate_sdl_refs(ctx: BuildContext):
    from specbuild.checks.sdlvalidate import report_sdl_refs, validate_sdl_references_soup

    issues = validate_sdl_references_soup(ctx.soup)
    if ctx.report is not None:
        ctx.report.sdl_issues = issues
    report_sdl_refs(issues, ctx.html_path, strict=ctx.args.validate_sdl_refs_strict)


@register_quality_check(
    name="check-sdl-syntax",
    cli_flags=["--check-sdl-syntax", "--strict-sdl-syntax"],
    description="Validate SDL code blocks against the MPEG SDL grammar.",
)
def _qc_check_sdl_syntax(ctx: BuildContext):
    from specbuild.checks.sdlsyntax import run_sdl_syntax_check

    strict = bool(getattr(ctx.args, "strict_sdl_syntax", False))
    error_count = run_sdl_syntax_check(strict=strict)
    if ctx.report is not None:
        ctx.report.sdl_syntax_errors = error_count if error_count > 0 else 0
    if strict and error_count > 0:
        raise RuntimeError(f"SDL syntax check found {error_count} error(s) (--strict-sdl-syntax)")


@register_quality_check(
    name="check-images",
    cli_flags=["--check-images", "--check-images-strict"],
    description="Check for broken image references.",
)
def _qc_check_images(ctx: BuildContext):
    from specbuild.checks.imagecheck import check_images_soup, report_missing_images

    issues = check_images_soup(ctx.soup, ctx.html_path.parent)
    if ctx.report is not None:
        ctx.report.broken_images = issues
    report_missing_images(issues, ctx.html_path, strict=ctx.args.check_images_strict)


@register_quality_check(
    name="accessibility-audit",
    cli_flags=["--accessibility-audit", "--accessibility-audit-strict"],
    description="WCAG accessibility audit.",
)
def _qc_accessibility(ctx: BuildContext):
    from specbuild.checks.accessibility import audit_accessibility_soup, report_accessibility

    issues = audit_accessibility_soup(ctx.soup, ctx=ctx)
    if ctx.report is not None:
        ctx.report.accessibility_issues = issues
    report_accessibility(issues, strict=ctx.args.accessibility_audit_strict)


@register_quality_check(
    name="check-dfn",
    cli_flags=["--check-dfn", "--check-dfn-strict"],
    description="Check definition consistency (unused/undefined).",
)
def _qc_check_dfn(ctx: BuildContext):
    from specbuild.checks.dfnconsistency import check_dfn_consistency_soup, report_dfn_consistency

    result = check_dfn_consistency_soup(ctx.soup, ctx=ctx)
    if ctx.report is not None:
        ctx.report.dfn_issues = result
    report_dfn_consistency(result, strict=ctx.args.check_dfn_strict)


@register_quality_check(
    name="check-terminology",
    cli_flags=["--check-terminology"],
    description="Check for terminology inconsistencies.",
)
def _qc_check_terminology(ctx: BuildContext):
    from specbuild.checks.terminology import check_terminology_soup, report_terminology_issues

    issues = check_terminology_soup(ctx.soup)
    if ctx.report is not None:
        ctx.report.terminology_issues = issues
    report_terminology_issues(issues)


@register_quality_check(
    name="check-orphan-refs",
    cli_flags=["--check-orphan-refs", "--check-orphan-refs-strict"],
    description="Detect uncited bibliography entries.",
)
def _qc_check_orphan_refs(ctx: BuildContext):
    from specbuild.checks.orphanrefs import detect_orphan_references_soup, report_orphan_references

    result = detect_orphan_references_soup(ctx.soup)
    if ctx.report is not None:
        ctx.report.orphan_refs = result
    report_orphan_references(result, strict=ctx.args.check_orphan_refs_strict)


@register_quality_check(
    name="check-links",
    cli_flags=["--check-links", "--check-links-strict"],
    description="Check external URLs are reachable.",
)
def _qc_check_links(ctx: BuildContext):
    from specbuild.checks.linkcheck import check_external_links_soup, report_external_links

    issues = check_external_links_soup(ctx.soup, allowlist=ctx.args.check_links_allowlist, ctx=ctx)
    if ctx.report is not None:
        ctx.report.link_check_issues = issues
    report_external_links(issues, strict=ctx.args.check_links_strict)


@register_quality_check(
    name="check-internal-links",
    cli_flags=["--check-internal-links"],
    description="Detect broken internal #id fragment links.",
)
def _qc_check_internal_links(ctx: BuildContext):
    from specbuild.checks.linkcheck import check_internal_links_soup

    issues = check_internal_links_soup(ctx.soup, ctx=ctx)
    if issues:
        import logging

        logging.warning(f"Internal link check: {len(issues)} broken fragment(s)")


@register_quality_check(
    name="check-tables",
    cli_flags=["--check-tables", "--check-tables-strict"],
    description="Validate table structure (columns, headers, captions).",
)
def _qc_check_tables(ctx: BuildContext):
    from specbuild.checks.tablevalidate import report_table_validation, validate_tables_soup

    issues = validate_tables_soup(ctx.soup)
    if ctx.report is not None:
        ctx.report.table_issues = issues
    report_table_validation(issues, strict=ctx.args.check_tables_strict)


@register_quality_check(
    name="check-referenceable",
    cli_flags=["--check-referenceable", "--check-referenceable-strict"],
    description="Check that tables/figures are numbered and cross-referenceable.",
)
def _qc_check_referenceable(ctx: BuildContext):
    from specbuild.checks.referenceable import check_referenceable_soup, report_referenceable

    issues = check_referenceable_soup(ctx.soup)
    if ctx.report is not None:
        ctx.report.referenceable_issues = issues
    report_referenceable(issues, strict=ctx.args.check_referenceable_strict)


@register_quality_check(
    name="spellcheck",
    cli_flags=["--spellcheck", "--spellcheck-strict"],
    description="Domain-aware spelling/terminology check.",
)
def _qc_spellcheck(ctx: BuildContext):
    from specbuild.checks.spellingcheck import (
        check_spelling_soup,
        load_custom_dict,
        report_spelling,
    )

    extra_rules = []
    if ctx.args.spellcheck_dict:
        extra_rules = load_custom_dict(Path(ctx.args.spellcheck_dict))
    issues = check_spelling_soup(ctx.soup, extra_rules=extra_rules)
    if ctx.report is not None:
        ctx.report.spelling_issues = issues
    report_spelling(issues, strict=ctx.args.spellcheck_strict)


@register_quality_check(
    name="check-duplicates",
    cli_flags=["--check-duplicates", "--check-duplicates-strict"],
    description="Detect near-duplicate paragraphs across sections.",
)
def _qc_check_duplicates(ctx: BuildContext):
    from specbuild.checks.duplicates import detect_duplicates_soup, report_duplicates

    dupes = detect_duplicates_soup(ctx.soup, threshold=ctx.args.duplicate_threshold)
    report_duplicates(dupes, strict=ctx.args.check_duplicates_strict)


@register_quality_check(
    name="editorial",
    cli_flags=["--editorial", "--editorial-strict"],
    description="Editorial consistency (compound words, dfn capitalization).",
)
def _qc_editorial(ctx: BuildContext):
    from specbuild.checks.editorial import (
        check_editorial_soup,
        load_editorial_rules,
        report_editorial_issues,
    )

    extra_rules = None
    if ctx.args.editorial_rules:
        extra_rules = load_editorial_rules(Path(ctx.args.editorial_rules))
    issues = check_editorial_soup(ctx.soup, extra_rules=extra_rules, ctx=ctx)
    report_editorial_issues(issues, strict=ctx.args.editorial_strict)


@register_quality_check(
    name="validate-references",
    cli_flags=["--validate-references", "--validate-references-strict"],
    description="Validate bibliography references against standards database.",
)
def _qc_validate_references(ctx: BuildContext):
    from specbuild.checks.refvalidate import report_reference_validation, validate_references_soup

    issues = validate_references_soup(
        ctx.soup,
        flavor=ctx.standards_flavor,
        online=getattr(ctx.args, "online_refs", False),
    )
    if ctx.report is not None:
        ctx.report.reference_issues = issues
    report_reference_validation(issues, strict=ctx.args.validate_references_strict)


@register_quality_check(
    name="validate-standards",
    cli_flags=["--validate-standards", "--standards-strict"],
    description="Validate document structure per standards flavor.",
)
def _qc_validate_standards(ctx: BuildContext):
    if not ctx.standards_flavor:
        return

    from specbuild.checks.standardsvalidate import (
        _heading_texts,
        report_standards_validation,
        validate_annex_classification_soup,
        validate_bibliography_format_soup,
        validate_metadata_completeness,
        validate_section_order_soup,
        validate_structure_soup,
        validate_terms_section_soup,
    )
    from specbuild.config import STANDARDS
    from specbuild.standards.metadata import resolve_metadata

    # Extract headings once and share across validators that need them.
    headings = _heading_texts(ctx.soup)

    issues: list[dict[str, str]] = []
    issues.extend(validate_structure_soup(ctx.soup, ctx.standards_flavor, headings=headings))
    issues.extend(validate_section_order_soup(ctx.soup, ctx.standards_flavor, headings=headings))

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    issues.extend(validate_metadata_completeness(meta, ctx.standards_flavor))
    issues.extend(
        validate_bibliography_format_soup(ctx.soup, ctx.standards_flavor, headings=headings)
    )
    issues.extend(validate_annex_classification_soup(ctx.soup))
    issues.extend(validate_terms_section_soup(ctx.soup))

    if ctx.report is not None:
        ctx.report.standards_issues = issues
    report_standards_validation(issues, strict=ctx.args.standards_strict)


# ═══════════════════════════════════════════════════════════════════════════
# Enhancements (sequential soup mutations, ordered by `order`)
# ═══════════════════════════════════════════════════════════════════════════

# --- Precompute helpers (run in parallel thread pool) ---


def _precompute_changed_lines(baseline_ref):
    """Shared precompute for change-bars and table-of-changes."""
    from specbuild.enhancements.changebars import get_changed_lines, resolve_baseline

    ref = resolve_baseline(baseline_ref)
    return ref, get_changed_lines(ref)


def _precompute_changebars(args):
    return _precompute_changed_lines(args.change_bars)


def _precompute_toc_changes(args):
    return _precompute_changed_lines(args.table_of_changes)


def _precompute_revhistory():
    from specbuild.enhancements.revhistory import get_revision_entries

    return get_revision_entries()


def _load_asset_pair(css_name, js_name):
    """Load a CSS/JS asset pair, preferring workspace overrides."""
    from specbuild.utils import resolve_asset_file

    css = js = None
    try:
        css = resolve_asset_file(f"css/{css_name}").read_text(encoding="utf-8")
    except FileNotFoundError:
        pass
    try:
        js = resolve_asset_file(f"js/{js_name}").read_text(encoding="utf-8")
    except FileNotFoundError:
        pass
    return css, js


def _precompute_tooltips():
    return _load_asset_pair("figure-table-tooltips.css", "figure-table-tooltips.js")


def _precompute_syntax_tooltips():
    return _load_asset_pair("syntax-tooltips.css", "syntax-tooltips.js")


# --- Enhancement plugins ---


@register_enhancement(
    name="amendment-format",
    cli_flags=["--amendment"],
    description="Format document as amendment/corrigendum with cover page and change marks.",
    order=4,
    enabled=lambda args: bool(getattr(args, "amendment", False)),
)
def _enh_amendment_format(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.output.amendment import (
        generate_amendment_toc_soup,
        inject_amendment_cover_soup,
        inject_amendment_css_soup,
        mark_changed_sections_soup,
    )
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    if ctx.args.base_document:
        meta["base_document"] = ctx.args.base_document
    if ctx.args.amendment_number:
        meta["amendment_number"] = ctx.args.amendment_number
    if not meta.get("doc_type") or meta["doc_type"] == "standard":
        meta["doc_type"] = "amendment"

    inject_amendment_cover_soup(ctx.soup, meta, ctx.standards_flavor)

    from specbuild.standards.amendmentdiff import apply_amendment_changes_from_git

    changed = apply_amendment_changes_from_git(ctx.soup)
    if not changed:
        mark_changed_sections_soup(ctx.soup)

    generate_amendment_toc_soup(ctx.soup, meta)
    inject_amendment_css_soup(ctx.soup)
    ctx.dirty = True


@register_enhancement(
    name="cross-part-links",
    cli_flags=["--cross-part-links"],
    description="Resolve cross-part references to hyperlinks.",
    order=4,
    enabled=lambda args: bool(getattr(args, "cross_part_links", False)),
)
def _enh_cross_part_links(ctx: BuildContext):
    from specbuild.multipart import inject_cross_part_links_soup

    if inject_cross_part_links_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="inject-boilerplate",
    cli_flags=["--inject-boilerplate"],
    description="Inject standards boilerplate sections (foreword, scope, etc.).",
    order=5,
    enabled=lambda args: bool(getattr(args, "inject_boilerplate", False)),
)
def _enh_inject_boilerplate(ctx: BuildContext):
    from specbuild.enhancements.boilerplate import inject_boilerplate

    inject_boilerplate(ctx)


@register_enhancement(
    name="iso-numbering",
    cli_flags=["--iso-numbering"],
    description="Apply ISO-compliant clause, annex, figure, and table numbering.",
    order=6,
    enabled=lambda args: bool(getattr(args, "iso_numbering", False)),
)
def _enh_iso_numbering(ctx: BuildContext):
    if not ctx.standards_flavor:
        return
    from specbuild.enhancements.isonumbering import (
        renumber_annexes_soup,
        renumber_clauses_soup,
        renumber_figures_tables_soup,
    )

    modified = renumber_clauses_soup(ctx.soup, ctx.standards_flavor)
    modified += renumber_annexes_soup(ctx.soup, ctx.standards_flavor)
    modified += renumber_figures_tables_soup(ctx.soup, ctx.standards_flavor)
    if modified:
        ctx.dirty = True


@register_enhancement(
    name="format-terms",
    cli_flags=["--standards-flavor"],
    description="Format Terms and definitions section per ISO 10241.",
    order=7,
    enabled=lambda args: bool(getattr(args, "standards_flavor", None)),
)
def _enh_format_terms(ctx: BuildContext):
    if not ctx.standards_flavor:
        return
    from specbuild.enhancements.termsformat import format_terms_section_soup

    if format_terms_section_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="format-bibliography",
    cli_flags=["--format-bibliography"],
    description="Reformat bibliography per standards citation style.",
    order=8,
    enabled=lambda args: bool(getattr(args, "format_bibliography", False)),
)
def _enh_format_bibliography(ctx: BuildContext):
    if not ctx.standards_flavor:
        return
    from specbuild.enhancements.bibformat import format_bibliography_soup

    if format_bibliography_soup(ctx.soup, ctx.standards_flavor):
        ctx.dirty = True


@register_enhancement(
    name="auto-expand-refs",
    cli_flags=["--auto-expand-refs"],
    description="Auto-expand short bibliography references to full citations from database.",
    order=8,
    enabled=lambda args: bool(getattr(args, "auto_expand_refs", False)),
)
def _enh_auto_expand_refs(ctx: BuildContext):
    from specbuild.enhancements.autoexpand import auto_expand_bibliography_soup

    if auto_expand_bibliography_soup(ctx.soup, ctx.standards_flavor):
        ctx.dirty = True


@register_enhancement(
    name="load-terms-from",
    cli_flags=["--load-terms-from"],
    description="Load external term databases from TBX or YAML files.",
    order=6,
    enabled=lambda args: bool(getattr(args, "load_terms_from", None)),
)
def _enh_load_terms_from(ctx: BuildContext):
    from specbuild.standards.termdb import (
        load_terms_from_tbx,
        load_terms_from_yaml,
        register_external_terms,
    )

    paths = getattr(ctx.args, "load_terms_from", None) or []
    for path in paths:
        lower = path.lower()
        if lower.endswith(".tbx") or lower.endswith(".xml"):
            terms = load_terms_from_tbx(path)
        elif lower.endswith(".yaml") or lower.endswith(".yml"):
            terms = load_terms_from_yaml(path)
        else:
            logging.warning(
                f"--load-terms-from: unrecognized file type '{path}'; expected .tbx, .xml, .yaml, or .yml"
            )
            continue
        if terms:
            db_name = Path(path).stem
            register_external_terms(db_name, terms)


@register_enhancement(
    name="import-terms",
    cli_flags=["--import-terms"],
    description="Auto-import term definitions from external terminology databases.",
    order=7,
    enabled=lambda args: bool(getattr(args, "import_terms", False)),
)
def _enh_import_terms(ctx: BuildContext):
    from specbuild.standards.termdb import import_terms_soup

    if import_terms_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="conformance-requirements",
    cli_flags=["--conformance-requirements"],
    description="Add conformance requirement anchors and summary table.",
    order=9,
    enabled=lambda args: bool(getattr(args, "conformance_requirements", False)),
)
def _enh_conformance_requirements(ctx: BuildContext):
    from specbuild.enhancements.conformance import inject_conformance_soup

    if inject_conformance_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="structured-requirements",
    cli_flags=["--structured-requirements"],
    description="Process structured requirement/permission/recommendation blocks.",
    order=9,
    enabled=lambda args: bool(getattr(args, "structured_requirements", False)),
)
def _enh_structured_requirements(ctx: BuildContext):
    from specbuild.enhancements.requirements import process_requirement_blocks_soup

    if process_requirement_blocks_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="autolink-req-ids",
    cli_flags=["--autolink-req-ids"],
    description="Convert bare REQ-/PER-/REC- IDs in prose text to hyperlinks.",
    order=45,
    enabled=lambda args: bool(getattr(args, "autolink_req_ids", False)),
)
def _enh_autolink_req_ids(ctx: BuildContext):
    from specbuild.enhancements.requirements import autolink_requirement_ids

    if autolink_requirement_ids(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="reviewer-notes",
    cli_flags=["--reviewer-notes"],
    description="Process reviewer annotation blocks as styled comments.",
    order=9,
    enabled=lambda args: bool(getattr(args, "reviewer_notes", False)),
)
def _enh_reviewer_notes(ctx: BuildContext):
    from specbuild.enhancements.reviewer import process_reviewer_notes_soup

    if process_reviewer_notes_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="strip-reviewer-notes",
    cli_flags=["--strip-reviewer-notes"],
    description="Remove all reviewer annotations for publication builds.",
    order=9,
    enabled=lambda args: bool(getattr(args, "strip_reviewer_notes", False)),
)
def _enh_strip_reviewer_notes(ctx: BuildContext):
    from specbuild.enhancements.reviewer import strip_reviewer_notes_soup

    if strip_reviewer_notes_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="section-permalinks",
    cli_flags=["--section-permalinks"],
    description="Add §N.N permalink anchors to every numbered heading.",
    order=11,
)
def _enh_section_permalinks(ctx: BuildContext):
    from specbuild.enhancements.sectionheaders import inject_section_permalinks_soup

    if inject_section_permalinks_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="number-equations",
    cli_flags=["--number-equations"],
    description="Auto-number display equations as (section.N).",
    order=10,
)
def _enh_number_equations(ctx: BuildContext):
    from specbuild.enhancements.equations import number_equations_soup

    if number_equations_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="change-bars",
    cli_flags=["--change-bars"],
    description="Add change bars marking modified text.",
    order=20,
    precompute=_precompute_changebars,
)
def _enh_change_bars(ctx: BuildContext):
    cb_data = ctx.precomputed.get("change-bars")
    if cb_data:
        _cb_ref, changed_lines = cb_data
        from specbuild.enhancements.changebars import add_change_bars_soup

        add_change_bars_soup(ctx.soup, changed_lines)
        ctx.dirty = True


@register_enhancement(
    name="revision-history",
    cli_flags=["--revision-history"],
    description="Insert revision history table from git tags/commits.",
    order=25,
    precompute=_precompute_revhistory,
)
def _enh_revision_history(ctx: BuildContext):
    rev_data = ctx.precomputed.get("revision-history")
    if rev_data:
        entries, use_tags = rev_data
        if entries:
            from specbuild.enhancements.revhistory import inject_revision_history_soup

            inject_revision_history_soup(ctx.soup, entries, use_tags=use_tags)
            ctx.dirty = True


@register_enhancement(
    name="table-of-changes",
    cli_flags=["--table-of-changes"],
    description="Insert Table of Changes listing modified sections.",
    order=30,
    precompute=_precompute_toc_changes,
    enabled=lambda args: bool(args.table_of_changes),
)
def _enh_table_of_changes(ctx: BuildContext):
    # Reuse change_bars data when both are enabled; otherwise use own data
    toc_data = ctx.precomputed.get("table-of-changes") or ctx.precomputed.get("change-bars")
    if toc_data:
        toc_ref, toc_changed_lines = toc_data
        from specbuild.enhancements.tableofchanges import (
            get_section_changes,
            inject_table_of_changes_soup,
        )

        section_changes = get_section_changes(ctx.soup, toc_changed_lines)
        if section_changes:
            inject_table_of_changes_soup(ctx.soup, section_changes, baseline_label=toc_ref)
            ctx.dirty = True


@register_enhancement(
    name="index",
    cli_flags=["--index"],
    description="Index management (alphabetical, remove, or Bikeshed default).",
    order=35,
    enabled=lambda args: args.index != "bikeshed",
)
def _enh_index(ctx: BuildContext):
    from specbuild.enhancements.indexgen import manage_index_soup

    manage_index_soup(ctx.soup, ctx.args.index)
    ctx.dirty = True


@register_enhancement(
    name="highlight-keywords",
    cli_flags=["--highlight-keywords"],
    description="Visually highlight RFC 2119 keywords.",
    order=40,
)
def _enh_highlight_keywords(ctx: BuildContext):
    from specbuild.enhancements.keywords import highlight_keywords_soup

    if highlight_keywords_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="figure-table-tooltips",
    cli_flags=["--figure-table-tooltips"],
    description="Hover tooltips for figure/table cross-references.",
    order=50,
    precompute=_precompute_tooltips,
)
def _enh_figure_table_tooltips(ctx: BuildContext):
    from specbuild.utils import inject_css, inject_js

    tooltip_data = ctx.precomputed.get("figure-table-tooltips", (None, None))
    css, js = tooltip_data
    injected = False
    if css:
        inject_css(ctx.soup, "figure-table-tooltips-css", css)
        injected = True
    else:
        logging.warning("figure-table-tooltips.css not found; skipping CSS injection")
    if js:
        inject_js(ctx.soup, "figure-table-tooltips-js", js)
        injected = True
    else:
        logging.warning("figure-table-tooltips.js not found; skipping JS injection")
    if injected:
        ctx.dirty = True
        logging.debug("Injected figure/table tooltip CSS and JS")


@register_enhancement(
    name="syntax-tooltips",
    cli_flags=["--syntax-tooltips"],
    description="Hover tooltips on SDL syntax table elements.",
    order=55,
    precompute=_precompute_syntax_tooltips,
)
def _enh_syntax_tooltips(ctx: BuildContext):
    from specbuild.enhancements.sdltooltips import add_syntax_tooltips_soup

    st_data = ctx.precomputed.get("syntax-tooltips", (None, None))
    st_css, st_js = st_data
    if add_syntax_tooltips_soup(ctx.soup, css=st_css, js=st_js):
        ctx.dirty = True


@register_enhancement(
    name="toc-bold-primary-only",
    cli_flags=["--toc-bold-primary-only"],
    description="Only bold top-level TOC entries.",
    order=60,
)
def _enh_toc_bold(ctx: BuildContext):
    from specbuild.utils import inject_css

    inject_css(
        ctx.soup,
        "toc-bold-primary-only-css",
        """
/* TOC: only bold top-level entries */
.toc > li li { font-weight: normal; }
.toc > li[data-level]:not([data-level="1"]) { font-weight: normal; }
""",
    )
    ctx.dirty = True


@register_enhancement(
    name="content-width",
    cli_flags=["--content-width"],
    description="Constrain HTML content width on screen.",
    order=65,
    enabled=lambda args: _resolve_content_width(args) is not None,
)
def _enh_content_width(ctx: BuildContext):
    width = _resolve_content_width(ctx.args)
    from specbuild.utils import inject_css

    inject_css(
        ctx.soup,
        "content-width-css",
        f"""
@media screen {{
  body {{
    max-width: {width};
    margin-left: auto;
    margin-right: auto;
    padding-left: 1em;
    padding-right: 1em;
  }}
}}
""",
    )
    ctx.dirty = True


def _resolve_content_width(args) -> str | None:
    """Resolve content width from CLI args or theme, returning None if disabled."""
    from specbuild.theme import THEME

    width = args.content_width or THEME.content_width
    if width and width.lower() != "none":
        return width
    return None


@register_enhancement(
    name="line-anchors",
    cli_flags=["--line-anchors"],
    description="Deep-linkable line number anchors in code blocks.",
    order=70,
)
def _enh_line_anchors(ctx: BuildContext):
    from specbuild.enhancements.lineanchors import add_line_anchors_soup

    if add_line_anchors_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="pwa",
    cli_flags=["--pwa"],
    description="Progressive Web App for offline viewing.",
    order=75,
)
def _enh_pwa(ctx: BuildContext):
    from specbuild.enhancements.pwa import inject_pwa_soup

    inject_pwa_soup(ctx.soup)
    ctx.dirty = True


@register_enhancement(
    name="stability",
    cli_flags=["--stability"],
    description="Inject section stability badges (new/active).",
    order=80,
)
def _enh_stability(ctx: BuildContext):
    from specbuild.enhancements.stability import analyze_stability, inject_stability_badges_soup

    stability_data = analyze_stability()
    ctx.precomputed["stability"] = stability_data
    if inject_stability_badges_soup(ctx.soup, stability_data):
        ctx.dirty = True


@register_enhancement(
    name="watermark",
    cli_flags=["--watermark"],
    description="Custom watermark overlay (draft, confidential, etc.).",
    order=85,
    enabled=lambda args: args.watermark and args.watermark not in ("bikeshed", "none"),
)
def _enh_watermark(ctx: BuildContext):
    from specbuild.enhancements.watermark import inject_watermark_soup

    inject_watermark_soup(ctx.soup, ctx.args.watermark)
    ctx.dirty = True


@register_enhancement(
    name="suppress-watermark",
    cli_flags=["--watermark"],
    description="Remove all watermarks.",
    order=86,
    enabled=lambda args: args.watermark == "none",
)
def _enh_suppress_watermark(ctx: BuildContext):
    from specbuild.enhancements.watermark import suppress_all_watermarks_soup

    suppress_all_watermarks_soup(ctx.soup)
    ctx.dirty = True


@register_enhancement(
    name="cover-page",
    cli_flags=["--cover-page"],
    description="Add a styled cover page to the document.",
    order=90,
)
def _enh_cover_page(ctx: BuildContext):
    from specbuild.enhancements.coverpage import inject_cover_page_soup

    inject_cover_page_soup(
        ctx.soup,
        title=ctx.args.cover_title,
        subtitle=ctx.args.cover_subtitle,
        doc_number=ctx.args.cover_doc_number,
        date=ctx.spec_date,
        version=f"{ctx.branch_name}@{ctx.sha}",
        logo_path=ctx.args.cover_logo,
        organization=ctx.args.cover_organization,
    )
    ctx.dirty = True


@register_enhancement(
    name="page-numbers",
    cli_flags=["--page-numbers"],
    description="Page numbering style (dual, arabic, or none).",
    order=95,
    enabled=lambda args: args.page_numbers and args.page_numbers != "none",
)
def _enh_page_numbers(ctx: BuildContext):
    from specbuild.enhancements.pagenumbers import inject_page_numbering_soup

    inject_page_numbering_soup(
        ctx.soup, style=ctx.args.page_numbers, use_weasyprint=ctx.args.weasyprint
    )
    ctx.dirty = True


# ═══════════════════════════════════════════════════════════════════════════
# Output tasks (independent, parallelizable)
# ═══════════════════════════════════════════════════════════════════════════


@register_output_task(
    name="pdf",
    cli_flags=["--pdf", "--weasyprint"],
    description="Generate PDF (Chrome or WeasyPrint).",
)
def _out_pdf(ctx: BuildContext):
    from specbuild.output.pdf import generate_pdf

    generate_pdf(
        ctx.target_dir,
        use_weasyprint=ctx.args.weasyprint,
        font_size_increase=ctx.args.pdf_font_increase,
        toc_leaders=ctx.args.toc_leaders,
        equation_font=ctx.args.equation_font,
        equation_scale=ctx.args.equation_scale,
        generate_lof=ctx.args.lof,
        generate_lot=ctx.args.lot,
        front_matter_order=ctx.front_matter_order,
        section_headers=ctx.args.section_headers,
        page_size=ctx.args.page_size,
        optimize_pdf=ctx.args.optimize_pdf,
        no_pdf_tags=ctx.args.no_pdf_tags,
    )


@register_output_task(
    name="docx",
    cli_flags=["--docx"],
    description="Export as Word document (.docx).",
)
def _out_docx(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.docxexport import generate_docx

    ref_doc = Path(ctx.args.docx_template) if ctx.args.docx_template else None
    generate_docx(
        ctx.html_path,
        ctx.target_dir / "spec.docx",
        reference_doc=ref_doc,
        title=CONFIG.spec_full_name,
        branch=ctx.branch_name,
        sha=ctx.sha,
        date=ctx.spec_date,
        page_size=ctx.args.page_size,
    )


@register_output_task(
    name="standalone",
    cli_flags=["--standalone"],
    description="Standalone HTML with all resources inlined.",
)
def _out_standalone(ctx: BuildContext):
    from specbuild.output.standalone import generate_standalone_html

    generate_standalone_html(ctx.html_path)


@register_output_task(
    name="optimize-images",
    cli_flags=["--optimize-images"],
    description="Optimize PNG and SVG images in build output.",
)
def _out_optimize_images(ctx: BuildContext):
    from specbuild.output.imageoptimize import optimize_images, report_optimization

    opt_result = optimize_images(ctx.target_dir)
    report_optimization(opt_result)


@register_output_task(
    name="change-summary",
    cli_flags=["--change-summary"],
    description="Summary of spec changes since a baseline ref.",
)
def _out_change_summary(ctx: BuildContext):
    from specbuild.analysis.changesummary import (
        format_change_summary_markdown,
        generate_change_summary,
    )

    baseline = None if ctx.args.change_summary == "auto" else ctx.args.change_summary
    summary = generate_change_summary(baseline)
    md = format_change_summary_markdown(summary)
    summary_path = ctx.target_dir / "change_summary.md"
    summary_path.write_text(md, encoding="utf-8")
    logging.info(f"Change summary written to {summary_path}")


@register_output_task(
    name="spec-metrics",
    cli_flags=["--spec-metrics"],
    description="Specification metrics (word count, sections, tables).",
)
def _out_spec_metrics(ctx: BuildContext):
    from specbuild.analysis.specmetrics import (
        collect_current_metrics,
        collect_metrics_soup,
        render_metrics_html,
        write_metrics_json,
    )

    metrics = _soup_or_file(collect_metrics_soup, collect_current_metrics, ctx.soup, ctx.html_path)
    if metrics:
        write_metrics_json(metrics, ctx.target_dir / "spec_metrics.json")
        metrics_html = render_metrics_html(metrics)
        (ctx.target_dir / "spec_metrics.html").write_text(metrics_html, encoding="utf-8")
        logging.info(f"Spec metrics written to {ctx.target_dir}")


@register_output_task(
    name="search-index",
    cli_flags=["--search-index"],
    description="Client-side search with Ctrl+K/Cmd+K overlay.",
)
def _out_search_index(ctx: BuildContext):
    from specbuild.enhancements.searchindex import (
        generate_search_index_soup,
        inject_search_ui_soup,
    )
    from specbuild.utils import write_html

    soup = ctx.soup
    if soup is None:
        from specbuild.enhancements.searchindex import generate_search_index

        generate_search_index(ctx.html_path)
        return

    index = generate_search_index_soup(soup)
    inject_search_ui_soup(soup, index)
    write_html(ctx.html_path, soup)


@register_output_task(
    name="pdfa",
    cli_flags=["--pdfa"],
    description="PDF/A-compliant output with metadata.",
)
def _out_pdfa(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.pdfa import generate_pdfa

    generate_pdfa(
        ctx.html_path,
        ctx.target_dir / "spec_pdfa.pdf",
        title=CONFIG.spec_full_name,
        use_weasyprint=ctx.args.weasyprint,
    )


@register_output_task(
    name="xref-report",
    cli_flags=["--xref-report"],
    description="Cross-reference report (inter-section links).",
)
def _out_xref_report(ctx: BuildContext):
    from specbuild.analysis.xrefreport import (
        generate_xref_report,
        generate_xref_report_soup,
        render_xref_html,
        write_xref_report,
    )

    report = _soup_or_file(
        generate_xref_report_soup, generate_xref_report, ctx.soup, ctx.html_path, ctx=ctx
    )
    if report:
        write_xref_report(report, ctx.target_dir / "xref_report.json")
        xref_html = render_xref_html(report)
        (ctx.target_dir / "xref_report.html").write_text(xref_html, encoding="utf-8")
        logging.info(f"Cross-reference report written to {ctx.target_dir}")


@register_output_task(
    name="compliance-matrix",
    cli_flags=["--compliance-matrix"],
    description="RFC 2119 normative statement compliance matrix.",
)
def _out_compliance_matrix(ctx: BuildContext):
    from specbuild.analysis.compliance import (
        generate_compliance_matrix,
        generate_compliance_matrix_soup,
        render_compliance_html,
        write_compliance_matrix,
    )

    matrix = _soup_or_file(
        generate_compliance_matrix_soup, generate_compliance_matrix, ctx.soup, ctx.html_path
    )
    if matrix:
        write_compliance_matrix(matrix, ctx.target_dir / "compliance_matrix.json")
        comp_html = render_compliance_html(matrix)
        (ctx.target_dir / "compliance_matrix.html").write_text(comp_html, encoding="utf-8")
        logging.info(f"Compliance matrix written to {ctx.target_dir}")


@register_output_task(
    name="attribution",
    cli_flags=["--attribution"],
    description="Contributor attribution from git blame.",
)
def _out_attribution(ctx: BuildContext):
    from specbuild.analysis.attribution import (
        generate_attribution,
        render_attribution_html,
        write_attribution,
    )

    data = generate_attribution()
    if data.get("files"):
        write_attribution(data, ctx.target_dir / "attribution.json")
        attr_html = render_attribution_html(data)
        (ctx.target_dir / "attribution.html").write_text(attr_html, encoding="utf-8")
        logging.info(f"Attribution report written to {ctx.target_dir}")


@register_output_task(
    name="stability-report",
    cli_flags=["--stability"],
    description="Section stability analysis report.",
)
def _out_stability_report(ctx: BuildContext):
    from specbuild.enhancements.stability import render_stability_html, write_stability

    data = ctx.precomputed.get("stability")
    if data is None:
        from specbuild.enhancements.stability import analyze_stability

        data = analyze_stability()
    write_stability(data, ctx.target_dir / "stability.json")
    stab_html = render_stability_html(data)
    (ctx.target_dir / "stability.html").write_text(stab_html, encoding="utf-8")
    logging.info(f"Stability report written to {ctx.target_dir}")


@register_output_task(
    name="latex",
    cli_flags=["--latex"],
    description="Export as LaTeX document.",
)
def _out_latex(ctx: BuildContext):
    from specbuild.output.latexexport import export_latex

    export_latex(ctx.html_path, ctx.target_dir / "spec.tex")


@register_output_task(
    name="dfn-index",
    cli_flags=["--dfn-index"],
    description="Definition cross-reference index (glossary).",
)
def _out_dfn_index(ctx: BuildContext):
    from specbuild.analysis.dfnindex import (
        generate_dfn_index,
        generate_dfn_index_soup,
        render_dfn_index_html,
        write_dfn_index,
    )

    data = _soup_or_file(
        generate_dfn_index_soup, generate_dfn_index, ctx.soup, ctx.html_path, ctx=ctx
    )
    if data:
        write_dfn_index(data, ctx.target_dir / "dfn_index.json")
        idx_html = render_dfn_index_html(data)
        (ctx.target_dir / "dfn_index.html").write_text(idx_html, encoding="utf-8")
        logging.info(f"Definition index written to {ctx.target_dir}")


@register_output_task(
    name="pr-summary",
    cli_flags=["--pr-summary"],
    description="PR summary from git diff analysis.",
)
def _out_pr_summary(ctx: BuildContext):
    from specbuild.analysis.prsummary import (
        generate_pr_summary,
        render_pr_summary_html,
        render_pr_summary_markdown,
    )
    from specbuild.config import CONFIG

    baseline = None if ctx.args.pr_summary == "auto" else ctx.args.pr_summary
    data = generate_pr_summary(base_branch=baseline or CONFIG.main_branch)
    md = render_pr_summary_markdown(data)
    (ctx.target_dir / "pr_summary.md").write_text(md, encoding="utf-8")
    pr_html = render_pr_summary_html(data)
    (ctx.target_dir / "pr_summary.html").write_text(pr_html, encoding="utf-8")
    logging.info(f"PR summary written to {ctx.target_dir}")


@register_output_task(
    name="regression",
    cli_flags=["--regression"],
    description="Build regression check against baseline.",
)
def _out_regression(ctx: BuildContext):
    from specbuild.analysis.regression import render_regression_html, report_regression

    if ctx.args.regression == "auto":
        from specbuild.analysis.baseline import compare_with_baseline

        data = compare_with_baseline(ctx.html_path)
    else:
        from specbuild.analysis.regression import compare_builds

        data = compare_builds(ctx.html_path, Path(ctx.args.regression))
    report_regression(data, strict=ctx.args.regression_strict)
    reg_html = render_regression_html(data)
    (ctx.target_dir / "regression_report.html").write_text(reg_html, encoding="utf-8")
    logging.info(f"Regression report written to {ctx.target_dir}")


@register_output_task(
    name="save-baseline",
    cli_flags=["--save-baseline"],
    description="Save structural baseline for future regression checks.",
)
def _out_save_baseline(ctx: BuildContext):
    from specbuild.analysis.baseline import save_baseline

    save_baseline(ctx.html_path)


@register_output_task(
    name="spec-compare",
    cli_flags=["--spec-compare"],
    description="Spec version comparison dashboard.",
)
def _out_spec_compare(ctx: BuildContext):
    from specbuild.analysis.specdiff import generate_spec_comparison, render_comparison_dashboard

    data = generate_spec_comparison(ctx.html_path, Path(ctx.args.spec_compare))
    dashboard_html = render_comparison_dashboard(data)
    (ctx.target_dir / "spec_comparison.html").write_text(dashboard_html, encoding="utf-8")
    logging.info(f"Spec comparison dashboard written to {ctx.target_dir}")


@register_output_task(
    name="normative-deps",
    cli_flags=["--normative-deps"],
    description="Normative dependency graph (cross-section requirements).",
)
def _out_normative_deps(ctx: BuildContext):
    from specbuild.analysis.normdeps import (
        build_normative_graph,
        build_normative_graph_soup,
        render_normative_graph_html,
    )

    graph = _soup_or_file(
        build_normative_graph_soup, build_normative_graph, ctx.soup, ctx.html_path
    )
    graph_html = render_normative_graph_html(graph)
    (ctx.target_dir / "normative_deps.html").write_text(graph_html, encoding="utf-8")
    logging.info(f"Normative dependency graph written to {ctx.target_dir}")


@register_output_task(
    name="release",
    cli_flags=["--release"],
    description="Release automation: baseline, changelog, git tag.",
)
def _out_release(ctx: BuildContext):
    from specbuild.output.release import prepare_release

    result = prepare_release(
        ctx.args.release,
        ctx.html_path,
        ctx.target_dir,
        skip_clean_check=False,
    )
    if not result["success"]:
        logging.error("Release workflow failed")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Standards workflow output tasks
# ---------------------------------------------------------------------------


@register_output_task(
    name="requirement-ids",
    cli_flags=["--requirement-ids"],
    description="Assign stable requirement IDs to normative statements (REQ-<section>-<NNN>).",
)
def _out_requirement_ids(ctx: BuildContext):
    from specbuild.analysis.requirementids import (
        generate_requirement_ids,
        generate_requirement_ids_soup,
        render_requirements_html,
        write_requirements_csv,
        write_requirements_json,
    )

    data = _soup_or_file(
        generate_requirement_ids_soup, generate_requirement_ids, ctx.soup, ctx.html_path
    )
    if data:
        write_requirements_json(data, ctx.target_dir / "requirements.json")
        write_requirements_csv(data, ctx.target_dir / "requirements.csv")
        html = render_requirements_html(data)
        (ctx.target_dir / "requirements.html").write_text(html, encoding="utf-8")
        logging.info(
            f"Requirement IDs: {data['summary']['total']} requirements across "
            f"{data['summary']['sections']} sections"
        )


@register_output_task(
    name="issue-traceability",
    cli_flags=["--issue-traceability"],
    description="Map issues to changed spec sections from git history.",
)
def _out_issue_traceability(ctx: BuildContext):
    from specbuild.analysis.issuetraceability import (
        generate_issue_traceability,
        render_traceability_html,
        write_traceability_json,
    )

    baseline = getattr(ctx.args, "issue_traceability", "auto")
    if baseline is True:
        baseline = "auto"
    data = generate_issue_traceability(baseline=baseline)
    write_traceability_json(data, ctx.target_dir / "issue_traceability.json")
    html = render_traceability_html(data)
    (ctx.target_dir / "issue_traceability.html").write_text(html, encoding="utf-8")
    logging.info(
        f"Issue traceability: {data['summary']['total_issues']} issues, "
        f"{data['summary']['total_sections']} sections"
    )


@register_output_task(
    name="ext-spec-deps",
    cli_flags=["--ext-spec-deps"],
    description="Track external specification dependencies and cross-references.",
)
def _out_ext_spec_deps(ctx: BuildContext):
    from specbuild.analysis.extspecdeps import (
        generate_ext_spec_deps,
        generate_ext_spec_deps_soup,
        render_ext_spec_deps_html,
        write_ext_spec_deps_json,
    )

    data = _soup_or_file(
        generate_ext_spec_deps_soup, generate_ext_spec_deps, ctx.soup, ctx.html_path
    )
    if data:
        write_ext_spec_deps_json(data, ctx.target_dir / "ext_spec_deps.json")
        html = render_ext_spec_deps_html(data)
        (ctx.target_dir / "ext_spec_deps.html").write_text(html, encoding="utf-8")
        logging.info(
            f"External spec deps: {data['summary']['total_external_specs']} specs, "
            f"{data['summary']['total_references']} references"
        )


@register_output_task(
    name="metrics-trend",
    cli_flags=["--metrics-trend"],
    description="Spec metrics trend analysis with section-level growth warnings.",
)
def _out_metrics_trend(ctx: BuildContext):
    from specbuild.analysis.metricstrend import (
        generate_metrics_trend,
        render_metrics_trend_html,
        write_metrics_trend_json,
    )

    baseline_path = getattr(ctx.args, "metrics_trend", None)
    if baseline_path is True or baseline_path == "auto":
        baseline_path = None  # Use saved baseline if available
    elif baseline_path:
        baseline_path = Path(baseline_path)

    data = generate_metrics_trend(ctx.html_path, baseline_path, soup=ctx.soup)
    if data:
        write_metrics_trend_json(data, ctx.target_dir / "metrics_trend.json")
        html = render_metrics_trend_html(data)
        (ctx.target_dir / "metrics_trend.html").write_text(html, encoding="utf-8")
        n_warnings = len(data.get("warnings", []))
        logging.info(f"Metrics trend: {n_warnings} warning(s)")


@register_output_task(
    name="isodoc-xml",
    cli_flags=["--isodoc-xml"],
    description="Export IsoDoc-compatible XML.",
)
def _out_isodoc_xml(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.output.isodocxml import export_isodoc_xml
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    export_isodoc_xml(
        ctx.html_path,
        ctx.target_dir / "spec_isodoc.xml",
        meta,
        ctx.standards_flavor,
        soup=ctx.soup,
    )


@register_output_task(
    name="sts-xml",
    cli_flags=["--sts-xml", "--validate-sts"],
    description="Export NISO STS XML for ISO document management.",
)
def _out_sts_xml(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.output.stsxml import export_sts_xml, validate_sts_xml
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    out_path = ctx.target_dir / "spec_sts.xml"
    export_sts_xml(
        ctx.html_path,
        out_path,
        meta,
        ctx.standards_flavor,
        soup=ctx.soup,
    )

    # Optional validation gate: fail the build if the STS is not DTD-valid.
    if getattr(ctx.args, "validate_sts", False):
        errors = validate_sts_xml(out_path)
        if errors:
            preview = "\n".join(f"  {e}" for e in errors[:25])
            extra = f"\n  ... and {len(errors) - 25} more" if len(errors) > 25 else ""
            raise RuntimeError(
                f"STS XML failed NISO STS 1.2 DTD validation ({len(errors)} error(s)):\n"
                f"{preview}{extra}"
            )
        logging.info("STS XML is valid against the NISO STS 1.2 interchange DTD.")



@register_output_task(
    name="iso-docx",
    cli_flags=["--iso-docx"],
    description="Export ISO-styled Word document.",
)
def _out_iso_docx(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.output.isodocx import generate_iso_docx
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    ref_doc = Path(ctx.args.docx_template) if getattr(ctx.args, "docx_template", None) else None
    generate_iso_docx(
        ctx.html_path,
        ctx.target_dir / "spec_iso.docx",
        metadata=meta,
        flavor=ctx.standards_flavor,
        reference_doc=ref_doc,
        soup=ctx.soup,
    )


@register_output_task(
    name="collection-toc",
    cli_flags=["--collection-toc"],
    description="Generate multi-part standard collection table of contents.",
)
def _out_collection_toc(ctx: BuildContext):
    from specbuild.multipart import generate_collection_toc

    generate_collection_toc(ctx.target_dir / "collection_toc.html")


@register_output_task(
    name="compile-collection",
    cli_flags=["--compile-collection"],
    description="Compile multi-part standard collection into single navigable document.",
)
def _out_compile_collection(ctx: BuildContext):
    from specbuild.multipart import get_multipart_config
    from specbuild.output.collection import compile_collection

    config = get_multipart_config()
    if not config.parts:
        logging.info("No multi-part config; skipping collection compilation")
        return

    parts = []
    for part in config.parts:
        if part.path:
            html_path = Path(part.path) / "index.html"
            if html_path.exists():
                parts.append(
                    {
                        "part_number": part.part_number,
                        "title": part.title,
                        "html_path": html_path,
                    }
                )

    if parts:
        compile_collection(parts, ctx.target_dir / "collection.html", config)


@register_output_task(
    name="conformance-levels",
    cli_flags=["--conformance-levels"],
    description="Generate conformance level compliance matrix.",
)
def _out_conformance_levels(ctx: BuildContext):
    from specbuild.analysis.conformancelevels import generate_conformance_level_matrix

    levels_arg = ctx.args.conformance_levels
    if not levels_arg:
        return
    levels = [part.strip() for part in levels_arg.split(",") if part.strip()]
    generate_conformance_level_matrix(ctx.soup, levels, ctx.target_dir / "conformance_levels.html")


# ═══════════════════════════════════════════════════════════════════════════
# New authoring & workflow features
# ═══════════════════════════════════════════════════════════════════════════


@register_quality_check(
    name="completeness",
    cli_flags=["--completeness", "--completeness-strict"],
    description="Check for TODO/TBD markers, empty sections, and unfilled editor notes.",
)
def _qc_completeness(ctx: BuildContext):
    from specbuild.checks.completeness import (
        check_completeness_soup,
        report_completeness,
        write_completeness_report,
    )

    issues = check_completeness_soup(ctx.soup)
    write_completeness_report(issues, ctx.target_dir / "completeness_report.html")
    report_completeness(issues, strict=getattr(ctx.args, "completeness_strict", False))


@register_output_task(
    name="impact",
    cli_flags=["--impact", "--impact-base"],
    description="Compare current build against a previous build; classify changed sections.",
)
def _out_impact(ctx: BuildContext):
    from specbuild.analysis.changeimpact import (
        compare_html,
        find_base_html,
        write_impact_json,
        write_impact_report,
    )

    base_path = getattr(ctx.args, "impact_base", None)
    base_html = find_base_html(ctx.html_path, base_path)
    if not base_html:
        logging.warning(
            "--impact: no baseline HTML found. Run a previous build first, "
            "or specify --impact-base PATH."
        )
        return

    items = compare_html(base_html, ctx.html_path, new_soup=ctx.soup)
    write_impact_report(items, ctx.target_dir / "impact_report.html")
    write_impact_json(items, ctx.target_dir / "impact_report.json")


@register_output_task(
    name="slides",
    cli_flags=["--slides", "--slides-sections"],
    description="Generate a meeting contribution presentation (.pptx) from the spec.",
)
def _out_slides(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.meetingslides import (
        build_presentation,
        extract_slides_content,
        save_presentation,
    )

    section_ids_arg = getattr(ctx.args, "slides_sections", None)
    section_ids = [s.strip() for s in section_ids_arg.split(",")] if section_ids_arg else None

    slides_content = extract_slides_content(ctx.soup, section_ids)

    import datetime

    metadata = {
        "title": CONFIG.spec_full_name or CONFIG.spec_name or "Specification",
        "subtitle": "Standards Contribution",
        "date": datetime.date.today().isoformat(),
    }

    prs = build_presentation(slides_content, metadata)
    slides_path = ctx.target_dir / f"{CONFIG.spec_name or 'spec'}_slides.pptx"
    save_presentation(prs, slides_path)


@register_output_task(
    name="relaton-enrich",
    cli_flags=["--relaton-enrich", "--relaton-data-dir"],
    description="Enrich bibliography entries with structured Relaton API metadata.",
)
def _out_relaton_enrich(ctx: BuildContext):
    from specbuild.standards.relaton import enrich_bibliography_soup
    from specbuild.utils import write_html

    data_dir_arg = getattr(ctx.args, "relaton_data_dir", None)
    local_dir = Path(data_dir_arg) if data_dir_arg else None

    enriched = enrich_bibliography_soup(ctx.soup, api=True, local_dir=local_dir)
    if enriched:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Relaton: enriched {enriched} bibliography entries")


@register_output_task(
    name="ballot-comments",
    cli_flags=["--ballot-comments"],
    description="Load ballot comment XLSX/CSV and generate an interactive HTML tracker.",
)
def _out_ballot_comments(ctx: BuildContext):
    from specbuild.analysis.ballotcomments import (
        export_comments_json,
        generate_comment_tracker,
        link_comments_to_clauses,
        load_ballot_comments,
    )

    path_arg = getattr(ctx.args, "ballot_comments", None)
    if not path_arg:
        return
    xlsx_path = Path(path_arg)
    if not xlsx_path.exists():
        logging.warning(f"--ballot-comments: file not found: {xlsx_path}")
        return

    comments = load_ballot_comments(xlsx_path)
    comments = link_comments_to_clauses(comments, ctx.soup)
    generate_comment_tracker(comments, ctx.target_dir / "ballot_comments.html")
    export_comments_json(comments, ctx.target_dir / "ballot_comments.json")


@register_output_task(
    name="contribution-cover",
    cli_flags=["--contribution-cover"],
    description="Inject a contribution cover page (JVET/MPEG/AOM) from TOML config.",
)
def _out_contribution_cover(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.contributioncover import (
        inject_cover_page_soup,
        load_contribution_metadata_from_config,
    )
    from specbuild.utils import write_html

    config_data = {}
    meta = load_contribution_metadata_from_config(config_data)
    if not meta.title and not meta.input_doc:
        logging.warning(
            "--contribution-cover: no [standards.contribution] config found. "
            "Add input_doc, title, authors, etc. to specbuild.toml."
        )
        return

    flavor = getattr(CONFIG, "standards_flavor", "jvet")
    if inject_cover_page_soup(ctx.soup, meta, flavor=flavor):
        write_html(ctx.html_path, ctx.soup)


@register_output_task(
    name="xpart-manifest",
    cli_flags=["--xpart-manifest"],
    description="Write xpart_refs.json listing all outgoing cross-part [[xpart:N/id]] references.",
)
def _out_xpart_manifest(ctx: BuildContext):
    from specbuild.multipart import get_multipart_config, inject_cross_part_links_soup
    from specbuild.utils import write_html

    config = get_multipart_config()
    manifest_path = ctx.target_dir / "xpart_refs.json"
    count = inject_cross_part_links_soup(ctx.soup, config, xpart_manifest_path=manifest_path)
    if count:
        write_html(ctx.html_path, ctx.soup)


@register_output_task(
    name="requirements-json",
    cli_flags=["--requirements-json"],
    description="Export requirements manifest JSON for build-to-build diffing (use with --requirement-ids).",
)
def _out_requirements_json(ctx: BuildContext):
    from specbuild.analysis.requirementids import (
        generate_requirement_ids_soup,
        write_requirements_json,
        write_requirements_manifest,
    )
    from specbuild.utils import write_html

    data = generate_requirement_ids_soup(ctx.soup, inject_attrs=True)
    if data:
        write_requirements_json(data, ctx.target_dir / "requirements.json")
        write_requirements_manifest(data, ctx.target_dir / "requirements_manifest.json")
        write_html(ctx.html_path, ctx.soup)
        logging.info(
            f"Requirements JSON: {data['summary']['total']} requirements, "
            f"manifest written to {ctx.target_dir / 'requirements_manifest.json'}"
        )


@register_output_task(
    name="tbx-export",
    cli_flags=["--tbx-export"],
    description="Export terms as ISO 30042 TBX XML",
)
def _out_tbx_export(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.tbxexport import export_tbx

    title = CONFIG.spec_full_name or CONFIG.spec_name or "Terminology"
    output_path = ctx.target_dir / "terminology.tbx"
    result = export_tbx(ctx.soup, output_path, title=title)
    if result:
        logging.info(f"TBX terminology export written to {result}")
    else:
        logging.info("TBX export: no Terms and Definitions section found — skipped")


@register_output_task(
    name="boilerplate-bilingual",
    cli_flags=["--boilerplate-lang"],
    description="Inject bilingual (EN/FR) boilerplate sections for ISO/IEC flavors",
    enabled=lambda args: getattr(args, "boilerplate_lang", "en") != "en",
)
def _out_boilerplate_bilingual(ctx: BuildContext):
    from specbuild.standards.boilerplate import inject_bilingual_boilerplate_soup
    from specbuild.utils import write_html

    lang = getattr(ctx.args, "boilerplate_lang", "en") if ctx.args else "en"
    if lang == "en":
        return

    flavor = ctx.standards_flavor
    if flavor is None:
        logging.debug("boilerplate-bilingual: no active flavor — skipped")
        return
    metadata = ctx.metadata
    count = inject_bilingual_boilerplate_soup(ctx.soup, flavor, metadata, lang=lang)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Bilingual boilerplate injected: {count} section(s) (lang={lang})")


@register_output_task(
    name="boilerplate-stage",
    cli_flags=["--boilerplate-stage"],
    description="Inject stage-specific boilerplate (WD/CD/DIS/FDIS/IS) for ISO/IEC flavors",
    enabled=lambda args: bool(getattr(args, "boilerplate_stage", None)),
)
def _out_boilerplate_stage(ctx: BuildContext):
    from specbuild.standards.boilerplate import inject_stage_boilerplate_soup
    from specbuild.utils import write_html

    stage = getattr(ctx.args, "boilerplate_stage", None) if ctx.args else None
    if not stage:
        return

    flavor = ctx.standards_flavor
    if flavor is None:
        logging.debug("boilerplate-stage: no active flavor — skipped")
        return

    metadata = ctx.metadata
    count = inject_stage_boilerplate_soup(ctx.soup, flavor, metadata, stage=stage)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Stage boilerplate injected: {count} section(s) (stage={stage})")


@register_output_task(
    name="callouts",
    cli_flags=["--callouts"],
    description="Process code callout markers (/* <1> */ and <co> elements)",
)
def _out_callouts(ctx: BuildContext):
    from specbuild.enhancements.callouts import process_callouts_soup
    from specbuild.utils import write_html

    count = process_callouts_soup(ctx.soup)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Callouts: processed {count} callout group(s)")


@register_output_task(
    name="subfigures",
    cli_flags=["--subfigures"],
    description="Process compound figures and inject (a)/(b)/(c) subfigure labels",
)
def _out_subfigures(ctx: BuildContext):
    from specbuild.enhancements.subfigures import process_subfigures_soup
    from specbuild.utils import write_html

    count = process_subfigures_soup(ctx.soup)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Subfigures: processed {count} compound figure(s)")


@register_output_task(
    name="admonitions",
    cli_flags=["--admonitions"],
    description="Process admonition blocks (caution/warning/important/tip): inject labels and CSS",
)
def _out_admonitions(ctx: BuildContext):
    from specbuild.enhancements.admonitions import process_admonitions_soup
    from specbuild.utils import write_html

    count = process_admonitions_soup(ctx.soup)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Admonitions: processed {count} admonition block(s)")


@register_output_task(
    name="rfc-xml",
    cli_flags=["--rfc-xml"],
    description="Export RFC 7991 XML (IETF RFC v3 format)",
)
def _out_rfc_xml(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.rfcxml import export_rfc_xml_soup

    output_path = ctx.target_dir / "rfc.xml"
    title = CONFIG.spec_full_name or CONFIG.spec_name or "RFC"
    xml_str = export_rfc_xml_soup(ctx.soup, {"title": title})
    if xml_str:
        output_path.write_text(xml_str, encoding="utf-8")
        logging.info(f"RFC XML written to {output_path}")
    else:
        logging.info("RFC XML: nothing to export")


@register_output_task(
    name="ats-export",
    cli_flags=["--ats-export"],
    description="Export Abstract Test Suite (ATS) XML for OGC/ISO conformance specs",
)
def _out_ats_export(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.atsexport import export_ats

    output_path = ctx.target_dir / "ats.xml"
    title = CONFIG.spec_full_name or CONFIG.spec_name or "Abstract Test Suite"
    result = export_ats(ctx.soup, output_path, title=title)
    if result:
        logging.info(f"ATS XML written to {result}")
    else:
        logging.info("ATS export: no requirements found — skipped")


@register_output_task(
    name="cite-macros",
    cli_flags=["--cite-macros"],
    description="Process {{cite:DocID}} macros into bibliography anchor links",
)
def _out_cite_macros(ctx: BuildContext):
    from specbuild.enhancements.citemacro import process_cite_macros_soup
    from specbuild.utils import write_html

    count = process_cite_macros_soup(ctx.soup)
    if count:
        write_html(ctx.html_path, ctx.soup)
        logging.info(f"Cite macros: replaced {count} citation macro(s)")


# ═══════════════════════════════════════════════════════════════════════════
# New typography & prose enhancements
# ═══════════════════════════════════════════════════════════════════════════


@register_enhancement(
    name="typography",
    cli_flags=["--typography"],
    description="Smart typography: curly quotes, em-dashes, ellipsis.",
    order=42,
)
def _enh_typography(ctx: BuildContext):
    from specbuild.enhancements.typography import process_typography_soup

    french = getattr(ctx.args, "french_spacing", False)
    if process_typography_soup(ctx.soup, french_spacing=bool(french)):
        ctx.dirty = True


@register_enhancement(
    name="math-symbols",
    cli_flags=["--math-symbols"],
    description="Replace ASCII math approximations with Unicode symbols.",
    order=43,
)
def _enh_math_symbols(ctx: BuildContext):
    from specbuild.enhancements.mathsymbols import process_math_symbols_soup

    if process_math_symbols_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="passthrough",
    cli_flags=["--passthrough"],
    description="Inject raw HTML/XML from data-passthrough elements.",
    order=44,
)
def _enh_passthrough(ctx: BuildContext):
    from specbuild.enhancements.passthrough import process_passthrough_soup

    if process_passthrough_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="term-links",
    cli_flags=["--term-links"],
    description="Auto-link term occurrences to their definition anchors.",
    order=45,
)
def _enh_term_links(ctx: BuildContext):
    from specbuild.enhancements.termlinker import process_term_links_soup

    if process_term_links_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="smart-xrefs",
    cli_flags=["--smart-xrefs"],
    description="Rewrite generic cross-reference text to include Figure/Table/Clause labels.",
    order=46,
)
def _enh_smart_xrefs(ctx: BuildContext):
    from specbuild.enhancements.smartxref import process_smart_xrefs_soup

    if process_smart_xrefs_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="iso-body-numbering",
    cli_flags=["--iso-body-numbering"],
    description="Sequential body figure/table numbering (Figure 1, 2, …; Annex: Figure A.1, …).",
    order=7,
)
def _enh_iso_body_numbering(ctx: BuildContext):
    from specbuild.enhancements.isonumbering import number_figures_soup, number_tables_soup

    count = number_figures_soup(ctx.soup) + number_tables_soup(ctx.soup)
    if count:
        ctx.dirty = True


@register_enhancement(
    name="inject-aria",
    cli_flags=["--inject-aria"],
    description="Inject WCAG 2.1 ARIA landmark roles on structural HTML elements.",
    order=48,
)
def _enh_inject_aria(ctx: BuildContext):
    from specbuild.checks.accessibility import inject_aria_roles

    if inject_aria_roles(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="bibformat-normalize",
    cli_flags=["--bibformat-normalize"],
    description="Normalize and deduplicate bibliography entries per the active flavor's citation style.",
    order=9,
)
def _enh_bibformat_normalize(ctx: BuildContext):
    from specbuild.standards.bibformat import (
        deduplicate_bibliography_soup,
        normalize_bibliography_soup,
    )

    flavor_name = ctx.standards_flavor.name if ctx.standards_flavor else ""
    count = normalize_bibliography_soup(ctx.soup, flavor_name=flavor_name, relaton_cache={})
    count += deduplicate_bibliography_soup(ctx.soup)
    if count:
        ctx.dirty = True


@register_enhancement(
    name="pseudocode",
    cli_flags=["--pseudocode"],
    description="Style pseudocode/algorithm blocks with ISO-style line numbering.",
    order=47,
)
def _enh_pseudocode(ctx: BuildContext):
    from specbuild.enhancements.pseudocode import process_pseudocode_soup

    if process_pseudocode_soup(ctx.soup):
        ctx.dirty = True


@register_enhancement(
    name="figure-sources",
    cli_flags=["--figure-sources"],
    description="Style 'Source: ...' attribution text in figure captions.",
    order=51,
)
def _enh_figure_sources(ctx: BuildContext):
    from specbuild.enhancements.figuresource import process_figure_sources_soup

    if process_figure_sources_soup(ctx.soup):
        ctx.dirty = True


# ═══════════════════════════════════════════════════════════════════════════
# New output tasks
# ═══════════════════════════════════════════════════════════════════════════


@register_output_task(
    name="epub",
    cli_flags=["--epub"],
    description="Export as EPUB3 for e-reader distribution.",
)
def _out_epub(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.epubexport import export_epub

    metadata = {
        "title": CONFIG.spec_full_name or CONFIG.spec_name or "",
        "creator": "",
        "docid": CONFIG.spec_name or "specbuild-doc",
    }
    output_path = ctx.target_dir / f"{CONFIG.spec_name or 'spec'}.epub"
    image_base_dir = ctx.html_path.parent if ctx.html_path else None
    result = export_epub(ctx.soup, output_path, metadata, image_base_dir=image_base_dir)
    if result:
        logging.info(f"EPUB written to {result}")
    else:
        logging.info("EPUB export: no body content found — skipped")


@register_output_task(
    name="errata",
    cli_flags=["--errata"],
    description="Inject errata markers and generate HTML tracker from CSV/JSON file.",
    enabled=lambda args: bool(getattr(args, "errata", None)),
)
def _out_errata(ctx: BuildContext):
    from pathlib import Path as _Path

    from specbuild.analysis.errata import (
        export_errata_json,
        generate_errata_html,
        inject_errata_markers_soup,
        load_errata_csv,
        load_errata_json,
    )
    from specbuild.utils import write_html

    path_arg = getattr(ctx.args, "errata", None)
    if not path_arg:
        return
    errata_path = _Path(path_arg)
    if not errata_path.exists():
        logging.warning(f"--errata: file not found: {errata_path}")
        return

    if errata_path.suffix.lower() == ".json":
        errata = load_errata_json(errata_path)
    else:
        errata = load_errata_csv(errata_path)

    injected = inject_errata_markers_soup(ctx.soup, errata)
    if injected:
        write_html(ctx.html_path, ctx.soup)

    generate_errata_html(errata, ctx.target_dir / "errata.html")
    export_errata_json(errata, ctx.target_dir / "errata.json")
    logging.info(f"Errata: {len(errata)} entries, {injected} marker(s) injected")


# ═══════════════════════════════════════════════════════════════════════════
# Localization, RTL, and code presentation enhancements
# ═══════════════════════════════════════════════════════════════════════════


@register_enhancement(
    name="localize-labels",
    cli_flags=["--doc-language"],
    description="Translate figure/table/note/annex labels to the document language.",
    order=38,
    enabled=lambda args: getattr(args, "doc_language", "en") not in ("en", None),
)
def _enh_localize_labels(ctx: BuildContext):
    from specbuild.standards.boilerplate import inject_localized_labels

    lang = getattr(ctx.args, "doc_language", "en") or "en"
    if inject_localized_labels(ctx.soup, lang=lang):
        ctx.dirty = True


@register_enhancement(
    name="inject-rtl",
    cli_flags=["--inject-rtl"],
    description="Inject RTL CSS for right-to-left document languages.",
    order=39,
)
def _enh_inject_rtl(ctx: BuildContext):
    from specbuild.utils import inject_css

    inject_css(
        ctx.soup,
        "rtl-css",
        "body { direction: rtl; text-align: right; }\n.toc, .toc ol, .toc li { direction: rtl; }\n",
    )
    ctx.dirty = True


@register_enhancement(
    name="mathml-a11y",
    cli_flags=["--mathml-a11y"],
    description="Add ARIA labels and display attributes to MathML elements.",
    order=41,
)
def _enh_mathml_a11y(ctx: BuildContext):
    from specbuild.enhancements.mathml import inject_mathml_css, process_mathml_accessibility_soup

    count = process_mathml_accessibility_soup(ctx.soup)
    if count:
        inject_mathml_css(ctx.soup)
        ctx.dirty = True


@register_enhancement(
    name="line-numbers",
    cli_flags=["--line-numbers"],
    description="Add line numbers to source code blocks.",
    order=71,
    enabled=lambda args: getattr(args, "line_numbers", "none") not in ("none", None),
)
def _enh_line_numbers(ctx: BuildContext):
    from specbuild.enhancements.linenumbers import process_line_numbers_soup

    style = getattr(ctx.args, "line_numbers", "gutter") or "gutter"
    if process_line_numbers_soup(ctx.soup, style=style):
        ctx.dirty = True


@register_enhancement(
    name="copy-code-buttons",
    cli_flags=["--copy-code-buttons"],
    description="Add copy-to-clipboard buttons to source code blocks.",
    order=72,
)
def _enh_copy_code_buttons(ctx: BuildContext):
    from specbuild.enhancements.clipboard import inject_copy_buttons_soup

    if inject_copy_buttons_soup(ctx.soup):
        ctx.dirty = True


# ═══════════════════════════════════════════════════════════════════════════
# New quality checks
# ═══════════════════════════════════════════════════════════════════════════


@register_quality_check(
    name="validate-rfc2119",
    cli_flags=["--validate-rfc2119", "--validate-rfc2119-strict"],
    description="Validate RFC 2119 keyword usage in normative/informative sections.",
)
def _qc_validate_rfc2119(ctx: BuildContext):
    from specbuild.checks.rfc2119validate import check_rfc2119_usage_soup, report_rfc2119_validation

    issues = check_rfc2119_usage_soup(ctx.soup)
    report_rfc2119_validation(issues, strict=getattr(ctx.args, "validate_rfc2119_strict", False))
    if ctx.report is not None:
        ctx.report.rfc2119_issues = issues


@register_quality_check(
    name="math-lint",
    cli_flags=["--math-lint", "--math-lint-strict"],
    description="Lint math/equation fragments for paren balance and symbol consistency.",
)
def _qc_math_lint(ctx: BuildContext):
    from specbuild.checks.mathlint import report_math_lint, run_math_lint

    result = run_math_lint(ctx.soup)
    if ctx.report is not None:
        ctx.report.math_lint_issues = result
    report_math_lint(result, strict=getattr(ctx.args, "math_lint_strict", False))


@register_quality_check(
    name="check-xpart-refs",
    cli_flags=["--check-xpart-refs", "--check-xpart-refs-strict"],
    description="Validate cross-part references resolve to valid anchors.",
)
def _qc_check_xpart_refs(ctx: BuildContext):
    from specbuild.checks.xpartcheck import check_cross_part_refs_soup, report_cross_part_ref_issues

    issues = check_cross_part_refs_soup(ctx.soup, parts_dir=ctx.target_dir.parent)
    report_cross_part_ref_issues(issues, strict=getattr(ctx.args, "check_xpart_refs_strict", False))


@register_quality_check(
    name="check-xrefs",
    cli_flags=["--check-xrefs", "--check-xrefs-strict"],
    description="Validate all cross-references: internal anchors (XREF-1), cross-part links (XREF-2), and bibliography erefs (XREF-3).",
)
def _qc_check_xrefs(ctx: BuildContext):
    from specbuild.checks.xrefcheck import check_xrefs_soup, report_xref_issues

    parts_dir = ctx.target_dir.parent if ctx.target_dir else None
    issues = check_xrefs_soup(ctx.soup, parts_dir=parts_dir, ctx=ctx)
    report_xref_issues(issues, strict=getattr(ctx.args, "check_xrefs_strict", False))


# ═══════════════════════════════════════════════════════════════════════════
# New output tasks
# ═══════════════════════════════════════════════════════════════════════════


@register_output_task(
    name="doc-relations",
    cli_flags=["--doc-relations"],
    description="Extract and inject document relation metadata (supersedes, amends, etc.).",
)
def _out_doc_relations(ctx: BuildContext):
    from specbuild.standards.docrelations import (
        extract_relations_from_soup,
        inject_relations_metadata,
        render_relations_html,
    )
    from specbuild.utils import write_html

    relations = extract_relations_from_soup(ctx.soup)
    injected = inject_relations_metadata(ctx.soup, relations)
    if injected:
        write_html(ctx.html_path, ctx.soup)
    html = render_relations_html(relations)
    (ctx.target_dir / "doc_relations.html").write_text(html, encoding="utf-8")
    logging.info(f"Document relations: {len(relations.relations)} relation(s) found")


@register_output_task(
    name="relaton-export",
    cli_flags=["--relaton-export"],
    description="Export document as Relaton JSON/XML for Metanorma interoperability.",
    enabled=lambda args: bool(getattr(args, "relaton_export", None)),
)
def _out_relaton_export(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.standards.metadata import resolve_metadata
    from specbuild.standards.relatonexport import (
        build_relaton_record,
        export_relaton_json,
        export_relaton_xml,
    )

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    flavor_name = getattr(ctx.args, "standards_flavor", None)
    record = build_relaton_record(ctx.soup, meta, flavor=flavor_name)
    fmt = getattr(ctx.args, "relaton_export", "json") or "json"
    output_path = ctx.target_dir / f"relaton.{fmt}"
    if fmt == "xml":
        export_relaton_xml(record, output_path)
    else:
        export_relaton_json(record, output_path)
    logging.info(f"Relaton {fmt.upper()} written to {output_path}")


# ═══════════════════════════════════════════════════════════════════════════
# New enhancements: Metanorma gap-fill batch 2
# ═══════════════════════════════════════════════════════════════════════════


@register_enhancement(
    name="svg-accessibility",
    cli_flags=["--svg-accessibility"],
    description="Add ARIA roles, title/desc, and viewBox normalization to inline SVG elements.",
    order=52,
)
def _enh_svg_accessibility(ctx: BuildContext):
    from specbuild.enhancements.svgaccessibility import (
        inject_svg_accessibility_css,
        process_svg_accessibility_soup,
    )

    count = process_svg_accessibility_soup(ctx.soup)
    if count:
        inject_svg_accessibility_css(ctx.soup)
    logging.info(f"SVG accessibility: processed {count} SVG element(s)")


@register_enhancement(
    name="note-numbers",
    cli_flags=["--note-numbers"],
    description="Number NOTE and EXAMPLE blocks sequentially per top-level clause.",
    order=53,
)
def _enh_note_numbers(ctx: BuildContext):
    from specbuild.enhancements.notenumbering import process_note_numbers_soup

    count = process_note_numbers_soup(ctx.soup)
    logging.info(f"Note numbering: updated {count} label(s)")


@register_enhancement(
    name="abbreviations",
    cli_flags=["--abbreviations"],
    description="Auto-extract abbreviations from <abbr> tags and inline patterns.",
    order=54,
)
def _enh_abbreviations(ctx: BuildContext):
    from specbuild.enhancements.abbreviations import extract_abbreviations_soup

    count = extract_abbreviations_soup(ctx.soup)
    logging.info(f"Abbreviations: processed {count} abbreviation(s)")


@register_enhancement(
    name="checklists",
    cli_flags=["--checklists"],
    description="Convert [ ] / [x] checklist items to HTML checkboxes.",
    order=55,
)
def _enh_checklists(ctx: BuildContext):
    from specbuild.enhancements.checklists import process_checklists_soup

    count = process_checklists_soup(ctx.soup)
    logging.info(f"Checklists: converted {count} item(s)")


@register_enhancement(
    name="contributor-block",
    cli_flags=["--contributor-block"],
    description="Render structured contributor/editor table from document metadata.",
    order=56,
)
def _enh_contributor_block(ctx: BuildContext):
    from specbuild.enhancements.contributorblock import process_contributor_block_soup

    count = process_contributor_block_soup(ctx.soup)
    logging.info(f"Contributor block: rendered {count} contributor(s)")


@register_enhancement(
    name="code-attribution",
    cli_flags=["--code-attribution"],
    description="Render source attribution for code blocks.",
    order=57,
)
def _enh_code_attribution(ctx: BuildContext):
    from specbuild.enhancements.clipboard import process_code_attribution_soup

    count = process_code_attribution_soup(ctx.soup)
    logging.info(f"Code attribution: processed {count} block(s)")


@register_enhancement(
    name="html-lang",
    cli_flags=["--html-lang"],
    description="Inject lang attribute on <html> element from document language metadata.",
    order=58,
)
def _enh_html_lang(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.standards.boilerplate import inject_html_lang_attr

    lang = getattr(ctx.args, "doc_language", None) or STANDARDS.language or "en"
    inject_html_lang_attr(ctx.soup, lang=lang)
    logging.info(f"HTML lang attribute set to '{lang}'")


@register_enhancement(
    name="term-crossrefs",
    cli_flags=["--term-crossrefs"],
    description="Auto-link first occurrence of defined terms in body text to their definitions.",
    order=59,
)
def _enh_term_crossrefs(ctx: BuildContext):
    from specbuild.enhancements.termsformat import auto_link_term_references_soup

    count = auto_link_term_references_soup(ctx.soup)
    logging.info(f"Term cross-references: linked {count} occurrence(s)")


@register_enhancement(
    name="toc-depth",
    cli_flags=["--toc-depth"],
    description="Limit table of contents depth via CSS injection.",
    enabled=lambda args: getattr(args, "toc_depth", None) is not None,
    order=60,
)
def _enh_toc_depth(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.enhancements.tocdepth import apply_toc_depth_soup

    depth = getattr(ctx.args, "toc_depth", None) or CONFIG.toc_depth
    apply_toc_depth_soup(ctx.soup, depth=depth)


@register_enhancement(
    name="autolink",
    cli_flags=["--autolink"],
    description="Auto-link clause/table/figure/annex cross-references in prose.",
    order=61,
)
def _enh_autolink(ctx: BuildContext):
    from specbuild.enhancements.autolink import auto_link_xrefs_soup

    count = auto_link_xrefs_soup(ctx.soup)
    logging.info(f"Autolink: linked {count} cross-reference(s)")


@register_enhancement(
    name="seo",
    cli_flags=["--seo"],
    description="Inject SEO meta tags (og:title, description, twitter:card, keywords, canonical).",
    order=62,
)
def _enh_seo(ctx: BuildContext):
    from specbuild.enhancements.seo import inject_seo_metadata_soup

    count = inject_seo_metadata_soup(ctx.soup)
    logging.info(f"SEO: injected {count} meta tag(s)")


@register_enhancement(
    name="code-lang-labels",
    cli_flags=["--code-lang-labels"],
    description="Inject language labels above code blocks.",
    order=63,
)
def _enh_code_lang_labels(ctx: BuildContext):
    from specbuild.enhancements.lineanchors import inject_code_language_labels_soup

    count = inject_code_language_labels_soup(ctx.soup)
    logging.info(f"Code language labels: added {count} label(s)")


@register_enhancement(
    name="print-css",
    cli_flags=["--print-css"],
    description="Inject print-optimised CSS for page-break control and layout polish.",
    order=64,
)
def _enh_print_css(ctx: BuildContext):
    from specbuild.enhancements.pagenumbers import inject_print_css_soup

    inject_print_css_soup(ctx.soup)
    logging.info("Print CSS injected")


@register_enhancement(
    name="bib-links",
    cli_flags=["--bib-links"],
    description="Inject hyperlinks for DOI, RFC, Internet-Draft, W3C identifiers in bibliography.",
    order=65,
)
def _enh_bib_links(ctx: BuildContext):
    from specbuild.enhancements.bibformat import inject_bib_hyperlinks_soup

    count = inject_bib_hyperlinks_soup(ctx.soup)
    logging.info(f"Bibliography hyperlinks: injected {count} link(s)")


@register_enhancement(
    name="unit-spacing",
    cli_flags=["--unit-spacing"],
    description="Insert non-breaking spaces between numbers and SI/technical unit symbols.",
    order=66,
)
def _enh_unit_spacing(ctx: BuildContext):
    from specbuild.enhancements.typography import inject_unit_spacing_soup

    count = inject_unit_spacing_soup(ctx.soup)
    logging.info(f"Unit spacing: modified {count} text node(s)")


@register_output_task(
    name="verification-matrix",
    cli_flags=["--verification-matrix"],
    description="Generate a conformance verification matrix HTML report.",
)
def _out_verification_matrix(ctx: BuildContext):
    from specbuild.analysis.verificationmatrix import generate_verification_matrix

    if ctx.html_path is None:
        return
    output_path = ctx.html_path.parent / "verification_matrix.html"
    result = generate_verification_matrix(ctx.soup, output_path)
    if result:
        logging.info(f"Verification matrix written to {result}")


@register_output_task(
    name="relaton-bib",
    cli_flags=["--relaton-bib"],
    description="Export bibliography as a Relaton XML collection (ISO 30042 / Metanorma format).",
)
def _out_relaton_bib(ctx: BuildContext):
    from specbuild.config import STANDARDS
    from specbuild.output.relatonxml import export_relaton_xml
    from specbuild.standards.metadata import resolve_metadata

    meta = ctx.metadata or resolve_metadata(ctx.args, STANDARDS, ctx.soup)
    output_path = ctx.target_dir / "relaton-bibliography.xml"
    export_relaton_xml(ctx.html_path, output_path, meta, flavor=ctx.standards_flavor, soup=ctx.soup)


@register_output_task(
    name="error-log",
    cli_flags=["--error-log"],
    description="Write build warnings and errors to <spec>.err.html (equivalent to Metanorma .err.html).",
)
def _out_error_log(ctx: BuildContext):
    from specbuild.config import CONFIG
    from specbuild.output.errlog import export_error_log

    stem = CONFIG.spec_name or "spec"
    output_path = ctx.target_dir / f"{stem}.err.html"
    export_error_log(output_path)


@register_output_task(
    name="aom-boilerplate",
    cli_flags=["--aom-boilerplate"],
    description="Strip spurious 'AOM ' prefix from profile-and-date heading (Bikeshed workaround).",
)
def _out_aom_boilerplate(ctx: BuildContext):
    from specbuild.enhancements.aomboilerplate import apply_aom_boilerplate

    apply_aom_boilerplate(ctx.html_path)

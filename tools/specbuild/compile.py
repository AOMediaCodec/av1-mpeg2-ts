#!/usr/bin/env python3
"""Build driver for the Bikeshed specification.

This is a thin CLI wrapper around the ``specbuild`` package.  All logic lives
in the package modules; this file only parses arguments and orchestrates the
high-level build steps.

Usage::

    python compile.py                  # basic build
    python compile.py --diff           # build + HTML diff against main
    python compile.py --pdf            # build + PDF via Chrome
    python compile.py --weasyprint     # build + PDF via WeasyPrint
    python compile.py --watch          # auto-rebuild on source changes
    python compile.py --multipage      # multipage HTML output

See ``python compile.py -h`` for the full list of options.
"""

from __future__ import annotations

import argparse
import inspect
import logging
import subprocess
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import specbuild
import specbuild.plugin_registry  # noqa: F401  - populate plugin registry
from specbuild.builder import compile_spec
from specbuild.cli import build_parser, expand_all_checks, resolve_manifest
from specbuild.config import CONFIG, autodetect_layout, load_config
from specbuild.config import STANDARDS as _STANDARDS
from specbuild.git import resolve_build_identity
from specbuild.merge import parse_manifest_front_matter
from specbuild.plugins import generate_feature_help, get_enabled_plugins
from specbuild.postprocess import (
    copy_spec,
    generate_syntax_browser,
    inject_links,
)
from specbuild.utils import zip_directory

# Set PROJECT_ROOT to this file's directory so specbuild locates scripts/,
# config/, and css/ from the project that contains compile.py — not from
# the specbuild package directory.  This is essential when specbuild is
# imported via PYTHONPATH or pip from a different repository.
specbuild.PROJECT_ROOT = Path(__file__).resolve().parent


def _specbuild_version() -> str:
    """Return the SpecBuild version string.

    Resolution order:
    1. ``importlib.metadata`` (works when installed via pip).
    2. Nearest git tag reachable from PROJECT_ROOT (dev / editable installs).
    3. ``version`` field parsed from ``pyproject.toml`` (vendored copies
       extracted via ``git archive``, where there is no ``.git`` to query).
    4. Literal ``"unknown"`` only if all of the above fail.
    """
    try:
        from importlib.metadata import version as _meta_version

        return _meta_version("specbuild")
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(specbuild.PROJECT_ROOT),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    try:
        import tomllib

        with (specbuild.PROJECT_ROOT / "pyproject.toml").open("rb") as f:
            data = tomllib.load(f)
        v = data.get("project", {}).get("version")
        if v:
            return str(v)
    except Exception:
        pass
    return "unknown"


if TYPE_CHECKING:
    from bs4 import BeautifulSoup

    from specbuild.analysis.buildreport import BuildReportData
    from specbuild.standards.flavors import FlavorSpec


# ---------------------------------------------------------------------------
# Concurrent task helper
# ---------------------------------------------------------------------------

_MAX_PARALLEL_WORKERS = 16  # cap for thread pools (quality checks, precompute, output tasks)


def _run_concurrent_tasks(
    tasks: list[tuple[str, Callable[[], None]]],
    label: str,
) -> None:
    """Run named tasks concurrently and surface the first failure.

    Args:
        tasks: List of ``(name, callable)`` pairs to execute.
        label: Human-readable category for error messages (e.g. "Quality check").
    """
    errors: list[tuple[str, Exception]] = []
    with ThreadPoolExecutor(max_workers=min(len(tasks), _MAX_PARALLEL_WORKERS)) as executor:
        futures = {executor.submit(fn): name for name, fn in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                errors.append((futures[future], exc))
    if errors:
        for name, exc in errors:
            logging.error(f"{label} '{name}' failed: {exc}")
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Enhancement & quality-check helpers
# ---------------------------------------------------------------------------


def _precompute_enhancements(plugins, args: argparse.Namespace) -> dict:
    """Pre-compute data shared by multiple enhancement plugins.

    Some plugins declare a ``precompute`` attribute — a callable that returns
    data to be stored in :attr:`BuildContext.precomputed`.  This function
    runs all precompute callables, deduplicating where possible (e.g. two
    plugins that share the same baseline reference only resolve it once).

    Returns:
        A dict mapping precompute key → result, ready for BuildContext.
    """
    precomputed: dict = {}
    tasks: dict[str, Callable] = {}
    for p in plugins:
        pc = getattr(p, "precompute", None)
        if pc is not None:
            # Pass args to precompute functions that accept a parameter
            sig = inspect.signature(pc)
            tasks[p.name] = partial(pc, args) if sig.parameters else pc

    if not tasks:
        return precomputed

    # Deduplicate change-bars / table-of-changes when they share a baseline
    cb_fn = tasks.get("change-bars")
    toc_fn = tasks.get("table-of-changes")
    if (
        cb_fn
        and toc_fn
        and "change-bars" in tasks
        and "table-of-changes" in tasks
        and getattr(args, "table_of_changes", None) == getattr(args, "change_bars", None)
    ):
        del tasks["table-of-changes"]

    if len(tasks) == 1:
        key, fn = next(iter(tasks.items()))
        return {key: fn()}

    with ThreadPoolExecutor(max_workers=min(len(tasks), _MAX_PARALLEL_WORKERS)) as executor:
        future_map = {executor.submit(fn): key for key, fn in tasks.items()}
        for future in as_completed(future_map):
            precomputed[future_map[future]] = future.result()

    # Share result when table-of-changes was deduped
    if "change-bars" in precomputed and "table-of-changes" not in precomputed and toc_fn:
        precomputed["table-of-changes"] = precomputed["change-bars"]

    return precomputed


def _run_enhancements(
    args: argparse.Namespace,
    html_path: Path,
    spec_date: str,
    branch_name: str,
    sha: str,
    standards_flavor: FlavorSpec | None = None,
) -> tuple[BeautifulSoup | None, dict]:
    """Run registry-driven enhancements on the compiled HTML.

    Enhancements modify the HTML (inject CSS, add page numbers, etc.) and
    are applied sequentially in the order defined by the plugin registry.

    Returns:
        Tuple of ``(soup, precomputed)`` where *precomputed* is the dict
        built during the precompute phase (may be empty).  Returns
        ``(None, {})`` if no enhancements ran.
    """
    from specbuild.context import BuildContext
    from specbuild.utils import read_html, write_html

    plugins = get_enabled_plugins("enhancement", args)
    if not plugins:
        return None, {}

    precomputed = _precompute_enhancements(plugins, args)

    ctx = BuildContext(
        args=args,
        html_path=html_path,
        target_dir=html_path.parent,
        branch_name=branch_name,
        sha=sha,
        spec_date=spec_date,
        precomputed=precomputed,
        standards_flavor=standards_flavor,
    )

    soup = read_html(html_path)
    ctx.soup = soup

    if standards_flavor is not None:
        from specbuild.config import STANDARDS
        from specbuild.standards.metadata import resolve_metadata

        ctx.metadata = resolve_metadata(args, STANDARDS, soup)

    for p in plugins:
        logging.debug(f"Enhancement: {p.name}")
        p.func(ctx)
        if ctx.report:
            ctx.report.add_enhancement(p.name)

    write_html(html_path, soup)

    return soup, ctx.precomputed


def _run_quality_checks(
    args: argparse.Namespace,
    html_path: Path,
    soup: BeautifulSoup | None = None,
    *,
    report: BuildReportData | None = None,
    standards_flavor: FlavorSpec | None = None,
) -> None:
    """Run read-only quality checks on the compiled HTML.

    Plugins are discovered from the registry via
    :func:`~specbuild.plugins.get_enabled_plugins` and executed
    concurrently in a thread pool.

    Args:
        args:      Parsed CLI arguments (controls which checks run).
        html_path: Path to the compiled ``index.html``.
        soup:      Pre-parsed BeautifulSoup tree (may be ``None``).
        report:    Optional build report to receive check results.
    """
    from specbuild.context import BuildContext, compute_lookup_maps

    plugins = get_enabled_plugins("quality_check", args)
    if not plugins:
        return

    ctx = BuildContext(
        args=args,
        html_path=html_path,
        target_dir=html_path.parent,
        soup=soup,
        report=report,
        standards_flavor=standards_flavor,
    )
    # Build {id: element} and {href: [<a>, ...]} maps once; quality checks
    # share them via ctx.precomputed instead of re-walking the soup.
    if soup is not None:
        ctx.precomputed.update(compute_lookup_maps(soup))

    checks_to_run = [(p.name, lambda p=p: p.func(ctx)) for p in plugins]

    if len(checks_to_run) == 1:
        # Single check — no need for thread pool overhead
        checks_to_run[0][1]()
    else:
        logging.debug(
            f"Running {len(checks_to_run)} quality checks in parallel: "
            f"{', '.join(name for name, _ in checks_to_run)}"
        )
        _run_concurrent_tasks(checks_to_run, "Quality check")


# ---------------------------------------------------------------------------
# Validate-only mode
# ---------------------------------------------------------------------------


def _find_latest_output_html() -> Path | None:
    """Return the index.html in the most-recently-modified output directory.

    Scans the current working directory for directories whose names match the
    ``output_dir_template`` pattern and returns the ``index.html`` from the
    one with the most-recent modification time.  Returns ``None`` if no
    candidate is found.
    """
    import glob

    pattern = (
        CONFIG.output_dir_template.replace("{date}", "*")
        .replace("{sha}", "*")
        .replace("{spec_name}", "*")
    )
    candidates = sorted(
        (p for p in glob.glob(pattern) if (Path(p) / "index.html").exists()),
        key=lambda p: Path(p).stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return Path(candidates[0]) / "index.html"
    return None


def _run_validate_only(args: argparse.Namespace) -> None:
    """Run all quality checks against an existing compiled HTML file.

    This path skips Bikeshed compilation, enhancements, and output generation.
    It resolves the HTML file to validate, parses it, runs every quality check
    enabled by *args* (after expanding ``--all-checks``), prints a summary, and
    exits with code 1 if any check reported an issue.

    Args:
        args: Parsed CLI arguments (must already have ``expand_all_checks``
              applied and ``validate_only`` set to ``True``).

    Raises:
        SystemExit: Always — exits 0 on success, 1 on any check failure.
    """
    from specbuild.utils import read_html

    # --- Locate the HTML file ---
    if args.validate_path:
        html_path = Path(args.validate_path)
    else:
        html_path = _find_latest_output_html()

    if html_path is None:
        logging.error(
            "Could not find a compiled index.html to validate. "
            "Run the build first, or pass --validate-path PATH."
        )
        raise SystemExit(1)

    if not html_path.exists():
        logging.error(f"HTML file not found: {html_path}")
        raise SystemExit(1)

    logging.info(f"Validating: {html_path}")

    # --- Parse ---
    soup = read_html(html_path)

    # --- Run quality checks ---
    # We re-use _run_quality_checks but capture exceptions so we can count them.
    from specbuild.context import BuildContext
    from specbuild.plugins import get_enabled_plugins

    plugins = get_enabled_plugins("quality_check", args)
    if not plugins:
        logging.warning("No quality checks enabled. Pass --all-checks or specific --check-* flags.")
        print("0 checks run, 0 issues found.")
        raise SystemExit(0)

    ctx = BuildContext(
        args=args,
        html_path=html_path,
        target_dir=html_path.parent,
        soup=soup,
    )

    checks_run = 0
    failures: list[tuple[str, Exception]] = []

    checks_to_run = [(p.name, lambda p=p: p.func(ctx)) for p in plugins]

    with ThreadPoolExecutor(max_workers=min(len(checks_to_run), _MAX_PARALLEL_WORKERS)) as executor:
        futures = {executor.submit(fn): name for name, fn in checks_to_run}
        for future in as_completed(futures):
            name = futures[future]
            checks_run += 1
            try:
                future.result()
            except Exception as exc:
                failures.append((name, exc))
                logging.error(f"Check '{name}' failed: {exc}")

    passed = checks_run - len(failures)
    print(f"{passed} check(s) passed, {len(failures)} issue(s) found.")
    raise SystemExit(1 if failures else 0)


# ---------------------------------------------------------------------------
# Build pipeline
# ---------------------------------------------------------------------------


def _run_compile(
    args: argparse.Namespace,
    manifest_path: Path | None,
    target_dir: Path,
    _step: Callable,
) -> None:
    """Merge, compile with Bikeshed, and copy to the target directory."""
    if CONFIG.source_format == "asciidoc":
        from specbuild.builder_adoc import compile_adoc_spec, locate_adoc_entry_point

        with _step("Compile"):
            base_dir = Path(CONFIG.asciidoc_source_dir) if CONFIG.asciidoc_source_dir else None
            adoc_path = locate_adoc_entry_point(base_dir)
            compile_adoc_spec(adoc_path, output_html=Path("index.html"))
    else:
        with _step("Compile"):
            compile_spec(
                convert_sdl=args.convert_sdl,
                compact=args.compact,
                remove_editor_notes_flag=args.remove_editor_notes,
                override_date=args.date,
                striped_code_blocks=args.striped_code_blocks,
                auto_indent_code=args.auto_indent_code,
                manifest_path=manifest_path,
                bikeshed_die_on=args.bikeshed_die_on,
                include_sections=args.include_sections,
                exclude_sections=args.exclude_sections,
            )
            if args.diff and not args.convert_sdl:
                compile_spec(
                    diff_hack=True,
                    convert_sdl=False,
                    compact=args.compact,
                    remove_editor_notes_flag=args.remove_editor_notes,
                    override_date=args.date,
                    striped_code_blocks=args.striped_code_blocks,
                    auto_indent_code=args.auto_indent_code,
                    manifest_path=manifest_path,
                    bikeshed_die_on=args.bikeshed_die_on,
                    include_sections=args.include_sections,
                    exclude_sections=args.exclude_sections,
                )

    with _step("Post-process"):
        copy_spec(
            target_dir,
            externalize=args.externalize_resources,
            minify=args.minify,
            mobile_optimized=args.mobile_optimized,
        )


def _run_enhancements_phase(
    args: argparse.Namespace,
    html_path: Path,
    target_dir: Path,
    spec_date: str,
    branch_name: str,
    sha: str,
    source_hash: str | None,
    report: BuildReportData | None,
    _step: Callable,
    standards_flavor: FlavorSpec | None = None,
) -> tuple[BeautifulSoup | None, dict]:
    """Run enhancements and quality checks, respecting incremental caching.

    Returns:
        Tuple of ``(soup, precomputed)`` where *precomputed* is the dict
        computed during the enhancement phase (empty if enhancements were
        skipped).
    """
    skip_enhancements = False
    if args.incremental:
        from specbuild.incremental import should_skip_enhancements

        skip_enh, enh_reason = should_skip_enhancements(html_path, args)
        if skip_enh:
            logging.info(f"Incremental build: skipping enhancements ({enh_reason})")
            skip_enhancements = True
        else:
            logging.info(f"Incremental build: will run enhancements ({enh_reason})")

    if not skip_enhancements:
        with _step("Enhancements"):
            soup, precomputed = _run_enhancements(
                args, html_path, spec_date, branch_name, sha, standards_flavor
            )

        with _step("Quality checks"):
            _run_quality_checks(
                args, html_path, soup, report=report, standards_flavor=standards_flavor
            )

        if args.incremental:
            from specbuild.incremental import compute_enhancement_hash
            from specbuild.incremental import save_cache as _save_cache

            enh_hash = compute_enhancement_hash(html_path, args)
            _save_cache(source_hash or "", str(target_dir), enhancement_hash=enh_hash)

        return soup, precomputed

    logging.info("Using cached enhancements")
    return None, {}


def _run_diff_phase(
    args: argparse.Namespace,
    target_dir: Path,
    _step: Callable,
) -> None:
    """Run diff generation, diff viewer, and diff explorer."""
    if not (args.diff or args.diff_viewer or args.diff_explorer):
        return

    with _step("Diff"):
        from specbuild.output.diff import diff_spec

        diff_spec(
            target_dir,
            args.no_clone,
            args.diff_sha,
            args.convert_sdl,
            args.compact,
            args.remove_editor_notes,
            args.date,
            args.striped_code_blocks,
        )

    if args.diff_viewer:
        with _step("Diff viewer"):
            from specbuild.output.diffviewer import generate_diff_viewer

            anchor_dir = Path(CONFIG.main_branch_clone_dir)
            generate_diff_viewer(target_dir, anchor_dir=anchor_dir)

    if args.diff_explorer:
        with _step("Diff explorer"):
            from specbuild.output.diffexplorer import generate_diff_explorer

            anchor_dir = Path(CONFIG.main_branch_clone_dir)
            generate_diff_explorer(target_dir, anchor_dir=anchor_dir)


def _run_output_phase(
    args: argparse.Namespace,
    html_path: Path,
    target_dir: Path,
    branch_name: str,
    sha: str,
    spec_date: str,
    front_matter_order: list[str] | None,
    _step: Callable,
    standards_flavor: FlavorSpec | None = None,
    soup: BeautifulSoup | None = None,
    precomputed: dict | None = None,
) -> None:
    """Run registry-driven output tasks and post-output steps."""
    from specbuild.context import BuildContext

    output_plugins = get_enabled_plugins("output_task", args)

    if output_plugins:
        out_ctx = BuildContext(
            args=args,
            html_path=html_path,
            target_dir=target_dir,
            branch_name=branch_name,
            sha=sha,
            spec_date=spec_date,
            front_matter_order=front_matter_order,
            standards_flavor=standards_flavor,
            precomputed=precomputed or {},
        )
        if soup is not None:
            out_ctx.soup = soup

        if standards_flavor is not None:
            from specbuild.config import STANDARDS
            from specbuild.standards.metadata import resolve_metadata

            out_ctx.metadata = resolve_metadata(args, STANDARDS, soup or out_ctx.soup)

        # search-index writes back to index.html; run it sequentially first to avoid
        # racing with parallel output tasks that read the same file
        # These output tasks mutate ctx.soup and write back to ctx.html_path; running
        # them concurrently with each other (or with parallel readers) causes lost
        # writes and BS4 mutation races.  Run them sequentially before the parallel pool.
        sequential_names = {
            "search-index",
            "relaton-enrich",
            "contribution-cover",
            "xpart-manifest",
            "requirements-json",
            "callouts",
            "subfigures",
            "admonitions",
            "cite-macros",
            "errata",
            "doc-relations",
            # These re-nest the flat heading stream into <section> wrappers in
            # place (and otherwise mutate out_ctx.soup); running them
            # concurrently corrupts each other's tree (e.g. truncated IsoDoc
            # when STS runs alongside). Keep them sequential.
            "sts-xml",
            "isodoc-xml",
            "iso-docx",
        }
        sequential_tasks = [
            (n, fn)
            for n, fn in [(p.name, lambda p=p: p.func(out_ctx)) for p in output_plugins]
            if n in sequential_names
        ]
        output_tasks = [
            (p.name, lambda p=p: p.func(out_ctx))
            for p in output_plugins
            if p.name not in sequential_names
        ]

        for name, fn in sequential_tasks:
            with _step(name):
                fn()

        if args.parallel_outputs and len(output_tasks) > 1:
            logging.info(
                f"Running {len(output_tasks)} output steps in parallel: "
                f"{', '.join(name for name, _ in output_tasks)}"
            )
            with _step("Parallel outputs"):
                _run_concurrent_tasks(output_tasks, "Output step")
        else:
            for name, fn in output_tasks:
                with _step(name):
                    fn()

    # Syntax browser
    if args.syntax_browser:
        if not args.convert_sdl:
            logging.warning("Syntax browser requires SDL tables to be enabled.")
            logging.warning(
                "Please run again without the --sdl flag (SDL tables are enabled by default)"
            )
        else:
            with _step("Syntax browser"):
                generate_syntax_browser(target_dir)

    # Multipage
    if args.multipage:
        with _step("Multipage"):
            from specbuild.output.multipage import run_multipage

            run_multipage(args, target_dir, branch_name, sha, spec_date)

    # Post-output
    if args.links:
        inject_links(target_dir)

    if args.pwa:
        from specbuild.enhancements.pwa import generate_pwa_files

        generate_pwa_files(target_dir)

    if args.zip:
        with _step("ZIP archive"):
            zip_path = str(target_dir.resolve()) + ".zip"
            zip_directory(zip_path, target_dir)


def _handle_source_detection(args: argparse.Namespace) -> None:
    """Auto-detect source format and transparently convert Metanorma to Bikeshed.

    Called early in main() — before import modes and profile application.
    Mutates CONFIG.bikeshed_dir if conversion is performed.
    """
    import tempfile

    from specbuild.config import CONFIG
    from specbuild.detect import detect_source_format

    # Explicit --source path takes priority; otherwise use CWD
    source_path_str = getattr(args, "source", None)
    fmt_override = getattr(args, "source_format", None) or "auto"

    if source_path_str:
        source_path = Path(source_path_str)
    else:
        # Only auto-detect CWD if the configured bikeshed_dir doesn't exist yet
        bs_dir = Path(CONFIG.bikeshed_dir)
        if bs_dir.exists():
            return  # Bikeshed project already in place, nothing to do
        source_path = Path.cwd()

    if fmt_override == "auto" or fmt_override is None:
        fmt = detect_source_format(source_path)
    else:
        fmt = fmt_override

    if fmt == "bikeshed":
        if source_path_str:
            # Point bikeshed_dir at the explicit source
            bs_candidate = source_path if source_path.is_dir() else source_path.parent
            if (bs_candidate / "bikeshed").exists():
                CONFIG.bikeshed_dir = str(bs_candidate / "bikeshed")
            elif (bs_candidate / "manifest.txt").exists():
                CONFIG.bikeshed_dir = str(bs_candidate)
        return  # nothing to convert

    if fmt == "asciidoc":
        logging.info(f"Detected AsciiDoc source at {source_path} — will compile with asciidoctor…")
        CONFIG.source_format = "asciidoc"
        CONFIG.sdl_files = ()
        CONFIG.asciidoc_source_dir = str(
            source_path if source_path.is_dir() else source_path.parent
        )
        return

    if fmt == "metanorma":
        from specbuild.convert.metanorma import convert_project

        logging.info(f"Detected Metanorma/AsciiDoc source at {source_path} — auto-converting…")
        tmp = tempfile.mkdtemp(prefix="specbuild-metanorma-")
        result = convert_project(
            source_path,
            tmp,
            overwrite=True,
            scaffold=False,
        )
        bs_dir_out = Path(tmp) / "bikeshed"
        CONFIG.bikeshed_dir = str(bs_dir_out)
        CONFIG.sdl_files = ()

        # Load generated specbuild.toml if present (metadata, flavor, etc.)
        generated_toml = Path(tmp) / "specbuild.toml"
        if generated_toml.exists():
            from specbuild.config import load_config

            load_config(generated_toml)
            CONFIG.bikeshed_dir = str(bs_dir_out)  # load_config may reset it

        warnings = result.get("warnings", [])
        if warnings:
            for w in warnings[:5]:
                logging.warning(f"  converter: {w}")
            if len(warnings) > 5:
                logging.warning(f"  … and {len(warnings) - 5} more converter warning(s)")

        logging.info(
            f"Auto-conversion complete: {len(result.get('sections', []))} section(s) → {bs_dir_out}"
        )
        return

    if source_path_str:
        # Explicit --source with unrecognised format
        logging.warning(
            f"Could not detect source format at {source_path}. "
            "Proceeding with default bikeshed_dir."
        )


def _write_build_report(
    report: BuildReportData,
    report_handler: logging.Handler | None,
    report_format: str,
    timer,
    soup: BeautifulSoup | None,
    html_path: Path,
    target_dir: Path,
) -> None:
    """Collect timing data, analyze sections, and write the build report."""
    if timer:
        for name, elapsed in timer.steps:
            report.add_step(name, elapsed)

    if html_path.exists():
        from specbuild.utils import get_bs4, read_html

        try:
            get_bs4()
            report_soup = soup if soup is not None else read_html(html_path)
            from specbuild.analysis.buildreport import analyze_sections_soup

            report.sections, report.total_words = analyze_sections_soup(report_soup)
        except ImportError:
            logging.debug("bs4 not available; skipping section analysis in build report")

    if report_handler:
        logging.getLogger().removeHandler(report_handler)

    from specbuild.analysis.buildreport import write_html_report, write_json_report

    if report_format in ("html", "both"):
        write_html_report(report, target_dir / "build_report.html")
    if report_format in ("json", "both"):
        write_json_report(report, target_dir / "build_report.json")


def _run_build(
    args: argparse.Namespace,
    manifest_path: Path | None,
    front_matter_order: list[str] | None,
    standards_flavor: FlavorSpec | None = None,
) -> None:
    """Execute the full build pipeline.

    This is separated from :func:`main` so it can be called repeatedly by
    watch mode.
    """
    from specbuild.timing import BuildTimer

    timer = BuildTimer() if args.timing else None

    # --- Build report setup ---
    report = None
    report_handler = None
    if args.build_report:
        from specbuild.analysis.buildreport import BuildReportData, ReportLogHandler

        report = BuildReportData()
        report.cli_flags = {k: v for k, v in vars(args).items()}
        report_handler = ReportLogHandler(report)
        logging.getLogger().addHandler(report_handler)

    # --- Error log setup (must be early to capture all build messages) ---
    if getattr(args, "error_log", False):
        from specbuild.output.errlog import install_handler as _install_errlog_handler

        _install_errlog_handler()

    def _step(name):
        return timer.step(name) if timer else nullcontext()

    # --- Incremental build check ---
    skip_compile = False
    source_hash = None
    if args.incremental:
        from specbuild.incremental import should_skip_compile

        skip_compile, reason, source_hash = should_skip_compile(manifest_path=manifest_path)
        if skip_compile:
            logging.info(f"Incremental build: skipping compilation ({reason})")
        else:
            logging.info(f"Incremental build: will recompile ({reason})")

    # --- Resolve build identity ---
    branch_name, sha, spec_date, target_dir = resolve_build_identity(
        branch_override=args.branch, date_override=args.date
    )
    logging.debug(
        f"args.branch={args.branch}, branch_name={branch_name}, sha={sha}, spec_date={spec_date}"
    )
    logging.info(f"Building '{CONFIG.spec_name}' — {branch_name}@{sha} ({spec_date})")

    if report:
        report.branch = branch_name
        report.sha = sha
        report.date = spec_date
        report.spec_title = CONFIG.spec_full_name

    # --- Compile ---
    if not skip_compile:
        _run_compile(args, manifest_path, target_dir, _step)
    else:
        logging.info(f"Using cached output in {target_dir}")

    if args.incremental:
        from specbuild.incremental import save_cache

        if source_hash is None:
            from specbuild.incremental import compute_source_hash

            source_hash = compute_source_hash(manifest_path=manifest_path)
        save_cache(source_hash, str(target_dir))

    # --- Post-compile phases (enhancements, diff, output) ---
    # Wrap in try/except so that partial output is flagged on failure.
    try:
        # --- Enhancements & quality checks ---
        html_path = target_dir / "index.html"
        soup, precomputed = _run_enhancements_phase(
            args,
            html_path,
            target_dir,
            spec_date,
            branch_name,
            sha,
            source_hash,
            report,
            _step,
            standards_flavor,
        )

        # --- Diff & Output tasks ---
        # When both diff and output tasks are active they write to different
        # files (diff.html vs pdf/docx/etc.) so they can safely run in parallel.
        diff_requested = bool(args.diff or args.diff_viewer or args.diff_explorer)
        output_tasks_requested = bool(
            get_enabled_plugins("output_task", args)
            or args.syntax_browser
            or args.multipage
            or args.links
            or args.pwa
            or args.zip
        )

        if diff_requested and output_tasks_requested:
            with ThreadPoolExecutor(max_workers=2) as executor:
                diff_future = executor.submit(_run_diff_phase, args, target_dir, _step)
                output_future = executor.submit(
                    _run_output_phase,
                    args,
                    html_path,
                    target_dir,
                    branch_name,
                    sha,
                    spec_date,
                    front_matter_order,
                    _step,
                    standards_flavor,
                    soup,
                    precomputed,
                )
                diff_future.result()
                output_future.result()
        else:
            # --- Diff ---
            _run_diff_phase(args, target_dir, _step)

            # --- Output tasks, multipage, post-output ---
            _run_output_phase(
                args,
                html_path,
                target_dir,
                branch_name,
                sha,
                spec_date,
                front_matter_order,
                _step,
                standards_flavor,
                soup,
                precomputed,
            )
    except Exception:
        logging.error(f"Build failed after compilation. Partial output may remain in: {target_dir}")
        raise

    # --- Test-vector manifest validation + coverage report ---
    if getattr(args, "testvector_manifest", None):
        try:
            from specbuild.standards.testvectors import (
                generate_coverage_matrix,
                load_manifest,
                report_validation_issues,
                validate_manifest,
                write_coverage_report,
            )
            from specbuild.utils import read_html as _tv_read_html

            tv_manifest_path = Path(args.testvector_manifest)
            vectors = load_manifest(tv_manifest_path)
            issues = validate_manifest(
                vectors,
                tv_manifest_path.parent,
                check_hashes=not getattr(args, "testvector_no_hashes", False),
            )
            report_validation_issues(issues)

            if soup is None:
                soup = _tv_read_html(html_path)
            matrix = generate_coverage_matrix(vectors, soup)
            report_path = target_dir / "testvector_coverage.html"
            write_coverage_report(matrix, vectors, report_path)
            logging.info(
                "Test-vector coverage report written: %s (%d vectors, %d/%d clauses covered)",
                report_path,
                len(vectors),
                matrix.get("covered_clauses", 0),
                matrix.get("total_clauses", 0),
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — never fail the build over coverage
            logging.warning(f"Test-vector manifest processing failed: {exc}")

    # --- Codesync report (compare C++ READ_* macros to SDL syntax tables) ---
    if getattr(args, "codesync", None):
        try:
            from specbuild.checks.codesync import run_codesync

            cpp_arg, out_arg = args.codesync
            cpp_path = Path(cpp_arg)
            report_path = Path(out_arg)
            if not report_path.is_absolute():
                report_path = target_dir / report_path
            diffs = run_codesync(cpp_path, html_path, report_path)
            logging.info(
                "Codesync report written: %s (%d diff entries)",
                report_path,
                len(diffs),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the build over codesync
            logging.warning(f"Codesync report generation failed: {exc}")

    # --- Bitstream-syntax crosswalk diff between two SDL-tagged sources ---
    if getattr(args, "syntax_diff", None):
        try:
            from specbuild.analysis.syntaxdiff import run_syntaxdiff

            old_arg, new_arg = args.syntax_diff
            html_out = target_dir / "syntax_diff.html"
            json_out = target_dir / "syntax_diff.json"
            records = run_syntaxdiff(Path(old_arg), Path(new_arg), html_out, json_out)
            logging.info(
                "Syntax-diff report written: %s (%d records)",
                html_out,
                len(records),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the build
            logging.warning(f"Syntax-diff report generation failed: {exc}")

    # --- Profile/level/tier consistency validation ---
    if getattr(args, "profiles_spec", None):
        try:
            from specbuild.checks.profilevalidate import (
                load_profiles_spec,
                report_issues,
                validate_profiles,
            )
            from specbuild.utils import read_html as _ps_read_html

            ps_path = Path(args.profiles_spec)
            ps_profiles = load_profiles_spec(ps_path)
            ps_soup = soup if soup is not None else _ps_read_html(html_path)
            ps_issues = validate_profiles(ps_profiles, ps_soup)
            report_issues(
                ps_issues,
                strict=bool(getattr(args, "profiles_spec_strict", False)),
            )
            logging.info(
                "Profiles-spec check: %d profile(s), %d issue(s)",
                len(ps_profiles),
                len(ps_issues),
            )
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001 — never fail the build
            logging.warning(f"Profiles-spec validation failed: {exc}")

    # --- Test-vector crosswalk (cross-spec coverage migration) ---
    if getattr(args, "testvector_crosswalk", None):
        try:
            from specbuild.standards.testvectors import run_crosswalk

            old_arg, new_arg = args.testvector_crosswalk
            cmap = getattr(args, "testvector_clause_map", None)
            cw_html = target_dir / "testvector_crosswalk.html"
            cw = run_crosswalk(
                Path(old_arg),
                Path(new_arg),
                cw_html,
                clause_map_path=Path(cmap) if cmap else None,
            )
            logging.info(
                "Testvector crosswalk: unchanged=%d retargeted=%d retired=%d",
                len(cw["unchanged"]),
                len(cw["retargeted"]),
                len(cw["retired"]),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the build
            logging.warning(f"Testvector crosswalk failed: {exc}")

    # --- Errata backport patch generation ---
    if getattr(args, "backport_errata", None):
        try:
            from specbuild.output.errataport import backport_errata

            tb = getattr(args, "target_branch", None)
            if not tb:
                logging.warning("--backport-errata requires --target-branch; skipping.")
            else:
                backport_errata(
                    Path(args.backport_errata),
                    tb,
                    target_dir,
                )
        except Exception as exc:  # noqa: BLE001 — never fail the build
            logging.warning(f"Errata backport failed: {exc}")

    # --- Provenance manifest (after all HTML mutations complete) ---
    if getattr(args, "provenance", False):
        try:
            from specbuild.output.provenance import write_provenance

            asset_dirs: list[Path] = []
            for sub in ("css", "js", "images"):
                candidate = Path(sub)
                if candidate.is_dir():
                    asset_dirs.append(candidate)

            build_identity = {
                "branch": branch_name,
                "sha": sha,
                "date": spec_date,
                "spec_name": CONFIG.spec_name,
            }
            prov_path = write_provenance(
                target_dir,
                bs_dir=Path(CONFIG.bikeshed_dir),
                html_path=html_path,
                asset_dirs=asset_dirs,
                build_identity=build_identity,
            )
            logging.info(f"Wrote provenance manifest: {prov_path}")
        except Exception as exc:  # noqa: BLE001 — never fail the build over provenance
            logging.warning(f"Failed to write provenance.json: {exc}")

    # --- Build report ---
    if report:
        _write_build_report(
            report,
            report_handler,
            args.build_report,
            timer,
            soup,
            html_path,
            target_dir,
        )

    # --- AI-assisted review (opt-in; reads local files only) ---
    if getattr(args, "ai_review", False):
        try:
            from specbuild.analysis.aireview import run_ai_review

            run_ai_review(
                repo_root=Path.cwd(),
                baseline=getattr(args, "ai_review_baseline", "auto"),
                output_path=target_dir / "ai_review.md",
                dry_run=getattr(args, "ai_review_dry_run", False),
            )
        except Exception as exc:  # noqa: BLE001 — never fail the build over AI review
            logging.warning(f"--ai-review failed: {exc}")

    # --- Timing report ---
    if timer:
        timer.report()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments, configure logging, and run the build pipeline."""
    parser = build_parser()
    args = parser.parse_args()

    from specbuild.logsetup import setup_logging

    setup_logging(args.log_level)

    # Load spec configuration from file (specbuild.toml or pyproject.toml)
    config_path = Path(args.config) if args.config else None
    load_config(config_path)
    autodetect_layout()

    # Load custom profiles from TOML if specified
    if args.profiles_file:
        import specbuild.profiles as _profiles_mod
        from specbuild.profiles import get_merged_profiles

        merged = get_merged_profiles(Path(args.profiles_file))
        _profiles_mod.PROFILES = merged

    # Handle --help-features
    if args.help_features:
        print(generate_feature_help())
        return

    # Handle --list-profiles
    if args.list_profiles:
        from specbuild.profiles import list_profiles

        print(list_profiles())
        return

    # Handle --diagnose
    if args.diagnose:
        from specbuild.diagnose import run_diagnose

        raise SystemExit(run_diagnose())

    # Handle --bib-enrich (one-shot bibliography enrichment, not a build step)
    if getattr(args, "bib_enrich", None):
        from specbuild.standards.bibenrich import enrich_bib_file

        bib_path = Path(args.bib_enrich)
        if not bib_path.exists():
            logging.error(f"Bibliography file not found: {bib_path}")
            raise SystemExit(1)
        try:
            n = enrich_bib_file(bib_path, bib_path)
        except Exception as exc:  # noqa: BLE001
            logging.error(f"Bibliography enrichment failed: {exc}")
            raise SystemExit(1) from exc
        logging.info(f"Enriched {n} bibliography entr{'y' if n == 1 else 'ies'} in {bib_path}")
        raise SystemExit(0)

    # Handle --list-templates
    if args.list_templates:
        import specbuild.templates.catalog  # noqa: F401 - populate TEMPLATES
        from specbuild.templates import TEMPLATES, list_templates

        names = list_templates()
        if not names:
            print("No templates available.")
            return
        print("Available spec templates:\n")
        for name in names:
            tmpl = TEMPLATES[name]
            desc = tmpl.get("description", "")
            flavor = tmpl.get("flavor", "")
            print(f"  {name:<25s} [{flavor}] {desc}")
        print("\nUse --new-from-template NAME to scaffold a new project.")
        return

    # Handle --new-from-template
    if args.new_from_template:
        import specbuild.templates.catalog  # noqa: F401 - populate TEMPLATES
        from specbuild.templates import get_template, list_templates

        tmpl = get_template(args.new_from_template)
        if tmpl is None:
            logging.error(
                f"Unknown template: {args.new_from_template!r}. "
                f"Available: {', '.join(list_templates())}"
            )
            raise SystemExit(1)
        # Scaffold the project directory
        tmpl_name = tmpl["name"]
        project_dir = Path(tmpl_name)
        if project_dir.exists():
            logging.error(f"Directory already exists: {project_dir}")
            raise SystemExit(1)
        bs_dir = project_dir / "bikeshed"
        bs_dir.mkdir(parents=True)
        manifest_lines = []
        for section in tmpl.get("sections", []):
            fname = section["filename"]
            (bs_dir / fname).write_text(section.get("stub_content", ""), encoding="utf-8")
            manifest_lines.append(fname)
        (bs_dir / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
        logging.info(f"Created project from template '{tmpl_name}' in {project_dir}/")
        logging.info(f"  Sections: {len(tmpl.get('sections', []))}")
        logging.info(f"  Suggested profile: {tmpl.get('suggested_profile', 'default')}")
        return

    # Handle --new-clause (one-shot clause scaffolding; exits before build)
    if getattr(args, "new_clause", None):
        from specbuild.templates.clause_templates import list_clause_types, render_clause

        clause_type, title = args.new_clause
        try:
            snippet = render_clause(clause_type, title)
        except ValueError as exc:
            logging.error(str(exc))
            logging.error(f"Available types: {', '.join(list_clause_types())}")
            raise SystemExit(1) from exc
        out_path = getattr(args, "new_clause_file", None)
        if out_path:
            Path(out_path).write_text(snippet, encoding="utf-8")
            logging.info(f"Wrote {clause_type} clause to {out_path}")
        else:
            print(snippet)
        raise SystemExit(0)

    # Handle --export-sdl (one-shot extraction from compiled HTML; exits before build)
    if getattr(args, "export_sdl", None):
        import glob as _glob

        from specbuild.output.sdlexport import export_sdl as _export_sdl
        from specbuild.utils import read_html as _read_html

        # Find a compiled index.html: prefer the most recent output dir.
        pattern = (
            CONFIG.output_dir_template.replace("{date}", "*")
            .replace("{sha}", "*")
            .replace("{spec_name}", "*")
        )
        matches = sorted(_glob.glob(pattern), reverse=True)
        html_candidate: Path | None = None
        for m in matches:
            cand = Path(m) / "index.html"
            if cand.exists():
                html_candidate = cand
                break
        if html_candidate is None:
            fallback = Path("index.html")
            if fallback.exists():
                html_candidate = fallback
        if html_candidate is None:
            logging.error(
                "--export-sdl: no compiled index.html found. "
                "Run a build first or pass --export-sdl after compilation."
            )
            raise SystemExit(1)
        try:
            soup = _read_html(html_candidate)
            written = _export_sdl(soup, Path(args.export_sdl))
        except Exception as exc:  # noqa: BLE001 - never crash on export
            logging.error(f"--export-sdl failed: {exc}")
            raise SystemExit(1) from exc
        logging.info(f"--export-sdl: wrote {len(written) - 1} headers to {args.export_sdl}")
        raise SystemExit(0)

    # --- Transparent source format detection ---
    # If --source is given (or CWD looks like a Metanorma project and bikeshed/ is absent),
    # detect the format and auto-convert Metanorma → Bikeshed before compilation.
    _handle_source_detection(args)

    # --- Import mode ---
    if args.import_docx:
        from specbuild.input import import_docx

        output_dir = Path(args.import_output_dir or CONFIG.bikeshed_dir)
        result = import_docx(
            Path(args.import_docx),
            output_dir,
            split_level=args.import_split_level,
            detect_sdl=args.import_detect_sdl,
            extract_symbols=args.import_extract_symbols,
            flavor=args.import_flavor or "",
            syntax_format=getattr(args, "import_syntax_format", "table"),
        )
        logging.info(f"Import complete: {len(result.get('bs_files', []))} .bs files generated")
        CONFIG.bikeshed_dir = str(output_dir)
        CONFIG.sdl_files = ()
        if not any(
            getattr(args, f, False)
            for f in ("pdf", "docx", "diff", "standards_flavor", "profile", "all_checks")
        ):
            return

    if args.import_pdf:
        from specbuild.input import import_pdf

        output_dir = Path(args.import_output_dir or CONFIG.bikeshed_dir)
        result = import_pdf(
            Path(args.import_pdf),
            output_dir,
            split_level=args.import_split_level,
            flavor=args.import_flavor or "",
        )
        logging.info(f"Import complete: {len(result.get('bs_files', []))} .bs files generated")
        CONFIG.bikeshed_dir = str(output_dir)
        CONFIG.sdl_files = ()
        if not any(
            getattr(args, f, False)
            for f in ("pdf", "docx", "diff", "standards_flavor", "profile", "all_checks")
        ):
            return

    # Apply profile if specified
    if args.profile:
        from specbuild.profiles import apply_profile

        parser_defaults = vars(parser.parse_args([]))
        apply_profile(args, args.profile, parser_defaults=parser_defaults)

    # --no-pdf overrides any PDF flags set by a profile (or by the user).
    if getattr(args, "no_pdf", False):
        cleared = [k for k in ("pdf", "weasyprint", "pdfa") if getattr(args, k, False)]
        if cleared:
            logging.info(f"--no-pdf: skipping PDF generation ({', '.join(cleared)} cleared)")
        for k in ("pdf", "weasyprint", "pdfa"):
            if hasattr(args, k):
                setattr(args, k, False)

    # --no-pwa overrides any --pwa set by a profile (or by the user). A
    # cache-first service worker can mask newer content when the spec is served
    # from a shared path, so allow a profile's PWA to be turned off explicitly.
    if getattr(args, "no_pwa", False) and getattr(args, "pwa", False):
        logging.info("--no-pwa: skipping PWA/service-worker generation")
        args.pwa = False

    # Engine default for PDF generation: WeasyPrint unless --chrome-pdf is set.
    # `args.weasyprint` is the truth-of-which-engine flag throughout the
    # codebase, so we normalize it here once — after profiles have applied
    # so the flip catches `--profile publication` and similar that set
    # `pdf=True` without specifying an engine.
    if args.pdf and not getattr(args, "chrome_pdf", False):
        args.weasyprint = True

    # --serve disables PWA generation: a registered service worker would
    # cache-first every fetch and serve stale HTML/CSS/JS forever, defeating
    # both the rebuild loop and the livereload signal.
    if getattr(args, "serve", False) and getattr(args, "pwa", False):
        logging.info("--serve: disabling --pwa (service worker would block livereload)")
        args.pwa = False

    # Expand --all-checks into individual quality-check flags
    expand_all_checks(args)

    # --- Validate-only mode (early exit — no compilation) ---
    if getattr(args, "validate_only", False):
        _run_validate_only(args)
        return  # _run_validate_only always raises SystemExit; belt-and-suspenders

    # --- Resolve standards flavor ---
    from specbuild.standards import get_active_flavor

    if args.standards_flavor:
        _STANDARDS.flavor = args.standards_flavor
    if args.standards_stage:
        _STANDARDS.stage = args.standards_stage
    if args.iso_docnumber:
        _STANDARDS.docnumber = args.iso_docnumber
    if args.base_document:
        _STANDARDS.base_document = args.base_document
    if args.amendment_number:
        _STANDARDS.amendment_number = args.amendment_number
    if args.conformance_levels:
        _STANDARDS.conformance_levels = tuple(
            level.strip() for level in args.conformance_levels.split(",") if level.strip()
        )

    _active_flavor = get_active_flavor(_STANDARDS.flavor)

    # Apply SDO theme overrides
    if _active_flavor:
        from specbuild.standards.sdothemes import apply_flavor_theme

        apply_flavor_theme(_active_flavor)

    # Apply CLI overrides to CONFIG
    if args.x86_python:
        CONFIG.x86_python_path = args.x86_python

    # Validate manifest path early
    manifest_path = resolve_manifest(args)
    front_matter_order = None
    if manifest_path is not None:
        front_matter_order = parse_manifest_front_matter(manifest_path)

    # Auto-enable LOF/LOT if listed in manifest front-matter
    if front_matter_order:
        if "lof" in front_matter_order and not args.lof and not args.no_lof:
            args.lof = True
            logging.debug("Manifest: auto-enabled --lof (listed in [front-matter])")
        if "lot" in front_matter_order and not args.lot and not args.no_lot:
            args.lot = True
            logging.debug("Manifest: auto-enabled --lot (listed in [front-matter])")

    # Print SpecBuild + Bikeshed versions
    logging.info(f"SpecBuild version: {_specbuild_version()}")
    if CONFIG.source_format != "asciidoc":
        try:
            result = subprocess.run(
                ["bikeshed", "--version"], capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0:
                logging.info(f"Bikeshed version: {result.stdout.strip()}")
            else:
                logging.error("Bikeshed returned an error. Is it installed correctly?")
                logging.error(f"stderr: {result.stderr.strip()}")
                raise SystemExit(1)
        except FileNotFoundError:
            logging.error("Bikeshed not found. Please install it: pip install bikeshed")
            raise SystemExit(1)

    # --- Watch / Serve mode ---
    if getattr(args, "serve", False):
        from specbuild.output.livepreview import (
            find_index_html,
            notify_reload,
            open_browser,
            start_server,
        )

        # Force watch loop on
        args.watch = True

        # Locate the output HTML — best-effort before first build
        # (will be re-checked after build completes)
        _serve_started = False

        def _orig_build():
            return _run_build(args, manifest_path, front_matter_order, _active_flavor)

        def _build_and_serve():
            nonlocal _serve_started
            _orig_build()
            if not _serve_started:
                # Find the output dir from the most recent build
                import glob

                from specbuild.config import CONFIG

                pattern = (
                    CONFIG.output_dir_template.replace("{date}", "*")
                    .replace("{sha}", "*")
                    .replace("{spec_name}", "*")
                )
                matches = sorted(glob.glob(pattern), reverse=True)
                output_html = Path(matches[0]) / "index.html" if matches else None
                if output_html is None or not output_html.exists():
                    # Fallback: serve the project root
                    output_html = Path("index.html")
                serve_dir = output_html.parent if output_html.exists() else Path(".")
                _httpd, url = start_server(serve_dir, getattr(args, "serve_port", 8080))
                index = find_index_html(serve_dir)
                full_url = f"{url}/{index.name}" if index else url
                logging.info(f"Serving spec at: {full_url}")
                logging.info("Livereload active — browser will auto-reload on rebuild")
                open_browser(full_url)
                _serve_started = True
            else:
                # Subsequent rebuild — push reload to connected browsers.
                notify_reload()

        from specbuild.watch import watch_and_rebuild

        watch_and_rebuild(
            _build_and_serve,
            manifest_path=manifest_path,
            interval=args.watch_interval,
        )
        return

    if args.watch:
        from specbuild.watch import watch_and_rebuild

        watch_and_rebuild(
            lambda: _run_build(args, manifest_path, front_matter_order, _active_flavor),
            manifest_path=manifest_path,
            interval=args.watch_interval,
        )
        return

    # --- Normal build ---
    _run_build(args, manifest_path, front_matter_order, _active_flavor)
    _log_build_summary(args)


def _log_build_summary(args: argparse.Namespace) -> None:
    """Print a one-line "Build complete" summary listing output artifacts.

    Looks at the output directory derived from CONFIG.output_dir_template
    and lists notable files (index.html, the PDF, multipage dir, etc.)
    with sizes.  Single line per artifact; quiet when nothing was built.
    """
    target = _find_latest_output_html()
    if not target:
        return
    target_dir = target.parent

    notable: list[tuple[str, Path]] = []
    if target.exists():
        notable.append(("HTML", target))
    # PDF named after the output dir (per current template)
    pdf = target_dir / f"{target_dir.name}.pdf"
    if pdf.exists():
        notable.append(("PDF", pdf))
    # Multipage dir lives next to target_dir
    mp = target_dir.parent / f"{target_dir.name}_Multipage"
    if mp.is_dir():
        notable.append(("Multipage", mp))
    # Diff
    diff = target_dir / "diff.html"
    if diff.exists():
        notable.append(("Diff", diff))

    logging.info(f"Build complete → {target_dir}/")
    for label, path in notable:
        try:
            if path.is_file():
                size_kb = path.stat().st_size / 1024
                logging.info(f"  {label:9s} {path.parent.name}/{path.name}  ({size_kb:,.1f} KB)")
            else:
                logging.info(f"  {label:9s} {path.name}/")
        except OSError:
            logging.info(f"  {label:9s} {path.parent.name}/{path.name}")


if __name__ == "__main__":
    main()

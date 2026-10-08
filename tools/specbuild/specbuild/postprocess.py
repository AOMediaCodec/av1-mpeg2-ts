"""Post-processing steps applied after Bikeshed compilation.

This module contains every HTML transformation that runs between the raw
Bikeshed output and the final deliverable: copying assets, inserting
navigation aids (back-to-TOC links, quick-links banner), renumbering
annexes, generating a syntax browser, and optional optimizations such as
minification and resource externalization.

All functions operate on already-compiled HTML files on disk and are
orchestrated by :func:`copy_spec` (the main entry point for single-page
builds).
"""

from __future__ import annotations

import html as _html
import logging
import re
import shutil
from pathlib import Path

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import (
    get_bs4,
    move_and_overwrite,
    read_html,
    resolve_asset_file,
    run_helper_script,
    write_html,
)

# ---------------------------------------------------------------------------
# Unicode symbols used in generated navigation elements
# ---------------------------------------------------------------------------
_UP_ARROW = "\u2191"  # ↑  — "Back to TOC" link prefix
_ICON_PDF = "\U0001f4c4"  # 📄 — PDF link icon
_ICON_DIFF = "\U0001f50d"  # 🔍 — Diff link icon
_ICON_SYNTAX = "\U0001f527"  # 🔧 — Syntax browser link icon

# Bikeshed CSS classes that mark headings excluded from numbering / TOC
_EXCLUDED_H2_CLASSES = frozenset({"no-num", "no-toc", "no-ref"})


# ===================================================================
# TOC navigation helpers
# ===================================================================


def _should_skip_h2(h2, *, is_first_eligible: bool) -> bool:
    """Decide whether an ``<h2>`` element should be skipped for TOC-link insertion.

    The following headings are skipped:

    * Headings with Bikeshed exclusion classes (``no-num``, ``no-toc``,
      ``no-ref``).
    * The TOC heading itself (``id="contents"``).
    * Headings that are children of the TOC container (``<div id="toc">``).
    * The first numbered section (``Scope``, or whatever comes first).

    Args:
        h2: A BeautifulSoup ``<h2>`` Tag element.
        is_first_eligible: ``True`` when this is the first non-skipped heading
            encountered — it will also be skipped (the very first section
            needs no "back" link).

    Returns:
        ``True`` if the heading should be skipped.
    """
    classes = set(h2.get("class", []))
    if classes & _EXCLUDED_H2_CLASSES:
        return True
    if h2.get("id") == "contents":
        return True
    parent = h2.parent
    if parent and parent.get("id") == "toc":
        return True
    # The "Scope" section is always the first numbered heading; skip it.
    if h2.get("id") == "scope":
        return True
    if is_first_eligible:
        return True
    return False


def add_toc_links(html_path: Path) -> None:
    """Insert *Back to Table of Contents* links before every qualifying ``<h2>``.

    A small ``<p class="back-to-toc-wrapper">`` element containing an
    anchor to ``#toc`` is inserted immediately before each main-section
    heading, giving the reader a quick way to jump back to the TOC.

    Args:
        html_path: Path to the HTML file to modify.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping TOC link insertion")
        return

    logging.debug(f"Adding 'Back to TOC' links to {html_path.name}")

    try:
        soup = read_html(html_path)

        h2_headings = soup.find_all("h2")
        links_added = 0
        first_eligible = True

        for h2 in h2_headings:
            if _should_skip_h2(h2, is_first_eligible=first_eligible):
                # Once we pass all the structural skips, mark the next
                # eligible heading so it is consumed by the first-section
                # guard inside _should_skip_h2.
                classes = set(h2.get("class", []))
                if not (
                    classes & _EXCLUDED_H2_CLASSES
                    or h2.get("id") in ("contents", "scope")
                    or (h2.parent and h2.parent.get("id") == "toc")
                ):
                    first_eligible = False
                continue

            toc_wrapper = soup.new_tag("p", **{"class": "back-to-toc-wrapper"})
            toc_link = soup.new_tag("a", **{"class": "back-to-toc"}, href="#toc")
            toc_link.string = f"{_UP_ARROW} Back to Table of Contents"
            toc_wrapper.append(toc_link)
            h2.insert_before(toc_wrapper)
            links_added += 1

        write_html(html_path, soup)
        logging.debug(f"Added {links_added} 'Back to TOC' links")

    except Exception as e:
        logging.warning(f"Failed to add TOC links: {e}")


# ===================================================================
# Annex renumbering
# ===================================================================


def renumber_annexes_in_html(html_path: Path) -> None:
    """Renumber Annex sections from numeric to alphabetic notation.

    Delegates to the external ``renumber_annexes.py`` helper script.

    Args:
        html_path: Path to the HTML file to process.
    """
    logging.debug(f"Renumbering Annex sections in {html_path.name}")
    extra_args: list[str | Path] = [html_path]

    # Forward the theme's annex heading format to the helper script
    fmt = THEME.annex_heading_format
    if fmt and fmt != "prefix":
        extra_args += ["--format", fmt]

    if run_helper_script("renumber_annexes.py", extra_args, description="Annex renumbering"):
        logging.debug("Annex renumbering completed")


# ===================================================================
# Mobile optimization
# ===================================================================


def add_collapsible_sections_in_html(html_path: Path) -> None:
    """Add collapsible ``<details>``/``<summary>`` wrappers for mobile use.

    Delegates to the external ``add_collapsible_sections.py`` helper script.

    Args:
        html_path: Path to the HTML file to process.
    """
    logging.info(f"Adding collapsible sections for mobile optimization in {html_path.name}")
    run_helper_script(
        "add_collapsible_sections.py", [html_path], description="Collapsible sections"
    )


# ===================================================================
# Quick-links banner injection
# ===================================================================


def _build_banner_style(theme) -> str:  # noqa: ANN001 (Theme forward-ref)
    """Return the inline CSS string for the links-banner ``<div>``.

    Args:
        theme: The active :class:`~specbuild.theme.Theme` instance.

    Returns:
        A CSS style string.
    """
    return (
        f"background: {theme.banner_bg}; "
        f"color: {theme.banner_text_color}; "
        "padding: 15px 20px; "
        "margin: 20px 0; "
        "border-radius: 8px; "
        f"border: {theme.banner_border}; "
        "box-shadow: 0 2px 4px rgba(0,0,0,0.05); "
        f"font-family: {theme.font_sans};"
    )


def _build_link_style(theme) -> str:  # noqa: ANN001
    """Return the inline CSS string shared by every link inside the banner.

    Args:
        theme: The active :class:`~specbuild.theme.Theme` instance.

    Returns:
        A CSS style string.
    """
    return (
        f"background: {theme.banner_link_bg}; "
        f"color: {theme.banner_link_color}; "
        "padding: 6px 14px; "
        "border-radius: 4px; "
        f"border: {theme.banner_link_border}; "
        "text-decoration: none; "
        "font-weight: 500; "
        f"font-size: {theme.banner_link_font_size}; "
        "display: inline-block; "
        "transition: all 0.2s;"
    )


def _create_banner_link(soup, href: str, icon: str, label: str, style: str):
    """Create a single styled ``<a>`` element for the links banner.

    Args:
        soup: The BeautifulSoup document tree.
        href: The ``href`` attribute value.
        icon: A Unicode emoji/icon character prepended to the label.
        label: The visible link text (after the icon).
        style: Inline CSS applied to the ``<a>`` tag.

    Returns:
        A BeautifulSoup ``Tag`` (``<a>``).
    """
    link = soup.new_tag("a", href=href)
    link["style"] = style
    link.string = f"{icon} {label}"
    return link


def inject_links(target_path: Path) -> None:
    """Inject a *Quick Links* banner into the compiled HTML specification.

    The banner is inserted immediately after the Bikeshed-generated
    ``<div class="head">`` header and may contain links to:

    * The PDF rendition of the spec.
    * The HTML diff against the main branch.
    * The syntax browser (sections 5 & 6 only).

    Links are only shown for files that actually exist in *target_path*.

    Args:
        target_path: Path to the build directory containing ``index.html``.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping links injection")
        return

    html_path = target_path / "index.html"
    if not html_path.exists():
        logging.warning(f"Cannot inject links: {html_path} does not exist")
        return

    logging.info("Injecting links banner into specification")

    # Discover which companion files are available
    available_links: list[tuple[str, str, str]] = []  # (href, icon, label)
    pdf_file = target_path / f"{target_path.name}.pdf"
    diff_file = target_path / "diff.html"
    syntax_file = target_path / "syntax_browser.html"

    if pdf_file.exists():
        available_links.append((f"{target_path.name}.pdf", _ICON_PDF, "PDF Version"))
    if diff_file.exists():
        available_links.append(("diff.html", _ICON_DIFF, "Diff vs Main"))
    if syntax_file.exists():
        available_links.append(("syntax_browser.html", _ICON_SYNTAX, "Syntax Browser"))

    if not available_links:
        logging.info("No files found for links, skipping links injection")
        return

    try:
        soup = read_html(html_path)

        head_div = soup.find("div", class_="head")
        if not head_div:
            logging.warning("Could not find <div class='head'> in HTML, skipping links injection")
            return

        theme = THEME

        # -- Banner container --
        banner_div = soup.new_tag("div", **{"class": "links-banner"})
        banner_div["style"] = _build_banner_style(theme)

        # -- Title row --
        title_tag = soup.new_tag("div")
        title_tag["style"] = (
            f"font-size: {theme.banner_title_font_size}; font-weight: 600; "
            f"margin-bottom: 10px; color: {theme.banner_title_color};"
        )
        title_tag.string = "Quick Links"
        banner_div.append(title_tag)

        # -- Links row --
        links_container = soup.new_tag("div")
        links_container["style"] = "display: flex; gap: 10px; flex-wrap: wrap;"

        link_css = _build_link_style(theme)
        for href, icon, label in available_links:
            links_container.append(_create_banner_link(soup, href, icon, label, link_css))

        banner_div.append(links_container)

        # -- Hover style (injected once into <head>) --
        hover_style_tag = soup.new_tag("style")
        hover_style_tag.string = (
            f".links-banner a:hover {{ background: {theme.banner_link_hover_bg}; "
            f"border-color: {theme.banner_link_hover_border}; "
            "transform: translateY(-1px); }}"
        )

        head_div.insert_after(banner_div)

        head_tag = soup.find("head")
        if head_tag and not soup.find("style", string=lambda text: text and "links-banner" in text):
            head_tag.append(hover_style_tag)

        write_html(html_path, soup)
        logging.info(f"Successfully injected links banner with {len(available_links)} link(s)")

    except Exception as e:
        logging.warning(f"Failed to inject links: {e}")


# ===================================================================
# HTML minification & resource externalization
# ===================================================================


def minify_html(html_path: Path) -> None:
    """Minify an HTML file by stripping unnecessary whitespace and comments.

    Delegates to the external ``minify_html.py`` helper script.

    Args:
        html_path: Path to the HTML file to minify.
    """
    logging.info(f"Minifying {html_path.name}")
    run_helper_script("minify_html.py", [html_path], description="HTML minification")


def externalize_resources(html_path: Path) -> None:
    """Extract inline CSS and JavaScript into separate files.

    Delegates to the ``externalize_css.py`` and ``externalize_js.py``
    helper scripts in sequence.

    Args:
        html_path: Path to the HTML file to process.
    """
    logging.info(f"Externalizing CSS from {html_path.name}")
    run_helper_script("externalize_css.py", [html_path], description="Externalize CSS")

    logging.info(f"Externalizing JavaScript from {html_path.name}")
    run_helper_script("externalize_js.py", [html_path], description="Externalize JS")


# ===================================================================
# Syntax browser generation
# ===================================================================


def generate_syntax_browser(target_dir: Path) -> None:
    """Generate a lightweight syntax browser containing only sections 5 and 6.

    The syntax browser is a standalone HTML page derived from the full
    specification that lets readers focus on the bitstream syntax.

    Args:
        target_dir: Build directory containing the compiled ``index.html``.
    """
    logging.info("Generating syntax browser")

    input_html = target_dir / "index.html"
    output_html = target_dir / "syntax_browser.html"

    if not input_html.exists():
        logging.error(f"Input HTML not found: {input_html}")
        return

    if run_helper_script(
        "generate_syntax_browser.py",
        [input_html, output_html, CONFIG.spec_name],
        description="Syntax browser",
    ):
        logging.info(f"Syntax browser generated: {output_html}")


# ===================================================================
# Main entry point — copy and post-process compiled spec
# ===================================================================

# Asset directories to copy alongside the HTML.
#
# Each entry: (dir_name, missing_log_level, source).
#
# *source* selects where the directory is read from:
#
#   "system"   — sourced from PROJECT_ROOT (the build system's own dir).
#                If a same-named directory also exists in the consumer
#                workspace (CWD), its contents overlay on top so consumers
#                can ship spec-specific overrides without forking.
#   "user"     — sourced from the consumer workspace (CWD) only.
#
# This lets consumers drop the build system into their repo without
# having to copy css/ and js/ from this project.
_ASSET_DIRS: list[tuple[str, int, str]] = [
    # User assets are optional — most specs without images/attachments
    # would see noise, so log at DEBUG when the directory is absent.
    ("images", logging.DEBUG, "user"),
    ("css", logging.WARNING, "system"),
    ("js", logging.WARNING, "system"),
    ("attachments", logging.DEBUG, "user"),
]


def _inject_dark_mode_css(html_path: Path) -> None:
    """Inject dark-mode CSS as an inline ``<style>`` at end of ``<head>``.

    The CSS must appear *after* Bikeshed's boilerplate ``<style>`` blocks
    so that the dark-theme variable overrides win.  Reading from the
    external ``css/dark-mode.css`` keeps maintenance in one place.
    """
    css_file = resolve_asset_file("css/dark-mode.css")
    if not css_file.exists():
        return

    text = html_path.read_text(encoding="utf-8")
    if 'id="dark-mode-css"' in text:
        return  # already injected

    css = css_file.read_text(encoding="utf-8")
    style_block = f'<style id="dark-mode-css">\n{css}\n</style>\n</head>'
    # Case-insensitive: some serializers emit </HEAD>.
    new_text, count = re.subn(r"</head\s*>", style_block, text, count=1, flags=re.IGNORECASE)
    if count == 0:
        logging.warning("Dark-mode CSS not injected: no </head> tag found in %s", html_path)
        return
    html_path.write_text(new_text, encoding="utf-8")
    logging.debug("Injected dark-mode CSS inline (after boilerplate)")


def _render_latex_to_mathml(html_path: Path) -> None:
    """Convert LaTeX math delimiters in the HTML to native MathML.

    Handles three delimiter styles:
    - ``$$...$$``   — display math (common in specbuild demo spec)
    - ``\\[...\\]``  — display math (common in AV2/IEEE/W3C specs)
    - ``\\(...\\)``  — inline math

    Replaces the external MathJax CDN dependency (blocked by GitHub Enterprise
    Pages CSP and many internal network proxies) with server-side rendering via
    ``latex2mathml``.  When the MathJax CDN ``<script>`` is also present in
    the HTML, it is removed since server-side rendering makes it redundant.

    Skips quietly when ``latex2mathml`` is not installed.
    """
    try:
        import latex2mathml.converter as _l2m
    except ImportError:
        return

    text = html_path.read_text(encoding="utf-8")

    # Already native MathML (e.g. re-run after a previous postprocess) — fastest exit
    if "<math" in text:
        return

    # Detect which equation delimiters are present
    has_dollars = "$$" in text
    has_backslash_paren = "\\(" in text
    has_backslash_bracket = "\\[" in text
    # Bikeshed strips the leading \ from \[, producing <p>[\n...\n\]</p>.
    # Detect this mangled form via the surviving closing \] delimiter.
    has_bs_mangled_bracket = "\\]" in text and not has_backslash_bracket

    if not (has_dollars or has_backslash_paren or has_backslash_bracket or has_bs_mangled_bracket):
        return

    changed = False

    def _display(m: re.Match) -> str:
        nonlocal changed
        latex = _html.unescape(m.group(1).strip())
        try:
            mathml = _l2m.convert(latex, display="block")
            changed = True
            return mathml
        except Exception:
            return m.group(0)

    def _inline(m: re.Match) -> str:
        nonlocal changed
        latex = _html.unescape(m.group(1).strip())
        try:
            mathml = _l2m.convert(latex, display="inline")
            changed = True
            return mathml
        except Exception:
            return m.group(0)

    if has_dollars:
        text = re.sub(r"\$\$(.+?)\$\$", _display, text, flags=re.DOTALL)
    if has_backslash_bracket:
        # Standard \[...\] form; also check mangled form in case some survived
        text = re.sub(r"\\\[(.+?)\\\]", _display, text, flags=re.DOTALL)
        text = re.sub(
            r"<p>\[\s*(.+?)\\\]</p>",
            lambda m: f"<p>{_display(m)}</p>",
            text,
            flags=re.DOTALL,
        )
    elif has_bs_mangled_bracket:
        # Bikeshed-mangled form only: \[ stripped to [, giving <p>[\n...\n\]</p>
        text = re.sub(
            r"<p>\[\s*(.+?)\\\]</p>",
            lambda m: f"<p>{_display(m)}</p>",
            text,
            flags=re.DOTALL,
        )
    if has_backslash_paren:
        text = re.sub(r"\\\((.+?)\\\)", _inline, text, flags=re.DOTALL)

    # Remove MathJax CDN script(s) — only needed if equations were actually converted.
    if changed and (
        "cdn.jsdelivr.net/npm/mathjax" in text or "cdnjs.cloudflare.com/ajax/libs/mathjax" in text
    ):
        # Remove the polyfill.io script (supply-chain-compromised since 2024)
        text = re.sub(r"<script[^>]+polyfill\.io[^>]*></script>\s*", "", text)
        # Remove MathJax CDN loader script
        text = re.sub(
            r"<script[^>]+(?:cdn\.jsdelivr\.net/npm/mathjax|cdnjs\.cloudflare\.com/ajax/libs/mathjax)[^>]*>\s*</script>\s*",
            "",
            text,
        )
        # Remove inline MathJax config block (the var MathJax = {...} script)
        text = re.sub(
            r"<script[^>]*>\s*MathJax\s*=\s*\{.*?\}\s*;\s*</script>\s*",
            "",
            text,
            flags=re.DOTALL,
        )
        logging.info("Removed MathJax CDN (replaced by server-side latex2mathml rendering)")

    if changed:
        html_path.write_text(text, encoding="utf-8")
        logging.debug("Pre-rendered LaTeX equations to MathML (no MathJax CDN needed)")


def _localize_w3c_css(html_path: Path) -> None:
    """Replace the external W3C stylesheet link with the local specbuild.css.

    GitHub Pages (and many internal Pages deployments) block external stylesheets
    via CSP (``style-src 'self'``).  The W3C layout CSS at www.w3.org/StyleSheets/
    is the main source of the TOC sidebar layout; without it the spec renders as a
    single column with no sidebar.

    If ``css/specbuild.css`` is present next to the built ``index.html``, the
    external link is replaced with a relative path so the spec is fully
    self-contained.
    """
    css_src = resolve_asset_file("css/specbuild.css")
    if not css_src.exists():
        return  # no local copy — leave external link in place

    text = html_path.read_text(encoding="utf-8")
    if "specbuild.css" in text:
        return  # already localized

    if "www.w3.org/StyleSheets/TR" not in text:
        return  # no W3C link to replace

    # Copy specbuild.css (and base.css it imports) to the output css/ dir.
    target_css_dir = html_path.parent / "css"
    target_css_dir.mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(css_src, target_css_dir / "specbuild.css")
    base_src = resolve_asset_file("css/base.css")
    if base_src.exists():
        shutil.copy2(base_src, target_css_dir / "base.css")

    # Patch the HTML to use the local file.
    new_text = re.sub(
        r"https://www\.w3\.org/StyleSheets/TR/[^\s\"']+",
        "css/specbuild.css",
        text,
    )
    if new_text != text:
        html_path.write_text(new_text, encoding="utf-8")
        logging.debug("Replaced external W3C stylesheet with local css/specbuild.css")


def _postprocess_html(
    html_path: Path, *, externalize: bool, minify: bool, mobile_optimized: bool
) -> None:
    """Apply the post-processing pipeline to a single HTML file.

    The steps always run in a fixed order: TOC links, annex renumbering,
    then the optional passes (mobile, externalize, minify).

    Args:
        html_path: Path to the HTML file.
        externalize: If ``True``, externalize inline CSS and JS.
        minify: If ``True``, strip whitespace/comments from the HTML.
        mobile_optimized: If ``True``, add collapsible sections.
    """
    add_toc_links(html_path)
    renumber_annexes_in_html(html_path)
    if CONFIG.introduction_section_zero:
        from specbuild.enhancements.introzero import renumber_introduction_as_zero

        renumber_introduction_as_zero(html_path)
    _inject_dark_mode_css(html_path)
    _localize_w3c_css(html_path)
    if CONFIG.hevc_equations:
        from specbuild.enhancements.hevcequations import (
            fix_operator_tables,
            process_hevc_equations,
        )

        process_hevc_equations(html_path)
        fix_operator_tables(html_path)
    else:
        _render_latex_to_mathml(html_path)

    if mobile_optimized:
        add_collapsible_sections_in_html(html_path)
    if externalize:
        externalize_resources(html_path)
    if minify:
        minify_html(html_path)


def _copy_asset_dirs(root_path: Path, target_path: Path) -> None:
    """Copy standard asset directories (images, css, js, attachments).

    System asset directories (``css/``, ``js/``) are read from
    ``PROJECT_ROOT`` — the build-system root — with an optional overlay
    from *root_path* (the consumer workspace).  User asset directories
    (``images/``, ``attachments/``) are read from *root_path* only.

    Args:
        root_path: Consumer workspace (CWD) where ``images/`` and
            ``attachments/`` live and where overrides for ``css/`` /
            ``js/`` may live.
        target_path: Destination directory.
    """
    for dir_name, missing_log_level, source in _ASSET_DIRS:
        copied_any = False
        copied_paths: set[Path] = set()

        if source == "system":
            system_src = PROJECT_ROOT / dir_name
            if system_src.exists():
                logging.debug(
                    f"Copying {dir_name} directory from '{system_src}' to "
                    f"'{target_path / dir_name}'"
                )
                shutil.copytree(system_src, target_path / dir_name, dirs_exist_ok=True)
                copied_any = True
                copied_paths.add(system_src.resolve())

        # Consumer-workspace dir: sole source for "user" assets, optional
        # overlay for "system" assets.  Skip if it's the same physical
        # directory we already copied (PROJECT_ROOT == CWD on dev builds).
        user_src = root_path / dir_name
        if user_src.exists() and user_src.resolve() not in copied_paths:
            logging.debug(
                f"Copying {dir_name} directory from '{user_src}' to '{target_path / dir_name}'"
            )
            shutil.copytree(user_src, target_path / dir_name, dirs_exist_ok=True)
            copied_any = True

        if not copied_any:
            logging.log(
                missing_log_level, f"{dir_name.capitalize()} directory not found for '{dir_name}'."
            )


def _substitute_print_css_placeholders(target_path: Path) -> None:
    """Replace placeholders in print CSS files with themed values.

    Substitutes in both ``print.css`` and ``weasyprint.css``:
    - ``SPEC_FULL_NAME`` → configured specification name
    - ``FONT_SANS`` → ``THEME.font_sans`` (body/footer font family)

    Args:
        target_path: Build output directory containing the ``css/`` subdirectory.
    """
    from specbuild.theme import THEME

    for css_name in ("print.css", "weasyprint.css"):
        css_path = target_path / "css" / css_name
        if not css_path.exists():
            continue
        css_text = css_path.read_text(encoding="utf-8")
        changed = False
        if "SPEC_FULL_NAME" in css_text:
            css_text = css_text.replace("SPEC_FULL_NAME", CONFIG.spec_full_name)
            changed = True
        if "FONT_SANS" in css_text:
            css_text = css_text.replace("FONT_SANS", THEME.font_sans)
            changed = True
        if changed:
            css_path.write_text(css_text, encoding="utf-8")
            logging.debug(f"Substituted placeholders in {css_path}")


def copy_spec(
    target_path: Path,
    root_dir: Path | None = None,
    *,
    externalize: bool = False,
    minify: bool = False,
    mobile_optimized: bool = False,
) -> None:
    """Copy specification files to the output directory and post-process them.

    This is the main post-processing entry point for single-page builds.
    It performs three stages:

    1. **Move HTML** — all ``index*.html`` files are moved from *root_dir*
       into *target_path*, then each is post-processed (TOC links, annex
       renumbering, and the optional mobile/externalize/minify passes).
    2. **Copy assets** — the ``images/``, ``css/``, ``js/``, and
       ``attachments/`` directories are copied.
    3. **Template substitution** — placeholders in ``print.css`` are
       replaced with themed values (``SPEC_FULL_NAME``, ``FONT_SANS``).

    Args:
        target_path: Destination build directory.
        root_dir: Source directory containing the Bikeshed output.
            Defaults to the current working directory.
        externalize: If ``True``, externalize inline CSS and JS to files.
        minify: If ``True``, minify HTML output.
        mobile_optimized: If ``True``, wrap sections in collapsible elements.
    """
    root_path = root_dir if root_dir else Path(".")

    logging.debug(f"Copy compiled specs into '{target_path}'")
    target_path.mkdir(parents=True, exist_ok=True)

    # -- Stage 1: move and post-process HTML files --
    index_files = list(root_path.glob("index*.html"))
    if not index_files:
        logging.warning(f"No index*.html files found in {root_path}")
        return

    for index_file in index_files:
        move_and_overwrite(index_file, target_path)
        _postprocess_html(
            target_path / index_file.name,
            externalize=externalize,
            minify=minify,
            mobile_optimized=mobile_optimized,
        )

    # -- Stage 2: copy asset directories --
    _copy_asset_dirs(root_path, target_path)

    # -- Stage 3: template substitution in print.css --
    _substitute_print_css_placeholders(target_path)

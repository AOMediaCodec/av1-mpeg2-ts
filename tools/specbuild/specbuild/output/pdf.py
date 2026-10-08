"""PDF generation from compiled HTML specifications.

This module orchestrates the full PDF pipeline, supporting two rendering
engines: **Chrome headless** and **WeasyPrint**.  The public entry point is
:func:`generate_pdf`, which drives a zone-based approach to minimize
HTML parse/serialize cycles:

- **Zone A** — subprocess-based preprocessing (table/figure numbering,
  MathJax pre-rendering, SVG fixes).
- **Zone B** — single BeautifulSoup parse/write pass (equation styling,
  section headers, LOF/LOT injection, front-matter re-marking).
- **Subprocess boundary** — TOC page-number extraction via Chrome two-pass.
- **Zone C** — final parse/write pass (TOC page-number restyling,
  WeasyPrint table stripping or Chrome font-size override).

Supporting concerns handled here:

- CSS injection helpers for font-size overrides and equation styling.
- Localization of external W3C stylesheet/image URLs to a local cache
  (``css/w3c-cache/``) so WeasyPrint can resolve them offline.
- List-of-Figures / List-of-Tables generation and injection.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import (
    chrome_path,
    get_bs4,
    homebrew_lib_for_dyld,
    inject_css,
    read_html,
    run_helper_script,
    write_html,
)

# ---------------------------------------------------------------------------
# Page-size mapping (CLI value → CSS @page size value)
# ---------------------------------------------------------------------------

_PAGE_SIZE_CSS_MAP: dict[str, str] = {
    "letter": "letter",
    "a4": "A4",
    "legal": "legal",
}


# ---------------------------------------------------------------------------
# CSS injection helpers
# ---------------------------------------------------------------------------


def inject_pdf_font_size_override(html_path: Path, font_increase: int) -> None:
    """Inject CSS to increase font sizes for PDF generation.

    File-based wrapper around :func:`inject_pdf_font_size_override_soup`.

    Args:
        html_path (Path): Path to the HTML file to modify.
        font_increase (int): Amount to increase font sizes by (in pt).
    """
    if font_increase <= 0:
        return

    soup = read_html(html_path)
    inject_pdf_font_size_override_soup(soup, font_increase)
    write_html(html_path, soup)


def inject_pdf_font_size_override_soup(soup: Any, font_increase: int) -> None:
    """Inject CSS to increase font sizes on a pre-parsed soup object.

    Code blocks receive a smaller increase than body text to avoid overflow
    in long SDL syntax blocks.  SDL table font sizes are kept fixed.

    Args:
        soup: BeautifulSoup document (mutated in place).
        font_increase: Amount to increase font sizes by (in pt).
    """
    if font_increase <= 0:
        return

    head = soup.find("head")
    if not head:
        logging.warning("No <head> found in HTML, cannot inject font size overrides")
        return

    t = THEME
    body_size = t.body_font_size + font_increase
    table_size = t.table_font_size + font_increase
    # Code blocks get roughly half the increase to prevent overflow in
    # large blocks (SDL tables, pseudocode, etc.)
    code_increase = max(1, (font_increase + 1) // 2)
    code_size = t.code_font_size + code_increase
    sdl_size = t.sdl_font_size  # SDL tables: no increase (kept at theme default)
    back_to_toc_size = t.back_to_toc_font_size + font_increase
    figcaption_size = t.caption_font_size + font_increase
    list_size = t.list_font_size + font_increase

    css_content = f"""
/* PDF Font Size Override - Increase by {font_increase}pt for body/tables, {code_increase}pt for code, 0pt for SDL */
/* Note: No @media print wrapper needed - CSS applies directly */
/* Code blocks use smaller increase, SDL tables kept at 8pt to prevent large blocks from overflowing */
body {{
  font-size: {body_size}pt !important;
}}

/* Tables */
table {{
  font-size: {table_size}pt !important;
}}

table td, table th {{
  font-size: {table_size}pt !important;
}}

table thead th {{
  font-size: {table_size}pt !important;
}}

/* SDL Syntax Tables */
.sdl-syntax-table {{
  font-size: {sdl_size}pt !important;
}}

.sdl-syntax-table td,
.sdl-syntax-table th {{
  font-size: {sdl_size}pt !important;
}}

.sdl-syntax-table .sdl-descriptor {{
  font-size: {sdl_size}pt !important;
}}

.sdl-syntax-table .sdl-var-with-descriptor,
.sdl-syntax-table .sdl-code {{
  font-size: {sdl_size}pt !important;
}}

/* Code blocks and pre elements */
pre, code {{
  font-size: {code_size}pt !important;
}}

.code-table {{
  font-size: {code_size}pt !important;
}}

.code-table td {{
  font-size: {code_size}pt !important;
}}

/* Smaller tables */
.table-sm td,
.table-sm th {{
  font-size: {code_size}pt !important;
}}

/* Back to TOC links */
.back-to-toc {{
  font-size: {back_to_toc_size}pt !important;
}}

/* Figures and captions */
figcaption {{
  font-size: {figcaption_size}pt !important;
  text-align: center !important;
}}

/* Lists */
ul, ol {{
  font-size: {list_size}pt !important;
}}

li {{
  font-size: {list_size}pt !important;
}}
"""

    style_tag = soup.new_tag("style", id="pdf-font-size-override")
    style_tag.string = css_content
    head.append(style_tag)

    logging.info(
        f"Injected PDF font size override: +{font_increase}pt "
        f"(body: {body_size}pt, tables: {table_size}pt, "
        f"code: {code_size}pt, SDL: {sdl_size}pt)"
    )


def inject_equation_styling(
    html_path: Path, equation_font: str = "default", equation_scale: float = 1.0
) -> None:
    """Inject CSS to customize equation font and scale for PDF generation.

    File-based wrapper around :func:`inject_equation_styling_soup`.

    Args:
        html_path (Path): Path to the HTML file to modify.
        equation_font (str): Font choice name.
        equation_scale (float): Scale factor for equations.
    """
    soup = read_html(html_path)
    inject_equation_styling_soup(soup, equation_font, equation_scale)
    write_html(html_path, soup)


def inject_equation_styling_soup(
    soup: Any, equation_font: str = "default", equation_scale: float = 1.0
) -> None:
    """Inject CSS to customize equation font and scale on a pre-parsed soup.

    Targets native MathML ``<math>`` elements (rendered by latex2mathml at
    build time).  The font stack is applied to the math element and all its
    children so the operator glyphs, identifiers, and numbers share the same
    math-aware typeface.

    Args:
        soup: BeautifulSoup document (mutated in place).
        equation_font: Font choice name (see ``--equation-font`` CLI flag).
        equation_scale: Scale factor for equations (1.0 = match body text).
    """
    # Math-aware font stacks in order of rendering quality.
    # Each entry provides: primary math font, fallbacks.
    font_families = {
        "default": "",
        # --- Recommended: dedicated math fonts with full Unicode coverage ---
        "stix": '"STIX Two Math", "STIX Two Text", "STIX", serif',
        "latin-modern": '"Latin Modern Math", "Latin Modern Roman", "Computer Modern", serif',
        "xits": '"XITS Math", "XITS", serif',
        "libertinus": '"Libertinus Math", "Libertinus Serif", serif',
        "tex-gyre-termes": '"TeX Gyre Termes Math", "TeX Gyre Termes", "Times New Roman", serif',
        "tex-gyre-pagella": '"TeX Gyre Pagella Math", "TeX Gyre Pagella", "Palatino Linotype", serif',
        # --- System fonts (no dedicated math font; glyphs from general font) ---
        "cambria": '"Cambria Math", Cambria, serif',
        "times-new-roman": '"Times New Roman", Times, serif',
        "georgia": "Georgia, serif",
    }

    if equation_font not in font_families:
        logging.warning(f"Unknown equation font: {equation_font!r}, using default")
        equation_font = "default"

    font_family = font_families[equation_font]

    head = soup.find("head")
    if not head:
        logging.warning("No <head> found in HTML, cannot inject equation styling")
        return

    css_parts = []

    if font_family:
        css_parts.append(f"""
/* Equation Font: {equation_font} — applied to native MathML elements */
math, math * {{
  font-family: {font_family} !important;
}}
""")

    scale_pct = f"{equation_scale * 100:.0f}%"
    css_parts.append(f"""
/* Equation Scale: {equation_scale} (1.0 = match surrounding text) */
math[display="block"] {{
  font-size: {scale_pct};
}}
math[display="inline"] {{
  font-size: {scale_pct};
}}
""")

    if not css_parts:
        return

    css_content = "\n".join(css_parts)
    style_tag = soup.new_tag("style", id="equation-styling-override")
    style_tag.string = css_content
    head.append(style_tag)

    font_desc = equation_font if equation_font != "default" else "browser default"
    logging.info(f"Injected equation styling: font={font_desc}, scale={equation_scale}")


# ---------------------------------------------------------------------------
# Internal PDF pipeline stages
# ---------------------------------------------------------------------------

# Map of external URLs to local cached filenames (relative to css/w3c-cache/).
_W3C_CACHE_MAP = {
    "https://www.w3.org/StyleSheets/TR/2021/W3C-UD": "W3C-UD.css",
    "https://www.w3.org/StyleSheets/TR/2021/logos/W3C": "W3C-logo.svg",
    "https://www.w3.org/StyleSheets/TR/2016/logos/UD-watermark": "UD-watermark.svg",
    "https://www.w3.org/StyleSheets/TR/2021/base.css": "base.css",
    "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-draft.svg": "UD-watermark-light-draft.svg",
    "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-unofficial.svg": "UD-watermark-light-unofficial.svg",
}


def _patch_cached_css(cache_dir: Path) -> None:
    """Rewrite references inside cached CSS files to use local file URIs.

    Handles:
    - W3C-UD.css: @import "base.css" and relative url(logos/...) refs
    - base.css: absolute url(https://...) refs to watermark images

    Idempotent: skips files that have already been patched (detected by
    the presence of ``file://`` URIs).
    """
    # --- W3C-UD.css: fix @import and relative logo URLs ---
    w3c_ud = cache_dir / "W3C-UD.css"
    if w3c_ud.exists():
        css_text = w3c_ud.read_text(encoding="utf-8")

        # Skip if already patched (contains file:// URIs)
        if "file://" in css_text:
            logging.debug("W3C-UD.css already patched, skipping")
        else:
            css_changed = False

            # Fix @import "base.css" -> absolute file URI (or remove if not cached)
            base_css = cache_dir / "base.css"
            if base_css.exists():
                base_uri = base_css.resolve().as_uri()
                new_css = css_text.replace('@import "base.css"', f'@import "{base_uri}"')
            else:
                new_css = css_text.replace('@import "base.css";', "/* base.css not cached */")
            if new_css != css_text:
                css_text = new_css
                css_changed = True

            # Fix relative url(logos/...) -> absolute file URIs or neutralize
            logo_map = {
                "logos/UD": "UD-watermark.svg",
                "logos/UD-watermark-light-draft": "UD-watermark-light-draft.svg",
                "logos/UD-watermark-light-unofficial": "UD-watermark-light-unofficial.svg",
            }
            for rel_path, cached_name in logo_map.items():
                if f"url({rel_path})" not in css_text:
                    continue
                local = cache_dir / cached_name
                if local.exists():
                    css_text = css_text.replace(
                        f"url({rel_path})", f"url({local.resolve().as_uri()})"
                    )
                else:
                    css_text = css_text.replace(f"url({rel_path})", "url(about:blank)")
                css_changed = True

            if css_changed:
                w3c_ud.write_text(css_text, encoding="utf-8")
                logging.info("  Patched W3C-UD.css internal references")

    # --- base.css: fix absolute watermark URLs and attribute selectors ---
    base_css = cache_dir / "base.css"
    if base_css.exists():
        css_text = base_css.read_text(encoding="utf-8")

        # Skip if already patched (contains file:// URIs)
        if "file://" in css_text:
            logging.debug("base.css already patched, skipping")
        else:
            css_changed = False

            abs_url_map = {
                "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-draft.svg": "UD-watermark-light-draft.svg",
                "https://www.w3.org/StyleSheets/TR/2021/logos/UD-watermark-light-unofficial.svg": "UD-watermark-light-unofficial.svg",
            }
            for url, cached_name in abs_url_map.items():
                if url not in css_text:
                    continue
                local = cache_dir / cached_name
                if local.exists():
                    css_text = css_text.replace(url, local.resolve().as_uri())
                else:
                    css_text = css_text.replace(url, "about:blank")
                css_changed = True

            # Fix CSS attribute selectors that match on the original W3C logo path.
            # After localization the img src becomes a file:// URI containing
            # "W3C-logo" instead of "logos/W3C", so the selectors won't match.
            logo_local = cache_dir / "W3C-logo.svg"
            if logo_local.exists() and 'src*="logos/W3C"' in css_text:
                css_text = css_text.replace('src*="logos/W3C"', 'src*="W3C-logo"')
                css_changed = True

            if css_changed:
                base_css.write_text(css_text, encoding="utf-8")
                logging.info("  Patched base.css absolute URLs and selectors")


def _localize_external_resources(index_pdf_path: Path) -> None:
    """Rewrite external W3C URLs to local cached copies if available.

    The cache directory is ``css/w3c-cache/`` under the project root.
    Run ``scripts/download_w3c_cache.sh`` once (with network access) to populate it.

    This also creates a patched copy of W3C-UD.css next to the PDF HTML
    that has its internal relative references (``@import "base.css"`` and
    ``url(logos/...)```) rewritten to absolute file URIs.
    """
    cache_dir = PROJECT_ROOT / "css" / "w3c-cache"
    if not cache_dir.is_dir():
        return

    text = index_pdf_path.read_text(encoding="utf-8")
    changed = False

    for url, filename in _W3C_CACHE_MAP.items():
        local_path = cache_dir / filename
        if not local_path.exists():
            continue
        # Use absolute file URI so WeasyPrint can resolve it
        file_uri = local_path.resolve().as_uri()
        if url in text:
            text = text.replace(url, file_uri)
            changed = True
            logging.info(f"  Localized {url} -> {filename}")

    if changed:
        index_pdf_path.write_text(text, encoding="utf-8")
        logging.info("Rewrote external URLs to local W3C cache")
    else:
        logging.debug("No external URLs to localize (cache may be empty)")

    # Patch cached CSS files so their internal references resolve locally.
    # WeasyPrint follows the file:// URIs we injected above, so these cached
    # files need their own relative/absolute external refs fixed too.
    _patch_cached_css(cache_dir)


def _pdf_preprocess_html(index_pdf_path: Path, *, use_weasyprint: bool = False) -> None:
    """Pre-process the PDF working copy: table numbers, MathJax rendering.

    Runs external subprocess tools that must operate on files on disk.
    Equation styling is injected later in the single-pass Zone B.
    """
    # Always run table/figure number preprocessing — both code paths need
    # the "Table X.Y:" and "Figure X.Y:" prefixes in captions for LOF/LOT
    # number extraction.  WeasyPrint later strips table numbers (it uses CSS
    # counters for tables), but figure numbers are kept.
    logging.info("Pre-processing HTML to add table and figure numbers for PDF...")
    run_helper_script(
        "add_table_numbers_for_pdf.py",
        [index_pdf_path],
        description="Table/figure number preprocessing",
    )

    html_text = index_pdf_path.read_text(encoding="utf-8", errors="ignore")
    has_native_mathml = "<math" in html_text

    if has_native_mathml and not use_weasyprint:
        # Chrome renders <math> elements natively — no JS pre-render needed.
        logging.info("Skipping MathJax pre-render: native MathML detected (Chrome)")
        return

    if has_native_mathml and use_weasyprint:
        # WeasyPrint cannot render MathML.  Inject MathJax with MML input so
        # the Puppeteer pre-render step can convert <math> elements to SVG,
        # which WeasyPrint CAN render.
        mathjax_inject = (
            '<script>MathJax = { loader: { load: ["input/mml", "output/svg"] },'
            ' options: { skipHtmlTags: ["script","noscript","style","textarea","pre"] }'
            " };</script>"
            '<script id="MathJax-script" async'
            ' src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/mml-svg.js"></script>'
        )
        patched = html_text.replace("</head>", mathjax_inject + "\n</head>", 1)
        index_pdf_path.write_text(patched, encoding="utf-8")
        logging.info("Injected MathJax MML→SVG for WeasyPrint pre-render")

    logging.info("Pre-rendering MathJax for PDF...")
    mathjax_script = PROJECT_ROOT / "scripts" / "prerender_mathjax_for_weasyprint.py"
    if mathjax_script.exists() and chrome_path():
        try:
            subprocess.run(
                [sys.executable, str(mathjax_script), str(index_pdf_path), chrome_path()],
                check=True,
                timeout=300,
            )

            run_helper_script(
                "fix_mathjax_svg_widths.py", [index_pdf_path], description="SVG width fix"
            )
        except subprocess.CalledProcessError as e:
            logging.warning(f"Failed to pre-render MathJax: {e}")
            logging.warning(
                "Continuing without MathJax pre-rendering (equations may not display correctly)"
            )
    else:
        if not mathjax_script.exists():
            logging.warning(f"MathJax pre-rendering script not found: {mathjax_script}")
        if not chrome_path():
            logging.warning("Chrome path not set - cannot pre-render MathJax")
        logging.warning("MathJax equations may not display correctly in PDF")


def _pdf_inject_lof_lot_soup(
    soup: Any,
    generate_lof: bool,
    generate_lot: bool,
    toc_leaders: str,
    front_matter_order: list[str] | None,
) -> bool:
    """Inject List-of-Figures / List-of-Tables into the soup for non-WeasyPrint modes.

    Returns True if the soup was modified.
    """
    if not generate_lof and not generate_lot:
        return False

    logging.info("Generating LOF/LOT for Chrome PDF mode...")
    script_dir = PROJECT_ROOT / "scripts"
    sys.path.insert(0, str(script_dir))
    try:
        BeautifulSoup = get_bs4()

        from generate_lof_lot import (
            create_lof_html,
            create_lot_html,
            extract_figures_from_html,
            extract_tables_from_html,
        )

        nav_elements = {}
        if generate_lof:
            logging.info("  - Adding List of Figures...")
            figures = extract_figures_from_html(soup)
            if figures:
                format_style = "table" if toc_leaders == "table" else "list"
                lof_html = create_lof_html(figures, format_style)
                lof_soup = BeautifulSoup(lof_html, "html.parser")
                lof_nav = lof_soup.find("nav", id="lof")
                if lof_nav:
                    nav_elements["lof"] = lof_nav
                    logging.info(f"    Added {len(figures)} figures to LOF")

        if generate_lot:
            logging.info("  - Adding List of Tables...")
            tables = extract_tables_from_html(soup)
            if tables:
                format_style = "table" if toc_leaders == "table" else "list"
                lot_html = create_lot_html(tables, format_style)
                lot_soup = BeautifulSoup(lot_html, "html.parser")
                lot_nav = lot_soup.find("nav", id="lot")
                if lot_nav:
                    nav_elements["lot"] = lot_nav
                    logging.info(f"    Added {len(tables)} tables to LOT")

        toc = soup.find("nav", id="toc")
        if toc and nav_elements:
            order = front_matter_order if front_matter_order else ["toc", "lof", "lot"]
            insert_order = [k for k in order if k in nav_elements]
            for k in nav_elements:
                if k not in insert_order:
                    insert_order.append(k)

            for key in reversed(insert_order):
                toc.insert_after(nav_elements[key])
            logging.info(f"    Front-matter order: {', '.join(insert_order)}")

        # Inject LOF/LOT CSS directly into the soup (avoid separate parse/write)
        if generate_lof or generate_lot:
            # Build the CSS content using the same logic as inject_lof_lot_css
            # but inject directly into this soup's <head>
            format_style = "table" if toc_leaders == "table" else "list"
            use_leaders = True if format_style == "list" else (toc_leaders in ["css", "table"])
            _inject_lof_lot_css_soup(soup, format_style, use_leaders)
            logging.info("  - Injected LOF/LOT CSS")

        return bool(nav_elements)

    except Exception as e:
        logging.error(f"Failed to generate LOF/LOT: {e}", exc_info=True)
        return False
    finally:
        sys.path.pop(0)


def _inject_lof_lot_css_soup(soup: Any, format_style: str, use_leaders: bool) -> None:
    """Inject LOF/LOT CSS directly into the soup's <head>.

    Delegates CSS construction to :func:`generate_lof_lot.build_lof_lot_css`
    (the single source of truth) and appends the resulting ``<style>`` tag.
    """
    head = soup.find("head")
    if not head:
        return

    script_dir = str(PROJECT_ROOT / "scripts")
    added = script_dir not in sys.path
    if added:
        sys.path.insert(0, script_dir)
    try:
        from generate_lof_lot import build_lof_lot_css

        style_tag = soup.new_tag("style", id="lof-lot-styles")
        style_tag.string = build_lof_lot_css(format_style, use_leaders)
        head.append(style_tag)
    finally:
        if added:
            sys.path.remove(script_dir)


def _pdf_add_toc_page_numbers(
    index_pdf_path: Path,
    use_weasyprint: bool,
    toc_leaders: str,
    generate_lof: bool,
    generate_lot: bool,
) -> None:
    """Add TOC page numbers to the HTML working copy (Chrome headless two-pass)."""
    if use_weasyprint:
        return

    scripts_dir = PROJECT_ROOT / "scripts"

    logging.info("Adding TOC page numbers for Chrome headless (two-pass)...")
    toc_chrome_script = scripts_dir / "add_toc_page_numbers_chrome.py"
    if toc_chrome_script.exists() and chrome_path():
        cmd = [
            sys.executable,
            str(toc_chrome_script),
            str(index_pdf_path),
            chrome_path(),
            "--toc-leaders",
            toc_leaders,
        ]
        try:
            subprocess.run(cmd, check=True, timeout=300)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            logging.warning(f"Failed to add TOC page numbers: {exc}")

        if generate_lof or generate_lot:
            logging.info("Adding LOF/LOT page numbers for Chrome headless...")
            lof_lot_script = scripts_dir / "add_lof_lot_page_numbers_chrome.py"
            page_map_file = index_pdf_path.parent / "page_map_debug.txt"
            if lof_lot_script.exists() and page_map_file.exists():
                cmd = [sys.executable, str(lof_lot_script), str(index_pdf_path), str(page_map_file)]
                try:
                    subprocess.run(cmd, check=True, timeout=300)
                    logging.info("  LOF/LOT page numbers injected")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
                    logging.warning(f"Failed to inject LOF/LOT page numbers: {e}")
            else:
                if not lof_lot_script.exists():
                    logging.warning(f"LOF/LOT page numbers script not found: {lof_lot_script}")
                if not page_map_file.exists():
                    logging.warning(f"Page map file not found: {page_map_file}")

        # Drop the page-map debug file once the LOF/LOT step that consumes
        # it has run.  Build artifact, not user-facing.  Set
        # SPECBUILD_KEEP_DEBUG=1 to preserve it for debugging.
        page_map_file = index_pdf_path.parent / "page_map_debug.txt"
        if page_map_file.exists() and not os.environ.get("SPECBUILD_KEEP_DEBUG"):
            page_map_file.unlink()
    else:
        if not toc_chrome_script.exists():
            logging.warning(f"TOC page numbers script not found: {toc_chrome_script}")
        if not chrome_path():
            logging.warning("Chrome path not set")


def _pdf_strip_weasyprint_table_numbering(index_pdf_path: Path) -> None:
    """Remove JS-based table numbering and strip table caption prefixes for WeasyPrint.

    File-based wrapper around :func:`_pdf_strip_weasyprint_table_numbering_soup`.
    """
    logging.info("Removing table-numbering.js script from PDF HTML...")
    try:
        soup = read_html(index_pdf_path)
        _pdf_strip_weasyprint_table_numbering_soup(soup)
        write_html(index_pdf_path, soup)
    except Exception as e:
        logging.warning(f"Failed to remove table-numbering.js: {e}")


def _pdf_strip_weasyprint_table_numbering_soup(soup: Any) -> None:
    """Remove JS-based table numbering and strip table caption prefixes on soup.

    WeasyPrint uses CSS counters for table numbering, so the hardcoded
    "Table X.Y:" prefixes added by ``add_table_numbers_for_pdf.py`` must be
    removed.  Figure numbers in ``<figcaption>`` are intentionally preserved
    since there is no CSS-counter equivalent for figures.

    Args:
        soup: BeautifulSoup document (mutated in place).
    """
    # Matches prefixes like "Table 5.3:" or "Table A.1." at the start of caption text.
    # Groups: "Table" + whitespace + section.table (word chars) + optional colon/period.
    _table_prefix_re = re.compile(r"^Table\s+[\w]+\.[\w]+[:\.]?\s*")

    for script in soup.find_all("script", src=lambda x: x and "table-numbering.js" in x):
        script.decompose()
        logging.info("  Removed table-numbering.js script tag")

    stripped_count = 0
    for caption in soup.find_all("caption"):
        if "has-table-number" in caption.get("class", []):
            continue

        strong_tag = caption.find("strong")
        if strong_tag:
            strong_text = strong_tag.get_text()
            if _table_prefix_re.match(strong_text):
                strong_tag.decompose()
                stripped_count += 1
                logging.info(f"  Removed <strong> tag with table number: '{strong_text[:30]}'")
                continue

        caption_text = caption.get_text()
        cleaned_text = _table_prefix_re.sub("", caption_text)
        if cleaned_text != caption_text:
            strong = caption.find("strong")
            if strong:
                strong.decompose()
            else:
                from bs4 import NavigableString as _NS

                node = next((c for c in caption.children if isinstance(c, _NS)), None)
                if node:
                    node.replace_with(_NS(cleaned_text))
            stripped_count += 1
            logging.info(f"  Stripped text: '{caption_text[:50]}' -> '{cleaned_text[:50]}'")

    if stripped_count == 0:
        logging.info(
            f"  No table number prefixes found to strip "
            f"(found {len(soup.find_all('caption'))} captions)"
        )
    else:
        logging.info(f"  Stripped {stripped_count} table number prefixes")


# ---------------------------------------------------------------------------
# Engine-specific PDF generators
# ---------------------------------------------------------------------------


def _pdf_generate_weasyprint(
    index_pdf_path: Path,
    output_pdf: Path,
    toc_leaders: str,
    generate_lof: bool,
    generate_lot: bool,
    front_matter_order: list[str] | None,
    page_size: str = "letter",
) -> bool:
    """Generate a PDF using WeasyPrint.

    Falls back to Chrome headless on failure, returning False so the caller
    can invoke the Chrome path.

    Returns:
        True if WeasyPrint succeeded, False if it failed or was unavailable.
    """
    logging.info(
        "Using WeasyPrint for PDF generation with comprehensive TOC and table caption support..."
    )
    pdf_gen_script = PROJECT_ROOT / "scripts" / "generate_pdf_with_toc.py"

    if not pdf_gen_script.exists():
        logging.warning(f"PDF generation script not found: {pdf_gen_script}")
        return False

    try:
        if CONFIG.x86_python_path and Path(CONFIG.x86_python_path).exists():
            weasyprint_cmd_prefix = ["arch", "-x86_64", CONFIG.x86_python_path]
            logging.info(f"Using x86_64 Python for WeasyPrint: {CONFIG.x86_python_path}")
        else:
            weasyprint_cmd_prefix = [sys.executable]
            logging.info("Using default Python for WeasyPrint PDF generation")

        cmd = weasyprint_cmd_prefix + [
            str(pdf_gen_script),
            "--engine",
            "weasyprint",
            "-i",
            str(index_pdf_path),
            "-o",
            str(output_pdf),
            "--size",
            page_size,
        ]

        if toc_leaders != "none":
            cmd.extend(["--toc-leaders", toc_leaders])
            logging.info(f"  - TOC leader dots enabled ({toc_leaders} format)")
        if generate_lof:
            cmd.append("--lof")
            logging.info("  - List of Figures enabled")
        if generate_lot:
            cmd.append("--lot")
            logging.info("  - List of Tables enabled")
        if front_matter_order:
            cmd.extend(["--front-matter-order", ",".join(front_matter_order)])
            logging.info(f"  - Front-matter order: {', '.join(front_matter_order)}")

        logging.info("  - Accurate TOC page numbers via WeasyPrint box tree traversal")
        logging.info("  - Table captions with section.table numbering (Table X.Y)")
        logging.info("  - Back to TOC links")
        logging.info("  - Center-aligned captions")
        logging.info("  - MathJax equations pre-rendered")

        env = None
        homebrew_lib = homebrew_lib_for_dyld()
        if homebrew_lib:
            env = os.environ.copy()
            existing = env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
            env["DYLD_FALLBACK_LIBRARY_PATH"] = (
                f"{homebrew_lib}:{existing}" if existing else str(homebrew_lib)
            )
            logging.debug(
                f"DYLD_FALLBACK_LIBRARY_PATH={env['DYLD_FALLBACK_LIBRARY_PATH']} "
                "(arm64 Homebrew libs for WeasyPrint)"
            )

        subprocess.run(cmd, check=True, timeout=900, env=env)
        logging.info("PDF generated successfully with WeasyPrint")
        return True

    except subprocess.CalledProcessError as e:
        logging.error(f"Failed to generate PDF with WeasyPrint: {e}")
        logging.error("Falling back to Chrome headless...")
        return False


def _inject_page_size_css_soup(soup: Any, page_size: str) -> None:
    """Inject ``@page { size }`` override into a pre-parsed soup.

    Skipped for the ``"letter"`` default (``css/print.css`` already declares
    that size).  Uses :func:`specbuild.utils.inject_css` so the ``<style>``
    tag gets a dedup ``id``.

    Args:
        soup: BeautifulSoup document (mutated in place).
        page_size: CLI page-size value (``"letter"``, ``"a4"``, ``"legal"``).
    """
    if page_size == "letter":
        return

    css_size = _PAGE_SIZE_CSS_MAP.get(page_size, "letter")
    css = (
        f"/* Page-size override: {css_size} */\n"
        f"@media print {{\n"
        f"  @page {{ size: {css_size} !important; }}\n"
        f"}}\n"
    )
    inject_css(soup, "page-size-override", css)
    logging.info(f"Injected page-size override CSS: {css_size}")


def _pdf_generate_chrome(
    index_pdf_path: Path, output_pdf: Path, *, disable_tagging: bool = False
) -> bool:
    """Generate a PDF using Chrome headless printing.

    Args:
        index_pdf_path: Path to the HTML file to render.
        output_pdf: Path for the output PDF.
        disable_tagging: If True, pass ``--disable-pdf-tagging`` to Chrome
            to omit the PDF structure tree (StructElem objects) and
            marked-content operators (BDC/EMC).  This can reduce raw PDF
            size by 50-60% for large specs at the cost of losing PDF
            accessibility tagging.

    Returns:
        True if the PDF was generated successfully, False otherwise.
    """
    if chrome_path() is None:
        logging.error("Chrome not found on system. Please install Google Chrome.")
        logging.error("  - macOS: Install from https://www.google.com/chrome/")
        logging.error("  - Linux: sudo apt-get install google-chrome-stable")
        logging.error("  - Windows: Install from https://www.google.com/chrome/")
        return False

    if not Path(chrome_path()).exists():
        logging.error(f"Chrome not found at: {chrome_path()}")
        return False

    flags = [
        "--headless=new",  # New headless mode; handles macOS process policies better
        "--no-pdf-header-footer",  # Suppress Chrome's default header/footer
        "--disable-gpu",  # Required for headless on some systems
        "--run-all-compositor-stages-before-draw",  # Wait for full render
        "--virtual-time-budget=5000",  # 5 s virtual time (no MathJax JS since we use native MathML)
    ]
    if disable_tagging:
        flags.append("--disable-pdf-tagging")
        logging.info(
            "PDF tagging disabled (--disable-pdf-tagging): "
            "no StructElem tree or marked-content operators"
        )
    command = [chrome_path()] + flags + [f"--print-to-pdf={output_pdf}", str(index_pdf_path)]
    logging.info("Generating PDF with Chrome headless...")
    try:
        # Capture Chrome's stderr (e.g. "NNNNNN bytes written to file …")
        # and re-emit through our logger so output stays uniformly prefixed.
        result = subprocess.run(command, check=True, timeout=900, capture_output=True, text=True)
        for line in (result.stderr or "").splitlines():
            stripped = line.strip()
            if stripped:
                logging.info(f"chrome: {stripped}")
        return True
    except subprocess.CalledProcessError as exc:
        logging.error(f"Chrome PDF generation failed: {exc}")
        if exc.stderr:
            for line in exc.stderr.splitlines():
                if line.strip():
                    logging.error(f"chrome: {line.strip()}")
        return False


# ---------------------------------------------------------------------------
# Orchestrator helpers (extracted from generate_pdf for readability)
# ---------------------------------------------------------------------------


def _validate_pdf_engines(use_weasyprint: bool, *, optimize_pdf: bool = False) -> None:
    """Check that the required PDF rendering engine(s) are available.

    WeasyPrint mode falls back to Chrome, so missing WeasyPrint only warns.
    Chrome is always required for MathJax pre-rendering; in Chrome-only mode
    it is also the sole PDF renderer, so its absence is fatal.

    Raises:
        SystemExit: If Chrome is required but not found, or if
            ``optimize_pdf`` is requested but Ghostscript is missing.
    """
    if optimize_pdf and shutil.which("gs") is None:
        logging.error("Ghostscript (gs) not found on PATH — required by --optimize-pdf")
        logging.error("  macOS: brew install ghostscript")
        logging.error("  Linux: sudo apt-get install ghostscript")
        raise SystemExit(1)
    if use_weasyprint:
        try:
            import importlib

            importlib.import_module("weasyprint")
        except ImportError:
            logging.warning(
                "WeasyPrint not available in this process; "
                "will use subprocess via --x86-python if configured"
            )
            logging.warning("  Install with: pip install weasyprint")
        except OSError as exc:
            homebrew_lib = homebrew_lib_for_dyld()
            if homebrew_lib:
                logging.warning(
                    "WeasyPrint installed but its native libs aren't on the "
                    f"loader path in this process ({exc.__class__.__name__})."
                )
                logging.warning(
                    f"  The PDF subprocess will inject DYLD_FALLBACK_LIBRARY_PATH={homebrew_lib} "
                    "automatically — no action needed."
                )
                logging.warning(
                    "  For other tools (e.g. running weasyprint directly), add to your shell rc:"
                )
                logging.warning(
                    f"    export DYLD_FALLBACK_LIBRARY_PATH={homebrew_lib}:$DYLD_FALLBACK_LIBRARY_PATH"
                )
            else:
                logging.warning(f"WeasyPrint failed to load native libs: {exc}")
                logging.warning("  macOS: brew install pango")
                logging.warning("  Linux: sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0")

    # Chrome is needed for MathJax pre-rendering and as PDF fallback
    if not chrome_path():
        if use_weasyprint:
            logging.warning("Chrome not found — MathJax pre-rendering will be skipped")
        else:
            logging.error("Chrome not found on system. PDF generation requires Chrome.")
            logging.error("  macOS: Install from https://www.google.com/chrome/")
            logging.error("  Linux: sudo apt-get install google-chrome-stable")
            raise SystemExit(1)
    elif not Path(chrome_path()).exists():
        if use_weasyprint:
            logging.warning(
                f"Chrome not found at {chrome_path()} — MathJax pre-rendering will be skipped"
            )
        else:
            logging.error(f"Chrome not found at: {chrome_path()}")
            raise SystemExit(1)


def _pdf_zone_b(
    index_pdf_path: Path,
    *,
    use_weasyprint: bool,
    equation_font: str,
    equation_scale: float,
    section_headers: bool,
    generate_lof: bool,
    generate_lot: bool,
    toc_leaders: str,
    front_matter_order: list[str] | None,
) -> None:
    """Zone B: single-pass soup operations between MathJax and TOC subprocesses.

    Parses the HTML once, applies equation styling, section headers,
    LOF/LOT injection, and front-matter re-marking, then writes once.
    """
    soup = read_html(index_pdf_path)
    soup_dirty = False

    # Equation styling (font family and scale overrides)
    inject_equation_styling_soup(soup, equation_font, equation_scale)
    soup_dirty = True

    # Section headers (WeasyPrint only — no-op for Chrome)
    if section_headers:
        from specbuild.enhancements.sectionheaders import inject_section_headers_soup

        inject_section_headers_soup(soup, use_weasyprint=use_weasyprint)
        if use_weasyprint:
            soup_dirty = True

    # LOF/LOT injection (Chrome only — WeasyPrint handles this in its script)
    if not use_weasyprint:
        if _pdf_inject_lof_lot_soup(
            soup, generate_lof, generate_lot, toc_leaders, front_matter_order
        ):
            soup_dirty = True

    # Re-mark any newly added front-matter elements (e.g. LOF/LOT)
    from specbuild.enhancements.pagenumbers import remark_front_matter_soup

    if remark_front_matter_soup(soup):
        soup_dirty = True

    if soup_dirty:
        write_html(index_pdf_path, soup)
        logging.info(
            "Zone B: wrote single-pass soup (equation styling + "
            "section headers + LOF/LOT + front-matter)"
        )


def _pdf_zone_c(
    index_pdf_path: Path,
    output_pdf: Path,
    *,
    use_weasyprint: bool,
    font_size_increase: int,
    toc_leaders: str,
    generate_lof: bool,
    generate_lot: bool,
    front_matter_order: list[str] | None,
    page_size: str = "letter",
    disable_tagging: bool = False,
) -> None:
    """Zone C: post-TOC single-pass soup operations and final PDF rendering.

    Parses the HTML once to apply TOC page-number restyling and
    engine-specific mutations (WeasyPrint table stripping or Chrome
    font-size override), writes the result, then invokes the PDF engine.
    """
    soup = read_html(index_pdf_path)
    soup_dirty = False

    # Restyle TOC/LOF/LOT page numbers for dual numbering
    from specbuild.enhancements.pagenumbers import restyle_toc_page_numbers_soup

    if restyle_toc_page_numbers_soup(soup):
        soup_dirty = True

    generated = False

    if use_weasyprint:
        # Create a WeasyPrint-specific copy so Chrome fallback sees unstripped captions.
        # Read fresh, then apply both TOC restyle AND table stripping (WeasyPrint uses CSS
        # counters so the JS-based table numbers must be stripped before it renders).
        weasyprint_soup = read_html(index_pdf_path)
        restyle_toc_page_numbers_soup(weasyprint_soup)
        _pdf_strip_weasyprint_table_numbering_soup(weasyprint_soup)
        write_html(index_pdf_path, weasyprint_soup)
        logging.info(
            "Zone C: wrote WeasyPrint-specific soup (page number "
            "restyling + WeasyPrint table stripping)"
        )

        # Localize external resources (raw text replacement, not soup)
        _localize_external_resources(index_pdf_path)

        generated = _pdf_generate_weasyprint(
            index_pdf_path,
            output_pdf,
            toc_leaders,
            generate_lof,
            generate_lot,
            front_matter_order,
            page_size=page_size,
        )

        if not generated:
            # Restore the clean file so Chrome uses unstripped captions
            write_html(index_pdf_path, soup)

    if not generated:
        # Chrome path: optionally inject font size and page size overrides
        if font_size_increase > 0:
            inject_pdf_font_size_override_soup(soup, font_size_increase)
            soup_dirty = True

        _inject_page_size_css_soup(soup, page_size)
        if page_size != "letter":
            soup_dirty = True

        if soup_dirty:
            write_html(index_pdf_path, soup)
            logging.info(
                "Zone C: wrote single-pass soup (page number restyling + font size override)"
            )

        _pdf_generate_chrome(index_pdf_path, output_pdf, disable_tagging=disable_tagging)


# ---------------------------------------------------------------------------
# Post-generation PDF optimization
# ---------------------------------------------------------------------------


def _optimize_pdf_ghostscript(pdf_path: Path) -> bool:
    """Optimize a PDF using Ghostscript for smaller file size.

    Applies font subsetting, image deduplication, and stream compression
    using the ``/prepress`` quality setting (high quality, suitable for
    print distribution).

    The original file is replaced in-place if optimization succeeds.

    Args:
        pdf_path: Path to the PDF file to optimize.

    Returns:
        True if optimization succeeded, False otherwise.
    """
    gs_bin = shutil.which("gs")
    if gs_bin is None:
        logging.warning(
            "Ghostscript (gs) not found on PATH — skipping PDF optimization. "
            "Install with: brew install ghostscript (macOS) or "
            "apt-get install ghostscript (Linux)"
        )
        return False

    original_size = pdf_path.stat().st_size
    optimized_path = pdf_path.with_suffix(".optimized.pdf")

    # Clean up stale temp file from a previous interrupted run
    if optimized_path.exists():
        optimized_path.unlink()

    cmd = [
        gs_bin,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.5",
        "-dPDFSETTINGS=/prepress",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDetectDuplicateImages=true",
        f"-sOutputFile={optimized_path}",
        str(pdf_path),
    ]

    try:
        logging.info("Optimizing PDF with Ghostscript...")
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stderr:
            logging.debug(f"Ghostscript stderr: {result.stderr.strip()}")

        optimized_size = optimized_path.stat().st_size
        reduction = (1 - optimized_size / original_size) * 100 if original_size > 0 else 0

        # Sanity check: verify output is a valid PDF (not truncated/corrupt)
        with open(optimized_path, "rb") as f:
            magic = f.read(5)
        if magic != b"%PDF-" or optimized_size < 1024:
            logging.warning(
                f"Ghostscript produced invalid output ({optimized_size} bytes) "
                "— keeping original PDF"
            )
            optimized_path.unlink()
            return False

        if optimized_size < original_size:
            # Replace original with optimized version (atomic on POSIX)
            optimized_path.replace(pdf_path)
            logging.info(
                f"PDF optimized: {original_size / 1024 / 1024:.1f} MB → "
                f"{optimized_size / 1024 / 1024:.1f} MB ({reduction:.0f}% reduction)"
            )
        else:
            # Optimization didn't help — keep original
            optimized_path.unlink()
            logging.info(
                f"PDF optimization skipped (no size reduction: "
                f"{original_size / 1024 / 1024:.1f} MB)"
            )
        return True

    except subprocess.CalledProcessError as e:
        logging.warning(f"Ghostscript optimization failed: {e}")
        if e.stderr:
            logging.warning(f"Ghostscript error output: {e.stderr.strip()}")
        if optimized_path.exists():
            optimized_path.unlink()
        return False


# ---------------------------------------------------------------------------
# Public orchestrator
# ---------------------------------------------------------------------------


def generate_pdf(
    target_dir: Path,
    *,
    use_weasyprint: bool = False,
    font_size_increase: int = 0,
    toc_leaders: str = "css",
    equation_font: str = "default",
    equation_scale: float = 1.0,
    generate_lof: bool = False,
    generate_lot: bool = False,
    front_matter_order: list[str] | None = None,
    section_headers: bool = False,
    page_size: str = "letter",
    optimize_pdf: bool = False,
    no_pdf_tags: bool = False,
) -> None:
    """Generate a PDF from the compiled HTML specification.

    Uses a zone-based single-pass approach to minimize HTML parse/serialize
    cycles.  Operations are grouped around subprocess boundaries:

    - **Zone A** (subprocesses): table numbers, MathJax pre-rendering, SVG fixes.
    - **Zone B** (single parse/write): equation styling, section headers,
      LOF/LOT injection, front-matter re-marking.
    - **Subprocess boundary**: TOC page number extraction via Chrome.
    - **Zone C** (single parse/write): TOC page number restyling,
      WeasyPrint table stripping or Chrome font-size override.

    Args:
        target_dir (Path): Directory containing ``index.html``.
        use_weasyprint: Use WeasyPrint.
        font_size_increase: Points to add to base font sizes.
        toc_leaders: Leader style (``"none"``, ``"css"``, ``"table"``).
        equation_font: Equation font name.
        equation_scale: Equation scale factor.
        generate_lof: Generate List of Figures.
        generate_lot: Generate List of Tables.
        front_matter_order: Ordered front-matter keywords.
        section_headers: Inject running section titles in page headers.
        page_size: Page size (``"letter"``, ``"a4"``, or ``"legal"``).
        optimize_pdf: Run Ghostscript post-processing to reduce file size.
        no_pdf_tags: Disable Chrome PDF accessibility tagging to reduce size.
    """
    base_name = target_dir.name
    output_pdf = target_dir / f"{base_name}.pdf"
    index_path = target_dir / "index.html"

    index_pdf_path = target_dir / "index_pdf.html"
    if index_pdf_path.exists():
        index_pdf_path.unlink()
    shutil.copy2(index_path, index_pdf_path)
    logging.info(f"Created PDF working copy: {index_pdf_path}")
    logging.info(f"Generate PDF: {output_pdf}")

    _validate_pdf_engines(use_weasyprint, optimize_pdf=optimize_pdf)

    try:
        # ── Zone A: subprocess-based preprocessing ──────────────────────
        # These run external processes that must operate on files on disk.
        _pdf_preprocess_html(index_pdf_path, use_weasyprint=use_weasyprint)

        # ── Zone B: single-pass soup operations ─────────────────────────
        _pdf_zone_b(
            index_pdf_path,
            use_weasyprint=use_weasyprint,
            equation_font=equation_font,
            equation_scale=equation_scale,
            section_headers=section_headers,
            generate_lof=generate_lof,
            generate_lot=generate_lot,
            toc_leaders=toc_leaders,
            front_matter_order=front_matter_order,
        )

        # ── Subprocess boundary: TOC page numbers ───────────────────────
        # Chrome two-pass: generates temp PDF, extracts page numbers.
        _pdf_add_toc_page_numbers(
            index_pdf_path, use_weasyprint, toc_leaders, generate_lof, generate_lot
        )

        # ── Zone C: post-TOC single-pass soup operations ────────────────
        # --optimize-pdf implies --no-pdf-tags (tagging adds ~56% bloat)
        disable_tagging = no_pdf_tags or optimize_pdf
        _pdf_zone_c(
            index_pdf_path,
            output_pdf,
            use_weasyprint=use_weasyprint,
            font_size_increase=font_size_increase,
            toc_leaders=toc_leaders,
            generate_lof=generate_lof,
            generate_lot=generate_lot,
            front_matter_order=front_matter_order,
            page_size=page_size,
            disable_tagging=disable_tagging,
        )

        # ── Post-generation: Ghostscript optimization ─────────────────
        if optimize_pdf and output_pdf.exists():
            _optimize_pdf_ghostscript(output_pdf)
    finally:
        if index_pdf_path.exists():
            index_pdf_path.unlink()
            logging.info(f"Cleaned up PDF working copy: {index_pdf_path}")

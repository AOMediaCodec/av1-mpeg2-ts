#!/usr/bin/env python3
"""Build script for AV1-MPEG2-TS specification.

Usage:
  python compile.py            # Build with SDL syntax tables (default)
  python compile.py --no-sdl   # Build with raw code blocks (same as bikeshed spec)
  python compile.py --pdf      # Build with SDL tables and generate PDF via WeasyPrint
  python compile.py --date 2025-06-01  # Override the spec date
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import date as _date
from html import escape
from pathlib import Path

SOURCE = Path("index.bs")
COMPILED = Path("_index_compiled.bs")
HTML_OUT = Path("index.html")
PDF_OUT = Path("index.pdf")

# Matches descriptor lines: uimsbf(8) field_name;  or  bslbf(1) flag;  (semicolon optional)
# Also captures optional inline /* comment */
DESCRIPTOR_RE = re.compile(
    r"^(uimsbf|bslbf)\((\d+)\)\s+(.+?)(?:;)?\s*(/\*.*?\*/)?$"
)

# Matches function/syntax header: word_chars(optional params) {
HEADER_RE = re.compile(r"^\w[\w\s]*\([^)]*\)\s*\{")

# Matches the Date: field in the Bikeshed metadata block
DATE_RE = re.compile(r"^Date:\s*\S+", re.MULTILINE)


def _escape(text: str) -> str:
    return escape(text, quote=False)


def parse_sdl_to_table(code: str) -> str:
    """Convert a single SDL cpp block into a 2-column HTML syntax table."""
    lines = code.strip().splitlines()
    if not lines:
        return ""

    rows = []
    header_text = ""

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # Compute indentation level (4 spaces = 1 level)
        indent = (len(raw_line) - len(raw_line.lstrip())) // 4
        pad = f'style="padding-left: {indent}em"' if indent else ""

        # Function/structure header (first non-blank line matching header pattern)
        if not header_text and HEADER_RE.match(line):
            header_text = _escape(line)
            continue

        # Descriptor field line
        m = DESCRIPTOR_RE.match(line)
        if m:
            mnemonic, bits, name, comment = m.groups()
            name_escaped = _escape(name.strip())
            cell_content = f'<span {pad}>{name_escaped}'
            if comment:
                cell_content += f" <span class='sdl-comment'>{_escape(comment)}</span>"
            cell_content += "</span>"
            rows.append(
                f'<tr>'
                f'<td class="sdl-var-with-descriptor">{cell_content}</td>'
                f'<td class="sdl-descriptor">{mnemonic}({bits})</td>'
                f'</tr>'
            )
            continue

        # Control flow / assignment / closing brace
        cell_content = f'<span {pad}>{_escape(line)}</span>' if pad else _escape(line)
        rows.append(
            f'<tr>'
            f'<td class="sdl-code">{cell_content}</td>'
            f'<td class="sdl-descriptor"></td>'
            f'</tr>'
        )

    if not header_text:
        header_text = _escape(lines[0])

    html = (
        '<div class="sdl-syntax-wrapper">\n'
        '<table class="sdl-syntax-table">\n'
        '<thead><tr>'
        f'<th class="sdl-syntax-name">{header_text}</th>'
        '<th class="sdl-descriptor-header">Type</th>'
        '</tr></thead>\n'
        '<tbody>\n'
        + "\n".join(rows)
        + "\n</tbody>\n</table>\n</div>"
    )
    return html


def convert_sdl_blocks(content: str) -> str:
    """Replace all ```cpp ... ``` blocks in content with HTML tables."""
    pattern = re.compile(r"```cpp\n(.*?)```", re.DOTALL)

    def replace(m: re.Match) -> str:
        return parse_sdl_to_table(m.group(1))

    return pattern.sub(replace, content)


def build(use_sdl: bool = True, generate_pdf: bool = False, spec_date: str = None) -> None:
    if not SOURCE.exists():
        sys.exit(f"Error: {SOURCE} not found. Run from the repository root.")

    if spec_date is None:
        spec_date = _date.today().isoformat()

    mode = "SDL syntax tables" if use_sdl else "raw code blocks"
    print(f"Building {HTML_OUT} ({mode}, date: {spec_date}) …")

    content = SOURCE.read_text(encoding="utf-8")
    content = DATE_RE.sub(f"Date: {spec_date}", content)
    if use_sdl:
        content = convert_sdl_blocks(content)

    COMPILED.write_text(content, encoding="utf-8")
    try:
        subprocess.run(
            ["bikeshed", "spec", str(COMPILED), str(HTML_OUT)],
            check=True,
        )
    finally:
        COMPILED.unlink(missing_ok=True)

    print(f"HTML written to {HTML_OUT}")

    if generate_pdf:
        _generate_pdf()


PDF_CSS = """
@page {
    size: A4;
    margin: 2.5cm 2cm;
}
body {
    font-size: 9pt;
    line-height: 1.4;
}
img {
    max-width: 100% !important;
    height: auto !important;
}
figure img {
    max-width: 100% !important;
    width: auto !important;
    height: auto !important;
}
.spec-table {
    width: 100% !important;
    table-layout: fixed;
}
.spec-table td, .spec-table th {
    word-break: break-word;
    overflow-wrap: break-word;
}
/* Page number in footer on every page */
@page {
    @bottom-right {
        content: counter(page);
        font-size: 9pt;
    }
}
/* TOC page numbers */
#toc .toc a {
    display: flex;
    align-items: baseline;
}
#toc .toc a::after {
    content: target-counter(attr(href), page);
    flex-shrink: 0;
    margin-left: auto;
    padding-left: 1em;
}
"""


def _generate_pdf() -> None:
    if not HTML_OUT.exists():
        sys.exit(f"Error: {HTML_OUT} not found. Build HTML first.")

    # Inject PDF-specific styles into the HTML
    html_content = HTML_OUT.read_text(encoding="utf-8")
    pdf_style_tag = f"<style>{PDF_CSS}</style>"
    if "</head>" in html_content:
        html_content = html_content.replace("</head>", f"{pdf_style_tag}\n</head>", 1)
    else:
        html_content = pdf_style_tag + html_content

    # Write patched HTML to a temp file so WeasyPrint resolves relative paths correctly
    tmp_html = HTML_OUT.with_suffix(".pdf.html")
    tmp_html.write_text(html_content, encoding="utf-8")

    # Build environment — on macOS ensure Homebrew libs are findable by WeasyPrint/Pango
    env = os.environ.copy()
    if sys.platform == "darwin":
        homebrew_lib = "/opt/homebrew/lib"
        existing = env.get("DYLD_LIBRARY_PATH", "")
        if homebrew_lib not in existing:
            env["DYLD_LIBRARY_PATH"] = f"{homebrew_lib}:{existing}" if existing else homebrew_lib

    script = (
        f"from weasyprint import HTML; "
        f"HTML(filename='{tmp_html}').write_pdf('{PDF_OUT}')"
    )
    print(f"Generating {PDF_OUT} …")
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.exit(f"WeasyPrint failed:\n{result.stderr}")
        print(f"PDF written to {PDF_OUT}")
    finally:
        tmp_html.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the AV1-MPEG2-TS specification.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--no-sdl",
        action="store_true",
        help="Render syntax blocks as code blocks instead of HTML tables",
    )
    parser.add_argument(
        "--pdf",
        action="store_true",
        help="Generate PDF output via WeasyPrint (requires: pip install weasyprint)",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Override the spec date (default: today's date)",
    )
    args = parser.parse_args()
    build(use_sdl=not args.no_sdl, generate_pdf=args.pdf, spec_date=args.date)


if __name__ == "__main__":
    main()

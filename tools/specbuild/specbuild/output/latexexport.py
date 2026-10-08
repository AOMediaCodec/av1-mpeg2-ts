"""LaTeX export: convert compiled HTML specification to LaTeX.

Converts the main structural elements of the specification:

- Section headings (mapped to \\section, \\subsection, etc.)
- Paragraphs
- Tables (tabular environment)
- Figures and images
- Definition lists
- Code blocks (verbatim/lstlisting)
- Cross-references (\\ref, \\label)
- Basic inline formatting (bold, italic, code)
- Inline and display math (from span.math-expr and equation-wrapper divs)
- Notes, examples, and admonitions
- Bibliography / references sections
- Annex (appendix) sections

The output is a standalone LaTeX document with a preamble suitable
for compilation with pdflatex or xelatex.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from specbuild.utils import HEADING_TAGS, get_bs4, read_html

# Module-level reference to the current soup being processed (for footnote lookup)
_current_soup: object = None

# Set to True once \appendix has been emitted (to avoid emitting it twice)
_in_appendix: bool = False

# Heading level -> LaTeX command mapping
_LATEX_HEADING = {
    1: "chapter",
    2: "section",
    3: "subsection",
    4: "subsubsection",
    5: "paragraph",
    6: "subparagraph",
}

# Pattern to detect annex/appendix headings
_ANNEX_RE = re.compile(r"(?i)^(annex|appendix)\s+([A-Z])")


def export_latex(html_path: Path, output_path: Path | None = None) -> Path | None:
    """Convert compiled HTML to LaTeX.

    Args:
        html_path: Path to the compiled HTML file.
        output_path: Destination .tex path (default: sibling of html_path).

    Returns:
        Path to the generated LaTeX file, or None on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping LaTeX export")
        return None

    try:
        soup = read_html(html_path)
    except (FileNotFoundError, OSError) as exc:
        logging.error(f"LaTeX export: cannot read {html_path}: {exc}")
        return None
    latex = export_latex_soup(soup)

    if output_path is None:
        output_path = html_path.with_suffix(".tex")

    try:
        output_path.write_text(latex, encoding="utf-8")
    except OSError as exc:
        logging.error(f"LaTeX export: cannot write {output_path}: {exc}")
        return None
    logging.info(f"LaTeX export written to {output_path}")
    return output_path


def export_latex_soup(soup: object) -> str:
    """Convert parsed HTML to a LaTeX document string.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        Complete LaTeX document string.
    """
    global _current_soup, _in_appendix
    _current_soup = soup
    _in_appendix = False

    # Extract title
    title_elem = soup.find("h1") or soup.find("title")
    title = _escape_latex(title_elem.get_text(strip=True)) if title_elem else "Specification"

    # Build document body
    main = soup.find("main") or soup.find("body") or soup
    body = _convert_element(main)

    return _PREAMBLE.format(title=title) + body + "\n\\end{document}\n"


def _convert_element(elem: object) -> str:
    """Recursively convert an HTML element to LaTeX."""
    global _in_appendix

    if not hasattr(elem, "name") or elem.name is None:
        # NavigableString
        return _escape_latex(str(elem))

    name = elem.name

    # Skip script, style, nav, footer
    if name in ("script", "style", "nav", "footer", "header"):
        return ""

    # Headings
    if name in HEADING_TAGS:
        level = int(name[1])
        text = _inline_text(elem)
        raw_text = elem.get_text(strip=True)
        sec_id = elem.get("id", "")
        label = f"\\label{{{sec_id}}}" if sec_id else ""

        # Detect annex/appendix headings — emit \appendix once then use \section
        if level <= 2 and _ANNEX_RE.match(raw_text):
            prefix = ""
            if not _in_appendix:
                _in_appendix = True
                prefix = "\n\\appendix\n"
            return f"{prefix}\n\\section{{{text}}}{label}\n"

        cmd = _LATEX_HEADING.get(level, "paragraph")
        return f"\n\\{cmd}{{{text}}}{label}\n"

    # Paragraph
    if name == "p":
        text = _inline_text(elem)
        if text.strip():
            return f"\n{text}\n"
        return ""

    # Code blocks
    if name == "pre":
        code = elem.find("code")
        raw = code.get_text() if code else elem.get_text()
        lang = elem.get("highlight") or elem.get("data-highlight") or ""
        if not lang and code:
            cls = " ".join(code.get("class", []))
            m = re.search(r"language-(\w+)|highlight-(\w+)", cls)
            if m:
                lang = m.group(1) or m.group(2)
        if lang:
            return f"\n\\begin{{lstlisting}}[language={lang}]\n{raw}\\end{{lstlisting}}\n"
        return f"\n\\begin{{lstlisting}}\n{raw}\\end{{lstlisting}}\n"

    # Inline code
    if name == "code":
        parent = elem.parent
        if parent and parent.name == "pre":
            return ""  # Handled by pre
        return f"\\texttt{{{_escape_latex(elem.get_text())}}}"

    # Bold
    if name in ("strong", "b"):
        return f"\\textbf{{{_inline_text(elem)}}}"

    # Italic
    if name in ("em", "i"):
        return f"\\textit{{{_inline_text(elem)}}}"

    # Definition term
    if name == "dfn":
        return f"\\textbf{{{_inline_text(elem)}}}"

    # Superscript / subscript
    if name == "sup":
        # Detect footnote reference pattern: <sup><a href="#fn-N">
        for child in elem.children:
            if hasattr(child, "name") and child.name == "a":
                classes = child.get("class", [])
                href = child.get("href", "")
                if "footnote-ref" in classes and href.startswith("#"):
                    fn_id = href[1:]
                    fn_text = _resolve_footnote(fn_id)
                    if fn_text:
                        return f"\\footnote{{{_escape_latex(fn_text)}}}"
        return f"$^{{{_inline_text(elem)}}}$"

    if name == "sub":
        return f"$_{{{_inline_text(elem)}}}$"

    # Inline math span
    if name == "span":
        classes = elem.get("class", [])
        if any(c in classes for c in ("math-expr", "math", "formula", "inline-math")):
            math_text = elem.get_text(strip=True)
            return f"${math_text}$"
        return _convert_children(elem)

    # Links
    if name == "a":
        href = elem.get("href", "")
        text = _inline_text(elem)
        classes = elem.get("class", [])
        # Footnote reference
        if "footnote-ref" in classes and href.startswith("#"):
            fn_id = href[1:]
            fn_text = _resolve_footnote(fn_id)
            if fn_text:
                return f"\\footnote{{{_escape_latex(fn_text)}}}"
        # Internal link
        if href.startswith("#"):
            ref_id = href[1:]
            return f"\\hyperref[{ref_id}]{{{text}}}"
        elif href.startswith(("http://", "https://")):
            escaped_href = _escape_latex(href)
            return f"\\href{{{escaped_href}}}{{{text}}}"
        return text

    # Images / figures
    if name == "figure":
        return _convert_figure(elem)

    if name == "img":
        # Standalone image (not in figure)
        parent = elem.parent
        if parent and parent.name == "figure":
            return ""  # Handled by figure
        src = elem.get("src", "")
        return f"\\includegraphics[width=0.8\\textwidth]{{{_escape_latex(src)}}}"

    # Tables
    if name == "table":
        return _convert_table(elem)

    # Lists
    if name == "ul":
        items = "\n".join(
            f"  \\item {_inline_text(li)}" for li in elem.find_all("li", recursive=False)
        )
        return f"\n\\begin{{itemize}}\n{items}\n\\end{{itemize}}\n"

    if name == "ol":
        items = "\n".join(
            f"  \\item {_inline_text(li)}" for li in elem.find_all("li", recursive=False)
        )
        return f"\n\\begin{{enumerate}}\n{items}\n\\end{{enumerate}}\n"

    # Definition list
    if name == "dl":
        classes = elem.get("class", [])
        # Bibliography DL — emit as thebibliography
        if "bibliography" in classes:
            return _convert_bibliography_dl(elem)
        parts = ["\n\\begin{description}"]
        for child in elem.children:
            if hasattr(child, "name"):
                if child.name == "dt":
                    parts.append(f"  \\item[{_inline_text(child)}]")
                elif child.name == "dd":
                    parts.append(f"    {_inline_text(child)}")
        parts.append("\\end{description}\n")
        return "\n".join(parts)

    # Blockquote
    if name == "blockquote":
        return f"\n\\begin{{quote}}\n{_convert_children(elem)}\\end{{quote}}\n"

    # Div — check for semantic classes
    if name == "div":
        return _convert_div(elem)

    # Section — check for references/bibliography
    if name == "section":
        return _convert_section_element(elem)

    # Generic container — recurse
    if name in (
        "article",
        "main",
        "body",
        "li",
        "dd",
        "dt",
        "td",
        "th",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "figcaption",
        "caption",
    ):
        return _convert_children(elem)

    # Skip unknown elements but process children
    return _convert_children(elem)


def _convert_children(elem: object) -> str:
    """Convert all children of an element."""
    parts: list[str] = []
    for child in elem.children:
        parts.append(_convert_element(child))
    return "".join(parts)


def _inline_text(elem: object) -> str:
    """Convert an element's content to inline LaTeX."""
    return _convert_children(elem)


def _convert_div(elem: object) -> str:
    """Convert a <div> element, handling semantic classes."""
    classes = elem.get("class", [])

    if "note" in classes:
        content = _convert_children(elem)
        return f"\n\\begin{{specnote}}{{NOTE}}\n{content}\\end{{specnote}}\n"

    if "example" in classes:
        content = _convert_children(elem)
        return f"\n\\begin{{specnote}}{{EXAMPLE}}\n{content}\\end{{specnote}}\n"

    if any(c in classes for c in ("advisement", "warning", "caution")):
        content = _convert_children(elem)
        label = (
            "WARNING"
            if "warning" in classes
            else "CAUTION"
            if "caution" in classes
            else "IMPORTANT"
        )
        return f"\n\\begin{{specnote}}{{{label}}}\n{content}\\end{{specnote}}\n"

    if "equation-wrapper" in classes:
        return _convert_equation_wrapper(elem)

    return _convert_children(elem)


def _convert_equation_wrapper(elem: object) -> str:
    """Convert an equation-wrapper <div> to a LaTeX equation environment."""
    # Capture equation ID from the number span before any text extraction
    num_span = elem.find("span", class_="equation-number")
    eq_id = num_span.get("id", "") if num_span else ""

    tex = elem.get("data-tex", "")
    if not tex:
        ann = elem.find("annotation", {"encoding": "application/x-tex"})
        if ann:
            tex = ann.get_text(strip=True)
    if not tex:
        for p in elem.find_all("p"):
            text = p.get_text(strip=True)
            m = re.match(r"^\$\$(.+?)\$\$\s*$", text, re.DOTALL)
            if m:
                tex = m.group(1).strip()
                break
    if not tex:
        # Last resort: concatenate text nodes that are not equation-number spans
        parts: list[str] = []
        for child in elem.children:
            if hasattr(child, "get") and "equation-number" in (child.get("class") or []):
                continue
            parts.append(child.get_text() if hasattr(child, "get_text") else str(child))
        tex = "".join(parts).strip()

    if eq_id:
        return f"\n\\begin{{equation}}\\label{{{eq_id}}}\n{tex}\n\\end{{equation}}\n"
    return f"\n\\begin{{equation}}\n{tex}\n\\end{{equation}}\n"


def _convert_section_element(elem: object) -> str:
    """Convert a <section> element, detecting bibliography sections."""
    heading = elem.find(["h1", "h2", "h3", "h4", "h5", "h6"])

    if heading is not None:
        raw_text = heading.get_text(strip=True)
        if re.match(
            r"(?i)^(?:\d[\d.]*\s+)?(bibliography|normative\s+references?|informative\s+references?|references?)$",
            raw_text,
        ):
            return _convert_references_section(elem)

    return _convert_children(elem)


def _convert_references_section(section: object) -> str:
    """Convert a references section to a LaTeX bibliography."""
    heading = section.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    title = heading.get_text(strip=True) if heading else "References"

    entries: list[str] = []

    # Entries in <li> elements
    for li in section.find_all("li"):
        li_id = li.get("id", "")
        key = li_id[len("ref-") :] if li_id.startswith("ref-") else li_id
        text = _escape_latex(li.get_text(strip=True))
        if key:
            entries.append(f"  \\bibitem{{{key}}}\n  {text}")
        else:
            entries.append(f"  \\bibitem{{{text[:20].replace(' ', '-')}}}\n  {text}")

    # Entries in <dd> elements (bibliography DL style)
    for dd in section.find_all("dd"):
        dd_id = dd.get("id", "")
        key = dd_id[len("biblio-") :] if dd_id.startswith("biblio-") else dd_id
        text = _escape_latex(dd.get_text(strip=True))
        if key:
            entries.append(f"  \\bibitem{{{key}}}\n  {text}")

    if not entries:
        return _convert_children(section)

    body = "\n\n".join(entries)
    return (
        f"\n\\phantomsection\n\\addcontentsline{{toc}}{{section}}{{{_escape_latex(title)}}}\n"
        f"\\section*{{{_escape_latex(title)}}}\n"
        f"\\begin{{thebibliography}}{{99}}\n{body}\n\\end{{thebibliography}}\n"
    )


def _convert_bibliography_dl(dl: object) -> str:
    """Convert a <dl class="bibliography"> to LaTeX bibliography entries."""
    entries: list[str] = []
    for dt in dl.find_all("dt", recursive=False):
        dt_id = dt.get("id", "")
        key = dt_id[len("biblio-") :] if dt_id.startswith("biblio-") else dt.get_text(strip=True)
        if not key:
            continue
        dd = dt.find_next_sibling("dd")
        if dd:
            text = _escape_latex(dd.get_text(strip=True))
            entries.append(f"  \\bibitem{{{key}}}\n  {text}")
    if not entries:
        return ""
    body = "\n\n".join(entries)
    return f"\n\\begin{{thebibliography}}{{99}}\n{body}\n\\end{{thebibliography}}\n"


def _convert_table(table: object) -> str:
    """Convert an HTML table to LaTeX tabular with colspan/rowspan support."""
    rows = table.find_all("tr")
    if not rows:
        return ""

    # Determine column count from first row
    first_cells = rows[0].find_all(["td", "th"])
    ncols = sum(int(c.get("colspan", "1")) for c in first_cells)
    if ncols == 0:
        ncols = 1
    col_spec = "|" + "l|" * ncols

    parts = [f"\n\\begin{{tabular}}{{{col_spec}}}", "\\hline"]

    for row in rows:
        cells = row.find_all(["td", "th"])
        cell_texts: list[str] = []
        for cell in cells:
            text = _inline_text(cell)
            if cell.name == "th":
                text = f"\\textbf{{{text}}}"
            colspan = int(cell.get("colspan", "1"))
            rowspan = int(cell.get("rowspan", "1"))
            if colspan > 1 and rowspan > 1:
                # Both: multicolumn wrapping multirow
                inner = f"\\multirow{{{rowspan}}}{{*}}{{{text}}}"
                text = f"\\multicolumn{{{colspan}}}{{c}}{{{inner}}}"
            elif colspan > 1:
                text = f"\\multicolumn{{{colspan}}}{{c}}{{{text}}}"
            elif rowspan > 1:
                text = f"\\multirow{{{rowspan}}}{{*}}{{{text}}}"
            cell_texts.append(text)
        parts.append(" & ".join(cell_texts) + " \\\\")
        parts.append("\\hline")

    parts.append("\\end{tabular}\n")

    # Wrap in table environment if there's a caption
    caption = table.find("caption")
    if caption:
        table_parts = ["\n\\begin{table}[htbp]", "\\centering"]
        table_parts.append("\n".join(parts))
        table_parts.append(f"\\caption{{{_inline_text(caption)}}}")
        tid = table.get("id", "")
        if tid:
            table_parts.append(f"\\label{{{tid}}}")
        table_parts.append("\\end{table}\n")
        return "\n".join(table_parts)

    return "\n".join(parts)


def _convert_figure(figure: object) -> str:
    """Convert a <figure> element, supporting single images and subfigures."""
    caption = figure.find("figcaption")
    fig_id = figure.get("id", "")

    # Collect direct child <figure> and <img> elements (subfigure detection)
    child_figures = figure.find_all("figure", recursive=False)
    # Also count direct <img> children that are not inside a nested figure
    direct_imgs = [c for c in figure.children if hasattr(c, "name") and c.name == "img"]

    if len(child_figures) >= 2 or (len(child_figures) == 0 and len(direct_imgs) >= 2):
        # Subfigure layout
        panels = child_figures if child_figures else direct_imgs
        parts = ["\n\\begin{figure}[htbp]", "\\centering"]
        for panel in panels:
            if hasattr(panel, "name") and panel.name == "figure":
                sub_img = panel.find("img")
                sub_cap = panel.find("figcaption")
                src = _escape_latex(sub_img.get("src", "") if sub_img else "")
                sub_cap_text = _inline_text(sub_cap) if sub_cap else ""
            else:
                # direct img
                src = _escape_latex(panel.get("src", ""))
                sub_cap_text = ""
            parts.append("  \\begin{subfigure}[b]{0.45\\textwidth}")
            parts.append(f"    \\includegraphics[width=\\linewidth]{{{src}}}")
            if sub_cap_text:
                parts.append(f"    \\caption{{{sub_cap_text}}}")
            parts.append("  \\end{subfigure}")
            parts.append("  \\hfill")
        # Remove trailing \hfill
        if parts and parts[-1] == "  \\hfill":
            parts.pop()
        if caption:
            parts.append(f"\\caption{{{_inline_text(caption)}}}")
        if fig_id:
            parts.append(f"\\label{{{fig_id}}}")
        parts.append("\\end{figure}\n")
        return "\n".join(parts)

    # Single image
    img = figure.find("img")
    parts = ["\n\\begin{figure}[htbp]", "\\centering"]
    if img:
        src = img.get("src", "")
        parts.append(f"\\includegraphics[width=0.8\\textwidth]{{{_escape_latex(src)}}}")
    if caption:
        parts.append(f"\\caption{{{_inline_text(caption)}}}")
    if fig_id:
        parts.append(f"\\label{{{fig_id}}}")
    parts.append("\\end{figure}\n")
    return "\n".join(parts)


def _resolve_footnote(fn_id: str) -> str:
    """Look up footnote text by id from the current soup being processed."""
    global _current_soup
    if _current_soup is None:
        return ""
    fn_elem = _current_soup.find(id=fn_id)
    if fn_elem is None:
        return ""
    return fn_elem.get_text(strip=True)


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text.

    Uses a single-pass regex so that the ``\\textbackslash{}`` replacement
    produced for a literal ``\\`` is never re-escaped by the brace step.
    """
    # Map each special character to its LaTeX encoding.  The regex alternation
    # processes every character exactly once in document order.
    _SPECIAL = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }
    _LATEX_SPECIAL_RE = re.compile(r"[\\&%$#_{}~^]")
    return _LATEX_SPECIAL_RE.sub(lambda m: _SPECIAL[m.group(0)], text)


_PREAMBLE = r"""\documentclass[11pt,a4paper]{{article}}
\usepackage[utf8]{{inputenc}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}
\usepackage{{graphicx}}
\usepackage{{hyperref}}
\usepackage{{listings}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{multirow}}
\usepackage{{subcaption}}
\usepackage{{amsmath}}
\usepackage{{amssymb}}
\usepackage[margin=2.5cm]{{geometry}}

\lstset{{
  basicstyle=\ttfamily\small,
  breaklines=true,
  frame=single,
  captionpos=b,
}}

% Note/example/admonition box
\usepackage{{mdframed}}
\newenvironment{{specnote}}[1]{{%
  \begin{{mdframed}}[linewidth=0.5pt,innertopmargin=4pt,innerbottommargin=4pt]%
  \noindent\textbf{{#1}}\quad%
}}{{%
  \end{{mdframed}}%
}}

\title{{{title}}}
\date{{}}

\begin{{document}}
\maketitle
\tableofcontents
\newpage

"""

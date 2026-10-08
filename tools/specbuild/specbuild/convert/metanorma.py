"""Metanorma/AsciiDoc → Bikeshed (.bs) converter.

Converts a Metanorma ISO AsciiDoc project into a Bikeshed source tree
suitable for use with the specbuild pipeline.

Usage (programmatic)::

    from specbuild.convert.metanorma import convert_project
    result = convert_project("/path/to/metanorma/project", "/path/to/output")

Usage (CLI)::

    python convert.py --from metanorma /path/to/project --output /path/to/output
"""

from __future__ import annotations

import logging
import re
import shutil
import string
from pathlib import Path

# Translation table for converting single-digit subscripts to Unicode subscript characters.
# Used by _asciimathml_operators to avoid combining accent chars landing on HTML tags.
_UNICODE_SUBSCRIPTS = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def convert_project(
    input_path: str | Path,
    output_path: str | Path,
    *,
    overwrite: bool = False,
    single_file: bool = False,
    scaffold: bool = True,
) -> dict:
    """Convert a Metanorma AsciiDoc project to a Bikeshed source tree.

    Args:
        input_path: Path to the Metanorma project directory OR main ``.adoc`` file.
        output_path: Destination directory for the Bikeshed project.
        overwrite: If True, overwrite files in an existing output directory.
        single_file: If True, merge all sections into a single ``.bs`` file.
        scaffold: If True (default), copy the specbuild pipeline (scripts, css,
            js, config, compile.py) into the output so the project is
            immediately buildable.

    Returns:
        Dict with keys ``sections`` (list of converted file paths),
        ``warnings`` (list of warning strings), ``output_dir`` (Path).
    """
    inp = Path(input_path)
    out = Path(output_path)

    # Locate main .adoc file
    if inp.is_file():
        main_adoc = inp
        project_dir = inp.parent
    else:
        adoc_files = list(inp.glob("*.adoc"))
        if not adoc_files:
            raise FileNotFoundError(f"No .adoc file found in {inp}")
        # Prefer the one that has the most :key: attributes (main doc)
        main_adoc = max(adoc_files, key=lambda f: f.read_text("utf-8").count(":"))
        project_dir = inp

    text = main_adoc.read_text(encoding="utf-8")
    meta = _extract_metadata(text)
    includes = _find_includes(text, project_dir)

    if not out.exists():
        out.mkdir(parents=True)
    elif not overwrite:
        raise FileExistsError(
            f"Output directory already exists: {out}. Use --overwrite to continue."
        )

    bs_dir = out / "bikeshed"
    bs_dir.mkdir(exist_ok=True)

    warnings: list[str] = []
    converted: list[Path] = []
    annex_counter = [0]  # mutable for closures
    used_slugs: set[str] = set()  # shared across all sections for heading deduplication

    if single_file:
        # Merge everything into one .bs file
        all_lines: list[str] = []
        first = True
        for src_path in includes:
            src_text = src_path.read_text(encoding="utf-8")
            # Resolve nested includes relative to this file's directory
            src_text = _resolve_includes(src_text, src_path.parent)
            doc_attrs = {
                "docname": src_path.stem,
                "docfile": src_path.name,
                "docdir": str(src_path.parent),
            }
            lines, warns = convert_section(
                src_text,
                annex_counter=annex_counter,
                meta=meta,
                used_slugs=used_slugs,
                doc_attrs=doc_attrs,
            )
            if first:
                header = _build_bs_metadata(meta)
                all_lines = header + [""] + lines
                first = False
            else:
                all_lines += [""] + lines
            warnings.extend(warns)
        bs_file = bs_dir / "index.bs"
        bs_file.write_text("\n".join(all_lines), encoding="utf-8")
        converted.append(bs_file)
        manifest_lines = ["index.bs"]
    else:
        manifest_lines: list[str] = []
        for i, src_path in enumerate(includes):
            src_text = src_path.read_text(encoding="utf-8")
            # Resolve nested includes relative to this file's directory
            src_text = _resolve_includes(src_text, src_path.parent)
            doc_attrs = {
                "docname": src_path.stem,
                "docfile": src_path.name,
                "docdir": str(src_path.parent),
            }
            lines, warns = convert_section(
                src_text,
                annex_counter=annex_counter,
                meta=meta,
                used_slugs=used_slugs,
                doc_attrs=doc_attrs,
            )
            warnings.extend(warns)

            # First file gets the Bikeshed metadata block prepended
            if i == 0:
                header = _build_bs_metadata(meta)
                lines = header + [""] + lines

            bs_name = src_path.stem + ".bs"
            bs_file = bs_dir / bs_name
            bs_file.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
            converted.append(bs_file)
            manifest_lines.append(bs_name)

    # Write manifest.txt
    manifest_path = bs_dir / "manifest.txt"
    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")

    # Write specbuild.toml
    toml_path = out / "specbuild.toml"
    toml_path.write_text(_build_specbuild_toml(meta), encoding="utf-8")

    # Copy all asset directories from the source project (images, fonts, etc.)
    for asset_dir in project_dir.iterdir():
        if asset_dir.is_dir() and asset_dir.name not in ("sections", ".git", "__pycache__"):
            dst = out / asset_dir.name
            if dst.exists():
                if overwrite:
                    shutil.rmtree(dst)
                else:
                    continue
            shutil.copytree(asset_dir, dst)
            logging.info(f"Copied {asset_dir.name}/ → {dst}")

    # Scaffold the specbuild pipeline into the output directory
    if scaffold:
        _scaffold_specbuild(out, overwrite=overwrite)

    logging.info(f"Converted {len(converted)} section(s) → {out}. {len(warnings)} warning(s).")

    return {
        "sections": converted,
        "warnings": warnings,
        "output_dir": out,
        "metadata": meta,
    }


# ---------------------------------------------------------------------------
# Nested include resolution
# ---------------------------------------------------------------------------

_INCLUDE_RE = re.compile(r"^include::([^\[]+)\[([^\]]*)\]")


# Tag/end markers inside an included file. AsciiDoc:
#   // tag::foo[]
#   ...content...
#   // end::foo[]
_TAG_OPEN_RE = re.compile(r"//\s*tag::([\w-]+)\[\]")
_TAG_END_RE = re.compile(r"//\s*end::([\w-]+)\[\]")


def _filter_by_tags(text: str, tag_spec: str) -> str:
    """Filter *text* by AsciiDoc ``tag=`` / ``tags=`` specifiers.

    *tag_spec* is a semicolon-separated list of tag names.  Lines between the
    matching ``// tag::name[]`` and ``// end::name[]`` markers are kept; tag
    marker lines themselves are dropped.  All other content is excluded.
    """
    wanted = {t.strip() for t in tag_spec.split(";") if t.strip()}
    if not wanted:
        return text
    out: list[str] = []
    active: set[str] = set()
    for line in text.splitlines():
        m_open = _TAG_OPEN_RE.search(line)
        if m_open:
            active.add(m_open.group(1))
            continue
        m_end = _TAG_END_RE.search(line)
        if m_end:
            active.discard(m_end.group(1))
            continue
        if active & wanted:
            out.append(line)
    return "\n".join(out)


def _parse_include_attrs(attr_str: str) -> dict[str, str]:
    """Parse the ``key=value,key=value`` attribute list of an include directive."""
    attrs: dict[str, str] = {}
    for part in attr_str.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            attrs[k.strip()] = v.strip()
    return attrs


# ---------------------------------------------------------------------------
# Nested include resolution
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Conditional directive evaluation
# ---------------------------------------------------------------------------

# Block-form directive open: matches ifdef::/ifndef:: with empty []
# Group 1: directive kind ("def" or "ndef")
# Group 2: attr-list expression
_IFDEF_OPEN_RE = re.compile(r"^\s*if(n?def)::([^\[]*)\[\s*\]\s*$")
# ifeval block form: ifeval::[expr] — comparison expression INSIDE brackets.
# Group 1: comparison expression body.
_IFEVAL_OPEN_RE = re.compile(r"^\s*ifeval::\[(.+)\]\s*$")
_IFDEF_INLINE_RE = re.compile(r"^\s*if(n?def)::([^\[]*)\[(.+)\]\s*$")
_ENDIF_RE = re.compile(r"^\s*endif::[^\[]*\[\s*\]\s*$")

# Comparison operators recognised inside ``ifeval::[...]`` (longest first so
# >= and <= match before > and <).
_IFEVAL_OPS = ("==", "!=", ">=", "<=", ">", "<")


def _attr_defined(attr_expr: str, meta: dict[str, str]) -> bool:
    """Evaluate an AsciiDoc attribute expression against *meta*.

    Supports the comma-OR (``a,b``) and plus-AND (``a+b``) forms used by
    ``ifdef::``/``ifndef::``.  An empty expression evaluates to False.
    """
    expr = attr_expr.strip()
    if not expr:
        return False
    if "," in expr:
        return any(_attr_defined(p, meta) for p in expr.split(","))
    if "+" in expr:
        return all(_attr_defined(p, meta) for p in expr.split("+"))
    return expr.strip() in meta


def _eval_ifeval(expr: str, meta: dict[str, str]) -> bool:
    """Evaluate an ``ifeval::["{a}" == "b"]`` style comparison.

    Substitutes ``{attr}`` references from *meta*, then compares the two sides
    using one of ``==``, ``!=``, ``>=``, ``<=``, ``>``, ``<``.  Numeric
    comparisons fall back to string comparison if either side is not numeric.
    Unparseable expressions evaluate to ``False``.
    """
    if not expr or not expr.strip():
        return False

    def _subst(s: str) -> str:
        return _ATTR_REF_RE.sub(lambda m: meta.get(m.group(1), m.group(0)), s)

    def _strip(s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
            s = s[1:-1]
        return s

    op_used: str | None = None
    lhs_raw: str = ""
    rhs_raw: str = ""
    for op in _IFEVAL_OPS:
        idx = expr.find(op)
        if idx != -1:
            op_used = op
            lhs_raw = expr[:idx]
            rhs_raw = expr[idx + len(op) :]
            break
    if op_used is None:
        return False

    lhs = _strip(_subst(lhs_raw))
    rhs = _strip(_subst(rhs_raw))

    if op_used == "==":
        return lhs == rhs
    if op_used == "!=":
        return lhs != rhs
    # numeric comparison; fall back to string compare on ValueError
    try:
        l_num = float(lhs)
        r_num = float(rhs)
        if op_used == ">":
            return l_num > r_num
        if op_used == "<":
            return l_num < r_num
        if op_used == ">=":
            return l_num >= r_num
        if op_used == "<=":
            return l_num <= r_num
    except (ValueError, TypeError):
        if op_used == ">":
            return lhs > rhs
        if op_used == "<":
            return lhs < rhs
        if op_used == ">=":
            return lhs >= rhs
        if op_used == "<=":
            return lhs <= rhs
    return False


def _evaluate_ifdef_blocks(text: str, meta: dict[str, str] | None) -> str:
    """Resolve block-form ``ifdef::``/``ifndef::``/``ifeval::``/``endif::``
    directives.

    Single-line inline form ``ifdef::attr[content]`` is left for the line
    walker to handle.  This function only consumes the multi-line block form
    where the directive line ends with ``[]``.

    ``ifeval::["{a}" == "b"][]`` blocks balance the push/pop stack alongside
    ``ifdef::``/``ifndef::`` so subsequent guards remain correctly nested.
    """
    if meta is None:
        meta = {}
    out: list[str] = []
    # Stack of booleans: True means "currently emitting"; False means "skip".
    stack: list[bool] = [True]
    for line in text.splitlines():
        m_open = _IFDEF_OPEN_RE.match(line)
        if m_open:
            kind, attr_expr = m_open.group(1), m_open.group(2)
            defined = _attr_defined(attr_expr, meta)
            include = defined if kind == "def" else not defined
            stack.append(stack[-1] and include)
            continue
        m_eval = _IFEVAL_OPEN_RE.match(line)
        if m_eval:
            include = _eval_ifeval(m_eval.group(1), meta)
            stack.append(stack[-1] and include)
            continue
        if _ENDIF_RE.match(line):
            if len(stack) > 1:
                stack.pop()
            continue
        if stack[-1]:
            out.append(line)
    return "\n".join(out)


def _resolve_includes(
    text: str, base_dir: Path, _depth: int = 0, _seen: frozenset[Path] | None = None
) -> str:
    """Recursively expand include:: directives in *text*.

    Includes are resolved relative to *base_dir*.  Sub-includes in the
    included files are also resolved (up to 20 levels deep to prevent
    infinite recursion).  Circular includes are detected via *_seen* and
    skipped with a warning.
    """
    if _seen is None:
        _seen = frozenset()
    if _depth > 20:
        return text

    result_lines: list[str] = []
    for line in text.splitlines():
        m = _INCLUDE_RE.match(line.strip())
        if m:
            rel_path = m.group(1)
            attrs = _parse_include_attrs(m.group(2))
            target = base_dir / rel_path
            if target.exists():
                real_path = target.resolve()
                if real_path in _seen:
                    logging.warning(f"Circular include detected and skipped: {rel_path}")
                    result_lines.append(f"<!-- circular include skipped: {rel_path} -->")
                else:
                    included = target.read_text(encoding="utf-8")
                    # Apply tag/tags filter (if any) before recursing.
                    tag_spec = attrs.get("tags") or attrs.get("tag")
                    if tag_spec:
                        included = _filter_by_tags(included, tag_spec)
                    # Recursively resolve includes in the included file
                    included = _resolve_includes(
                        included, target.parent, _depth + 1, _seen | {real_path}
                    )
                    result_lines.append(included)
            else:
                logging.warning(f"include not found: {target}")
                result_lines.append(f"<!-- include not found: {rel_path} -->")
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Project scaffolding
# ---------------------------------------------------------------------------


def _scaffold_specbuild(out: Path, *, overwrite: bool = False) -> None:
    """Copy the specbuild pipeline into *out* to make a self-contained project.

    Copies (from the specbuild package root):
    - ``compile.py``
    - ``compile_multipage.py``
    - ``specbuild/`` package
    - ``scripts/`` helper scripts
    - ``css/`` stylesheets
    - ``js/`` JavaScript
    - ``config/`` SDL descriptors

    Also writes a minimal ``requirements.txt`` and ``README.md``.
    """
    # Locate the specbuild repo root via the package __file__
    pkg_root = Path(__file__).parent.parent.parent  # specbuild/convert/metanorma.py → repo root

    def _copy_item(src: Path, dst: Path) -> None:
        if not src.exists():
            return
        if dst.exists() and not overwrite:
            return
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        else:
            shutil.copy2(src, dst)

    # Copy pipeline entry points
    for fname in ("compile.py", "compile_multipage.py"):
        _copy_item(pkg_root / fname, out / fname)

    # Copy specbuild package
    _copy_item(pkg_root / "specbuild", out / "specbuild")

    # Copy support directories
    for dirname in ("scripts", "css", "js", "config"):
        _copy_item(pkg_root / dirname, out / dirname)

    # Write requirements.txt
    req_path = out / "requirements.txt"
    if not req_path.exists() or overwrite:
        req_src = pkg_root / "requirements.txt"
        if req_src.exists():
            shutil.copy2(req_src, req_path)
        else:
            req_path.write_text(
                "bikeshed\nbeautifulsoup4\nhtml5lib\nlxml\nPygments\nrequests\n",
                encoding="utf-8",
            )

    # Write pyproject.toml stub (if not present)
    pyproject_path = out / "pyproject.toml"
    if not pyproject_path.exists():
        pyproject_src = pkg_root / "pyproject.toml"
        if pyproject_src.exists():
            shutil.copy2(pyproject_src, pyproject_path)

    # Write README.md
    readme_path = out / "README.md"
    if not readme_path.exists() or overwrite:
        readme_path.write_text(
            "# Bikeshed Specification Project\n\n"
            "This project was generated by `specbuild convert`.\n\n"
            "## Setup\n\n"
            "```bash\n"
            "python -m venv venv && source venv/bin/activate\n"
            "pip install -r requirements.txt\n"
            "```\n\n"
            "## Build\n\n"
            "```bash\n"
            "python compile.py\n"
            "python compile.py --pdf\n"
            "python compile.py --standards-flavor iso\n"
            "```\n\n"
            "## Source files\n\n"
            "Bikeshed source files are in `bikeshed/`. "
            "Edit them, then rebuild with `python compile.py`.\n\n"
            "## Images\n\n"
            "Copy your images into the `images/` directory "
            "(see `IMAGES_NOTE.txt` if present).\n",
            encoding="utf-8",
        )

    logging.info(f"Scaffolded specbuild pipeline into {out}")


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_ATTR_RE = re.compile(r"^:([a-zA-Z0-9_-]+):\s*(.*)")


def _extract_metadata(text: str) -> dict[str, str]:
    """Extract AsciiDoc document attributes from the header."""
    meta: dict[str, str] = {}
    for line in text.splitlines():
        # Document title (first line starting with = not ==)
        if line.startswith("= ") and "title" not in meta:
            meta["title"] = line[2:].strip()
            continue
        m = _ATTR_RE.match(line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
    return meta


def _find_includes(text: str, project_dir: Path) -> list[Path]:
    """Find include:: directives in order and resolve them to Path objects."""
    paths: list[Path] = []
    for line in text.splitlines():
        m = _INCLUDE_RE.match(line.strip())
        if m:
            p = project_dir / m.group(1)
            if p.exists():
                paths.append(p)
            else:
                logging.warning(f"include not found: {p}")
    return paths


# ---------------------------------------------------------------------------
# Metadata → Bikeshed header block + specbuild.toml
# ---------------------------------------------------------------------------


def _build_bs_metadata(meta: dict[str, str]) -> list[str]:
    """Build the Bikeshed ``<pre class="metadata">`` block."""
    doc_num = meta.get("docnumber", "")
    part = meta.get("partnumber", "")
    full_num = f"ISO/IEC {doc_num}-{part}" if part else (f"ISO/IEC {doc_num}" if doc_num else "")

    title_intro = meta.get("title-intro-en", "")
    title_main = meta.get("title-main-en", meta.get("title", ""))
    title_part = meta.get("title-part-en", "")

    if title_intro and title_main and title_part:
        full_title = f"{title_intro} — {title_main} — Part {part}: {title_part}"
    elif title_main and title_part:
        full_title = f"{title_main} — Part {part}: {title_part}"
    elif title_main:
        full_title = title_main
    else:
        full_title = meta.get("title", "Untitled")

    if full_num:
        full_title = f"{full_num} — {full_title}"

    shortname = re.sub(r"[^a-z0-9]+", "-", full_title.lower()).strip("-")
    if len(shortname) > 60:
        shortname = shortname[:60].rstrip("-")

    revdate = meta.get("revdate", "")
    date_str = revdate[:10] if revdate else ""

    sc_num = meta.get("subcommittee-number", "")
    wg_num = meta.get("workgroup-number", "")
    editor_str = f"ISO/IEC JTC 1/SC {sc_num}/WG {wg_num}" if sc_num and wg_num else "ISO"

    return [
        line
        for line in [
            "<pre class='metadata'>",
            f"Title: {full_title}",
            "Status: DREAM",
            f"Shortname: {shortname}",
            "Level: none",
            f"Editor: {editor_str}",
            f"Date: {date_str}" if date_str else "",
            "Markup Shorthands: markdown yes, biblio yes",
            "Abstract: This document specifies the format described herein.",
            "</pre>",
        ]
        if line
    ]


def _build_specbuild_toml(meta: dict[str, str]) -> str:
    """Generate specbuild.toml content from document metadata."""
    doc_num = meta.get("docnumber", "23008")
    part = meta.get("partnumber", "")
    spec_name = f"ISO{doc_num}-{part}" if part else f"ISO{doc_num}"

    title_main = meta.get("title-main-en", meta.get("title", ""))
    title_part = meta.get("title-part-en", "")
    full_name = (
        f"ISO/IEC {doc_num}-{part} — {title_main} — Part {part}: {title_part}"
        if part and title_part
        else f"ISO/IEC {doc_num} — {title_main}"
    )

    revdate = meta.get("revdate", "")
    sc_num = meta.get("subcommittee-number", "29")
    wg_num = meta.get("workgroup-number", "3")
    edition = meta.get("edition", "1")
    stage = meta.get("docstage", "20")
    doc_full = f"{doc_num}-{part}" if part else doc_num

    return f"""# specbuild.toml — generated by specbuild convert
spec_name = "{spec_name}"
spec_full_name = "{full_name}"
bikeshed_dir = "bikeshed"
output_dir_template = "output/{{date}}_{{sha}}_{spec_name}_Spec_Draft"

[standards]
flavor = "iso"
# document_number = "{doc_full}"
edition = "{edition}"
technical_committee = "ISO/IEC JTC 1/SC {sc_num}/WG {wg_num}"
stage = "{stage}"
# date = "{revdate}"
"""


# ---------------------------------------------------------------------------
# Per-section conversion
# ---------------------------------------------------------------------------


def convert_section(
    text: str,
    *,
    annex_counter: list[int] | None = None,
    meta: dict[str, str] | None = None,
    used_slugs: set[str] | None = None,
    doc_attrs: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Convert a single AsciiDoc section to Bikeshed lines.

    Args:
        text: AsciiDoc source text.
        annex_counter: Mutable list with one int element tracking how many
            annexes have been seen (for auto A/B/C lettering).
        meta: Document metadata dict (used for {attr} substitutions).
        used_slugs: Shared set of already-used heading slugs for deduplication
            across multiple ``convert_section`` calls in the same project.
        doc_attrs: Optional Asciidoctor doc-path built-ins
            (``docname``/``docdir``/``docfile``) populated from the source path.

    Returns:
        Tuple of (output_lines, warnings).
    """
    if annex_counter is None:
        annex_counter = [0]
    converter = _SectionConverter(
        annex_counter, meta=meta, used_slugs=used_slugs, doc_attrs=doc_attrs
    )
    return converter.convert(text)


# ---------------------------------------------------------------------------
# State-machine converter
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(={2,6})\s+(.+)")
_ANCHOR_RE = re.compile(r"^\[\[([^\]]+)\]\]\s*$")
# Inline anchor at start of line followed by content: `[[id]] body...`
_ANCHOR_INLINE_RE = re.compile(r"^\[\[([^\]]+)\]\]\s+(.+)$")
_BLOCK_ATTR_RE = re.compile(r"^\[([^\]]*)\]\s*$")
# AsciiDoc table/block caption: a line starting with a single "." followed by text
# (but NOT ".." which is an ordered-list item)
_TABLE_CAPTION_RE = re.compile(r"^\.[^.\s](.*)$")

# ISO unnumbered front-matter sections (Foreword, Introduction, etc.)
_ISO_UNNUMBERED = frozenset(
    {"foreword", "introduction", "abstract", "preface", "acknowledgements", "acknowledgments"}
)

# Inline patterns
_BOLD_RE = re.compile(
    # **two-or-more chars** OR *single-non-space-char* OR *2+ char string with non-space ends*
    r"\*\*(.+?)\*\*|\*([^*\s])\*(?!\w)|\*([^*\s][^*]*[^*\s])\*(?!\w)"
)
_ITALIC_RE = re.compile(r"__(.+?)__|(?<![_\w])_([^_\n]+?)_(?![_\w])")
_MONO_RE = re.compile(r"``(.+?)``|`([^`]+)`")
_XREF_RE = re.compile(r"<<([^,>\s]+)(?:,([^>]+))?>>")
_SUPERSCRIPT_RE = re.compile(r"\^([^^\s]+)\^")
_SUBSCRIPT_RE = re.compile(r"~([^~\s]+)~")
_BIB_REF_RE = re.compile(r"^\[\[\[([^,\]]+)(?:,([^\]]+))?\]\]\]")
# Metanorma collection ref patterns: repo:(...) and path:(...)
_REPO_REF_RE = re.compile(r"(?:repo|path):\(([^)]*)\)")
# Named image attributes: width=, height=, align=, etc.
_IMAGE_NAMED_ATTRS_RE = re.compile(
    r'\b(width|height|align|float|role|link|title)\s*=\s*"?([^",\]]*)"?'
)
# Inline passthrough: `+text+` (prevents substitutions)
_INLINE_PASS_RE = re.compile(r"`\+([^+`]+)\+`")
# Triple-plus passthrough: +++literal HTML+++ — content emitted verbatim.
# Non-greedy so the first +++ closes the span; a single trailing + (e.g. "+++a+b+++")
# is OK because the inner pattern excludes runs of + at the start.
_TRIPLE_PLUS_PASS_RE = re.compile(r"\+\+\+(.+?)\+\+\+", re.DOTALL)
# Constrained inline monospace: +text+ (Asciidoctor alternative to backticks).
# Avoid space-adjacent boundaries (continuation `+` lines, additive operators).
_PLUS_MONO_RE = re.compile(r"(?<![+\w])\+([^+\s][^+\n]*?[^+\s]|[^+\s])\+(?![+\w])")
# HTML tag stripper for alt= attribute plain-text extraction
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Table cell boundary: optional cell prefix (colspan, rowspan, align, type) followed by |
# Prefixes recognised, in order:
#   N+        colspan
#   .M+       rowspan
#   N.M+      combined colspan+rowspan
#   ^<>.hasmel single-char align/type modifiers
_TABLE_CELL_BOUNDARY_RE = re.compile(r"((?:\d+\.\d+\+|\d+\+|\.?\d+\+|[.<>^hasmel])*)\|")

_PIPE_PLACEHOLDER = "\x00PIPE\x00"
# Checklist bullet: `[ ]`, `[x]`, `[X]`, `[*]` at the start of a list item body
_CHECKLIST_ITEM_RE = re.compile(r"^\[([ xX*])\]\s+(.*)$")


def _protect_backtick_pipes(line: str) -> str:
    """Replace ``|`` inside backtick-delimited spans with a placeholder.

    This prevents pipes inside inline code (e.g., ``cmd | grep``) from being
    treated as table cell boundaries by ``_TABLE_CELL_BOUNDARY_RE``.
    """
    result: list[str] = []
    in_backtick = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "`":
            in_backtick = not in_backtick
            result.append(ch)
        elif ch == "|" and in_backtick:
            result.append(_PIPE_PLACEHOLDER)
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _restore_backtick_pipes(text: str) -> str:
    """Reverse the substitution made by :func:`_protect_backtick_pipes`."""
    return text.replace(_PIPE_PLACEHOLDER, "|")


# Literal block delimiter
_LITERAL_DELIM = "...."

# Inline anchor macro: anchor:id[label]
# Negative lookbehind for / and : prevents matching inside URL paths like https://…/anchor:foo[bar]
_ANCHOR_MACRO_RE = re.compile(r"(?<![/:])anchor:([^\[\s]+)\[([^\]]*)\]")

# Highlight/mark syntax: #text#
# Negative lookbehind for {, :, \w avoids CSS hex colors (#fff, #3a3a3a) and
# Bikeshed anchor fragments ({#some-id}).  Requires at least 2 chars of content.
# Negative lookahead for } avoids matching the closing } of {#id} fragments.
_MARK_RE = re.compile(r"(?<![{:\w])#([^#\n]{2,})#(?![}\w])")


def _extract_bib_display_name(ref_name: str) -> str:
    """Extract human-readable name from repo:(...) or path:(...) ref strings."""
    m = _REPO_REF_RE.search(ref_name)
    if m:
        inner = m.group(1)
        # Format: "collection/doc,Display Name" or just "DocName"
        parts = inner.split(",", 1)
        return parts[-1].strip() if len(parts) > 1 else parts[0].strip()
    return ref_name.strip()


_STEM_RE = re.compile(r"(stem|latexmath|asciimath):\[([^\]]+)\]")
_IMAGE_RE = re.compile(r"^image::([^\[]+)\[([^\]]*)\]")
_INLINE_IMAGE_RE = re.compile(r"image:([^\[]+)\[([^\]]*)\]")
_VIDEO_RE = re.compile(r"^video::([^\[]+)\[([^\]]*)\]")
_AUDIO_RE = re.compile(r"^audio::([^\[]+)\[([^\]]*)\]")
_ICON_RE = re.compile(r"icon:(\w[\w-]*)(?:\[([^\]]*)\])?")
# Term reference: {{term}} or {{term,display}}
_TERM_REF_RE = re.compile(r"\{\{([^},]+)(?:,([^}]+))?\}\}")
# Definition list: "term:: definition" (term followed by exactly "::" then text)
_DEFLIST_RE = re.compile(r"^(.+?)::\s+(.+)$")
# Definition list: "term::" with no text (term on its own line, definition on next)
_DEFLIST_TERM_ONLY_RE = re.compile(r"^(.+?)::\s*$")
# Footnote: footnote:[text] or footnote:id[text]
_FOOTNOTE_RE = re.compile(r"footnote:([^[\s]*)\[([^\]]*)\]")
# Link macro: link:url[text]
_LINK_RE = re.compile(r"link:([^\[]+)\[([^\]]*)\]")
# URL with bracket text: https://...[] or https://...[text]
_URL_BRACKET_RE = re.compile(r"(https?://[^\s\[]+)\[([^\]]*)\]")
# Bare URL (not already in href=): https://... or http://... followed by space/end
_BARE_URL_RE = re.compile(r'(?<!=")(?<!\[)(?<!>)(https?://[^\s<>"]+)')
# Attribute reference: {attr-name}
_ATTR_REF_RE = re.compile(r"\{([a-zA-Z0-9_-]+)\}")
# Code callout reference in running text: <N>
_CALLOUT_TEXT_RE = re.compile(r"<(\d+)>")
# Inline passthrough: pass:[content]
_PASS_RE = re.compile(r"pass:(?:[a-z,]*)\[([^\]]*)\]")
# Inline role span: [.role]#text# → <span class="role">text</span>
_ROLE_SPAN_RE = re.compile(r"\[\.([\w-]+)\]#([^#\n]+?)#")
# Footnote reuse: footnoteref:[id] → reference to existing footnote
_FOOTNOTEREF_RE = re.compile(r"footnoteref:\[([^\]]+)\]")
# Citation macro: cite:[ref]
_CITE_RE = re.compile(r"cite:\[([^\]]*)\]")
# Index term macros: (((primary,secondary))) invisible; ((term)) visible
_INDEX_TERM3_RE = re.compile(r"\(\(\(([^)]+)\)\)\)")
_INDEX_TERM2_RE = re.compile(r"\(\(([^)]+)\)\)")
# Character substitution patterns (compiled for performance)
_CHAR_SUB_COPY_RE = re.compile(r"\(C\)")
_CHAR_SUB_TM_RE = re.compile(r"\(TM\)")
_CHAR_SUB_REG_RE = re.compile(r"\(R\)")
_CHAR_SUB_RARROW_RE = re.compile(r"->")
_CHAR_SUB_DRRARROW_RE = re.compile(r"=>")
_CHAR_SUB_LARROW_RE = re.compile(r"<-")
_CHAR_SUB_DLLARROW_RE = re.compile(r"<=")
_CHAR_SUB_EMDASH_SPACED_RE = re.compile(r" -- ")
_CHAR_SUB_EMDASH_RE = re.compile(r"(?<!-)---(?!-)")
# UI macros: kbd, btn, menu
_KBD_RE = re.compile(r"kbd:\[([^\]]+)\]")
_BTN_RE = re.compile(r"btn:\[([^\]]+)\]")
_MENU_RE = re.compile(r"menu:(\w+)\[([^\]]*)\]")
# Triple-colon definition list: "term::: definition" (nested / ::: deeper than ::)
_DEFLIST3_RE = re.compile(r"^(.+?):::\s+(.+)$")
_DEFLIST3_TERM_ONLY_RE = re.compile(r"^(.+?):::\s*$")
# Mid-document attribute definition: :attr-name: value  (or bare :attr-name:)
_MID_DOC_ATTR_RE = re.compile(r"^:([a-zA-Z0-9_-]+):(\s+(.+))?$")
# Metanorma term status macros: preferred:[text], admitted:[text], deprecated:[text]
_TERM_STATUS_RE = re.compile(r"^(preferred|admitted|deprecated):\[(.+)\]$")


def _apply_outside_code_spans(
    text: str,
    patterns: list[tuple[re.Pattern[str], str]],
) -> str:
    """Apply regex substitutions only to text outside ``<code>...</code>`` spans.

    *patterns* is a list of ``(compiled_re, replacement_string)`` pairs.
    Each pattern is applied independently to every non-code segment.
    """
    # Split into alternating non-code / code segments.
    # We keep the delimiters so we can reconstruct the string exactly.
    code_re = re.compile(r"(<code>.*?</code>)", re.DOTALL)
    segments = code_re.split(text)
    result: list[str] = []
    for idx, seg in enumerate(segments):
        if idx % 2 == 0:
            # Non-code segment — apply all substitutions
            for pat, repl in patterns:
                seg = pat.sub(repl, seg)
            result.append(seg)
        else:
            # Code segment — pass through unchanged
            result.append(seg)
    return "".join(result)


def _parse_image_attrs(attrs_str: str) -> dict[str, str]:
    """Parse image macro attribute string into a dict.

    Returns keys: alt, width, height, align, link.
    Handles positional args: [alt, width, height] and named key=value pairs.
    AsciiDoc positional form: image::path["alt text", 300, 200] or image::path["",145,172].
    """
    result: dict[str, str] = {}
    if not attrs_str.strip():
        return result
    # Extract named attributes first (key=value or key="value")
    for km in _IMAGE_NAMED_ATTRS_RE.finditer(attrs_str):
        result[km.group(1)] = km.group(2).strip()
    # Remove named attrs from string to find positional args
    remainder = _IMAGE_NAMED_ATTRS_RE.sub("", attrs_str).strip().strip(",").strip()
    if remainder and "=" not in remainder:
        # Split into positional slots: [0]=alt, [1]=width, [2]=height
        pos_parts = [p.strip() for p in remainder.split(",")]
        for idx, part in enumerate(pos_parts):
            clean = part.strip("\"' ")
            if idx == 0:
                if clean and "alt" not in result:
                    result["alt"] = clean
            elif clean.isdigit():
                if "width" not in result:
                    result["width"] = clean
                elif "height" not in result:
                    result["height"] = clean
    return result


def _parse_image_alt(attrs_str: str) -> str:
    """Extract alt text from image macro attrs; ignore width/height/named attrs."""
    return _parse_image_attrs(attrs_str).get("alt", "")


def _top_level_split(s: str, sep: str = ",") -> list[str]:
    """Split s at top-level sep (not inside any brackets)."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in s:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth -= 1
            buf.append(ch)
        elif ch == sep and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


def _slugify(text: str) -> str:
    """Convert heading text to a slug for ``{#slug}``."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    text = re.sub(r"-+", "-", text)
    return text


def _to_plain_text(html: str) -> str:
    """Strip HTML tags from *html* to produce plain text for alt attributes."""
    return _HTML_TAG_RE.sub("", html).strip()


def _expand_frac(s: str) -> str:
    """Expand AsciiMath ``frac(num)(den)`` to ``(num)/(den)`` with balanced-paren
    matching so nested forms collapse fully.

    Repeatedly finds the leftmost ``frac(`` whose two argument groups contain no
    further ``frac(`` (innermost first), substitutes, and repeats until stable.
    """

    def _scan_balanced(text: str, start: int) -> int | None:
        """Return the index of the closing ``)`` matching the ``(`` at *start*, or None."""
        if start >= len(text) or text[start] != "(":
            return None
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        return None

    iterations = 0
    while iterations < 32:
        iterations += 1
        # Find rightmost `frac(` (most-deeply-nested when scanning left-to-right
        # this lands on innermost since outer frac contains inner)
        i = s.rfind("frac(")
        if i < 0:
            break
        # Word-boundary check on the left
        if i > 0 and (s[i - 1].isalnum() or s[i - 1] == "_"):
            # not a real frac — bail
            break
        open_a = i + 4  # position of first '('
        close_a = _scan_balanced(s, open_a)
        if close_a is None or close_a + 1 >= len(s) or s[close_a + 1] != "(":
            break
        open_b = close_a + 1
        close_b = _scan_balanced(s, open_b)
        if close_b is None:
            break
        num = s[open_a + 1 : close_a]
        den = s[open_b + 1 : close_b]
        s = s[:i] + f"({num})/({den})" + s[close_b + 1 :]
    return s


def _asciimathml_operators(s: str) -> str:
    """Apply AsciiMath operator/symbol substitutions to a string fragment."""
    s = re.sub(r"\btext\(([^)]+)\)", r"\1", s)
    s = re.sub(r"\bsqrt\(([^)]+)\)", r"√(\1)", s)
    s = re.sub(r"\bsqrt\b", "√", s)
    # Fraction: frac(num)(den) → (num)/(den).  Use balanced-paren matching so
    # nested fractions like frac(frac(1)(2))(3) collapse fully.  Iterate from
    # innermost outward by repeatedly resolving the leftmost frac whose
    # arguments contain no further `frac(`.
    s = _expand_frac(s)
    # Integer/floor division: a // b → a ÷ b
    s = re.sub(r"\s//\s", " ÷ ", s)
    s = s.replace(" ge ", " ≥ ").replace(" le ", " ≤ ").replace(" ne ", " ≠ ")
    s = s.replace(" xx ", " × ").replace(" -: ", " ÷ ")
    s = s.replace("<=", " ≤ ").replace(">=", " ≥ ")
    # Sum / product / integral with subscript/superscript
    # Parenthesized limits: sum_(i=0)^n → Σ<sub>i=0</sub><sup>n</sup>
    s = re.sub(
        r"\bsum_\(([^)]+)\)\^([^\s<]+)",
        lambda m: f"Σ<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bsum_\(([^)]+)\)", lambda m: f"Σ<sub>{m.group(1)}</sub>", s)
    # Bare numeric limits: sum_0^n → Σ<sub>0</sub><sup>n</sup>
    s = re.sub(
        r"\bsum_(-?\w+)\^([^\s<]+)",
        lambda m: f"Σ<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bsum_(-?\w+)", lambda m: f"Σ<sub>{m.group(1)}</sub>", s)
    s = re.sub(r"\bsum\^([^\s<]+)", lambda m: f"Σ<sup>{m.group(1)}</sup>", s)
    s = re.sub(r"\bsum\b", "Σ", s)
    s = re.sub(
        r"\bprod_\(([^)]+)\)\^([^\s<]+)",
        lambda m: f"Π<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bprod_\(([^)]+)\)", lambda m: f"Π<sub>{m.group(1)}</sub>", s)
    s = re.sub(
        r"\bprod_(-?\w+)\^([^\s<]+)",
        lambda m: f"Π<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bprod_(-?\w+)", lambda m: f"Π<sub>{m.group(1)}</sub>", s)
    s = re.sub(r"\bprod\b", "Π", s)
    s = re.sub(
        r"\bint_\(([^)]+)\)\^([^\s<]+)",
        lambda m: f"∫<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bint_\(([^)]+)\)", lambda m: f"∫<sub>{m.group(1)}</sub>", s)
    s = re.sub(
        r"\bint_(-?\w+)\^([^\s<]+)",
        lambda m: f"∫<sub>{m.group(1)}</sub><sup>{m.group(2)}</sup>",
        s,
    )
    s = re.sub(r"\bint_(-?\w+)", lambda m: f"∫<sub>{m.group(1)}</sub>", s)
    s = re.sub(r"\bint\b", "∫", s)
    # lim/max/min with subscript
    s = re.sub(
        r"\b(lim|max|min)_\(([^)]+)\)",
        lambda m: f"{m.group(1)}<sub>{m.group(2)}</sub>",
        s,
    )
    s = re.sub(
        r"\b(lim|max|min)_(-?\w+)",
        lambda m: f"{m.group(1)}<sub>{m.group(2)}</sub>",
        s,
    )
    # Ceiling and floor: ceil(x) → ⌈x⌉, floor(x) → ⌊x⌋
    s = re.sub(r"\bceil\(([^)]+)\)", r"⌈\1⌉", s)
    s = re.sub(r"\bfloor\(([^)]+)\)", r"⌊\1⌋", s)
    # Absolute value: abs(x) → |x|
    s = re.sub(r"\babs\(([^)]+)\)", r"|\1|", s)
    # Norm: norm(x) → ‖x‖
    s = re.sub(r"\bnorm\(([^)]+)\)", r"‖\1‖", s)
    # Accent operators run BEFORE sub/superscript to avoid combining char landing on HTML tags.
    # hat(x) → x̂, tilde(x) → x̃, bar(x) → x̄, dot(x) → ẋ
    # For single-digit subscripts we first convert x_0 → x₀ (Unicode subscript digit) so that
    # hat(x₀) → x₀̂ — the hat applies correctly to x and the subscript digit is preserved.
    # Multi-character or letter subscripts (x_i, x_ij) are still handled by the <sub> pattern.
    #
    # Accents on subscripted expressions: hat(x_i) → x̂<sub>i</sub>
    # Must precede the general hat(x) pattern to match subscripted forms first.
    # Only matches non-digit subscripts (letter subscripts like x_i, x_ij); digit
    # subscripts (x_0) are handled by the Unicode subscript conversion below.
    for _aname, _achar in [("hat", "̂"), ("bar", "̄"), ("tilde", "̃"), ("dot", "̇")]:
        s = re.sub(
            rf"\b{_aname}\((\w+)_([a-zA-Z_]\w*)\)",
            lambda m, c=_achar: m.group(1) + c + f"<sub>{m.group(2)}</sub>",
            s,
        )
        # Also handle parenthesized subscripts: hat(x_(ij))
        s = re.sub(
            rf"\b{_aname}\((\w+)_\(([^)]+)\)\)",
            lambda m, c=_achar: m.group(1) + c + f"<sub>{m.group(2)}</sub>",
            s,
        )
    s = re.sub(
        r"(\w)_([0-9])\b",
        lambda m: m.group(1) + m.group(2).translate(_UNICODE_SUBSCRIPTS),
        s,
    )
    s = re.sub(r"\bhat\(([^)]+)\)", r"\1̂", s)
    s = re.sub(r"\btilde\(([^)]+)\)", r"\1̃", s)
    s = re.sub(r"\bbar\(([^)]+)\)", r"\1̄", s)
    s = re.sub(r"\bdot\(([^)]+)\)", r"\1̇", s)
    # Vector arrow accent: vec(x) → x⃗
    s = re.sub(r"\bvec\(([^)]+)\)", r"\1⃗", s)
    # Calculus operators: nabla, partial, del, mod
    s = re.sub(r"\bnabla\b", "∇", s)
    s = re.sub(r"\bpartial\b", "∂", s)
    # "del" as differential operator (same glyph as partial in plain math)
    s = re.sub(r"\bdel\b", "∂", s)
    # Modulo (binary): "a mod b" → "a mod b" with spacing preserved; rendered
    # as a thin-spaced operator. Keep word "mod" but with surrounding nbsp so
    # it visually groups.
    s = re.sub(r"\s+mod\s+", " mod ", s)
    # Infinity
    s = re.sub(r"\b(?:infty|oo)\b", "∞", s)
    # Set operators (notin before in to avoid partial match)
    s = re.sub(r"\bnotin\b", "∉", s)
    # Restrict "in" → ∈ to operator context (preceded by non-word char,
    # not followed by a letter).  Avoids rewriting the English word "in"
    # at the start of math fragments containing prose, and prevents the
    # substitution from firing when "in" is followed by additional letters
    # that happen to look like a word boundary on the regex engine's side.
    s = re.sub(r"(\W)in(?![a-zA-Z])", r"\1∈", s)
    s = re.sub(r"\bsubset\b", "⊂", s)
    s = re.sub(r"\bcup\b", "∪", s)
    s = re.sub(r"\bcap\b", "∩", s)
    # Greek letters — must come before superscript/subscript rules to avoid
    # matching letter-fragments inside already-emitted HTML tags
    _GREEK_SUBS = (
        ("alpha", "α"),
        ("beta", "β"),
        ("gamma", "γ"),
        ("Gamma", "Γ"),
        ("delta", "δ"),
        ("Delta", "Δ"),
        ("epsilon", "ε"),
        ("zeta", "ζ"),
        ("eta", "η"),
        ("theta", "θ"),
        ("Theta", "Θ"),
        ("iota", "ι"),
        ("kappa", "κ"),
        ("lambda", "λ"),
        ("Lambda", "Λ"),
        ("mu", "μ"),
        ("nu", "ν"),
        ("xi", "ξ"),
        ("Xi", "Ξ"),
        ("omicron", "ο"),
        ("pi", "π"),
        ("Pi", "Π"),
        ("rho", "ρ"),
        ("sigma", "σ"),
        ("Sigma", "Σ"),
        ("tau", "τ"),
        ("upsilon", "υ"),
        ("phi", "φ"),
        ("Phi", "Φ"),
        ("chi", "χ"),
        ("psi", "ψ"),
        ("Psi", "Ψ"),
        ("omega", "ω"),
        ("Omega", "Ω"),
    )
    for name, char in _GREEK_SUBS:
        # Use a letter-only negative lookahead instead of \b — \b doesn't fire
        # before `_` since underscore is a word char in Python regex.  This lets
        # `sigma_x` correctly substitute (followed by `_`, which is not a letter)
        # while still rejecting `sigmoid`, `sigmas`, etc.
        s = re.sub(rf"\b{name}(?![a-zA-Z])", char, s)
    # Common math functions (sin, cos, tan, log, ln, exp, lim) left as plain text
    # Superscripts: word^(expr) or word^token → word<sup>…</sup>
    s = re.sub(r"(\w)\^\(([^)]+)\)", lambda m: f"{m.group(1)}<sup>{m.group(2)}</sup>", s)
    s = re.sub(r"(\w)\^(-?\w+)", lambda m: f"{m.group(1)}<sup>{m.group(2)}</sup>", s)
    # Subscripts: word_token or word_(expr)
    s = re.sub(r"(\w)_\(([^)]+)\)", lambda m: f"{m.group(1)}<sub>{m.group(2)}</sub>", s)
    s = re.sub(r"(\w)_(\w+)", lambda m: f"{m.group(1)}<sub>{m.group(2)}</sub>", s)
    # Bare ^expr after ] (matrix superscript handled elsewhere)
    s = re.sub(r"\^\(([^)]+)\)", lambda m: f"<sup>{m.group(1)}</sup>", s)
    s = re.sub(r"\^(-?\w+)", lambda m: f"<sup>{m.group(1)}</sup>", s)
    # {: :} are invisible AsciiMath grouping brackets — strip them only
    s = s.replace("{:", "").replace(":}", "")
    # Do NOT strip bare { } — they appear in set notation: x ∈ {0, 1, 2}
    return s


def _render_asciimathml_matrix(s: str) -> str | None:
    """Render [ [r1c1,r1c2,...], [r2c1,...], ... ] as an HTML table.

    Returns HTML string, or None if s is not a well-formed matrix.
    """
    s = re.sub(r"\s+", " ", s).strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    parts = _top_level_split(s[1:-1])
    if not parts:
        return None
    rows: list[list[str]] = []
    for part in parts:
        part = part.strip()
        if part.startswith("[") and part.endswith("]"):
            rows.append(_top_level_split(part[1:-1]))
        else:
            return None  # not all row-vectors
    td = 'style="padding:0.1em 0.4em;text-align:center;white-space:nowrap"'
    html = (
        '<table style="display:inline-table;vertical-align:middle;'
        "border-left:2px solid currentColor;border-right:2px solid currentColor;"
        'padding:0.1em 0.3em;border-spacing:0;margin:0 0.15em">'
    )
    for row in rows:
        html += "<tr>"
        for cell in row:
            cell_html = _asciimathml_to_text(cell.strip())
            # Unwrap outer span if present so cells don't double-italicise
            cell_html = re.sub(r'^<span class="math-expr">(.*)</span>$', r"\1", cell_html)
            html += f"<td {td}>{cell_html}</td>"
        html += "</tr>"
    html += "</table>"
    return html


def _asciimathml_to_text(expr: str) -> str:
    """Convert AsciiMath notation to readable HTML."""
    s = re.sub(r"\s+", " ", expr).strip()

    # AsciiMath italic text: ii"..." → <em>…</em>
    s = re.sub(r'\bii"([^"]*)"', r"<em>\1</em>", s)
    # String literals: "text" → text
    s = re.sub(r'"([^"]*)"', r"\1", s)

    # Piecewise {(val;cond),(val;cond):} or {[eq],[eq]:}
    pw_m = re.match(r"^\{(.+?)(?::)?\}$", s, re.DOTALL)
    if pw_m:
        inner = pw_m.group(1).strip().lstrip(":")  # strip leading : from {: ... :} notation
        cases_raw = _top_level_split(inner)
        rows: list[str] = []
        for case in cases_raw:
            case = case.strip().rstrip(" :")  # strip trailing AsciiMath {: :} marker
            # Strip exactly ONE outer paren/bracket pair — not all of them, since the
            # expression body may itself end with ) (e.g. 2^(14+text(P))).
            if len(case) >= 2 and case[0] in "([" and case[-1] in ")]":
                case = case[1:-1].strip()
            halves = [h.strip() for h in case.split(";", 1)]
            val = _asciimathml_operators(halves[0])
            if len(halves) == 2:
                cond = halves[1]
                if not cond.lower().startswith("if "):
                    cond = "if " + cond
                rows.append(f"{val} &nbsp;&nbsp; {_asciimathml_operators(cond)}")
            else:
                rows.append(val)
        return f'<span class="math-expr">{"<br>".join(rows)}</span>'

    # Equation(s) with possible matrices: split on " = " at top level
    eq_parts = _top_level_split(s, "=")
    if len(eq_parts) > 1:
        rendered: list[str] = []
        has_matrix = False
        for part in eq_parts:
            part = part.strip()
            # Matrix with optional trailing ^superscript
            mat_m = re.match(r"^(\[.+\])(\^.+)?$", part, re.DOTALL)
            if mat_m:
                mat_html = _render_asciimathml_matrix(mat_m.group(1))
                if mat_html:
                    has_matrix = True
                    suffix = (mat_m.group(2) or "").strip()
                    if suffix:
                        suffix = re.sub(
                            r"^\^(-?\w+|\([^)]+\))",
                            lambda m: f"<sup>{m.group(1).strip('()')}</sup>",
                            suffix,
                        )
                    rendered.append(mat_html + suffix)
                    continue
            # Piecewise or nested expression: recurse through _asciimathml_to_text
            if part.startswith("{"):
                inner = _asciimathml_to_text(part)
                inner = re.sub(
                    r'^<span class="math-expr">(.*)</span>$', r"\1", inner, flags=re.DOTALL
                )
                has_matrix = True  # force multiline-aware return path
                rendered.append(inner)
                continue
            rendered.append(_asciimathml_operators(part))
        if has_matrix:
            return f'<span class="math-expr">{" = ".join(rendered)}</span>'

    # Direct matrix (no = sign)
    mat_html = _render_asciimathml_matrix(s)
    if mat_html:
        return f'<span class="math-expr">{mat_html}</span>'

    # Plain expression
    return f'<span class="math-expr">{_asciimathml_operators(s)}</span>'


def _convert_inline(text: str, _ctx: _SectionConverter | None = None) -> str:  # noqa: UP037
    """Apply inline AsciiDoc → HTML/Bikeshed transformations."""

    # Triple-plus passthrough: +++literal+++ → content emitted verbatim.
    # Stash matches BEFORE any other substitution (including attribute refs)
    # so the literal is preserved exactly.  Restore at the end.  Run before
    # +monospace+ so triple-plus wins on overlapping input like "+++a+b+++".
    _triple_pass_stash: list[str] = []

    def _stash_triple(m: re.Match) -> str:
        _triple_pass_stash.append(m.group(1))
        return f"\x00TPASS{len(_triple_pass_stash) - 1}\x00"

    text = _TRIPLE_PLUS_PASS_RE.sub(_stash_triple, text)

    # Attribute references: {attr-name} → value from ctx metadata
    # Built-in AsciiDoc attributes are resolved first regardless of ctx.
    def _attr_ref(m: re.Match) -> str:
        name = m.group(1)
        # Standard AsciiDoc built-in character entities
        if name == "nbsp":
            return "&nbsp;"
        if name == "zwsp":
            return "&#8203;"
        if name == "wj":
            return "&#8288;"
        # Asciidoctor doc-path built-ins, populated from ctx if available
        if _ctx is not None:
            doc_attrs = getattr(_ctx, "_doc_attrs", None) or {}
            if name in ("docname", "docdir", "docfile") and name in doc_attrs:
                return doc_attrs[name]
            if _ctx._meta:
                return _ctx._meta.get(name, m.group(0))
        return m.group(0)

    text = _ATTR_REF_RE.sub(_attr_ref, text)

    # Inline passthrough: pass:[content] → raw content
    text = _PASS_RE.sub(lambda m: m.group(1), text)

    # Citation macro: cite:[ref] → same as <<ref>>
    def _cite(m: re.Match) -> str:
        ref = m.group(1).strip()
        anchor = f"biblio-{_slugify(ref)}"
        return f'<a href="#{anchor}">[{ref}]</a>'

    text = _CITE_RE.sub(_cite, text)

    # Footnotes: footnote:[text] or footnote:id[text]
    def _footnote(m: re.Match) -> str:
        fn_id_hint = m.group(1)  # optional id, may be empty
        fn_text = m.group(2)
        if _ctx is not None:
            _ctx._footnote_num += 1
            n = _ctx._footnote_num
            fn_id = fn_id_hint or f"fn-{n}"
            ref_id = f"fnref-{n}"
            _ctx._footnotes.append((fn_id, ref_id, _convert_inline(fn_text, _ctx=_ctx)))
            return f'<a href="#{fn_id}" id="{ref_id}" class="footnote-ref"><sup>[{n}]</sup></a>'
        # No context — render inline
        return f"<sup>[{fn_text}]</sup>"

    text = _FOOTNOTE_RE.sub(_footnote, text)

    # Stem/math: stem:[expr] / asciimath:[expr] → readable Unicode/HTML span.
    # latexmath:[expr] is preserved as a TeX block wrapped in \(...\) so a
    # downstream renderer (MathJax/KaTeX) can typeset it.
    def _stem_repl(m: re.Match) -> str:
        kind, body = m.group(1), m.group(2)
        if kind == "latexmath":
            return f'<span class="math inline">\\({body}\\)</span>'
        return _asciimathml_to_text(body)

    text = _STEM_RE.sub(_stem_repl, text)

    # Keyboard/button/menu UI macros
    text = _KBD_RE.sub(lambda m: f"<kbd>{m.group(1)}</kbd>", text)
    text = _BTN_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)

    def _menu_repl(m: re.Match) -> str:
        name = m.group(1)
        content = m.group(2).strip() if m.group(2) else ""
        if not content:
            return name
        # Expand `>` separators inside the bracket so that
        # menu:File[New > Project > Other] → File › New › Project › Other
        chain = [part.strip() for part in re.split(r"\s*>\s*", content)]
        return " &rsaquo; ".join([name] + chain)

    text = _MENU_RE.sub(_menu_repl, text)

    # Superscript / subscript
    text = _SUPERSCRIPT_RE.sub(lambda m: f"<sup>{m.group(1)}</sup>", text)
    text = _SUBSCRIPT_RE.sub(lambda m: f"<sub>{m.group(1)}</sub>", text)

    # Inline image
    def _inline_image(m: re.Match) -> str:
        src = m.group(1)
        attrs = _parse_image_attrs(m.group(2))
        alt = attrs.get("alt", "")
        tag = f'<img src="{src}" alt="{alt}"'
        if "width" in attrs:
            tag += f' width="{attrs["width"]}"'
        if "height" in attrs:
            tag += f' height="{attrs["height"]}"'
        tag += ">"
        return tag

    text = _INLINE_IMAGE_RE.sub(_inline_image, text)

    # Inline anchor macro: anchor:id[label]
    text = _ANCHOR_MACRO_RE.sub(
        lambda m: (
            f'<span id="{m.group(1)}">{m.group(2)}</span>'
            if m.group(2)
            else f'<span id="{m.group(1)}"></span>'
        ),
        text,
    )

    # Link macro: link:url[text] (before URL bracket to avoid double-match)
    text = _LINK_RE.sub(lambda m: f'<a href="{m.group(1)}">{m.group(2) or m.group(1)}</a>', text)

    # URL with bracket: https://url[text] or https://url[]
    text = _URL_BRACKET_RE.sub(
        lambda m: f'<a href="{m.group(1)}">{m.group(2) or m.group(1)}</a>', text
    )

    # Cross-references: <<ref>> or <<ref,text/named-params>>
    def _xref(m: re.Match) -> str:
        ref = m.group(1).strip()
        # Inter-doc form: foo.adoc#anchor → anchor (mirror xref: macro behaviour)
        if ".adoc#" in ref:
            ref = ref.split(".adoc#", 1)[1]
        elif ref.endswith(".adoc"):
            ref = ref[:-5]
        raw_label = (m.group(2) or "").strip()
        # Parse named parameters: clause=N, section=N, anchor="val", xrefstyle=...
        # If label contains =, it's a named-param list; extract display from it
        display = raw_label
        if "=" in raw_label:
            # Extract clause= or section= for human-readable display
            cm = re.search(r"\bclause=(\S+)", raw_label)
            sm = re.search(r"\bsection=(\S+)", raw_label)
            am = re.search(r'\banchor=["\']?([^"\'>,]+)["\']?', raw_label)
            if cm:
                display = f"Clause {cm.group(1).rstrip(',')}"
            elif sm:
                display = f"Section {sm.group(1).rstrip(',')}"
            elif am:
                display = am.group(1)
            else:
                display = ""  # will fall back to ref-based display below
        # Run the display label through inline conversion so **bold**, _italic_,
        # `mono`, etc. inside xref labels render as expected.
        if display:
            display = _convert_inline(display, _ctx=_ctx)
        is_section = ref and ref[0].islower()
        if is_section:
            return f'<a href="#{ref}">{display or ref}</a>'
        # Bibliography ref
        anchor = f"biblio-{_slugify(ref)}"
        return f'<a href="#{anchor}">{display or f"[{ref}]"}</a>'

    text = _XREF_RE.sub(_xref, text)

    # xref:anchor[text] explicit cross-reference macro (Metanorma variant of <<anchor,text>>).
    # Inter-document form `xref:other.adoc#anchor[text]` is normalized by stripping the
    # `<doc>.adoc#` prefix so the link targets the in-document anchor.
    def _xref_macro(m: re.Match) -> str:
        target = m.group(1).strip()
        label = m.group(2).strip()
        # Inter-doc form: foo.adoc#anchor → anchor
        if ".adoc#" in target:
            target = target.split(".adoc#", 1)[1]
        elif target.endswith(".adoc"):
            # Whole-document link, no anchor
            target = target[:-5]
        return f'<a href="#{target}">{label or target}</a>'

    text = re.sub(r"(?<![/:])xref:([^\[]+)\[([^\]]*)\]", _xref_macro, text)

    # Bare URLs not already wrapped in <a href=...>
    text = _BARE_URL_RE.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', text)

    # Term references: {{term}} or {{term,display}}
    # Terms are defined as ==== headings in Clause 3, so their anchor is their slug.
    # Rendered as italic linked text per ISO convention.
    def _term_ref(m: re.Match) -> str:
        term = m.group(1).strip()
        display = (m.group(2) or term).strip()
        anchor = _slugify(term)
        return f'<em><a href="#{anchor}">{display}</a></em>'

    text = _TERM_REF_RE.sub(_term_ref, text)

    # Monospace (before bold/italic to avoid conflicts)
    # Handle `+text+` passthrough (AsciiDoc inline passthrough prevents substitutions)
    text = _INLINE_PASS_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    text = _MONO_RE.sub(lambda m: f"<code>{m.group(1) or m.group(2)}</code>", text)
    # Constrained inline monospace: +text+ (Asciidoctor alternative to backticks).
    # Triple-plus passthrough has already been stashed, so any remaining `+...+`
    # is genuine constrained monospace.  The regex avoids word-adjacent and
    # space-adjacent boundaries so list-continuation `+` lines and additive
    # operators (`a + b`) don't match.
    text = _PLUS_MONO_RE.sub(lambda m: f"<code>{m.group(1)}</code>", text)

    # Index terms: (((primary,secondary))) → stripped (invisible); ((term)) → term (visible)
    # Apply outside code spans to avoid corrupting code content.
    text = _apply_outside_code_spans(
        text,
        [
            (_INDEX_TERM3_RE, ""),
            (_INDEX_TERM2_RE, r"\1"),
        ],
    )

    # Character substitutions: applied to text spans only (outside <code> spans)
    _CHAR_SUBS: list[tuple[re.Pattern[str], str]] = [
        (_CHAR_SUB_EMDASH_RE, "\u2014"),  # --- → em-dash (no spaces); before spaced variant
        (_CHAR_SUB_EMDASH_SPACED_RE, " \u2014 "),  # " -- " → " — "
        (_CHAR_SUB_COPY_RE, "\u00a9"),  # (C) → ©
        (_CHAR_SUB_TM_RE, "\u2122"),  # (TM) → ™
        (_CHAR_SUB_REG_RE, "\u00ae"),  # (R) → ®
        (_CHAR_SUB_RARROW_RE, "\u2192"),  # -> → →
        (_CHAR_SUB_DRRARROW_RE, "\u21d2"),  # => → ⇒
        (_CHAR_SUB_LARROW_RE, "\u2190"),  # <- → ←
        (_CHAR_SUB_DLLARROW_RE, "\u21d0"),  # <= → ⇐
    ]
    text = _apply_outside_code_spans(text, _CHAR_SUBS)

    text = _BOLD_RE.sub(
        lambda m: f"<strong>{m.group(1) or m.group(2) or m.group(3)}</strong>", text
    )

    # Italic — emit <em> directly so Bikeshed doesn't re-process spacing edge cases
    text = _ITALIC_RE.sub(lambda m: f"<em>{(m.group(1) or m.group(2)).strip()}</em>", text)

    # Highlighted/marked text: #text# → <mark>text</mark>
    # Skip CSS hex color values (3 or 6 hex digits) that slipped past the regex.
    def _mark_sub(mm: re.Match) -> str:
        content = mm.group(1)
        if re.fullmatch(r"[0-9a-fA-F]{3,6}", content):
            return mm.group(0)  # leave it unchanged
        return f"<mark>{content}</mark>"

    # Inline role spans must run BEFORE _MARK_RE so [.role]#text# isn't matched as #text# alone
    text = _ROLE_SPAN_RE.sub(lambda m: f'<span class="{m.group(1)}">{m.group(2)}</span>', text)
    text = _MARK_RE.sub(_mark_sub, text)
    # footnoteref:[id] reuses an earlier footnote
    text = _FOOTNOTEREF_RE.sub(
        lambda m: f'<sup><a href="#fn-{m.group(1)}" class="footnote-ref">[ref]</a></sup>',
        text,
    )

    # Icon macros: icon:name[attrs] → <span class="icon icon-name">
    text = _ICON_RE.sub(
        lambda m: f'<span class="icon icon-{m.group(1)}" aria-label="{m.group(1)}"></span>',
        text,
    )

    # Hard line break: AsciiDoc trailing " +" → <br>
    if text.rstrip().endswith(" +"):
        text = text.rstrip()[:-2] + "<br>"

    # Restore +++literal+++ passthrough content verbatim
    if _triple_pass_stash:

        def _unstash(m: re.Match) -> str:
            return _triple_pass_stash[int(m.group(1))]

        text = re.sub(r"\x00TPASS(\d+)\x00", _unstash, text)

    return text


# ---------------------------------------------------------------------------
# Table parser
# ---------------------------------------------------------------------------

_TABLE_CELL_RE = re.compile(r"(?:(\d+)\+)?([.<>^])?([ha])?(?:\.(\d+)\+)?\|")


def _parse_cell_prefix(prefix: str) -> tuple[str, dict[str, str]]:
    """Parse an AsciiDoc table cell prefix (e.g. ``3+h|``, ``^|``, ``.3+|``).

    Returns ``(tag, attrs)`` where *tag* is ``"th"`` or ``"td"`` and
    *attrs* is a dict suitable for building the opening tag attributes.
    """
    tag = "td"
    attrs: dict[str, str] = {}

    # combined colspan+rowspan: N.M+  (e.g. "2.2+" → colspan=2 rowspan=2)
    combined_m = re.match(r"^(\d+)\.(\d+)\+", prefix)
    if combined_m:
        attrs["colspan"] = combined_m.group(1)
        attrs["rowspan"] = combined_m.group(2)
        prefix = prefix[combined_m.end() :]
    else:
        # colspan: N+  (e.g. "3+")
        colspan_m = re.match(r"^(\d+)\+", prefix)
        if colspan_m:
            attrs["colspan"] = colspan_m.group(1)
            prefix = prefix[colspan_m.end() :]

        # rowspan: .N+  (e.g. ".3+")
        rowspan_m = re.match(r"^\.(\d+)\+", prefix)
        if rowspan_m:
            attrs["rowspan"] = rowspan_m.group(1)
            prefix = prefix[rowspan_m.end() :]

    # alignment specifier: ^, <, >, .
    if prefix.startswith("^"):
        attrs["style"] = "text-align:center"
        prefix = prefix[1:]
    elif prefix.startswith(">"):
        attrs["style"] = "text-align:right"
        prefix = prefix[1:]
    elif prefix.startswith("<"):
        prefix = prefix[1:]  # left is default, no extra attr

    # cell type: h=header, a=asciidoc, s=strong, m=monospace, e=emphasis, l=literal
    if prefix.startswith("h"):
        tag = "th"
        prefix = prefix[1:]
    elif prefix.startswith("a"):
        prefix = prefix[1:]  # treat as normal td
    elif prefix.startswith("s"):
        attrs["class"] = "strong"
        prefix = prefix[1:]
    elif prefix.startswith("m"):
        attrs["class"] = "monospace"
        prefix = prefix[1:]
    elif prefix.startswith("e"):
        attrs["class"] = "emphasis"
        prefix = prefix[1:]
    elif prefix.startswith("l"):
        attrs["class"] = "literal"
        prefix = prefix[1:]

    return tag, attrs


def _build_tag(tag: str, attrs: dict[str, str], content: str) -> str:
    """Build an HTML element string."""
    attr_str = "".join(f' {k}="{v}"' for k, v in attrs.items())
    return f"<{tag}{attr_str}>{content}</{tag}>"


def _parse_cols_widths(cols_attr: str) -> list[str]:
    """Parse ``cols="1,2,1"`` or ``cols="1,3,5"`` → percentage width strings.

    Each number is treated as a proportional weight. Returns strings like
    ``"14%"`` ready for ``<col style="width:14%">``, or an empty list if
    the attribute cannot be parsed.

    Note: alignment specifiers (``<>^~``) inside the cols list are stripped
    here.  Use :func:`_parse_cols_widths_aligns` to capture them.
    """
    parts = [p.strip().rstrip("*ah<>^~%") for p in cols_attr.split(",")]
    try:
        weights = [float(p) for p in parts if p]
    except ValueError:
        return []
    total = sum(weights)
    if total == 0:
        return []
    return [f"{round(w / total * 100)}%" for w in weights]


def _parse_cols_widths_aligns(
    cols_attr: str,
) -> tuple[list[str], list[str | None]]:
    """Parse ``cols="<,^,>"`` or ``cols="1<,2^,1>"`` → (widths, alignments).

    Alignments are ``"left"``/``"center"``/``"right"`` or ``None`` for the default.
    Each comma-separated entry may include a leading multiplier (``Nx``), a
    width (number), an alignment glyph (``<`` left, ``^`` center, ``>`` right),
    and a trailing style/percent marker.  Multipliers expand the column count.
    """
    raw_parts = [p.strip() for p in cols_attr.split(",") if p.strip()]
    align_map = {"<": "left", "^": "center", ">": "right"}
    widths: list[str] = []
    aligns: list[str | None] = []
    for part in raw_parts:
        # Optional repeat: Nx prefix (e.g. "3*<" or "2*1<")
        rep = 1
        rep_m = re.match(r"^(\d+)\*", part)
        if rep_m:
            rep = int(rep_m.group(1))
            part = part[rep_m.end() :]
        align: str | None = None
        for glyph, name in align_map.items():
            if glyph in part:
                align = name
                part = part.replace(glyph, "")
                break
        # Strip non-numeric trailing chars (style markers a/h/%/~)
        cleaned = re.sub(r"[ah%~]", "", part).strip()
        # The remaining piece is the width; default 1 if missing
        try:
            weight = float(cleaned) if cleaned else 1.0
        except ValueError:
            weight = 1.0
        for _ in range(rep):
            widths.append(str(weight))
            aligns.append(align)
    total = sum(float(w) for w in widths) if widths else 0.0
    if total == 0:
        return [], aligns
    pct_widths = [f"{round(float(w) / total * 100)}%" for w in widths]
    return pct_widths, aligns


def _convert_cell_paragraph(text: str) -> str:
    """Convert paragraph text inside an a| cell, handling list markers.

    Returns an HTML fragment.  Prose is wrapped in ``<p>...</p>``; list items
    are wrapped in ``<ul>``/``<ol>``.  Mixed content (e.g. intro prose followed
    by a list) yields valid sequential block HTML — never `<p>...<ul>...</ul></p>`.
    """
    lines = [ln for ln in text.strip().split("\n") if ln.strip()]
    if not lines:
        return ""

    def _emit_list(tag: str, prefix: str, items_lines: list[str]) -> str:
        items = "".join(f"<li>{ln.strip()[len(prefix) :]}</li>" for ln in items_lines)
        return f"<{tag}>{items}</{tag}>"

    # Walk lines and group prose vs list-item runs so prose preceding/following a
    # list is not silently dropped (common in HEIF tables: "Defined values:\n\n* a\n* b").
    parts: list[str] = []
    prose_buf: list[str] = []
    list_buf: list[str] = []
    list_kind: str | None = None  # "ul" or "ol"
    has_block = False  # set True when we emit a list (mixed-content guard for callers)

    def _flush_prose() -> None:
        if prose_buf:
            parts.append(" ".join(prose_buf))
            prose_buf.clear()

    def _flush_list() -> None:
        nonlocal list_kind, has_block
        if list_buf and list_kind:
            prefix = "* " if list_kind == "ul" else ". "
            parts.append(_emit_list(list_kind, prefix, list_buf))
            has_block = True
            list_buf.clear()
            list_kind = None

    for ln in lines:
        s = ln.strip()
        if s.startswith("* "):
            if list_kind != "ul":
                _flush_list()
                list_kind = "ul"
            _flush_prose()
            list_buf.append(ln)
        elif s.startswith(". "):
            if list_kind != "ol":
                _flush_list()
                list_kind = "ol"
            _flush_prose()
            list_buf.append(ln)
        else:
            _flush_list()
            prose_buf.append(s)

    _flush_list()
    _flush_prose()

    # If we emitted any list, wrap remaining prose in <p> so the result is valid
    # block HTML (no <p>prose<ul>...</ul></p>).  Otherwise return joined plain text.
    if not parts:
        return ""
    if has_block:
        # Walk parts and wrap any non-list piece in <p>...</p>
        out_parts: list[str] = []
        for p in parts:
            if p.startswith(("<ul>", "<ol>")):
                out_parts.append(p)
            else:
                out_parts.append(f"<p>{p}</p>")
        return "".join(out_parts)
    return "".join(parts)


def _parse_table_block(
    lines: list[str],
    start_idx: int,
    ctx: _SectionConverter | None = None,  # noqa: UP037
    anchor: str | None = None,
    col_widths: list[str] | None = None,
    col_aligns: list[str | None] | None = None,
    has_footer: bool = False,
    header_from_attr: bool = False,
    extra_classes: list[str] | None = None,
) -> tuple[list[str], int]:
    """Parse a ``|===`` ... ``|===`` block and return (html_lines, next_idx).

    *start_idx* should point to the line **after** the opening ``|===``.
    Returns a list of HTML lines and the index of the first line after the
    closing ``|===``.

    Row model:
    - A line that begins with (optional cell-prefix)|  starts a NEW row.
    - Continuation lines (no leading |) append to the last cell's content.
    - A blank line also ends the current row (for multi-line cell blocks).
    """
    html: list[str] = []
    id_attr = f' id="{anchor}"' if anchor else ""
    classes = ["data"]
    if extra_classes:
        classes.extend(extra_classes)
    class_value = " ".join(classes)
    html.append(f'<table class="{class_value}"{id_attr}>')
    if col_widths:
        html.append("<colgroup>")
        for idx, w in enumerate(col_widths):
            style = f"width:{w}"
            if col_aligns and idx < len(col_aligns) and col_aligns[idx]:
                style += f";text-align:{col_aligns[idx]}"
            html.append(f'<col style="{style}">')
        html.append("</colgroup>")

    # Collect all raw table lines until closing |===
    raw_lines: list[str] = []
    i = start_idx
    while i < len(lines):
        if lines[i].strip() == "|===":
            i += 1
            break
        raw_lines.append(lines[i])
        i += 1

    # cell_boundary_re: matches an optional cell prefix followed by |
    # prefix chars: digits + (colspan), . + digits + (rowspan), ^<> (align), h/a (type)
    cell_boundary_re = _TABLE_CELL_BOUNDARY_RE

    rows: list[list[tuple[str, dict[str, str], str]]] = []
    current_row: list[tuple[str, dict[str, str], str]] = []
    # Pending cell accumulator — use a mutable dict so nested closures always see
    # the current values without needing nonlocal rebinding.
    # "asciidoc" is True when the current cell has the "a|" cell type, which
    # allows block-level content (blank lines become paragraph breaks, not row
    # boundaries).
    _PARA_SEP = "\x00PARASEP\x00"
    cell_state: dict = {
        "tag": "td",
        "attrs": {},
        "parts": [],
        "active": False,
        "asciidoc": False,
    }

    def _flush_cell() -> None:
        if cell_state["active"]:
            if cell_state["asciidoc"] and _PARA_SEP in cell_state["parts"]:
                # Split on paragraph separator tokens, join each paragraph's
                # words, then convert via _convert_cell_paragraph which handles
                # list items (* / .) and wraps plain paragraphs in <p> tags.
                para_parts: list[str] = []
                para_words: list[str] = []
                for p in cell_state["parts"]:
                    if p == _PARA_SEP:
                        # Join with newlines so _convert_cell_paragraph can detect
                        # per-line list markers.
                        raw = "\n".join(w.strip() for w in para_words if w.strip())
                        converted = _convert_cell_paragraph(raw)
                        if converted:
                            # Block content (lists or mixed) is already validly wrapped.
                            # Plain prose still needs <p>...</p>.
                            if converted.startswith(("<ul>", "<ol>", "<p>")):
                                para_parts.append(converted)
                            else:
                                para_parts.append(f"<p>{converted}</p>")
                        para_words = []
                    else:
                        para_words.append(p)
                raw = "\n".join(w.strip() for w in para_words if w.strip())
                converted = _convert_cell_paragraph(raw)
                if converted:
                    if converted.startswith(("<ul>", "<ol>", "<p>")):
                        para_parts.append(converted)
                    else:
                        para_parts.append(f"<p>{converted}</p>")
                content = "".join(para_parts)
            elif cell_state["asciidoc"]:
                # Single paragraph asciidoc cell — check for list items too.
                raw = "\n".join(p.strip() for p in cell_state["parts"] if p.strip())
                content = _convert_cell_paragraph(raw)
            else:
                content = " ".join(p.strip() for p in cell_state["parts"] if p.strip())
            content = _restore_backtick_pipes(content)
            current_row.append((cell_state["tag"], dict(cell_state["attrs"]), content))
            cell_state["active"] = False
            cell_state["parts"].clear()
            cell_state["asciidoc"] = False

    def _flush_row() -> None:
        nonlocal current_row
        _flush_cell()
        if current_row:
            rows.append(current_row)
            current_row = []

    def _line_starts_cells(stripped: str) -> bool:
        """Return True if *stripped* begins with a cell boundary (optional prefix + |)."""
        m = cell_boundary_re.match(stripped)
        return m is not None and m.start() == 0

    for raw in raw_lines:
        stripped = raw.strip()
        stripped = _protect_backtick_pipes(stripped)  # protect pipes inside backtick spans

        if not stripped:
            # Blank line ends the current row, UNLESS we are accumulating an
            # asciidoc cell (a|) which allows multi-paragraph block content.
            if cell_state["active"] and cell_state["asciidoc"]:
                cell_state["parts"].append(_PARA_SEP)
            else:
                _flush_row()
            continue

        if _line_starts_cells(stripped):
            # This line starts one or more new cells → it is a new row.
            # Flush the previous row first.
            _flush_row()

            # Now parse all cells on this line
            pos = 0
            while pos < len(stripped):
                m = cell_boundary_re.match(stripped, pos)
                if not m:
                    # Trailing text after last cell (shouldn't happen normally)
                    if cell_state["active"]:
                        cell_state["parts"].append(stripped[pos:])
                    break
                prefix = m.group(1)
                pipe_end = m.end()
                # Flush previous cell (from earlier on this same line)
                if cell_state["active"]:
                    _flush_cell()
                # Find where this cell's content ends (at the next cell boundary)
                next_m = cell_boundary_re.search(stripped, pipe_end)
                if next_m:
                    content_text = stripped[pipe_end : next_m.start()]
                    pos = next_m.start()
                else:
                    content_text = stripped[pipe_end:]
                    pos = len(stripped)

                new_tag, new_attrs = _parse_cell_prefix(prefix)
                # Detect "a" (asciidoc) cell type from the raw prefix.
                # After stripping combined N.M+, colspan (\d+\+), rowspan (\.\d+\+),
                # and alignment (^<>), if the remaining char is "a" the cell allows
                # multi-paragraph block content.
                raw_type = re.sub(r"^\d+\.\d+\+|^\d+\+|^\.\d+\+|^[.<>^]", "", prefix)
                cell_state["tag"] = new_tag
                cell_state["attrs"] = new_attrs
                cell_state["parts"] = [content_text]
                cell_state["active"] = True
                cell_state["asciidoc"] = raw_type.startswith("a")
        else:
            # Continuation line: append to the current cell's content
            if cell_state["active"]:
                cell_state["parts"].append(stripped)
            else:
                # Orphan text — treat as a plain td
                cell_state["tag"] = "td"
                cell_state["attrs"] = {}
                cell_state["parts"] = [stripped]
                cell_state["active"] = True

    # End of table — flush any remaining row
    _flush_row()

    # Apply per-column alignment from cols=… spec to each cell's style attr
    # (cell-level alignment specifiers in the prefix override column defaults).
    if col_aligns:

        def _apply_col_align(
            row: list[tuple[str, dict[str, str], str]],
        ) -> list[tuple[str, dict[str, str], str]]:
            new_row: list[tuple[str, dict[str, str], str]] = []
            col = 0
            for tag, attrs, content in row:
                if col < len(col_aligns) and col_aligns[col]:
                    existing = attrs.get("style", "")
                    if "text-align" not in existing:
                        attrs = dict(attrs)
                        new_style = f"text-align:{col_aligns[col]}"
                        attrs["style"] = f"{existing};{new_style}" if existing else new_style
                new_row.append((tag, attrs, content))
                col += int(attrs.get("colspan", "1"))
            return new_row

        rows = [_apply_col_align(r) for r in rows]

    # Emit rows, splitting thead (all-<th> first row, or %header attr) from tbody
    def _ci(c: str) -> str:
        return _convert_inline(c, _ctx=ctx)

    # If the caller flagged a [footer] row, split off the last row for <tfoot>.
    footer_row: list[tuple[str, dict[str, str], str]] | None = None
    if has_footer and rows:
        footer_row = rows[-1]
        rows = rows[:-1]

    if rows:
        first_row_all_th = all(tag == "th" for tag, _, _ in rows[0])
        treat_first_as_header = first_row_all_th or header_from_attr
        html.append("<thead>")
        if treat_first_as_header:
            # Render first row cells as <th> regardless of their original tag
            first_row_html = (
                "<tr>" + "".join(_build_tag("th", a, _ci(c)) for _, a, c in rows[0]) + "</tr>"
            )
            html.append(first_row_html)
            html.append("</thead>")
            html.append("<tbody>")
            for row in rows[1:]:
                html.append("<tr>" + "".join(_build_tag(t, a, _ci(c)) for t, a, c in row) + "</tr>")
        else:
            html.append("</thead>")
            html.append("<tbody>")
            for row in rows:
                html.append("<tr>" + "".join(_build_tag(t, a, _ci(c)) for t, a, c in row) + "</tr>")
    elif footer_row is None:
        html.append("<thead>")
        html.append("</thead>")
        html.append("<tbody>")
    else:
        # No body rows but a footer row exists — still emit valid structure.
        html.append("<thead>")
        html.append("</thead>")
        html.append("<tbody>")

    html.append("</tbody>")
    if footer_row is not None:
        html.append("<tfoot>")
        html.append("<tr>" + "".join(_build_tag(t, a, _ci(c)) for t, a, c in footer_row) + "</tr>")
        html.append("</tfoot>")
    html.append("</table>")
    return html, i


class _SectionConverter:
    """Line-by-line state machine for AsciiDoc → Bikeshed conversion."""

    # Block states
    _NORMAL = "normal"
    _CODE = "code"
    _LITERAL = "literal"
    _ADMONITION = "admonition"
    _PASSTHROUGH = "passthrough"
    _STEM_PASS = "stem_pass"
    _SIDEBAR = "sidebar"
    _QUOTE = "quote"
    _COMMENT = "comment"  # inside a //// block comment
    _OPEN_ADMON = "open_admon"  # inside `[NOTE]` + `--` open-block admonition

    def __init__(
        self,
        annex_counter: list[int],
        meta: dict[str, str] | None = None,
        used_slugs: set[str] | None = None,
        doc_attrs: dict[str, str] | None = None,
    ) -> None:
        self._annex_counter = annex_counter
        self._meta: dict[str, str] = meta or {}
        self._used_slugs: set[str] = used_slugs if used_slugs is not None else set()
        # Asciidoctor doc-path built-ins ({docname}/{docdir}/{docfile}); optional.
        self._doc_attrs: dict[str, str] = doc_attrs or {}
        self._pending_anchor: str | None = None
        self._pending_block_attr: str | None = None
        self._pending_caption: str | None = None
        self._state: str = self._NORMAL
        self._code_lang: str = ""
        self._admonition_class: str = "note"  # CSS class for the current admonition block
        self._in_verse: bool = False
        self._quote_attribution: str | None = None
        self._quote_citation: str | None = None
        self._in_terms_section: bool = False
        self._in_terms_dl: bool = False  # inside a <dl class="terms"> block
        self._warnings: list[str] = []
        self._out: list[str] = []
        self._in_dl: bool = False
        self._in_dd: bool = False
        self._in_dd_ul: bool = False
        self._in_dd_list_tag: str = "ul"
        self._in_bib_section: bool = False
        self._in_bib_list: bool = False
        self._stem_pass_lines: list[str] = []
        self._stem_close: str = "++++"
        self._stem_is_latex: bool = False
        # Literal block accumulator (.... delimiters)
        self._literal_lines: list[str] = []
        # Pending obligation (obligation=normative/informative block attr)
        self._pending_obligation: str | None = None
        # Table [%header] attribute flag
        self._table_header_from_attr: bool = False
        # Footnote collection
        self._footnotes: list[tuple[str, str, str]] = []  # (fn_id, ref_id, html_text)
        self._footnote_num: int = 0
        # HTML list state (replaces Markdown "- " list items)
        self._list_tag_stack: list[str] = []  # stack of "ul"/"ol" per depth
        self._in_li: bool = False  # innermost <li> is open
        self._list_base_depth: int = 0  # depth of first item in current list context
        self._list_continuation: bool = (
            False  # "+" seen after list item; suppress next blank-line close
        )
        # Optional CSS class to apply to the outermost <ul>/<ol> when opened.
        # Used by checklist (* [ ] / * [x]) and similar special list flavours.
        self._pending_list_class: str | None = None
        # Triple-colon ::: nested definition list state
        self._in_nested_dl: bool = False  # inside a nested <dl> for ::: entries
        self._in_nested_dd: bool = False  # inside a <dd> for ::: entry

    def convert(self, text: str) -> tuple[list[str], list[str]]:
        text = _evaluate_ifdef_blocks(text, self._meta)
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            i = self._process_line(lines, i)
        # Close any open blocks
        self._close_all_lists()
        self._close_nested_dl()
        self._close_dd()
        if self._in_dl:
            self._out.append("</dl>")
            self._in_dl = False
        if self._in_bib_list:
            self._out.append("</dl>")
            self._in_bib_list = False
        if self._in_terms_dl:
            self._out.append("</dd></dl>")
            self._in_terms_dl = False
        # Emit collected footnotes
        if self._footnotes:
            self._out.append("")
            self._out.append('<section class="footnotes" role="doc-endnotes">')
            self._out.append("<ol>")
            for fn_id, ref_id, fn_html in self._footnotes:
                self._out.append(
                    f'<li id="{fn_id}"><p>{fn_html} '
                    f'<a href="#{ref_id}" class="footnote-back" role="doc-backlink">↩</a></p></li>'
                )
            self._out.append("</ol>")
            self._out.append("</section>")
        return self._out, self._warnings

    def _emit(self, line: str) -> None:
        self._out.append(line)

    def _close_dd(self) -> None:
        """Close an open <dd> (and any <ul>/<ol> inside it)."""
        if self._in_dd_ul:
            self._out.append(f"</{self._in_dd_list_tag}>")
            self._in_dd_ul = False
        if self._in_dd:
            self._out.append("</dd>")
            self._in_dd = False

    def _close_nested_dl(self) -> None:
        """Close an open ::: nested <dl> inside a :: definition entry."""
        if self._in_nested_dd:
            self._out.append("</dd>")
            self._in_nested_dd = False
        if self._in_nested_dl:
            self._out.append("</dl>")
            self._in_nested_dl = False

    def _close_li(self) -> None:
        if self._in_li:
            self._out.append("</li>")
            self._in_li = False

    def _close_all_lists(self) -> None:
        """Close all open HTML list elements."""
        self._close_li()
        while self._list_tag_stack:
            tag = self._list_tag_stack.pop()
            self._out.append(f"</{tag}>")
            # If there are still parent levels, the parent li was left open
            # when we went deeper — close it before popping the next level.
            if self._list_tag_stack:
                self._out.append("</li>")
        self._list_base_depth = 0
        self._list_continuation = False
        self._pending_list_class = None

    def _open_list_item(self, depth: int, tag: str, content: str) -> None:
        """Open a new HTML list item at the given depth (1-based)."""
        # Normalize depth so that a list starting at depth=2 (**) without a depth=1
        # parent (* ) still produces flat siblings rather than spurious nesting.
        if not self._list_tag_stack:
            self._list_base_depth = depth
        if self._list_base_depth > 1:
            depth = max(1, depth - self._list_base_depth + 1)
        current = len(self._list_tag_stack)
        # Optional class for the outermost list (e.g. "checklist"). Consumed once.
        outer_class = self._pending_list_class
        if depth > current:
            # Going deeper: parent li stays open; add new list levels
            while len(self._list_tag_stack) < depth:
                if outer_class and not self._list_tag_stack:
                    self._out.append(f'<{tag} class="{outer_class}">')
                    self._pending_list_class = None
                else:
                    self._out.append(f"<{tag}>")
                self._list_tag_stack.append(tag)
        elif depth == current:
            # Same depth: just close the current li.
            # If the list type changed (ul↔ol), close the old container and open a new one.
            self._close_li()
            if self._list_tag_stack and self._list_tag_stack[-1] != tag:
                old_tag = self._list_tag_stack.pop()
                self._out.append(f"</{old_tag}>")
                self._out.append(f"<{tag}>")
                self._list_tag_stack.append(tag)
        else:
            # Going shallower: close current li, then close excess levels
            self._close_li()
            while len(self._list_tag_stack) > depth:
                t = self._list_tag_stack.pop()
                self._out.append(f"</{t}>")
                # Close the parent li that enclosed this nested list
                if len(self._list_tag_stack) >= depth:
                    self._out.append("</li>")
        self._out.append(f"<li>{content}")
        self._in_li = True

    def _warn(self, msg: str) -> None:
        self._warnings.append(msg)

    def _dedup_slug(self, slug: str) -> str:
        """Return slug, appending -2/-3/... if already used in this project."""
        if slug not in self._used_slugs:
            self._used_slugs.add(slug)
            return slug
        n = 2
        while f"{slug}-{n}" in self._used_slugs:
            n += 1
        deduped = f"{slug}-{n}"
        self._used_slugs.add(deduped)
        return deduped

    def _consume_anchor(self) -> str | None:
        """Consume pending [[anchor]], registering it so auto-slugs avoid it."""
        anchor = self._pending_anchor
        self._pending_anchor = None
        if anchor:
            if anchor in self._used_slugs:
                self._warn(f"explicit anchor '{anchor}' is already used by an earlier heading")
            self._used_slugs.add(anchor)
        return anchor

    def _resolve_slug(self, anchor: str | None, base_text: str) -> str:
        """Return anchor (explicit) or a deduplicated auto-slug from base_text."""
        return anchor if anchor else self._dedup_slug(_slugify(base_text))

    def _inline(self, text: str) -> str:
        """Inline conversion with this converter's context (footnotes, meta)."""
        return _convert_inline(text, _ctx=self)

    def _process_line(self, lines: list[str], i: int) -> int:  # noqa: C901
        line = lines[i]

        # --- Block comment (////) state ---
        if self._state == self._COMMENT:
            if line.strip() == "////":
                self._state = self._NORMAL
            return i + 1

        # --- Passthrough block ---
        if self._state == self._PASSTHROUGH:
            if line.strip() == "++++":
                self._state = self._NORMAL
            else:
                self._emit(line)
            return i + 1

        # --- Stem passthrough block (math content) ---
        if self._state == self._STEM_PASS:
            if line.strip() == self._stem_close:
                content = " ".join(self._stem_pass_lines)
                self._emit("")
                if getattr(self, "_stem_is_latex", False):
                    self._emit(f'<div class="math display">\\[{content}\\]</div>')
                else:
                    self._emit(_asciimathml_to_text(content))
                self._emit("")
                self._stem_pass_lines = []
                self._stem_close = "++++"
                self._stem_is_latex = False
                self._state = self._NORMAL
            else:
                self._stem_pass_lines.append(line.strip())
            return i + 1

        # --- Code block ---
        if self._state == self._CODE:
            if line.strip() == "----":
                if self._code_lang:
                    self._emit("</code></pre>")
                else:
                    self._emit("</pre>")
                self._state = self._NORMAL
                self._code_lang = ""
                # Consume any trailing callout list (<N> annotation text)
                j = i + 1
                callouts: list[tuple[str, str]] = []
                while j < len(lines):
                    stripped_j = lines[j].strip()
                    co_m = re.match(r"^<(\d+)>\s+(.+)$", stripped_j)
                    if co_m:
                        callouts.append((co_m.group(1), co_m.group(2)))
                        j += 1
                    elif not stripped_j and callouts:
                        j += 1
                        break
                    else:
                        break
                if callouts:
                    self._emit('<ol class="callout-list">')
                    for num, ann in callouts:
                        self._emit(f"<li><sup>({num})</sup> {self._inline(ann)}</li>")
                    self._emit("</ol>")
                return j
            else:
                # Replace callout markers <N> in code with superscripts
                escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                # Restore callout markers that got escaped: &lt;N&gt; → <sup>(N)</sup>
                escaped = re.sub(r"&lt;(\d+)&gt;", r"<sup>(\1)</sup>", escaped)
                self._emit(escaped)
            return i + 1

        # --- Literal block ---
        if self._state == self._LITERAL:
            if line.strip() == "....":
                content = "\n".join(self._literal_lines)
                escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                self._emit(f"<pre>{escaped}</pre>")
                self._literal_lines = []
                self._state = self._NORMAL
            else:
                self._literal_lines.append(line)
            return i + 1

        # --- Admonition block ---
        if self._state == self._ADMONITION:
            if line.strip() == "====":
                self._close_all_lists()
                self._emit("</div>")
                self._state = self._NORMAL
                return i + 1
            # Inside admonition: handle list items, blank lines, images, and inline content
            stripped = line.strip()
            if not stripped:
                self._close_all_lists()
                self._emit("")
                return i + 1
            # AsciiDoc list continuation marker — skip
            if stripped == "+":
                return i + 1
            # Block title / caption inside example block (e.g. grouped figures)
            if stripped.startswith(".") and not stripped.startswith(".."):
                self._pending_caption = stripped[1:].strip()
                return i + 1
            # Image macro inside example block
            img_m = _IMAGE_RE.match(stripped)
            if img_m:
                self._close_all_lists()
                self._process_image(img_m)
                return i + 1
            # Nested unordered list items — use HTML <li>
            if stripped.startswith("**** "):
                self._open_list_item(4, "ul", self._inline(stripped[5:]))
                return i + 1
            if stripped.startswith("*** "):
                self._open_list_item(3, "ul", self._inline(stripped[4:]))
                return i + 1
            if stripped.startswith("** "):
                self._open_list_item(2, "ul", self._inline(stripped[3:]))
                return i + 1
            if stripped.startswith("* "):
                self._open_list_item(1, "ul", self._inline(stripped[2:]))
                return i + 1
            # Nested ordered list items — use HTML <li>
            if stripped.startswith(".. "):
                self._open_list_item(2, "ol", self._inline(stripped[3:]))
                return i + 1
            if stripped.startswith(". "):
                self._open_list_item(1, "ol", self._inline(stripped[2:]))
                return i + 1
            # Inline admonition keywords inside an admonition block
            for _kw, _cls in (
                ("NOTE:", "note"),
                ("NOTE ", "note"),
                ("WARNING:", "advisement"),
                ("CAUTION:", "advisement"),
                ("IMPORTANT:", "advisement"),
                ("TIP:", "note"),
            ):
                if stripped.startswith(_kw):
                    _rest = stripped[len(_kw) :].lstrip()
                    if _rest or _kw.endswith(":"):
                        self._close_all_lists()
                        self._emit(f'<div class="{_cls}">{self._inline(_rest)}</div>')
                        return i + 1
            self._close_all_lists()
            self._emit(self._inline(line))
            return i + 1

        # --- Sidebar block ---
        if self._state == self._SIDEBAR:
            if line.strip() == "****":
                self._emit("</aside>")
                self._state = self._NORMAL
            else:
                self._emit(self._inline(line))
            return i + 1

        # --- Quote block ---
        if self._state == self._QUOTE:
            if line.strip() == "____":
                attribution = getattr(self, "_quote_attribution", None)
                citation = getattr(self, "_quote_citation", None)
                if attribution or citation:
                    pieces: list[str] = []
                    if attribution:
                        pieces.append(f"— {self._inline(attribution)}")
                    if citation:
                        pieces.append(f"<cite>{self._inline(citation)}</cite>")
                    self._emit('<p class="attribution">' + ", ".join(pieces) + "</p>")
                self._quote_attribution = None
                self._quote_citation = None
                self._emit("</blockquote>")
                self._in_verse = False
                self._state = self._NORMAL
            elif self._in_verse:
                self._emit(self._inline(line) + "<br>")
            else:
                self._emit(self._inline(line))
            return i + 1

        # --- Normal state ---

        stripped = line.strip()

        # Mid-document attribute definition: :attr-name: value (or bare :attr-name:)
        # These must be absorbed silently — not emitted as paragraph text.
        attr_def_m = _MID_DOC_ATTR_RE.match(stripped)
        if attr_def_m:
            attr_name = attr_def_m.group(1)
            attr_val = (attr_def_m.group(3) or "").strip()
            self._meta[attr_name] = attr_val
            return i + 1

        # Block comment delimiter: //// (must be checked before single-line // check)
        if stripped == "////":
            self._state = self._COMMENT
            return i + 1

        # AsciiDoc open block delimiter `--`.
        # When preceded by `[NOTE]` / `[WARNING]` / etc., open a div with the
        # appropriate class and treat content lines until the closing `--` as
        # the admonition body. Without a pending block attribute, `--` is a
        # plain structural grouping with no HTML output.
        if stripped == "--":
            if self._state == self._OPEN_ADMON:
                self._emit("</div>")
                self._state = self._NORMAL
                return i + 1
            attr = (self._pending_block_attr or "").lower()
            if attr:
                if any(x in attr for x in ("warning", "caution", "important")):
                    cls = "advisement"
                elif "note" in attr or "tip" in attr:
                    cls = "note"
                elif "example" in attr:
                    cls = "example"
                else:
                    cls = None
                if cls is not None:
                    self._pending_block_attr = None
                    anchor = self._consume_anchor() or ""
                    open_tag = f'<div class="{cls}"' + (f' id="{anchor}"' if anchor else "") + ">"
                    self._emit(open_tag)
                    self._state = self._OPEN_ADMON
                    return i + 1
            return i + 1

        # Page break
        if stripped == "<<<":
            self._emit('<div class="page-break" style="page-break-after:always"></div>')
            return i + 1

        # Conditional inclusion directives: skip the directive line itself
        # (block-form conditionals leave content lines to be processed normally)
        if (
            stripped.startswith("ifdef::")
            or stripped.startswith("ifndef::")
            or stripped.startswith("ifeval::")
            or stripped.startswith("endif::")
        ):
            # Extract inline content from single-line form: ifdef::attr[inline content]
            # (content is INSIDE the brackets, not after them)
            bracket_open = stripped.find("[")
            bracket_close = stripped.rfind("]")
            if bracket_open != -1 and bracket_close > bracket_open:
                inline_content = stripped[bracket_open + 1 : bracket_close].strip()
                if inline_content:
                    self._emit(self._inline(inline_content))
            return i + 1

        # Skip AsciiDoc comment lines
        if line.startswith("//"):
            return i + 1

        # Skip blank lines (emit them for paragraph breaks)
        if not line.strip():
            # "+" list continuation suppresses list-closing on the following blank line
            if self._list_continuation:
                self._list_continuation = False
            else:
                # Suppress list-closing if next non-blank line is also an em-dash list item
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                next_non_blank = lines[j].strip() if j < len(lines) else ""
                if not next_non_blank.startswith("\u2014 "):
                    self._close_all_lists()
            self._close_nested_dl()
            # Close definition list on blank line, but only if the next non-blank
            # line is NOT another definition entry (keep consecutive terms grouped).
            self._close_dd()
            if self._in_dl:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                next_line = lines[j] if j < len(lines) else ""
                if not _DEFLIST_RE.match(next_line) and not _DEFLIST_TERM_ONLY_RE.match(next_line):
                    self._emit("</dl>")
                    self._in_dl = False
            self._emit("")
            return i + 1

        # AsciiDoc list continuation marker (standalone + on its own line)
        if line.strip() == "+":
            if self._list_tag_stack or self._in_li:
                self._list_continuation = True
            return i + 1

        # Passthrough block start — if [stem...] attr precedes it, treat as math block
        if line.strip() == "++++":
            attr = (self._pending_block_attr or "").lower()
            self._pending_block_attr = None
            if "stem" in attr or "latexmath" in attr or "asciimath" in attr:
                self._state = self._STEM_PASS
                self._stem_pass_lines = []
                self._stem_is_latex = "latexmath" in attr
            else:
                self._state = self._PASSTHROUGH
            return i + 1

        # Sidebar block start
        if line.strip() == "****":
            self._emit("<aside>")
            self._state = self._SIDEBAR
            return i + 1

        # Quote block start
        if line.strip() == "____":
            raw_attr = self._pending_block_attr or ""
            attr = raw_attr.lower()
            self._pending_block_attr = None
            # Parse `[quote, attribution, citation]`. The block-attribute may be
            # comma-separated; the first token is the kind (quote/verse), the
            # rest are positional metadata.
            attribution: str | None = None
            citation: str | None = None
            if "," in raw_attr:
                parts = [p.strip() for p in raw_attr.split(",")]
                # parts[0] is the kind label (quote/verse); parts[1:] are
                # attribution / citation
                if len(parts) > 1 and parts[1]:
                    attribution = parts[1]
                if len(parts) > 2 and parts[2]:
                    citation = parts[2]
            self._quote_attribution = attribution
            self._quote_citation = citation
            if "verse" in attr:
                self._in_verse = True
                self._emit('<blockquote class="verse">')
            else:
                self._emit("<blockquote>")
            self._state = self._QUOTE
            return i + 1

        # Block anchor: [[id]]
        m = _ANCHOR_RE.match(line)
        if m:
            self._pending_anchor = m.group(1)
            return i + 1

        # Inline anchor: `[[id]] body text`. Set pending anchor and rewrite
        # the current line in place to drop the anchor prefix so the rest of
        # the dispatcher sees normal content.
        m = _ANCHOR_INLINE_RE.match(line)
        if m:
            self._pending_anchor = m.group(1)
            lines[i] = m.group(2)
            line = lines[i]

        # Block attribute: [attr] — capture for next block; accumulate multiple lines
        m = _BLOCK_ATTR_RE.match(line)
        if m:
            new_attr = m.group(1)
            if self._pending_block_attr:
                self._pending_block_attr = self._pending_block_attr + " " + new_attr
            else:
                self._pending_block_attr = new_attr
            # Extract obligation= from the attribute string (H)
            obl_m = re.search(r"\bobligation=(normative|informative)\b", new_attr, re.IGNORECASE)
            if obl_m:
                self._pending_obligation = obl_m.group(1).lower()
            return i + 1

        # AsciiDoc block/table caption: .Caption text (single dot prefix, not .. ordered list)
        m = _TABLE_CAPTION_RE.match(line)
        if m:
            # Store the full caption text (dot + first char + rest)
            self._pending_caption = line[1:]  # strip leading dot
            return i + 1

        # Multi-line stem:[...] block (no closing ] on same line): treat as passthrough
        if line.startswith("stem:[") and "]" not in line:
            # Collect until closing ] line
            math_lines = [line[6:].strip()]  # content after stem:[
            j = i + 1
            while j < len(lines):
                nl = lines[j]
                if nl.strip() == "]":
                    j += 1
                    break
                math_lines.append(nl)
                j += 1
            math_content = " ".join(ln.strip() for ln in math_lines if ln.strip())
            self._emit("")
            self._emit(_asciimathml_to_text(math_content))
            return j

        # include:: / embed:: directives — should already be resolved, but handle residual ones
        m = _INCLUDE_RE.match(line)
        if m:
            self._emit(f"<!-- include: {m.group(1)} -->")
            return i + 1
        if line.startswith("embed::"):
            self._emit(f"<!-- embed: {line[7:].split('[')[0].strip()} -->")
            return i + 1

        # Heading: == Title
        m = _HEADING_RE.match(line.strip())
        if m:
            return self._process_heading(m, lines, i)

        # Code block delimiter ---- (or math block if [stem] attribute precedes it)
        if line.strip() == "----":
            attr = (self._pending_block_attr or "").lower()
            if "stem" in attr:
                self._pending_block_attr = None
                self._state = self._STEM_PASS
                self._stem_close = "----"
                self._stem_pass_lines = []
            else:
                self._start_code_block()
            return i + 1

        # Literal block delimiter ....
        if line.strip() == "....":
            self._pending_block_attr = None
            self._literal_lines = []
            self._state = self._LITERAL
            return i + 1

        # Table delimiter |===
        if line.strip() == "|===":
            self._close_all_lists()
            return self._start_table(lines, i + 1)

        # Admonition inline: NOTE: text, NOTE:text, NOTE text, WARNING: text, etc.
        for kw, cls in (
            ("NOTE:", "note"),
            ("NOTE ", "note"),
            ("WARNING:", "advisement"),
            ("CAUTION:", "advisement"),
            ("IMPORTANT:", "advisement"),
            ("TIP:", "note"),
        ):
            if line.startswith(kw):
                rest = line[len(kw) :].lstrip()
                if rest or kw.endswith(":"):
                    content = self._inline(rest)
                    self._emit(f'<div class="{cls}">{content}</div>')
                    self._pending_block_attr = None
                    return i + 1

        # Admonition block (====) — always opens a block, semantic class from pending attr
        if line.strip() == "====":
            self._close_all_lists()
            attr = (self._pending_block_attr or "").lower()
            self._pending_block_attr = None
            if any(x in attr for x in ("warning", "caution", "important")):
                cls = "advisement"
            elif "requirement" in attr:
                cls = "requirement"
            elif "permission" in attr:
                cls = "permission"
            elif "recommendation" in attr:
                cls = "recommendation"
            elif "note" in attr or "tip" in attr:
                cls = "note"
            else:
                cls = "example"
            # Consume pending anchor and caption (figure groups use .Caption + [[id]])
            anchor = self._consume_anchor() or ""
            caption = self._pending_caption
            self._pending_caption = None
            open_tag = f'<div class="{cls}"' + (f' id="{anchor}"' if anchor else "") + ">"
            self._emit(open_tag)
            if caption:
                self._emit(f'<p class="caption">{self._inline(caption)}</p>')
            self._admonition_class = cls
            self._state = self._ADMONITION
            return i + 1

        # Bibliography entry: [[[REF,Full Name]]]
        m = _BIB_REF_RE.match(line)
        if m:
            return self._process_bib_entry(m, lines, i)

        # Block image: image::path[Caption]
        m = _IMAGE_RE.match(line)
        if m:
            self._process_image(m)
            return i + 1

        # Block video: video::path[attrs]
        m = _VIDEO_RE.match(line)
        if m:
            path, attrs_str = m.group(1).strip(), m.group(2)
            attrs = _parse_image_attrs(attrs_str)
            width = attrs.get("width", "")
            height = attrs.get("height", "")
            opts = attrs.get("opts", attrs.get("options", ""))
            w_attr = f' width="{width}"' if width else ""
            h_attr = f' height="{height}"' if height else ""
            controls = " controls" if not opts or "nocontrols" not in opts else ""
            autoplay = " autoplay" if "autoplay" in opts else ""
            self._close_all_lists()
            self._emit(
                f'<figure><video src="{path}"{w_attr}{h_attr}{controls}{autoplay}><p>Video: {path}</p></video></figure>'
            )
            return i + 1

        # Block audio: audio::path[attrs]
        m = _AUDIO_RE.match(line)
        if m:
            path, attrs_str = m.group(1).strip(), m.group(2)
            attrs = _parse_image_attrs(attrs_str)
            opts = attrs.get("opts", attrs.get("options", ""))
            controls = " controls" if not opts or "nocontrols" not in opts else ""
            autoplay = " autoplay" if "autoplay" in opts else ""
            self._close_all_lists()
            self._emit(f'<audio src="{path}"{controls}{autoplay}><p>Audio: {path}</p></audio>')
            return i + 1

        # Definition list: term:: definition  OR  term:: (term only on line)
        # Check triple-colon ::: FIRST (before ::, since ::: contains ::)
        dl3_m = _DEFLIST3_RE.match(line)
        if dl3_m:
            return self._process_deflist3_entry(dl3_m, lines, i)

        dl3_term_m = _DEFLIST3_TERM_ONLY_RE.match(line)
        if dl3_term_m:
            return self._process_deflist3_term_only(dl3_term_m, lines, i)

        dl_m = _DEFLIST_RE.match(line)
        if dl_m:
            # Make sure it's not an AsciiDoc labeled list for abbreviations (all caps term)
            return self._process_deflist_entry(dl_m, lines, i)

        dl_term_m = _DEFLIST_TERM_ONLY_RE.match(line)
        if dl_term_m:
            return self._process_deflist_term_only(dl_term_m, lines, i)

        # Bibliography list item: * [[[...]]] ... (must come before generic list item check)
        if self._in_bib_section and line.startswith("* "):
            return self._process_bib_list_item(line, lines, i)
        if line.startswith("* [[["):
            return self._process_bib_list_item(line, lines, i)

        # List items: unordered — use HTML <ul><li> with open-li pattern.
        # A `[checklist]` block attribute before the first item pre-sets the
        # list class so the <ul> is always emitted with class="checklist"
        # even for items that don't start with `* [ ]` / `* [x]`.
        if line.startswith(("**** ", "*** ", "** ", "* ")):
            attr_lower = (self._pending_block_attr or "").lower()
            if "checklist" in attr_lower and not self._list_tag_stack:
                self._pending_list_class = "checklist"
                self._pending_block_attr = None
            if line.startswith("**** "):
                depth, prefix_len = 4, 5
            elif line.startswith("*** "):
                depth, prefix_len = 3, 4
            elif line.startswith("** "):
                depth, prefix_len = 2, 3
            else:
                depth, prefix_len = 1, 2
            body = line[prefix_len:]
            # Checklist marker: "[ ] text" / "[x] text" / "[X] text" / "[*] text"
            checklist_m = _CHECKLIST_ITEM_RE.match(body)
            if checklist_m:
                checked = checklist_m.group(1).lower() in ("x", "*")
                checkbox = (
                    '<input type="checkbox" disabled checked> '
                    if checked
                    else '<input type="checkbox" disabled> '
                )
                content = checkbox + self._inline(checklist_m.group(2))
                # Mark the soon-to-open <ul> as a checklist if we're at the top
                if not self._list_tag_stack and not self._in_dd:
                    self._pending_list_class = "checklist"
            else:
                content = self._inline(body)
            if self._in_dd:
                # Inside a <dd>: immediate-close html li
                if not self._in_dd_ul:
                    self._emit("<ul>")
                    self._in_dd_ul = True
                    self._in_dd_list_tag = "ul"
                self._emit(f"<li>{content}</li>")
            else:
                self._open_list_item(depth, "ul", content)
            self._pending_block_attr = None
            return i + 1

        # List items: ordered — use HTML <ol><li> with open-li pattern
        if line.startswith("... "):
            content = self._inline(line[4:])
            if self._in_dd:
                if not self._in_dd_ul:
                    self._emit("<ol>")
                    self._in_dd_ul = True
                    self._in_dd_list_tag = "ol"
                self._emit(f"<li>{content}</li>")
            else:
                self._open_list_item(3, "ol", content)
            self._pending_block_attr = None
            return i + 1
        if line.startswith(".. "):
            content = self._inline(line[3:])
            if self._in_dd:
                if not self._in_dd_ul:
                    self._emit("<ol>")
                    self._in_dd_ul = True
                    self._in_dd_list_tag = "ol"
                self._emit(f"<li>{content}</li>")
            else:
                self._open_list_item(2, "ol", content)
            self._pending_block_attr = None
            return i + 1
        if line.startswith(". "):
            content = self._inline(line[2:])
            if self._in_dd:
                if not self._in_dd_ul:
                    self._emit("<ol>")
                    self._in_dd_ul = True
                    self._in_dd_list_tag = "ol"
                self._emit(f"<li>{content}</li>")
            else:
                self._open_list_item(1, "ol", content)
            self._pending_block_attr = None
            return i + 1

        # Horizontal rule
        if line.strip() in ("---", "'''"):
            self._emit("<hr>")
            return i + 1

        # EDITOR: notes → HTML comments
        if line.startswith("EDITOR:"):
            self._emit(f"<!-- EDITOR: {line[7:].strip()} -->")
            return i + 1

        # Metanorma term status macros: preferred:[text], admitted:[text], deprecated:[text]
        term_status_m = _TERM_STATUS_RE.match(stripped)
        if term_status_m:
            status = term_status_m.group(1)  # preferred / admitted / deprecated
            display = term_status_m.group(2)
            self._emit(f'<p class="{status}">{self._inline(display)}</p>')
            return i + 1

        # ISO em-dash list items: "— item text" (U+2014 em dash + space)
        if line.startswith("\u2014 "):
            content = self._inline(line[2:])
            self._open_list_item(1, "ul", content)
            return i + 1

        # Regular paragraph text
        # Close an open <ul>/<ol> inside a <dd> before emitting prose
        if self._in_dd_ul:
            self._emit(f"</{self._in_dd_list_tag}>")
            self._in_dd_ul = False
        # If there's an orphaned pending caption, check if it's an ISO section title
        if self._pending_caption:
            cap = self._pending_caption.strip()
            if cap.lower() in _ISO_UNNUMBERED:
                slug = _slugify(cap)
                self._emit(f'<h2 class="no-num" id="{slug}">{cap}</h2>')
            else:
                self._emit(self._inline(cap))
            self._pending_caption = None
        # Handle semantic class attrs: [.source], [.alt], and [literal] in terms sections
        pending_attr_lower = (self._pending_block_attr or "").lower().lstrip(".")
        if pending_attr_lower == "source":
            self._emit(f'<p class="source">SOURCE: {self._inline(line)}</p>')
            self._pending_block_attr = None
            return i + 1
        if pending_attr_lower == "alt":
            self._emit(f'<p class="alt-term">ADMITTED: {self._inline(line)}</p>')
            self._pending_block_attr = None
            return i + 1
        if pending_attr_lower.startswith("literal"):
            escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            self._emit(f"<pre>{escaped}</pre>")
            self._pending_block_attr = None
            return i + 1
        # Fix 2: [abstract] before a paragraph → <div class="abstract">
        if pending_attr_lower == "abstract":
            self._emit(f'<div class="abstract">{self._inline(line)}</div>')
            self._pending_block_attr = None
            return i + 1
        # Fix 3: role annotations [.lead], [.small], [.text-center], etc.
        # The pending attr starts with "." (before lstrip above stripped it), so check the
        # original pending attr for the leading dot.
        _raw_pending = self._pending_block_attr or ""
        if _raw_pending.startswith("."):
            role_str = _raw_pending[1:].strip()
            # Multiple roles are space-separated; join as CSS class string
            roles = " ".join(role_str.split())
            if roles:
                self._emit(f'<p class="{roles}">{self._inline(line)}</p>')
                self._pending_block_attr = None
                return i + 1
        # [%hardbreaks] — every internal newline of the paragraph becomes <br>.
        # Collect this and any following non-blank lines into a single <p>.
        if "%hardbreaks" in pending_attr_lower:
            para_lines = [self._inline(line)]
            j = i + 1
            while j < len(lines) and lines[j].strip():
                # Stop at any structural line (heading, list, block delim, attr, etc.)
                nxt = lines[j]
                nxt_stripped = nxt.strip()
                if (
                    _HEADING_RE.match(nxt_stripped)
                    or nxt.startswith(("* ", "- ", ". ", "** ", "*** ", "**** ", ".. ", "... "))
                    or nxt_stripped
                    in ("|===", "----", "....", "====", "****", "____", "++++", "--")
                    or nxt.startswith("[[[")
                    or nxt.startswith("[")
                    and nxt_stripped.endswith("]")
                ):
                    break
                para_lines.append(self._inline(nxt))
                j += 1
            self._emit("<p>" + "<br>\n".join(para_lines) + "</p>")
            self._pending_block_attr = None
            return j
        self._emit(self._inline(line))
        self._pending_block_attr = None
        return i + 1

    def _process_heading(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle == heading lines."""
        level_markers = m.group(1)  # "==" to "======"
        heading_text = m.group(2).strip()
        bs_level = len(level_markers) - 1  # == → 1 (#), === → 2 (##), etc.
        hashes = "#" * bs_level

        attr = self._pending_block_attr or ""
        self._pending_block_attr = None
        obligation = self._pending_obligation
        self._pending_obligation = None

        # Close any open lists, dl/dd
        self._close_all_lists()
        self._close_nested_dl()
        self._close_dd()
        if self._in_dl:
            self._emit("</dl>")
            self._in_dl = False
        if self._in_bib_list:
            self._emit("</dl>")
            self._in_bib_list = False
        if self._in_terms_dl:
            self._emit("</dd></dl>")
            self._in_terms_dl = False

        # Detect section type from block attribute
        is_appendix = "appendix" in attr.lower()
        is_bibliography = "bibliography" in attr.lower()
        is_discrete = "discrete" in attr.lower()
        is_abstract = "abstract" in attr.lower()
        # Book-structure section attributes ([partintro], [colophon], [dedication])
        # produce <section class="..."> wrappers so downstream styling can target them.
        attr_lower = attr.lower()
        book_section_class: str | None = None
        for _label in ("partintro", "colophon", "dedication"):
            if _label in attr_lower:
                book_section_class = _label
                break
        is_terms = bool(
            re.match(
                r"(?i)^(?:"
                r"terms\s+and\s+definitions(?:\s+and\s+(?:symbols?|abbreviations?))?|"
                r"terms,\s+definitions(?:\s+and\s+symbols?)?(?:\s+and\s+abbreviations?)?|"
                r"terms\s+(&)\s+definitions?|"
                r"vocabulary|"
                r"definitions"
                r")$",
                heading_text.strip(),
            )
        )

        # A heading inside a Terms section MAY be a term entry.
        # Use lookahead: if the next non-blank line is another heading, this is
        # a sub-section heading, not a term.  In Metanorma ISO convention,
        # `===` (bs_level=2) marks individual term entries within a Terms section;
        # only `====` and deeper are always sub-term entries.
        if self._in_terms_section and bs_level >= 2 and not is_appendix:
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            next_line = lines[j] if j < len(lines) else ""
            next_is_heading = bool(_HEADING_RE.match(next_line))
            # Also consider it a sub-section if it has no text below it at all
            if not next_is_heading:
                # It's a term definition entry
                slug = self._resolve_slug(self._consume_anchor(), heading_text)
                if not self._in_terms_dl:
                    self._emit('<dl class="terms">')
                    self._in_terms_dl = True
                else:
                    self._emit("</dd>")
                self._emit(
                    f'<dt id="{slug}"><dfn id="dfn-{slug}">{self._inline(heading_text)}</dfn></dt><dd>'
                )
                return i + 1

        if is_terms:
            self._in_terms_section = True
        elif bs_level == 1 and not is_terms:
            self._in_terms_section = False

        self._in_bib_section = is_bibliography

        anchor = self._consume_anchor()

        if is_appendix:
            self._annex_counter[0] += 1
            _n = self._annex_counter[0] - 1
            letter = string.ascii_uppercase[_n] if _n < 26 else f"X{_n + 1}"
            # Obligation priority: inline (normative) in heading attr > [obligation=…] block attr
            # > default informative
            if "normative" in attr.lower():
                annex_obligation = "normative"
            elif obligation:
                annex_obligation = obligation
            else:
                annex_obligation = "informative"
            slug = self._resolve_slug(anchor, f"annex-{letter}")
            display = f"Annex {letter} ({annex_obligation}) — {self._inline(heading_text)}"
            self._emit(f"{hashes} {display} {hashes} {{#{slug}}}")
        elif is_discrete:
            slug = self._resolve_slug(anchor, heading_text)
            level = bs_level + 1  # Bikeshed h-level
            self._emit(
                f'<h{level} class="no-num" id="{slug}">{self._inline(heading_text)}</h{level}>'
            )
        elif book_section_class:
            slug = self._resolve_slug(anchor, heading_text)
            level = bs_level + 1
            self._emit(f'<section class="{book_section_class}">')
            self._emit(f'<h{level} id="{slug}">{self._inline(heading_text)}</h{level}>')
            # Close immediately — book sections are typically short blocks.
            # Subsequent paragraphs will be siblings of this <section>; users
            # who need richer structure can rely on the class for CSS scoping.
            self._emit("</section>")
        elif is_abstract or heading_text.lower() in _ISO_UNNUMBERED:
            slug = self._resolve_slug(anchor, heading_text)
            self._emit(f'<h2 class="no-num" id="{slug}">{self._inline(heading_text)}</h2>')
        elif is_bibliography:
            slug = self._resolve_slug(anchor, heading_text)
            self._emit(f"{hashes} {self._inline(heading_text)} {hashes} {{#{slug}}}")
            self._emit('<dl class="bibliography">')
            self._in_bib_list = True
        else:
            slug = self._resolve_slug(anchor, heading_text)
            if obligation:
                level = bs_level + 1
                self._emit(
                    f'<h{level} id="{slug}" data-obligation="{obligation}">'
                    f"{self._inline(heading_text)}</h{level}>"
                )
            else:
                self._emit(f"{hashes} {self._inline(heading_text)} {hashes} {{#{slug}}}")

        return i + 1

    def _start_code_block(self) -> None:
        """Open a code block, checking pending block attribute for language."""
        attr = self._pending_block_attr or ""
        self._pending_block_attr = None
        lang = ""
        # [source,lang] or [source,lang,...] or [source%unnumbered] or [source%unnumbered,lang]
        # Try "source,lang" first, then "source%flag,lang", then "source%flag"
        m = re.match(r"(?i)source(?:%[a-zA-Z]+)?(?:\s*,\s*([a-zA-Z0-9_+-]+))?", attr)
        if m and m.group(1) and m.group(1).lower() != "unnumbered":
            lang = m.group(1)
        self._code_lang = lang
        if lang:
            self._emit(f'<pre highlight="{lang}"><code>')
        else:
            self._emit("<pre>")
        self._state = self._CODE

    def _start_table(self, lines: list[str], start_idx: int) -> int:
        """Parse a full |===...  |=== block and emit HTML. Returns next line index."""
        # Extract anchor and cols= from pending state before consuming them
        anchor = self._pending_anchor
        self._pending_anchor = None
        if anchor:
            self._used_slugs.add(anchor)
        block_attr = self._pending_block_attr or ""
        self._pending_block_attr = None
        caption = self._pending_caption
        self._pending_caption = None
        # Parse cols= attribute for proportional column widths and per-column alignment.
        # Match either a quoted value (e.g. cols=">,<,^") or an unquoted token.
        # The quoted form must come first so that a `>` inside the value isn't
        # misinterpreted as an attribute terminator.
        cols_m = re.search(r'\bcols=(?:"([^"]+)"|\'([^\']+)\'|([^\s,\]]+))', block_attr)
        col_widths: list[str] | None = None
        col_aligns: list[str | None] | None = None
        if cols_m:
            cols_value = cols_m.group(1) or cols_m.group(2) or cols_m.group(3) or ""
            col_widths, col_aligns = _parse_cols_widths_aligns(cols_value)
            if not any(col_aligns):
                col_aligns = None
            if not col_widths:
                col_widths = None
        # Detect [%header] or [options="header"] attribute — treat first row as header
        if (
            "%header" in block_attr
            or 'options="header"' in block_attr
            or "options=header" in block_attr
        ):
            self._table_header_from_attr = True
        # Detect [%footer] / [footer] / options="footer" → wrap last row in <tfoot>
        has_footer = (
            "%footer" in block_attr
            or 'options="footer"' in block_attr
            or "options=footer" in block_attr
            or bool(re.search(r"(?:^|[\s,])footer(?:[\s,]|$)", block_attr))
        )
        # Parse table styling attributes: stripes=, grid=, frame=
        # Each maps to a CSS class on <table>. Recognised values mirror Asciidoctor.
        extra_classes: list[str] = []
        _STRIPES_VALUES = ("odd", "even", "hover", "none")
        _GRID_VALUES = ("all", "rows", "cols", "none")
        _FRAME_VALUES = ("all", "topbot", "ends", "sides", "none")
        for key, allowed in (
            ("stripes", _STRIPES_VALUES),
            ("grid", _GRID_VALUES),
            ("frame", _FRAME_VALUES),
        ):
            m = re.search(
                rf'\b{key}=(?:"([^"]+)"|\'([^\']+)\'|([^\s,\]]+))',
                block_attr,
            )
            if m:
                value = (m.group(1) or m.group(2) or m.group(3) or "").strip().lower()
                if value in allowed:
                    extra_classes.append(f"{key}-{value}")
        html_lines, next_i = _parse_table_block(
            lines,
            start_idx,
            ctx=self,
            anchor=anchor,
            col_widths=col_widths,
            col_aligns=col_aligns,
            has_footer=has_footer,
            header_from_attr=self._table_header_from_attr,
            extra_classes=extra_classes or None,
        )
        self._table_header_from_attr = False
        if caption and html_lines:
            # Insert <caption> after <table ...> and optional <colgroup>
            insert_at = 1
            while insert_at < len(html_lines) and html_lines[insert_at].startswith("<col"):
                insert_at += 1
            if insert_at < len(html_lines) and html_lines[insert_at] == "</colgroup>":
                insert_at += 1
            caption_line = f"<caption>{self._inline(caption)}</caption>"
            html_lines = html_lines[:insert_at] + [caption_line] + html_lines[insert_at:]
        for hl in html_lines:
            self._emit(hl)
        return next_i

    def _process_deflist_entry(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle ``term:: definition`` style definition list entry."""
        self._close_nested_dl()
        term = m.group(1).strip()
        defn = m.group(2).strip()
        if not self._in_dl:
            attr = (self._pending_block_attr or "").lower()
            self._pending_block_attr = None
            if "%key" in attr:
                dl_class = "key"
            elif "horizontal" in attr:
                dl_class = "horizontal"
            elif "qanda" in attr:
                dl_class = "qanda"
            else:
                dl_class = ""
            class_attr = f' class="{dl_class}"' if dl_class else ""
            self._emit(f"<dl{class_attr}>")
            self._in_dl = True
        self._close_dd()
        # Detect ``+``-style continuation paragraphs after the first defn line.
        cont_paras = self._collect_deflist_continuations(lines, i)
        if cont_paras:
            self._emit(f"<dt>{self._inline(term)}</dt><dd>")
            self._emit(f"<p>{self._inline(defn)}</p>")
            for para in cont_paras[:-1]:
                self._emit(f"<p>{self._inline(para)}</p>")
            # Leave the dd open for further inline content from the last paragraph.
            self._emit(f"<p>{self._inline(cont_paras[-1])}</p>")
            self._in_dd = True
            return i + 1 + 2 * len(cont_paras)
        self._emit(f"<dt>{self._inline(term)}</dt><dd>{self._inline(defn)}")
        self._in_dd = True
        return i + 1

    def _process_deflist_term_only(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle ``term::`` (term alone on line, definition on next line)."""
        self._close_nested_dl()
        term = m.group(1).strip()
        if not self._in_dl:
            attr = (self._pending_block_attr or "").lower()
            self._pending_block_attr = None
            if "%key" in attr:
                dl_class = "key"
            elif "horizontal" in attr:
                dl_class = "horizontal"
            elif "qanda" in attr:
                dl_class = "qanda"
            else:
                dl_class = ""
            class_attr = f' class="{dl_class}"' if dl_class else ""
            self._emit(f"<dl{class_attr}>")
            self._in_dl = True
        self._close_dd()
        # Locate definition on the next non-blank line
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and not _HEADING_RE.match(lines[j]) and not lines[j].startswith("[[["):
            defn = lines[j].strip()
            cont_paras = self._collect_deflist_continuations(lines, j)
            if cont_paras:
                self._emit(f"<dt>{self._inline(term)}</dt><dd>")
                self._emit(f"<p>{self._inline(defn)}</p>")
                for para in cont_paras[:-1]:
                    self._emit(f"<p>{self._inline(para)}</p>")
                self._emit(f"<p>{self._inline(cont_paras[-1])}</p>")
                self._in_dd = True
                return j + 1 + 2 * len(cont_paras)
            self._emit(f"<dt>{self._inline(term)}</dt><dd>{self._inline(defn)}")
            self._in_dd = True
            return j + 1
        # Term with no following definition — emit dt alone
        self._emit(f"<dt>{self._inline(term)}</dt>")
        return i + 1

    def _collect_deflist_continuations(self, lines: list[str], i: int) -> list[str]:
        """Return list of continuation paragraphs after a deflist defn line.

        AsciiDoc uses ``+`` on its own line as the list-continuation marker:
        the paragraph after the ``+`` belongs to the same dd. This scans
        forward starting at ``i`` (the line containing the first defn),
        accumulating ``+``-separated paragraphs and stops at the first
        non-continuation gap.
        """
        paras: list[str] = []
        j = i + 1
        while j + 1 < len(lines):
            if lines[j].strip() != "+":
                break
            nxt = lines[j + 1]
            if not nxt.strip():
                break
            paras.append(nxt.strip())
            j += 2
        return paras

    def _process_deflist3_entry(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle ``term::: definition`` — nested definition list (one level deeper than ::)."""
        term = m.group(1).strip()
        defn = m.group(2).strip()
        if not self._in_nested_dl:
            self._emit("<dl>")
            self._in_nested_dl = True
        if self._in_nested_dd:
            self._emit("</dd>")
        self._emit(f"<dt>{self._inline(term)}</dt>")
        self._emit(f"<dd>{self._inline(defn)}")
        self._in_nested_dd = True
        return i + 1

    def _process_deflist3_term_only(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle ``term:::`` (term alone on line, definition on next line)."""
        term = m.group(1).strip()
        if not self._in_nested_dl:
            self._emit("<dl>")
            self._in_nested_dl = True
        if self._in_nested_dd:
            self._emit("</dd>")
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        if j < len(lines) and not _HEADING_RE.match(lines[j]) and not lines[j].startswith("[[["):
            defn = lines[j].strip()
            self._emit(f"<dt>{self._inline(term)}</dt>")
            self._emit(f"<dd>{self._inline(defn)}")
            self._in_nested_dd = True
            return j + 1
        self._emit(f"<dt>{self._inline(term)}</dt>")
        return i + 1

    def _process_bib_entry(self, m: re.Match, lines: list[str], i: int) -> int:
        """Handle bibliography reference entry [[[REF,Full Name]]]."""
        ref_id = m.group(1).strip()
        raw_name = m.group(2).strip() if m.group(2) else ref_id
        # Resolve repo:(...) / path:(...) collection references to a display name
        ref_name = _extract_bib_display_name(raw_name)
        # Collect trailing lines as the citation content
        citation_lines: list[str] = []
        j = i + 1
        while j < len(lines) and lines[j].strip() and not lines[j].startswith("[[["):
            citation_lines.append(lines[j].strip())
            j += 1
        citation = " ".join(citation_lines)
        full_ref = f"{ref_name}{', ' + citation if citation else ''}"
        # Emit as Bikeshed-compatible bibliography entry
        self._emit(f'<dt id="biblio-{self._dedup_slug(_slugify(ref_id))}">[{ref_id}]</dt>')
        self._emit(f"<dd>{self._inline(full_ref)}</dd>")
        return j

    def _process_bib_list_item(self, line: str, lines: list[str], i: int) -> int:
        """Handle bibliography list items ``* [[[REF,Name]]], _citation text_``."""
        content = line[2:].strip() if line.startswith("* ") else line.strip()
        bib_m = _BIB_REF_RE.match(content)
        if bib_m:
            ref_id = bib_m.group(1).strip()
            raw_name = bib_m.group(2).strip() if bib_m.group(2) else ref_id
            ref_name = _extract_bib_display_name(raw_name)
            # Remaining text after [[[...]]] on this line
            rest = content[bib_m.end() :].strip().lstrip(",").strip()
            # Collect continuation lines
            j = i + 1
            while (
                j < len(lines)
                and lines[j].strip()
                and not lines[j].startswith("* [[[")
                and not lines[j].startswith("[[[")
            ):
                rest = rest + " " + lines[j].strip()
                j += 1
            citation = rest.strip()
            full_ref = f"{ref_name}{', ' + citation if citation else ''}"
            anchor = self._dedup_slug(_slugify(ref_id))
            self._emit(f'<dt id="biblio-{anchor}">[{ref_id}]</dt>')
            self._emit(f"<dd>{self._inline(full_ref)}</dd>")
            return j
        else:
            # Plain-text bibliography entry without [[[...]]] anchor.
            # Emit as a self-contained <dt>/<dd> pair to keep valid <dl> structure.
            self._emit(f'<dt class="bib-plain">{self._inline(content)}</dt>')
            self._emit("<dd></dd>")
            return i + 1

    def _process_image(self, m: re.Match) -> None:
        """Handle image:: block macro."""
        path = m.group(1).strip()
        attrs = _parse_image_attrs(m.group(2))
        alt_text = attrs.get("alt", "")
        # Block caption (.Caption text) takes priority over attrs alt text
        caption = (self._pending_caption or "").strip() or alt_text
        self._pending_caption = None
        anchor = self._consume_anchor() or ""
        fig_id = anchor or self._dedup_slug(_slugify(caption) if caption else _slugify(path))
        # Build img tag with optional width/height
        img_attrs = f' src="{path}"'
        if alt_text or caption:
            plain_alt = _to_plain_text(self._inline(alt_text or caption))
            img_attrs += f' alt="{plain_alt}"'
        if "width" in attrs:
            img_attrs += f' width="{attrs["width"]}"'
        if "height" in attrs and attrs["height"] != "auto":
            img_attrs += f' height="{attrs["height"]}"'
        img_tag = f"<img{img_attrs}>"
        # Wrap with link if specified
        if "link" in attrs:
            img_tag = f'<a href="{attrs["link"]}">{img_tag}</a>'
        if caption:
            self._emit(
                f'<figure id="{fig_id}">'
                f"{img_tag}"
                f"<figcaption>{self._inline(caption)}</figcaption>"
                f"</figure>"
            )
        else:
            self._emit(f'<figure id="{fig_id}">{img_tag}</figure>')

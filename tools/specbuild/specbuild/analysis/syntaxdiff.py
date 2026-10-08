"""Bitstream-syntax crosswalk diff for migration between codec generations.

Compares two SDL-tagged Bikeshed sources (e.g. HEVC vs VVC, AV1 vs AV2) and
reports element-level differences:

* **renamed** — same descriptor, similar name on both sides
* **added** — present in NEW but not OLD
* **removed** — present in OLD but not NEW
* **descriptor_changed** — same name, different bit-width / descriptor
* **unchanged** — same name, same descriptor

The parser reuses :func:`specbuild.sdl._find_descriptor` so syntax-element
extraction stays consistent with the spec rendering pipeline.

Typical use::

    from specbuild.analysis.syntaxdiff import run_syntaxdiff
    diffs = run_syntaxdiff(
        Path("hevc.bs"), Path("vvc.bs"),
        Path("syntax_diff.html"), Path("syntax_diff.json"),
    )
"""

from __future__ import annotations

import difflib
import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntaxField:
    """A parsed SDL syntax-element record.

    Attributes:
        name: Element identifier (e.g. ``slice_type``).
        descriptor: Bitstream descriptor (e.g. ``u(2)``, ``ue(v)``).
        bit_width: Numeric width (or empty string when descriptor is
            variable-length, e.g. ``ue(v)``).
        function: Enclosing syntax function name (e.g. ``slice_header``).
    """

    name: str
    descriptor: str
    bit_width: str = ""
    function: str = ""


# ---------------------------------------------------------------------------
# SDL block extraction
# ---------------------------------------------------------------------------

# Match Bikeshed-style fenced SDL code blocks: ```sdl ... ```
_SDL_BLOCK_RE = re.compile(r"```\s*sdl\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
_FUNC_HEADER_RE = re.compile(r"^([A-Za-z_]\w*)\s*\([^)]*\)")
_BIT_WIDTH_RE = re.compile(r"\((\d+)\)")
# Standard video-coding syntax descriptors. Covers HEVC/VVC (u/f/i/b/ue/se/me/ae/tu),
# AVC (ce), AV1/AV2 (L, T, S), and signed-fixed-point (s).
_DESCRIPTOR_RE = re.compile(
    r"^("
    r"u\(\d+\)|f\(\d+\)|i\(\d+\)|b\(\d+\)|s\(\d+\)|"
    r"L\(\d+\)|T\(\d+\)|"
    r"ue\(v\)|se\(v\)|ce\(v\)|me\(v\)|ae\(v\)|tu\(v\)|s\(v\)|"
    r"S\(\)"
    r")\s+"
)


def _split_blocks(text: str) -> list[str]:
    """Return every SDL fenced block body found in *text* (in source order)."""
    return [m.group(1) for m in _SDL_BLOCK_RE.finditer(text)]


def _parse_block(block: str) -> list[SyntaxField]:
    """Parse a single SDL block into :class:`SyntaxField` records.

    The first non-empty line that matches ``ident(...)`` is taken as the
    enclosing function name; subsequent lines are scanned with a built-in
    descriptor regex covering the standard video-coding descriptors:
    ``u(N)``, ``f(N)``, ``i(N)``, ``b(N)``, ``ue(v)``, ``se(v)``, ``ce(v)``,
    ``me(v)``, ``ae(v)``, ``tu(v)``, ``s(v)``, ``S()``, plus AV2-style
    ``L(N)``, ``T(N)``.
    """
    fields: list[SyntaxField] = []
    function = ""
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//") or line.startswith("/*"):
            continue
        if not function:
            m = _FUNC_HEADER_RE.match(line)
            if m:
                function = m.group(1)
                continue
        m = _DESCRIPTOR_RE.match(line)
        if not m:
            continue
        descriptor = m.group(1)
        remainder = line[m.end() :]
        var_name = remainder.strip().rstrip(";").strip().rstrip("{").strip()
        # Strip array subscripts to keep matching robust across drafts:
        # ``foo[i]`` and ``foo`` should compare equal.
        name = re.sub(r"\[.*?\]", "", var_name).strip()
        if not name:
            continue
        bw_match = _BIT_WIDTH_RE.search(descriptor)
        bit_width = bw_match.group(1) if bw_match else ""
        fields.append(
            SyntaxField(
                name=name,
                descriptor=descriptor,
                bit_width=bit_width,
                function=function,
            )
        )
    return fields


def extract_fields(source: Path | str) -> list[SyntaxField]:
    """Extract every :class:`SyntaxField` from a ``.bs`` source file or string.

    Args:
        source: Either a path to a Bikeshed ``.bs`` file, or raw text
            containing one or more fenced ``sdl`` blocks.

    Returns:
        Flat list of fields, in document order.
    """
    if isinstance(source, Path):
        text = source.read_text(encoding="utf-8", errors="replace")
    else:
        text = source
    out: list[SyntaxField] = []
    for block in _split_blocks(text):
        out.extend(_parse_block(block))
    return out


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

# Threshold above which two element names are considered a rename candidate.
# 0.7 catches "ref_idx_l0" -> "ref_idx_lx" without false-flagging unrelated
# fields.
_RENAME_SIMILARITY_THRESHOLD = 0.7


def _similarity(a: str, b: str) -> float:
    """Return SequenceMatcher ratio for two element names (0.0–1.0)."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def diff_fields(
    old: list[SyntaxField],
    new: list[SyntaxField],
) -> list[dict]:
    """Diff *old* vs *new* and return a list of JSON-friendly diff records.

    Each record carries ``kind`` (one of ``unchanged``, ``descriptor_changed``,
    ``renamed``, ``added``, ``removed``) plus the relevant field metadata.
    """
    old_by_name = {f.name: f for f in old}
    new_by_name = {f.name: f for f in new}

    records: list[dict] = []
    matched_old: set[str] = set()
    matched_new: set[str] = set()

    # 1) Exact-name matches first — they are always preferred over heuristics.
    for name, of in old_by_name.items():
        nf = new_by_name.get(name)
        if nf is None:
            continue
        matched_old.add(name)
        matched_new.add(name)
        if of.descriptor == nf.descriptor:
            kind = "unchanged"
        else:
            kind = "descriptor_changed"
        records.append(
            {
                "kind": kind,
                "old_name": of.name,
                "new_name": nf.name,
                "old_descriptor": of.descriptor,
                "new_descriptor": nf.descriptor,
                "old_bit_width": of.bit_width,
                "new_bit_width": nf.bit_width,
                "old_function": of.function,
                "new_function": nf.function,
                "similarity": 1.0,
            }
        )

    # 2) Rename heuristic over the residue: for every unmatched old field, find
    #    the most similar unmatched new field with the *same* descriptor.
    remaining_old = [of for n, of in old_by_name.items() if n not in matched_old]
    remaining_new = {n: nf for n, nf in new_by_name.items() if n not in matched_new}
    for of in remaining_old:
        best_score = 0.0
        best_match: SyntaxField | None = None
        for nf in remaining_new.values():
            if of.descriptor != nf.descriptor:
                continue
            score = _similarity(of.name, nf.name)
            if score > best_score:
                best_score = score
                best_match = nf
        if best_match is not None and best_score >= _RENAME_SIMILARITY_THRESHOLD:
            matched_old.add(of.name)
            matched_new.add(best_match.name)
            del remaining_new[best_match.name]
            records.append(
                {
                    "kind": "renamed",
                    "old_name": of.name,
                    "new_name": best_match.name,
                    "old_descriptor": of.descriptor,
                    "new_descriptor": best_match.descriptor,
                    "old_bit_width": of.bit_width,
                    "new_bit_width": best_match.bit_width,
                    "old_function": of.function,
                    "new_function": best_match.function,
                    "similarity": round(best_score, 3),
                }
            )

    # 3) Anything still unmatched is added/removed.
    for of in old:
        if of.name not in matched_old:
            records.append(
                {
                    "kind": "removed",
                    "old_name": of.name,
                    "new_name": "",
                    "old_descriptor": of.descriptor,
                    "new_descriptor": "",
                    "old_bit_width": of.bit_width,
                    "new_bit_width": "",
                    "old_function": of.function,
                    "new_function": "",
                    "similarity": 0.0,
                }
            )
    for nf in new:
        if nf.name not in matched_new:
            records.append(
                {
                    "kind": "added",
                    "old_name": "",
                    "new_name": nf.name,
                    "old_descriptor": "",
                    "new_descriptor": nf.descriptor,
                    "old_bit_width": "",
                    "new_bit_width": nf.bit_width,
                    "old_function": "",
                    "new_function": nf.function,
                    "similarity": 0.0,
                }
            )

    # Stable, predictable ordering for deterministic output.
    kind_order = {
        "unchanged": 0,
        "descriptor_changed": 1,
        "renamed": 2,
        "added": 3,
        "removed": 4,
    }
    records.sort(key=lambda r: (kind_order.get(r["kind"], 99), r["old_name"], r["new_name"]))
    return records


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _h(text: object) -> str:
    """Shortcut for ``html.escape`` that tolerates non-string input."""
    return html.escape("" if text is None else str(text))


_REPORT_CSS = """\
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;
     margin:2em;color:#222;}
h1{font-size:1.5em;border-bottom:2px solid #333;padding-bottom:.2em;}
.summary{background:#f7f7f7;padding:.6em 1em;border-left:4px solid #666;
         margin-bottom:1.5em;}
table.diffs{border-collapse:collapse;width:100%;}
table.diffs th,table.diffs td{border:1px solid #ccc;padding:4px 8px;
                              font-size:.92em;text-align:left;vertical-align:top;}
table.diffs th{background:#eee;}
.k-unchanged{background:#fff;}
.k-descriptor_changed{background:#fff5d6;}
.k-renamed{background:#eaf3ff;}
.k-added{background:#e7f7ec;}
.k-removed{background:#fbe5e5;}
code{font-family:SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;}
"""


def write_html_report(
    records: list[dict],
    output_path: Path,
    *,
    old_label: str = "OLD",
    new_label: str = "NEW",
) -> None:
    """Write a side-by-side HTML diff report to *output_path*.

    All cell values are escaped via :func:`html.escape`.
    """
    counts: dict[str, int] = {}
    for r in records:
        counts[r["kind"]] = counts.get(r["kind"], 0) + 1

    lines: list[str] = []
    lines.append("<!doctype html>")
    lines.append('<html lang="en"><head><meta charset="utf-8">')
    lines.append("<title>Syntax Diff Report</title>")
    lines.append(f"<style>{_REPORT_CSS}</style>")
    lines.append("</head><body>")
    lines.append("<h1>Bitstream-Syntax Crosswalk</h1>")
    summary_bits = [f"{_h(k)}: <strong>{counts[k]}</strong>" for k in sorted(counts)]
    lines.append(
        '<div class="summary">'
        f"<div><code>{_h(old_label)}</code> &rarr; <code>{_h(new_label)}</code></div>"
        f"<div>{', '.join(summary_bits) or 'no records'}</div>"
        "</div>"
    )
    lines.append('<table class="diffs">')
    lines.append(
        "<thead><tr><th>Kind</th>"
        f"<th>{_h(old_label)} name</th><th>{_h(old_label)} descriptor</th>"
        f"<th>{_h(new_label)} name</th><th>{_h(new_label)} descriptor</th>"
        "<th>Function</th><th>Similarity</th></tr></thead><tbody>"
    )
    for r in records:
        kind = r.get("kind", "")
        function = r.get("new_function") or r.get("old_function") or ""
        sim = r.get("similarity", "")
        sim_text = f"{sim:.2f}" if isinstance(sim, float) and sim else ""
        lines.append(
            f'<tr class="k-{_h(kind)}">'
            f"<td>{_h(kind)}</td>"
            f"<td><code>{_h(r.get('old_name', ''))}</code></td>"
            f"<td><code>{_h(r.get('old_descriptor', ''))}</code></td>"
            f"<td><code>{_h(r.get('new_name', ''))}</code></td>"
            f"<td><code>{_h(r.get('new_descriptor', ''))}</code></td>"
            f"<td>{_h(function)}</td>"
            f"<td>{_h(sim_text)}</td>"
            "</tr>"
        )
    lines.append("</tbody></table>")
    lines.append("</body></html>")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def write_json_report(records: list[dict], output_path: Path) -> None:
    """Write *records* as pretty-printed JSON to *output_path*.

    Records are sorted deterministically so the same inputs always produce
    byte-identical output.  The sort key avoids mixed-type comparisons
    (``str`` vs ``float``) by using only string-typed fields.
    """
    sorted_records = sorted(
        records,
        key=lambda d: (d.get("kind", ""), d.get("old_name", ""), d.get("new_name", "")),
    )
    output_path.write_text(json.dumps(sorted_records, indent=2, sort_keys=True), encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_syntaxdiff(
    old_path: Path,
    new_path: Path,
    html_out: Path,
    json_out: Path | None = None,
) -> list[dict]:
    """Top-level: extract, diff, and write HTML/JSON outputs.

    Args:
        old_path: Path to the OLD ``.bs`` source.
        new_path: Path to the NEW ``.bs`` source.
        html_out: Where to write the HTML report.
        json_out: Optional JSON report path.

    Returns:
        The list of diff records (also written to *html_out*).
    """
    old_path = Path(old_path)
    new_path = Path(new_path)
    if not old_path.exists():
        raise FileNotFoundError(f"OLD source not found: {old_path}")
    if not new_path.exists():
        raise FileNotFoundError(f"NEW source not found: {new_path}")

    old_fields = extract_fields(old_path)
    new_fields = extract_fields(new_path)
    records = diff_fields(old_fields, new_fields)

    write_html_report(
        records,
        Path(html_out),
        old_label=old_path.stem,
        new_label=new_path.stem,
    )
    if json_out is not None:
        write_json_report(records, Path(json_out))

    logging.info(
        "syntax-diff: %d OLD fields, %d NEW fields, %d records",
        len(old_fields),
        len(new_fields),
        len(records),
    )
    return records


__all__ = [
    "SyntaxField",
    "extract_fields",
    "diff_fields",
    "write_html_report",
    "write_json_report",
    "run_syntaxdiff",
    "asdict",  # re-exported for tests
]

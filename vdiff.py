#!/usr/bin/env python3
"""Visual diff of rendered bikeshed spec between two git refs or a ref and the working tree.

Uses lxml.html.diff to produce a content-oriented inline diff that preserves the
spec's own styling and highlights additions/deletions with <ins>/<del> tags.

Tables are diffed separately: unchanged tables pass through as-is, while changed
tables are shown as before/after blocks to avoid garbled output.

Usage:
  python vdiff.py              # Diff current vs main
  python vdiff.py other-branch # Diff current vs other-branch
  python vdiff.py main --head-ref HEAD --ci -o diff.html  # CI mode

Requirements:
  pip install lxml
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from lxml import html
from lxml.html import tostring
from lxml.html.diff import htmldiff

from compile import SOURCE, COMPILED, HTML_OUT, convert_sdl_blocks


class VDiffError(Exception):
    """Raised when vdiff encounters a non-recoverable error."""


DIFF_STYLES = """
<style>
ins {
    background-color: #d4edda;
    text-decoration: none;
    padding: 1px 3px;
    border-radius: 3px;
}
del {
    background-color: #f8d7da;
    text-decoration: line-through;
    padding: 1px 3px;
    border-radius: 3px;
}
ins img { border: 3px solid #28a745; }
del img { border: 3px solid #dc3545; }

.table-diff-block {
    border: 2px solid #856404;
    border-radius: 6px;
    margin: 1.5em 0;
    overflow: hidden;
}
.table-diff-block summary {
    background: #fff3cd;
    padding: 8px 14px;
    cursor: pointer;
    font-family: system-ui, sans-serif;
    font-size: 0.9em;
    font-weight: 600;
    color: #856404;
}
.table-diff-side {
    padding: 12px;
}
.table-diff-side.old-side {
    background: #fff5f5;
    border-bottom: 1px dashed #ccc;
}
.table-diff-side.new-side {
    background: #f0fff4;
}
.table-diff-label {
    font-family: system-ui, sans-serif;
    font-size: 0.8em;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}
.table-diff-label.old-label { color: #dc3545; }
.table-diff-label.new-label { color: #28a745; }

#diff-nav {
    position: sticky;
    top: 0;
    z-index: 1000;
    background: #343a40;
    padding: 6px 16px;
    font-family: system-ui, sans-serif;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 4px;
    flex-wrap: wrap;
    box-shadow: 0 2px 4px rgba(0,0,0,0.15);
}
#diff-nav .diff-nav-label {
    color: #adb5bd;
    margin-right: 6px;
    white-space: nowrap;
}
#diff-nav a {
    display: inline-block;
    min-width: 24px;
    height: 24px;
    line-height: 24px;
    text-align: center;
    border-radius: 4px;
    background: #495057;
    color: #f8f9fa;
    text-decoration: none;
    font-weight: 600;
    font-size: 12px;
    padding: 0 5px;
    transition: background 0.15s;
}
#diff-nav a:hover { background: #6c757d; }
#diff-nav a.active { background: #0d6efd; color: #fff; }
.diff-change-highlight {
    outline: 3px solid #0d6efd;
    outline-offset: 2px;
    border-radius: 3px;
}
</style>
"""

DIFF_NAV_SCRIPT = """
<script>
(function() {
  // Collect all change elements: ins, del, and table-diff-block containers
  var changeEls = document.querySelectorAll('ins, del, .table-diff-block');
  if (!changeEls.length) return;

  // Group nearby changes (within 80px vertically) into single change locations
  var groups = [];
  var MERGE_DISTANCE = 80; // px
  changeEls.forEach(function(el) {
    // Skip elements inside the nav bar or legend
    if (el.closest('#diff-nav') || el.closest('[data-fill-with]')) return;
    var rect = el.getBoundingClientRect();
    var absTop = rect.top + window.scrollY;
    if (groups.length && absTop - groups[groups.length - 1].bottom < MERGE_DISTANCE) {
      var g = groups[groups.length - 1];
      g.bottom = Math.max(g.bottom, absTop + rect.height);
      g.elements.push(el);
    } else {
      groups.push({ top: absTop, bottom: absTop + rect.height, elements: [el] });
    }
  });

  if (!groups.length) return;

  // Add anchor ids to the first element of each group
  groups.forEach(function(g, i) {
    var anchor = g.elements[0];
    if (!anchor.id) anchor.id = 'diff-change-' + (i + 1);
    g.id = anchor.id;
  });

  // Build the nav bar
  var nav = document.createElement('div');
  nav.id = 'diff-nav';
  var label = document.createElement('span');
  label.className = 'diff-nav-label';
  label.textContent = 'Changes (' + groups.length + '):';
  nav.appendChild(label);

  var currentHighlight = null;
  groups.forEach(function(g, i) {
    var a = document.createElement('a');
    a.href = '#' + g.id;
    a.textContent = i + 1;
    a.title = 'Go to change ' + (i + 1);
    a.addEventListener('click', function(e) {
      e.preventDefault();
      // Remove previous highlight
      if (currentHighlight) currentHighlight.classList.remove('diff-change-highlight');
      // Scroll and highlight
      var target = document.getElementById(g.id);
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      target.classList.add('diff-change-highlight');
      currentHighlight = target;
      // Update active link
      nav.querySelectorAll('a').forEach(function(l) { l.classList.remove('active'); });
      a.classList.add('active');
      // Remove highlight after a delay
      setTimeout(function() { target.classList.remove('diff-change-highlight'); }, 2000);
    });
    nav.appendChild(a);
  });

  document.body.insertBefore(nav, document.body.firstChild);
})();
</script>
"""

# Matches <table ...>...</table> (outermost tables only via non-greedy + no nesting)
# We use a regex on serialized HTML fragments, which is safe here because lxml
# already produced well-formed output.
_TABLE_RE = re.compile(
    r"(<(?:div\s+class=\"sdl-syntax-wrapper\">.*?</div>|table[\s>].*?</table>))",
    re.DOTALL,
)
_IMG_RE = re.compile(
    r"(<(?:figure[\s>].*?</figure>|img\s[^>]*>))",
    re.DOTALL,
)

# Sentinel prefixes used to replace tables/images with placeholders before diffing.
# Old and new sides use distinct prefixes so they survive htmldiff without collision.
_OLD_TABLE_PLACEHOLDER = "\u200b\u200bOLD_TABLE_PLACEHOLDER_{}\u200b\u200b"
_NEW_TABLE_PLACEHOLDER = "\u200b\u200bNEW_TABLE_PLACEHOLDER_{}\u200b\u200b"
_OLD_IMG_PLACEHOLDER = "\u200b\u200bOLD_IMG_PLACEHOLDER_{}\u200b\u200b"
_NEW_IMG_PLACEHOLDER = "\u200b\u200bNEW_IMG_PLACEHOLDER_{}\u200b\u200b"


def _split_by_pattern(
    body_html: str, pattern: re.Pattern
) -> tuple[list[str], list[str]]:
    """Split body HTML into segments and matched elements.

    Returns (segments, elements) where segments[i] is content between matches
    and elements[i] is the i-th matched element's HTML.
    len(segments) == len(elements) + 1.
    """
    elements: list[str] = []
    parts: list[str] = []
    last_end = 0
    for m in pattern.finditer(body_html):
        parts.append(body_html[last_end : m.start()])
        elements.append(m.group(1))
        last_end = m.end()
    parts.append(body_html[last_end:])
    return parts, elements


def _signature_of(element_html: str) -> str:
    """Get a comparable signature of an HTML element.

    For tables: plain text content.
    For images/figures: the src attribute(s) + alt text.
    """
    doc = html.fromstring(f"<div>{element_html}</div>")
    # Collect image srcs if any
    srcs = [img.get("src", "") for img in doc.iter("img")]
    if srcs:
        alts = [img.get("alt", "") for img in doc.iter("img")]
        text = (doc.text_content() or "").strip()
        return f"{'|'.join(srcs)}|{'|'.join(alts)}|{text}"
    return (doc.text_content() or "").strip()


def _match_elements(
    old_elements: list[str], new_elements: list[str]
) -> list[tuple[str | None, str | None]]:
    """Match old and new elements by signature, returning aligned pairs.

    Returns a list of (old_element, new_element) tuples. Either side can be None
    for added/removed elements.

    Matching strategy:
      1. Exact signature match (unchanged elements).
      2. Positional match for remaining unmatched elements at the same index
         (modified elements that kept their position).
      3. Anything still unmatched is treated as added or removed.
    """
    old_sigs = {i: _signature_of(el) for i, el in enumerate(old_elements)}
    new_sigs = {i: _signature_of(el) for i, el in enumerate(new_elements)}

    matched_old: set[int] = set()
    matched_new: set[int] = set()

    # First pass: exact signature match
    new_to_old: dict[int, int] = {}
    for ni, nsig in new_sigs.items():
        for oi, osig in old_sigs.items():
            if oi not in matched_old and nsig == osig:
                new_to_old[ni] = oi
                matched_old.add(oi)
                matched_new.add(ni)
                break

    # Second pass: positional match for remaining unmatched elements.
    # Tables generally keep their order, so old[i] ↔ new[i] when both are
    # unmatched is very likely the same table with modified content.
    for i in range(min(len(old_elements), len(new_elements))):
        if i not in matched_old and i not in matched_new:
            new_to_old[i] = i
            matched_old.add(i)
            matched_new.add(i)

    # Collect unmatched old elements (removals)
    unmatched_old = [i for i in range(len(old_elements)) if i not in matched_old]

    # Build result: interleave removals and matched/added elements
    pairs: list[tuple[str | None, str | None]] = []
    removal_idx = 0
    for ni in range(len(new_elements)):
        if ni in new_to_old:
            # Emit any removals that came before this match
            oi = new_to_old[ni]
            while removal_idx < len(unmatched_old) and unmatched_old[removal_idx] < oi:
                pairs.append((old_elements[unmatched_old[removal_idx]], None))
                removal_idx += 1
            pairs.append((old_elements[oi], new_elements[ni]))
        else:
            pairs.append((None, new_elements[ni]))

    # Remaining removals
    while removal_idx < len(unmatched_old):
        pairs.append((old_elements[unmatched_old[removal_idx]], None))
        removal_idx += 1

    return pairs


def _make_diff_block(old_el: str, new_el: str, label: str = "Table") -> str:
    """Render a before/after block for a changed element."""
    return (
        '<details class="table-diff-block" open>'
        f"<summary>{label} changed (click to collapse)</summary>"
        '<div class="table-diff-side old-side">'
        '<div class="table-diff-label old-label">Removed</div>'
        f"{old_el}"
        "</div>"
        '<div class="table-diff-side new-side">'
        '<div class="table-diff-label new-label">Added</div>'
        f"{new_el}"
        "</div>"
        "</details>"
    )


def render_to_html(bs_content: str, workdir: Path) -> str:
    """Render bikeshed source text to HTML, returning the HTML string."""
    compiled = workdir / COMPILED.name
    output = workdir / HTML_OUT.name

    converted = convert_sdl_blocks(bs_content)
    compiled.write_text(converted, encoding="utf-8")
    try:
        result = subprocess.run(
            ["bikeshed", "spec", str(compiled), str(output)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            raise VDiffError("bikeshed failed")
        return output.read_text(encoding="utf-8")
    finally:
        compiled.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


def get_source(ref: str) -> str:
    """Get index.bs content from a git ref."""
    result = subprocess.run(
        ["git", "show", f"{ref}:{SOURCE}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise VDiffError(
            f"Failed to read {SOURCE} from {ref}:\n{result.stderr.strip()}"
        )
    return result.stdout


def get_current_source() -> str:
    """Get index.bs content from the working tree."""
    return SOURCE.read_text(encoding="utf-8")


def extract_body(raw_html: str) -> str:
    """Extract the inner HTML of <body> from a full HTML document."""
    doc = html.fromstring(raw_html)
    body = doc.find(".//body")
    if body is None:
        return raw_html
    parts = []
    if body.text:
        parts.append(body.text)
    for child in body:
        parts.append(tostring(child, encoding="unicode"))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def extract_head(raw_html: str) -> str:
    """Extract the full <head> element (including tag) from an HTML document."""
    doc = html.fromstring(raw_html)
    head = doc.find(".//head")
    if head is None:
        return ""
    return tostring(head, encoding="unicode")


def _placeholder_regex(placeholder_text: str) -> re.Pattern:
    """Build a regex that matches a placeholder even when wrapped in diff tags.

    htmldiff may wrap placeholders in <ins>, <del>, or <span> tags either
    around or inside the <p>.  We handle both patterns:
      - <ins><p>PLACEHOLDER</p></ins>   (tags outside <p>)
      - <p><ins>PLACEHOLDER</ins></p>   (tags inside <p>)
      - <p>PLACEHOLDER</p>              (no wrapping)
    """
    escaped = re.escape(placeholder_text)
    _DIFF_TAG_OPEN = r"(?:<(?:ins|del|span)[^>]*>\s*)*"
    _DIFF_TAG_CLOSE = r"(?:\s*</(?:ins|del|span)>)*"
    return re.compile(
        _DIFF_TAG_OPEN
        + r"<p>\s*"
        + _DIFF_TAG_OPEN
        + escaped
        + _DIFF_TAG_CLOSE
        + r"\s*</p>"
        + _DIFF_TAG_CLOSE,
        re.DOTALL,
    )


def _restore_elements(
    diffed: str,
    old_elements: list[str],
    new_elements: list[str],
    old_placeholder_template: str,
    new_placeholder_template: str,
    label: str,
) -> str:
    """Restore placeholders with matched element pairs."""
    pairs = _match_elements(old_elements, new_elements)
    result = diffed

    # Remove old-side placeholders (htmldiff typically wraps these in <del>)
    for i in range(len(old_elements)):
        pat = _placeholder_regex(old_placeholder_template.format(i))
        result = pat.sub("", result, count=1)

    # Replace new-side placeholders with the appropriate content
    for i in range(len(new_elements)):
        pat = _placeholder_regex(new_placeholder_template.format(i))
        # Find the corresponding pair for this new element
        replacement = ""
        for old_el, new_el in pairs:
            if new_el is not None and new_el == new_elements[i]:
                if old_el is None:
                    replacement = (
                        f'<div class="table-diff-block" style="border-color:#28a745">'
                        f'<div class="table-diff-side new-side">'
                        f'<div class="table-diff-label new-label">Added {label.lower()}</div>'
                        f"{new_el}</div></div>"
                    )
                elif _signature_of(old_el) == _signature_of(new_el):
                    replacement = new_el
                else:
                    replacement = _make_diff_block(old_el, new_el, label)
                break
        result = pat.sub(replacement, result, count=1)

    # Append removed elements at end
    removed_html = ""
    for old_el, new_el in pairs:
        if new_el is None and old_el is not None:
            removed_html += (
                f'<div class="table-diff-block" style="border-color:#dc3545">'
                f'<div class="table-diff-side old-side">'
                f'<div class="table-diff-label old-label">Removed {label.lower()}</div>'
                f"{old_el}</div></div>"
            )
    result += removed_html

    return result


def make_visual_diff(
    base_html: str, current_html: str, base_ref: str, head_label: str
) -> str:
    """Produce a visual inline diff, handling tables as before/after blocks."""
    base_body = extract_body(base_html)
    current_body = extract_body(current_html)

    # Pull tables and images out of both bodies so htmldiff doesn't mangle them.
    # Process tables first, then images within the remaining segments.
    base_segments, base_tables = _split_by_pattern(base_body, _TABLE_RE)
    cur_segments, cur_tables = _split_by_pattern(current_body, _TABLE_RE)

    # Replace tables with distinct old/new placeholders
    base_prose = ""
    for i, seg in enumerate(base_segments):
        base_prose += seg
        if i < len(base_tables):
            base_prose += f"<p>{_OLD_TABLE_PLACEHOLDER.format(i)}</p>"

    cur_prose = ""
    for i, seg in enumerate(cur_segments):
        cur_prose += seg
        if i < len(cur_tables):
            cur_prose += f"<p>{_NEW_TABLE_PLACEHOLDER.format(i)}</p>"

    # Now pull images out of the table-free prose
    base_parts, base_images = _split_by_pattern(base_prose, _IMG_RE)
    cur_parts, cur_images = _split_by_pattern(cur_prose, _IMG_RE)

    base_prose = ""
    for i, seg in enumerate(base_parts):
        base_prose += seg
        if i < len(base_images):
            base_prose += f"<p>{_OLD_IMG_PLACEHOLDER.format(i)}</p>"

    cur_prose = ""
    for i, seg in enumerate(cur_parts):
        cur_prose += seg
        if i < len(cur_images):
            cur_prose += f"<p>{_NEW_IMG_PLACEHOLDER.format(i)}</p>"

    # Diff only the prose portions
    diffed = htmldiff(base_prose, cur_prose)

    # Restore tables using content-based matching
    diffed = _restore_elements(
        diffed, base_tables, cur_tables,
        _OLD_TABLE_PLACEHOLDER, _NEW_TABLE_PLACEHOLDER, "Table",
    )

    # Restore images using content-based matching
    diffed = _restore_elements(
        diffed, base_images, cur_images,
        _OLD_IMG_PLACEHOLDER, _NEW_IMG_PLACEHOLDER, "Image",
    )

    # Clean up any leftover placeholders (old or new side, with optional diff-tag wrapping)
    diffed = re.sub(
        r"(?:<(?:ins|del|span)[^>]*>\s*)*"
        r"<p>\s*"
        r"(?:<(?:ins|del|span)[^>]*>\s*)*"
        r"\u200b\u200b(?:OLD|NEW)_(?:TABLE|IMG)_PLACEHOLDER_\d+\u200b\u200b"
        r"(?:\s*</(?:ins|del|span)>)*"
        r"\s*</p>"
        r"(?:\s*</(?:ins|del|span)>)*",
        "", diffed,
    )

    head = extract_head(current_html)
    head = head.replace("</head>", f"{DIFF_STYLES}\n</head>")

    return f"""<!DOCTYPE html>
<html>
{head}
<body>
<div style="background: #f1f3f5; padding: 8px 16px; margin-bottom: 16px; border-radius: 4px; font-family: system-ui, sans-serif; font-size: 14px;">
  Visual diff: <code>{base_ref}</code> &rarr; <code>{head_label}</code> &mdash;
  <span style="background:#d4edda; padding:2px 6px; border-radius:3px;">additions</span>
  <span style="background:#f8d7da; padding:2px 6px; border-radius:3px; text-decoration:line-through;">deletions</span>
  <span style="background:#fff3cd; padding:2px 6px; border-radius:3px; border:1px solid #856404;">table changes</span>
</div>
{diffed}
{DIFF_NAV_SCRIPT}
</body>
</html>
"""


def _write_summary(message: str) -> None:
    """Write a message to $GITHUB_STEP_SUMMARY if the env var is set."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visual HTML diff of rendered spec vs a base branch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "base",
        nargs="?",
        default="main",
        help="Base git ref to compare against (default: main)",
    )
    parser.add_argument(
        "--head-ref",
        default=None,
        help="Head git ref (default: use working tree)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: write summary to $GITHUB_STEP_SUMMARY, suppress interactive output, always exit 0",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="diff.html",
        help="Output HTML file (default: diff.html)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save intermediate base and current rendered HTML files alongside the output",
    )
    args = parser.parse_args()

    try:
        # Guard for missing bikeshed
        if not shutil.which("bikeshed"):
            raise VDiffError(
                "bikeshed not found on PATH. Install with: pip install bikeshed"
            )

        if not args.ci:
            print(f"Reading {SOURCE} from {args.base}...")
        base_source = get_source(args.base)

        if args.head_ref:
            head_label = args.head_ref
            if not args.ci:
                print(f"Reading {SOURCE} from {args.head_ref}...")
            current_source = get_source(args.head_ref)
        else:
            head_label = "working tree"
            if not args.ci:
                print(f"Reading {SOURCE} from working tree...")
            current_source = get_current_source()

        # Early exit if spec unchanged
        if base_source == current_source:
            msg = f"No changes to {SOURCE} between {args.base} and {head_label}."
            if args.ci:
                _write_summary(f"### Visual Diff\n{msg}")
                Path(args.output).write_text(
                    f"<!DOCTYPE html><html><body><p>{msg}</p></body></html>",
                    encoding="utf-8",
                )
            else:
                print(msg)
            return

        # Symlink images/ into the temp dir so relative paths resolve
        repo_images = Path("images")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            if repo_images.is_dir():
                os.symlink(repo_images.resolve(), tmpdir / "images")

            if not args.ci:
                print(f"Rendering {SOURCE} from {args.base}...")
            base_html = render_to_html(base_source, tmpdir)

            if not args.ci:
                print(
                    f"Rendering {SOURCE} from {head_label}..."
                )
            current_html = render_to_html(current_source, tmpdir)

        if args.debug:
            out = Path(args.output)
            base_out = out.with_stem(out.stem + "_base")
            cur_out = out.with_stem(out.stem + "_current")
            base_out.write_text(base_html, encoding="utf-8")
            cur_out.write_text(current_html, encoding="utf-8")
            if not args.ci:
                print(f"Debug: saved {base_out} and {cur_out}")

        if not args.ci:
            print("Generating visual diff...")
        diff_html = make_visual_diff(base_html, current_html, args.base, head_label)

        out = Path(args.output)
        out.write_text(diff_html, encoding="utf-8")

        if args.ci:
            _write_summary(
                f"### Visual Diff\n"
                f"Visual diff generated between `{args.base}` and `{head_label}`. "
                f"See the `diff.html` artifact."
            )
        else:
            print(f"Diff written to {out}")

    except VDiffError as e:
        if args.ci:
            _write_summary(f"### Visual Diff\n:warning: {e}")
            print(f"vdiff warning: {e}", file=sys.stderr)
            Path(args.output).write_text(
                f"<!DOCTYPE html><html><body><p>Visual diff unavailable: {e}</p></body></html>",
                encoding="utf-8",
            )
        else:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

"""
Preprocess HTML files for diffing by removing elements that cause false differences.

This script removes or normalizes:
1. Bikeshed line number markers (bs-line-number)
2. data-original-syntax attributes from SDL tables (contains line numbers)
3. Unique IDs that may change between compilations
4. Timestamp/date information that varies
5. SDL table structure (indentation styles, tooltip attributes)
6. Code block formatting (auto-indent whitespace, line anchor wrappers)

The goal is to make the HTML diff focus on actual content changes rather than
artifacts of the compilation process.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

# Route logging through the shared colored formatter when this script is
# invoked as a subprocess of compile.py.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
from specbuild.logsetup import setup_logging  # noqa: E402
from specbuild.utils import read_html  # noqa: E402

setup_logging("INFO")


def preprocess_html_for_diff(html_path: Path, output_path: Path) -> None:
    """
    Preprocess HTML file for diffing by removing elements that cause false differences.

    Args:
        html_path (Path): Input HTML file path
        output_path (Path): Output HTML file path
    """
    logging.info(f"Preprocessing {html_path.name} for diff")

    # Use a spec-compliant parser (via read_html's lxml/html5lib fallback
    # chain) rather than the stdlib html.parser. Bikeshed emits bibliography
    # entries with implicitly-closed <dt>/<dd> tags (relying on the next
    # sibling to close the previous one); html.parser doesn't implement that
    # HTML5 auto-closing rule and instead nests them indefinitely
    # (dt > dd > dt > dd > ...), producing a DOM that diffs as "changed" even
    # when the reference text is identical on both sides.
    soup = read_html(html_path)

    changes_made = 0

    # 1. Remove Back-to-TOC navigation links — these are navigation aids
    # injected by SpecBuild that are not part of the spec content and would
    # cause false-positive diffs.
    back_to_toc_removed = 0
    for elem in soup.find_all(class_="back-to-toc-wrapper"):
        elem.decompose()
        back_to_toc_removed += 1
    logging.debug(f"  Removed {back_to_toc_removed} back-to-toc links")

    # 2. Remove data-original-syntax attributes from SDL tables
    # These contain the original syntax with line number markers that change
    for table in soup.find_all("table", class_="sdl-syntax-table"):
        if table.has_attr("data-original-syntax"):
            del table["data-original-syntax"]
            changes_made += 1

    logging.debug(f"  Removed data-original-syntax from {changes_made} SDL tables")

    # 2. Remove bs-line-number attributes from all elements
    # These are Bikeshed line numbers that change even when content doesn't
    bs_line_changes = 0
    for elem in soup.find_all(attrs={"bs-line-number": True}):
        del elem["bs-line-number"]
        bs_line_changes += 1

    logging.info(f"  Removed bs-line-number from {bs_line_changes} elements")

    # 3. Remove or normalize script content that contains timestamps/hashes
    # Look for scripts that might contain build timestamps
    script_changes = 0
    for script in soup.find_all("script"):
        script_content = script.get_text()
        if script_content:
            # Remove any timestamp-like patterns (ISO dates, Unix timestamps, etc.)
            # This is a conservative approach - only normalize obvious timestamps
            normalized_content = re.sub(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", "TIMESTAMP", script_content
            )
            normalized_content = re.sub(r"timestamp:\s*\d+", "timestamp: 0", normalized_content)
            if normalized_content != script_content:
                # Replace the entire script content with the normalized text,
                # handling scripts that may have multiple text nodes or mixed content.
                script.clear()
                script.append(normalized_content)
                script_changes += 1

    logging.info(f"  Normalized {script_changes} script tags")

    # 4. Normalize date/time stamps in the document
    # The <time> element in the header changes with every build
    time_changes = 0
    for time_elem in soup.find_all("time", class_="dt-updated"):
        if time_elem.get("datetime"):
            time_elem["datetime"] = "2000-01-01"  # Normalize to fixed date
        if time_elem.string:
            time_elem.string = "1 January 2000"  # Normalize display text
        time_changes += 1

    logging.info(f"  Normalized {time_changes} time elements")

    # 5. Normalize Bikeshed generator version in meta tags
    # The generator meta tag includes Bikeshed version and timestamp
    meta_changes = 0
    for meta in soup.find_all("meta", attrs={"name": "generator"}):
        if meta.get("content") and "Bikeshed" in meta.get("content", ""):
            meta["content"] = "Bikeshed version NORMALIZED"
            meta_changes += 1

    logging.info(f"  Normalized {meta_changes} generator meta tags")

    # 6. Normalize version/commit information in document metadata
    # The <dd> after <dt>Version: contains branch and commit SHA
    version_changes = 0
    for dt in soup.find_all("dt"):
        if dt.string and "Version:" in dt.string:
            # Find the next <dd> sibling
            dd = dt.find_next_sibling("dd")
            if dd:
                # Replace content with normalized version
                dd.clear()
                dd.string = "branch: NORMALIZED"
                version_changes += 1

    logging.info(f"  Normalized {version_changes} version metadata entries")

    # 7. Remove unique element IDs that are auto-generated and may vary
    # Keep semantic IDs (section anchors) but remove generated ones
    # This is conservative - only remove IDs that look auto-generated
    id_changes = 0
    for elem in soup.find_all(id=True):
        elem_id = elem.get("id")
        # Remove IDs that look like auto-generated hashes or GUIDs
        if re.match(r"^[a-f0-9]{8,}$", elem_id) or re.match(r"^gen-\d+$", elem_id):
            del elem["id"]
            id_changes += 1

    logging.info(f"  Removed {id_changes} auto-generated IDs")

    # 7b. Unwrap RFC 2119/8174 keyword spans (highlight_keywords enhancement).
    # The <span class="rfc-keyword"> wrappers are injected only into the enhanced
    # build, never the bare anchor, so these one-sided insertions desync the
    # word-level diff and cascade into false differences elsewhere. Unwrapping
    # restores the plain keyword text so both sides match. This must run
    # *before* step 8's whitespace normalization: a keyword span splits its
    # surrounding text into sibling text nodes (e.g. "SHALL NOT" + " (the "),
    # and normalizing those nodes in isolation would strip the leading space
    # off " (the " as if it were edge whitespace, silently eating the space
    # between the keyword and what follows once the span is later unwrapped.
    rfc_keyword_changes = 0
    for span in soup.find_all("span", class_="rfc-keyword"):
        span.unwrap()
        rfc_keyword_changes += 1

    logging.info(f"  Unwrapped {rfc_keyword_changes} rfc-keyword spans")

    # 8. Normalize whitespace in table cells and definition list entries to
    # avoid spurious diffs. SDL tables can have different whitespace that
    # doesn't affect content, and reference entries (<dt>/<dd>, e.g. "[AV2]"
    # and its citation) pick up trailing newlines in the bare anchor but not
    # the enhanced build after HTML reserialization — whitespace-only
    # differences htmldiff would otherwise flag.
    #
    # This must treat the cell's text as one continuous stream, not each text
    # node in isolation: inline markup (an rfc-keyword <span>, a bikeshed
    # <a> link) can split one sentence into several sibling text nodes, and a
    # space that sits *between* two words can end up as the trailing/leading
    # edge of one of those fragments (e.g. "SHALL NOT" + " (the "). Trimming
    # every node's edges independently would delete that space even though
    # it's internal to the sentence — only the cell's true outer edges should
    # be stripped; whitespace *within* a node collapses to a single space but
    # keeps at least one space if it was there, so word boundaries introduced
    # by markup survive.
    cell_changes = 0
    for cell in soup.find_all(["td", "th", "dt", "dd"]):
        text_nodes = cell.find_all(string=True)
        if not text_nodes:
            continue
        cell_modified = False
        for text_node in text_nodes:
            original_text = str(text_node)
            collapsed_text = re.sub(r"\s+", " ", original_text)
            if collapsed_text != original_text:
                text_node.replace_with(collapsed_text)
                cell_modified = True
        text_nodes = cell.find_all(string=True)
        if len(text_nodes) == 1:
            original_text = str(text_nodes[0])
            stripped_text = original_text.strip()
            if stripped_text != original_text:
                text_nodes[0].replace_with(stripped_text)
                cell_modified = True
        else:
            first_text = str(text_nodes[0])
            stripped_first = first_text.lstrip()
            if stripped_first != first_text:
                text_nodes[0].replace_with(stripped_first)
                cell_modified = True
            last_text = str(text_nodes[-1])
            stripped_last = last_text.rstrip()
            if stripped_last != last_text:
                text_nodes[-1].replace_with(stripped_last)
                cell_modified = True
        if cell_modified:
            cell_changes += 1

    logging.info(f"  Normalized whitespace in {cell_changes} table cells")

    # 8b. Inject CSS overrides for the diff view. These live in <head> so
    # htmldiff preserves them into diff.html.
    #  * Bikeshed sets `[data-link-type=biblio] { white-space: pre }`; combined
    #    with htmldiff's word-per-line output (which leaves newlines inside
    #    citation links), references render one token per line. Force normal.
    #  * Bikeshed's in-spec sidebar TOC (`#toc`) and its reserved left padding
    #    (`body:not(.toc-inline) { padding-left: 29em }`, applied above 78em)
    #    are redundant in the diff viewer (it has its own TOC) and, in a
    #    full-width single pane, shove the spec content far to the right. Hide
    #    the TOC and drop the padding so the content fills the pane.
    diff_css = (
        "[data-link-type=biblio]{white-space:normal !important;}"
        "#toc{display:none !important;}"
        "body:not(.toc-inline){padding-left:1.5em !important;}"
    )
    override_changes = 0
    head = soup.find("head")
    if head is not None:
        override = soup.new_tag("style", id="diff-view-css-overrides")
        override.string = diff_css
        head.append(override)
        override_changes = 1

    logging.info(f"  Injected diff-view CSS overrides: {override_changes}")

    # 9. Normalize SDL table inline indentation styles
    # The padding-left value can vary between builds depending on source
    # whitespace changes that don't affect semantic content.
    sdl_indent_changes = 0
    for span in soup.find_all("span", style=True):
        parent_td = span.find_parent("td")
        if parent_td and any(
            cls in parent_td.get("class", []) for cls in ("sdl-code", "sdl-var-with-descriptor")
        ):
            style = span.get("style", "")
            # Normalize padding-left to a canonical value
            normalized = re.sub(
                r"padding-left:\s*[\d.]+em",
                "padding-left: 0em",
                style,
            )
            if normalized != style:
                span["style"] = normalized
                sdl_indent_changes += 1

    logging.info(f"  Normalized indentation in {sdl_indent_changes} SDL table cells")

    # 10. Remove SDL tooltip attributes (added by post-processing, not content)
    tooltip_changes = 0
    for elem in soup.find_all(attrs={"data-tooltip": True}):
        del elem["data-tooltip"]
        tooltip_changes += 1
    for elem in soup.find_all(class_="has-syntax-tooltip"):
        elem["class"] = [c for c in elem["class"] if c != "has-syntax-tooltip"]
        tooltip_changes += 1

    logging.info(f"  Removed {tooltip_changes} tooltip attributes")

    # 11. Unwrap line-anchor spans in code blocks
    # Line anchors (<span class="code-line">) are a presentation feature;
    # unwrapping them exposes the raw code text for semantic diffing.
    line_anchor_changes = 0
    for span in soup.find_all("span", class_="code-line"):
        span.unwrap()
        line_anchor_changes += 1
    # Remove the has-line-anchors class from <pre> elements
    for pre in soup.find_all("pre", class_="has-line-anchors"):
        pre["class"] = [c for c in pre["class"] if c != "has-line-anchors"]

    logging.info(f"  Unwrapped {line_anchor_changes} line-anchor spans")

    # 11b. Unwrap Bikeshed syntax-highlight tokens (<c- ...> elements) in code.
    # Bikeshed wraps each highlighted token as e.g. `<c- b="">unsigned</c->`,
    # but the diff anchor is built with the highlight fence stripped
    # (hack_bs_for_diff), so its code is plain text with no tokens. htmldiff
    # cannot align tokenized-vs-plain code, so it misses real code changes and
    # emits spurious whitespace diffs. Unwrapping the tokens on both sides
    # reduces code to plain text so genuine edits (e.g. a changed field width
    # or an added struct member) diff correctly. The diff view loses code
    # colouring, but the Current pane (not preprocessed) keeps it.
    c_token_changes = 0
    for token in soup.find_all("c-"):
        token.unwrap()
        c_token_changes += 1

    logging.info(f"  Unwrapped {c_token_changes} syntax-highlight tokens")

    # 12. Normalize code block leading whitespace
    # Auto-indent changes indentation but not semantic content.
    # Collapse all leading whitespace in code lines to a single space.
    code_ws_changes = 0
    for pre in soup.find_all("pre", class_="highlight"):
        for text_node in pre.find_all(string=True):
            original = str(text_node)
            # Only normalize leading whitespace on lines, not all whitespace
            lines = original.split("\n")
            normalized_lines = []
            modified = False
            for line in lines:
                stripped = line.lstrip()
                if stripped and line != stripped:
                    normalized_lines.append(stripped)
                    modified = True
                else:
                    normalized_lines.append(line)
            if modified:
                text_node.replace_with("\n".join(normalized_lines))
                code_ws_changes += 1

    logging.info(f"  Normalized whitespace in {code_ws_changes} code block text nodes")

    # 13. Remove injected style/script blocks that are build artifacts.
    # SpecBuild enhancements inject <style>/<script> blocks whose id ends in
    # "-css"/"-js" (e.g. rfc-keyword-css, page-numbering-css, content-width-css).
    # They exist only in the enhanced build, not the bare anchor, so strip them
    # from both sides. Matching by suffix (rather than a fixed list) keeps new
    # enhancements from reintroducing false diffs.
    artifact_changes = 0
    for tag in soup.find_all(["style", "script"], id=True):
        tid = tag.get("id", "")
        if tid.endswith("-css") or tid.endswith("-js"):
            tag.decompose()
            artifact_changes += 1

    logging.info(f"  Removed {artifact_changes} injected style/script blocks")

    # Write output
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    total_changes = (
        changes_made
        + bs_line_changes
        + script_changes
        + time_changes
        + meta_changes
        + version_changes
        + id_changes
        + cell_changes
        + override_changes
        + sdl_indent_changes
        + tooltip_changes
        + rfc_keyword_changes
        + line_anchor_changes
        + c_token_changes
        + code_ws_changes
        + artifact_changes
    )
    logging.info(f"  Total changes: {total_changes}")
    logging.info(f"Preprocessed HTML written to {output_path.name}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_html> <output_html>")
        print()
        print("Preprocess HTML file for diffing by removing elements that cause false differences.")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if not input_path.exists():
        logging.error(f"Input file not found: {input_path}")
        sys.exit(1)

    try:
        preprocess_html_for_diff(input_path, output_path)
    except (OSError, PermissionError) as e:
        logging.error(f"File I/O error while processing HTML: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error while preprocessing HTML: {e}")
        sys.exit(1)

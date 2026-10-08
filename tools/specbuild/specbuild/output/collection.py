"""Multi-part standard collection compilation.

Merges multiple compiled HTML specification parts into a single navigable
document with a unified table of contents, shared deduplicated bibliography,
cross-part reference resolution, and a sidebar for part navigation.

This is the "collection" concept from Metanorma — a single HTML view that
spans all parts of a multi-part standard (e.g., all 40 parts of ISO 14496).

Usage::

    python compile.py --compile-collection
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Tag

if TYPE_CHECKING:
    from specbuild.multipart import MultiPartConfig

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_collection(
    parts: list[dict],
    output_path: Path,
    config: MultiPartConfig | None = None,
) -> Path | None:
    """Compile multiple spec parts into a single navigable HTML document.

    Each entry in *parts* must have:

    - ``part_number`` — string identifier (e.g. ``"1"``, ``"10"``)
    - ``title`` — human-readable part title
    - ``html_path`` — :class:`Path` to the compiled ``index.html``

    The generated document contains:

    1. A sidebar listing every part with anchor links.
    2. A unified table of contents covering all parts.
    3. All part content with prefixed IDs to avoid collisions.
    4. A merged, deduplicated bibliography.

    Args:
        parts: List of part descriptors (see above).
        output_path: Destination HTML file path.
        config: Optional :class:`MultiPartConfig` for extra metadata.

    Returns:
        Path to the generated collection HTML, or ``None`` on failure.
    """
    if not parts:
        logging.info("No parts provided; skipping collection compilation")
        return None

    # Sort parts by numeric part_number (fallback to string sort).
    parts = sorted(parts, key=lambda p: _sort_key(p["part_number"]))

    # Parse each part's HTML.
    parts_data: list[dict] = []
    for part in parts:
        html_path = Path(part["html_path"])
        if not html_path.exists():
            logging.warning(f"Collection: part {part['part_number']} HTML not found: {html_path}")
            continue
        try:
            html_text = html_path.read_text(encoding="utf-8")
            soup = BeautifulSoup(html_text, "html.parser")
        except Exception as exc:
            logging.warning(f"Collection: failed to parse part {part['part_number']}: {exc}")
            continue
        parts_data.append(
            {
                "part_number": part["part_number"],
                "title": part["title"],
                "soup": soup,
                "html_path": html_path,
            }
        )

    if not parts_data:
        logging.warning("Collection: no valid parts parsed; aborting")
        return None

    # Prefix IDs in each part to avoid collisions.
    for pd in parts_data:
        _prefix_ids(pd["soup"], pd["part_number"])

    # Build sub-components.
    sidebar_html = _build_part_nav(parts_data)
    toc_html = _build_collection_toc(parts_data)
    bib_entries = _merge_bibliographies([pd["soup"] for pd in parts_data])

    # Extract title from config or derive from parts.
    if config and config.title_main:
        doc_title = config.title_main
        if config.base_docnumber:
            doc_title = f"{config.base_docnumber} — {doc_title}"
    else:
        doc_title = "Multi-Part Standard Collection"

    # Assemble the articles.
    articles: list[str] = []
    for pd in parts_data:
        body = pd["soup"].find("body")
        body_content = "".join(str(child) for child in body.children) if body else ""
        pnum = pd["part_number"]
        articles.append(
            f'<article id="part-{pnum}" class="collection-part">\n'
            f'<h1 class="part-header">Part {pnum} &mdash; {_esc(pd["title"])}</h1>\n'
            f"{body_content}\n"
            f"</article>\n"
        )

    # Build bibliography section.
    bib_html = ""
    if bib_entries:
        bib_rows = "\n".join(f"<li>{entry}</li>" for entry in bib_entries)
        bib_html = (
            '<section id="collection-bibliography">\n'
            "<h2>Bibliography</h2>\n"
            f"<ul>\n{bib_rows}\n</ul>\n"
            "</section>\n"
        )

    # Collect <head> content from the first part (base stylesheets, etc.)
    head_extras = _extract_head_content(parts_data[0]["soup"])

    # Resolve cross-part references.
    full_html = _assemble_document(
        doc_title,
        head_extras,
        sidebar_html,
        toc_html,
        articles,
        bib_html,
    )
    full_soup = BeautifulSoup(full_html, "html.parser")
    resolved = _resolve_cross_part_refs(full_soup, parts_data)
    if resolved:
        logging.info(f"Collection: resolved {resolved} cross-part reference(s)")

    # Inject collection-specific CSS.
    _inject_collection_css(full_soup)

    # Write output.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(str(full_soup), encoding="utf-8")

    size_kb = output_path.stat().st_size / 1024
    logging.info(
        f"Collection written to {output_path} ({size_kb:.0f} KB) — "
        f"{len(parts_data)} part(s), {len(bib_entries)} bibliography entries"
    )
    return output_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _sort_key(part_number: str) -> tuple[int, str]:
    """Sort key that orders numeric parts naturally, alpha parts last."""
    try:
        return (int(part_number), "")
    except ValueError:
        return (9999, part_number)


def _esc(text: str) -> str:
    """Minimal HTML escaping for attribute/text values."""
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# ID prefixing
# ---------------------------------------------------------------------------


def _prefix_ids(soup: BeautifulSoup, part_number: str) -> None:
    """Prefix all ``id`` attributes and internal ``href="#..."`` links.

    Transforms ``id="foo"`` to ``id="part-N-foo"`` and
    ``href="#foo"`` to ``href="#part-N-foo"`` within the same document,
    ensuring no collisions when multiple parts are merged.
    """
    prefix = f"part-{part_number}-"

    # Collect all existing IDs first so we only rewrite hrefs that target them.
    existing_ids: set[str] = set()
    for tag in soup.find_all(True):
        eid = tag.get("id")
        if eid:
            existing_ids.add(eid)

    # Prefix all IDs.
    for tag in soup.find_all(True):
        eid = tag.get("id")
        if eid:
            tag["id"] = prefix + eid

    # Rewrite internal hrefs.
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("#"):
            target = href[1:]
            if target in existing_ids:
                a_tag["href"] = f"#{prefix}{target}"


# ---------------------------------------------------------------------------
# Unified table of contents
# ---------------------------------------------------------------------------


def _build_collection_toc(parts_data: list[dict]) -> str:
    """Build a unified table of contents with part headers.

    Extracts ``h2``–``h4`` headings from each part's soup (after ID
    prefixing) and groups them under per-part headings.
    """
    lines: list[str] = []
    lines.append('<div id="collection-toc">')
    lines.append("<h2>Table of Contents</h2>")
    lines.append('<ol class="collection-toc-list">')

    for pd in parts_data:
        pnum = pd["part_number"]
        lines.append(
            f'<li class="toc-part"><a href="#part-{pnum}">'
            f"Part {pnum} &mdash; {_esc(pd['title'])}</a>"
        )
        lines.append('<ol class="toc-part-sections">')

        body = pd["soup"].find("body")
        if body:
            for heading in body.find_all(["h2", "h3", "h4"]):
                hid = heading.get("id", "")
                text = heading.get_text(strip=True)
                if not text:
                    continue
                level = int(heading.name[1])  # 2, 3, or 4
                indent_class = f"toc-level-{level}"
                if hid:
                    lines.append(
                        f'<li class="{indent_class}"><a href="#{hid}">{_esc(text)}</a></li>'
                    )
                else:
                    lines.append(f'<li class="{indent_class}">{_esc(text)}</li>')

        lines.append("</ol>")
        lines.append("</li>")

    lines.append("</ol>")
    lines.append("</div>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Part navigation sidebar
# ---------------------------------------------------------------------------


def _build_part_nav(parts_data: list[dict]) -> str:
    """Build a sidebar navigation listing all parts."""
    lines: list[str] = []
    lines.append('<nav class="collection-sidebar">')
    lines.append("<h2>Parts</h2>")
    lines.append("<ul>")
    for pd in parts_data:
        pnum = pd["part_number"]
        lines.append(f'<li><a href="#part-{pnum}">Part {pnum}: {_esc(pd["title"])}</a></li>')
    lines.append("</ul>")
    lines.append("</nav>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bibliography merging
# ---------------------------------------------------------------------------

# Regex to extract a citation key from common patterns like "[RFC 8216]" or
# "ISO/IEC 14496-10:2022".
_CITE_KEY_RE = re.compile(
    r"^\[?([A-Z][A-Za-z0-9/\s\-:.]+?)(?:\]|,|\s{2,})",
)


def _merge_bibliographies(soups: list[BeautifulSoup]) -> list[str]:
    """Merge and deduplicate bibliography entries across parts.

    Looks for ``<section>`` or ``<div>`` elements whose heading contains
    "References" or "Bibliography", extracts ``<li>`` entries, and
    deduplicates by normalised citation key.

    Returns a list of HTML strings (one per unique entry).
    """
    seen_keys: dict[str, str] = {}  # normalised key -> HTML string
    ordered_keys: list[str] = []

    for soup in soups:
        bib_sections = _find_bibliography_sections(soup)
        for sec in bib_sections:
            for li in sec.find_all("li", recursive=True):
                text = li.get_text(strip=True)
                key = _normalise_cite_key(text)
                if key not in seen_keys:
                    seen_keys[key] = _inner_html(li)
                    ordered_keys.append(key)

    return [seen_keys[k] for k in ordered_keys]


def _find_bibliography_sections(soup: BeautifulSoup) -> list[Tag]:
    """Find bibliography/references sections in a parsed HTML document."""
    results: list[Tag] = []
    for heading in soup.find_all(["h2", "h3", "h4"]):
        text = heading.get_text(strip=True).lower()
        if any(
            kw in text
            for kw in (
                "bibliography",
                "references",
                "normative references",
                "informative references",
            )
        ):
            parent = heading.parent
            if parent and parent.name in ("section", "div"):
                results.append(parent)
    return results


def _normalise_cite_key(text: str) -> str:
    """Extract and normalise a citation key from bibliography entry text.

    Strips brackets, collapses whitespace, and lowercases for dedup.
    """
    m = _CITE_KEY_RE.match(text)
    if m:
        return re.sub(r"\s+", " ", m.group(1).strip()).lower()
    # Fallback: first 80 chars normalised.
    return re.sub(r"\s+", " ", text[:80]).strip().lower()


def _inner_html(tag: Tag) -> str:
    """Return the inner HTML of a tag (children serialised)."""
    return "".join(str(child) for child in tag.children)


# ---------------------------------------------------------------------------
# Cross-part reference resolution
# ---------------------------------------------------------------------------

# Matches patterns like "Part 10, Clause 7.3" or "see Part 1".
_CROSS_PART_RE = re.compile(
    r"Part\s+(\d+)(?:\s*,\s*(?:Clause|Section|Annex)\s+([\w.]+))?",
    re.IGNORECASE,
)


def _resolve_cross_part_refs(soup: BeautifulSoup, parts_data: list[dict]) -> int:
    """Resolve cross-part references within the merged document.

    Scans text for patterns like "Part 10, Clause 7.3" and converts them
    to anchor links pointing at the appropriate prefixed ID.

    Returns the number of references resolved.
    """
    known_parts = {pd["part_number"] for pd in parts_data}
    count = 0

    for text_node in soup.find_all(string=_CROSS_PART_RE):
        parent = text_node.parent
        if parent and parent.name == "a":
            continue  # Already a link.
        if parent and parent.name in ("script", "style"):
            continue

        original = str(text_node)
        new_text = original
        replaced = False

        for m in _CROSS_PART_RE.finditer(original):
            part_num = m.group(1)
            if part_num not in known_parts:
                continue

            clause = m.group(2)
            if clause:
                # Try to find a heading ID that matches.
                anchor = f"part-{part_num}-{_clause_to_anchor(clause)}"
            else:
                anchor = f"part-{part_num}"

            # Verify the anchor exists in the merged document.
            target = soup.find(id=anchor)
            if target is None and clause:
                # Fallback to just the part anchor.
                anchor = f"part-{part_num}"

            link = f'<a href="#{anchor}" class="cross-part-ref">{m.group(0)}</a>'
            new_text = new_text.replace(m.group(0), link, 1)
            replaced = True
            count += 1

        if replaced:
            fragment = BeautifulSoup(new_text, "html.parser")
            _frag_body = fragment.find("body") or fragment
            _children = list(_frag_body.children)
            text_node.replace_with(*_children if _children else [new_text])

    return count


def _clause_to_anchor(clause: str) -> str:
    """Convert a clause reference like '7.3' to a plausible anchor fragment."""
    return re.sub(r"[^a-z0-9]+", "-", clause.lower()).strip("-")


# ---------------------------------------------------------------------------
# CSS injection
# ---------------------------------------------------------------------------


def _inject_collection_css(soup: BeautifulSoup) -> None:
    """Inject CSS for collection layout (part headers, sidebar, print)."""
    css = """\
/* === Collection layout === */
.collection-sidebar {
  position: fixed;
  top: 0;
  left: 0;
  width: 250px;
  height: 100vh;
  overflow-y: auto;
  background: #f7f7f7;
  border-right: 1px solid #ddd;
  padding: 1em;
  box-sizing: border-box;
  font-size: 0.9em;
  z-index: 100;
}
.collection-sidebar h2 {
  margin-top: 0;
  font-size: 1.1em;
  border-bottom: 1px solid #ccc;
  padding-bottom: 0.3em;
}
.collection-sidebar ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.collection-sidebar li {
  margin: 0.3em 0;
}
.collection-sidebar a {
  color: #333;
  text-decoration: none;
}
.collection-sidebar a:hover {
  text-decoration: underline;
  color: #005a9c;
}
.collection-content {
  margin-left: 270px;
  padding: 2em;
  max-width: 900px;
}
#collection-toc {
  margin-bottom: 3em;
  border-bottom: 2px solid #333;
  padding-bottom: 1.5em;
}
#collection-toc h2 {
  margin-top: 0;
}
.collection-toc-list {
  list-style: none;
  padding: 0;
}
.collection-toc-list > li.toc-part {
  margin: 1em 0 0.3em;
  font-weight: bold;
  font-size: 1.05em;
}
.toc-part-sections {
  list-style: none;
  padding-left: 1.5em;
  font-weight: normal;
  font-size: 0.95em;
}
.toc-level-3 { padding-left: 1.5em; }
.toc-level-4 { padding-left: 3em; }
.collection-part {
  border-top: 3px solid #005a9c;
  margin-top: 3em;
  padding-top: 1em;
}
.part-header {
  color: #005a9c;
  font-size: 1.6em;
  border-bottom: 1px solid #ccc;
  padding-bottom: 0.3em;
}
#collection-bibliography {
  border-top: 2px solid #333;
  margin-top: 3em;
  padding-top: 1em;
}
.cross-part-ref {
  color: #005a9c;
  border-bottom: 1px dashed #005a9c;
  text-decoration: none;
}
.cross-part-ref:hover {
  text-decoration: underline;
}

/* Print styles */
@media print {
  .collection-sidebar { display: none; }
  .collection-content { margin-left: 0; padding: 0; max-width: none; }
  .collection-part { page-break-before: always; }
}
"""
    head = soup.find("head")
    if head:
        style_tag = soup.new_tag("style", attrs={"data-collection": "true"})
        style_tag.string = css
        head.append(style_tag)
    else:
        # No <head>; prepend a <style> tag at the top of the document.
        style_tag = soup.new_tag("style", attrs={"data-collection": "true"})
        style_tag.string = css
        if soup.contents:
            soup.contents[0].insert_before(style_tag)


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------


def _extract_head_content(soup: BeautifulSoup) -> str:
    """Extract reusable ``<head>`` children (stylesheets, meta) from a part."""
    head = soup.find("head")
    if not head:
        return ""
    # Keep <meta>, <link>, and <style> tags.
    parts: list[str] = []
    for child in head.children:
        if isinstance(child, Tag) and child.name in ("meta", "link", "style"):
            parts.append(str(child))
    return "\n".join(parts)


def _assemble_document(
    title: str,
    head_extras: str,
    sidebar_html: str,
    toc_html: str,
    articles: list[str],
    bib_html: str,
) -> str:
    """Assemble the final collection HTML document."""
    articles_str = "\n".join(articles)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
{head_extras}
</head>
<body>
{sidebar_html}
<main class="collection-content">
{toc_html}

{articles_str}

{bib_html}
</main>
</body>
</html>
"""

"""Multi-part standard orchestration.

Manages collections of related specification parts (e.g., ISO 14496 Parts 1-40),
cross-part references, shared metadata, and collection table of contents.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PartSpec:
    """Metadata for a single part of a multi-part standard."""

    part_number: str
    title: str
    path: str = ""
    status: str = "active"
    edition: str = ""
    year: str = ""


@dataclass
class MultiPartConfig:
    """Configuration for a multi-part standard collection."""

    base_docnumber: str = ""
    title_main: str = ""
    organization: str = ""
    parts: list[PartSpec] = field(default_factory=list)
    shared_metadata: dict[str, str] = field(default_factory=dict)


_MULTIPART = MultiPartConfig()

# Module-level compiled patterns — compiled once rather than per-call.
_RE_BARE_PART_NUM = re.compile(r"^\d+$")
_RE_PART_REF = re.compile(
    r"(?:(?:see|in|of)\s+)?Part\s+(\d+)(?:\s*,\s*(?:Clause|Section|Annex)\s+[\w.]+)?",
    re.IGNORECASE,
)
_RE_XPART = re.compile(r"\[\[xpart:(\d+)/([^\]|]+)(?:\|([^\]]+))?\]\]")
_RE_PART_TEXT = re.compile(r"(?:Part\s+)?(\d+)(?:\s*,\s*(.+))?", re.IGNORECASE)
_CROSS_PART_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Part\s+(\d+),?\s+Clause\s+([\d.]+)", re.IGNORECASE), "clause"),
    (re.compile(r"Part\s+(\d+),?\s+Figure\s+([\d.]+)", re.IGNORECASE), "fig"),
    (re.compile(r"Part\s+(\d+),?\s+Table\s+([\d.]+)", re.IGNORECASE), "table"),
]


def load_multipart_config(config_data: dict[str, Any]) -> MultiPartConfig:
    """Load multi-part configuration from a TOML [standards.multipart] section.

    Expected TOML structure::

        [standards.multipart]
        base_docnumber = "ISO/IEC 14496"
        title_main = "Information technology — Coding of audio-visual objects"
        organization = "ISO/IEC JTC 1/SC 29"

        [[standards.multipart.parts]]
        part_number = "1"
        title = "Systems"
        path = "../iso14496-1"
        status = "active"
        edition = "5"
        year = "2020"

        [[standards.multipart.parts]]
        part_number = "10"
        title = "Advanced video coding"
        path = "../iso14496-10"
    """
    global _MULTIPART

    mp = MultiPartConfig(
        base_docnumber=config_data.get("base_docnumber", ""),
        title_main=config_data.get("title_main", ""),
        organization=config_data.get("organization", ""),
    )

    mp.shared_metadata = {
        k: v
        for k, v in config_data.items()
        if k not in ("base_docnumber", "title_main", "organization", "parts") and isinstance(v, str)
    }

    parts_data = config_data.get("parts", [])
    for p in parts_data:
        if isinstance(p, dict):
            mp.parts.append(
                PartSpec(
                    part_number=str(p.get("part_number", "")),
                    title=p.get("title", ""),
                    path=p.get("path", ""),
                    status=p.get("status", "active"),
                    edition=p.get("edition", ""),
                    year=p.get("year", ""),
                )
            )

    _MULTIPART = mp
    logging.info(f"Loaded multi-part config: {mp.base_docnumber} with {len(mp.parts)} part(s)")
    return mp


def get_multipart_config() -> MultiPartConfig:
    """Return the active multi-part configuration."""
    return _MULTIPART


def generate_collection_toc(
    output_path: Path,
    config: MultiPartConfig | None = None,
) -> Path | None:
    """Generate an HTML collection table of contents for all parts.

    Creates a standalone HTML page listing all parts with links,
    status badges, and shared metadata.
    """
    if config is None:
        config = _MULTIPART

    if not config.parts:
        logging.info("No multi-part configuration; skipping collection TOC")
        return None

    rows = []
    for part in sorted(config.parts, key=lambda p: _sort_key(p.part_number)):
        status_badge = _status_badge(part.status)
        doc_id = f"{config.base_docnumber}-{part.part_number}"
        if part.year:
            doc_id += f":{part.year}"

        link = ""
        if part.path:
            link = f' <a href="{part.path}/index.html">[view]</a>'

        rows.append(
            f"<tr>"
            f"<td>{part.part_number}</td>"
            f"<td>{doc_id}</td>"
            f"<td>{part.title}{link}</td>"
            f"<td>{part.edition or '—'}</td>"
            f"<td>{status_badge}</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{config.base_docnumber} — Collection</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.3em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ddd; padding: 0.5em 0.75em; text-align: left; }}
th {{ background: #f5f5f5; font-weight: 600; }}
tr:nth-child(even) {{ background: #fafafa; }}
.badge {{ display: inline-block; padding: 0.15em 0.5em; border-radius: 3px; font-size: 0.85em; }}
.badge-active {{ background: #d4edda; color: #155724; }}
.badge-draft {{ background: #fff3cd; color: #856404; }}
.badge-withdrawn {{ background: #f8d7da; color: #721c24; }}
.badge-superseded {{ background: #e2e3e5; color: #383d41; }}
.meta {{ color: #666; margin: 0.25em 0; }}
</style>
</head>
<body>
<h1>{config.base_docnumber}</h1>
<p class="meta"><strong>{config.title_main}</strong></p>
<p class="meta">{config.organization}</p>

<h2>Parts</h2>
<table>
<thead>
<tr><th>Part</th><th>Document ID</th><th>Title</th><th>Edition</th><th>Status</th></tr>
</thead>
<tbody>
{"".join(rows)}
</tbody>
</table>

<p class="meta">Generated by specbuild</p>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Collection TOC written to {output_path}")
    return output_path


def resolve_cross_part_reference(
    ref_text: str,
    config: MultiPartConfig | None = None,
) -> dict[str, str] | None:
    """Resolve a cross-part reference like "Part 10, Clause 7.3" or a bare part number "10".

    Returns a dict with keys: part_number, title, path, clause (if any).
    Returns None if the reference cannot be resolved.
    """
    if config is None:
        config = _MULTIPART

    # Accept bare numeric string as part number
    if _RE_BARE_PART_NUM.match(ref_text.strip()):
        part_num = ref_text.strip()
        for part in config.parts:
            if part.part_number == part_num:
                return {"part_number": part.part_number, "title": part.title, "path": part.path}
        return None

    m = _RE_PART_TEXT.match(ref_text)
    if not m:
        return None

    part_num = m.group(1)
    clause_ref = m.group(2) or ""

    for part in config.parts:
        if part.part_number == part_num:
            result: dict[str, str] = {
                "part_number": part.part_number,
                "title": part.title,
                "path": part.path,
            }
            if clause_ref:
                result["clause"] = clause_ref.strip()
            return result

    return None


def resolve_cross_part_text_refs(soup: Any, config: MultiPartConfig | None = None) -> int:
    """Scan text nodes and convert plain-text cross-part references to hyperlinks.

    Handles three patterns in ``<p>``, ``<li>``, and ``<td>`` elements:

    - ``Part N, Clause X.Y.Z`` → ``../part-N/index.html#clause-X-Y-Z``
    - ``Part N, Figure X.Y``   → ``../part-N/index.html#fig-X-Y``
    - ``Part N, Table X.Y``    → ``../part-N/index.html#table-X-Y``

    Each match is wrapped in
    ``<a href="..." class="cross-part-ref" data-part="N">...</a>``.

    Args:
        soup: Parsed BeautifulSoup document to modify in-place.
        config: Multi-part configuration; defaults to the module singleton.

    Returns:
        Number of links created.
    """
    if config is None:
        config = _MULTIPART

    if not config.parts:
        return 0

    # Build a quick lookup set of known part numbers for fast rejection.
    known_parts = {p.part_number for p in config.parts if p.path}

    count = 0

    for tag_name in ("p", "li", "td"):
        for container in list(soup.find_all(tag_name)):
            for pattern, anchor_prefix in _CROSS_PART_PATTERNS:
                for text_node in list(container.find_all(string=pattern)):
                    parent = text_node.parent
                    if parent and getattr(parent, "name", None) == "a":
                        continue

                    raw = str(text_node)
                    modified = False

                    # Collect (start, end, link) tuples for position-based reconstruction
                    replacements: list[tuple[int, int, str]] = []
                    for m in pattern.finditer(raw):
                        part_num = m.group(1)
                        ref_num = m.group(2)
                        if part_num not in known_parts:
                            continue

                        ref = resolve_cross_part_reference(part_num, config)
                        if not ref or not ref.get("path"):
                            continue

                        anchor = f"{anchor_prefix}-{ref_num.rstrip('.').replace('.', '-')}"
                        href = f"{ref['path']}/index.html#{anchor}"
                        link = (
                            f'<a href="{href}" class="cross-part-ref" '
                            f'data-part="{part_num}">{m.group(0)}</a>'
                        )
                        replacements.append((m.start(), m.end(), link))
                        modified = True
                        count += 1

                    if modified:
                        from bs4 import BeautifulSoup as BS

                        rebuilt: list[str] = []
                        last_end = 0
                        for start, end, link in replacements:
                            rebuilt.append(raw[last_end:start])
                            rebuilt.append(link)
                            last_end = end
                        rebuilt.append(raw[last_end:])
                        new_html = "".join(rebuilt)

                        _frag = BS(new_html, "html.parser")
                        _body = _frag.find("body") or _frag
                        _children = list(_body.children)
                        if _children:
                            text_node.replace_with(*_children)
                        else:
                            text_node.replace_with(new_html)

    if count:
        logging.info(f"resolve_cross_part_text_refs: created {count} link(s)")
    return count


def _collect_incoming_refs(
    config: MultiPartConfig,
    current_part_number: str,
    parts_dir: Path | None,
) -> list[dict[str, str]]:
    """Scan sibling parts' HTML for references pointing at *current_part_number*.

    Args:
        config: Multi-part configuration with part paths.
        current_part_number: The part number whose incoming refs to collect.
        parts_dir: Optional base directory for resolving relative part paths.

    Returns:
        List of dicts with ``source_part``, ``href``, ``label`` keys.
    """
    incoming: list[dict[str, str]] = []
    try:
        from bs4 import BeautifulSoup as BS
    except ImportError:
        return incoming

    for part in config.parts:
        if part.part_number == current_part_number or not part.path:
            continue

        # Resolve part HTML path
        html_path: Path
        if parts_dir:
            html_path = parts_dir / part.path / "index.html"
        else:
            html_path = Path(part.path) / "index.html"

        if not html_path.exists():
            continue

        try:
            text = html_path.read_text(encoding="utf-8", errors="replace")
            part_soup = BS(text, "html.parser")
        except OSError:
            continue

        for a_tag in part_soup.find_all("a", class_="cross-part-ref"):
            if a_tag.get("data-part") == current_part_number:
                incoming.append(
                    {
                        "source_part": part.part_number,
                        "href": a_tag.get("href", ""),
                        "label": a_tag.get_text(strip=True),
                    }
                )

    return incoming


def inject_cross_part_links_soup(
    soup: Any,
    config: MultiPartConfig | None = None,
    xpart_manifest_path: Path | None = None,
    current_part_number: str = "",
    parts_dir: Path | None = None,
) -> int:
    """Replace cross-part reference text and ``[[xpart:N/id]]`` placeholders with hyperlinks.

    Handles three reference forms:

    1. Literal ``[[xpart:N/id]]`` strings left in the HTML by Bikeshed — resolved to
       ``<a href="../part-N/index.html#id" class="cross-part-ref" data-part="N"
       data-target="id">Part N, id</a>``.
    2. Prose text like ``"see Part 10"`` or ``"[Part 2, Clause 5.1]"`` — replaced
       with ``<a class="cross-part-ref" ...>`` links.
    3. Specific ``Part N, Clause X.Y.Z`` / ``Part N, Figure X.Y`` /
       ``Part N, Table X.Y`` patterns (via :func:`resolve_cross_part_text_refs`).

    If *xpart_manifest_path* is provided, a ``xpart_refs.json`` manifest is written
    listing all outgoing cross-part links together with an ``incoming_refs`` field
    that lists all references TO this part found in sibling parts (requires part HTML
    to already be built at *parts_dir*).

    Args:
        soup: Parsed BeautifulSoup document to modify in-place.
        config: Multi-part configuration; defaults to the module singleton.
        xpart_manifest_path: If given, write outgoing refs JSON here.
        current_part_number: Part number of the document being processed (used for
            collecting incoming refs when *xpart_manifest_path* is set).
        parts_dir: Base directory for locating sibling part HTML files when
            collecting incoming refs.

    Returns:
        Number of links injected (across all passes).
    """

    if config is None:
        config = _MULTIPART

    if not config.parts:
        return 0

    part_pattern = _RE_PART_REF
    xpart_pattern = _RE_XPART

    count = 0
    outgoing_refs: list[dict[str, str]] = []

    # --- Pass 1: [[xpart:N/id]] explicit references ---
    for text_node in list(soup.find_all(string=xpart_pattern)):
        parent = text_node.parent
        if parent and parent.name == "a":
            continue

        raw_1 = str(text_node)
        modified = False
        replacements_1: list[tuple[int, int, str]] = []
        for m in xpart_pattern.finditer(raw_1):
            part_num = m.group(1)
            target_id = m.group(2).strip()
            label = m.group(3) or f"Part {part_num}, {target_id}"

            ref = resolve_cross_part_reference(part_num, config)
            if ref and ref.get("path"):
                href = f"{ref['path']}/index.html#{target_id}"
                link = (
                    f'<a href="{href}" class="cross-part-ref" '
                    f'data-part="{part_num}" data-target="{target_id}">'
                    f"{label}</a>"
                )
                replacements_1.append((m.start(), m.end(), link))
                outgoing_refs.append(
                    {
                        "source_part": current_part_number,
                        "target_part": part_num,
                        "target_id": target_id,
                        "href": href,
                        "label": label,
                    }
                )
                modified = True
                count += 1

        if modified:
            from bs4 import BeautifulSoup as BS

            rebuilt_1: list[str] = []
            last_end = 0
            for start, end, link in replacements_1:
                rebuilt_1.append(raw_1[last_end:start])
                rebuilt_1.append(link)
                last_end = end
            rebuilt_1.append(raw_1[last_end:])
            new_html = "".join(rebuilt_1)

            _frag = BS(new_html, "html.parser")
            _body = _frag.find("body") or _frag
            _children = list(_body.children)
            if _children:
                text_node.replace_with(*_children)
            else:
                text_node.replace_with(new_html)

    # --- Pass 2: Prose "Part N" text references ---
    for text_node in list(soup.find_all(string=part_pattern)):
        parent = text_node.parent
        if parent and parent.name == "a":
            continue

        raw_2 = str(text_node)
        modified = False
        replacements_2: list[tuple[int, int, str]] = []
        for m in part_pattern.finditer(raw_2):
            part_num = m.group(1)
            ref = resolve_cross_part_reference(part_num, config)
            if ref and ref.get("path"):
                href = f"{ref['path']}/index.html"
                clause = ref.get("clause", "")
                if clause:
                    anchor = re.sub(r"[^a-z0-9]+", "-", clause.lower()).strip("-")
                    href += f"#{anchor}"
                link = f'<a href="{href}" class="cross-part-ref">{m.group(0)}</a>'
                replacements_2.append((m.start(), m.end(), link))
                outgoing_refs.append(
                    {
                        "source_part": current_part_number,
                        "target_part": part_num,
                        "target_id": clause,
                        "href": href,
                        "label": m.group(0),
                    }
                )
                modified = True
                count += 1

        if modified:
            from bs4 import BeautifulSoup as BS

            rebuilt_2: list[str] = []
            last_end = 0
            for start, end, link in replacements_2:
                rebuilt_2.append(raw_2[last_end:start])
                rebuilt_2.append(link)
                last_end = end
            rebuilt_2.append(raw_2[last_end:])
            new_text = "".join(rebuilt_2)

            _frag2 = BS(new_text, "html.parser")
            _body2 = _frag2.find("body") or _frag2
            _children2 = list(_body2.children)
            if _children2:
                text_node.replace_with(*_children2)
            else:
                text_node.replace_with(new_text)

    # --- Pass 3: Specific "Part N, Clause/Figure/Table X.Y" patterns ---
    count += resolve_cross_part_text_refs(soup, config)

    if xpart_manifest_path and outgoing_refs:
        incoming_refs = _collect_incoming_refs(config, current_part_number, parts_dir)
        manifest: dict[str, object] = {
            "outgoing_refs": outgoing_refs,
            "incoming_refs": incoming_refs,
        }
        xpart_manifest_path.parent.mkdir(parents=True, exist_ok=True)
        xpart_manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logging.info(f"Cross-part manifest written to {xpart_manifest_path}")

    if count:
        logging.info(f"Injected {count} cross-part reference link(s)")
    return count


def _sort_key(part_number: str) -> tuple[int, str]:
    """Sort key that handles numeric and alpha part numbers."""
    try:
        return (int(part_number), "")
    except ValueError:
        return (9999, part_number)


def _status_badge(status: str) -> str:
    """Generate an HTML badge for a part's status."""
    css_class = {
        "active": "badge-active",
        "draft": "badge-draft",
        "withdrawn": "badge-withdrawn",
        "superseded": "badge-superseded",
    }.get(status.lower(), "badge-draft")
    return f'<span class="badge {css_class}">{status}</span>'


def generate_collection_cover_html(parts: list[dict], metadata: dict) -> str:
    """Generate a cover page for a multi-part document collection.

    Args:
        parts: List of dicts with title, number, url, status keys.
        metadata: Dict with doc_title, doc_number, sdo, etc.

    Returns:
        HTML string for the collection cover.
    """
    title = metadata.get("doc_title", "Multi-Part Standard")
    doc_num = metadata.get("doc_number", "")
    sdo = metadata.get("sdo", "ISO")

    parts_html = ""
    for p in parts:
        num = p.get("number", "")
        ptitle = p.get("title", "")
        url = p.get("url", "")
        status = p.get("status", "")
        link = f'<a href="{url}">{ptitle}</a>' if url else ptitle
        status_span = f' <span class="status">{status}</span>' if status else ""
        parts_html += f"<li>Part {num}: {link}{status_span}</li>\n"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>{title}</title></head>
<body>
<header class="collection-cover">
  <p class="sdo">{sdo}</p>
  <h1 class="doc-number">{doc_num}</h1>
  <h2 class="doc-title">{title}</h2>
</header>
<section class="parts-list">
  <h2>Parts of this standard</h2>
  <ul>{parts_html}</ul>
</section>
</body>
</html>"""

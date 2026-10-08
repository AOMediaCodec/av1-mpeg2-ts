"""EPUB3 export for standards specifications."""

from __future__ import annotations

import html
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

_IMAGE_MIME: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}


def export_epub(
    soup: BeautifulSoup,
    output_path: Path,
    metadata: dict[str, str],
    image_base_dir: Path | None = None,
) -> Path | None:
    """Build a valid EPUB3 package from compiled HTML.

    Args:
        soup:           BeautifulSoup document (read-only).
        output_path:    Destination ``.epub`` path.
        metadata:       Dict with optional keys: title, creator, docid, date.
        image_base_dir: Directory from which relative ``<img src>`` paths are
                        resolved.  Images that exist on disk are embedded inside
                        the EPUB under ``OEBPS/images/``.

    Returns:
        ``output_path`` on success, or ``None`` if the soup has no body content.
    """
    body = soup.find("body")
    if body is None or not body.get_text(strip=True):
        return None

    title = metadata.get("title", "") or _extract_title(soup)
    creator = metadata.get("creator", "")
    docid = metadata.get("docid", "specbuild-doc")
    date = metadata.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Collect embeddable images and build src_map + manifest items in one pass
    src_map: dict[str, str] = {}
    image_items: list[tuple[str, str, str]] = []
    images: list[tuple[str, Path, str]] = []
    if image_base_dir is not None:
        images = _collect_images(soup, image_base_dir)
        for i, (orig_src, resolved_path, mime) in enumerate(images):
            href = f"images/{resolved_path.name}"
            src_map[orig_src] = href
            image_items.append((f"img-{i}", href, mime))

    # Build nav from headings
    headings = _collect_headings(soup)

    # Serialise body as XHTML (with rewritten image paths)
    content_xhtml = _build_content_xhtml(soup, title, src_map)

    # Build sub-documents
    container_xml = _CONTAINER_XML
    content_opf = _build_content_opf(title, creator, docid, date, image_items)
    toc_ncx = _build_toc_ncx(title, docid, headings)
    nav_xhtml = _build_nav_xhtml(headings)
    main_css = _MAIN_CSS

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # mimetype MUST be first and uncompressed
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
        )
        zf.writestr("META-INF/container.xml", container_xml)
        zf.writestr("OEBPS/content.opf", content_opf)
        zf.writestr("OEBPS/toc.ncx", toc_ncx)
        zf.writestr("OEBPS/nav.xhtml", nav_xhtml)
        zf.writestr("OEBPS/styles/main.css", main_css)
        zf.writestr("OEBPS/content.xhtml", content_xhtml)

        # Embed images
        for _orig_src, resolved_path, _mime in images:
            arcname = f"OEBPS/images/{resolved_path.name}"
            try:
                zf.write(resolved_path, arcname)
            except OSError:
                logging.warning(f"EPUB: could not embed image {resolved_path}")

    logging.info(f"EPUB3 written to {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _collect_images(
    soup: BeautifulSoup,
    image_base_dir: Path,
) -> list[tuple[str, Path, str]]:
    """Return [(original_src, resolved_path, mime_type)] for embeddable images."""
    seen: dict[str, tuple[str, Path, str]] = {}
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or src.startswith(("http://", "https://", "data:", "//")):
            continue
        if src in seen:
            continue
        resolved = (image_base_dir / src).resolve()
        if not resolved.is_file():
            continue
        mime = _IMAGE_MIME.get(resolved.suffix.lower())
        if mime is None:
            continue
        seen[src] = (src, resolved, mime)
    return list(seen.values())


def _extract_title(soup: BeautifulSoup) -> str:
    """Extract title from <title> or first <h1>."""
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return "Specification"


def _collect_headings(soup: BeautifulSoup) -> list[tuple[str, str, int]]:
    """Return [(text, id, level)] for all h1/h2/h3 elements that have an id."""
    results: list[tuple[str, str, int]] = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        hid = tag.get("id", "")
        text = tag.get_text(strip=True)
        level = int(tag.name[1])
        results.append((text, hid, level))
    return results


def _build_content_xhtml(
    soup: BeautifulSoup,
    title: str,
    src_map: dict[str, str] | None = None,
) -> str:
    """Serialise document body as XHTML5, stripping <script> elements."""
    import copy

    body = soup.find("body")
    if body is None:
        body_content = ""
    else:
        body_copy = copy.deepcopy(body)
        for script in body_copy.find_all("script"):
            script.decompose()
        if src_map:
            for img in body_copy.find_all("img"):
                orig = img.get("src", "")
                if orig in src_map:
                    img["src"] = src_map[orig]
        body_content = str(body_copy)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="en">\n'
        "<head>\n"
        f"  <title>{html.escape(title)}</title>\n"
        '  <link rel="stylesheet" type="text/css" href="styles/main.css"/>\n'
        "</head>\n"
        f"{body_content}\n"
        "</html>"
    )


def _build_content_opf(
    title: str,
    creator: str,
    docid: str,
    date: str,
    image_items: list[tuple[str, str, str]] | None = None,
) -> str:
    """Build the OPF 3.0 package document."""
    creator_elem = f"  <dc:creator>{html.escape(creator)}</dc:creator>\n" if creator else ""
    img_manifest = ""
    if image_items:
        img_manifest = "".join(
            f'    <item id="{item_id}" href="{href}" media-type="{mime}"/>\n'
            for item_id, href, mime in image_items
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<package version="3.0" xmlns="http://www.idpf.org/2007/opf"'
        ' unique-identifier="uid" xml:lang="en">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f"    <dc:title>{html.escape(title)}</dc:title>\n"
        f"{creator_elem}"
        "    <dc:language>en</dc:language>\n"
        f'    <dc:identifier id="uid">{html.escape(docid)}</dc:identifier>\n'
        f"    <dc:date>{html.escape(date)}</dc:date>\n"
        "  </metadata>\n"
        "  <manifest>\n"
        '    <item id="content" href="content.xhtml"'
        ' media-type="application/xhtml+xml"/>\n'
        '    <item id="nav" href="nav.xhtml"'
        ' media-type="application/xhtml+xml" properties="nav"/>\n'
        '    <item id="css" href="styles/main.css" media-type="text/css"/>\n'
        '    <item id="ncx" href="toc.ncx"'
        ' media-type="application/x-dtbncx+xml"/>\n'
        f"{img_manifest}"
        "  </manifest>\n"
        '  <spine toc="ncx">\n'
        '    <itemref idref="content"/>\n'
        "  </spine>\n"
        "</package>"
    )


def _build_toc_ncx(title: str, docid: str, headings: list[tuple[str, str, int]]) -> str:
    """Build the NCX navigation document for EPUB2 compatibility."""
    nav_points = []
    for i, (text, hid, _level) in enumerate(headings, 1):
        href = f"content.xhtml#{hid}" if hid else "content.xhtml"
        nav_points.append(
            f'  <navPoint id="navPoint-{i}" playOrder="{i}">\n'
            f"    <navLabel><text>{html.escape(text)}</text></navLabel>\n"
            f'    <content src="{href}"/>\n'
            f"  </navPoint>"
        )
    nav_points_str = "\n".join(nav_points)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"'
        ' "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{html.escape(docid)}"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{html.escape(title)}</text></docTitle>\n"
        f"  <navMap>\n{nav_points_str}\n  </navMap>\n"
        "</ncx>"
    )


def _build_nav_xhtml(headings: list[tuple[str, str, int]]) -> str:
    """Build the EPUB3 navigation document."""
    toc_items = _build_nav_items(headings)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE html>\n"
        '<html xmlns="http://www.w3.org/1999/xhtml"'
        ' xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="en">\n'
        "<head>\n"
        "  <title>Table of Contents</title>\n"
        "</head>\n"
        "<body>\n"
        '  <nav epub:type="toc" id="toc">\n'
        "    <h1>Table of Contents</h1>\n"
        f"    <ol>\n{toc_items}    </ol>\n"
        "  </nav>\n"
        "</body>\n"
        "</html>"
    )


def _build_nav_items(headings: list[tuple[str, str, int]], base_level: int = 1) -> str:
    """Recursively build nested <ol>/<li>/<a> for navigation."""
    if not headings:
        return ""

    lines: list[str] = []
    i = 0
    while i < len(headings):
        text, hid, level = headings[i]
        if level < base_level:
            break
        if level > base_level:
            i += 1
            continue

        href = f"content.xhtml#{hid}" if hid else "content.xhtml"
        indent = "      " + "  " * (level - 1)

        j = i + 1
        while j < len(headings) and headings[j][2] > level:
            j += 1

        child_headings = headings[i + 1 : j]
        if child_headings:
            children = _build_nav_items(child_headings, base_level=level + 1)
            lines.append(
                f"{indent}<li>\n"
                f'{indent}  <a href="{href}">{html.escape(text)}</a>\n'
                f"{indent}  <ol>\n{children}{indent}  </ol>\n"
                f"{indent}</li>"
            )
        else:
            lines.append(f'{indent}<li><a href="{href}">{html.escape(text)}</a></li>')
        i = j

    return "\n".join(lines) + "\n" if lines else ""


_CONTAINER_XML = """\
<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

_MAIN_CSS = """\
body {
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 1rem;
  line-height: 1.6;
  margin: 1em 2em;
  color: #222;
}
h1 { font-size: 1.8em; margin-top: 1.2em; }
h2 { font-size: 1.4em; margin-top: 1em; }
h3 { font-size: 1.2em; margin-top: 0.9em; }
h4, h5, h6 { font-size: 1em; margin-top: 0.8em; }
pre, code {
  font-family: 'Courier New', Courier, monospace;
  font-size: 0.9em;
  background: #f5f5f5;
  padding: 0.1em 0.3em;
  border-radius: 2px;
}
pre {
  padding: 0.8em 1em;
  overflow-x: auto;
  border-left: 3px solid #ccc;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 1em 0;
}
th, td {
  border: 1px solid #bbb;
  padding: 0.4em 0.6em;
  text-align: left;
}
th { background: #eee; font-weight: bold; }
figure { margin: 1em 0; text-align: center; }
figcaption { font-size: 0.9em; color: #555; margin-top: 0.3em; }
"""

"""Broken image detection for compiled HTML specifications.

Validates that all ``<img>``, ``<source>``, and favicon ``<link>`` references
in the compiled HTML resolve to existing files in the build output directory.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

from specbuild.utils import get_bs4, read_html

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def check_images(html_path: Path, base_dir: Path | None = None) -> list[dict]:
    """File-based wrapper around :func:`check_images_soup`.

    Args:
        html_path: Path to the compiled HTML file.
        base_dir: Directory to resolve relative paths against.
            Defaults to ``html_path.parent``.

    Returns:
        List of dicts with ``src``, ``tag``, ``context`` keys.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping image reference check")
        return []

    if base_dir is None:
        base_dir = html_path.parent

    logging.info(f"Checking image references in {html_path.name}")
    soup = read_html(html_path)
    return check_images_soup(soup, base_dir)


def check_images_soup(soup: object, base_dir: Path) -> list[dict]:
    """Check all image references in the parsed HTML.

    Checks:

    - ``<img src="...">`` elements
    - ``<source srcset="...">`` inside ``<picture>``
    - ``<link rel="icon" href="...">`` favicons

    Skips:

    - Data URIs (``src="data:..."``)
    - External URLs (``http://``, ``https://``)
    - SVG inline content (no ``src``)
    - Empty ``src`` attributes

    Args:
        soup: BeautifulSoup document.
        base_dir: Base directory for resolving relative paths.

    Returns:
        List of dicts with keys:

        - ``src``: the broken reference path
        - ``tag``: element tag name (``'img'``, ``'source'``, ``'link'``)
        - ``context``: nearest heading text for user context
    """
    issues: list[dict] = []
    checked = 0

    # --- <img> elements ---------------------------------------------------
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
        if _should_skip(src):
            continue
        checked += 1
        resolved = _resolve_path(src, base_dir)
        if not resolved.exists():
            issues.append(
                {
                    "src": src,
                    "tag": "img",
                    "context": _find_nearest_heading(img),
                }
            )

    # --- <source> elements inside <picture> --------------------------------
    for source in soup.find_all("source"):
        # Only check <source> inside <picture>, not <audio>/<video>
        if source.parent is None or source.parent.name != "picture":
            continue
        srcset = source.get("srcset", "")
        if not srcset:
            continue
        urls = _parse_srcset(srcset)
        for url in urls:
            if _should_skip(url):
                continue
            checked += 1
            resolved = _resolve_path(url, base_dir)
            if not resolved.exists():
                issues.append(
                    {
                        "src": url,
                        "tag": "source",
                        "context": _find_nearest_heading(source),
                    }
                )

    # --- <link rel="icon"> favicons ----------------------------------------
    for link in soup.find_all("link", rel=True):
        # rel is a list in BS4
        rels = link.get("rel", [])
        if not isinstance(rels, list):
            rels = [rels]
        if "icon" not in rels:
            continue
        href = link.get("href", "")
        if not href:
            continue
        if _should_skip(href):
            continue
        checked += 1
        resolved = _resolve_path(href, base_dir)
        if not resolved.exists():
            issues.append(
                {
                    "src": href,
                    "tag": "link",
                    "context": _find_nearest_heading(link),
                }
            )

    logging.info(f"Checked {checked} image reference(s), {len(issues)} broken")
    return issues


def check_image_dimensions_soup(soup: object, base_dir: Path) -> list[dict]:
    """Check image dimensions for oversized images in the parsed HTML.

    Uses Pillow if available to read actual image dimensions.  Skips images
    that are external URLs, data URIs, or cannot be opened.

    Args:
        soup: BeautifulSoup document.
        base_dir: Base directory for resolving relative paths.

    Returns:
        List of dicts with keys:

        - ``path``: resolved file path string
        - ``src``: the original ``src`` attribute value
        - ``dimension_warning``: ``"WxH"`` string for the offending image
        - ``context``: nearest heading text
    """
    warnings: list[dict] = []

    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src or _should_skip(src):
            continue
        resolved = _resolve_path(src, base_dir)
        if not resolved.exists():
            continue
        result = _check_image_dimensions(resolved)
        if result is not None:
            result["src"] = src
            result["context"] = _find_nearest_heading(img)
            warnings.append(result)

    if warnings:
        logging.warning(f"Found {len(warnings)} oversized image(s) (>4000px in any dimension)")
    else:
        logging.info("Image dimension check passed")
    return warnings


def _check_image_dimensions(path: Path) -> dict | None:
    """Return a warning dict if image exceeds recommended max dimensions, else None."""
    try:
        from PIL import Image

        with Image.open(path) as img:
            w, h = img.size
            # Warn if > 4000px in any dimension (likely unoptimized)
            if w > 4000 or h > 4000:
                return {"dimension_warning": f"{w}x{h}", "path": str(path)}
    except Exception:
        pass
    return None


def report_missing_images(issues: list[dict], html_path: Path, *, strict: bool = False) -> None:
    """Log broken image references.

    Args:
        issues: From :func:`check_images` or :func:`check_images_soup`.
        html_path: For log messages.
        strict: If ``True``, raise ``SystemExit(1)`` on issues.
    """
    if not issues:
        logging.info("All image references are valid")
        return

    logging.warning(f"Found {len(issues)} broken image reference(s) in {html_path.name}:")
    for ref in issues:
        logging.warning(f'  <{ref["tag"]}> src="{ref["src"]}" near: {ref["context"]}')

    if strict:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _should_skip(src: str) -> bool:
    """Return True if *src* is a data URI or external URL that should not be checked."""
    if src.startswith("data:"):
        return True
    parsed = urlparse(src)
    if parsed.scheme in ("http", "https"):
        return True
    return False


def _resolve_path(src: str, base_dir: Path) -> Path:
    """Resolve a (possibly URL-encoded) relative path against *base_dir*."""
    # Strip any fragment or query string
    parsed = urlparse(src)
    path_part = parsed.path
    # Decode percent-encoded characters (e.g. %20 -> space)
    decoded = unquote(path_part)
    return base_dir / decoded


def _parse_srcset(srcset: str) -> list[str]:
    """Extract URLs from a ``srcset`` attribute value.

    The ``srcset`` attribute contains comma-separated entries, each with a URL
    and an optional size descriptor (e.g. ``"image.png 2x, image-large.png 3x"``).

    Returns:
        List of URL strings with descriptors stripped.
    """
    urls: list[str] = []
    for entry in srcset.split(","):
        parts = entry.strip().split()
        if parts:
            urls.append(parts[0])
    return urls


def _find_nearest_heading(element: object) -> str:
    """Walk up the DOM to find the nearest heading for context.

    Args:
        element: A BeautifulSoup Tag whose ancestor headings are searched.

    Returns:
        Truncated text of the nearest heading, or ``"(unknown section)"``.
    """
    max_heading_len = 60
    for parent in element.parents:
        if parent is None:
            break
        # Check previous siblings for headings
        for sibling in parent.previous_siblings:
            if hasattr(sibling, "name") and sibling.name in _HEADING_TAGS:
                return sibling.get_text(strip=True)[:max_heading_len]
        # Check if parent itself is under a heading
        if hasattr(parent, "name") and parent.name in ("section", "div"):
            heading = next(
                (c for c in parent.children if hasattr(c, "name") and c.name in _HEADING_TAGS),
                None,
            )
            if heading:
                return heading.get_text(strip=True)[:max_heading_len]
    return "(unknown section)"

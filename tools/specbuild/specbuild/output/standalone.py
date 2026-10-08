"""Standalone HTML export: inline all external resources into a single file.

Reads the compiled ``index.html`` and inlines every external CSS, JavaScript,
and image reference so that the result is a fully self-contained HTML document
that can be opened from any location without needing the ``css/``, ``js/``,
or ``images/`` directories.

External resources (CDN scripts, remote stylesheets) are fetched over HTTP
when available; if the fetch fails the original reference is preserved with
a comment noting the failure.

Usage::

    python compile.py --standalone       # generates index_standalone.html
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

# ---------------------------------------------------------------------------
# MIME type helpers
# ---------------------------------------------------------------------------

# Extend Python's built-in MIME map for types common in specs
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/javascript", ".mjs")


def _guess_mime(path: Path) -> str:
    """Guess MIME type from file extension, with sensible defaults."""
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def _is_remote(url: str) -> bool:
    """Return True if *url* is an absolute remote URL."""
    return url.startswith(("http://", "https://", "//"))


def _is_data_uri(url: str) -> bool:
    """Return True if *url* is already a data: URI."""
    return url.startswith("data:")


def _file_url_to_path(url: str) -> Path:
    """Convert a ``file://`` URL to a local :class:`Path`."""
    return Path(url2pathname(urlparse(url).path))


# ---------------------------------------------------------------------------
# Resource fetching
# ---------------------------------------------------------------------------


def _fetch_remote(url: str, *, as_bytes: bool = False) -> str | bytes | None:
    """Fetch a remote URL and return its content, or None on failure.

    When *as_bytes* is True the raw ``bytes`` are returned; otherwise the
    decoded ``str`` text is returned.
    """
    try:
        import requests

        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content if as_bytes else resp.text
    except Exception as exc:
        logging.warning(f"Standalone: failed to fetch {url}: {exc}")
        return None


# ---------------------------------------------------------------------------
# File-to-data-URI conversion
# ---------------------------------------------------------------------------


def _file_to_data_uri(file_path: Path) -> str | None:
    """Read a local file and return a ``data:`` URI, or None if missing."""
    if not file_path.exists():
        logging.debug(f"Standalone: file not found: {file_path}")
        return None
    mime = _guess_mime(file_path)
    data = file_path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _remote_to_data_uri(url: str) -> str | None:
    """Fetch a remote resource and return a ``data:`` URI."""
    raw = _fetch_remote(url, as_bytes=True)
    if raw is None:
        return None
    # Guess MIME from URL path
    parsed = urlparse(url)
    mime, _ = mimetypes.guess_type(parsed.path)
    if mime is None:
        # Sniff from content
        if raw[:5] == b"<?xml" or raw[:4] == b"<svg":
            mime = "image/svg+xml"
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif raw[:2] == b"\xff\xd8":
            mime = "image/jpeg"
        else:
            mime = "application/octet-stream"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


# ---------------------------------------------------------------------------
# CSS url() inlining
# ---------------------------------------------------------------------------

_CSS_URL_RE = re.compile(
    r"""url\(\s*(?P<q>['"]?)(?P<url>[^)'"]+?)(?P=q)\s*\)""",
)


def _inline_css_urls(css_text: str, base_dir: Path) -> str:
    """Replace ``url(...)`` references in CSS with data URIs.

    Handles both local relative paths and ``file://`` protocol URLs.
    Remote ``http(s)://`` URLs are left as-is in CSS (they're typically
    CDN fonts or external assets that shouldn't be inlined).
    """

    def _replace_url(m: re.Match) -> str:
        url = m.group("url")

        # Skip data: URIs and remote URLs
        if _is_data_uri(url) or _is_remote(url):
            return m.group(0)

        # Handle file:// protocol
        if url.startswith("file://"):
            local_path = _file_url_to_path(url)
        else:
            local_path = base_dir / url

        data_uri = _file_to_data_uri(local_path)
        if data_uri:
            return f"url({data_uri})"
        return m.group(0)

    return _CSS_URL_RE.sub(_replace_url, css_text)


# ---------------------------------------------------------------------------
# HTML transformation
# ---------------------------------------------------------------------------


def generate_standalone_html(
    html_path: Path,
    output_path: Path | None = None,
) -> Path | None:
    """Generate a standalone HTML file with all resources inlined.

    Processes the compiled ``index.html``:

    1. Replaces ``<link rel="stylesheet" href="...">`` with inline
       ``<style>`` blocks (fetching remote CSS if needed).
    2. Replaces ``<script src="...">`` with inline ``<script>`` blocks.
    3. Replaces ``<img src="...">`` with base64 ``data:`` URIs.
    4. Inlines ``url(...)`` references within CSS.

    Args:
        html_path: Path to the compiled ``index.html``.
        output_path: Destination path.  Defaults to
            ``index_standalone.html`` in the same directory.

    Returns:
        Path to the generated standalone HTML, or ``None`` on failure.
    """
    if not html_path.exists():
        logging.error(f"Standalone: HTML file not found: {html_path}")
        return None

    if output_path is None:
        output_path = html_path.parent / "index_standalone.html"

    base_dir = html_path.parent
    html = html_path.read_text(encoding="utf-8")

    stats = {"css": 0, "js": 0, "img": 0, "css_url": 0, "remote": 0, "failed": 0}

    logging.info("Generating standalone HTML (inlining all resources)...")

    # --- Step 1: Inline <link rel="stylesheet"> ---
    def _replace_css_link(m: re.Match) -> str:
        tag = m.group(0)

        # Extract href and media from the full tag
        href_m = re.search(r'href=(["\'])([^"\']+)\1', tag)
        media_m = re.search(r'media=(["\'])([^"\']+)\1', tag)
        if not href_m:
            return tag
        href = href_m.group(2)
        media = media_m.group(2) if media_m else ""

        if _is_remote(href):
            css_text = _fetch_remote(href)
            stats["remote"] += 1
            if css_text is None:
                stats["failed"] += 1
                return f"<!-- standalone: failed to fetch {href} -->\n{tag}"
        else:
            css_path = base_dir / href
            if not css_path.exists():
                logging.debug(f"Standalone: CSS not found: {css_path}")
                return tag
            css_text = css_path.read_text(encoding="utf-8")
            # Resolve @import directives within the CSS
            css_text = _resolve_css_imports(css_text, css_path.parent)

        # Inline url() references within the CSS
        css_dir = (base_dir / href).parent if not _is_remote(href) else base_dir
        css_text = _inline_css_urls(css_text, css_dir)

        media_attr = f' media="{media}"' if media else ""
        stats["css"] += 1
        return f"<style data-standalone-inlined{media_attr}>\n{css_text}\n</style>"

    # Match any <link> tag with rel="stylesheet" (regardless of attribute order)
    html = re.sub(
        r'<link\s[^>]*rel=["\']stylesheet["\'][^>]*/?>',
        _replace_css_link,
        html,
    )

    # --- Step 2: Inline <script src="..."> ---
    def _replace_js_script(m: re.Match) -> str:
        tag = m.group(0)
        src = m.group("src")
        attrs = m.group("attrs") or ""

        if _is_remote(src):
            js_text = _fetch_remote(src)
            stats["remote"] += 1
            if js_text is None:
                stats["failed"] += 1
                return f"<!-- standalone: failed to fetch {src} -->\n{tag}"
        else:
            js_path = base_dir / src
            if not js_path.exists():
                logging.debug(f"Standalone: JS not found: {js_path}")
                return tag
            js_text = js_path.read_text(encoding="utf-8")

        # Preserve async/defer attributes
        extra_attrs = ""
        if re.search(r"\basync\b", attrs):
            extra_attrs += " async"
        if re.search(r"\bdefer\b", attrs):
            extra_attrs += " defer"

        stats["js"] += 1
        return f"<script{extra_attrs}>\n{js_text}\n</script>"

    html = re.sub(
        r'<script(?P<attrs>[^>]*?)\s+src=(?P<q>["\'])(?P<src>[^"\']+)(?P=q)'
        r"[^>]*>\s*</script>",
        _replace_js_script,
        html,
    )

    # --- Step 3: Inline <img src="..."> ---
    def _replace_img_src(m: re.Match) -> str:
        full_tag = m.group(0)
        src = m.group("src")

        if _is_data_uri(src):
            return full_tag

        if _is_remote(src):
            data_uri = _remote_to_data_uri(src)
            stats["remote"] += 1
            if data_uri is None:
                stats["failed"] += 1
                return full_tag
        else:
            img_path = base_dir / src
            data_uri = _file_to_data_uri(img_path)
            if data_uri is None:
                return full_tag

        stats["img"] += 1
        return full_tag.replace(src, data_uri)

    html = re.sub(
        r'<img\s+[^>]*?src=(?P<q>["\'])(?P<src>[^"\']+)(?P=q)[^>]*/?>',
        _replace_img_src,
        html,
    )

    # --- Step 4: Inline url() in remaining inline <style> blocks ---
    # Skip blocks already processed by Step 1 (marked with data-standalone-inlined).
    def _replace_inline_style_urls(m: re.Match) -> str:
        attrs = m.group("attrs")
        if "data-standalone-inlined" in attrs:
            return m.group(0)
        style_content = m.group("content")
        inlined = _inline_css_urls(style_content, base_dir)
        if inlined != style_content:
            stats["css_url"] += 1
        return f"<style{attrs}>{inlined}</style>"

    html = re.sub(
        r"<style(?P<attrs>[^>]*)>(?P<content>.*?)</style>",
        _replace_inline_style_urls,
        html,
        flags=re.DOTALL,
    )

    # --- Write output ---
    # Remove the internal marker attribute before writing
    html = html.replace(" data-standalone-inlined", "")
    output_path.write_text(html, encoding="utf-8")

    size_kb = output_path.stat().st_size / 1024
    logging.info(
        f"Standalone HTML written to {output_path} ({size_kb:.0f} KB) — "
        f"inlined {stats['css']} CSS, {stats['js']} JS, {stats['img']} images"
        + (f", {stats['remote']} remote" if stats["remote"] else "")
        + (f", {stats['failed']} failed" if stats["failed"] else "")
    )
    return output_path


# ---------------------------------------------------------------------------
# CSS @import resolution
# ---------------------------------------------------------------------------


def _resolve_css_imports(
    css_text: str,
    css_dir: Path,
    *,
    _seen: set[Path] | None = None,
) -> str:
    """Resolve ``@import`` directives by inlining the referenced files.

    Handles both ``@import "file.css"`` and ``@import url("file.css")``
    syntax, including ``file://`` protocol paths.
    """
    if _seen is None:
        _seen = set()

    def _replace_import(m: re.Match) -> str:
        url = m.group("url")

        if _is_remote(url):
            # Leave remote imports as-is
            return m.group(0)

        if url.startswith("file://"):
            local_path = _file_url_to_path(url)
        else:
            local_path = css_dir / url

        resolved = local_path.resolve()
        if resolved in _seen:
            logging.debug(f"Standalone: circular @import skipped: {local_path}")
            return m.group(0)

        if not local_path.exists():
            logging.debug(f"Standalone: @import target not found: {local_path}")
            return m.group(0)

        _seen.add(resolved)
        imported_css = local_path.read_text(encoding="utf-8")
        # Recursively resolve imports in the imported file
        imported_css = _resolve_css_imports(imported_css, local_path.parent, _seen=_seen)
        # Inline url() references relative to the imported file's directory
        imported_css = _inline_css_urls(imported_css, local_path.parent)

        return f"/* @import inlined from {local_path.name} */\n{imported_css}"

    # Match @import "url" and @import url("url")
    css_text = re.sub(
        r'@import\s+url\(\s*(?P<q>["\']?)(?P<url>[^)"\'\s]+)(?P=q)\s*\)\s*;',
        _replace_import,
        css_text,
    )
    css_text = re.sub(
        r'@import\s+(?P<q>["\'])(?P<url>[^"\']+)(?P=q)\s*;',
        _replace_import,
        css_text,
    )

    return css_text

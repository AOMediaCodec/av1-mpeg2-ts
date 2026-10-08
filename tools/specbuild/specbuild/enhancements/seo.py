"""SEO metadata injector: add ``<meta>`` and ``<link>`` tags to ``<head>``.

Injects standard web metadata (Open Graph, Twitter Card, description,
keywords and canonical URL) into compiled HTML to improve discoverability.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

from specbuild.utils import get_bs4, read_html, write_html

log = logging.getLogger(__name__)

_DESCRIPTION_MAX_LEN = 160


# ---------------------------------------------------------------------------
# Description extractor
# ---------------------------------------------------------------------------


def extract_document_description(soup: BeautifulSoup) -> str:
    """Return the first 160 characters of the Scope section's first paragraph.

    Falls back to the first ``<p>`` in ``<body>`` if no Scope section is found.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        Truncated description string (at most 160 chars).
    """
    # Look for a section with id="sec-scope" or a heading matching "Scope"
    scope_section = soup.find(id="sec-scope")
    if scope_section is None:
        scope_re = re.compile(r"\bScope\b", re.IGNORECASE)
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            if scope_re.search(heading.get_text(strip=True)):
                scope_section = (
                    heading.find_parent(["section", "div"]) or heading.find_next_sibling()
                )
                break

    if scope_section is not None:
        # Find the first paragraph inside the scope section (or after the heading)
        para = scope_section.find("p")
        if para is None and hasattr(scope_section, "find_next_sibling"):
            para = scope_section.find_next_sibling("p")
        if para:
            return para.get_text(strip=True)[:_DESCRIPTION_MAX_LEN]

    # Final fallback: first body paragraph
    body = soup.find("body")
    if body:
        para = body.find("p")
        if para:
            return para.get_text(strip=True)[:_DESCRIPTION_MAX_LEN]

    return ""


# ---------------------------------------------------------------------------
# Main injector
# ---------------------------------------------------------------------------


def inject_seo_metadata_soup(
    soup: BeautifulSoup,
    *,
    title: str = "",
    description: str = "",
    url: str = "",
    keywords: list[str] | None = None,
) -> int:
    """Inject SEO ``<meta>`` and ``<link>`` tags into ``<head>``.

    Only tags that do not already exist are inserted.

    Args:
        soup: BeautifulSoup document (mutated in place).
        title: Document title override.  Inferred from ``<h1>`` or ``<title>``
            if empty.
        description: Description override (truncated to 160 chars).  Inferred
            from Scope section or first paragraph if empty.
        url: Canonical URL.  A ``<link rel="canonical">`` is only added when
            this is non-empty.
        keywords: List of keyword strings.  Inferred from ``<dfn>`` texts
            (first 10) if *None*.

    Returns:
        Number of tags injected.
    """
    head = soup.find("head")
    if not head:
        return 0

    injected = 0

    # --- Resolve title ---
    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True)

    # --- Resolve description ---
    # Honour an already-present <meta name="description">
    existing_desc_tag = soup.find("meta", attrs={"name": "description"})
    if existing_desc_tag:
        description = existing_desc_tag.get("content", "") or description
    if not description:
        description = extract_document_description(soup)
    description = description[:_DESCRIPTION_MAX_LEN]

    # --- Resolve keywords ---
    if keywords is None:
        dfns = soup.find_all("dfn")
        keywords = [d.get_text(strip=True) for d in dfns[:10] if d.get_text(strip=True)]

    # ------------------------------------------------------------------
    # Helper: check whether a meta/link tag already exists
    # ------------------------------------------------------------------
    def _meta_exists(name: str | None = None, prop: str | None = None) -> bool:
        if name:
            return bool(soup.find("meta", attrs={"name": name}))
        if prop:
            return bool(soup.find("meta", attrs={"property": prop}))
        return False

    def _link_exists(rel: str) -> bool:
        for link in soup.find_all("link"):
            if link.get("rel") == [rel] or link.get("rel") == rel:
                return True
        return False

    def _inject_meta(**attrs) -> None:
        nonlocal injected
        tag = soup.new_tag("meta", attrs=attrs)
        head.append(tag)
        injected += 1

    # --- <meta name="description"> ---
    if existing_desc_tag:
        if not existing_desc_tag.get("content") and description:
            existing_desc_tag["content"] = description
    elif description:
        _inject_meta(name="description", content=description)

    # --- Open Graph ---
    if title and not _meta_exists(prop="og:title"):
        _inject_meta(**{"property": "og:title", "content": title})
    if description and not _meta_exists(prop="og:description"):
        _inject_meta(**{"property": "og:description", "content": description})
    if not _meta_exists(prop="og:type"):
        _inject_meta(**{"property": "og:type", "content": "article"})

    # --- Twitter Card ---
    if not _meta_exists(name="twitter:card"):
        _inject_meta(name="twitter:card", content="summary")
    if title and not _meta_exists(name="twitter:title"):
        _inject_meta(name="twitter:title", content=title)

    # --- Keywords ---
    if keywords and not _meta_exists(name="keywords"):
        _inject_meta(name="keywords", content=", ".join(keywords))

    # --- Canonical URL ---
    if url and not _link_exists("canonical"):
        tag = soup.new_tag("link", rel="canonical", href=url)
        head.append(tag)
        injected += 1

    log.info("inject_seo_metadata_soup: injected %d tags", injected)
    return injected


# ---------------------------------------------------------------------------
# File-based wrapper
# ---------------------------------------------------------------------------


def inject_seo_metadata(
    html_path: Path,
    *,
    title: str = "",
    description: str = "",
    url: str = "",
    keywords: list[str] | None = None,
) -> int:
    """Read an HTML file, inject SEO metadata, and write it back.

    Args:
        html_path: Path to an HTML file produced by Bikeshed.
        title: Optional title override.
        description: Optional description override.
        url: Optional canonical URL.
        keywords: Optional list of keyword strings.

    Returns:
        Number of tags injected.
    """
    try:
        get_bs4()
    except ImportError:
        log.warning("BeautifulSoup not available, skipping SEO metadata injection")
        return 0

    soup = read_html(html_path)
    count = inject_seo_metadata_soup(
        soup, title=title, description=description, url=url, keywords=keywords
    )
    if count:
        write_html(html_path, soup)
    return count

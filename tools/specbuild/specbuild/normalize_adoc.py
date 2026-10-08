"""Normalize Asciidoctor-generated HTML to the pipeline-compatible shape.

Asciidoctor emits ``<div class="sectN">`` wrappers around headings with
``<div class="sectionbody">`` children.  The specbuild pipeline expects:

- Flat ``<h2 class="heading settled" data-level="2">`` headings in ``<main>``
  with ``<span class="secno">`` and ``<span class="content">`` children.
- ``<section>`` elements created by ``isodocxml._ensure_section_wrappers()``.
- ``<nav class="toc">`` for the table of contents.
- Standard admonition/block class names for styling.

This module transforms the former into the latter without touching any other
part of the specbuild pipeline.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from bs4 import Tag

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def normalize_asciidoctor_html(soup: BeautifulSoup) -> None:
    """Transform Asciidoctor HTML in-place into the pipeline-compatible shape."""
    _normalize_header(soup)
    _normalize_toc(soup)
    _flatten_sections(soup)
    _normalize_blocks(soup)
    _normalize_container_blocks(soup)


# ---------------------------------------------------------------------------
# Header normalization
# ---------------------------------------------------------------------------


def _normalize_header(soup: BeautifulSoup) -> None:
    """Wrap the document header in a standard ``<header>`` if not present."""
    header_div = soup.find("div", id="header")
    if header_div and header_div.name == "div":
        header_div.name = "header"


# ---------------------------------------------------------------------------
# TOC normalization
# ---------------------------------------------------------------------------


def _normalize_toc(soup: BeautifulSoup) -> None:
    """Replace Asciidoctor's ``<div id="toc">`` with ``<nav class="toc">``."""
    toc_div = soup.find("div", id="toc")
    if not toc_div:
        return

    nav = soup.new_tag("nav", attrs={"class": "toc", "id": "toc"})
    for child in list(toc_div.children):
        child.extract()
        nav.append(child)

    toc_div.replace_with(nav)

    # Split plain TOC link text into secno/content spans so that downstream
    # modules (sectionheaders.py, renumber_annexes.py) can find them.
    _prefix_re = re.compile(r"^([\d.]+\.?\s*|Annex\s+[A-Z]\.?\s*|[A-Z]\.\s*)")
    for a_tag in nav.find_all("a"):
        if a_tag.find(True):  # already has child elements — skip
            continue
        raw = a_tag.get_text()
        if not raw.strip():
            continue
        a_tag.clear()
        m = _prefix_re.match(raw)
        secno_span = soup.new_tag("span", attrs={"class": "secno"})
        content_span = soup.new_tag("span", attrs={"class": "content"})
        if m:
            secno_span.string = m.group(1)
            content_span.string = raw[m.end() :]
        else:
            secno_span.string = ""
            content_span.string = raw
        a_tag.append(secno_span)
        a_tag.append(content_span)


# ---------------------------------------------------------------------------
# Section flattening
# ---------------------------------------------------------------------------

_SECT_RE = re.compile(r"^sect(\d+)$")


def _flatten_sections(soup: BeautifulSoup) -> None:
    """Flatten Asciidoctor's nested sectN divs into a ``<main>`` element.

    Asciidoctor output::

        <div id="content">
          <div class="sect1">
            <h2 id="...">Title</h2>
            <div class="sectionbody">
              <p>...</p>
              <div class="sect2">
                <h3 id="...">Sub</h3>
                <div class="sectionbody">...</div>
              </div>
            </div>
          </div>
        </div>

    Pipeline shape::

        <main>
          <h2 id="..." class="heading settled" data-level="2">
            <span class="secno"></span><span class="content">Title</span>
          </h2>
          <p>...</p>
          <h3 id="..." class="heading settled" data-level="3">...</h3>
          ...
        </main>
    """
    content_div = soup.find("div", id="content")
    if not content_div:
        return

    # Build flat list of (tag_or_element, ...) items
    flat_items: list[Tag] = []
    _collect_flat(content_div, soup, flat_items)

    # Create or reuse <main>
    main = soup.find("main")
    if not main:
        main = soup.new_tag("main")
        content_div.replace_with(main)
    else:
        content_div.decompose()

    # Clear main and repopulate
    main.clear()
    for item in flat_items:
        main.append(item)


def _collect_flat(node: Tag, soup: BeautifulSoup, out: list) -> None:
    """Recursively collect normalized flat content from a sectN div tree."""
    for child in list(node.children):
        if not isinstance(child, Tag):
            continue

        classes = child.get("class") or []
        if isinstance(classes, str):
            classes = [classes]

        # Check if this is a sectN div
        sect_match = None
        for cls in classes:
            m = _SECT_RE.match(cls)
            if m:
                sect_match = m
                break

        if sect_match:
            level = min(int(sect_match.group(1)) + 1, 6)  # sect1 → h2, …; capped at h6
            # First direct child heading
            h_tag = child.find(f"h{level}", recursive=False)
            if h_tag is None:
                # fallback: any heading
                for tag in ("h2", "h3", "h4", "h5", "h6"):
                    h_tag = child.find(tag, recursive=False)
                    if h_tag:
                        break

            if h_tag:
                h_tag.extract()  # Remove from DOM before recursing to avoid duplicate emission
                sec_id = h_tag.get("id", "")
                normalized_h = _make_heading(soup, level, sec_id, h_tag)
                out.append(normalized_h)

            # Recurse into sectionbody
            body_div = child.find("div", class_="sectionbody", recursive=False)
            if body_div:
                _collect_flat(body_div, soup, out)
            else:
                # Recurse directly (some Asciidoctor versions omit sectionbody)
                _collect_flat(child, soup, out)

        elif child.get("id") in ("toc", "header", "footer"):
            # Skip — these are handled separately or dropped
            continue

        elif child.get("id") == "preamble":
            # Asciidoctor wraps pre-section content in <div id="preamble">
            # Recurse into its sectionbody (or directly if absent)
            body_div = child.find("div", class_="sectionbody", recursive=False) or child
            _collect_flat(body_div, soup, out)

        elif child.get("id") == "footnotes":
            # Asciidoctor emits a <div id="footnotes"> at the end of the body.
            # Convert it to a pipeline-compatible <section class="footnotes"> so
            # downstream modules can find it without recursing into an unclassed div.
            child.extract()
            child.name = "section"
            child["class"] = ["footnotes"]
            # Remove the decorative <hr>
            hr = child.find("hr")
            if hr:
                hr.decompose()
            # Convert interior footnote divs to paragraphs
            for fn_div in child.find_all("div", class_="footnote"):
                fn_div.name = "p"
            out.append(child)

        elif child.name == "div" and not classes:
            # Transparent wrapper — recurse
            _collect_flat(child, soup, out)

        elif (
            child.name == "div"
            and classes
            and any(
                c in classes
                for c in (
                    "paragraph",
                    "ulist",
                    "olist",
                    "dlist",
                    "colist",
                    "tableblock",
                    "openblock",
                    # NOTE: do NOT include "literalblock" or "verseblock" here — they
                    # have dedicated normalizers (_normalize_listing_blocks, _normalize_verse_blocks)
                    # that need the wrapper present to attach syntax highlighting / blockquote class.
                )
            )
        ):
            # Asciidoctor wraps content in named divs — unwrap and keep inner content
            inner = child.find("div", class_="content", recursive=False) or child
            _collect_flat(inner, soup, out)

        else:
            # Regular content — keep as-is
            child.extract()
            out.append(child)


def _make_heading(soup: BeautifulSoup, level: int, sec_id: str, h_tag: Tag) -> Tag:
    """Create a pipeline-compatible heading element.

    Inline markup (``<strong>``, ``<em>``, ``<code>``, etc.) inside *h_tag* is
    preserved by moving the tag's children into the ``content_span`` rather than
    extracting plain text via ``get_text()``.
    """
    h = soup.new_tag(f"h{level}", id=sec_id)
    h["class"] = ["heading", "settled"]
    h["data-level"] = str(level)

    secno_span = soup.new_tag("span", attrs={"class": "secno"})
    secno_span.string = ""  # filled by renumber_annexes or left empty

    content_span = soup.new_tag("span", attrs={"class": "content"})
    for child in list(h_tag.children):
        child.extract()
        content_span.append(child)

    h.append(secno_span)
    h.append(content_span)
    return h


# ---------------------------------------------------------------------------
# Block normalization
# ---------------------------------------------------------------------------


def _normalize_blocks(soup: BeautifulSoup) -> None:
    """Normalize Asciidoctor block divs to pipeline-compatible classes/elements."""
    _normalize_admonitions(soup)
    _normalize_listing_blocks(soup)
    _normalize_image_blocks(soup)


def _normalize_admonitions(soup: BeautifulSoup) -> None:
    """Map Asciidoctor admonition classes to pipeline CSS classes."""
    # Asciidoctor: <div class="admonitionblock note">
    for div in soup.find_all("div", class_="admonitionblock"):
        classes = div.get("class") or []
        if "note" in classes or "tip" in classes:
            div["class"] = ["admonitionblock", "note"]
        elif "warning" in classes or "caution" in classes or "important" in classes:
            div["class"] = ["admonitionblock", "advisement"]


def _normalize_listing_blocks(soup: BeautifulSoup) -> None:
    """Ensure listing/source and literal blocks expose a pipeline-compatible ``<pre>``."""
    for block_class in ("listingblock", "literalblock"):
        for div in soup.find_all("div", class_=block_class):
            content_div = div.find("div", class_="content")
            if not content_div:
                continue
            pre = content_div.find("pre")
            if not pre:
                continue
            code = pre.find("code")
            if code:
                lang_classes = [c for c in (code.get("class") or []) if c.startswith("language-")]
                if lang_classes and "highlight" not in (pre.get("class") or []):
                    pre_classes = list(pre.get("class") or []) + lang_classes + ["highlight"]
                    pre["class"] = pre_classes
                    # Set the attribute form used by the pipeline for syntax highlighting
                    pre["highlight"] = lang_classes[0].removeprefix("language-")


def _normalize_image_blocks(soup: BeautifulSoup) -> None:
    """Wrap Asciidoctor ``<div class="imageblock">`` in ``<figure>`` elements."""
    for div in soup.find_all("div", class_="imageblock"):
        content_div = div.find("div", class_="content")
        title_div = div.find("div", class_="title")

        img = content_div.find("img") if content_div else None
        if not img:
            img = div.find("img")  # fallback: direct child or any descendant
        if not img:
            continue

        figure = soup.new_tag("figure")
        img.extract()
        figure.append(img)

        if title_div:
            caption_text = title_div.get_text(strip=True)
            figcaption = soup.new_tag("figcaption")
            figcaption.string = caption_text
            figure.append(figcaption)

        div.replace_with(figure)


# ---------------------------------------------------------------------------
# Container block normalization
# ---------------------------------------------------------------------------


def _normalize_container_blocks(soup: BeautifulSoup) -> None:
    """Normalize Asciidoctor example/sidebar/quote/verse blocks to semantic HTML."""
    _normalize_example_blocks(soup)
    _normalize_sidebar_blocks(soup)
    _normalize_quote_blocks(soup)
    _normalize_verse_blocks(soup)


def _normalize_example_blocks(soup: BeautifulSoup) -> None:
    """``<div class="exampleblock">`` → ``<div class="example">``."""
    for div in soup.find_all("div", class_="exampleblock"):
        content_div = div.find("div", class_="content")
        example = soup.new_tag("div")
        example["class"] = ["example"]
        if content_div:
            for child in list(content_div.children):
                child.extract()
                example.append(child)
        div.replace_with(example)


def _normalize_sidebar_blocks(soup: BeautifulSoup) -> None:
    """``<div class="sidebarblock">`` → ``<aside class="sidebar">``."""
    for div in soup.find_all("div", class_="sidebarblock"):
        content_div = div.find("div", class_="content")
        aside = soup.new_tag("aside")
        aside["class"] = ["sidebar"]
        if content_div:
            for child in list(content_div.children):
                child.extract()
                aside.append(child)
        div.replace_with(aside)


def _normalize_quote_blocks(soup: BeautifulSoup) -> None:
    """``<div class="quoteblock">`` → ``<blockquote>`` with optional ``<footer>``."""
    for div in soup.find_all("div", class_="quoteblock"):
        content_div = div.find("div", class_="content")
        attribution_div = div.find("div", class_="attribution")

        blockquote = soup.new_tag("blockquote")
        if content_div:
            for child in list(content_div.children):
                child.extract()
                blockquote.append(child)

        if attribution_div:
            footer = soup.new_tag("footer")
            for child in list(attribution_div.children):
                child.extract()
                footer.append(child)
            blockquote.append(footer)

        div.replace_with(blockquote)


def _normalize_verse_blocks(soup: BeautifulSoup) -> None:
    """``<div class="verseblock">`` → ``<blockquote class="verse">`` with inner ``<pre>``."""
    for div in soup.find_all("div", class_="verseblock"):
        content_div = div.find("div", class_="content")

        blockquote = soup.new_tag("blockquote")
        blockquote["class"] = ["verse"]

        if content_div:
            pre = content_div.find("pre")
            if pre:
                pre.extract()
                blockquote.append(pre)
            else:
                for child in list(content_div.children):
                    child.extract()
                    blockquote.append(child)

        div.replace_with(blockquote)

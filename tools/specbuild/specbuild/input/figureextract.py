"""Extract embedded images and pair them with figure captions.

Word documents embed images as binary relationships.  This module
extracts every image, saves it to an ``images/`` subdirectory, and then
pairs each image paragraph (``Figure Graphic``) with the nearest
``Figure title`` caption paragraph.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from docx.document import Document

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Image content types we recognise.
_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/bmp",
        "image/tiff",
        "image/svg+xml",
        "image/x-emf",
        "image/x-wmf",
    }
)

#: Map content-type to preferred file extension.
_EXT_MAP: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/svg+xml": ".svg",
    "image/x-emf": ".emf",
    "image/x-wmf": ".wmf",
}

#: Regex to extract a figure number from a caption string.
_FIG_NUM_RE = re.compile(r"(?:Figure|Fig\.?)\s+(\d+[\-\u2013]?\d*)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------


def extract_images(doc: Document, output_dir: Path) -> dict[str, Path]:
    """Extract all embedded images from a DOCX to ``output_dir/images/``.

    Args:
        doc:        A python-docx ``Document``.
        output_dir: Base directory; images are saved under ``images/``.

    Returns:
        Mapping from relationship ID (``rId3``, etc.) to the saved file path.
    """
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    rid_map: dict[str, Path] = {}
    image_count = 0

    for rel_id, rel in doc.part.rels.items():
        if rel.reltype and "image" in rel.reltype.lower():
            try:
                blob = rel.target_part.blob
                content_type = getattr(rel.target_part, "content_type", "")
                ext = _EXT_MAP.get(content_type, ".bin")

                # Use the original filename if available, else generate one
                orig_name = getattr(rel.target_part, "partname", None)
                if orig_name:
                    stem = Path(str(orig_name)).stem
                    fname = f"{stem}{ext}"
                else:
                    image_count += 1
                    fname = f"image_{image_count:04d}{ext}"

                dest = images_dir / fname
                dest.write_bytes(blob)
                rid_map[rel_id] = dest
            except Exception as exc:
                logging.warning(f"Failed to extract image {rel_id}: {exc}")

    logging.info(f"Extracted {len(rid_map)} images to {images_dir}")
    return rid_map


# ---------------------------------------------------------------------------
# Figure pairing
# ---------------------------------------------------------------------------


def _paragraph_has_image(paragraph) -> bool:
    """Check if a paragraph contains an inline image (blip)."""
    try:
        xml = paragraph._element.xml
        return "a:blip" in xml or "wp:inline" in xml or "wp:anchor" in xml
    except Exception:
        return False


def _extract_image_rid(paragraph) -> str | None:
    """Extract the relationship ID of the first image in a paragraph."""
    try:
        xml = paragraph._element.xml
        # Look for r:embed="rIdNN" inside a:blip
        m = re.search(r'r:embed="(rId\d+)"', xml)
        return m.group(1) if m else None
    except Exception:
        return None


def pair_figures(
    paragraphs: list,
    images: dict[str, Path],
    style_infos: list[dict] | None = None,
) -> list[dict]:
    """Pair Figure Graphic paragraphs with their Figure title captions.

    Walks the paragraph list looking for image-containing paragraphs
    followed or preceded by a ``Figure title`` caption.

    Args:
        paragraphs:  Ordered list of python-docx ``Paragraph`` objects.
        images:      Mapping from relationship ID to saved image path
                     (from :func:`extract_images`).
        style_infos: Optional parallel list of style classification dicts
                     (from :func:`~specbuild.input.stylemap.classify_paragraph`).

    Returns:
        List of figure dicts with keys: ``image_path``, ``caption``,
        ``figure_id``.
    """
    figures: list[dict] = []
    n = len(paragraphs)

    for i, para in enumerate(paragraphs):
        if not _paragraph_has_image(para):
            continue

        rid = _extract_image_rid(para)
        image_path = images.get(rid) if rid else None

        # Look for adjacent caption (next paragraph or previous)
        caption = ""
        figure_id = ""

        # Check next paragraph
        if i + 1 < n:
            next_style = ""
            if style_infos and i + 1 < len(style_infos):
                next_style = style_infos[i + 1].get("type", "")
            else:
                next_style_name = getattr(getattr(paragraphs[i + 1], "style", None), "name", "")
                from specbuild.input.stylemap import classify_paragraph

                next_style = classify_paragraph(next_style_name).get("type", "")

            if next_style == "figure_caption":
                caption = paragraphs[i + 1].text.strip()

        # Check previous paragraph if no caption found
        if not caption and i - 1 >= 0:
            prev_style = ""
            if style_infos and i - 1 < len(style_infos):
                prev_style = style_infos[i - 1].get("type", "")
            else:
                prev_style_name = getattr(getattr(paragraphs[i - 1], "style", None), "name", "")
                from specbuild.input.stylemap import classify_paragraph

                prev_style = classify_paragraph(prev_style_name).get("type", "")

            if prev_style == "figure_caption":
                caption = paragraphs[i - 1].text.strip()

        # Extract figure number from caption
        m = _FIG_NUM_RE.search(caption) if caption else None
        if m:
            # Normalize en-dashes and lowercase for ID consistency with xrefmap.py
            fig_num = m.group(1).replace("\u2013", "-").lower()
            figure_id = f"figure-{fig_num}"
        else:
            figure_id = f"figure-{len(figures) + 1}"

        figures.append(
            {
                "image_path": image_path,
                "caption": caption,
                "figure_id": figure_id,
            }
        )

    logging.info(f"Paired {len(figures)} figures with captions")
    return figures


# ---------------------------------------------------------------------------
# Bikeshed formatting
# ---------------------------------------------------------------------------


def format_figure_bs(fig: dict) -> str:
    """Format a figure for Bikeshed output.

    Args:
        fig: Dict with ``image_path``, ``caption``, ``figure_id``.

    Returns:
        Bikeshed ``<figure>`` markup.
    """
    fig_id = fig.get("figure_id", "figure-unknown")
    caption = fig.get("caption", "")
    image_path = fig.get("image_path")

    if image_path:
        # Use relative path from bikeshed source dir
        src = f"images/{Path(image_path).name}"
    else:
        src = "images/missing.png"

    lines: list[str] = [
        f'<figure id="{fig_id}">',
        f'  <img src="{src}" alt="{_escape_attr(caption)}">',
    ]
    if caption:
        lines.append(f"  <figcaption>{caption}</figcaption>")
    lines.append("</figure>")
    lines.append("")

    return "\n".join(lines)


def _escape_attr(text: str) -> str:
    """Escape text for use in an HTML attribute value."""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")

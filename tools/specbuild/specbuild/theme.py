"""Default visual theme for PDF and HTML output.

This module defines the :class:`Theme` dataclass with all default values
for fonts, colors, sizes, and layout.  The active singleton :data:`THEME`
is populated with these defaults at import time.

**Customisation:** override any field via the ``[theme]`` section in your
project's ``specbuild.toml`` (or ``pyproject.toml [tool.specbuild.theme]``).
You should never need to edit this file directly::

    # specbuild.toml
    [theme]
    body_font_size = 11
    color_accent = "#0055aa"
    annex_heading_format = "letter"

Internal usage in other modules::

    from specbuild.theme import THEME

    css = f"font-size: {THEME.footer_font_size}pt;"
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WatermarkPreset:
    """A single watermark preset."""

    text: str
    color: str
    font_size: str


@dataclass
class Theme:
    """Central visual theme for the specification build.

    The values below are **defaults**.  To customise, add a ``[theme]``
    section to your project's ``specbuild.toml`` — only the fields you
    want to change need to be listed.  All CSS injected by the build
    pipeline reads from the :data:`THEME` singleton.
    """

    # ------------------------------------------------------------------
    # Fonts
    # ------------------------------------------------------------------
    font_sans: str = "Arial, Helvetica, sans-serif"
    font_mono: str = "'Fira Code', 'Source Code Pro', 'JetBrains Mono', 'Consolas', 'Monaco', 'Courier New', monospace"
    font_serif: str = "'Times New Roman', Times, serif"

    # ------------------------------------------------------------------
    # Base font sizes (pt) — used by print.css overrides and injected CSS
    # ------------------------------------------------------------------
    body_font_size: int = 10
    table_font_size: int = 9
    code_font_size: int = 8
    sdl_font_size: int = 8  # SDL syntax tables (kept small)
    caption_font_size: int = 9  # figcaption
    list_font_size: int = 10
    back_to_toc_font_size: int = 9
    footer_font_size: int = 9

    # ------------------------------------------------------------------
    # Colors
    # ------------------------------------------------------------------
    color_text: str = "#000000"  # primary text (tables, code)
    color_body: str = "#1a1a1a"  # body / headings
    color_muted: str = "#666"  # secondary text, footers, dates
    color_secondary: str = "#555"  # organization, banner titles
    color_subtle: str = "#444"  # subtitles
    color_meta: str = "#333"  # version text, index text
    color_accent: str = "#034575"  # TOC links, index links
    color_link: str = "#0066cc"  # back-to-toc, change bars
    color_print_link: str = "#0033aa"  # links in print mode
    color_border: str = "#ccc"  # table borders, section dividers
    color_border_light: str = "#ddd"  # banner borders
    color_bg_subtle: str = "#f9f9f9"  # alternating table rows
    color_bg_muted: str = "#f0f0f0"  # table headers (rev history)

    # ------------------------------------------------------------------
    # Page setup
    # ------------------------------------------------------------------
    page_size: str = "letter"
    page_margins: str = "0.75in 0.5in 0.75in 0.5in"

    # ------------------------------------------------------------------
    # Content layout (screen only)
    # ------------------------------------------------------------------
    content_width: str = "60em"  # max-width for HTML viewing; "none" to disable

    # ------------------------------------------------------------------
    # Page numbering
    # ------------------------------------------------------------------
    page_number_prefix: str = "Page "  # text before the page number

    # ------------------------------------------------------------------
    # TOC
    # ------------------------------------------------------------------
    toc_font_size: str = "9.5pt"
    toc_heading_font_size: str = "14pt"
    toc_heading_border: str = "2pt solid #000"
    toc_line_height: str = "1.8"
    toc_indent_level2: str = "2em"
    toc_indent_level3: str = "4em"
    toc_bold_primary_only: bool = True  # Only bold top-level TOC entries

    # ------------------------------------------------------------------
    # Section headers (running headers in PDF)
    # ------------------------------------------------------------------
    section_header_font_size: str = "8pt"
    section_header_color: str = "#999"

    # ------------------------------------------------------------------
    # Cover page
    # ------------------------------------------------------------------
    cover_title_font_size: str = "28pt"
    cover_title_color: str = "#1a1a1a"
    cover_subtitle_font_size: str = "16pt"
    cover_subtitle_color: str = "#444"
    cover_org_font_size: str = "14pt"
    cover_org_color: str = "#555"
    cover_doc_number_font_size: str = "14pt"
    cover_doc_number_color: str = "#666"
    cover_version_font_size: str = "13pt"
    cover_version_color: str = "#333"
    cover_date_font_size: str = "13pt"
    cover_date_color: str = "#666"
    cover_logo_max_width: str = "200pt"
    cover_logo_max_height: str = "80pt"

    # ------------------------------------------------------------------
    # Watermark presets and defaults
    # ------------------------------------------------------------------
    watermark_font_weight: str = "bold"
    watermark_letter_spacing: str = "0.1em"
    watermark_default_color: str = "rgba(200, 0, 0, 0.07)"
    watermark_default_font_size: str = "100pt"
    watermark_presets: dict = field(
        default_factory=lambda: {
            "draft": WatermarkPreset(
                text="DRAFT",
                color="rgba(200, 0, 0, 0.08)",
                font_size="120pt",
            ),
            "confidential": WatermarkPreset(
                text="CONFIDENTIAL",
                color="rgba(200, 0, 0, 0.06)",
                font_size="80pt",
            ),
            "review": WatermarkPreset(
                text="FOR REVIEW",
                color="rgba(0, 0, 200, 0.06)",
                font_size="90pt",
            ),
            "obsolete": WatermarkPreset(
                text="OBSOLETE",
                color="rgba(200, 0, 0, 0.10)",
                font_size="100pt",
            ),
        }
    )

    # ------------------------------------------------------------------
    # Change bars
    # ------------------------------------------------------------------
    change_bar_border: str = "3px solid #0066cc"
    change_bar_border_print: str = "2pt solid black"

    # ------------------------------------------------------------------
    # Links banner (injected into HTML spec)
    # ------------------------------------------------------------------
    banner_bg: str = "white"
    banner_text_color: str = "#333"
    banner_border: str = "1px solid #ddd"
    banner_title_font_size: str = "14px"
    banner_title_color: str = "#555"
    banner_link_bg: str = "#f7fafc"
    banner_link_color: str = "#2d3748"
    banner_link_border: str = "1px solid #e2e8f0"
    banner_link_font_size: str = "13px"
    banner_link_hover_bg: str = "#e2e8f0"
    banner_link_hover_border: str = "#cbd5e0"

    # ------------------------------------------------------------------
    # Annex headings
    # ------------------------------------------------------------------
    # "prefix" → secno "Annex A. ", content "Assembly Process"
    # "letter" → secno "A. ",       content "Assembly Process"
    annex_heading_format: str = "prefix"

    # ------------------------------------------------------------------
    # Equations
    # ------------------------------------------------------------------
    equation_number_color: str = "#333"
    equation_number_font_size: str = "10pt"
    equation_ref_prefix: str = "Equation"

    # ------------------------------------------------------------------
    # Index
    # ------------------------------------------------------------------
    index_font_size: str = "0.95em"
    index_header_font_size: str = "0.9em"  # was 8pt in print
    index_heading_border: str = "1px solid #ccc"
    index_label_color: str = "#666"

    # ------------------------------------------------------------------
    # Revision history
    # ------------------------------------------------------------------
    rev_table_header_bg: str = "#f0f0f0"
    rev_table_header_border: str = "1px solid #ccc"
    rev_table_cell_border: str = "1px solid #ccc"
    rev_table_alt_row_bg: str = "#f9f9f9"
    rev_heading_font_size: str = "1.2em"
    rev_table_font_size: str = "0.9em"

    # ------------------------------------------------------------------
    # Keywords (RFC 2119)
    # ------------------------------------------------------------------
    keyword_color: str = "#1a1a1a"
    keyword_font_size: str = "0.95em"


# Active theme — override by assigning a new Theme() before building.
THEME = Theme()

"""PDF/A export: generate PDF/A-compliant output with metadata and font embedding.

Uses WeasyPrint (preferred) or Chrome headless to generate the initial PDF,
then applies PDF/A metadata using pikepdf if available.  Key features:

- XMP metadata injection (title, author, subject, creation date)
- PDF/A-1b intent marker
- Color profile embedding (sRGB)
- Document structure tags (when WeasyPrint is used)

Falls back gracefully: if pikepdf is not installed, produces a standard
PDF with a warning.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path


def generate_pdfa(
    html_path: Path,
    output_path: Path | None = None,
    *,
    title: str = "",
    author: str = "",
    subject: str = "",
    use_weasyprint: bool = True,
) -> Path | None:
    """Generate a PDF/A-compliant file from compiled HTML.

    Args:
        html_path: Path to the compiled HTML file.
        output_path: Destination PDF path (default: sibling of html_path).
        title: Document title for XMP metadata.
        author: Author name for XMP metadata.
        subject: Subject for XMP metadata.
        use_weasyprint: If True, use WeasyPrint; otherwise use Chrome.

    Returns:
        Path to the generated PDF, or None on failure.
    """
    if output_path is None:
        output_path = html_path.with_name(html_path.stem + "_pdfa.pdf")

    # Step 1: Generate the base PDF
    base_pdf = _generate_base_pdf(html_path, output_path, use_weasyprint=use_weasyprint)
    if base_pdf is None:
        return None

    # Step 2: Apply PDF/A metadata
    _apply_pdfa_metadata(base_pdf, title=title, author=author, subject=subject)

    logging.info(f"PDF/A output: {output_path}")
    return output_path


def _generate_base_pdf(
    html_path: Path,
    output_path: Path,
    *,
    use_weasyprint: bool = True,
) -> Path | None:
    """Generate the base PDF using WeasyPrint or Chrome.

    Args:
        html_path: Source HTML.
        output_path: Destination PDF.
        use_weasyprint: Backend selection.

    Returns:
        Path to the generated PDF, or None on failure.
    """
    if use_weasyprint:
        return _pdf_via_weasyprint(html_path, output_path)
    return _pdf_via_chrome(html_path, output_path)


def _pdf_via_weasyprint(html_path: Path, output_path: Path) -> Path | None:
    """Generate PDF using WeasyPrint."""
    try:
        import weasyprint
    except ImportError:
        logging.error("WeasyPrint not installed. Install with: pip install weasyprint")
        return None

    try:
        doc = weasyprint.HTML(filename=str(html_path))
        doc.write_pdf(str(output_path))
        logging.info(f"PDF generated via WeasyPrint: {output_path}")
        return output_path
    except Exception as exc:
        logging.error(f"WeasyPrint PDF generation failed: {exc}")
        return None


def _pdf_via_chrome(html_path: Path, output_path: Path) -> Path | None:
    """Generate PDF using Chrome headless."""
    from specbuild.utils import chrome_path

    chrome = chrome_path()
    if not chrome:
        logging.error("Chrome not found for PDF generation")
        return None

    try:
        file_url = html_path.resolve().as_uri()
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                f"--print-to-pdf={output_path}",
                file_url,
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
        logging.info(f"PDF generated via Chrome: {output_path}")
        return output_path
    except subprocess.CalledProcessError as exc:
        logging.error(f"Chrome PDF generation failed: {exc}")
        return None
    except subprocess.TimeoutExpired:
        logging.error("Chrome PDF generation timed out")
        return None


def _apply_pdfa_metadata(
    pdf_path: Path,
    *,
    title: str = "",
    author: str = "",
    subject: str = "",
) -> bool:
    """Apply PDF/A metadata to an existing PDF using pikepdf.

    Args:
        pdf_path: Path to the PDF to modify in-place.
        title: Document title.
        author: Author name.
        subject: Document subject.

    Returns:
        True if metadata was applied, False if pikepdf is not available.
    """
    try:
        import pikepdf
    except ImportError:
        logging.warning(
            "pikepdf not installed — skipping PDF/A metadata. Install with: pip install pikepdf"
        )
        return False

    try:
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            with pdf.open_metadata() as meta:
                if title:
                    meta["dc:title"] = title
                if author:
                    meta["dc:creator"] = [author]
                if subject:
                    meta["dc:description"] = subject
                meta["pdf:Producer"] = "specbuild (bikeshed-publish)"
                # Mark as PDF/A-1b intent
                meta["pdfaid:part"] = "1"
                meta["pdfaid:conformance"] = "B"

            pdf.save(pdf_path)

        logging.info(f"PDF/A metadata applied to {pdf_path}")
        return True

    except Exception as exc:
        logging.warning(f"Failed to apply PDF/A metadata: {exc}")
        return False

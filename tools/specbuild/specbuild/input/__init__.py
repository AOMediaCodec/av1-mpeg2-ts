"""Word/PDF to Bikeshed specification converter.

Provides :func:`import_docx` for high-fidelity conversion of Word documents
and :func:`import_pdf` for lower-fidelity PDF fallback.  Both produce a set
of ``.bs`` source files, a ``manifest.txt``, and a conversion quality report.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def import_docx(docx_path: Path, output_dir: Path, **options: Any) -> dict:
    """Convert a Word document to Bikeshed source files.

    Args:
        docx_path:  Path to the ``.docx`` file.
        output_dir: Directory to write the generated ``.bs`` files into.
        **options:  Forwarded to :func:`~specbuild.input.docximport.convert_docx`.

    Returns:
        Dict with keys ``bs_files``, ``manifest_path``, and ``report``.
    """
    from specbuild.input.docximport import convert_docx

    return convert_docx(docx_path, output_dir, **options)


def import_pdf(pdf_path: Path, output_dir: Path, **options: Any) -> dict:
    """Convert a PDF to Bikeshed source files (lower fidelity).

    Args:
        pdf_path:   Path to the ``.pdf`` file.
        output_dir: Directory to write the generated ``.bs`` files into.
        **options:  Forwarded to :func:`~specbuild.input.pdfimport.convert_pdf`.

    Returns:
        Dict with keys ``bs_files``, ``manifest_path``, and ``report``.
    """
    from specbuild.input.pdfimport import convert_pdf

    return convert_pdf(pdf_path, output_dir, **options)

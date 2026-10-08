"""AsciiDoc compilation via Asciidoctor with HTML normalization.

Provides a drop-in replacement for the Bikeshed compile path when
``source_format = "asciidoc"`` is configured.  Runs the ``asciidoctor``
command-line tool to produce raw HTML, then applies
:func:`specbuild.normalize_adoc.normalize_asciidoctor_html` to transform the
Asciidoctor-specific div structure into the shape expected by all downstream
pipeline modules.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from bs4 import BeautifulSoup

from specbuild.config import CONFIG
from specbuild.normalize_adoc import normalize_asciidoctor_html


def compile_adoc_spec(adoc_path: Path, *, output_html: Path | None = None) -> Path:
    """Compile an AsciiDoc file to a normalized pipeline-ready ``index.html``.

    Args:
        adoc_path: Path to the main ``.adoc`` entry-point file.
        output_html: Where to write the output HTML.  Defaults to
            ``index.html`` in the same directory as *adoc_path*.

    Returns:
        Path to the written HTML file.
    """
    if output_html is None:
        output_html = adoc_path.parent / "index.html"

    try:
        raw_html = _run_asciidoctor(adoc_path, output_html)
    except subprocess.CalledProcessError:
        if output_html.exists():
            output_html.unlink()
        raise
    if not raw_html.exists() or raw_html.stat().st_size == 0:
        raise RuntimeError(f"asciidoctor produced empty or no output: {raw_html}")
    soup = _load_and_normalize(raw_html)
    output_html.write_text(str(soup), encoding="utf-8")
    logging.info(f"AsciiDoc compiled and normalized → {output_html}")
    return output_html


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_asciidoctor(adoc_path: Path, out_html: Path) -> Path:
    """Run ``asciidoctor`` to convert *adoc_path* to raw HTML at *out_html*.

    Attributes used:
    - ``sectnums``   — automatic section numbering
    - ``toc``        — inline table of contents
    - ``appendix-caption=Annex`` — ISO convention
    - ``stylesheet=``  — no embedded CSS (pipeline supplies its own)
    """
    cmd = [
        CONFIG.asciidoctor_bin,
        "-b",
        "html5",
        "-B",
        str(adoc_path.parent),
        "-a",
        "sectnums",
        "-a",
        "toc",
        "-a",
        "toc-placement=left",
        "-a",
        "appendix-caption=Annex",
        "-a",
        "stylesheet=",  # suppress embedded stylesheet
        "-o",
        str(out_html),
        str(adoc_path),
    ]
    logging.info(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if result.stderr.strip():
            for line in result.stderr.splitlines():
                if line.startswith("ERROR:"):
                    logging.error(line)
                elif line.startswith("WARNING:"):
                    logging.warning(line)
                else:
                    logging.debug(line)
    except FileNotFoundError:
        raise RuntimeError(
            "asciidoctor not found. Install it with: gem install asciidoctor"
        ) from None
    except subprocess.CalledProcessError as e:
        logging.error(f"asciidoctor failed:\n{e.stderr}")
        raise
    return out_html


def _load_and_normalize(html_path: Path) -> BeautifulSoup:
    """Parse *html_path* with BeautifulSoup and normalize the Asciidoctor HTML."""
    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html5lib")
    normalize_asciidoctor_html(soup)
    return soup


def locate_adoc_entry_point(base_dir: Path | None = None) -> Path:
    """Locate the main ``.adoc`` file according to config settings.

    Tries (in order):
    1. ``CONFIG.asciidoc_dir / CONFIG.main_adoc_file``
    2. Any single ``.adoc`` file in ``CONFIG.asciidoc_dir``
    3. ``CONFIG.main_adoc_file`` in CWD

    Raises ``FileNotFoundError`` if none found.
    """
    root = base_dir or Path(".")
    adoc_dir = root / CONFIG.asciidoc_dir
    candidate = adoc_dir / CONFIG.main_adoc_file
    if candidate.exists():
        return candidate.resolve()

    if adoc_dir.is_dir():
        adoc_files = list(adoc_dir.glob("*.adoc"))
        if len(adoc_files) == 1:
            return adoc_files[0].resolve()

    cwd_candidate = root / CONFIG.main_adoc_file
    if cwd_candidate.exists():
        return cwd_candidate.resolve()

    raise FileNotFoundError(
        f"Could not find main AsciiDoc file. "
        f"Tried {candidate}, {adoc_dir}/*.adoc, {cwd_candidate}. "
        f"Set main_adoc_file in specbuild.toml."
    )

"""Source format detection for transparent input handling.

Determines whether a given path contains a Bikeshed project (.bs files with
manifest.txt), a plain AsciiDoc project (an ``adoc/`` directory with .adoc
files but no Metanorma attributes), or a Metanorma/AsciiDoc project (.adoc
files with :docnumber: or similar ISO attributes).
"""

from __future__ import annotations

import re
from pathlib import Path

# AsciiDoc/Metanorma indicators in a .adoc file
_METANORMA_PATTERNS = re.compile(
    r"^(?::docnumber:|:doctype:|:mn-document-class:|= .+\n\n:)"
    r"|^= .+$",
    re.MULTILINE,
)
_METANORMA_ATTR_RE = re.compile(
    r"^:(?:docnumber|doctype|mn-document-class|partnumber|edition):", re.MULTILINE
)

# Bikeshed metadata block marker
_BIKESHED_META_RE = re.compile(r"<pre\s+class=['\"]metadata['\"]", re.IGNORECASE)

# Directories to exclude from recursive .adoc search
_SKIP_DIRS = frozenset(
    {"venv", ".venv", ".git", "node_modules", "__pycache__", ".tox", "dist", "build"}
)


def detect_source_format(path: str | Path) -> str:
    """Return the source format of the given path.

    Returns one of:
    - ``"bikeshed"``  — directory or file is a Bikeshed project
    - ``"asciidoc"``  — directory has an ``adoc/`` subdirectory with .adoc files
                        (plain AsciiDoc, not Metanorma)
    - ``"metanorma"`` — directory or file is a Metanorma/AsciiDoc project
    - ``"unknown"``   — cannot determine

    Detection rules:
    - Directory with ``bikeshed/manifest.txt`` → bikeshed
    - Directory with ``.bs`` files → bikeshed
    - ``.bs`` file with ``<pre class='metadata'>`` → bikeshed
    - Directory with ``adoc/`` subdirectory containing .adoc files → asciidoc
    - Directory with ``.adoc`` files containing Metanorma attributes → metanorma
    - ``.adoc`` file with Metanorma attributes → metanorma
    """
    p = Path(path)
    if not p.exists():
        return "unknown"

    if p.is_file():
        return _detect_file(p)

    return _detect_directory(p)


def _detect_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".bs":
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if _BIKESHED_META_RE.search(text):
                return "bikeshed"
        except OSError:
            pass
        return "bikeshed"  # .bs extension is a strong signal on its own

    if suffix == ".adoc":
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                return "unknown"
            if _METANORMA_ATTR_RE.search(text):
                return "metanorma"
        except OSError:
            pass
        return "asciidoc"  # .adoc with no Metanorma attributes is plain AsciiDoc

    return "unknown"


def _detect_directory(path: Path) -> str:
    # Explicit Bikeshed project: bikeshed/manifest.txt exists
    if (path / "bikeshed" / "manifest.txt").exists():
        return "bikeshed"

    # Any .bs file is a strong Bikeshed signal
    bs_files = list(path.glob("*.bs")) + list(path.glob("bikeshed/*.bs"))
    if bs_files:
        return "bikeshed"

    # Plain AsciiDoc project: adoc/ directory present with .adoc files
    adoc_subdir = path / "adoc"
    if adoc_subdir.is_dir() and next(adoc_subdir.glob("*.adoc"), None) is not None:
        return "asciidoc"

    # Look for .adoc files with Metanorma attributes
    adoc_files = list(path.glob("*.adoc"))
    if adoc_files:
        for adoc in adoc_files:
            try:
                text = adoc.read_text(encoding="utf-8", errors="replace")
                if _METANORMA_ATTR_RE.search(text):
                    return "metanorma"
            except OSError:
                continue
        # Any .adoc files found — likely Metanorma even without the exact attrs
        return "metanorma"

    # Check one level down for .adoc files (e.g., sections/), excluding tool dirs
    adoc_nested = [
        f
        for f in path.glob("**/*.adoc")
        if not any(part in _SKIP_DIRS for part in f.relative_to(path).parts)
    ]
    if adoc_nested:
        return "metanorma"

    return "unknown"


def _count_attrs(f: Path) -> int:
    """Return the number of Metanorma attributes in *f*, or 0 on read error."""
    try:
        return len(_METANORMA_ATTR_RE.findall(f.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return 0


def find_main_adoc(path: Path) -> Path | None:
    """Return the most likely main .adoc file in a Metanorma project directory."""
    if path.is_file() and path.suffix.lower() == ".adoc":
        return path

    adoc_files = list(path.glob("*.adoc"))
    if not adoc_files:
        return None
    if len(adoc_files) == 1:
        return adoc_files[0]

    # Prefer the file with the most Metanorma attributes (most likely the main doc)
    return max(adoc_files, key=_count_attrs)

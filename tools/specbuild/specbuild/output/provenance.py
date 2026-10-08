"""Build provenance: emit ``provenance.json`` for ISO archival reproducibility.

Captures every input that materially affected the build (source ``.bs`` files
plus assets such as ``css/``, ``js/``, ``images/``), the versions of the tools
involved (specbuild, bikeshed, Python, pandoc, git), and a sha256 hash of the
final compiled HTML.  The result is written next to the build output as
``provenance.json``.

The output is byte-for-byte deterministic for identical inputs (sorted keys,
fixed indentation, UTF-8) so that two reproducible builds yield identical
manifests.

Usage::

    python compile.py --provenance       # writes provenance.json next to index.html
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Schema version of the ``provenance.json`` document produced by this module.
SCHEMA_VERSION = 1

#: Maximum seconds to wait for any tool-version subprocess.
_TOOL_TIMEOUT = 10

#: Path components that should never be hashed (caches, hidden files).
_EXCLUDE_DIRS = {"__pycache__", ".git", ".DS_Store"}


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    """Return the sha256 hex digest of *path*."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_excluded(path: Path) -> bool:
    """Return True if *path* should be skipped (hidden file or cache dir)."""
    for part in path.parts:
        if part in _EXCLUDE_DIRS:
            return True
        if part.startswith(".") and part not in (".", ".."):
            return True
    return False


def compute_input_hashes(bs_dir: Path, asset_dirs: list[Path]) -> dict[str, str]:
    """Compute sha256 of every Bikeshed source and asset file.

    Hashes every ``.bs`` file under *bs_dir* (recursive) plus every file under
    each directory in *asset_dirs* (typically ``css/``, ``js/``, ``images/``).
    Hidden files and ``__pycache__`` directories are excluded.

    Paths in the returned manifest are stored relative to their owning
    source root: ``.bs`` files are relativised against *bs_dir*, and each
    asset file is relativised against the asset directory it lives under.
    The previous implementation relativised against the current working
    directory, which made two reproducible builds in different home
    directories (or different CWDs) produce different ``provenance.json``
    files — defeating the whole point of provenance.

    Args:
        bs_dir: Directory containing the ``.bs`` source files.
        asset_dirs: Asset directories to hash (each scanned recursively).

    Returns:
        Mapping of POSIX-style relative path → sha256 hex digest, sorted by key.
    """
    hashes: dict[str, str] = {}

    bs_dir = Path(bs_dir)
    if bs_dir.is_dir():
        for path in sorted(bs_dir.rglob("*.bs")):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(bs_dir)
            except ValueError:
                # Symlinks pointing outside bs_dir: store the absolute path
                # as a last resort.  This keeps the hash record useful but
                # means the manifest is not fully reproducible across hosts
                # for that one file (a strange setup).
                rel = path
            if _is_excluded(rel):
                continue
            hashes[rel.as_posix()] = _sha256_file(path)

    for asset_dir in asset_dirs:
        asset_dir = Path(asset_dir)
        if not asset_dir.is_dir():
            continue
        for path in sorted(asset_dir.rglob("*")):
            if not path.is_file():
                continue
            try:
                # Relativise against the asset-dir's *parent* so the asset
                # directory's name (``css``, ``images``, …) is included in
                # the manifest key — otherwise two assets named
                # ``style.css`` in ``css/`` and ``vendor/`` would collide.
                rel = path.relative_to(asset_dir.parent)
            except ValueError:
                try:
                    rel = path.relative_to(asset_dir)
                except ValueError:
                    rel = path
            if _is_excluded(rel):
                continue
            hashes[rel.as_posix()] = _sha256_file(path)

    # Return a key-sorted dict for determinism
    return dict(sorted(hashes.items()))


def compute_output_hash(html_path: Path) -> str:
    """Return the sha256 hex digest of the final compiled HTML file."""
    return _sha256_file(Path(html_path))


# ---------------------------------------------------------------------------
# Tool versions
# ---------------------------------------------------------------------------


def _first_line(text: str) -> str:
    """Return the first non-empty line of *text*, stripped."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _capture_version(cmd: list[str]) -> str:
    """Run *cmd* and return its first stdout line, or "unknown" on any failure."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        logging.debug(f"provenance: failed to capture version of {cmd!r}: {exc}")
        return "unknown"

    if result.returncode != 0:
        return "unknown"

    return _first_line(result.stdout) or _first_line(result.stderr) or "unknown"


def compute_tool_versions() -> dict[str, str]:
    """Capture tool versions for the provenance manifest.

    Reports the version of ``specbuild`` (from ``specbuild.__version__`` if it
    exists), ``bikeshed``, ``python``, ``pandoc``, and ``git``.  Any tool that
    cannot be invoked yields ``"unknown"`` rather than raising.

    Returns:
        Dict with deterministic key ordering: specbuild, bikeshed, python,
        pandoc, git.
    """
    # specbuild — read from __version__ if exposed, else "unknown"
    try:
        import specbuild as _specbuild_pkg

        specbuild_version = getattr(_specbuild_pkg, "__version__", "unknown")
    except Exception:  # noqa: BLE001 — never let import errors break provenance
        specbuild_version = "unknown"

    py_info = sys.version_info
    python_version = f"{py_info.major}.{py_info.minor}.{py_info.micro}"

    return {
        "specbuild": str(specbuild_version),
        "bikeshed": _capture_version(["bikeshed", "--version"]),
        "python": python_version,
        "pandoc": _capture_version(["pandoc", "--version"]),
        "git": _capture_version(["git", "--version"]),
    }


# ---------------------------------------------------------------------------
# Manifest assembly + write
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """Return current UTC time as an ISO 8601 string with seconds precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_provenance(
    out_dir: Path,
    *,
    bs_dir: Path,
    html_path: Path,
    asset_dirs: list[Path],
    build_identity: dict[str, str],
) -> Path:
    """Assemble and write ``provenance.json`` to *out_dir*.

    Args:
        out_dir: Directory to write ``provenance.json`` into.
        bs_dir: Directory containing the Bikeshed ``.bs`` source files.
        html_path: Path to the final compiled HTML output.
        asset_dirs: Asset directories that contributed to the build (hashed).
        build_identity: Mapping with at least ``branch``, ``sha``, ``date``,
            ``spec_name`` (extra keys are preserved verbatim).

    Returns:
        Absolute path to the written ``provenance.json`` file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tool_versions = compute_tool_versions()
    inputs = compute_input_hashes(Path(bs_dir), [Path(a) for a in asset_dirs])
    output_sha = compute_output_hash(Path(html_path)) if Path(html_path).is_file() else "unknown"

    manifest: dict = {
        "schema_version": SCHEMA_VERSION,
        "tool": {
            "name": "specbuild",
            "version": tool_versions.get("specbuild", "unknown"),
        },
        "build_identity": dict(sorted(build_identity.items())),
        "tool_versions": {
            "bikeshed": tool_versions["bikeshed"],
            "python": tool_versions["python"],
            "pandoc": tool_versions["pandoc"],
            "git": tool_versions["git"],
        },
        "inputs": inputs,
        "output": {
            "path": Path(html_path).name,
            "sha256": output_sha,
        },
        "generated_at": _utc_now_iso(),
    }

    target = out_dir / "provenance.json"
    # sort_keys + fixed indent + trailing newline → byte-for-byte stable output.
    target.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return target

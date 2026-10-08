"""Image optimization pipeline: compress and optimize images in build output.

Supports:
- PNG compression via ``pngquant`` or ``optipng`` (if available on PATH)
- SVG optimization by stripping editor metadata, comments, and unnecessary attributes
- Size reporting with before/after comparison

External tools are optional — the pipeline degrades gracefully when they are
not installed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def optimize_images(
    build_dir: Path,
    *,
    png: bool = True,
    svg: bool = True,
) -> dict:
    """Optimize images in the build output directory.

    Args:
        build_dir: Path to the build output directory.
        png: Whether to optimize PNG files.
        svg: Whether to optimize SVG files.

    Returns:
        Dict with keys:

        - ``png_files``: list of dicts with ``path``, ``original_size``,
          ``optimized_size``
        - ``svg_files``: list of dicts with ``path``, ``original_size``,
          ``optimized_size``
        - ``total_saved``: total bytes saved
        - ``tool``: name of the PNG optimization tool used (or None)
    """
    result: dict = {
        "png_files": [],
        "svg_files": [],
        "total_saved": 0,
        "tool": None,
    }

    if png:
        png_tool = _detect_png_tool()
        result["tool"] = png_tool
        png_paths = list(build_dir.rglob("*.png"))
        for info in _run_in_parallel(lambda p: _safe_optimize_png(p, png_tool), png_paths):
            if info:
                result["png_files"].append(info)
                result["total_saved"] += info["original_size"] - info["optimized_size"]

    if svg:
        svg_paths = list(build_dir.rglob("*.svg"))
        for info in _run_in_parallel(_safe_optimize_svg, svg_paths):
            if info:
                result["svg_files"].append(info)
                result["total_saved"] += info["original_size"] - info["optimized_size"]

    total_files = len(result["png_files"]) + len(result["svg_files"])
    saved_kb = result["total_saved"] / 1024
    if total_files > 0:
        logging.info(
            f"Image optimization: {total_files} file(s) processed, {saved_kb:.1f} KB saved"
        )
    else:
        logging.info("Image optimization: no images found to optimize")

    return result


# ---------------------------------------------------------------------------
# Parallel execution helpers
# ---------------------------------------------------------------------------


def _run_in_parallel(fn, items):
    """Run ``fn(item)`` for every *item* using a thread pool.

    Order of returned results matches the input order.  Workers default to
    ``os.cpu_count()`` (with a sane fallback).  Single-item lists short-
    circuit to a direct call to avoid pool overhead.  Errors raised by *fn*
    are swallowed and surfaced as a logged warning, mirroring the per-item
    try/except in the original sequential loop.
    """
    if not items:
        return []
    if len(items) == 1:
        return [fn(items[0])]
    workers = os.cpu_count() or 1
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(fn, items))


def _safe_optimize_png(png_path: Path, tool: str | None) -> dict | None:
    """Wrapper around :func:`_optimize_png` that never raises."""
    try:
        return _optimize_png(png_path, tool)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning(f"PNG optimization failed for {png_path}: {exc}")
        return None


def _safe_optimize_svg(svg_path: Path) -> dict | None:
    """Wrapper around :func:`_optimize_svg` that never raises."""
    try:
        return _optimize_svg(svg_path)
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning(f"SVG optimization failed for {svg_path}: {exc}")
        return None


def report_optimization(result: dict) -> None:
    """Log optimization results in detail.

    Args:
        result: Dict from :func:`optimize_images`.
    """
    if result["tool"]:
        logging.info(f"PNG optimization tool: {result['tool']}")
    elif result["png_files"]:
        logging.info("PNG optimization: no tool available (install pngquant or optipng)")

    for info in result["png_files"]:
        pct = _pct_saved(info["original_size"], info["optimized_size"])
        logging.info(
            f"  PNG {info['path']}: {info['original_size']} -> {info['optimized_size']} ({pct})"
        )

    for info in result["svg_files"]:
        pct = _pct_saved(info["original_size"], info["optimized_size"])
        logging.info(
            f"  SVG {info['path']}: {info['original_size']} -> {info['optimized_size']} ({pct})"
        )

    saved_kb = result["total_saved"] / 1024
    logging.info(f"Total saved: {saved_kb:.1f} KB")


# ---------------------------------------------------------------------------
# PNG optimization
# ---------------------------------------------------------------------------


def _detect_png_tool() -> str | None:
    """Detect available PNG optimization tool."""
    for tool in ("pngquant", "optipng"):
        if shutil.which(tool):
            return tool
    return None


def _optimize_png(png_path: Path, tool: str | None) -> dict | None:
    """Optimize a single PNG file.

    Returns:
        Dict with path, original_size, optimized_size or None if skipped.
    """
    original_size = png_path.stat().st_size
    if original_size == 0:
        return None

    if tool == "pngquant":
        try:
            subprocess.run(
                [
                    "pngquant",
                    "--force",
                    "--ext",
                    ".png",
                    "--skip-if-larger",
                    "--quality",
                    "65-90",
                    str(png_path),
                ],
                capture_output=True,
                timeout=30,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    elif tool == "optipng":
        try:
            subprocess.run(
                ["optipng", "-o2", "-quiet", str(png_path)],
                capture_output=True,
                timeout=60,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
    else:
        # No tool available — just report file info
        return {
            "path": str(png_path),
            "original_size": original_size,
            "optimized_size": original_size,
        }

    try:
        optimized_size = png_path.stat().st_size
    except OSError:
        return None
    return {
        "path": str(png_path),
        "original_size": original_size,
        "optimized_size": optimized_size,
    }


# ---------------------------------------------------------------------------
# SVG optimization
# ---------------------------------------------------------------------------

# Patterns for strippable content in SVGs
_SVG_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_SVG_METADATA_RE = re.compile(r"<metadata[^>]*>.*?</metadata>", re.DOTALL | re.IGNORECASE)
_SVG_EDITOR_ATTRS_RE = re.compile(
    r"\s+(?:inkscape|sodipodi|xmlns:inkscape|xmlns:sodipodi|"
    r'xmlns:dc|xmlns:cc|xmlns:rdf|xmlns:svg):[a-zA-Z-]+=(?:"[^"]*"|\'[^\']*\')',
)
_SVG_EXCESS_WHITESPACE_RE = re.compile(r">\s+<")
_SVG_EMPTY_GROUP_RE = re.compile(r"<g[^>]*/>")


def _optimize_svg(svg_path: Path) -> dict | None:
    """Optimize a single SVG file by stripping unnecessary content.

    Returns:
        Dict with path, original_size, optimized_size or None if skipped.
    """
    try:
        content = svg_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None

    original_size = svg_path.stat().st_size
    if original_size == 0:
        return None

    optimized = content
    # Strip XML comments
    optimized = _SVG_COMMENT_RE.sub("", optimized)
    # Strip <metadata> blocks
    optimized = _SVG_METADATA_RE.sub("", optimized)
    # Strip editor-specific attributes (Inkscape, Sodipodi)
    optimized = _SVG_EDITOR_ATTRS_RE.sub("", optimized)
    # Remove empty groups
    optimized = _SVG_EMPTY_GROUP_RE.sub("", optimized)
    # Compress whitespace between tags
    optimized = _SVG_EXCESS_WHITESPACE_RE.sub("><", optimized)
    # Remove trailing whitespace on lines
    optimized = re.sub(r"[ \t]+\n", "\n", optimized)
    # Collapse multiple blank lines
    optimized = re.sub(r"\n{3,}", "\n\n", optimized)

    optimized_size = len(optimized.encode("utf-8"))

    # Only write if we actually saved something
    if optimized_size < original_size:
        svg_path.write_text(optimized, encoding="utf-8")

    return {
        "path": str(svg_path),
        "original_size": original_size,
        "optimized_size": min(original_size, optimized_size),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pct_saved(original: int, optimized: int) -> str:
    """Format percentage saved."""
    if original == 0:
        return "0%"
    pct = (1 - optimized / original) * 100
    return f"-{pct:.1f}%"

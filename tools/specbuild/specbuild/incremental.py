"""Incremental build support: skip compilation and enhancements when unchanged.

Two levels of caching are provided:

1. **Source hash** — skip Bikeshed compilation if ``.bs`` sources, manifest,
   and CSS/JS assets are unchanged.
2. **Enhancement hash** — skip HTML enhancement passes (equation numbering,
   change bars, tooltips, line anchors, etc.) if the compiled HTML and the
   set of enhancement flags are unchanged since the last build.

Both hashes are stored in a single JSON cache file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG

# Cache file storing the hash of all source files from the last build.
_CACHE_FILE = ".specbuild_cache.json"

# Read buffer size (bytes) for SHA-256 file hashing.
_HASH_READ_SIZE = 8192

# Asset directories whose changes should invalidate the build cache.
_ASSET_DIRS = ("css", "js")

# File extensions to include when hashing asset directories.
_ASSET_EXTENSIONS = (".css", ".js")

# Configuration files whose changes should invalidate the build cache.
_CONFIG_FILES = ("specbuild.toml", "config/sdl_descriptors.cfg", "pyproject.toml")

# CLI flags that affect the enhancement pass.  When any of these change
# between builds the enhancement cache is invalidated.
_ENHANCEMENT_FLAGS = (
    "number_equations",
    "iso_numbering",
    "change_bars",
    "revision_history",
    "index",
    "highlight_keywords",
    "figure_table_tooltips",
    "syntax_tooltips",
    "toc_bold_primary_only",
    "line_anchors",
    "line_numbers",
    "pwa",
    "watermark",
    "cover_page",
    "cover_title",
    "cover_subtitle",
    "cover_doc_number",
    "cover_organization",
    "cover_logo",
    "page_numbers",
    "stability",
    "typography",
    "term_links",
    "smart_xrefs",
    "pseudocode",
    "copy_code_buttons",
    "autolink",
    "math_symbols",
    "validate_refs",
    "validate_refs_strict",
    "validate_sdl_refs",
    "validate_sdl_refs_strict",
    "check_terminology",
    "check_orphan_refs",
    "check_orphan_refs_strict",
    "check_images",
    "check_images_strict",
    "table_of_changes",
)


def _hash_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file's contents."""
    if sys.version_info >= (3, 11):
        # ``hashlib.file_digest`` reads in optimal-sized chunks internally
        # and avoids the Python-level loop over ``f.read``.
        with open(path, "rb") as f:
            return hashlib.file_digest(f, "sha256").hexdigest()
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_READ_SIZE), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_files_parallel(paths: list[Path]) -> list[str]:
    """Return SHA-256 digests for *paths* in the same order as the input.

    Hashing is I/O bound, so a thread pool delivers near-linear speedup on
    large source trees.  Single-file lists short-circuit to avoid pool
    overhead.
    """
    if not paths:
        return []
    if len(paths) == 1:
        return [_hash_file(paths[0])]
    workers = min(len(paths), (os.cpu_count() or 1) * 2)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(_hash_file, paths))


def compute_source_hash(bikeshed_dir: str = None, manifest_path: Path = None) -> str:
    """Compute a combined hash of all .bs source files and the manifest.

    Args:
        bikeshed_dir: Path to the bikeshed source directory.
        manifest_path: Path to the manifest file (if any).

    Returns:
        A hex digest representing the current state of all source files.
    """
    bs_dir = Path(bikeshed_dir or CONFIG.bikeshed_dir)
    combined = hashlib.sha256()

    # ------------------------------------------------------------------
    # Gather every file we need to hash, in the deterministic order the
    # combined digest expects, then hash them concurrently.  The combine
    # step that follows runs sequentially in this exact order so the
    # final digest matches the original implementation byte-for-byte.
    # ------------------------------------------------------------------
    keys: list[str] = []
    paths: list[Path] = []

    bs_files = sorted(bs_dir.glob("*.bs"))
    for bs_file in bs_files:
        keys.append(bs_file.name)
        paths.append(bs_file)

    if manifest_path and manifest_path.exists():
        keys.append("__manifest__")
        paths.append(manifest_path)

    footer = bs_dir / "footer.include"
    if footer.exists():
        keys.append("__footer__")
        paths.append(footer)

    asset_entries: list[tuple[str, Path]] = []
    for asset_dir_name in _ASSET_DIRS:
        asset_dir = PROJECT_ROOT / asset_dir_name
        if asset_dir.is_dir():
            for ext in _ASSET_EXTENSIONS:
                for asset_file in sorted(asset_dir.glob(f"*{ext}")):
                    asset_entries.append((f"{asset_dir_name}/{asset_file.name}", asset_file))
    for name, path in asset_entries:
        keys.append(f"__asset__:{name}")
        paths.append(path)

    config_entries: list[tuple[str, Path]] = []
    for config_name in _CONFIG_FILES:
        config_file = PROJECT_ROOT / config_name
        if config_file.exists():
            config_entries.append((config_name, config_file))
    for name, path in config_entries:
        keys.append(f"__config__:{name}")
        paths.append(path)

    digests = _hash_files_parallel(paths)

    # Reproduce the original combine ordering exactly.
    digest_iter = iter(digests)
    for bs_file in bs_files:
        combined.update(f"{bs_file.name}:{next(digest_iter)}\n".encode())

    if manifest_path and manifest_path.exists():
        combined.update(f"manifest:{next(digest_iter)}\n".encode())

    if footer.exists():
        combined.update(f"footer:{next(digest_iter)}\n".encode())

    for name, _ in asset_entries:
        combined.update(f"{name}:{next(digest_iter)}\n".encode())

    for name, _ in config_entries:
        combined.update(f"config/{name}:{next(digest_iter)}\n".encode())

    # Include the specbuild package version so that a code-only change (e.g.
    # a bug fix in a plugin) invalidates the cache even when no source .bs or
    # asset file was touched.
    try:
        import importlib.metadata as _meta

        _version = _meta.version("specbuild")
    except Exception:
        _version = "unknown"
    combined.update(f"specbuild-version:{_version}\n".encode())

    return combined.hexdigest()


def load_cache() -> dict:
    """Load the build cache from disk.

    Returns:
        Dict with cache data, or empty dict if no cache exists.
    """
    cache_path = Path(_CACHE_FILE)
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(source_hash: str, output_dir: str, *, enhancement_hash: str | None = None) -> None:
    """Save the build cache to disk.

    Existing keys (e.g., a previously written ``enhancement_hash``) are preserved
    when this function is called without that parameter, so a crash between the
    compile and enhancement phases doesn't wipe valid cache state.

    Args:
        source_hash: The hash of the source files.
        output_dir: The output directory name from this build.
        enhancement_hash: Optional hash of enhancement flags + HTML content.
    """
    cache = load_cache()
    cache["source_hash"] = source_hash
    cache["output_dir"] = output_dir
    if enhancement_hash is not None:
        cache["enhancement_hash"] = enhancement_hash
    try:
        with open(Path(_CACHE_FILE), "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except OSError as e:
        logging.warning(f"Could not save build cache: {e}")


def should_skip_compile(manifest_path: Path = None) -> tuple[bool, str, str]:
    """Check whether the bikeshed compilation can be skipped.

    Args:
        manifest_path: Path to the manifest file (if any).

    Returns:
        Tuple of (can_skip, reason_string, current_source_hash).
    """
    current_hash = compute_source_hash(manifest_path=manifest_path)

    cache = load_cache()
    if not cache or "source_hash" not in cache:
        return False, "no build cache found", current_hash

    cached_hash = cache["source_hash"]

    if cached_hash != current_hash:
        return False, "source files have changed", current_hash

    # Also verify the output still exists
    output_dir = cache.get("output_dir", "")
    if output_dir and not Path(output_dir).exists():
        return False, f"output directory '{output_dir}' no longer exists", current_hash

    index_html = Path(output_dir) / "index.html" if output_dir else None
    if index_html and not index_html.exists():
        return False, "index.html not found in output directory", current_hash

    return True, f"sources unchanged (cached: {output_dir})", current_hash


# ---------------------------------------------------------------------------
# Enhancement-level caching
# ---------------------------------------------------------------------------


def compute_enhancement_hash(html_path: Path, args: object) -> str:
    """Compute a hash that captures the enhancement inputs.

    Combines the SHA-256 of the compiled HTML file with a digest of
    enhancement-related CLI flags.  If either the HTML content or the
    flags change, the hash changes and enhancements must re-run.

    Args:
        html_path: Path to the compiled ``index.html``.
        args: Parsed CLI namespace (from :mod:`argparse`).

    Returns:
        A hex digest string.
    """
    h = hashlib.sha256()

    # Hash the HTML content
    if html_path.exists():
        h.update(f"html:{_hash_file(html_path)}\n".encode())

    # Hash the enhancement flags
    for flag_name in _ENHANCEMENT_FLAGS:
        value = getattr(args, flag_name, None)
        if value is not None:
            h.update(f"{flag_name}={value}\n".encode())

    return h.hexdigest()


def should_skip_enhancements(html_path: Path, args: object) -> tuple[bool, str]:
    """Check whether the enhancement passes can be skipped.

    Compares the current enhancement hash against the cached one.
    Enhancements can be skipped only when the compiled HTML *and* all
    enhancement-related CLI flags are identical to the previous build.

    Args:
        html_path: Path to the compiled ``index.html``.
        args: Parsed CLI namespace.

    Returns:
        Tuple of ``(can_skip, reason_string)``.
    """
    current_hash = compute_enhancement_hash(html_path, args)

    cache = load_cache()
    cached_hash = cache.get("enhancement_hash")

    if not cached_hash:
        return False, "no enhancement cache"

    if cached_hash != current_hash:
        return False, "enhancement inputs changed"

    return True, "enhancements unchanged (cached)"

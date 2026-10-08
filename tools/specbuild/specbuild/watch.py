"""Watch mode: auto-rebuild when source files change."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from specbuild.config import CONFIG


def _get_mtimes(bikeshed_dir: str = None, manifest_path: Path = None) -> dict[str, float]:
    """Get modification times for all source files.

    Returns:
        Dict mapping file path strings to their mtime.
    """
    bs_dir = Path(bikeshed_dir or CONFIG.bikeshed_dir)
    mtimes = {}

    for bs_file in bs_dir.glob("*.bs"):
        try:
            mtimes[str(bs_file)] = bs_file.stat().st_mtime
        except FileNotFoundError:
            pass

    footer = bs_dir / "footer.include"
    if footer.exists():
        mtimes[str(footer)] = footer.stat().st_mtime

    if manifest_path and manifest_path.exists():
        mtimes[str(manifest_path)] = manifest_path.stat().st_mtime

    return mtimes


def watch_and_rebuild(
    build_fn: Callable[[], None],
    *,
    bikeshed_dir: str = None,
    manifest_path: Path = None,
    interval: float = 1.0,
) -> None:
    """Watch for source file changes and trigger rebuilds.

    Polls the filesystem at the given interval. When any .bs file,
    footer.include, or manifest changes, calls ``build_fn()``.

    Args:
        build_fn: Callable that performs the build (no arguments).
        bikeshed_dir: Path to the bikeshed source directory.
        manifest_path: Path to the manifest file.
        interval: Polling interval in seconds.
    """
    logging.info("Watch mode: monitoring for source file changes...")
    logging.info(f"  Directory: {bikeshed_dir or CONFIG.bikeshed_dir}/")
    logging.info(f"  Poll interval: {interval}s")
    logging.info("  Press Ctrl+C to stop")
    logging.info("")

    last_mtimes = _get_mtimes(bikeshed_dir, manifest_path)

    # Do an initial build
    logging.info("Performing initial build...")
    try:
        build_fn()
    except SystemExit as e:
        if e.code:
            logging.warning(f"Initial build exited with code {e.code}")
    except Exception as e:
        logging.error(f"Build failed: {e}")

    try:
        while True:
            time.sleep(interval)

            current_mtimes = _get_mtimes(bikeshed_dir, manifest_path)

            # Detect changes
            changed_files = []

            # Check for modified or new files
            for path, mtime in current_mtimes.items():
                if path not in last_mtimes or last_mtimes[path] != mtime:
                    changed_files.append(Path(path).name)

            # Check for deleted files
            for path in last_mtimes:
                if path not in current_mtimes:
                    changed_files.append(f"{Path(path).name} (deleted)")

            if changed_files:
                logging.info("")
                logging.info(f"Changes detected: {', '.join(changed_files)}")
                logging.info("Rebuilding...")
                logging.info("")

                try:
                    build_fn()
                except SystemExit as e:
                    if e.code:
                        logging.warning(f"Build exited with code {e.code}")
                except Exception as e:
                    logging.error(f"Build failed: {e}")
                    logging.info("Waiting for next change...")

                last_mtimes = _get_mtimes(bikeshed_dir, manifest_path)

    except KeyboardInterrupt:
        logging.info("")
        logging.info("Watch mode stopped.")

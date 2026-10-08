"""Multipage HTML generation pipeline.

Splits the single-page HTML spec into per-section files and generates
navigation components, an index page, and copies shared assets.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from specbuild import PROJECT_ROOT
from specbuild.config import CONFIG
from specbuild.utils import import_script

if TYPE_CHECKING:
    import argparse

# Width (in characters) of the "=" banner lines in multipage log output.
_BANNER_WIDTH = 60


def run_multipage(
    args: argparse.Namespace,
    target_dir: Path,
    branch_name: str,
    sha: str,
    spec_date: str,
) -> None:
    """Execute the multipage generation pipeline.

    Splits the single-page HTML into per-section files and generates
    navigation components, an index page, and copies shared assets.

    Args:
        args:        Parsed CLI arguments.
        target_dir:  Path to the single-page output directory.
        branch_name: Git branch name.
        sha:         Git commit SHA.
        spec_date:   Build date string.
    """
    logging.info("=" * _BANNER_WIDTH)
    logging.info(f"{CONFIG.spec_full_name} — Multipage HTML Generator")
    logging.info("=" * _BANNER_WIDTH)

    # Create multipage output directory
    mp_name = f"{target_dir.name}_Multipage"
    multipage_dir = target_dir.parent / mp_name
    if multipage_dir.exists():
        shutil.rmtree(multipage_dir)
    multipage_dir.mkdir(parents=True)
    logging.info(f"Multipage directory: {multipage_dir}")

    # Split HTML into per-section files
    logging.info("Splitting HTML into multiple pages...")
    _splitter = import_script("split_html_to_multipage")
    html_path = target_dir / "index.html"
    sections = _splitter.split_html_to_pages(html_path, multipage_dir, args)
    logging.info(f"Split into {len(sections)} section pages")

    # Generate navigation components
    logging.info("Generating navigation components...")
    _navgen = import_script("generate_multipage_navigation")
    _navgen.generate_navigation_for_all_pages(sections, multipage_dir, args)
    logging.info("Navigation added to all pages")

    # Generate index page
    logging.info("Generating index page...")
    branch_info = {
        "branch_name": branch_name,
        "sha": sha,
        "date": spec_date,
    }
    _navgen.generate_index_page(
        sections, multipage_dir, branch_info, spec_title=CONFIG.spec_full_name
    )
    logging.info(f"Index page: {multipage_dir / 'index.html'}")

    # Copy assets (CSS, JS, images, attachments)
    logging.info("Copying assets...")
    _copy_assets(target_dir, multipage_dir)

    # Optional PWA
    if getattr(args, "pwa", False):
        from specbuild.enhancements.pwa import generate_pwa_files, inject_pwa_soup
        from specbuild.utils import read_html, write_html

        for html_file in multipage_dir.glob("*.html"):
            soup = read_html(html_file)
            inject_pwa_soup(soup)
            write_html(html_file, soup)
        generate_pwa_files(multipage_dir)
        logging.info("PWA support added to multipage output")

    logging.info("=" * _BANNER_WIDTH)
    logging.info("Multipage generation complete!")
    logging.info(f"Output: {multipage_dir}")
    logging.info(f"Open: {multipage_dir / 'index.html'}")
    logging.info("=" * _BANNER_WIDTH)


def _copy_assets(single_page_dir: Path, multipage_dir: Path) -> None:
    """Copy CSS, JS, images, and attachments to the multipage directory."""
    project_root = PROJECT_ROOT

    # Copy images from single-page build
    img_src = single_page_dir / "images"
    if img_src.exists():
        shutil.copytree(img_src, multipage_dir / "images", dirs_exist_ok=True)
        logging.debug("Copied images/")

    # CSS and JS — copy from build then overlay multipage-specific files
    _MULTIPAGE_OVERLAYS = {
        "css": ["multipage-navigation.css", "multipage-search.css"],
        "js": ["multipage-navigation.js", "multipage-search.js"],
    }
    for subdir, overlay_files in _MULTIPAGE_OVERLAYS.items():
        src = single_page_dir / subdir
        dst = multipage_dir / subdir
        if src.exists():
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            dst.mkdir(parents=True, exist_ok=True)
        for filename in overlay_files:
            src_file = project_root / subdir / filename
            if src_file.exists():
                shutil.copy(src_file, dst / filename)
            else:
                logging.warning(f"Multipage overlay file not found, skipping: {src_file}")

    # Attachments (from compact mode)
    att_src = single_page_dir / "attachments"
    if att_src.exists():
        shutil.copytree(att_src, multipage_dir / "attachments", dirs_exist_ok=True)

    logging.info("Assets copied")

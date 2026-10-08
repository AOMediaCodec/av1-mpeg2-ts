"""HTML diff generation against the main branch.

Compiles the anchor (main-branch) version of the specification and produces
an ``htmldiff.pl``-based side-by-side diff against the current working
branch.  Two strategies are supported:

* **Clone mode** (default) -- clones/fetches the repo into a separate
  directory (``CONFIG.main_branch_clone_dir``) and compiles there.
* **No-clone mode** (``--no_clone``) -- temporarily checks out the target
  SHA in the *current* working tree, compiles, then switches back.

The diff result is written to ``diff.html`` inside the build directory.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from specbuild import PROJECT_ROOT
from specbuild.builder import compile_spec
from specbuild.config import CONFIG
from specbuild.git import get_branch_info
from specbuild.postprocess import renumber_annexes_in_html
from specbuild.utils import download_file

# Type alias for the anchor-spec metadata dict returned by diff_spec.
AnchorInfo = dict[str, str | None]

# File-permission bits for the downloaded htmldiff.pl script (rwxr-xr-x).
_HTMLDIFF_EXECUTABLE_MODE = 0o755


# ---------------------------------------------------------------------------
# Anchor compilation strategies
# ---------------------------------------------------------------------------


def _compile_anchor_no_clone(
    diff_sha: str | None,
    convert_sdl: bool,
    compact: bool,
    remove_editor_notes_flag: bool,
    striped_code_blocks: bool,
) -> tuple:
    """Compile the anchor spec by switching branches in the current repo.

    Checks out *diff_sha* (or ``origin/<main>``) in the current working tree,
    compiles, renumbers annexes, then switches back to the original branch.

    Args:
        diff_sha: Specific SHA to diff against; falls back to ``origin/main``.
        convert_sdl: Forward to :func:`compile_spec`.
        compact: Forward to :func:`compile_spec`.
        remove_editor_notes_flag: Forward to :func:`compile_spec`.
        striped_code_blocks: Forward to :func:`compile_spec`.

    Returns:
        A ``(anchor_html_path, anchor_info)`` tuple.  On failure the info
        dict will have ``None`` values and the caller should abort.

    Raises:
        subprocess.CalledProcessError: Re-raised after logging so the
            caller can handle it.
    """
    anchor_info: AnchorInfo = {
        "path": None,
        "branch_name": None,
        "sha": None,
        "date": None,
    }

    current_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, timeout=60
    ).strip()
    logging.info(f"Current branch: {current_branch}")

    sha_to_checkout = diff_sha
    if sha_to_checkout is None:
        sha_to_checkout = subprocess.check_output(
            ["git", "rev-parse", f"origin/{CONFIG.main_branch}"], text=True, timeout=60
        ).strip()

    logging.info(f"Check out '{sha_to_checkout}'")

    # Guard against git option injection (e.g. --diff_sha=--orphan branch).
    # Only bare SHAs and simple ref names are safe to pass as a positional arg.
    if sha_to_checkout and not re.match(r"^[0-9a-f]{6,40}$", sha_to_checkout):
        # Not a raw SHA — allow only safe refname characters
        if not re.match(r"^[A-Za-z0-9_./:@^~-]+$", sha_to_checkout):
            raise ValueError(
                f"diff_sha {sha_to_checkout!r} contains unsafe characters; aborting diff"
            )

    # Stash any uncommitted changes (tracked + untracked) so we can switch
    # commits cleanly without "local changes would be overwritten" errors.
    stash_result = subprocess.run(
        ["git", "stash", "push", "--include-untracked", "-m", "specbuild-diff-stash"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if stash_result.returncode != 0:
        logging.warning(f"git stash failed: {stash_result.stderr.strip()}")
        stashed = False
    else:
        # git outputs "No local changes to save" when there is nothing to stash.
        stashed = "no local changes" not in stash_result.stdout.lower()

    anchor_html: Path | None = None
    try:
        # Fix: use plain `git checkout SHA` (not `git checkout -- SHA` which
        # treats SHA as a file path and fails for commit hashes).
        subprocess.run(["git", "checkout", sha_to_checkout], check=True, timeout=60)

        branch_name, sha, spec_date = get_branch_info(forced_git_cmd=True)
        anchor_info.update(sha=sha, branch_name=branch_name, path="./", date=spec_date)

        logging.info("Compiling anchor inside the root dir")
        if CONFIG.source_format == "asciidoc":
            from specbuild.builder_adoc import compile_adoc_spec, locate_adoc_entry_point

            anchor_html = Path("index.html")
            adoc_path = locate_adoc_entry_point()
            compile_adoc_spec(adoc_path, output_html=anchor_html)
        elif convert_sdl:
            compile_spec(
                convert_sdl=True,
                compact=compact,
                remove_editor_notes_flag=remove_editor_notes_flag,
                striped_code_blocks=striped_code_blocks,
            )
            anchor_html = Path("index.html")
        else:
            compile_spec(
                diff_hack=True,
                compact=compact,
                remove_editor_notes_flag=remove_editor_notes_flag,
                striped_code_blocks=striped_code_blocks,
            )
            anchor_html = Path("index.html")

        logging.info("Renumbering annexes in anchor spec")
        renumber_annexes_in_html(anchor_html)
    finally:
        logging.info(f"Switch back to the original branch: '{current_branch}'")
        subprocess.run(["git", "checkout", current_branch], check=True, timeout=60)
        if stashed:
            logging.info("Restoring stashed changes")
            subprocess.run(["git", "stash", "pop"], check=True, timeout=60)

    if anchor_html is None:
        raise RuntimeError("Anchor compilation failed — HTML output not produced")
    return anchor_html, anchor_info


def _compile_anchor_clone(
    diff_sha: str | None,
    convert_sdl: bool,
    compact: bool,
    remove_editor_notes_flag: bool,
    striped_code_blocks: bool,
) -> tuple:
    """Compile the anchor spec inside a separate clone directory.

    Clones the repo (if not already present), checks out the target SHA,
    compiles, and renumbers annexes.

    Args:
        diff_sha: Specific SHA to diff against; falls back to main branch.
        convert_sdl: Forward to :func:`compile_spec`.
        compact: Forward to :func:`compile_spec`.
        remove_editor_notes_flag: Forward to :func:`compile_spec`.
        striped_code_blocks: Forward to :func:`compile_spec`.

    Returns:
        A ``(anchor_html_path, anchor_info)`` tuple.  On failure the info
        dict will have ``None`` values and the caller should abort.

    Raises:
        subprocess.CalledProcessError: Re-raised after logging so the
            caller can handle it.
    """
    anchor_info: AnchorInfo = {
        "path": None,
        "branch_name": None,
        "sha": None,
        "date": None,
    }

    # Resolve the repo URL — use configured value, or fall back to the
    # current repo's origin remote so consumers don't have to set repo_url.
    repo_url = CONFIG.repo_url
    if not repo_url:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                repo_url = result.stdout.strip()
                logging.debug(f"Auto-detected repo_url from git remote: {repo_url}")
        except Exception:
            pass

    main_branch_path = Path(CONFIG.main_branch_clone_dir)
    main_branch_path.mkdir(parents=True, exist_ok=True)

    if CONFIG.source_format == "asciidoc":
        anchor_html = main_branch_path / "index.html"
    else:
        # Bikeshed always writes index.html regardless of main_bs_file.
        anchor_html = main_branch_path / "index.html"
    anchor_git_dir = main_branch_path / ".git"

    # Resolve the repo URL — use configured value, or fall back to the
    # current repo's origin remote so consumers don't have to set repo_url.
    repo_url = CONFIG.repo_url
    if not repo_url:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=10,
            )
            if result.returncode == 0:
                repo_url = result.stdout.strip()
        except Exception:
            pass

    # Clone if the directory doesn't contain a git checkout yet
    if not anchor_git_dir.exists():
        if not repo_url:
            logging.error(
                "Cannot clone anchor spec: repo_url is not set and could not be "
                "auto-detected. Set repo_url in specbuild.toml or use --no_clone."
            )
            return anchor_info
        logging.info(f"Cloning {repo_url} to {CONFIG.main_branch_clone_dir}")
        subprocess.run(["git", "clone", repo_url, str(main_branch_path)], check=True, timeout=300)
    else:
        # Fetch latest changes from remote
        logging.info(f"Fetching latest changes in {CONFIG.main_branch_clone_dir}")
        subprocess.run(["git", "fetch", "origin"], cwd=main_branch_path, check=True, timeout=120)

    if diff_sha is None:
        subprocess.run(
            ["git", "checkout", CONFIG.main_branch], cwd=main_branch_path, check=True, timeout=60
        )
    else:
        subprocess.run(["git", "checkout", diff_sha], cwd=main_branch_path, check=True, timeout=60)

    branch_name, sha, spec_date = get_branch_info(main_branch_path)
    anchor_info.update(sha=sha, branch_name=branch_name, path="./", date=spec_date)

    if not anchor_html.exists():
        if CONFIG.source_format == "asciidoc":
            from specbuild.builder_adoc import compile_adoc_spec, locate_adoc_entry_point

            adoc_path = locate_adoc_entry_point(main_branch_path)
            compile_adoc_spec(adoc_path, output_html=anchor_html)
        elif convert_sdl:
            compile_spec(
                main_branch_path,
                convert_sdl=True,
                compact=compact,
                remove_editor_notes_flag=remove_editor_notes_flag,
                striped_code_blocks=striped_code_blocks,
            )
        else:
            compile_spec(
                main_branch_path,
                diff_hack=True,
                compact=compact,
                remove_editor_notes_flag=remove_editor_notes_flag,
                striped_code_blocks=striped_code_blocks,
            )

    logging.info("Renumbering annexes in anchor spec")
    renumber_annexes_in_html(anchor_html)

    return anchor_html, anchor_info


# ---------------------------------------------------------------------------
# Diff execution
# ---------------------------------------------------------------------------


def _run_htmldiff(anchor_html: Path, target_html: Path, diff_file: Path) -> None:
    """Run ``htmldiff.pl`` with optional preprocessing.

    If ``scripts/preprocess_for_diff.py`` exists, both HTML files are
    preprocessed first to strip artifacts that cause false diff noise.
    On preprocessing failure, falls back to diffing the raw files.

    Args:
        anchor_html: Path to the anchor (main-branch) compiled HTML.
        target_html: Path to the current-branch compiled HTML.
        diff_file: Output path for the generated diff HTML.
    """
    preprocess_script = PROJECT_ROOT / "scripts" / "preprocess_for_diff.py"

    if preprocess_script.exists():
        _run_htmldiff_with_preprocessing(anchor_html, target_html, diff_file, preprocess_script)
    else:
        logging.warning(f"Preprocessing script not found: {preprocess_script}")
        logging.warning("Running diff without preprocessing (may have false differences)")
        _run_htmldiff_raw(anchor_html, target_html, diff_file)


def _run_htmldiff_with_preprocessing(
    anchor_html: Path,
    target_html: Path,
    diff_file: Path,
    preprocess_script: Path,
) -> None:
    """Preprocess both HTML files, then run ``htmldiff.pl``.

    Temporary ``.preprocessed.html`` files are always cleaned up.

    Args:
        anchor_html: Path to the anchor HTML.
        target_html: Path to the target HTML.
        diff_file: Output diff path.
        preprocess_script: Path to ``preprocess_for_diff.py``.
    """
    anchor_preprocessed = anchor_html.with_suffix(".preprocessed.html")
    target_preprocessed = target_html.with_suffix(".preprocessed.html")

    try:
        # Preprocess anchor and target in parallel — they are independent.
        def _preprocess(src: Path, dst: Path) -> None:
            subprocess.run(
                [sys.executable, str(preprocess_script), str(src), str(dst)],
                check=True,
                timeout=120,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = {
                pool.submit(_preprocess, anchor_html, anchor_preprocessed): "anchor",
                pool.submit(_preprocess, target_html, target_preprocessed): "target",
            }
            for fut in as_completed(futures):
                fut.result()  # re-raise any CalledProcessError

        logging.info(
            f"Running HTML diff tool: "
            f"{anchor_preprocessed.name} vs "
            f"{target_preprocessed.name} => {diff_file}"
        )
        subprocess.run(
            [
                "perl",
                str(PROJECT_ROOT / "htmldiff.pl"),
                str(anchor_preprocessed),
                str(target_preprocessed),
                str(diff_file),
            ],
            check=True,
            timeout=300,
        )
        logging.info("Diff created successfully.")
    except subprocess.CalledProcessError as exc:
        logging.error(f"Failed during preprocessing or diff. Error: {exc}")
        logging.warning("Falling back to running diff without preprocessing")
        _run_htmldiff_raw(anchor_html, target_html, diff_file)
    finally:
        if anchor_preprocessed.exists():
            anchor_preprocessed.unlink()
        if target_preprocessed.exists():
            target_preprocessed.unlink()


def _run_htmldiff_raw(anchor_html: Path, target_html: Path, diff_file: Path) -> None:
    """Run ``htmldiff.pl`` directly on unprocessed HTML files.

    Args:
        anchor_html: Path to the anchor HTML.
        target_html: Path to the target HTML.
        diff_file: Output diff path.
    """
    logging.info(f"Running HTML diff tool: {anchor_html} vs {target_html} => {diff_file}")
    try:
        subprocess.run(
            [
                "perl",
                str(PROJECT_ROOT / "htmldiff.pl"),
                str(anchor_html),
                str(target_html),
                str(diff_file),
            ],
            check=True,
            timeout=300,
        )
        logging.info("Diff created successfully.")
    except subprocess.CalledProcessError as exc:
        logging.error(f"Failed to run diff tool. Error: {exc}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_spec(
    build_dir: Path,
    no_clone: bool = False,
    diff_sha: str | None = None,
    convert_sdl: bool = False,
    compact: bool = False,
    remove_editor_notes_flag: bool = False,
    override_date: str | None = None,
    striped_code_blocks: bool = False,
) -> AnchorInfo:
    """Create a diff between the compiled specification and the main branch.

    Downloads ``htmldiff.pl`` if necessary, compiles the anchor spec using
    either the clone or no-clone strategy, then runs the diff tool.

    Args:
        build_dir: Directory containing the compiled specification.
        no_clone: If True, switch to main branch in-repo instead of cloning.
        diff_sha: Specific SHA to diff against; uses ``origin/main`` if None.
        convert_sdl: If True, convert SDL syntax blocks to HTML tables.
        compact: If True, extract Section 9 tables to ``.h`` files.
        remove_editor_notes_flag: If True, remove ``Note: TODO`` paragraphs.
        override_date: Date in ``YYYY-MM-DD`` to use instead of commit date.
        striped_code_blocks: If True, convert code blocks to striped tables.

    Returns:
        Anchor-spec metadata dict with keys
        ``path``, ``branch_name``, ``sha``, ``date``.
    """
    logging.info(f"Diffing {build_dir} VS. {CONFIG.main_branch_clone_dir}")

    anchor_spec_info: AnchorInfo = {
        "path": None,
        "branch_name": None,
        "sha": None,
        "date": None,
    }

    # Ensure the htmldiff.pl tool is available
    htmldiff_path = PROJECT_ROOT / "htmldiff.pl"
    if not htmldiff_path.exists():
        download_file(url=CONFIG.htmldiff_url, file_name=htmldiff_path)
    if not htmldiff_path.exists():
        logging.error("htmldiff.pl not found and could not be downloaded.")
        return anchor_spec_info
    # chmod is a no-op on Windows; only apply on POSIX systems.
    if sys.platform != "win32":
        htmldiff_path.chmod(_HTMLDIFF_EXECUTABLE_MODE)
    # Perl is required to run htmldiff.pl. macOS 14+ no longer ships Perl.
    if not shutil.which("perl"):
        logging.error(
            "Perl not found — cannot run htmldiff.pl. "
            "Install Perl (e.g. 'brew install perl' on macOS, 'apt install perl' on Linux)."
        )
        return anchor_spec_info

    # --- Compile the anchor spec ---
    compile_kwargs = dict(
        diff_sha=diff_sha,
        convert_sdl=convert_sdl,
        compact=compact,
        remove_editor_notes_flag=remove_editor_notes_flag,
        striped_code_blocks=striped_code_blocks,
    )

    if no_clone:
        logging.info("Switching to the main branch in the current repository.")
        try:
            anchor_html, anchor_spec_info = _compile_anchor_no_clone(**compile_kwargs)
        except subprocess.CalledProcessError as exc:
            logging.error(f"Failed to switch branches or compile the main branch. Error: {exc}")
            return anchor_spec_info
    else:
        try:
            anchor_html, anchor_spec_info = _compile_anchor_clone(**compile_kwargs)
        except subprocess.CalledProcessError as exc:
            logging.error(f"Failed to clone/checkout or compile. Error: {exc}")
            return anchor_spec_info

    # --- Run the diff ---
    # Bikeshed always writes index.html — use it for both anchor and target.
    target_html = build_dir / "index.html"
    diff_file = build_dir / "diff.html"

    logging.info("Preprocessing HTML files for diff...")
    _run_htmldiff(anchor_html, target_html, diff_file)

    return anchor_spec_info

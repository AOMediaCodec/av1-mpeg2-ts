"""Git helpers: branch info, commit SHA, date."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path


def get_branch_info(
    current_path: Path = None, forced_git_cmd: bool = True, override_date: str = None
) -> tuple[str, str, str]:
    """Get the branch name, commit SHA and the date.

    Reads from GitLab CI/CD environment variables when available, otherwise
    falls back to git commands.

    Args:
        current_path (Path, optional): The path to run git commands in.
        forced_git_cmd (bool): If True, forces git commands over CI env vars.
        override_date (str, optional): Date in YYYY-MM-DD to use instead of
            commit date.

    Returns:
        tuple[str, str, str]: (branch_name, commit_sha, commit_date).
    """
    cwd_path = str(current_path) if current_path else None

    if os.getenv("CI") and not forced_git_cmd:
        branch_name = os.getenv("CI_COMMIT_REF_NAME", "HEAD")
        commit_sha = os.getenv("CI_COMMIT_SHORT_SHA", "UNKNOWN")
        commit_timestamp = os.getenv("CI_COMMIT_TIMESTAMP", "UNKNOWN")
        logging.debug(
            f"branch_name={branch_name}, commit_sha={commit_sha}, "
            f"commit_timestamp={commit_timestamp}"
        )
        commit_date = commit_timestamp.split("T")[0] if commit_timestamp != "UNKNOWN" else "UNKNOWN"
    else:
        # Single git call for all three values
        try:
            git_output = (
                subprocess.check_output(
                    ["git", "log", "-1", "--format=%D%n%h%n%ci", "HEAD"],
                    cwd=cwd_path,
                    stderr=subprocess.PIPE,
                )
                .strip()
                .decode("utf-8")
            )
        except FileNotFoundError:
            raise SystemExit(
                "Error: git not found. Please install git and ensure it is in your PATH."
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace").strip() if exc.stderr else ""
            raise SystemExit(f"Error: git command failed (is this a git repository?).\n{stderr}")
        parts = git_output.split("\n", 2)
        if len(parts) < 3:
            raise SystemExit(
                f"Error: unexpected git log output (expected 3 fields, got {len(parts)}). "
                "Check that the repository has at least one commit."
            )
        ref_names, commit_sha, commit_raw_date = parts

        # Extract branch name from ref decoration (e.g. "HEAD -> main, origin/main")
        branch_name = "HEAD"
        for part in ref_names.split(","):
            part = part.strip()
            if part.startswith("HEAD -> "):
                branch_name = part[len("HEAD -> ") :]
                break
        if branch_name == "HEAD":
            # Detached HEAD — fall back to rev-parse
            try:
                branch_name = (
                    subprocess.check_output(
                        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                        cwd=cwd_path,
                        stderr=subprocess.PIPE,
                    )
                    .strip()
                    .decode("utf-8")
                )
            except subprocess.CalledProcessError:
                branch_name = "HEAD"

        commit_date = datetime.strptime(commit_raw_date.split()[0], "%Y-%m-%d").strftime("%Y-%m-%d")

    if override_date is not None:
        logging.info(f"Using override date: {override_date} (replacing commit date: {commit_date})")
        commit_date = override_date

    return branch_name, commit_sha, commit_date


def resolve_build_identity(
    branch_override: str = None,
    date_override: str = None,
) -> tuple[str, str, str, Path]:
    """Resolve branch name, SHA, date, and target directory for a build.

    This is the shared logic used by ``compile.py`` to determine the build
    identity for both single-page and multipage builds.

    Args:
        branch_override: Explicit branch name (skips git detection).
        date_override: Explicit date string (YYYY-MM-DD).

    Returns:
        Tuple of ``(branch_name, sha, spec_date, target_dir)``.
    """
    from specbuild.config import CONFIG

    if branch_override is None:
        branch_name, sha, spec_date = get_branch_info(override_date=date_override)
    else:
        branch_name = branch_override
        sha = "UNKNOWN"
        spec_date = date_override if date_override else "UNKNOWN"

    # Sanitise spec_name before embedding in the output directory path.
    # A malicious/accidental specbuild.toml like `spec_name = "../../etc"`
    # would otherwise point target_dir outside the project root.
    safe_spec_name = re.sub(r"[^A-Za-z0-9_\-]", "_", CONFIG.spec_name) or "Spec"
    target_dir = Path(
        CONFIG.output_dir_template.format(
            date=spec_date.replace("-", ""),
            sha=sha,
            spec_name=safe_spec_name,
        )
    )

    return branch_name, sha, spec_date, target_dir


def run_git(*args: str, timeout: int = 30) -> str | None:
    """Run a git command and return stdout, or None on failure.

    This is the preferred way for specbuild modules to invoke git
    subprocesses.  Errors are logged at debug level rather than raised.

    Args:
        *args: Arguments passed to ``git`` (e.g. ``'diff', '--name-status'``).
        timeout: Maximum seconds to wait for the command.

    Returns:
        Stripped stdout text on success, or ``None`` on any failure.
    """
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        if result.returncode != 0:
            logging.debug(f"git {' '.join(args)} failed: {result.stderr.strip()}")
            return None
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logging.debug(f"git command failed: {exc}")
        return None

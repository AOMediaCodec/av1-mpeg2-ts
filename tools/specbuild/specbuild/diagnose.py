"""System diagnostic report for specbuild.

Prints status of build dependencies and environment, then exits.  Useful for
troubleshooting "why doesn't ``--pdf`` work?" or "is python-pptx installed?"
without needing to start a full build.

Invoked via ``python compile.py --diagnose``.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Individual checks — each returns (label, version_or_status, ok, hint)
# ---------------------------------------------------------------------------


def _check_python() -> tuple[str, str, bool, str]:
    v = sys.version_info
    return ("Python", f"{v.major}.{v.minor}.{v.micro}", v >= (3, 10), "")


def _check_subprocess(label: str, cmd: list[str], hint: str = "") -> tuple[str, str, bool, str]:
    """Run *cmd* with timeout=10 and return its first stdout line."""
    if not shutil.which(cmd[0]):
        return (label, "not found", False, hint)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return (label, f"error: {exc}", False, hint)
    line = (result.stdout or result.stderr).strip().split("\n")[0]
    return (label, line or "ok", result.returncode == 0, hint)


def _check_import(label: str, module: str, extra: str) -> tuple[str, str, bool, str]:
    """Try to import *module* and report its version attribute."""
    try:
        mod = __import__(module)
    except ImportError:
        return (label, "not installed", False, f"pip install specbuild[{extra}]")
    except (OSError, Exception) as exc:  # noqa: BLE001  # native lib failures (e.g. weasyprint)
        hint = ""
        if module == "weasyprint":
            try:
                from specbuild.utils import homebrew_lib_for_dyld

                homebrew_lib = homebrew_lib_for_dyld()
            except ImportError:
                homebrew_lib = None
            if homebrew_lib:
                hint = (
                    "macOS arm64: add to your shell rc — "
                    f"export DYLD_FALLBACK_LIBRARY_PATH={homebrew_lib}:$DYLD_FALLBACK_LIBRARY_PATH"
                )
        return (label, f"import error: {type(exc).__name__}", False, hint)
    version = getattr(mod, "__version__", "(version unknown)")
    return (label, str(version), True, "")


def _check_chrome() -> tuple[str, str, bool, str]:
    try:
        from specbuild.utils import chrome_path
    except ImportError:
        return ("Chrome", "specbuild.utils unavailable", False, "")
    path = chrome_path()
    if path:
        return ("Chrome", path, True, "")
    return ("Chrome", "not found", False, "Required for --pdf (Chrome headless)")


def _check_project_root() -> tuple[str, str, bool, str]:
    try:
        import specbuild

        root = specbuild.PROJECT_ROOT
    except (ImportError, AttributeError):
        return ("Project root", "(not set)", False, "")
    return ("Project root", str(root), Path(root).exists(), "")


def _check_active_flavor() -> tuple[str, str, bool, str]:
    try:
        from specbuild.config import CONFIG
    except ImportError:
        return ("Active flavor", "(config not loaded)", False, "")
    flavor = getattr(CONFIG, "standards_flavor", None) or "(none)"
    return ("Active flavor", flavor, True, "")


def _check_cache_dir() -> tuple[str, str, bool, str]:
    cache = Path.home() / ".specbuild_cache"
    if not cache.exists():
        return ("Cache dir", "(empty)", True, "")
    try:
        size = sum(f.stat().st_size for f in cache.rglob("*") if f.is_file())
    except OSError:
        size = 0
    mb = size / (1024 * 1024)
    return ("Cache dir", f"{cache} ({mb:.1f} MB)", True, "")


def _check_worktrees() -> tuple[str, str, bool, str]:
    try:
        import specbuild

        wt_dir = Path(specbuild.PROJECT_ROOT) / ".claude" / "worktrees"
    except (ImportError, AttributeError):
        return ("Agent worktrees", "(n/a)", True, "")
    if not wt_dir.exists():
        return ("Agent worktrees", "(none)", True, "")
    count = sum(1 for p in wt_dir.iterdir() if p.is_dir() and p.name.startswith("agent-"))
    if count == 0:
        return ("Agent worktrees", "(none)", True, "")
    hint = "Run 'git worktree prune' to clean up" if count > 5 else ""
    return ("Agent worktrees", f"{count} present", count <= 5, hint)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_diagnostics() -> list[tuple[str, str, bool, str]]:
    """Run all diagnostic checks and return the results.

    Returns a list of ``(label, value, ok, hint)`` tuples.  Separate from the
    formatting/printing function so tests can assert on the structured data.
    """
    return [
        _check_python(),
        _check_subprocess(
            "Bikeshed",
            ["bikeshed", "--version"],
            "Required: pip install bikeshed",
        ),
        _check_chrome(),
        _check_import("WeasyPrint", "weasyprint", "pdf"),
        _check_subprocess(
            "Pandoc",
            ["pandoc", "--version"],
            "Required for --docx: install from pandoc.org",
        ),
        _check_subprocess(
            "Ghostscript",
            ["gs", "--version"],
            "Required for --optimize-pdf",
        ),
        _check_import("python-docx", "docx", "docx"),
        _check_import("python-pptx", "pptx", "slides"),
        _check_import("openpyxl (ballot)", "openpyxl", "ballot"),
        _check_subprocess("Git", ["git", "--version"], ""),
        _check_project_root(),
        _check_active_flavor(),
        _check_cache_dir(),
        _check_worktrees(),
    ]


def format_diagnostics(results: list[tuple[str, str, bool, str]]) -> str:
    """Format the diagnostic results as a human-readable report."""
    lines = ["specbuild diagnostic report", "=" * 60]
    width = max(len(r[0]) for r in results) + 2
    for label, value, ok, hint in results:
        icon = "[✓]" if ok else "[✗]"
        lines.append(f"{icon} {label:<{width}} {value}")
        if hint and not ok:
            lines.append(f"      {hint}")
    return "\n".join(lines) + "\n"


def run_diagnose() -> int:
    """Run diagnostics, print the report, return exit code (0 if all ok)."""
    results = collect_diagnostics()
    sys.stdout.write(format_diagnostics(results))
    # Only the critical checks (Python, Bikeshed, Git) gate the exit code.
    critical = {"Python", "Bikeshed", "Git"}
    failed_critical = [r for r in results if r[0] in critical and not r[2]]
    if failed_critical:
        logging.error(
            "Critical dependencies missing: %s",
            ", ".join(r[0] for r in failed_critical),
        )
        return 1
    return 0

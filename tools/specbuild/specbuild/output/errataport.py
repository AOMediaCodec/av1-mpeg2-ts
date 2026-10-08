"""Errata backport helper.

Reads an errata TOML manifest and prepares per-erratum patch files plus a
Markdown change-impact note for backporting onto a maintenance branch.

TOML schema (intentionally close to ``analysis/errata.py`` ``ErrataEntry``)::

    [[errata]]
    errata_id   = "ERR-2024-001"
    date        = "2024-03-15"
    clause_ref  = "7.3.2"
    type        = "technical"
    description = "Off-by-one in profile_idc range"
    correction  = "Replace 'shall be in the range 0..63' with '0..127'"
    status      = "confirmed"
    clause_id   = "profile-idc"
    commit      = "abc123"      # optional: cherry-pick source

If a ``commit`` field is present, the helper invokes ``git format-patch -1
<commit>`` against the target branch and stores the resulting patch under
``patches/<errata_id>.patch``.

When no commit is specified, a placeholder patch is emitted so reviewers
can fill in the diff manually.

This module is intentionally subprocess-friendly: every shell-out goes
through :func:`_run_git`, which is mocked in tests.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class BackportEntry:
    """One erratum to backport.

    Mirrors :class:`specbuild.analysis.errata.ErrataEntry` but optional
    fields are explicit so we can keep the parser tolerant.
    """

    errata_id: str
    date: str = ""
    clause_ref: str = ""
    type: str = ""
    description: str = ""
    correction: str = ""
    status: str = ""
    clause_id: str = ""
    commit: str = ""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        import tomli as tomllib  # type: ignore[no-redef]
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_errata(path: Path) -> list[BackportEntry]:
    """Parse a TOML errata manifest into :class:`BackportEntry` records."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Errata manifest not found: {path}")
    data = _load_toml(path)
    raw = data.get("errata", [])
    if not isinstance(raw, list):
        raise ValueError(f"{path}: 'errata' must be an array of tables")
    out: list[BackportEntry] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: errata #{i} must be a table")
        eid = entry.get("errata_id")
        if not eid or not isinstance(eid, str):
            raise ValueError(f"{path}: errata #{i} missing string 'errata_id'")
        out.append(
            BackportEntry(
                errata_id=eid,
                date=str(entry.get("date", "")),
                clause_ref=str(entry.get("clause_ref", "")),
                type=str(entry.get("type", "")),
                description=str(entry.get("description", "")),
                correction=str(entry.get("correction", "")),
                status=str(entry.get("status", "")),
                clause_id=str(entry.get("clause_id", "")),
                commit=str(entry.get("commit", "")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Git helpers (mocked in tests)
# ---------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: int = 30) -> str:
    """Run a git command and return stdout. Raises ``CalledProcessError`` on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    return result.stdout


def _format_patch_for_commit(
    commit: str,
    target_branch: str,
    output_dir: Path,
    *,
    name: str,
    repo: Path | None = None,
) -> Path | None:
    """Run ``git format-patch -1 <commit>`` and rename the result to *name*.patch.

    Returns the path to the produced patch file, or ``None`` on failure.
    """
    # Validate inputs to prevent git-option injection via crafted TOML values.
    _SHA_RE = re.compile(r"^[0-9a-f]{6,40}$")
    _BRANCH_RE = re.compile(r"^[A-Za-z0-9_./:@-]+$")
    if not _SHA_RE.match(commit):
        logging.warning(
            f"errataport: skipping commit {commit!r} — not a valid SHA (expected 6-40 hex chars)"
        )
        return None
    if not _BRANCH_RE.match(target_branch):
        logging.warning(
            f"errataport: skipping branch {target_branch!r} — contains unsafe characters"
        )
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        # format-patch writes a file in -o DIR with the standard
        # 0001-<subject>.patch name; capture stdout to learn the file.
        out = _run_git(
            [
                "format-patch",
                "-1",
                "--",
                commit,
                f"--base={target_branch}",
                "-o",
                str(output_dir),
            ],
            cwd=repo,
        )
        produced = [Path(line.strip()) for line in out.splitlines() if line.strip()]
        if not produced:
            logging.warning(f"errataport: format-patch produced no file for {commit}")
            return None
        src = produced[0]
        if not src.is_absolute():
            src = output_dir / src.name
        dest = output_dir / f"{name}.patch"
        if src.exists():
            src.rename(dest)
            return dest
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logging.warning(f"errataport: format-patch failed for {commit}: {exc}")
        return None


def _placeholder_patch(entry: BackportEntry, output_dir: Path) -> Path:
    """Write a stub patch file when no commit is supplied."""
    output_dir.mkdir(parents=True, exist_ok=True)
    body = (
        f"# Placeholder backport patch for {entry.errata_id}\n"
        f"# Clause: {entry.clause_ref} (id={entry.clause_id})\n"
        f"# Type:   {entry.type}\n"
        f"# Description: {entry.description}\n"
        f"# Correction:  {entry.correction}\n"
        "#\n"
        "# Fill in the actual diff below before applying.\n"
        "#\n"
    )
    dest = output_dir / f"{entry.errata_id}.patch"
    dest.write_text(body, encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Markdown note
# ---------------------------------------------------------------------------


def render_backport_note(
    entries: list[BackportEntry],
    target_branch: str,
    *,
    patches: dict[str, Path] | None = None,
) -> str:
    """Render the change-impact Markdown summary for the backport set."""
    patches = patches or {}
    lines: list[str] = [
        f"# Errata Backport Note — `{target_branch}`",
        "",
        f"Total entries: **{len(entries)}**",
        "",
        "| ID | Clause | Type | Status | Patch |",
        "|----|--------|------|--------|-------|",
    ]
    for e in entries:
        patch_path = patches.get(e.errata_id)
        patch_cell = f"`{patch_path.name}`" if patch_path else "_(missing)_"
        lines.append(
            f"| `{e.errata_id}` | {e.clause_ref or '—'} | {e.type or '—'} "
            f"| {e.status or '—'} | {patch_cell} |"
        )
    lines.append("")
    lines.append("## Details")
    for e in entries:
        lines.append("")
        lines.append(f"### {e.errata_id}")
        if e.description:
            lines.append("")
            lines.append(f"**Issue:** {e.description}")
        if e.correction:
            lines.append("")
            lines.append(f"**Correction:** {e.correction}")
        if e.commit:
            lines.append("")
            lines.append(f"_Source commit:_ `{e.commit}`")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def backport_errata(
    errata_path: Path,
    target_branch: str,
    output_dir: Path,
    *,
    repo: Path | None = None,
) -> dict[str, Any]:
    """Run the full backport workflow.

    Args:
        errata_path: TOML manifest path.
        target_branch: Branch the patches should apply against.
        output_dir: Where to write ``patches/`` and the Markdown note.
        repo: Optional git repository path (defaults to CWD).

    Returns:
        Dict with ``entries``, ``patches`` (per-id paths), and ``note_path``.
    """
    output_dir = Path(output_dir)
    patches_dir = output_dir / "patches"
    output_dir.mkdir(parents=True, exist_ok=True)
    patches_dir.mkdir(parents=True, exist_ok=True)

    entries = load_errata(Path(errata_path))
    patches: dict[str, Path] = {}
    for e in entries:
        if e.commit:
            path = _format_patch_for_commit(
                e.commit,
                target_branch,
                patches_dir,
                name=e.errata_id,
                repo=repo,
            )
            if path is None:
                path = _placeholder_patch(e, patches_dir)
        else:
            path = _placeholder_patch(e, patches_dir)
        patches[e.errata_id] = path

    note_path = output_dir / "errata_backport_note.md"
    note_path.write_text(
        render_backport_note(entries, target_branch, patches=patches),
        encoding="utf-8",
    )
    logging.info(
        "errataport: %d entries, %d patches, note=%s",
        len(entries),
        len(patches),
        note_path,
    )
    return {"entries": entries, "patches": patches, "note_path": note_path}


__all__ = [
    "BackportEntry",
    "load_errata",
    "render_backport_note",
    "backport_errata",
]

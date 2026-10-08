"""AI-assisted change-summary / consistency-review (opt-in).

This module provides an opt-in pass that asks an LLM (Anthropic's Claude API
by default) to summarise recent specification changes and flag potential
terminology drift across modified clauses.  It is intended to assist a
human editor preparing JVET/MPEG/3GPP ballot-comment responses; the output
is a plain markdown file (``ai_review.md``) and is NEVER substituted for an
editor's review.

Design constraints (these are deliberate and load-bearing):

* **Strictly opt-in.**  Activated only via the ``--ai-review`` CLI flag.
* **Reads local files only.**  The module performs ``git diff`` against a
  baseline ref and reads the resulting hunks; it never writes to source
  files, never uploads them anywhere except as the body of a single API
  request, and never persists API responses outside the user-controlled
  cache directory.
* **API key never persisted.**  ``ANTHROPIC_API_KEY`` is read once from
  the environment, used for the request, and never logged, written to
  disk, or echoed.
* **Deterministic in CI.**  A SHA-256 cache key over
  ``(diff_hunk + model + PROMPT_VERSION)`` is used to look up cached
  responses on disk, so repeated CI runs against the same diff do not
  re-bill or change output.
* **Polite to the API.**  A single API call per ``--ai-review`` invocation;
  small ``max_tokens`` budget by default.
* **Pure-Python, cross-platform.**  Only ``requests`` (already a project
  dependency) is used; no Anthropic SDK dependency.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, TypedDict

#: Bumped whenever ``build_prompt`` is modified.  Cached responses keyed
#: on a previous prompt version are simply ignored.
PROMPT_VERSION = "v1"

#: Default model (override with ``SPECBUILD_AI_MODEL`` env var).
DEFAULT_MODEL = "claude-sonnet-4.6"

#: Default cache directory.  Cross-platform: uses ``~``.
DEFAULT_CACHE_DIR = Path.home() / ".specbuild_cache" / "aireview"

#: Anthropic Messages API endpoint.
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

#: Anthropic API version header.
ANTHROPIC_API_VERSION = "2023-06-01"

#: Default token budget per call (deliberately small / polite).
DEFAULT_MAX_TOKENS = 8192

#: Default request timeout in seconds.
DEFAULT_TIMEOUT = 60.0

#: Heading-detection regex for surrounding-clause context.
_BIKESHED_HEADING_RE = re.compile(r"^(#{1,6}\s+.+|<h[1-6][^>]*>.*?</h[1-6]>)", re.IGNORECASE)


class ReviewResult(TypedDict):
    """One LLM-generated review entry for a single clause-level hunk."""

    clause_id: str
    summary: str
    terminology_drift: list[str]
    severity: str  # "info" | "warning" | "critical"


# ---------------------------------------------------------------------------
# Diff collection
# ---------------------------------------------------------------------------


def _resolve_baseline_ref(repo_root: Path, baseline_ref: str = "auto") -> str:
    """Resolve ``"auto"`` baseline to a usable git ref.

    Tries (in order): the most recent tag, ``origin/main``, ``main``,
    ``origin/master``, ``master``.  Returns the original ``baseline_ref``
    unchanged if it is not ``"auto"``.
    """
    if baseline_ref != "auto":
        return baseline_ref

    candidates = [
        ("describe", "--tags", "--abbrev=0"),
        ("rev-parse", "--verify", "origin/main"),
        ("rev-parse", "--verify", "main"),
        ("rev-parse", "--verify", "origin/master"),
        ("rev-parse", "--verify", "master"),
    ]
    for argv in candidates:
        try:
            out = subprocess.run(
                ["git", *argv],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()

    # Last resort: HEAD~1 — at least something diff-able.
    return "HEAD~1"


def _run_git(repo_root: Path, *args: str, timeout: int = 30) -> str:
    """Run a git command and return stdout (empty string on failure)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logging.debug(f"git {' '.join(args)} failed: {exc}")
        return ""
    if result.returncode != 0:
        logging.debug(f"git {' '.join(args)} returned {result.returncode}: {result.stderr.strip()}")
        return ""
    return result.stdout


def _extract_clause_id(hunk_header: str, file_path: str) -> str:
    """Pull a usable clause-id from a unified-diff hunk header.

    ``git diff -U`` puts the surrounding section heading after the
    ``@@ ... @@`` token, e.g.::

        @@ -10,7 +10,9 @@ ## 5.2 Bitstream syntax

    We extract whatever text trails the second ``@@``, strip leading
    markdown ``#`` markers, and fall back to ``<file>:hunk`` if the
    header carries no heading.

    If *file_path* is empty (e.g. malformed ``diff --git`` line that
    failed to expose the file name) we substitute ``<no-file>`` so the
    resulting clause-id never starts with ``:``.
    """
    m = re.match(r"^@@[^@]+@@\s*(.*)$", hunk_header)
    trailing = m.group(1).strip() if m else ""
    if trailing:
        # Strip leading bikeshed/markdown heading markers
        trailing = re.sub(r"^#{1,6}\s+", "", trailing)
        # Strip <h1>...</h1> wrappers
        trailing = re.sub(r"^<h[1-6][^>]*>\s*(.+?)\s*</h[1-6]>$", r"\1", trailing, flags=re.I)
        if trailing:
            return trailing
    # Fall back: prefer a real file name; substitute a placeholder when the
    # file name was lost (malformed diff header) so the clause-id never
    # starts with ``:``.
    return f"{file_path or '<no-file>'}:hunk"


def _split_hunks(diff_text: str) -> list[dict]:
    """Split a unified-diff blob into per-file, per-hunk records.

    Returns a list of dicts with keys ``file``, ``header``, ``body``.
    """
    hunks: list[dict] = []
    current_file = ""
    current_header = ""
    current_body: list[str] = []
    in_hunk = False

    def flush():
        if in_hunk and current_header:
            # Default to a placeholder when the diff header was malformed
            # and we never captured a real file path.  Without this, the
            # downstream clause-id would start with ``:`` (e.g. ``:hunk``).
            file_for_record = current_file if current_file else "<no-file>"
            hunks.append(
                {
                    "file": file_for_record,
                    "header": current_header,
                    "body": "\n".join(current_body),
                }
            )

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            flush()
            in_hunk = False
            current_header = ""
            current_body = []
            # diff --git a/path/to/file b/path/to/file
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[2][2:] if parts[2].startswith("a/") else parts[2]
            else:
                current_file = ""
            continue
        if line.startswith("+++ b/"):
            current_file = line[len("+++ b/") :].strip()
            continue
        if line.startswith("@@"):
            flush()
            current_header = line
            current_body = []
            in_hunk = True
            continue
        if in_hunk:
            current_body.append(line)

    flush()
    return hunks


def collect_diff_hunks(repo_root: Path, baseline_ref: str = "auto") -> list[dict]:
    """Extract per-clause diff hunks vs ``baseline_ref``.

    Args:
        repo_root: Path to the working tree to inspect.
        baseline_ref: Git ref to diff against, or ``"auto"`` to auto-detect
            via tags / ``origin/main`` / ``main``.

    Returns:
        List of dicts, each with keys::

            clause_id  — heading id pulled from the hunk header (best-effort)
            before     — concatenation of removed lines (without ``-`` prefix)
            after      — concatenation of added   lines (without ``+`` prefix)
            context    — concatenation of context lines (no leading marker)
            file       — source file path (relative to repo_root)
    """
    resolved = _resolve_baseline_ref(repo_root, baseline_ref)
    diff_text = _run_git(
        repo_root,
        "diff",
        "-U5",
        resolved,
        "--",
        "*.bs",
    )
    if not diff_text.strip():
        # Fall back to diffing the entire tree if no .bs pathspec match
        diff_text = _run_git(repo_root, "diff", "-U5", resolved)

    raw_hunks = _split_hunks(diff_text)
    out: list[dict] = []
    for h in raw_hunks:
        before_lines: list[str] = []
        after_lines: list[str] = []
        context_lines: list[str] = []
        for line in h["body"].splitlines():
            if not line:
                context_lines.append("")
                continue
            tag = line[0]
            rest = line[1:]
            if tag == "+":
                after_lines.append(rest)
            elif tag == "-":
                before_lines.append(rest)
            elif tag == " ":
                context_lines.append(rest)
            # Skip "\ No newline at end of file" markers (start with \)
        out.append(
            {
                "clause_id": _extract_clause_id(h["header"], h["file"]),
                "before": "\n".join(before_lines),
                "after": "\n".join(after_lines),
                "context": "\n".join(context_lines),
                "file": h["file"],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def build_prompt(hunks: list[dict]) -> str:
    """Assemble a prompt asking the LLM to summarise per-clause changes.

    The prompt is intentionally explicit about (a) what is being analysed,
    (b) the output JSON schema, and (c) the severity rubric.  The schema
    matches :class:`ReviewResult` so downstream parsing is straightforward.
    """
    header = (
        f"You are reviewing diffs from a draft video-coding specification "
        f"(JVET/MPEG/3GPP/AOMedia style).  Prompt version: {PROMPT_VERSION}.\n\n"
        "For each diff hunk, produce a concise human-grade change summary "
        "suitable as the basis for a ballot-comment response.  Flag any "
        "terminology drift (same concept renamed, inconsistent capitalisation, "
        "shifting normative keyword usage, etc.) and assign an overall "
        "severity per hunk:\n"
        "  - 'info'     — neutral wording / editorial change\n"
        "  - 'warning'  — possible inconsistency or minor semantic drift\n"
        "  - 'critical' — likely substantive technical change\n\n"
        "Reply with **only** a JSON array of objects matching this schema:\n"
        "  {\n"
        '    "clause_id": <string>,\n'
        '    "summary": <string, 1-3 sentences>,\n'
        '    "terminology_drift": <array of short strings, may be empty>,\n'
        '    "severity": "info" | "warning" | "critical"\n'
        "  }\n"
        "Do not include any prose outside the JSON array.\n\n"
        "Diff hunks follow:\n"
    )

    blocks: list[str] = []
    for i, h in enumerate(hunks, start=1):
        blocks.append(
            f"--- Hunk {i} ---\n"
            f"file: {h.get('file', '?')}\n"
            f"clause_id: {h.get('clause_id', '?')}\n"
            f"\n[CONTEXT]\n{h.get('context', '')}\n"
            f"\n[BEFORE]\n{h.get('before', '')}\n"
            f"\n[AFTER]\n{h.get('after', '')}\n"
        )

    return header + "\n".join(blocks)


# ---------------------------------------------------------------------------
# HTTP / Anthropic call
# ---------------------------------------------------------------------------


def call_anthropic(
    prompt: str,
    *,
    model: str,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """POST ``prompt`` to the Anthropic Messages API and return the text body.

    Args:
        prompt: Full user prompt (the entire LLM input).
        model: Model identifier (e.g. ``claude-sonnet-4.6``).
        api_key: Anthropic API key.  Never logged or persisted.
        timeout: HTTP timeout in seconds.
        max_tokens: Token budget for the response.

    Returns:
        The text from the first ``content`` block of the first message.

    Raises:
        ValueError: If ``api_key`` is empty.
        RuntimeError: On any HTTP error or malformed response.
    """
    if not api_key:
        raise ValueError("Anthropic API key is required (set ANTHROPIC_API_KEY).")

    # Local import: avoids importing requests at module-load when the
    # AI-review feature is not exercised.
    import requests

    headers = {
        "x-api-key": api_key,
        "anthropic-version": ANTHROPIC_API_VERSION,
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        response = requests.post(
            ANTHROPIC_API_URL,
            headers=headers,
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Anthropic API request failed: {exc}") from exc

    if response.status_code != 200:
        # Never log headers (contains api key)
        body_excerpt = (response.text or "")[:500]
        raise RuntimeError(f"Anthropic API returned HTTP {response.status_code}: {body_excerpt}")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Anthropic API returned non-JSON body: {exc}") from exc

    content = data.get("content")
    if not isinstance(content, list) or not content:
        raise RuntimeError(f"Anthropic API response has no 'content' blocks: {data!r}")

    first = content[0]
    if not isinstance(first, dict) or "text" not in first:
        raise RuntimeError(f"Anthropic API first content block missing 'text': {first!r}")

    return str(first["text"])


# ---------------------------------------------------------------------------
# Caching layer
# ---------------------------------------------------------------------------


def _hunks_cache_key(hunks: list[dict], model: str) -> str:
    """SHA-256 of ``(diff_hunks + model + PROMPT_VERSION)``."""
    payload = {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "hunks": [
            {
                "clause_id": h.get("clause_id", ""),
                "before": h.get("before", ""),
                "after": h.get("after", ""),
                "context": h.get("context", ""),
                "file": h.get("file", ""),
            }
            for h in hunks
        ],
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _parse_results(raw_text: str) -> list[ReviewResult]:
    """Parse the LLM response (a JSON array) into ``ReviewResult`` records.

    Lenient: if the LLM wraps the JSON in code fences or trailing prose,
    we extract the first ``[...]`` block.  Records with missing fields
    are filled with sensible defaults so a malformed LLM response never
    crashes the build.
    """
    text = raw_text.strip()
    # Strip ```json ... ``` fences if present
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    # Find the outermost JSON array
    m = re.search(r"\[.*\]", text, flags=re.DOTALL)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logging.warning(f"AI review: could not parse LLM response as JSON: {exc}")
        return []
    if not isinstance(data, list):
        logging.warning("AI review: LLM response was not a JSON array")
        return []

    out: list[ReviewResult] = []
    valid_severities = {"info", "warning", "critical"}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        severity = str(entry.get("severity", "info")).lower().strip()
        if severity not in valid_severities:
            severity = "info"
        drift_raw = entry.get("terminology_drift") or []
        drift: list[str] = [str(x) for x in drift_raw] if isinstance(drift_raw, list) else []
        out.append(
            {
                "clause_id": str(entry.get("clause_id", "?")),
                "summary": str(entry.get("summary", "")),
                "terminology_drift": drift,
                "severity": severity,
            }
        )
    return out


def cached_review(
    hunks: list[dict],
    *,
    model: str,
    api_key: str,
    cache_dir: Path,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[ReviewResult]:
    """Return parsed review results, using the on-disk cache when possible.

    Cache hits: read ``<cache_dir>/<sha256>.json`` and return it.
    Cache miss: call the LLM, parse the response, persist it, and return.
    """
    if not hunks:
        return []

    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _hunks_cache_key(hunks, model)
    cache_file = cache_dir / f"{key}.json"

    if cache_file.exists():
        try:
            cached_raw = cache_file.read_text(encoding="utf-8")
            data = json.loads(cached_raw)
            if isinstance(data, dict) and "raw_text" in data:
                return _parse_results(data["raw_text"])
        except (OSError, json.JSONDecodeError) as exc:
            logging.debug(f"AI review: cache read failed ({exc}); re-querying")

    prompt = build_prompt(hunks)
    raw_text = call_anthropic(
        prompt,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_tokens=max_tokens,
    )
    # Persist (the response only — never the api key, never the prompt
    # outside the cache dir).
    try:
        cache_file.write_text(
            json.dumps({"raw_text": raw_text, "model": model, "prompt_version": PROMPT_VERSION}),
            encoding="utf-8",
        )
    except OSError as exc:
        logging.debug(f"AI review: cache write failed ({exc})")

    return _parse_results(raw_text)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def write_review_report(results: list[ReviewResult], output_path: Path) -> None:
    """Write a markdown ``ai_review.md`` report grouping entries by severity.

    Sections: Overview, Per-clause changes, Terminology-drift flags.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    severities = ("critical", "warning", "info")
    by_sev: dict[str, list[ReviewResult]] = {s: [] for s in severities}
    for r in results:
        by_sev.setdefault(r.get("severity", "info"), []).append(r)

    lines: list[str] = []
    lines.append("# AI-Assisted Change Review")
    lines.append("")
    lines.append(
        "_Generated by specbuild ``--ai-review``.  This report is advisory "
        "only — always verify against the source spec before acting on any "
        "flagged item._"
    )
    lines.append("")

    # Overview
    lines.append("## Overview")
    lines.append("")
    if not results:
        lines.append("No reviewable changes were detected.")
        lines.append("")
    else:
        total = len(results)
        lines.append(f"- Total reviewed clauses: **{total}**")
        for sev in severities:
            n = len(by_sev.get(sev, []))
            lines.append(f"- {sev.capitalize()}: **{n}**")
        lines.append("")

    # Per-clause changes (grouped by severity, critical first)
    lines.append("## Per-clause changes")
    lines.append("")
    if not results:
        lines.append("_No clauses reviewed._")
        lines.append("")
    else:
        for sev in severities:
            entries = by_sev.get(sev, [])
            if not entries:
                continue
            lines.append(f"### Severity: {sev}")
            lines.append("")
            for r in entries:
                clause = r.get("clause_id", "?")
                summary = r.get("summary", "").strip() or "_(no summary)_"
                lines.append(f"- **{clause}** — {summary}")
            lines.append("")

    # Terminology-drift section
    lines.append("## Terminology-drift flags")
    lines.append("")
    drift_entries = [r for r in results if r.get("terminology_drift")]
    if not drift_entries:
        lines.append("_No terminology drift flagged._")
        lines.append("")
    else:
        for r in drift_entries:
            clause = r.get("clause_id", "?")
            lines.append(f"- **{clause}**")
            for note in r.get("terminology_drift", []):
                lines.append(f"  - {note}")
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------


def run_ai_review(
    repo_root: Path,
    *,
    baseline: str = "auto",
    output_path: Path,
    dry_run: bool = False,
    model: str | None = None,
    api_key: str | None = None,
    cache_dir: Path | None = None,
) -> int:
    """Top-level entry for the ``--ai-review`` build step.

    Args:
        repo_root: Working-tree root (the git repo to diff).
        baseline: Git ref to diff against, or ``"auto"``.
        output_path: Destination ``ai_review.md`` path.
        dry_run: If True, print the prompt to stdout and return 0 without
            calling the LLM.
        model: Override default model (otherwise read from
            ``SPECBUILD_AI_MODEL`` env var or :data:`DEFAULT_MODEL`).
        api_key: Override the API key (otherwise read from
            ``ANTHROPIC_API_KEY``).  Never logged.
        cache_dir: Override the cache directory.

    Returns:
        ``0`` on success (or dry-run, or no-op when there are no hunks);
        ``1`` if the LLM call failed or required configuration was missing.
    """
    resolved_model = (
        model if model is not None else os.environ.get("SPECBUILD_AI_MODEL", DEFAULT_MODEL)
    )
    resolved_cache_dir = cache_dir if cache_dir is not None else DEFAULT_CACHE_DIR

    hunks = collect_diff_hunks(repo_root, baseline)
    if not hunks:
        logging.info("--ai-review: no diff hunks found vs baseline; writing empty report.")
        write_review_report([], output_path)
        return 0

    if dry_run:
        prompt = build_prompt(hunks)
        # Write to stdout (so it can be captured / inspected) and skip API.
        print(prompt)
        return 0

    resolved_key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    if not resolved_key:
        logging.warning("--ai-review requires ANTHROPIC_API_KEY env var")
        return 1

    try:
        results = cached_review(
            hunks,
            model=resolved_model,
            api_key=resolved_key,
            cache_dir=resolved_cache_dir,
        )
    except Exception as exc:  # noqa: BLE001 — never let the LLM crash the build
        logging.error(f"--ai-review: LLM call failed: {exc}")
        return 1

    write_review_report(results, output_path)
    logging.info(f"--ai-review: wrote {output_path} ({len(results)} entries)")
    return 0


__all__ = [
    "PROMPT_VERSION",
    "DEFAULT_MODEL",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_MAX_TOKENS",
    "DEFAULT_TIMEOUT",
    "ReviewResult",
    "collect_diff_hunks",
    "build_prompt",
    "call_anthropic",
    "cached_review",
    "write_review_report",
    "run_ai_review",
]


# Silence the "imported but unused" lint for the optional Any/Dict typing
_: tuple[Any, ...] = ()

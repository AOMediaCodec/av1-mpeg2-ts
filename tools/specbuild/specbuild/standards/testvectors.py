"""Test-vector / conformance-bitstream manifest support.

Video coding specifications (HEVC, VVC, AV1, AV2, etc.) ship with
conformance bitstreams that exercise specific clauses of the spec.  Over
time those bitstream archives drift away from the spec text — clauses
get renumbered, vectors are added or retired, and hash records become
stale.

This module provides a small, self-contained framework for keeping a
conformance archive in sync with the prose:

* :class:`TestVector` — dataclass describing a single bitstream
  (filename, sha256, the clause IDs it exercises, optional profile and
  description).
* :func:`load_manifest` — parse a TOML manifest into a list of
  :class:`TestVector` objects.
* :func:`validate_manifest` — verify each referenced bitstream exists at
  ``root / path`` and (optionally) recompute its sha256.
* :func:`generate_coverage_matrix` — walk the compiled spec ``soup`` and
  build a ``{clause_id: [vector_names]}`` matrix, separately tracking
  clauses with zero vectors.
* :func:`write_coverage_report` — emit a self-contained HTML report
  (vector-by-clause table + coverage summary).
* :func:`report_validation_issues` — log issues at ``WARNING`` and (in
  strict mode) raise :class:`SystemExit`.

The manifest format is intentionally minimal::

    [[vectors]]
    name        = "AVC_intra_8bit_001"
    path        = "vectors/AVC/intra/AVC_intra_8bit_001.h264"
    sha256      = "abcdef..."
    clauses     = ["7.3.2.1", "8.5.3"]
    description = "8-bit intra-only stream exercising slice_header()"
    profile     = "Main"
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

#: Streaming chunk size for sha256 computation (64 KB).
_SHA256_CHUNK_SIZE = 64 * 1024

#: Regex matching a well-formed lowercase hex sha256 digest.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

#: Required keys on every ``[[vectors]]`` entry.
_REQUIRED_FIELDS = ("name", "path", "sha256", "clauses")


# ═══════════════════════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class TestVector:
    """A single conformance bitstream entry.

    Attributes:
        name: Unique vector name (also used as the display label).
        path: Filesystem path relative to the manifest's parent directory.
        sha256: Lowercase hex sha256 digest of the bitstream file.
        clauses: List of clause IDs the vector exercises (e.g.
            ``["7.3.2.1", "8.5.3"]``).
        description: Optional human-readable description.
        profile: Optional codec profile (e.g. ``"Main"``, ``"Main 10"``).
    """

    # Tell pytest not to collect this class — the ``Test`` prefix is part
    # of the spec-domain name, not a test class.
    __test__ = False

    name: str
    path: str
    sha256: str
    clauses: list[str] = field(default_factory=list)
    description: str = ""
    profile: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Manifest loading
# ═══════════════════════════════════════════════════════════════════════════


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file using stdlib ``tomllib`` (3.11+) or ``tomli``."""
    try:
        import tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:  # pragma: no cover — Python <3.11 fallback
        try:
            import tomli as tomllib  # type: ignore[import-not-found, no-redef]
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "TOML support requires Python 3.11+ or the 'tomli' package. "
                "Install it with: pip install tomli"
            ) from exc
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_manifest(path: Path) -> list[TestVector]:
    """Parse a TOML test-vector manifest into :class:`TestVector` objects.

    Args:
        path: Path to the manifest file.

    Returns:
        List of parsed :class:`TestVector` entries (in declaration order).

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the manifest is malformed (missing required field,
            wrong type for ``clauses``, etc.).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Test-vector manifest not found: {path}")

    data = _load_toml(path)
    raw_vectors = data.get("vectors", [])
    if not isinstance(raw_vectors, list):
        raise ValueError(
            f"{path}: '[[vectors]]' must be an array of tables, got {type(raw_vectors).__name__}"
        )

    vectors: list[TestVector] = []
    for index, entry in enumerate(raw_vectors):
        if not isinstance(entry, dict):
            raise ValueError(f"{path}: vector #{index} must be a table, got {type(entry).__name__}")
        for key in _REQUIRED_FIELDS:
            if key not in entry:
                raise ValueError(f"{path}: vector #{index} missing required field '{key}'")

        clauses = entry["clauses"]
        if not isinstance(clauses, list) or not all(isinstance(c, str) for c in clauses):
            raise ValueError(f"{path}: vector #{index} 'clauses' must be a list of strings")

        vectors.append(
            TestVector(
                name=str(entry["name"]),
                path=str(entry["path"]),
                sha256=str(entry["sha256"]).lower(),
                clauses=list(clauses),
                description=str(entry.get("description", "")),
                profile=entry.get("profile"),
            )
        )

    return vectors


# ═══════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════


def _stream_sha256(file_path: Path, chunk_size: int = _SHA256_CHUNK_SIZE) -> str:
    """Compute sha256 of *file_path* by streaming ``chunk_size`` bytes at a time."""
    digest = hashlib.sha256()
    with file_path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(
    vectors: list[TestVector],
    root: Path,
    *,
    check_hashes: bool = True,
) -> list[dict[str, str]]:
    """Validate that every referenced bitstream exists with the recorded hash.

    Args:
        vectors: Parsed test vectors from :func:`load_manifest`.
        root: Directory the manifest paths are resolved against (typically
            the manifest file's parent directory).
        check_hashes: When ``True`` (default), recompute sha256 for each
            file and compare against the manifest entry.  When ``False``,
            only file existence and digest format are checked.

    Returns:
        A list of issue dicts with keys ``name``, ``path``, ``kind``, and
        ``message``.  ``kind`` is one of:

        * ``"missing_file"`` — file does not exist on disk.
        * ``"hash_mismatch"`` — sha256 differs from manifest record.
        * ``"malformed_sha256"`` — recorded digest is not 64 lowercase hex.
        * ``"path_outside_root"`` — vector ``path`` resolves to a location
          outside *root* (path traversal: e.g. ``../../etc/passwd``).
          The file is reported but never opened or hashed.
    """
    root = Path(root)
    root_resolved = root.resolve()
    issues: list[dict[str, str]] = []

    for vector in vectors:
        file_path = root / vector.path

        # Reject any path that resolves outside *root* (e.g. ``../etc/passwd``).
        # We compare resolved absolute paths so symlink chains are also caught.
        # ``resolve(strict=False)`` is used so non-existent paths still
        # collapse ``..`` segments without raising.
        try:
            resolved = file_path.resolve()
        except OSError:
            resolved = file_path
        if not resolved.is_relative_to(root_resolved):
            issues.append(
                {
                    "name": vector.name,
                    "path": str(file_path),
                    "kind": "path_outside_root",
                    "message": (
                        f"vector path resolves outside manifest root: {vector.path!r} → {resolved}"
                    ),
                }
            )
            # Do NOT touch the filesystem for paths we have rejected.
            continue

        # 1. Always validate that the recorded digest is well-formed.
        if not _SHA256_RE.match(vector.sha256):
            issues.append(
                {
                    "name": vector.name,
                    "path": str(file_path),
                    "kind": "malformed_sha256",
                    "message": (
                        f"recorded sha256 is not 64 lowercase hex characters: {vector.sha256!r}"
                    ),
                }
            )

        # 2. File must exist on disk.
        if not file_path.exists():
            issues.append(
                {
                    "name": vector.name,
                    "path": str(file_path),
                    "kind": "missing_file",
                    "message": f"bitstream file not found: {file_path}",
                }
            )
            continue

        # 3. Optionally recompute and compare sha256.
        if check_hashes and _SHA256_RE.match(vector.sha256):
            actual = _stream_sha256(file_path)
            if actual != vector.sha256:
                issues.append(
                    {
                        "name": vector.name,
                        "path": str(file_path),
                        "kind": "hash_mismatch",
                        "message": (
                            f"sha256 mismatch: manifest records {vector.sha256}, file is {actual}"
                        ),
                    }
                )

    return issues


def report_validation_issues(issues: list[dict[str, str]], *, strict: bool = False) -> None:
    """Log validation issues at ``WARNING``; exit non-zero if *strict*.

    Args:
        issues: Issue dicts from :func:`validate_manifest`.
        strict: When ``True`` and at least one issue is present, raise
            :class:`SystemExit` with code 1 after logging.
    """
    for issue in issues:
        logging.warning(
            "test-vector %s [%s]: %s",
            issue.get("name", "<unknown>"),
            issue.get("kind", "<unknown>"),
            issue.get("message", ""),
        )
    if strict and issues:
        logging.error(
            "Test-vector manifest validation failed with %d issue(s) (strict mode).",
            len(issues),
        )
        raise SystemExit(1)


# ═══════════════════════════════════════════════════════════════════════════
# Coverage matrix
# ═══════════════════════════════════════════════════════════════════════════


def _extract_clause_ids(soup: BeautifulSoup) -> list[str]:
    """Return ordered, de-duplicated clause IDs from ``<h2>``/``<h3>`` tags.

    Falls back to scanning ``<dfn id="...">`` tags when no headings carry
    IDs, which lets the matrix work on bare-bones test fixtures.
    """
    seen: dict[str, None] = {}
    for tag in soup.find_all(["h2", "h3"]):
        clause_id = tag.get("id")
        if clause_id and clause_id not in seen:
            seen[clause_id] = None
    if not seen:
        for dfn in soup.find_all("dfn"):
            clause_id = dfn.get("id")
            if clause_id and clause_id not in seen:
                seen[clause_id] = None
    return list(seen)


def generate_coverage_matrix(vectors: list[TestVector], soup: BeautifulSoup) -> dict[str, Any]:
    """Build a clause→vectors coverage matrix from the compiled spec.

    Walks the spec ``soup``, collects every ``<h2>``/``<h3>`` (or, as a
    fallback, ``<dfn>``) ID, and maps each clause ID to the names of the
    test vectors that reference it.  Clause IDs that no vector touches
    are recorded separately under ``uncovered``.

    Args:
        vectors: Test vectors from :func:`load_manifest`.
        soup: Parsed spec HTML.

    Returns:
        ``{"matrix": {clause_id: [vector_names]}, "uncovered": [...],
        "total_clauses": int, "covered_clauses": int}``.
    """
    clause_ids = _extract_clause_ids(soup)
    clause_set = set(clause_ids)

    matrix: dict[str, list[str]] = {cid: [] for cid in clause_ids}
    for vector in vectors:
        for clause in vector.clauses:
            if clause in clause_set:
                # Avoid duplicate names if a vector lists the same clause twice.
                if vector.name not in matrix[clause]:
                    matrix[clause].append(vector.name)
            else:
                # Record extra clauses (referenced but not present in spec)
                # so they show up alongside the rest in the matrix.  This
                # keeps the report informative when the spec is partially
                # built or clause IDs have been renumbered.
                matrix.setdefault(clause, [])
                if vector.name not in matrix[clause]:
                    matrix[clause].append(vector.name)

    uncovered = [cid for cid in clause_ids if not matrix[cid]]
    covered = sum(1 for cid in clause_ids if matrix[cid])
    return {
        "matrix": matrix,
        "uncovered": uncovered,
        "total_clauses": len(clause_ids),
        "covered_clauses": covered,
    }


# ═══════════════════════════════════════════════════════════════════════════
# HTML report
# ═══════════════════════════════════════════════════════════════════════════


_REPORT_CSS = """\
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       margin: 2em; color: #222; }
h1 { border-bottom: 2px solid #333; padding-bottom: 0.3em; }
h2 { margin-top: 2em; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5em; }
th, td { border: 1px solid #ccc; padding: 0.4em 0.7em; text-align: left;
         vertical-align: top; font-size: 0.95em; }
th { background: #f0f0f0; }
tr.uncovered td { background: #ffe5e5; }
tr.uncovered td.count { color: #b00; font-weight: bold; }
.summary { background: #f7f7f7; padding: 0.8em 1em; border-left: 4px solid #666;
           margin-bottom: 1.5em; }
code { font-family: "SFMono-Regular", Menlo, Consolas, monospace;
       font-size: 0.92em; }
"""


def _render_vector_table(vectors: list[TestVector]) -> str:
    """Render the per-vector table (vector-by-clause)."""
    rows: list[str] = []
    for vector in vectors:
        clauses_html = ", ".join(html.escape(c) for c in vector.clauses) or "<em>(none)</em>"
        profile = html.escape(vector.profile) if vector.profile else ""
        rows.append(
            "<tr>"
            f"<td><code>{html.escape(vector.name)}</code></td>"
            f"<td><code>{html.escape(vector.path)}</code></td>"
            f"<td>{profile}</td>"
            f"<td>{clauses_html}</td>"
            f"<td>{html.escape(vector.description)}</td>"
            "</tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else ('<tr><td colspan="5"><em>No test vectors registered.</em></td></tr>')
    )
    return (
        "<table>\n"
        "<thead><tr>"
        "<th>Vector</th><th>Path</th><th>Profile</th>"
        "<th>Clauses</th><th>Description</th>"
        "</tr></thead>\n"
        f"<tbody>\n{body}\n</tbody>\n"
        "</table>"
    )


def _render_coverage_table(matrix: dict[str, list[str]]) -> str:
    """Render the clause-coverage-summary table."""
    rows: list[str] = []
    for clause_id, vector_names in matrix.items():
        count = len(vector_names)
        cls = ' class="uncovered"' if count == 0 else ""
        names_html = (
            ", ".join(f"<code>{html.escape(n)}</code>" for n in vector_names)
            if vector_names
            else "<em>uncovered</em>"
        )
        rows.append(
            f"<tr{cls}>"
            f"<td><code>{html.escape(clause_id)}</code></td>"
            f'<td class="count">{count}</td>'
            f"<td>{names_html}</td>"
            "</tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else ('<tr><td colspan="3"><em>No clauses extracted from spec.</em></td></tr>')
    )
    return (
        "<table>\n"
        "<thead><tr>"
        "<th>Clause ID</th><th>Vector count</th><th>Vectors</th>"
        "</tr></thead>\n"
        f"<tbody>\n{body}\n</tbody>\n"
        "</table>"
    )


def write_coverage_report(
    matrix: dict[str, Any],
    vectors: list[TestVector],
    output_path: Path,
) -> None:
    """Write a self-contained HTML coverage report to *output_path*.

    The report contains two tables:

    1. **Vector-by-clause** — one row per :class:`TestVector` listing the
       clauses it exercises.
    2. **Clause-coverage summary** — one row per clause with a vector
       count; rows for clauses with zero vectors are highlighted red.

    Args:
        matrix: Output of :func:`generate_coverage_matrix`.
        vectors: Original list of test vectors.
        output_path: Destination HTML path.  Parent directories are
            created automatically.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    clause_matrix = matrix.get("matrix", {})
    uncovered = matrix.get("uncovered", [])
    total = matrix.get("total_clauses", 0)
    covered = matrix.get("covered_clauses", 0)
    pct = (covered * 100 // total) if total else 0

    summary_html = (
        f'<div class="summary">'
        f"<strong>Test vectors:</strong> {len(vectors)} &middot; "
        f"<strong>Clauses:</strong> {total} &middot; "
        f"<strong>Covered:</strong> {covered} ({pct}%) &middot; "
        f"<strong>Uncovered:</strong> {len(uncovered)}"
        f"</div>"
    )

    page = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        "<title>Test-Vector Coverage Report</title>\n"
        f"<style>{_REPORT_CSS}</style>\n"
        "</head>\n<body>\n"
        "<h1>Test-Vector Coverage Report</h1>\n"
        f"{summary_html}\n"
        "<h2>Vectors</h2>\n"
        f"{_render_vector_table(vectors)}\n"
        "<h2>Clause coverage</h2>\n"
        f"{_render_coverage_table(clause_matrix)}\n"
        "</body>\n</html>\n"
    )
    output_path.write_text(page, encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Cross-spec crosswalk (vector migration between spec versions)
# ═══════════════════════════════════════════════════════════════════════════


def _load_clause_map(path: Path | None) -> dict[str, str]:
    """Load an optional ``old_clause -> new_clause`` mapping from TOML.

    Schema::

        [clause_map]
        "7.3.2.1" = "7.4.2.1"
        "8.5.3"   = "8.6.4"

    Returns an empty dict if *path* is ``None`` or the file is empty.
    """
    if path is None:
        return {}
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Clause map not found: {path}")
    data = _load_toml(path)
    raw = data.get("clause_map", {})
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: 'clause_map' must be a table")
    return {str(k): str(v) for k, v in raw.items()}


def crosswalk_vectors(
    old_vectors: list[TestVector],
    new_clauses: set[str],
    *,
    clause_map: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Classify each OLD vector by how it maps onto NEW clause IDs.

    Categories:

    * ``unchanged`` — every clause id of the vector still exists in NEW.
    * ``retargeted`` — at least one clause needs renaming (via *clause_map*)
      and *all* mapped clauses survive.
    * ``retired`` — at least one clause has neither a direct match nor a
      mapping entry pointing into NEW.

    Returns:
        ``{"unchanged": [...], "retargeted": [...], "retired": [...]}``,
        each entry a dict with ``name``, ``old_clauses``, ``new_clauses``,
        and ``description`` keys.
    """
    clause_map = clause_map or {}
    out: dict[str, list[dict[str, Any]]] = {
        "unchanged": [],
        "retargeted": [],
        "retired": [],
    }
    for v in old_vectors:
        new_clauses_for_v: list[str] = []
        any_mapped = False
        any_missing = False
        for c in v.clauses:
            if c in new_clauses:
                new_clauses_for_v.append(c)
                continue
            mapped = clause_map.get(c)
            if mapped and mapped in new_clauses:
                new_clauses_for_v.append(mapped)
                any_mapped = True
                continue
            any_missing = True
        record = {
            "name": v.name,
            "old_clauses": list(v.clauses),
            "new_clauses": new_clauses_for_v,
            "description": v.description,
        }
        if any_missing:
            out["retired"].append(record)
        elif any_mapped:
            out["retargeted"].append(record)
        else:
            out["unchanged"].append(record)
    return out


def _render_crosswalk_section(title: str, records: list[dict[str, Any]]) -> str:
    """Render a labelled HTML table for one crosswalk category."""
    if not records:
        body = '<tr><td colspan="4"><em>(none)</em></td></tr>'
    else:
        rows = []
        for r in records:
            old_html = ", ".join(html.escape(c) for c in r["old_clauses"]) or "—"
            new_html = ", ".join(html.escape(c) for c in r["new_clauses"]) or "—"
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(r['name'])}</code></td>"
                f"<td>{old_html}</td>"
                f"<td>{new_html}</td>"
                f"<td>{html.escape(r.get('description', ''))}</td>"
                "</tr>"
            )
        body = "\n".join(rows)
    return (
        f"<h2>{html.escape(title)} <small>({len(records)})</small></h2>\n"
        "<table>\n"
        "<thead><tr><th>Vector</th><th>Old clauses</th>"
        "<th>New clauses</th><th>Description</th></tr></thead>\n"
        f"<tbody>\n{body}\n</tbody>\n"
        "</table>"
    )


def write_crosswalk_report(
    crosswalk: dict[str, list[dict[str, Any]]],
    output_path: Path,
    *,
    old_label: str = "OLD",
    new_label: str = "NEW",
) -> None:
    """Write a self-contained HTML crosswalk report."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    counts = {k: len(v) for k, v in crosswalk.items()}
    summary = (
        f"<p><code>{html.escape(old_label)}</code> &rarr; "
        f"<code>{html.escape(new_label)}</code><br>"
        f"unchanged: <strong>{counts.get('unchanged', 0)}</strong>, "
        f"retargeted: <strong>{counts.get('retargeted', 0)}</strong>, "
        f"retired: <strong>{counts.get('retired', 0)}</strong></p>"
    )
    body = "\n".join(
        [
            _render_crosswalk_section("Unchanged", crosswalk.get("unchanged", [])),
            _render_crosswalk_section("Retargeted", crosswalk.get("retargeted", [])),
            _render_crosswalk_section("Retired", crosswalk.get("retired", [])),
        ]
    )
    page = (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        "<title>Test-Vector Crosswalk</title>"
        f"<style>{_REPORT_CSS}</style></head><body>\n"
        "<h1>Test-Vector Crosswalk</h1>\n"
        f'<div class="summary">{summary}</div>\n'
        f"{body}\n"
        "</body></html>\n"
    )
    output_path.write_text(page, encoding="utf-8")


def run_crosswalk(
    old_manifest: Path,
    new_manifest: Path,
    output_path: Path,
    *,
    clause_map_path: Path | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """End-to-end: load both manifests, derive new-clause set, write report.

    The NEW manifest is treated as the *post-migration* clause inventory:
    its union of clause IDs becomes the survival set against which OLD
    vectors are classified.
    """
    old_vectors = load_manifest(Path(old_manifest))
    new_vectors = load_manifest(Path(new_manifest))
    new_clauses: set[str] = set()
    for v in new_vectors:
        new_clauses.update(v.clauses)
    clause_map = _load_clause_map(Path(clause_map_path)) if clause_map_path else {}
    crosswalk = crosswalk_vectors(old_vectors, new_clauses, clause_map=clause_map)
    write_crosswalk_report(
        crosswalk,
        Path(output_path),
        old_label=Path(old_manifest).stem,
        new_label=Path(new_manifest).stem,
    )
    logging.info(
        "testvector-crosswalk: unchanged=%d retargeted=%d retired=%d -> %s",
        len(crosswalk["unchanged"]),
        len(crosswalk["retargeted"]),
        len(crosswalk["retired"]),
        output_path,
    )
    return crosswalk


__all__ = [
    "TestVector",
    "load_manifest",
    "validate_manifest",
    "report_validation_issues",
    "generate_coverage_matrix",
    "write_coverage_report",
    "crosswalk_vectors",
    "write_crosswalk_report",
    "run_crosswalk",
]

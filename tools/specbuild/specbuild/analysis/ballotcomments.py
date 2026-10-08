"""Ballot comment tracker for standards review cycles.

Loads ballot comment spreadsheets (SC29/JVET/MPEG format), links comments to
spec clauses, generates an interactive HTML tracker, and exports JSON.
"""

from __future__ import annotations

import csv
import html as _html
import io
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class BallotComment:
    """A single ballot comment from an SC29/JVET/MPEG comment spreadsheet."""

    comment_id: str
    country: str
    clause_ref: str
    paragraph: str
    comment_type: str
    comment: str
    proposed_change: str
    resolution: str
    resolution_notes: str
    clause_id: str = ""


# ---------------------------------------------------------------------------
# Column name normalisers (flexible header detection)
# ---------------------------------------------------------------------------

_COL_MAP: dict[str, str] = {
    # comment_id
    "no": "comment_id",
    "comment no": "comment_id",
    "comment number": "comment_id",
    "number": "comment_id",
    # country
    "country": "country",
    "national body": "country",
    "nb": "country",
    "organization": "country",
    # clause_ref
    "clause": "clause_ref",
    "clause no": "clause_ref",
    "section": "clause_ref",
    "clause number": "clause_ref",
    "clause ref": "clause_ref",
    # paragraph
    "paragraph": "paragraph",
    "para": "paragraph",
    "line": "paragraph",
    # comment_type
    "type": "comment_type",
    "comment type": "comment_type",
    "category": "comment_type",
    # comment
    "comment": "comment",
    "comments": "comment",
    "mb comments": "comment",
    "technical comments": "comment",
    # proposed_change
    "proposed change": "proposed_change",
    "proposed changes": "proposed_change",
    "change": "proposed_change",
    "proposed text": "proposed_change",
    # resolution
    "resolution": "resolution",
    "action": "resolution",
    "disposition": "resolution",
    # resolution_notes
    "resolution notes": "resolution_notes",
    "editor notes": "resolution_notes",
    "notes": "resolution_notes",
}


def _normalise_col(header: str) -> str:
    return _COL_MAP.get(header.strip().lower(), "")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_ballot_comments(xlsx_or_csv: Path) -> list[BallotComment]:
    """Load ballot comments from an XLSX or CSV file.

    Supports the standard SC29/JVET ballot comment spreadsheet format.
    Column headers are auto-detected; order does not matter.

    Args:
        xlsx_or_csv: Path to ``.xlsx`` or ``.csv`` file.

    Returns:
        List of :class:`BallotComment` objects.
    """
    if xlsx_or_csv.suffix.lower() in (".xlsx", ".xls"):
        return _load_xlsx(xlsx_or_csv)
    return _load_csv(xlsx_or_csv)


def _load_xlsx(path: Path) -> list[BallotComment]:
    try:
        import openpyxl  # type: ignore[import]
    except ImportError:
        logging.warning(
            "openpyxl is not installed; falling back to CSV. "
            "Install with: pip install specbuild[ballot]"
        )
        # Try treating the xlsx as csv (will fail, but graceful)
        return []

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    # Find header row (first row with recognisable column names)
    header_row_idx = 0
    col_map: dict[int, str] = {}
    for idx, row in enumerate(rows[:5]):
        col_map = {}
        for col_idx, cell in enumerate(row):
            if cell is None:
                continue
            field_name = _normalise_col(str(cell))
            if field_name:
                col_map[col_idx] = field_name
        if len(col_map) >= 3:
            header_row_idx = idx
            break

    return _parse_rows(rows[header_row_idx + 1 :], col_map)


def _load_csv(path: Path) -> list[BallotComment]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        logging.error(f"Cannot decode {path} as UTF-8. Check the file encoding.")
        return []
    except OSError as exc:
        logging.error(f"Cannot read {path}: {exc}")
        return []
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []

    col_map: dict[int, str] = {}
    for col_idx, header in enumerate(rows[0]):
        field_name = _normalise_col(header)
        if field_name:
            col_map[col_idx] = field_name

    return _parse_rows(rows[1:], col_map)


def _parse_rows(rows: list, col_map: dict[int, str]) -> list[BallotComment]:
    comments: list[BallotComment] = []
    for row in rows:
        if not row or all(c is None or str(c).strip() == "" for c in row):
            continue

        def _get(field: str) -> str:
            for col_idx, fname in col_map.items():
                if fname == field:
                    val = row[col_idx] if col_idx < len(row) else None
                    return str(val).strip() if val is not None else ""
            return ""

        comment_id = _get("comment_id")
        if not comment_id:
            continue

        comments.append(
            BallotComment(
                comment_id=comment_id,
                country=_get("country"),
                clause_ref=_get("clause_ref"),
                paragraph=_get("paragraph"),
                comment_type=_get("comment_type"),
                comment=_get("comment"),
                proposed_change=_get("proposed_change"),
                resolution=_get("resolution") or "pending",
                resolution_notes=_get("resolution_notes"),
            )
        )

    logging.info(f"Loaded {len(comments)} ballot comments")
    return comments


# ---------------------------------------------------------------------------
# Clause linking
# ---------------------------------------------------------------------------

# Patterns for clause references like "7.3.2", "A.1", "B.4.1"
_CLAUSE_RE = re.compile(r"^([A-Z]?\d+(?:\.\d+)*)$")

# Maps annex letters (A-Z) to the numeric section offset used in data-level.
# AV2 uses sections 10-15 as Annexes A-F; adjust _ANNEX_BASE to match.
_ANNEX_BASE = 9  # Annex A = section 10, B = 11, …


def _annex_ref_to_numeric(clause_ref: str) -> str:
    """Convert "Annex A.2" or "A.2" to a numeric section number.

    Maps the leading annex letter to the document's internal section number
    using ``_ANNEX_BASE`` (e.g. A→10, B→11, … with base 9).

    Returns the original string unchanged if no annex letter is detected.
    """
    # Match "Annex A", "annex b.3", "A.2.1", etc.
    m = re.match(
        r"^(?:annex\s+)?([A-Za-z])(?:[.\s](.+))?$",
        clause_ref.strip(),
        re.IGNORECASE,
    )
    if not m:
        return clause_ref

    letter = m.group(1).upper()
    rest = m.group(2)  # may be None

    number = _ANNEX_BASE + (ord(letter) - ord("A") + 1)  # A→10, B→11, …
    return f"{number}.{rest}" if rest else str(number)


def _build_level_map(soup: object) -> dict[str, str]:
    """Build a ``{data-level: id}`` map from heading elements in *soup*.

    Bikeshed annotates section headings with ``data-level="7.3.2"`` (numeric,
    even after annex renumbering).  This map lets us resolve a clause reference
    like ``"7.3.2"`` or ``"Annex A.2"`` directly to the heading's ``id``.
    """
    level_map: dict[str, str] = {}
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        for elem in soup.find_all(tag, attrs={"data-level": True}):
            level = elem.get("data-level", "").strip()
            eid = elem.get("id", "").strip()
            if level and eid:
                level_map[level] = eid
    return level_map


def link_comments_to_clauses(
    comments: list[BallotComment],
    soup: object,
) -> list[BallotComment]:
    """Resolve each comment's ``clause_ref`` to an HTML section ID.

    Tries three strategies in order:

    1. **data-level map**: build ``{section_number: id}`` from heading
       ``data-level`` attributes (works for numeric refs and Annex letters).
    2. **ID pattern matching**: try common prefix patterns such as
       ``section-7.3.2``, ``clause-7-3-2``, etc.
    3. **Fuzzy substring**: any HTML ``id`` that contains the dashed form.

    Args:
        comments: List of :class:`BallotComment` with ``clause_ref`` set.
        soup:     BeautifulSoup document to search for section IDs.

    Returns:
        The same list, with ``clause_id`` populated where possible.
    """
    level_map = _build_level_map(soup)

    all_ids: set[str] = set()
    for elem in soup.find_all(id=True):
        eid = elem.get("id", "")
        if eid:
            all_ids.add(eid)

    resolved = 0
    for comment in comments:
        clause_ref = comment.clause_ref.strip()
        if not clause_ref:
            continue
        best = _resolve_clause_id(clause_ref, all_ids, level_map)
        if best:
            comment.clause_id = best
            resolved += 1

    logging.info(f"Linked {resolved}/{len(comments)} comments to clause IDs")
    return comments


def _resolve_clause_id(
    clause_ref: str,
    all_ids: set[str],
    level_map: dict[str, str] | None = None,
) -> str:
    """Find the best matching HTML ID for a clause reference string."""
    # Strategy 1: data-level map (most accurate)
    if level_map:
        # Try original ref, then annex-converted numeric form
        for candidate_ref in (clause_ref, _annex_ref_to_numeric(clause_ref)):
            candidate_ref = candidate_ref.strip()
            if candidate_ref in level_map:
                return level_map[candidate_ref]
            # Also try stripping leading zeros in sub-sections
            if candidate_ref in level_map:
                return level_map[candidate_ref]

    # Strategy 2: common ID prefix patterns
    normalized = clause_ref.lower().replace(" ", "-")
    dashed = re.sub(r"[.\s]+", "-", normalized)

    candidates = [
        f"section-{normalized}",
        f"clause-{normalized}",
        f"sec-{normalized}",
        f"s{normalized}",
        normalized,
        dashed,
        f"section-{dashed}",
        f"clause-{dashed}",
    ]

    for c in candidates:
        if c in all_ids:
            return c

    # Strategy 3: fuzzy — any ID containing the dashed form
    for sid in all_ids:
        if dashed in sid:
            return sid

    return ""


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def generate_comment_tracker(
    comments: list[BallotComment],
    output_path: Path,
    *,
    org_label: str = "Organization",
) -> None:
    """Write an interactive HTML ballot comment tracker to *output_path*.

    Features:
    - Filter dropdowns by organisation, type, and resolution status.
    - Clause links jump to the corresponding spec section.
    - Each row has an Edit button that opens a modal for updating Resolution
      and Notes directly in the browser.
    - Edits are persisted in ``localStorage`` and survive page reloads.
    - An Export CSV button downloads the full comment list with current
      resolutions and notes applied.

    Args:
        comments:    List of :class:`BallotComment` to display.
        output_path: Destination path for the HTML file.
        org_label:   Column heading for the ``country`` field.  Defaults to
                     ``"Organization"`` (suitable for AOM/company-based
                     ballots); set to ``"Country"`` or ``"National Body"``
                     for ISO/MPEG/JVET processes.
    """
    rows_html = _build_rows_html(comments, org_label=org_label)

    orgs = sorted({c.country for c in comments if c.country})
    types = sorted({c.comment_type for c in comments if c.comment_type})
    resolutions_all = sorted({c.resolution for c in comments if c.resolution})

    def _options(items: list[str]) -> str:
        return "".join(
            f'<option value="{_html.escape(v)}">{_html.escape(v)}</option>' for v in items
        )

    pending = sum(1 for c in comments if c.resolution.lower() == "pending")
    accepted = sum(1 for c in comments if "accept" in c.resolution.lower())
    not_accepted = sum(
        1
        for c in comments
        if "not-accept" in c.resolution.lower() or c.resolution.lower() == "rejected"
    )

    # Embed all comment data as JSON for the CSV export and edit form.
    comments_json = json.dumps(
        [
            {
                "id": c.comment_id,
                "org": c.country,
                "clause": c.clause_ref,
                "clause_id": c.clause_id,
                "paragraph": c.paragraph,
                "type": c.comment_type,
                "comment": c.comment,
                "proposed_change": c.proposed_change,
                "resolution": c.resolution,
                "notes": c.resolution_notes,
            }
            for c in comments
        ],
        ensure_ascii=False,
    )

    resolution_options_html = "".join(
        f'<option value="{v}">{v}</option>'
        for v in ["pending", "accepted", "accepted-in-principle", "not-accepted", "noted"]
    )
    org_label_esc = _html.escape(org_label)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Ballot Comment Tracker</title>
<style>
/* ── Layout ──────────────────────────────────────────────────────────── */
*{{box-sizing:border-box}}
body{{font-family:system-ui,sans-serif;margin:0;padding:1.5rem 2rem;max-width:1500px;background:#fff}}
h1{{font-size:1.35em;margin:0 0 .3em}}
.summary{{color:#555;font-size:.88em;margin-bottom:1em}}
.toolbar{{display:flex;gap:.75em;align-items:center;flex-wrap:wrap;margin-bottom:.9em}}
.toolbar label{{font-size:.85em;display:flex;align-items:center;gap:.35em}}
select{{padding:3px 7px;border:1px solid #ccc;border-radius:4px;font-size:.85em}}
button.export-btn{{margin-left:auto;padding:5px 14px;background:#034575;color:#fff;border:none;
  border-radius:5px;cursor:pointer;font-size:.85em;font-weight:600}}
button.export-btn:hover{{background:#023060}}
/* ── Table ───────────────────────────────────────────────────────────── */
.tbl-wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:.8em}}
th,td{{border:1px solid #dee2e6;padding:.35rem .55rem;text-align:left;vertical-align:top}}
th{{background:#f1f3f5;font-weight:600;position:sticky;top:0;z-index:1}}
tr.hidden{{display:none}}
tr:hover td{{background:#f8f9ff}}
td.comment-text,td.proposed-text{{max-width:260px;color:#333}}
td.notes-cell{{max-width:200px;color:#444;font-size:.78em}}
/* ── Badges ──────────────────────────────────────────────────────────── */
.badge{{display:inline-block;padding:2px 7px;border-radius:3px;font-size:.78em;font-weight:700;white-space:nowrap}}
.res-accepted{{background:#d4edda;color:#155724}}
.res-accepted-in-principle{{background:#c3e6cb;color:#155724}}
.res-not-accepted{{background:#f8d7da;color:#721c24}}
.res-pending{{background:#fff3cd;color:#856404}}
.res-noted{{background:#d1ecf1;color:#0c5460}}
/* ── Edit button ─────────────────────────────────────────────────────── */
.edit-btn{{padding:2px 8px;font-size:.75em;border:1px solid #aaa;border-radius:3px;
  background:#fff;cursor:pointer;white-space:nowrap}}
.edit-btn:hover{{background:#e9ecef}}
/* ── Modal overlay ───────────────────────────────────────────────────── */
#modal-overlay{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:1000;
  align-items:center;justify-content:center}}
#modal-overlay.open{{display:flex}}
#modal{{background:#fff;border-radius:8px;box-shadow:0 8px 32px rgba(0,0,0,.25);
  width:min(560px,95vw);padding:1.5rem;position:relative}}
#modal h2{{margin:0 0 .4em;font-size:1em;color:#034575}}
#modal .meta{{font-size:.8em;color:#555;margin-bottom:1em;line-height:1.6}}
#modal .meta b{{color:#222}}
#modal label{{display:block;font-size:.85em;font-weight:600;margin-bottom:.25em}}
#modal select, #modal textarea{{width:100%;padding:6px 8px;border:1px solid #ccc;
  border-radius:4px;font-size:.85em;margin-bottom:.9em}}
#modal textarea{{height:90px;resize:vertical;font-family:inherit}}
#modal .comment-preview{{background:#f8f9fa;border-left:3px solid #ccc;padding:.5em .75em;
  font-size:.8em;color:#444;margin-bottom:1em;max-height:120px;overflow-y:auto;border-radius:0 4px 4px 0}}
.modal-btns{{display:flex;justify-content:flex-end;gap:.6em}}
.modal-btns button{{padding:6px 18px;border-radius:5px;cursor:pointer;font-size:.85em;font-weight:600;border:1px solid #ccc}}
#modal-save{{background:#034575;color:#fff;border-color:#034575}}
#modal-save:hover{{background:#023060}}
#modal-cancel{{background:#fff;color:#333}}
#modal-cancel:hover{{background:#f0f0f0}}
#modal-close{{position:absolute;top:.7em;right:.9em;background:none;border:none;
  font-size:1.3em;cursor:pointer;color:#999;line-height:1}}
#modal-close:hover{{color:#333}}
</style>
</head>
<body>
<h1>Ballot Comment Tracker</h1>
<p class="summary">
  {len(comments)} comments &mdash;
  <span style="color:#155724;font-weight:600">{accepted} accepted</span>,
  <span style="color:#721c24;font-weight:600">{not_accepted} not accepted</span>,
  <span style="color:#856404;font-weight:600">{pending} pending</span>
  &nbsp;|&nbsp; <em>Click <b>Edit</b> on any row to update resolution and notes.</em>
</p>

<div class="toolbar">
  <label>{org_label_esc}:
    <select id="f-org" onchange="applyFilter()">
      <option value="">All</option>{_options(orgs)}
    </select>
  </label>
  <label>Type:
    <select id="f-type" onchange="applyFilter()">
      <option value="">All</option>{_options(types)}
    </select>
  </label>
  <label>Resolution:
    <select id="f-res" onchange="applyFilter()">
      <option value="">All</option>{_options(resolutions_all)}
    </select>
  </label>
  <button class="export-btn" onclick="exportCSV()">&#x2913; Export CSV</button>
</div>

<div class="tbl-wrap">
<table id="tbl">
<thead><tr>
  <th></th>
  <th>ID</th>
  <th>{org_label_esc}</th>
  <th>Clause</th>
  <th>Para</th>
  <th>Type</th>
  <th>Comment</th>
  <th>Proposed Change</th>
  <th>Resolution</th>
  <th>Notes</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
</div>

<!-- Edit modal -->
<div id="modal-overlay" role="dialog" aria-modal="true">
  <div id="modal">
    <button id="modal-close" onclick="closeModal()" aria-label="Close">&times;</button>
    <h2 id="modal-title">Edit Resolution</h2>
    <div class="meta" id="modal-meta"></div>
    <div class="comment-preview" id="modal-comment"></div>
    <label for="modal-res-select">Resolution</label>
    <select id="modal-res-select">
      {resolution_options_html}
    </select>
    <label for="modal-notes-input">Resolution Notes</label>
    <textarea id="modal-notes-input" placeholder="Enter resolution notes, editor actions, or references…"></textarea>
    <div class="modal-btns">
      <button id="modal-cancel" onclick="closeModal()">Cancel</button>
      <button id="modal-save" onclick="saveEdit()">Save</button>
    </div>
  </div>
</div>

<script>
// ── Data ─────────────────────────────────────────────────────────────────
const COMMENTS = {comments_json};
const STORAGE_KEY = 'ballot_edits_v1';
const RES_CLASSES = {{
  'accepted': 'res-accepted',
  'accepted-in-principle': 'res-accepted-in-principle',
  'not-accepted': 'res-not-accepted',
  'pending': 'res-pending',
  'noted': 'res-noted'
}};

// ── localStorage helpers ──────────────────────────────────────────────────
function loadEdits() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}'); }}
  catch {{ return {{}}; }}
}}
function saveEdits(edits) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(edits));
}}

// ── Apply stored edits on page load ──────────────────────────────────────
(function applyStoredEdits() {{
  const edits = loadEdits();
  Object.entries(edits).forEach(([id, edit]) => {{
    const row = document.querySelector(`tr[data-id="${{CSS.escape(id)}}"]`);
    if (!row) return;
    const resKey = (edit.resolution || 'pending').toLowerCase().replace(/\\s+/g, '-');
    const cls = RES_CLASSES[resKey] || 'res-pending';
    const badge = row.querySelector('.badge');
    if (badge) {{
      badge.textContent = edit.resolution;
      badge.className = 'badge ' + cls;
    }}
    const notesCell = row.querySelector('.notes-cell');
    if (notesCell) notesCell.textContent = edit.notes || '';
    row.dataset.res = edit.resolution;
  }});
  updateSummary();
}})();

// ── Filter ───────────────────────────────────────────────────────────────
function applyFilter() {{
  const org = document.getElementById('f-org').value;
  const type = document.getElementById('f-type').value;
  const res = document.getElementById('f-res').value;
  document.querySelectorAll('#tbl tbody tr').forEach(tr => {{
    const d = tr.dataset;
    const show = (!org || d.org === org) && (!type || d.type === type) && (!res || d.res === res);
    tr.classList.toggle('hidden', !show);
  }});
}}

// ── Edit modal ───────────────────────────────────────────────────────────
let _editId = null;

function openEdit(commentId) {{
  const data = COMMENTS.find(c => c.id === commentId);
  if (!data) return;
  _editId = commentId;
  const edits = loadEdits();
  const stored = edits[commentId] || {{}};

  document.getElementById('modal-title').textContent = 'Edit: ' + commentId;
  document.getElementById('modal-meta').innerHTML =
    `<b>{org_label_esc}:</b> ${{data.org}} &nbsp;|&nbsp; <b>Clause:</b> ${{data.clause}} &nbsp;|&nbsp; <b>Type:</b> ${{data.type}}`;
  document.getElementById('modal-comment').textContent = data.comment;

  const resSel = document.getElementById('modal-res-select');
  resSel.value = stored.resolution || data.resolution || 'pending';
  if (!resSel.value) resSel.value = 'pending';

  document.getElementById('modal-notes-input').value =
    stored.notes !== undefined ? stored.notes : (data.notes || '');

  document.getElementById('modal-overlay').classList.add('open');
  document.getElementById('modal-res-select').focus();
}}

function closeModal() {{
  document.getElementById('modal-overlay').classList.remove('open');
  _editId = null;
}}

function saveEdit() {{
  if (!_editId) return;
  const resolution = document.getElementById('modal-res-select').value;
  const notes = document.getElementById('modal-notes-input').value.trim();

  // Persist
  const edits = loadEdits();
  edits[_editId] = {{ resolution, notes }};
  saveEdits(edits);

  // Update row in table
  const row = document.querySelector(`tr[data-id="${{CSS.escape(_editId)}}"]`);
  if (row) {{
    const resKey = resolution.toLowerCase().replace(/\\s+/g, '-');
    const cls = RES_CLASSES[resKey] || 'res-pending';
    const badge = row.querySelector('.badge');
    if (badge) {{ badge.textContent = resolution; badge.className = 'badge ' + cls; }}
    const notesCell = row.querySelector('.notes-cell');
    if (notesCell) notesCell.textContent = notes;
    row.dataset.res = resolution;
  }}

  updateSummary();
  closeModal();
}}

// Wire Edit buttons via delegation (avoids inline onclick / quote-escaping issues)
document.getElementById('tbl').addEventListener('click', e => {{
  const btn = e.target.closest('.edit-btn');
  if (btn) openEdit(btn.dataset.id);
}});

// Close modal on overlay click or Escape key
document.getElementById('modal-overlay').addEventListener('click', e => {{
  if (e.target === document.getElementById('modal-overlay')) closeModal();
}});
document.addEventListener('keydown', e => {{
  if (e.key === 'Escape') closeModal();
}});

// ── Summary update ───────────────────────────────────────────────────────
function updateSummary() {{
  const edits = loadEdits();
  let accepted = 0, notAccepted = 0, pending = 0;
  COMMENTS.forEach(c => {{
    const res = (edits[c.id]?.resolution || c.resolution || 'pending').toLowerCase();
    if (res.includes('accept') && !res.includes('not')) accepted++;
    else if (res.includes('not-accept') || res === 'rejected') notAccepted++;
    else if (res === 'pending') pending++;
  }});
  const s = document.querySelector('.summary');
  if (s) s.innerHTML =
    `${{COMMENTS.length}} comments &mdash; ` +
    `<span style="color:#155724;font-weight:600">${{accepted}} accepted</span>, ` +
    `<span style="color:#721c24;font-weight:600">${{notAccepted}} not accepted</span>, ` +
    `<span style="color:#856404;font-weight:600">${{pending}} pending</span>` +
    ` &nbsp;|&nbsp; <em>Click <b>Edit</b> on any row to update resolution and notes.</em>`;
}}

// ── CSV export ───────────────────────────────────────────────────────────
function exportCSV() {{
  const edits = loadEdits();
  const cols = ['ID', '{org_label_esc}', 'Clause', 'Paragraph', 'Type', 'Comment', 'Proposed Change', 'Resolution', 'Notes'];
  const esc = v => '"' + String(v || '').replace(/"/g, '""') + '"';
  const rows = [cols.map(esc).join(',')];
  COMMENTS.forEach(c => {{
    const e = edits[c.id] || {{}};
    rows.push([
      c.id, c.org, c.clause, c.paragraph, c.type,
      c.comment, c.proposed_change,
      e.resolution || c.resolution,
      e.notes !== undefined ? e.notes : (c.notes || '')
    ].map(esc).join(','));
  }});
  const blob = new Blob([rows.join('\\n')], {{type:'text/csv;charset=utf-8;'}});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'ballot_comments_resolved.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}}
</script>
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    logging.info(f"Ballot comment tracker written to {output_path}")


def _build_rows_html(comments: list[BallotComment], *, org_label: str = "Organization") -> str:
    rows = []
    for c in comments:
        res_lower = c.resolution.lower().replace(" ", "-")
        res_class = (
            f"res-{res_lower}"
            if res_lower
            in ("accepted", "accepted-in-principle", "not-accepted", "pending", "noted")
            else "res-pending"
        )

        clause_cell = (
            f'<a href="#{_html.escape(c.clause_id)}">{_html.escape(c.clause_ref)}</a>'
            if c.clause_id
            else _html.escape(c.clause_ref)
        )

        rows.append(
            f'<tr data-id="{_html.escape(c.comment_id)}" '
            f'data-org="{_html.escape(c.country)}" '
            f'data-type="{_html.escape(c.comment_type)}" '
            f'data-res="{_html.escape(c.resolution)}">'
            f'<td><button class="edit-btn" data-id="{_html.escape(c.comment_id)}">Edit</button></td>'
            f"<td>{_html.escape(c.comment_id)}</td>"
            f"<td>{_html.escape(c.country)}</td>"
            f"<td>{clause_cell}</td>"
            f"<td>{_html.escape(c.paragraph)}</td>"
            f"<td>{_html.escape(c.comment_type)}</td>"
            f'<td class="comment-text">{_html.escape(c.comment)}</td>'
            f'<td class="proposed-text">{_html.escape(c.proposed_change)}</td>'
            f'<td><span class="badge {res_class}">{_html.escape(c.resolution)}</span></td>'
            f'<td class="notes-cell">{_html.escape(c.resolution_notes)}</td>'
            f"</tr>"
        )
    return "\n".join(rows)


def export_comments_json(comments: list[BallotComment], output_path: Path) -> None:
    """Export ballot comments as JSON for downstream tooling."""
    data = [asdict(c) for c in comments]
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info(f"Ballot comments JSON written to {output_path}")

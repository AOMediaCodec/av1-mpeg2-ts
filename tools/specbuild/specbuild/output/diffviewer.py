"""Three-pane synchronized diff viewer with TOC sidebar.

Generates a standalone HTML page with four panes:

* **TOC sidebar** (left) — navigable table of contents with three modes:
  current spec, anchor (previous) spec, or changes-only.
* **Anchor pane** — the main-branch version of the specification.
* **Current pane** — the working-branch version.
* **Diff pane** — the ``htmldiff.pl`` output with ``<ins>``/``<del>`` markup.

Scrolling is synchronized across the three main panes.  Clicking a TOC
entry navigates all three panes to the corresponding section.
"""

from __future__ import annotations

import base64
import html as _html_mod
import logging
import re
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import extract_toc_html as _extract_toc_html


def _extract_changed_section_ids(diff_html: str) -> set[str]:
    """Scan diff HTML for sections that contain ``<ins>`` or ``<del>`` tags.

    Uses a single forward pass to collect heading positions, then maps
    each change to its nearest preceding heading via binary search.

    Args:
        diff_html: The full HTML of the diff output.

    Returns:
        Set of section anchor IDs that contain changes.
    """
    import bisect

    # Single pass: collect all heading positions and their IDs
    heading_positions: list[int] = []
    heading_ids: list[str] = []
    for m in re.finditer(r'<h[2-6][^>]*id="([^"]+)"', diff_html):
        heading_positions.append(m.start())
        heading_ids.append(m.group(1))

    if not heading_positions:
        return set()

    # Single pass: find all <ins>/<del> positions
    changed_ids: set[str] = set()
    for m in re.finditer(r"<(ins|del)[\s>]", diff_html):
        # Binary search for the nearest preceding heading
        idx = bisect.bisect_right(heading_positions, m.start()) - 1
        if idx >= 0:
            changed_ids.add(heading_ids[idx])

    return changed_ids


def _build_changes_only_toc(toc_html: str, changed_ids: set[str]) -> str:
    """Filter a TOC to show only entries whose sections contain changes.

    Args:
        toc_html: Full TOC HTML (inner content of the ``<nav>``).
        changed_ids: Set of section IDs that have diffs.

    Returns:
        Filtered TOC HTML with only changed-section entries.
    """
    if not changed_ids:
        return '<p style="padding: 1em; color: #666;">No differences found.</p>'

    # Extract individual <li> entries with their href targets
    filtered_items: list[str] = []
    for match in re.finditer(
        r'<li[^>]*>\s*<a[^>]*href="#([^"]+)"[^>]*>(.*?)</a>',
        toc_html,
        re.DOTALL,
    ):
        section_id = match.group(1)
        if section_id in changed_ids:
            # Strip any HTML tags from the link text and escape the result to
            # prevent XSS when the spec heading contains inline HTML (e.g. <code>).
            raw_text = match.group(2)
            plain_text = _html_mod.escape(re.sub(r"<[^>]+>", "", raw_text))
            safe_id = _html_mod.escape(section_id)
            filtered_items.append(
                f'<li><a href="#{safe_id}" class="toc-link">{plain_text}</a></li>'
            )

    if not filtered_items:
        return '<p style="padding: 1em; color: #666;">No differences found.</p>'

    return f'<ol class="toc changes-toc">{"".join(filtered_items)}</ol>'


# ---------------------------------------------------------------------------
# Viewer HTML generation
# ---------------------------------------------------------------------------

_VIEWER_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; font-family: FONT_SANS_PLACEHOLDER; }

/* ---- Top toolbar ---- */
.toolbar {
    display: flex; align-items: center; gap: 12px;
    padding: 6px 14px; background: #2d3748; color: #fff;
    font-size: 13px; height: 40px; flex-shrink: 0;
}
.toolbar .title { font-weight: 600; font-size: 14px; margin-right: 8px; }
.toolbar label { cursor: pointer; display: flex; align-items: center; gap: 4px; }
.toolbar input[type="checkbox"] { accent-color: #63b3ed; }
.toolbar .sep { width: 1px; height: 20px; background: #4a5568; }
.toolbar select {
    background: #4a5568; color: #fff; border: 1px solid #718096;
    border-radius: 4px; padding: 2px 6px; font-size: 12px;
}
.toolbar .sync-indicator {
    margin-left: auto; font-size: 11px; color: #a0aec0;
}

/* ---- Main layout ---- */
.container { display: flex; height: calc(100% - 40px); }

/* ---- TOC sidebar ---- */
.toc-sidebar {
    width: 280px; min-width: 200px; max-width: 400px;
    border-right: 2px solid #e2e8f0; overflow-y: auto;
    background: #f7fafc; flex-shrink: 0; font-size: 12px;
    resize: horizontal;
}
.toc-sidebar h3 {
    padding: 10px 14px 6px; font-size: 13px; color: #2d3748;
    border-bottom: 1px solid #e2e8f0; position: sticky; top: 0;
    background: #f7fafc; z-index: 1;
}
.toc-sidebar .toc { padding: 4px 0; list-style: none; }
.toc-sidebar .toc .toc { padding-left: 1.2em; }
.toc-sidebar .toc li { padding: 0; }
.toc-sidebar .toc a {
    display: block; padding: 3px 14px; color: #2d3748;
    text-decoration: none; border-left: 3px solid transparent;
    transition: all 0.15s;
}
.toc-sidebar .toc a:hover {
    background: #edf2f7; border-left-color: #4299e1;
}
.toc-sidebar .toc a.active {
    background: #ebf8ff; border-left-color: #3182ce;
    font-weight: 600; color: #2b6cb0;
}
.toc-sidebar .changes-toc a {
    border-left-color: #fc8181;
}
.toc-sidebar .changes-toc a:hover {
    border-left-color: #e53e3e;
}

/* ---- Panes ---- */
.panes {
    display: flex; flex: 1; overflow: hidden;
}
.pane {
    flex: 1; display: flex; flex-direction: column;
    border-right: 1px solid #e2e8f0; min-width: 0;
}
.pane:last-child { border-right: none; }
.pane.hidden { display: none; }
.pane-header {
    padding: 4px 10px; font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
    flex-shrink: 0; text-align: center;
}
.pane-header.anchor { background: #fed7d7; color: #9b2c2c; }
.pane-header.current { background: #c6f6d5; color: #276749; }
.pane-header.diff { background: #fefcbf; color: #975a16; }
.pane iframe {
    flex: 1; border: none; width: 100%;
}

/* ---- Resize handle ---- */
.resize-handle {
    width: 5px; cursor: col-resize; background: #e2e8f0;
    flex-shrink: 0; transition: background 0.2s;
}
.resize-handle:hover, .resize-handle.active { background: #a0aec0; }
"""

_VIEWER_JS = """\
(function() {
    'use strict';

    // --- State ---
    var panes = {
        anchor:  { el: document.getElementById('pane-anchor'),  iframe: document.getElementById('iframe-anchor')  },
        current: { el: document.getElementById('pane-current'), iframe: document.getElementById('iframe-current') },
        diff:    { el: document.getElementById('pane-diff'),    iframe: document.getElementById('iframe-diff')    },
    };
    var tocContainer = document.getElementById('toc-content');
    var tocModeSelect = document.getElementById('toc-mode');
    var syncIndicator = document.getElementById('sync-indicator');

    var syncEnabled = false;
    var isSyncing = false;
    var activeSection = null;

    // --- TOC mode switching ---
    var tocData = {
        current:  document.getElementById('toc-data-current').innerHTML,
        anchor:   document.getElementById('toc-data-anchor').innerHTML,
        changes:  document.getElementById('toc-data-changes').innerHTML,
    };

    function switchTocMode(mode) {
        tocContainer.innerHTML = tocData[mode] || tocData.current;
        bindTocLinks();
    }
    tocModeSelect.addEventListener('change', function() {
        switchTocMode(this.value);
    });

    // --- Pane visibility toggles ---
    document.querySelectorAll('.pane-toggle').forEach(function(cb) {
        cb.addEventListener('change', function() {
            var pane = panes[this.dataset.pane];
            if (pane) {
                pane.el.classList.toggle('hidden', !this.checked);
            }
        });
    });

    // --- Scroll sync via postMessage ---
    // Each iframe posts {type:"dv-scroll", pane, fraction, section}
    // Parent relays to other iframes via {type:"dv-set-scroll", pane, fraction}
    window.addEventListener('message', function(e) {
        var msg = e.data;
        if (!msg || msg.type !== 'dv-scroll') return;
        if (!syncEnabled || isSyncing) return;
        isSyncing = true;

        var sourceName = msg.pane;
        var fraction = msg.fraction;

        // Relay scroll to other visible panes
        Object.keys(panes).forEach(function(name) {
            if (name !== sourceName && !panes[name].el.classList.contains('hidden')) {
                panes[name].iframe.contentWindow.postMessage(
                    {type: 'dv-set-scroll', pane: name, fraction: fraction}, '*'
                );
            }
        });

        // Update active TOC entry
        if (msg.section && msg.section !== activeSection) {
            activeSection = msg.section;
            highlightTocEntry(msg.section);
        }

        setTimeout(function() { isSyncing = false; }, 50);
    });

    // --- TOC highlighting ---
    function highlightTocEntry(sectionId) {
        tocContainer.querySelectorAll('a.active').forEach(function(a) {
            a.classList.remove('active');
        });
        var link = tocContainer.querySelector('a[href=\"#' + CSS.escape(sectionId) + '\"]');
        if (link) {
            link.classList.add('active');
            link.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    // --- TOC click -> navigate all panes ---
    function bindTocLinks() {
        tocContainer.querySelectorAll('a[href^=\"#\"]').forEach(function(link) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                var targetId = this.getAttribute('href').substring(1);
                navigateAllPanes(targetId);
            });
        });
    }

    function navigateAllPanes(sectionId) {
        isSyncing = true;
        Object.keys(panes).forEach(function(name) {
            if (!panes[name].el.classList.contains('hidden')) {
                panes[name].iframe.contentWindow.postMessage(
                    {type: 'dv-navigate', pane: name, id: sectionId}, '*'
                );
            }
        });
        highlightTocEntry(sectionId);
        setTimeout(function() { isSyncing = false; }, 700);
    }

    // --- Sync toggle ---
    document.getElementById('sync-toggle').addEventListener('change', function() {
        syncEnabled = this.checked;
        syncIndicator.textContent = syncEnabled ? 'Scroll sync: ON' : 'Scroll sync: OFF';
    });

    // --- Initialize TOC ---
    switchTocMode('changes');
})();
"""


def _build_viewer_html(
    anchor_b64: str,
    current_b64: str,
    diff_b64: str,
    current_toc: str,
    anchor_toc: str,
    changes_toc: str,
) -> str:
    """Assemble the four-pane diff viewer as a standalone HTML page.

    The three spec documents are embedded as base64-encoded strings and
    loaded into iframes via Blob URLs at runtime.  This approach works
    reliably with both ``file://`` and ``http://`` protocols.

    Args:
        anchor_b64: Base64-encoded anchor HTML.
        current_b64: Base64-encoded current HTML.
        diff_b64: Base64-encoded diff HTML.
        current_toc: Extracted TOC HTML from the current spec.
        anchor_toc: Extracted TOC HTML from the anchor spec.
        changes_toc: Filtered TOC showing only changed sections.

    Returns:
        Complete HTML string for the viewer page.
    """
    css = _VIEWER_CSS.replace("FONT_SANS_PLACEHOLDER", THEME.font_sans)

    # Build the page without f-string to avoid issues with { } in JS/CSS
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diff Viewer — Specification Comparison</title>
<style>""")
    parts.append(css)
    parts.append("""</style>
</head>
<body>

<!-- Toolbar -->
<div class="toolbar">
    <span class="title">Diff Viewer</span>
    <span class="sep"></span>
    <label><input type="checkbox" class="pane-toggle" data-pane="anchor"> Anchor</label>
    <label><input type="checkbox" class="pane-toggle" data-pane="current"> Current</label>
    <label><input type="checkbox" class="pane-toggle" data-pane="diff" checked> Diff</label>
    <span class="sep"></span>
    <label>TOC:
        <select id="toc-mode">
            <option value="current">Current spec</option>
            <option value="anchor">Anchor spec</option>
            <option value="changes" selected>Changes only</option>
        </select>
    </label>
    <span class="sep"></span>
    <label><input type="checkbox" id="sync-toggle"> Sync scroll</label>
    <span class="sync-indicator" id="sync-indicator">Scroll sync: OFF</span>
</div>

<!-- Hidden TOC data stores -->
<div id="toc-data-current" style="display:none">""")
    parts.append(current_toc)
    parts.append('</div>\n<div id="toc-data-anchor" style="display:none">')
    parts.append(anchor_toc)
    parts.append('</div>\n<div id="toc-data-changes" style="display:none">')
    parts.append(changes_toc)
    parts.append('''</div>

<!-- Main layout -->
<div class="container">
    <!-- TOC sidebar -->
    <div class="toc-sidebar">
        <h3>Table of Contents</h3>
        <div id="toc-content"></div>
    </div>

    <!-- Three spec panes -->
    <div class="panes">
        <div class="pane hidden" id="pane-anchor">
            <div class="pane-header anchor">Anchor (Previous)</div>
            <iframe id="iframe-anchor"></iframe>
        </div>
        <div class="pane hidden" id="pane-current">
            <div class="pane-header current">Current</div>
            <iframe id="iframe-current"></iframe>
        </div>
        <div class="pane" id="pane-diff">
            <div class="pane-header diff">Diff</div>
            <iframe id="iframe-diff"></iframe>
        </div>
    </div>
</div>

<!-- Embedded spec data (base64) -->
<script>
var SPEC_DATA = {
    anchor:  "''')
    parts.append(anchor_b64)
    parts.append('",\n    current: "')
    parts.append(current_b64)
    parts.append('",\n    diff:    "')
    parts.append(diff_b64)
    parts.append(""""
};
</script>

<!-- Blob URL loader -->
<script>
(function() {
    function b64toBlob(b64) {
        var raw = atob(b64);
        var arr = new Uint8Array(raw.length);
        for (var i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
        return URL.createObjectURL(new Blob([arr], {type: 'text/html'}));
    }
    var ids = ['iframe-anchor', 'iframe-current', 'iframe-diff'];
    var keys = ['anchor', 'current', 'diff'];
    for (var i = 0; i < ids.length; i++) {
        document.getElementById(ids[i]).src = b64toBlob(SPEC_DATA[keys[i]]);
    }
})();
</script>

<!-- Main viewer logic -->
<script>
""")
    parts.append(_VIEWER_JS)
    parts.append("""
</script>
</body>
</html>""")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_diff_viewer(
    build_dir: Path,
    anchor_dir: Path | None = None,
) -> Path | None:
    """Generate the four-pane diff viewer HTML page.

    Reads the anchor, current, and diff HTML files, then assembles them
    into a single standalone viewer page with synchronized scrolling and
    a navigable TOC sidebar.

    Args:
        build_dir: Build output directory containing ``index.html`` and
            ``diff.html``.
        anchor_dir: Directory containing the anchor spec.  Defaults to
            ``CONFIG.main_branch_clone_dir``.

    Returns:
        Path to the generated viewer HTML, or ``None`` on failure.
    """
    if anchor_dir is None:
        anchor_dir = Path(CONFIG.main_branch_clone_dir)

    # Resolve file paths
    current_html_path = build_dir / "index.html"
    diff_html_path = build_dir / "diff.html"
    anchor_html_path = anchor_dir / "index.html"

    # Validate all required files exist
    missing = []
    for label, path in [
        ("Current", current_html_path),
        ("Diff", diff_html_path),
        ("Anchor", anchor_html_path),
    ]:
        if not path.exists():
            missing.append(f"{label}: {path}")
    if missing:
        logging.error("Cannot generate diff viewer — missing files:\n  " + "\n  ".join(missing))
        return None

    logging.info("Generating three-pane diff viewer...")

    # CSS to hide the spec's built-in TOC (our sidebar replaces it)
    hide_toc_css = (
        '<style>nav#toc, nav[data-fill-with="table-of-contents"], '
        "#toc { display: none !important; }</style>"
    )

    # Script injected into each iframe for cross-origin scroll sync via
    # postMessage (Blob URLs get isolated origins from file:// parents).
    _IFRAME_SCROLL_SCRIPT = """<script>
(function() {
    var PANE = "PANE_NAME_PLACEHOLDER";
    var syncing = false;
    window.addEventListener("scroll", function() {
        if (syncing) return;
        var doc = document.documentElement, body = document.body;
        var scrollTop = doc.scrollTop || body.scrollTop;
        var maxScroll = Math.max(doc.scrollHeight, body.scrollHeight) - (doc.clientHeight || body.clientHeight);
        var fraction = maxScroll > 0 ? scrollTop / maxScroll : 0;
        var currentId = null;
        var hh = document.querySelectorAll("h2[id], h3[id]");
        for (var i = 0; i < hh.length; i++) {
            if (hh[i].getBoundingClientRect().top <= 100) currentId = hh[i].id;
            else break;
        }
        parent.postMessage({type:"dv-scroll", pane:PANE, fraction:fraction, section:currentId}, "*");
    }, {passive:true});
    window.addEventListener("message", function(e) {
        var m = e.data;
        if (!m || !m.type) return;
        if (m.type === "dv-set-scroll" && m.pane === PANE) {
            syncing = true;
            var doc = document.documentElement, body = document.body;
            var maxScroll = Math.max(doc.scrollHeight, body.scrollHeight) - (doc.clientHeight || body.clientHeight);
            var t = Math.round(m.fraction * maxScroll);
            doc.scrollTop = t; body.scrollTop = t;
            setTimeout(function(){ syncing = false; }, 50);
        }
        if (m.type === "dv-navigate" && m.pane === PANE) {
            syncing = true;
            var el = document.getElementById(m.id);
            if (el) el.scrollIntoView({behavior:"smooth", block:"start"});
            setTimeout(function(){ syncing = false; }, 700);
        }
    });
})();
</script>"""

    # Read HTML content
    try:
        anchor_html = anchor_html_path.read_text(encoding="utf-8")
        current_html = current_html_path.read_text(encoding="utf-8")
        diff_html = diff_html_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError) as exc:
        logging.error(f"Failed to read HTML files for diff viewer: {exc}")
        return None

    def _patch_spec_html(html: str, pane_name: str) -> str:
        """Inject TOC-hiding CSS and scroll-sync script into spec HTML."""
        script = _IFRAME_SCROLL_SCRIPT.replace("PANE_NAME_PLACEHOLDER", pane_name)
        head_idx = html.lower().find("</head>")
        if head_idx >= 0:
            html = html[:head_idx] + hide_toc_css + html[head_idx:]
        body_idx = html.lower().find("</body>")
        if body_idx >= 0:
            html = html[:body_idx] + script + html[body_idx:]
        else:
            html += script
        return html

    anchor_html_patched = _patch_spec_html(anchor_html, "anchor")
    current_html_patched = _patch_spec_html(current_html, "current")
    diff_html_patched = _patch_spec_html(diff_html, "diff")

    # Extract TOCs from HTML content (before freeing originals)
    current_toc = _extract_toc_html(current_html)
    anchor_toc = _extract_toc_html(anchor_html)
    changed_ids = _extract_changed_section_ids(diff_html)
    changes_toc = _build_changes_only_toc(current_toc, changed_ids)

    # Free original strings — only patched versions are needed from here
    del anchor_html, current_html, diff_html

    # Base64-encode patched HTML for embedding as Blob URLs (works with file://)
    anchor_b64 = base64.b64encode(anchor_html_patched.encode("utf-8")).decode("ascii")
    current_b64 = base64.b64encode(current_html_patched.encode("utf-8")).decode("ascii")
    diff_b64 = base64.b64encode(diff_html_patched.encode("utf-8")).decode("ascii")

    # Free patched strings — base64 versions are all we need now
    del anchor_html_patched, current_html_patched, diff_html_patched

    viewer_html = _build_viewer_html(
        anchor_b64=anchor_b64,
        current_b64=current_b64,
        diff_b64=diff_b64,
        current_toc=current_toc,
        anchor_toc=anchor_toc,
        changes_toc=changes_toc,
    )

    output_path = build_dir / "diff_viewer.html"
    try:
        output_path.write_text(viewer_html, encoding="utf-8")
    except OSError as exc:
        logging.error(f"Failed to write diff viewer to {output_path}: {exc}")
        return None

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"Diff viewer written to {output_path} ({size_mb:.1f} MB)")
    return output_path

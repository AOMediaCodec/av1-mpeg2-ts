"""Interactive diff explorer: search, filter, and navigate specification diffs.

Extends the basic diff viewer with:

* **Full-text search** across all three panes (anchor, current, diff)
* **Change-type filtering** — show only insertions, deletions, or modifications
* **Per-section change statistics** — counts of ins/del/mod per heading
* **Keyboard navigation** — ``n``/``p`` to jump between changes, ``/`` to focus search
* **Change summary panel** — collapsible sidebar with change counts and navigation

The explorer is generated as a standalone HTML file that embeds the three
spec versions (anchor, current, diff) as base64 blobs, identical to the
diff viewer approach.
"""

from __future__ import annotations

import base64
import bisect
import logging
import re
from pathlib import Path

from specbuild.config import CONFIG
from specbuild.theme import THEME
from specbuild.utils import extract_toc_html as _extract_toc_html

# ---------------------------------------------------------------------------
# Change statistics extraction
# ---------------------------------------------------------------------------


def _extract_change_stats(diff_html: str) -> list[dict]:
    """Extract per-section change statistics from the diff HTML.

    Scans for ``<ins>`` and ``<del>`` elements and maps each to its nearest
    preceding section heading.

    Args:
        diff_html: Full diff HTML content.

    Returns:
        List of dicts with ``id``, ``title``, ``insertions``, ``deletions``.
    """
    # Collect heading positions
    heading_positions: list[int] = []
    heading_ids: list[str] = []
    heading_titles: list[str] = []
    for m in re.finditer(r'<h([2-6])[^>]*id="([^"]+)"[^>]*>(.*?)</h\1>', diff_html, re.DOTALL):
        heading_positions.append(m.start())
        heading_ids.append(m.group(2))
        # Strip HTML tags from title
        heading_titles.append(re.sub(r"<[^>]+>", "", m.group(3)).strip())

    if not heading_positions:
        return []

    # Initialize per-section counters
    stats: dict[str, dict] = {}
    for hid, htitle in zip(heading_ids, heading_titles):
        if hid not in stats:
            stats[hid] = {"id": hid, "title": htitle, "insertions": 0, "deletions": 0}

    # Count insertions
    for m in re.finditer(r"<ins[\s>]", diff_html):
        idx = bisect.bisect_right(heading_positions, m.start()) - 1
        if idx >= 0:
            stats[heading_ids[idx]]["insertions"] += 1

    # Count deletions
    for m in re.finditer(r"<del[\s>]", diff_html):
        idx = bisect.bisect_right(heading_positions, m.start()) - 1
        if idx >= 0:
            stats[heading_ids[idx]]["deletions"] += 1

    # Return only sections with changes, in document order
    ordered_ids = list(dict.fromkeys(heading_ids))  # preserve order, dedupe
    return [
        stats[hid]
        for hid in ordered_ids
        if stats[hid]["insertions"] > 0 or stats[hid]["deletions"] > 0
    ]


# ---------------------------------------------------------------------------
# Explorer CSS
# ---------------------------------------------------------------------------

_EXPLORER_CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; font-family: FONT_SANS_PLACEHOLDER; }

/* ---- Toolbar ---- */
.toolbar {
    display: flex; align-items: center; gap: 10px;
    padding: 5px 12px; background: #1a202c; color: #fff;
    font-size: 13px; height: 44px; flex-shrink: 0;
}
.toolbar .title { font-weight: 700; font-size: 14px; margin-right: 6px; }
.toolbar .sep { width: 1px; height: 22px; background: #4a5568; }
.toolbar label { cursor: pointer; display: flex; align-items: center; gap: 4px; }
.toolbar input[type="checkbox"] { accent-color: #63b3ed; }
.toolbar select, .toolbar button {
    background: #4a5568; color: #fff; border: 1px solid #718096;
    border-radius: 4px; padding: 3px 8px; font-size: 12px; cursor: pointer;
}
.toolbar button:hover { background: #718096; }
.toolbar .search-box {
    display: flex; align-items: center; gap: 4px;
    background: #2d3748; border: 1px solid #4a5568;
    border-radius: 4px; padding: 2px 8px;
}
.toolbar .search-box input {
    background: transparent; border: none; color: #fff;
    font-size: 12px; width: 180px; outline: none;
}
.toolbar .search-box input::placeholder { color: #a0aec0; }
.toolbar .search-count { font-size: 11px; color: #a0aec0; white-space: nowrap; }
.toolbar .kbd {
    display: inline-block; padding: 1px 5px; background: #4a5568;
    border-radius: 3px; font-size: 10px; color: #cbd5e0;
    font-family: monospace; margin-left: 2px;
}

/* ---- Main layout ---- */
.container { display: flex; height: calc(100% - 44px); }

/* ---- Change sidebar ---- */
.change-sidebar {
    width: 300px; min-width: 220px; max-width: 450px;
    border-right: 2px solid #e2e8f0; overflow-y: auto;
    background: #f7fafc; flex-shrink: 0; font-size: 12px;
    resize: horizontal;
}
.sidebar-tabs {
    display: flex; border-bottom: 1px solid #e2e8f0;
    position: sticky; top: 0; background: #f7fafc; z-index: 2;
}
.sidebar-tabs button {
    flex: 1; padding: 8px; background: transparent; border: none;
    font-size: 12px; font-weight: 600; color: #718096;
    cursor: pointer; border-bottom: 2px solid transparent;
}
.sidebar-tabs button.active {
    color: #2d3748; border-bottom-color: #4299e1;
}
.sidebar-tabs button:hover { color: #2d3748; }

.sidebar-panel { display: none; padding: 4px 0; }
.sidebar-panel.active { display: block; }

/* Change stats panel */
.change-item {
    display: flex; align-items: center; gap: 8px;
    padding: 5px 12px; cursor: pointer; border-left: 3px solid transparent;
    transition: all 0.15s;
}
.change-item:hover {
    background: #edf2f7; border-left-color: #4299e1;
}
.change-item.active {
    background: #ebf8ff; border-left-color: #3182ce;
}
.change-item .section-title {
    flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    color: #2d3748; font-size: 11.5px;
}
.change-item .badges { display: flex; gap: 4px; flex-shrink: 0; }
.badge {
    display: inline-block; padding: 1px 6px; border-radius: 10px;
    font-size: 10px; font-weight: 600;
}
.badge-ins { background: #c6f6d5; color: #276749; }
.badge-del { background: #fed7d7; color: #9b2c2c; }

/* TOC panel */
.toc-panel .toc { list-style: none; padding: 4px 0; }
.toc-panel .toc .toc { padding-left: 1.2em; }
.toc-panel .toc li { padding: 0; }
.toc-panel .toc a {
    display: block; padding: 3px 12px; color: #2d3748;
    text-decoration: none; border-left: 3px solid transparent;
    transition: all 0.15s; font-size: 11.5px;
}
.toc-panel .toc a:hover {
    background: #edf2f7; border-left-color: #4299e1;
}
.toc-panel .toc a.active {
    background: #ebf8ff; border-left-color: #3182ce;
    font-weight: 600;
}

/* Summary card */
.summary-card {
    display: flex; gap: 16px; padding: 10px 12px;
    background: #edf2f7; border-bottom: 1px solid #e2e8f0;
    font-size: 11px;
}
.summary-stat { text-align: center; }
.summary-stat .val { font-size: 18px; font-weight: 700; color: #2d3748; }
.summary-stat .lbl { color: #718096; text-transform: uppercase; letter-spacing: 0.3px; }
.summary-stat.ins .val { color: #276749; }
.summary-stat.del .val { color: #9b2c2c; }
.summary-stat.sec .val { color: #2b6cb0; }

/* ---- Panes ---- */
.panes { display: flex; flex: 1; overflow: hidden; }
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
.pane iframe { flex: 1; border: none; width: 100%; }

/* ---- Filter bar ---- */
.filter-bar {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 12px; background: #edf2f7;
    border-bottom: 1px solid #e2e8f0; font-size: 11px;
}
.filter-btn {
    padding: 3px 10px; border-radius: 12px; border: 1px solid #cbd5e0;
    background: white; cursor: pointer; font-size: 11px; color: #4a5568;
    transition: all 0.15s;
}
.filter-btn:hover { border-color: #a0aec0; }
.filter-btn.active { background: #4299e1; color: white; border-color: #4299e1; }
.filter-btn.active-ins { background: #48bb78; color: white; border-color: #48bb78; }
.filter-btn.active-del { background: #fc8181; color: white; border-color: #fc8181; }
"""

# ---------------------------------------------------------------------------
# Explorer JavaScript
# ---------------------------------------------------------------------------

_EXPLORER_JS = """\
(function() {
    'use strict';

    // --- State ---
    var panes = {
        anchor:  { el: document.getElementById('pane-anchor'),  iframe: document.getElementById('iframe-anchor')  },
        current: { el: document.getElementById('pane-current'), iframe: document.getElementById('iframe-current') },
        diff:    { el: document.getElementById('pane-diff'),    iframe: document.getElementById('iframe-diff')    },
    };

    var syncEnabled = true;
    var isSyncing = false;
    var activeSection = null;
    var searchQuery = '';
    var changeStats = JSON.parse(document.getElementById('change-stats-data').textContent);

    // --- Sidebar tabs ---
    var tabBtns = document.querySelectorAll('.sidebar-tabs button');
    var panels = document.querySelectorAll('.sidebar-panel');
    tabBtns.forEach(function(btn) {
        btn.addEventListener('click', function() {
            tabBtns.forEach(function(b) { b.classList.remove('active'); });
            panels.forEach(function(p) { p.classList.remove('active'); });
            btn.classList.add('active');
            document.getElementById('panel-' + btn.dataset.panel).classList.add('active');
        });
    });

    // --- Populate change stats ---
    var changeList = document.getElementById('change-list');
    var totalIns = 0, totalDel = 0;
    changeStats.forEach(function(s) {
        totalIns += s.insertions;
        totalDel += s.deletions;
        var item = document.createElement('div');
        item.className = 'change-item';
        item.dataset.sectionId = s.id;
        item.innerHTML =
            '<span class="section-title">' + escapeHtml(s.title) + '</span>' +
            '<span class="badges">' +
            (s.insertions ? '<span class="badge badge-ins">+' + s.insertions + '</span>' : '') +
            (s.deletions ? '<span class="badge badge-del">-' + s.deletions + '</span>' : '') +
            '</span>';
        item.addEventListener('click', function() {
            navigateAllPanes(s.id);
            highlightChangeItem(s.id);
        });
        changeList.appendChild(item);
    });

    // Update summary
    document.getElementById('stat-sections').textContent = changeStats.length;
    document.getElementById('stat-ins').textContent = totalIns;
    document.getElementById('stat-del').textContent = totalDel;

    function highlightChangeItem(sectionId) {
        changeList.querySelectorAll('.change-item.active').forEach(function(el) {
            el.classList.remove('active');
        });
        var item = changeList.querySelector('[data-section-id="' + CSS.escape(sectionId) + '"]');
        if (item) {
            item.classList.add('active');
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    // --- Pane visibility toggles ---
    document.querySelectorAll('.pane-toggle').forEach(function(cb) {
        cb.addEventListener('change', function() {
            var pane = panes[this.dataset.pane];
            if (pane) pane.el.classList.toggle('hidden', !this.checked);
        });
    });

    // --- Scroll sync via postMessage ---
    window.addEventListener('message', function(e) {
        var msg = e.data;
        if (!msg || msg.type !== 'dv-scroll') return;
        if (!syncEnabled || isSyncing) return;
        isSyncing = true;

        Object.keys(panes).forEach(function(name) {
            if (name !== msg.pane && !panes[name].el.classList.contains('hidden')) {
                panes[name].iframe.contentWindow.postMessage(
                    {type: 'dv-set-scroll', pane: name, fraction: msg.fraction}, '*'
                );
            }
        });

        if (msg.section && msg.section !== activeSection) {
            activeSection = msg.section;
            highlightTocEntry(msg.section);
            highlightChangeItem(msg.section);
        }

        setTimeout(function() { isSyncing = false; }, 50);
    });

    // --- TOC highlighting ---
    var tocContent = document.getElementById('toc-content');
    function highlightTocEntry(sectionId) {
        tocContent.querySelectorAll('a.active').forEach(function(a) {
            a.classList.remove('active');
        });
        var link = tocContent.querySelector('a[href="#' + CSS.escape(sectionId) + '"]');
        if (link) {
            link.classList.add('active');
            link.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }

    // --- TOC click navigation ---
    function bindTocLinks() {
        tocContent.querySelectorAll('a[href^="#"]').forEach(function(link) {
            link.addEventListener('click', function(e) {
                e.preventDefault();
                var targetId = this.getAttribute('href').substring(1);
                navigateAllPanes(targetId);
            });
        });
    }
    bindTocLinks();

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
        activeSection = sectionId;
        setTimeout(function() { isSyncing = false; }, 700);
    }

    // --- Sync toggle ---
    document.getElementById('sync-toggle').addEventListener('change', function() {
        syncEnabled = this.checked;
    });

    // --- Search ---
    var searchInput = document.getElementById('search-input');
    var searchCount = document.getElementById('search-count');
    var currentMatchIdx = -1;
    var matchCount = 0;

    searchInput.addEventListener('input', function() {
        searchQuery = this.value.trim();
        if (searchQuery.length < 2) {
            clearSearch();
            return;
        }
        triggerSearch(searchQuery);
    });

    function triggerSearch(query) {
        // Send search command to all visible iframes
        currentMatchIdx = -1;
        matchCount = 0;
        Object.keys(panes).forEach(function(name) {
            if (!panes[name].el.classList.contains('hidden')) {
                panes[name].iframe.contentWindow.postMessage(
                    {type: 'dv-search', query: query}, '*'
                );
            }
        });
    }

    function clearSearch() {
        searchCount.textContent = '';
        currentMatchIdx = -1;
        matchCount = 0;
        Object.keys(panes).forEach(function(name) {
            panes[name].iframe.contentWindow.postMessage(
                {type: 'dv-search-clear'}, '*'
            );
        });
    }

    // Receive match count from iframes
    window.addEventListener('message', function(e) {
        var msg = e.data;
        if (!msg) return;
        if (msg.type === 'dv-search-result') {
            matchCount = msg.count || 0;
            searchCount.textContent = matchCount > 0
                ? matchCount + ' match' + (matchCount !== 1 ? 'es' : '')
                : 'No matches';
        }
    });

    // Search navigation buttons
    document.getElementById('search-prev').addEventListener('click', function() {
        sendSearchNav('prev');
    });
    document.getElementById('search-next').addEventListener('click', function() {
        sendSearchNav('next');
    });

    function sendSearchNav(direction) {
        // Send to the diff pane primarily
        if (!panes.diff.el.classList.contains('hidden')) {
            panes.diff.iframe.contentWindow.postMessage(
                {type: 'dv-search-nav', direction: direction}, '*'
            );
        } else {
            // Fallback to first visible pane
            for (var name in panes) {
                if (!panes[name].el.classList.contains('hidden')) {
                    panes[name].iframe.contentWindow.postMessage(
                        {type: 'dv-search-nav', direction: direction}, '*'
                    );
                    break;
                }
            }
        }
    }

    // --- Change navigation (n/p keys) ---
    var changeIdx = -1;
    function navigateChanges(direction) {
        if (changeStats.length === 0) return;
        if (direction === 'next') {
            changeIdx = (changeIdx + 1) % changeStats.length;
        } else {
            changeIdx = changeIdx <= 0 ? changeStats.length - 1 : changeIdx - 1;
        }
        var sec = changeStats[changeIdx];
        navigateAllPanes(sec.id);
        highlightChangeItem(sec.id);
    }

    document.getElementById('nav-prev').addEventListener('click', function() { navigateChanges('prev'); });
    document.getElementById('nav-next').addEventListener('click', function() { navigateChanges('next'); });

    // --- Filter buttons ---
    var filterState = { ins: true, del: true };
    document.querySelectorAll('.filter-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var type = btn.dataset.filter;
            filterState[type] = !filterState[type];
            btn.classList.toggle('active-' + type, filterState[type]);
            btn.classList.toggle('active', filterState[type]);
            applyFilters();
        });
    });

    function applyFilters() {
        // Send filter state to diff iframe
        if (!panes.diff.el.classList.contains('hidden')) {
            panes.diff.iframe.contentWindow.postMessage(
                {type: 'dv-filter', showIns: filterState.ins, showDel: filterState.del}, '*'
            );
        }
        // Update sidebar visibility
        changeList.querySelectorAll('.change-item').forEach(function(item) {
            var sid = item.dataset.sectionId;
            var stat = changeStats.find(function(s) { return s.id === sid; });
            if (!stat) return;
            var visible = (filterState.ins && stat.insertions > 0) ||
                          (filterState.del && stat.deletions > 0);
            item.style.display = visible ? '' : 'none';
        });
    }

    // --- Keyboard shortcuts ---
    document.addEventListener('keydown', function(e) {
        // Ignore if typing in search
        if (e.target === searchInput) {
            if (e.key === 'Escape') { searchInput.blur(); clearSearch(); }
            if (e.key === 'Enter') { sendSearchNav(e.shiftKey ? 'prev' : 'next'); }
            return;
        }
        if (e.key === '/' || e.key === 'f' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            searchInput.focus();
        }
        if (e.key === 'n') navigateChanges('next');
        if (e.key === 'p') navigateChanges('prev');
    });

    function escapeHtml(text) {
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
})();
"""

# ---------------------------------------------------------------------------
# Iframe injection script (search + filter support)
# ---------------------------------------------------------------------------

_IFRAME_SCRIPT = """\
<script>
(function() {
    var PANE = "PANE_NAME_PLACEHOLDER";
    var syncing = false;
    var highlights = [];
    var currentHighlight = -1;

    // --- Scroll sync ---
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

        // --- Search ---
        if (m.type === "dv-search") {
            clearHighlights();
            var query = m.query;
            if (!query || query.length < 2) return;
            highlightMatches(query);
            parent.postMessage({type:"dv-search-result", pane:PANE, count:highlights.length}, "*");
        }

        if (m.type === "dv-search-clear") {
            clearHighlights();
        }

        if (m.type === "dv-search-nav") {
            if (highlights.length === 0) return;
            if (m.direction === "next") {
                currentHighlight = (currentHighlight + 1) % highlights.length;
            } else {
                currentHighlight = currentHighlight <= 0 ? highlights.length - 1 : currentHighlight - 1;
            }
            highlights.forEach(function(h, i) {
                h.style.background = i === currentHighlight ? "#ff6b00" : "#ffd700";
                h.style.color = i === currentHighlight ? "white" : "inherit";
            });
            highlights[currentHighlight].scrollIntoView({behavior:"smooth", block:"center"});
        }

        // --- Filter ---
        if (m.type === "dv-filter") {
            var insEls = document.querySelectorAll("ins");
            var delEls = document.querySelectorAll("del");
            insEls.forEach(function(el) {
                el.style.display = m.showIns ? "" : "none";
                el.style.visibility = m.showIns ? "" : "hidden";
            });
            delEls.forEach(function(el) {
                el.style.display = m.showDel ? "" : "none";
                el.style.visibility = m.showDel ? "" : "hidden";
            });
        }
    });

    function highlightMatches(query) {
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
        var textNodes = [];
        while (walker.nextNode()) textNodes.push(walker.currentNode);

        var lowerQuery = query.toLowerCase();
        textNodes.forEach(function(node) {
            var text = node.textContent;
            var lowerText = text.toLowerCase();
            var idx = lowerText.indexOf(lowerQuery);
            if (idx === -1) return;

            var parent = node.parentNode;
            if (!parent || parent.tagName === "SCRIPT" || parent.tagName === "STYLE") return;

            var frag = document.createDocumentFragment();
            var lastIdx = 0;
            while (idx !== -1) {
                if (idx > lastIdx) {
                    frag.appendChild(document.createTextNode(text.substring(lastIdx, idx)));
                }
                var mark = document.createElement("mark");
                mark.className = "dv-search-highlight";
                mark.style.background = "#ffd700";
                mark.style.padding = "1px 2px";
                mark.style.borderRadius = "2px";
                mark.textContent = text.substring(idx, idx + query.length);
                frag.appendChild(mark);
                highlights.push(mark);
                lastIdx = idx + query.length;
                idx = lowerText.indexOf(lowerQuery, lastIdx);
            }
            if (lastIdx < text.length) {
                frag.appendChild(document.createTextNode(text.substring(lastIdx)));
            }
            parent.replaceChild(frag, node);
        });
        currentHighlight = -1;
    }

    function clearHighlights() {
        highlights.forEach(function(mark) {
            var parent = mark.parentNode;
            if (parent) {
                parent.replaceChild(document.createTextNode(mark.textContent), mark);
                parent.normalize();
            }
        });
        highlights = [];
        currentHighlight = -1;
    }
})();
</script>"""


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _build_explorer_html(
    anchor_b64: str,
    current_b64: str,
    diff_b64: str,
    toc_html: str,
    change_stats: list[dict],
) -> str:
    """Assemble the interactive diff explorer as a standalone HTML page."""
    import json as _json

    css = _EXPLORER_CSS.replace("FONT_SANS_PLACEHOLDER", THEME.font_sans)
    stats_json = _json.dumps(change_stats)

    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Diff Explorer — Interactive Specification Comparison</title>
<style>""")
    parts.append(css)
    parts.append("""</style>
</head>
<body>

<!-- Toolbar -->
<div class="toolbar">
    <span class="title">Diff Explorer</span>
    <span class="sep"></span>
    <label><input type="checkbox" class="pane-toggle" data-pane="anchor" checked> Anchor</label>
    <label><input type="checkbox" class="pane-toggle" data-pane="current" checked> Current</label>
    <label><input type="checkbox" class="pane-toggle" data-pane="diff" checked> Diff</label>
    <span class="sep"></span>
    <div class="search-box">
        <input type="text" id="search-input" placeholder="Search... (press /)">
        <button id="search-prev" title="Previous match">&uarr;</button>
        <button id="search-next" title="Next match">&darr;</button>
        <span class="search-count" id="search-count"></span>
    </div>
    <span class="sep"></span>
    <button id="nav-prev" title="Previous change (p)">&larr; Prev</button>
    <button id="nav-next" title="Next change (n)">Next &rarr;</button>
    <span class="sep"></span>
    <label><input type="checkbox" id="sync-toggle" checked> Sync</label>
    <span class="kbd" title="/ = search, n/p = navigate changes">?</span>
</div>

<!-- Filter bar -->
<div class="filter-bar">
    <span style="color:#718096;font-weight:600">Filter:</span>
    <button class="filter-btn active active-ins" data-filter="ins">+ Insertions</button>
    <button class="filter-btn active active-del" data-filter="del">&minus; Deletions</button>
</div>

<!-- Change stats data -->
<script type="application/json" id="change-stats-data">""")
    parts.append(stats_json)
    parts.append("""</script>

<!-- Main layout -->
<div class="container">
    <!-- Change sidebar -->
    <div class="change-sidebar">
        <div class="summary-card">
            <div class="summary-stat sec"><div class="val" id="stat-sections">0</div><div class="lbl">Sections</div></div>
            <div class="summary-stat ins"><div class="val" id="stat-ins">0</div><div class="lbl">Insertions</div></div>
            <div class="summary-stat del"><div class="val" id="stat-del">0</div><div class="lbl">Deletions</div></div>
        </div>
        <div class="sidebar-tabs">
            <button class="active" data-panel="changes">Changes</button>
            <button data-panel="toc">TOC</button>
        </div>
        <div id="panel-changes" class="sidebar-panel active">
            <div id="change-list"></div>
        </div>
        <div id="panel-toc" class="sidebar-panel toc-panel">
            <div id="toc-content">""")
    parts.append(toc_html)
    parts.append('''</div>
        </div>
    </div>

    <!-- Three spec panes -->
    <div class="panes">
        <div class="pane" id="pane-anchor">
            <div class="pane-header anchor">Anchor (Previous)</div>
            <iframe id="iframe-anchor"></iframe>
        </div>
        <div class="pane" id="pane-current">
            <div class="pane-header current">Current</div>
            <iframe id="iframe-current"></iframe>
        </div>
        <div class="pane" id="pane-diff">
            <div class="pane-header diff">Diff</div>
            <iframe id="iframe-diff"></iframe>
        </div>
    </div>
</div>

<!-- Embedded spec data -->
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

<!-- Main explorer logic -->
<script>
""")
    parts.append(_EXPLORER_JS)
    parts.append("""
</script>
</body>
</html>""")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_diff_explorer(
    build_dir: Path,
    anchor_dir: Path | None = None,
) -> Path | None:
    """Generate the interactive diff explorer HTML page.

    Reads the anchor, current, and diff HTML files, extracts per-section
    change statistics, then assembles them into a standalone explorer page
    with search, filtering, and change navigation.

    Args:
        build_dir: Build output directory containing ``index.html`` and
            ``diff.html``.
        anchor_dir: Directory containing the anchor spec.  Defaults to
            ``CONFIG.main_branch_clone_dir``.

    Returns:
        Path to the generated explorer HTML, or ``None`` on failure.
    """
    if anchor_dir is None:
        anchor_dir = Path(CONFIG.main_branch_clone_dir)

    current_html_path = build_dir / "index.html"
    diff_html_path = build_dir / "diff.html"
    anchor_html_path = anchor_dir / "index.html"

    missing = []
    for label, path in [
        ("Current", current_html_path),
        ("Diff", diff_html_path),
        ("Anchor", anchor_html_path),
    ]:
        if not path.exists():
            missing.append(f"{label}: {path}")
    if missing:
        logging.error("Cannot generate diff explorer — missing files:\n  " + "\n  ".join(missing))
        return None

    logging.info("Generating interactive diff explorer...")

    # Hide spec's built-in TOC
    hide_toc_css = (
        '<style>nav#toc, nav[data-fill-with="table-of-contents"], '
        "#toc { display: none !important; }</style>"
    )

    # Read HTML content
    try:
        anchor_html = anchor_html_path.read_text(encoding="utf-8")
        current_html = current_html_path.read_text(encoding="utf-8")
        diff_html = diff_html_path.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError, OSError) as exc:
        logging.error(f"Could not read diff explorer input HTML: {exc}")
        return None

    # Extract change statistics before patching
    change_stats = _extract_change_stats(diff_html)
    toc_html = _extract_toc_html(current_html)

    logging.info(
        f"Diff explorer: {len(change_stats)} sections with changes, "
        f"{sum(s['insertions'] for s in change_stats)} insertions, "
        f"{sum(s['deletions'] for s in change_stats)} deletions"
    )

    def _patch_html(html: str, pane_name: str) -> str:
        """Inject TOC-hiding CSS and interactive script into spec HTML."""
        script = _IFRAME_SCRIPT.replace("PANE_NAME_PLACEHOLDER", pane_name)
        head_idx = html.lower().find("</head>")
        if head_idx >= 0:
            html = html[:head_idx] + hide_toc_css + html[head_idx:]
        body_idx = html.lower().find("</body>")
        if body_idx >= 0:
            html = html[:body_idx] + script + html[body_idx:]
        else:
            html += script
        return html

    anchor_patched = _patch_html(anchor_html, "anchor")
    current_patched = _patch_html(current_html, "current")
    diff_patched = _patch_html(diff_html, "diff")

    del anchor_html, current_html, diff_html

    anchor_b64 = base64.b64encode(anchor_patched.encode("utf-8")).decode("ascii")
    current_b64 = base64.b64encode(current_patched.encode("utf-8")).decode("ascii")
    diff_b64 = base64.b64encode(diff_patched.encode("utf-8")).decode("ascii")

    del anchor_patched, current_patched, diff_patched

    explorer_html = _build_explorer_html(
        anchor_b64=anchor_b64,
        current_b64=current_b64,
        diff_b64=diff_b64,
        toc_html=toc_html,
        change_stats=change_stats,
    )

    output_path = build_dir / "diff_explorer.html"
    output_path.write_text(explorer_html, encoding="utf-8")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logging.info(f"Diff explorer written to {output_path} ({size_mb:.1f} MB)")
    return output_path

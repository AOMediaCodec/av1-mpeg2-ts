"""Client-side search index generation for spec HTML output.

Generates a lightweight search index from the compiled HTML that enables
instant full-text search in the browser.  The index covers:

- Section headings (boosted weight)
- Prose text (paragraphs, list items)
- Definition terms (boosted weight)
- Table captions

The search UI is injected as a floating overlay with keyboard shortcut
(Ctrl+K / Cmd+K) support.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from specbuild.utils import HEADING_TAGS, get_bs4, inject_css, inject_js, read_html, write_html


def generate_search_index(html_path: Path) -> Path | None:
    """Generate a search index and inject search UI into the HTML.

    Args:
        html_path: Path to the compiled HTML file.

    Returns:
        Path to the generated search index JSON, or None on failure.
    """
    try:
        get_bs4()
    except ImportError:
        logging.warning("BeautifulSoup not available, skipping search index")
        return None

    soup = read_html(html_path)
    index = generate_search_index_soup(soup)

    # Inject search UI into the HTML (index is embedded inline in JS)
    inject_search_ui_soup(soup, index)
    write_html(html_path, soup)

    logging.info(f"Search index: {len(index)} entries injected into {html_path.name}")
    return html_path


def generate_search_index_soup(soup: object) -> list[dict]:
    """Build a search index from a pre-parsed soup object.

    Args:
        soup: BeautifulSoup document (read-only).

    Returns:
        List of index entry dicts with ``id``, ``title``, ``text``,
        ``type`` keys.
    """
    index: list[dict] = []
    seen_ids: set[str] = set()

    # Index sections by heading
    for heading in soup.find_all(list(HEADING_TAGS)):
        section_id = heading.get("id", "")
        if not section_id:
            # Try parent section
            parent = heading.find_parent(["section", "div"])
            if parent:
                section_id = parent.get("id", "")

        # Skip duplicate section IDs (can occur with certain document structures)
        if section_id and section_id in seen_ids:
            continue
        if section_id:
            seen_ids.add(section_id)

        title = heading.get_text(strip=True)
        if not title:
            continue

        # Determine heading level so we stop only at same-or-higher headings
        # (e.g. an h3 heading's content should not be cut off by a nested h4)
        heading_level = int(heading.name[1]) if heading.name[1:].isdigit() else 1

        # Collect text from the section until next same-level or higher heading
        text_parts: list[str] = []
        for sibling in heading.next_siblings:
            if hasattr(sibling, "name") and sibling.name in HEADING_TAGS:
                sibling_level = int(sibling.name[1]) if sibling.name[1:].isdigit() else 1
                if sibling_level <= heading_level:
                    break
            if hasattr(sibling, "get_text"):
                t = sibling.get_text(strip=True)
                if t:
                    text_parts.append(t)

        text = " ".join(text_parts)[:500]  # Cap text length per entry

        index.append(
            {
                "id": section_id,
                "title": title,
                "text": text,
                "type": "section",
            }
        )

    # Index definitions
    for dfn in soup.find_all("dfn"):
        dfn_id = dfn.get("id", "")
        term = dfn.get_text(strip=True)
        if not term:
            continue
        index.append(
            {
                "id": dfn_id,
                "title": term,
                "text": "",
                "type": "definition",
            }
        )

    return index


def inject_search_ui_soup(soup: object, index: list[dict]) -> None:
    """Inject the search overlay UI and JavaScript into the soup.

    Args:
        soup: BeautifulSoup document (modified in place).
        index: Search index data to embed.
    """
    search_css = """
/* Search overlay */
#spec-search-overlay {
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.5); z-index: 10000;
}
#spec-search-overlay.active { display: flex; justify-content: center; padding-top: 10vh; }
#spec-search-box {
    background: white; border-radius: 8px; box-shadow: 0 4px 24px rgba(0,0,0,0.3);
    width: 90%; max-width: 600px; max-height: 70vh; display: flex; flex-direction: column;
}
#spec-search-input {
    padding: 12px 16px; font-size: 16px; border: none; border-bottom: 1px solid #eee;
    border-radius: 8px 8px 0 0; outline: none; width: 100%; box-sizing: border-box;
}
#spec-search-results {
    overflow-y: auto; padding: 8px; flex: 1;
}
.spec-search-result {
    padding: 8px 12px; cursor: pointer; border-radius: 4px;
}
.spec-search-result:hover { background: #f0f0f0; }
.spec-search-result .title { font-weight: 600; }
.spec-search-result .snippet { font-size: 0.85em; color: #666; margin-top: 2px; }
.spec-search-result .type-badge {
    font-size: 0.75em; padding: 1px 6px; border-radius: 3px;
    background: #e8e8e8; color: #555; margin-left: 6px;
}
.spec-search-hint { padding: 12px; color: #999; text-align: center; font-size: 0.9em; }
"""

    search_js = (
        """
(function() {
    var INDEX = """
        + json.dumps(index, separators=(",", ":")).replace("</", "<\\/")
        + """;

    // Create overlay
    var overlay = document.createElement('div');
    overlay.id = 'spec-search-overlay';
    overlay.innerHTML = '<div id="spec-search-box">' +
        '<input id="spec-search-input" type="text" placeholder="Search specification... (Esc to close)">' +
        '<div id="spec-search-results"><div class="spec-search-hint">Type to search</div></div></div>';
    document.body.appendChild(overlay);

    var input = document.getElementById('spec-search-input');
    var results = document.getElementById('spec-search-results');

    function openSearch() {
        overlay.classList.add('active');
        input.value = '';
        results.innerHTML = '<div class="spec-search-hint">Type to search</div>';
        setTimeout(function() { input.focus(); }, 50);
    }

    function closeSearch() {
        overlay.classList.remove('active');
    }

    function search(query) {
        if (!query || query.length < 2) {
            results.innerHTML = '<div class="spec-search-hint">Type at least 2 characters</div>';
            return;
        }
        var q = query.toLowerCase();
        var matches = [];
        for (var i = 0; i < INDEX.length; i++) {
            var entry = INDEX[i];
            var titleMatch = entry.title.toLowerCase().indexOf(q) >= 0;
            var textMatch = entry.text.toLowerCase().indexOf(q) >= 0;
            if (titleMatch || textMatch) {
                var score = titleMatch ? 2 : 1;
                if (entry.type === 'definition') score += 1;
                matches.push({entry: entry, score: score});
            }
        }
        matches.sort(function(a, b) { return b.score - a.score; });
        if (matches.length === 0) {
            results.innerHTML = '<div class="spec-search-hint">No results found</div>';
            return;
        }
        var html = '';
        var limit = Math.min(matches.length, 20);
        for (var j = 0; j < limit; j++) {
            var e = matches[j].entry;
            var snippet = e.text ? e.text.substring(0, 120) + '...' : '';
            var badge = e.type === 'definition' ? '<span class="type-badge">dfn</span>' : '';
            html += '<div class="spec-search-result" data-id="' + escapeHtml(e.id) + '">' +
                '<div class="title">' + escapeHtml(e.title) + badge + '</div>' +
                (snippet ? '<div class="snippet">' + escapeHtml(snippet) + '</div>' : '') +
                '</div>';
        }
        if (matches.length > limit) {
            html += '<div class="spec-search-hint">' + (matches.length - limit) + ' more results...</div>';
        }
        results.innerHTML = html;
    }

    function escapeHtml(t) {
        var d = document.createElement('div');
        d.appendChild(document.createTextNode(t));
        return d.innerHTML;
    }

    // Event listeners
    document.addEventListener('keydown', function(e) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            openSearch();
        }
        if (e.key === 'Escape') closeSearch();
    });

    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeSearch();
    });

    input.addEventListener('input', function() { search(input.value); });

    results.addEventListener('click', function(e) {
        var item = e.target.closest('.spec-search-result');
        if (item && item.dataset.id) {
            closeSearch();
            var target = document.getElementById(item.dataset.id);
            if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
        }
    });
})();
"""
    )

    # Inject CSS and JS
    inject_css(soup, "spec-search-css", search_css)
    inject_js(soup, "spec-search-js", search_js)

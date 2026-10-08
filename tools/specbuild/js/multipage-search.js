/* Multipage Search — client-side full-text search across all section pages.
   Requires search-index.js to be loaded first (sets window.SEARCH_INDEX). */

(function () {
  "use strict";

  var DEBOUNCE_MS = 200;
  var MAX_RESULTS = 25;
  var SNIPPET_LEN = 120;

  var searchInput = null;
  var resultsContainer = null;
  var debounceTimer = null;

  /* ── Index access ──────────────────────────────────────────── */

  function getIndex() {
    return window.SEARCH_INDEX || [];
  }

  /* ── Tokenisation & scoring ────────────────────────────────── */

  function tokenize(text) {
    return text.toLowerCase().replace(/[^\w\s]/g, " ").split(/\s+/).filter(Boolean);
  }

  function scoreEntry(entry, queryTokens) {
    var score = 0;
    var titleLower = entry.title.toLowerCase();
    var textLower = (entry.text || "").toLowerCase();
    var matchedSnippet = "";

    for (var i = 0; i < queryTokens.length; i++) {
      var tok = queryTokens[i];

      // Title match (high weight)
      if (titleLower.indexOf(tok) !== -1) {
        score += 10;
        // Exact title start gets bonus
        if (titleLower.indexOf(tok) === 0) score += 5;
      }

      // Section number match
      if (entry.number && entry.number.toLowerCase().indexOf(tok) !== -1) {
        score += 8;
      }

      // Subsection title match
      if (entry.subsectionTitles) {
        var subLower = entry.subsectionTitles.toLowerCase();
        if (subLower.indexOf(tok) !== -1) score += 6;
      }

      // Body text match
      var textIdx = textLower.indexOf(tok);
      if (textIdx !== -1) {
        score += 3;
        // Extract snippet around first match
        if (!matchedSnippet) {
          var start = Math.max(0, textIdx - 40);
          var end = Math.min(textLower.length, textIdx + tok.length + SNIPPET_LEN - 40);
          matchedSnippet = entry.text.substring(start, end).trim();
          if (start > 0) matchedSnippet = "\u2026" + matchedSnippet;
          if (end < entry.text.length) matchedSnippet = matchedSnippet + "\u2026";
        }
      }
    }

    return { score: score, snippet: matchedSnippet };
  }

  function search(query) {
    if (!query || query.length < 2) return [];

    var tokens = tokenize(query);
    if (tokens.length === 0) return [];

    var index = getIndex();
    var results = [];

    for (var i = 0; i < index.length; i++) {
      var result = scoreEntry(index[i], tokens);
      if (result.score > 0) {
        results.push({
          entry: index[i],
          score: result.score,
          snippet: result.snippet
        });
      }
    }

    // Sort by score descending
    results.sort(function (a, b) { return b.score - a.score; });
    return results.slice(0, MAX_RESULTS);
  }

  /* ── Snippet highlighting ──────────────────────────────────── */

  function highlightSnippet(text, query) {
    if (!text || !query) return text || "";
    var tokens = tokenize(query);
    var escaped = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    for (var i = 0; i < tokens.length; i++) {
      var re = new RegExp("(" + tokens[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
      escaped = escaped.replace(re, "<mark>$1</mark>");
    }
    return escaped;
  }

  /* ── Render results ────────────────────────────────────────── */

  function renderResults(results, query) {
    if (!resultsContainer) return;

    if (results.length === 0) {
      if (query && query.length >= 2) {
        resultsContainer.innerHTML = '<div class="search-no-results">No results found</div>';
      } else {
        resultsContainer.innerHTML = "";
      }
      resultsContainer.style.display = query && query.length >= 2 ? "block" : "none";
      return;
    }

    var html = [];
    for (var i = 0; i < results.length; i++) {
      var r = results[i];
      var e = r.entry;
      var label = e.number ? e.number + " " + e.title : e.title;
      var highlightedLabel = highlightSnippet(label, query);
      var snippet = r.snippet ? highlightSnippet(r.snippet, query) : "";
      var href = (e.filename || "").replace(/"/g, '&quot;');

      html.push('<a class="search-result" href="' + href + '">');
      html.push('  <div class="search-result-title">' + highlightedLabel + '</div>');
      if (snippet) {
        html.push('  <div class="search-result-snippet">' + snippet + '</div>');
      }
      html.push("</a>");
    }

    resultsContainer.innerHTML = html.join("\n");
    resultsContainer.style.display = "block";
  }

  /* ── Event handlers ────────────────────────────────────────── */

  function onInput() {
    clearTimeout(debounceTimer);
    var query = searchInput.value.trim();
    debounceTimer = setTimeout(function () {
      var results = search(query);
      renderResults(results, query);
    }, DEBOUNCE_MS);
  }

  function clearSearch() {
    if (searchInput) searchInput.value = "";
    if (resultsContainer) {
      resultsContainer.innerHTML = "";
      resultsContainer.style.display = "none";
    }
  }

  function onKeydown(e) {
    // Escape closes results
    if (e.key === "Escape" && resultsContainer && resultsContainer.style.display === "block") {
      clearSearch();
      searchInput.blur();
      e.preventDefault();
      return;
    }

    // Arrow key navigation in results
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!resultsContainer || resultsContainer.style.display !== "block") return;
      var items = resultsContainer.querySelectorAll(".search-result");
      if (items.length === 0) return;

      var focused = resultsContainer.querySelector(".search-result-focused");
      var idx = -1;
      if (focused) {
        for (var i = 0; i < items.length; i++) {
          if (items[i] === focused) { idx = i; break; }
        }
        focused.classList.remove("search-result-focused");
      }

      if (e.key === "ArrowDown") {
        idx = (idx + 1) % items.length;
      } else {
        idx = idx <= 0 ? items.length - 1 : idx - 1;
      }

      items[idx].classList.add("search-result-focused");
      items[idx].scrollIntoView({ block: "nearest" });
      e.preventDefault();
    }

    // Enter navigates to focused result
    if (e.key === "Enter") {
      var focused = resultsContainer && resultsContainer.querySelector(".search-result-focused");
      if (focused) {
        window.location.href = focused.getAttribute("href");
        e.preventDefault();
      }
    }
  }

  /* ── Global keyboard shortcut ──────────────────────────────── */

  function onGlobalKeydown(e) {
    // Skip if user is typing in an input/textarea
    var tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || e.target.isContentEditable) return;

    // "/" to focus search (vim-style)
    if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
      if (searchInput) {
        searchInput.focus();
        e.preventDefault();
      }
      return;
    }

    // Ctrl+K / Cmd+K to focus search
    if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
      if (searchInput) {
        searchInput.focus();
        e.preventDefault();
      }
    }
  }

  /* ── Click outside to close ────────────────────────────────── */

  function onDocumentClick(e) {
    if (!resultsContainer || resultsContainer.style.display !== "block") return;
    var searchBox = document.getElementById("multipage-search");
    if (searchBox && !searchBox.contains(e.target)) {
      resultsContainer.style.display = "none";
    }
  }

  /* ── Build search UI ───────────────────────────────────────── */

  function createSearchUI() {
    var sidebar = document.getElementById("multipage-sidebar");
    if (!sidebar) return;

    // Create search container
    var searchBox = document.createElement("div");
    searchBox.id = "multipage-search";
    searchBox.className = "multipage-search";

    // Input
    searchInput = document.createElement("input");
    searchInput.type = "search";
    searchInput.id = "multipage-search-input";
    searchInput.className = "search-input";
    searchInput.placeholder = "Search... (/ or Ctrl+K)";
    searchInput.setAttribute("aria-label", "Search specification");
    searchInput.autocomplete = "off";

    // Clear button
    var clearBtn = document.createElement("button");
    clearBtn.className = "search-clear-btn";
    clearBtn.textContent = "\u00d7";
    clearBtn.title = "Clear search";
    clearBtn.setAttribute("aria-label", "Clear search");
    clearBtn.addEventListener("click", function () {
      clearSearch();
      searchInput.focus();
    });

    // Results container
    resultsContainer = document.createElement("div");
    resultsContainer.id = "multipage-search-results";
    resultsContainer.className = "search-results";
    resultsContainer.style.display = "none";

    searchBox.appendChild(searchInput);
    searchBox.appendChild(clearBtn);
    searchBox.appendChild(resultsContainer);

    // Insert before the TOC header
    var tocHeader = sidebar.querySelector(".multipage-toc-header");
    if (tocHeader) {
      sidebar.insertBefore(searchBox, tocHeader);
    } else {
      sidebar.insertBefore(searchBox, sidebar.firstChild);
    }

    // Bind events
    searchInput.addEventListener("input", onInput);
    searchInput.addEventListener("keydown", onKeydown);
    // Re-show results when focusing back into the input
    searchInput.addEventListener("focus", function () {
      if (searchInput.value.trim().length >= 2 && resultsContainer.innerHTML) {
        resultsContainer.style.display = "block";
      }
    });
  }

  /* ── Init ───────────────────────────────────────────────────── */

  function init() {
    createSearchUI();
    document.addEventListener("keydown", onGlobalKeydown);
    document.addEventListener("click", onDocumentClick);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

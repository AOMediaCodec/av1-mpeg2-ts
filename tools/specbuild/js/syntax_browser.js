/**
 * Syntax Browser - Interactive Features
 *
 * Simplified version for standalone syntax browser.
 * Provides:
 * 1. Resizable split pane
 * 2. One-way scroll sync (syntax → semantics)
 * 3. Element-level click navigation (bidirectional)
 * 4. Search functionality
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        scrollSyncEnabled: true,
        scrollSyncDelay: 100,
        highlightDuration: 2000,
        searchDebounceDelay: 200,
        maxSearchResults: 50
    };

    // Quick navigation targets (important structures)
    const QUICK_NAV = {
        'o': 'obu_header_syntax',              // OBU Header
        's': 'sequence_header_obu_syntax',     // Sequence Header
        'f': 'frame_header_obu_syntax',        // Frame Header
        't': 'tile_group_obu_syntax',          // Tile Group
        'm': 'metadata_obu_syntax',            // Metadata
        'c': 'color_config_syntax',            // Color Config
        'q': 'quantization_params_syntax',     // Quantization
        'l': 'loop_filter_params_syntax',      // Loop Filter
        'p': 'frame_size_syntax'               // Picture/Frame Size
    };

    // State
    let state = {
        isResizing: false,
        isSyncing: false,
        searchIndex: null,
        searchTimeout: null,
        awaitingSecondKey: false,
        firstKey: null
    };

    // DOM elements
    let elements = {};

    /**
     * Initialize the syntax browser
     */
    function init() {
        console.log('Initializing syntax browser...');

        // Get DOM elements
        elements.container = document.querySelector('.sidebyside-container');
        elements.leftPane = document.getElementById('syntax-pane');
        elements.rightPane = document.getElementById('semantics-pane');
        elements.divider = document.getElementById('divider');
        elements.leftContent = document.getElementById('syntax-content');
        elements.rightContent = document.getElementById('semantics-content');
        elements.searchOverlay = document.getElementById('search-overlay');
        elements.searchInput = document.getElementById('search-input');
        elements.searchResults = document.getElementById('search-results');
        elements.searchTrigger = document.getElementById('search-trigger');
        elements.searchClose = document.getElementById('search-close');
        elements.specHeader = document.getElementById('spec-header');
        elements.headerTab = document.getElementById('header-tab');
        elements.headerClose = document.getElementById('header-close');
        elements.searchTriggerTab = document.getElementById('search-trigger-tab');
        elements.breadcrumbSyntax = document.getElementById('breadcrumb-syntax');
        elements.breadcrumbSemantics = document.getElementById('breadcrumb-semantics');

        if (!elements.container || !elements.leftPane || !elements.rightPane) {
            console.error('Required elements not found');
            return;
        }

        // Initialize features
        initResizableDivider();
        // initScrollSync();  // Auto-scroll disabled
        initElementLevelNavigation();
        initSearch();
        initHeaderCollapse();
        initHashNavigation();
        initKeyboardShortcuts();
        initBreadcrumbs();
        initCopyButtons();

        console.log('Syntax browser initialized successfully');
    }

    /**
     * Initialize resizable divider
     */
    function initResizableDivider() {
        elements.divider.addEventListener('mousedown', startResize);
        elements.divider.addEventListener('touchstart', startResize);
        document.addEventListener('mousemove', resize);
        document.addEventListener('touchmove', resize);
        document.addEventListener('mouseup', stopResize);
        document.addEventListener('touchend', stopResize);
    }

    function startResize(e) {
        e.preventDefault();
        state.isResizing = true;
        document.body.style.userSelect = 'none';
        // Check if we're in vertical or horizontal layout
        const isVertical = window.innerWidth <= 1200;
        document.body.style.cursor = isVertical ? 'row-resize' : 'col-resize';
    }

    function resize(e) {
        if (!state.isResizing) return;
        e.preventDefault();

        const containerRect = elements.container.getBoundingClientRect();
        const isVertical = window.innerWidth <= 1200;

        // Get mouse/touch position
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;

        if (isVertical) {
            // Vertical layout (mobile) - resize top/bottom
            const mouseY = clientY;
            const offsetY = mouseY - containerRect.top;
            const topHeight = (offsetY / containerRect.height) * 100;
            const bottomHeight = 100 - topHeight;

            if (topHeight < 20 || bottomHeight < 20) return;

            elements.leftPane.style.flex = `0 0 ${topHeight}%`;
            elements.rightPane.style.flex = `0 0 ${bottomHeight}%`;
        } else {
            // Horizontal layout (desktop) - resize left/right
            const mouseX = clientX;
            const offsetX = mouseX - containerRect.left;
            const leftWidth = (offsetX / containerRect.width) * 100;
            const rightWidth = 100 - leftWidth;

            if (leftWidth < 20 || rightWidth < 20) return;

            elements.leftPane.style.flex = `0 0 ${leftWidth}%`;
            elements.rightPane.style.flex = `0 0 ${rightWidth}%`;
        }
    }

    function stopResize() {
        if (!state.isResizing) return;
        state.isResizing = false;
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
    }

    /**
     * Initialize one-way scroll sync (syntax → semantics only)
     */
    function initScrollSync() {
        if (!CONFIG.scrollSyncEnabled) return;

        let scrollTimeout = null;

        elements.leftContent.addEventListener('scroll', function() {
            if (state.isSyncing) return;

            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                syncScroll();
            }, CONFIG.scrollSyncDelay);
        });
    }

    /**
     * Sync scroll from syntax to semantics based on section position
     */
    function syncScroll() {
        const scrollTop = elements.leftContent.scrollTop;
        const height = elements.leftContent.clientHeight;
        const midpoint = scrollTop + height / 2;

        // Find which h3/h4 section we're in
        const headings = elements.leftContent.querySelectorAll('h3[id$="_syntax"], h4[id$="_syntax"]');
        let activeHeading = null;

        for (const heading of headings) {
            const headingTop = heading.offsetTop;
            const headingBottom = headingTop + heading.offsetHeight;

            if (midpoint >= headingTop) {
                activeHeading = heading;
            } else {
                break;
            }
        }

        if (!activeHeading) return;

        // Find corresponding semantics heading
        const syntaxId = activeHeading.id;
        const semanticsId = syntaxId.replace('_syntax', '_semantics');
        const semanticsHeading = elements.rightContent.querySelector(`#${semanticsId}`);

        if (semanticsHeading) {
            state.isSyncing = true;

            const targetScrollTop = semanticsHeading.offsetTop - 100;
            elements.rightContent.scrollTo({
                top: Math.max(0, targetScrollTop),
                behavior: 'smooth'
            });

            setTimeout(() => {
                state.isSyncing = false;
            }, 500);
        }
    }

    /**
     * Initialize element-level click navigation (bidirectional)
     */
    function initElementLevelNavigation() {
        console.log('Initializing element-level navigation...');

        // Syntax → Semantics navigation
        const varCells = elements.leftContent.querySelectorAll('.sdl-var-with-descriptor');
        console.log(`Found ${varCells.length} syntax variable cells`);

        let clickableCount = 0;

        varCells.forEach(cell => {
            const span = cell.querySelector('span');
            if (!span) return;

            const varName = span.textContent.trim();
            if (!varName || varName.length === 0) return;

            // Make it clickable
            span.setAttribute('data-var-name', varName);
            span.classList.add('clickable-var');
            clickableCount++;

            span.addEventListener('click', function(e) {
                e.stopPropagation();
                console.log(`Clicked on syntax variable: "${varName}"`);
                findAndHighlightInSemantics(varName, this);
            });
        });

        console.log(`Made ${clickableCount} syntax variables clickable`);

        // Semantics → Syntax navigation
        const semanticsStrong = elements.rightContent.querySelectorAll('strong, b');
        console.log(`Found ${semanticsStrong.length} semantics bold elements`);

        let semanticsClickableCount = 0;

        semanticsStrong.forEach(strong => {
            const varName = strong.textContent.trim();
            if (!varName || varName.length === 0) return;

            // Make it clickable
            strong.setAttribute('data-var-name', varName);
            strong.classList.add('clickable-var');
            strong.style.cursor = 'pointer';
            semanticsClickableCount++;

            strong.addEventListener('click', function(e) {
                e.stopPropagation();
                console.log(`Clicked on semantics variable: "${varName}"`);
                findAndHighlightInSyntax(varName, this);
            });
        });

        console.log(`Made ${semanticsClickableCount} semantics variables clickable`);
    }

    /**
     * Normalize variable name by replacing specific indices with generic ones
     * e.g., "seq_level_idx[ 0 ]" -> "seq_level_idx[ i ]"
     * e.g., "lcr_rep_info_present_flag[ isGlobal ][ xId ]" -> "lcr_rep_info_present_flag[ i ][ j ]"
     */
    function normalizeVarName(varName) {
        // Replace all array indices (numeric or named) with generic i, j, k, etc.
        // Match: [ anything ] and replace sequentially with [ i ], [ j ], [ k ]
        const genericIndices = ['i', 'j', 'k', 'l', 'm', 'n'];
        let indexCount = 0;

        return varName.replace(/\[\s*[^\]]+\s*\]/g, function() {
            const replacement = `[ ${genericIndices[indexCount] || 'i'} ]`;
            indexCount++;
            return replacement;
        });
    }

    /**
     * Check if two variable names match (exact or normalized)
     */
    function variableNamesMatch(name1, name2) {
        // Try exact match first
        if (name1 === name2) return true;

        // Try normalized match (with generic indices like [ i ][ j ])
        const normalized1 = normalizeVarName(name1);
        const normalized2 = normalizeVarName(name2);
        if (normalized1 === normalized2) return true;

        // Try base name match (strip all array indices)
        // e.g., "var[ x ][ y ]" matches "var"
        const baseName1 = name1.replace(/\[\s*[^\]]+\s*\]/g, '').trim();
        const baseName2 = name2.replace(/\[\s*[^\]]+\s*\]/g, '').trim();
        return baseName1 === baseName2;
    }

    /**
     * Find and highlight a variable in semantics
     */
    function findAndHighlightInSemantics(varName, clickedElement) {
        console.log(`Searching for "${varName}" in semantics...`);

        // Find the current section (h3 or h4) we're in
        let currentSection = clickedElement;
        while (currentSection && !currentSection.matches('h3[id$="_syntax"], h4[id$="_syntax"]')) {
            currentSection = currentSection.previousElementSibling;
        }

        if (!currentSection) {
            console.log('Could not find current section');
            // Search globally
            searchGlobally(varName);
            return;
        }

        const syntaxId = currentSection.id;
        const semanticsId = syntaxId.replace('_syntax', '_semantics');
        console.log(`Looking in semantics section: ${semanticsId}`);

        const semanticsSection = elements.rightContent.querySelector(`#${semanticsId}`);
        if (!semanticsSection) {
            console.log(`Semantics section not found: ${semanticsId}`);
            searchGlobally(varName);
            return;
        }

        // Search within this section and subsequent content until next section
        let searchArea = [];
        let current = semanticsSection.nextElementSibling;

        while (current && !current.matches('h3, h4')) {
            searchArea.push(current);
            current = current.nextElementSibling;
        }

        console.log(`Searching in ${searchArea.length} elements`);

        // Look for the variable in <strong> or <b> tags
        let found = false;
        for (const elem of searchArea) {
            const strongTags = elem.querySelectorAll('strong, b');

            for (const strong of strongTags) {
                const strongText = strong.textContent.trim();
                if (variableNamesMatch(strongText, varName)) {
                    highlightElement(strong, varName);
                    scrollToElement(strong);
                    found = true;
                    console.log(`Found match: "${varName}" -> "${strongText}"`);
                    break;
                }
            }

            if (found) break;
        }

        if (!found) {
            console.log(`"${varName}" not found in semantics section, searching globally...`);
            searchGlobally(varName);
        }
    }

    /**
     * Search for variable globally in all semantics
     */
    function searchGlobally(varName) {
        const allStrong = elements.rightContent.querySelectorAll('strong, b');

        for (const strong of allStrong) {
            const strongText = strong.textContent.trim();
            if (variableNamesMatch(strongText, varName)) {
                highlightElement(strong, varName);
                scrollToElement(strong);
                console.log(`Found "${varName}" -> "${strongText}" globally`);
                return;
            }
        }

        console.log(`"${varName}" not found anywhere in semantics`);
        showNotFoundMessage(varName);
    }

    /**
     * Find and highlight a variable in syntax (reverse direction)
     */
    function findAndHighlightInSyntax(varName, clickedElement) {
        console.log(`Searching for "${varName}" in syntax...`);

        // Find the current section (h3 or h4) we're in
        let currentSection = clickedElement;
        while (currentSection && !currentSection.matches('h3[id$="_semantics"], h4[id$="_semantics"]')) {
            currentSection = currentSection.previousElementSibling;
        }

        if (!currentSection) {
            console.log('Could not find current semantics section');
            searchGloballyInSyntax(varName);
            return;
        }

        const semanticsId = currentSection.id;
        const syntaxId = semanticsId.replace('_semantics', '_syntax');
        console.log(`Looking in syntax section: ${syntaxId}`);

        const syntaxSection = elements.leftContent.querySelector(`#${syntaxId}`);
        if (!syntaxSection) {
            console.log(`Syntax section not found: ${syntaxId}`);
            searchGloballyInSyntax(varName);
            return;
        }

        // Search within this section and subsequent content until next section
        let searchArea = [];
        let current = syntaxSection.nextElementSibling;

        while (current && !current.matches('h3, h4')) {
            searchArea.push(current);
            current = current.nextElementSibling;
        }

        console.log(`Searching in ${searchArea.length} syntax elements`);

        // Look for the variable in syntax table cells
        let found = false;
        for (const elem of searchArea) {
            const varCells = elem.querySelectorAll('.sdl-var-with-descriptor span');

            for (const span of varCells) {
                const spanText = span.textContent.trim();
                if (variableNamesMatch(spanText, varName)) {
                    highlightSyntaxElement(span, varName);
                    scrollToSyntaxElement(span);
                    found = true;
                    console.log(`Found match in syntax: "${varName}" -> "${spanText}"`);
                    break;
                }
            }

            if (found) break;
        }

        if (!found) {
            console.log(`"${varName}" not found in syntax section, searching globally...`);
            searchGloballyInSyntax(varName);
        }
    }

    /**
     * Search for variable globally in all syntax
     */
    function searchGloballyInSyntax(varName) {
        const allVarSpans = elements.leftContent.querySelectorAll('.sdl-var-with-descriptor span');

        for (const span of allVarSpans) {
            const spanText = span.textContent.trim();
            if (variableNamesMatch(spanText, varName)) {
                highlightSyntaxElement(span, varName);
                scrollToSyntaxElement(span);
                console.log(`Found "${varName}" -> "${spanText}" globally in syntax`);
                return;
            }
        }

        console.log(`"${varName}" not found anywhere in syntax`);
        showNotFoundMessage(varName, 'syntax');
    }

    /**
     * Highlight a syntax element
     */
    function highlightSyntaxElement(element, varName) {
        // Remove any existing highlights in syntax pane
        const existing = elements.leftContent.querySelectorAll('.element-highlighted');
        existing.forEach(el => el.classList.remove('element-highlighted'));

        // Add highlight
        element.classList.add('element-highlighted');

        setTimeout(() => {
            element.classList.remove('element-highlighted');
        }, CONFIG.highlightDuration);

        console.log(`Highlighted in syntax: "${varName}"`);
    }

    /**
     * Scroll to element in syntax pane
     */
    function scrollToSyntaxElement(element) {
        const elementRect = element.getBoundingClientRect();
        const containerRect = elements.leftContent.getBoundingClientRect();

        const currentScrollTop = elements.leftContent.scrollTop;
        const elementTopRelativeToViewport = elementRect.top;
        const containerTopRelativeToViewport = containerRect.top;

        const targetScrollTop = currentScrollTop + (elementTopRelativeToViewport - containerTopRelativeToViewport) - 100;

        elements.leftContent.scrollTo({
            top: Math.max(0, targetScrollTop),
            behavior: 'smooth'
        });
    }

    /**
     * Highlight an element
     */
    function highlightElement(element, varName) {
        // Remove any existing highlights
        const existing = elements.rightContent.querySelectorAll('.element-highlighted');
        existing.forEach(el => el.classList.remove('element-highlighted'));

        // Add highlight
        element.classList.add('element-highlighted');

        setTimeout(() => {
            element.classList.remove('element-highlighted');
        }, CONFIG.highlightDuration);

        console.log(`Highlighted: "${varName}"`);
    }

    /**
     * Scroll to element in semantics pane
     */
    function scrollToElement(element) {
        // Get the element's position relative to the viewport
        const elementRect = element.getBoundingClientRect();
        const containerRect = elements.rightContent.getBoundingClientRect();

        // Calculate the element's position within the scrollable container
        const currentScrollTop = elements.rightContent.scrollTop;
        const elementTopRelativeToViewport = elementRect.top;
        const containerTopRelativeToViewport = containerRect.top;

        // Calculate where we need to scroll to
        const targetScrollTop = currentScrollTop + (elementTopRelativeToViewport - containerTopRelativeToViewport) - 100;

        elements.rightContent.scrollTo({
            top: Math.max(0, targetScrollTop),
            behavior: 'smooth'
        });
    }

    /**
     * Show "not found" message
     */
    function showNotFoundMessage(varName, pane = 'semantics') {
        // Create temporary message
        const message = document.createElement('div');
        message.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 20px 30px;
            border-radius: 8px;
            font-size: 16px;
            z-index: 10000;
        `;
        message.textContent = `"${varName}" not found in ${pane}`;

        document.body.appendChild(message);

        setTimeout(() => {
            message.remove();
        }, 2000);
    }

    /**
     * Initialize search functionality
     */
    function initSearch() {
        console.log('Initializing search...');

        // Build search index
        buildSearchIndex();

        // Keyboard shortcuts
        document.addEventListener('keydown', function(e) {
            // Cmd/Ctrl+K or / to open search
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                openSearch();
            } else if (e.key === '/' && !isInputFocused()) {
                e.preventDefault();
                openSearch();
            } else if (e.key === 'Escape' && elements.searchOverlay.classList.contains('active')) {
                closeSearch();
            }
        });

        // Click handlers
        elements.searchTrigger.addEventListener('click', openSearch);
        elements.searchTriggerTab.addEventListener('click', openSearch);
        elements.searchClose.addEventListener('click', closeSearch);
        elements.searchOverlay.addEventListener('click', function(e) {
            if (e.target === elements.searchOverlay) {
                closeSearch();
            }
        });

        // Search input
        elements.searchInput.addEventListener('input', function() {
            clearTimeout(state.searchTimeout);
            state.searchTimeout = setTimeout(() => {
                performSearch(elements.searchInput.value.trim());
            }, CONFIG.searchDebounceDelay);
        });

        console.log('Search initialized');
    }

    /**
     * Build search index from syntax and semantics content
     */
    function buildSearchIndex() {
        console.log('Building search index...');
        state.searchIndex = [];

        // Index syntax section headings (h3 and h4)
        const syntaxHeadings = elements.leftContent.querySelectorAll('h3[id$="_syntax"], h4[id$="_syntax"]');
        syntaxHeadings.forEach(heading => {
            const headingText = heading.textContent.trim();
            if (!headingText) return;

            // Extract the base ID without the "_syntax" suffix for searching
            const headingId = heading.id.replace('_syntax', '');

            state.searchIndex.push({
                name: headingText,
                normalized: headingText.toLowerCase(),
                searchableId: headingId.replace(/_/g, ' ').toLowerCase(), // Convert underscores to spaces for matching
                pane: 'syntax',
                type: 'heading',
                element: heading,
                section: headingText,
                id: heading.id
            });
        });

        // Index semantics section headings (h3 and h4)
        const semanticsHeadings = elements.rightContent.querySelectorAll('h3[id$="_semantics"], h4[id$="_semantics"]');
        semanticsHeadings.forEach(heading => {
            const headingText = heading.textContent.trim();
            if (!headingText) return;

            // Extract the base ID without the "_semantics" suffix for searching
            const headingId = heading.id.replace('_semantics', '');

            state.searchIndex.push({
                name: headingText,
                normalized: headingText.toLowerCase(),
                searchableId: headingId.replace(/_/g, ' ').toLowerCase(), // Convert underscores to spaces for matching
                pane: 'semantics',
                type: 'heading',
                element: heading,
                section: headingText,
                id: heading.id
            });
        });

        // Index syntax variables
        const syntaxVars = elements.leftContent.querySelectorAll('.sdl-var-with-descriptor span');
        syntaxVars.forEach(span => {
            const varName = span.textContent.trim();
            if (!varName) return;

            // Find section
            let section = findSection(span, '_syntax');

            state.searchIndex.push({
                name: varName,
                normalized: normalizeVarName(varName),
                pane: 'syntax',
                type: 'variable',
                element: span,
                section: section
            });
        });

        // Index semantics variables
        const semanticsVars = elements.rightContent.querySelectorAll('strong, b');
        semanticsVars.forEach(strong => {
            const varName = strong.textContent.trim();
            if (!varName) return;

            // Find section
            let section = findSection(strong, '_semantics');

            state.searchIndex.push({
                name: varName,
                normalized: normalizeVarName(varName),
                pane: 'semantics',
                type: 'variable',
                element: strong,
                section: section
            });
        });

        console.log(`Search index built: ${state.searchIndex.length} items`);
    }

    /**
     * Find section heading for an element
     */
    function findSection(element, suffix) {
        let current = element;
        while (current && current !== elements.leftContent && current !== elements.rightContent) {
            if (current.matches && current.matches(`h3[id$="${suffix}"], h4[id$="${suffix}"]`)) {
                return current.textContent.trim();
            }
            current = current.previousElementSibling || current.parentElement;
        }
        return 'Unknown';
    }

    /**
     * Check if an input element is focused
     */
    function isInputFocused() {
        const activeElement = document.activeElement;
        return activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
    }

    /**
     * Open search overlay
     */
    function openSearch() {
        elements.searchOverlay.classList.add('active');
        elements.searchInput.value = '';
        elements.searchInput.focus();
        showSearchInfo();
    }

    /**
     * Close search overlay
     */
    function closeSearch() {
        elements.searchOverlay.classList.remove('active');
        elements.searchResults.innerHTML = '';
    }

    /**
     * Show initial search info
     */
    function showSearchInfo() {
        elements.searchResults.innerHTML = `
            <div class="search-info">
                Start typing to search for syntax structures, variables, and more...
            </div>
        `;
    }

    /**
     * Perform search
     */
    function performSearch(query) {
        if (!query || query.length < 2) {
            showSearchInfo();
            return;
        }

        console.log(`Searching for: "${query}"`);

        const normalizedQuery = normalizeVarName(query.toLowerCase());
        const results = [];

        // Search through index
        for (const item of state.searchIndex) {
            let score = 0;

            // Try exact match first (higher score for headings)
            if (item.name.toLowerCase().includes(query.toLowerCase())) {
                score = item.type === 'heading' ? 3 : 2;
                results.push({ item, score });
            }
            // For headings, also check the searchableId (e.g., "obu_header" matches "obu header syntax")
            else if (item.type === 'heading' && item.searchableId && item.searchableId.includes(query.toLowerCase().replace(/_/g, ' '))) {
                score = 3;
                results.push({ item, score });
            }
            // Try normalized match
            else if (item.normalized.toLowerCase().includes(normalizedQuery)) {
                score = item.type === 'heading' ? 2 : 1;
                results.push({ item, score });
            }

            // Limit results
            if (results.length >= CONFIG.maxSearchResults) break;
        }

        displayResults(results, query);
    }

    /**
     * Display search results
     */
    function displayResults(results, query) {
        if (results.length === 0) {
            elements.searchResults.innerHTML = `
                <div class="search-no-results">
                    <div class="search-no-results-title">No results found</div>
                    <div class="search-no-results-text">Try a different search term or check spelling</div>
                </div>
            `;
            return;
        }

        // Sort by score (exact matches first)
        results.sort((a, b) => b.score - a.score);

        const resultsHTML = results.map(({ item }) => {
            // Determine badge text and class based on type
            let badgeClass, badgeText;
            if (item.type === 'heading') {
                badgeClass = 'section';
                badgeText = 'Section';
            } else {
                badgeClass = item.pane === 'syntax' ? 'syntax' : 'semantics';
                badgeText = item.pane === 'syntax' ? 'Syntax' : 'Semantics';
            }

            // For headings, don't show section info (they ARE the section)
            const sectionInfo = item.type === 'heading'
                ? `<span class="result-section">${item.pane === 'syntax' ? 'Syntax' : 'Semantics'} Structure</span>`
                : `<span class="result-section">${escapeHtml(item.section)}</span>`;

            return `
                <div class="search-result-item" data-pane="${item.pane}" data-var="${item.name}" data-type="${item.type || 'variable'}" data-id="${item.id || ''}">
                    <div class="result-variable">${escapeHtml(item.name)}</div>
                    <div class="result-meta">
                        <span class="result-badge ${badgeClass}">${badgeText}</span>
                        ${sectionInfo}
                    </div>
                </div>
            `;
        }).join('');

        elements.searchResults.innerHTML = resultsHTML;

        // Add click handlers
        elements.searchResults.querySelectorAll('.search-result-item').forEach((item, index) => {
            item.addEventListener('click', () => {
                const pane = item.dataset.pane;
                const varName = item.dataset.var;
                const itemType = item.dataset.type;
                const itemId = item.dataset.id;
                const resultItem = results[index].item;

                closeSearch();

                // Handle headings differently - navigate to them
                if (itemType === 'heading' && itemId) {
                    history.pushState(null, null, `#${itemId}`);
                    navigateToHash(itemId);
                } else {
                    // Highlight and scroll to the element (variables)
                    if (pane === 'syntax') {
                        highlightSyntaxElement(resultItem.element, varName);
                        scrollToSyntaxElement(resultItem.element);
                    } else {
                        highlightElement(resultItem.element, varName);
                        scrollToElement(resultItem.element);
                    }
                }
            });
        });
    }

    /**
     * Escape HTML for safe display
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Initialize header collapse functionality
     */
    function initHeaderCollapse() {
        console.log('Initializing header collapse...');
        console.log('Header close button:', elements.headerClose);
        console.log('Header tab:', elements.headerTab);
        console.log('Spec header:', elements.specHeader);

        if (!elements.headerClose || !elements.headerTab || !elements.specHeader) {
            console.error('Missing header collapse elements!');
            return;
        }

        // Close button collapses header
        elements.headerClose.addEventListener('click', function(e) {
            console.log('Close button clicked!');
            e.preventDefault();
            e.stopPropagation();
            collapseHeader();
        });

        // Tab expands header (but not if clicking search button on tab)
        elements.headerTab.addEventListener('click', function(e) {
            console.log('Tab clicked!');
            e.preventDefault();
            // Don't expand if clicking the search button
            if (!e.target.closest('.search-trigger')) {
                expandHeader();
            }
        });

        console.log('Header collapse initialized successfully');
    }

    /**
     * Collapse header - show tab
     */
    function collapseHeader() {
        console.log('collapseHeader() called');
        console.log('Before - header classes:', elements.specHeader.className);
        console.log('Before - tab classes:', elements.headerTab.className);
        console.log('Before - body classes:', document.body.className);

        elements.specHeader.classList.add('collapsed');
        elements.headerTab.classList.add('visible');
        document.body.classList.add('header-collapsed');

        console.log('After - header classes:', elements.specHeader.className);
        console.log('After - tab classes:', elements.headerTab.className);
        console.log('After - body classes:', document.body.className);
        console.log('Header collapsed');
    }

    /**
     * Expand header - hide tab
     */
    function expandHeader() {
        console.log('expandHeader() called');
        elements.specHeader.classList.remove('collapsed');
        elements.headerTab.classList.remove('visible');
        document.body.classList.remove('header-collapsed');
        console.log('Header expanded');
    }

    /**
     * Initialize keyboard shortcuts
     */
    function initKeyboardShortcuts() {
        console.log('Initializing keyboard shortcuts...');

        document.addEventListener('keydown', function(e) {
            // Don't intercept if user is typing in an input
            if (isInputFocused()) return;

            // Don't intercept if search is open (already handles / and Esc)
            if (elements.searchOverlay.classList.contains('active')) return;

            const key = e.key.toLowerCase();

            // Handle 'g' prefix for "go to" actions (Gmail style)
            if (key === 'g' && !state.awaitingSecondKey) {
                e.preventDefault();
                state.awaitingSecondKey = true;
                state.firstKey = 'g';
                showKeyHint('g');

                // Reset after 2 seconds if no second key
                setTimeout(() => {
                    if (state.awaitingSecondKey && state.firstKey === 'g') {
                        state.awaitingSecondKey = false;
                        state.firstKey = null;
                        hideKeyHint();
                    }
                }, 2000);
                return;
            }

            // Handle second key after 'g'
            if (state.awaitingSecondKey && state.firstKey === 'g') {
                e.preventDefault();
                state.awaitingSecondKey = false;
                state.firstKey = null;
                hideKeyHint();

                // Check if it's a valid quick nav target
                if (QUICK_NAV[key]) {
                    navigateToHash(QUICK_NAV[key]);
                    console.log(`Quick nav: g+${key} -> ${QUICK_NAV[key]}`);
                } else if (key === 'g') {
                    // 'g' + 'g' = go to top
                    elements.leftContent.scrollTo({ top: 0, behavior: 'smooth' });
                    elements.rightContent.scrollTo({ top: 0, behavior: 'smooth' });
                } else if (key === 't') {
                    // 'g' + 't' is already used for tile_group, but we could add 'g' + 'shift+t' for "top"
                    // For now, just ignore unrecognized keys
                }
                return;
            }

            // Other single-key shortcuts
            switch(key) {
                case '?':
                    e.preventDefault();
                    showHelp();
                    break;
                case 'h':
                    if (!e.ctrlKey && !e.metaKey) {
                        e.preventDefault();
                        toggleHeader();
                    }
                    break;
                case 't':
                    if (!e.ctrlKey && !e.metaKey) {
                        e.preventDefault();
                        showTreeView();
                    }
                    break;
                case 'escape':
                    // Clear highlights
                    document.querySelectorAll('.element-highlighted, .section-highlighted').forEach(el => {
                        el.classList.remove('element-highlighted', 'section-highlighted');
                    });
                    break;
            }
        });

        console.log('Keyboard shortcuts initialized');
    }

    /**
     * Show key hint when waiting for second key
     */
    function showKeyHint(key) {
        let hint = document.getElementById('key-hint');
        if (!hint) {
            hint = document.createElement('div');
            hint.id = 'key-hint';
            hint.style.cssText = `
                position: fixed;
                bottom: 50px;
                left: 50%;
                transform: translateX(-50%);
                background: rgba(0, 0, 0, 0.85);
                color: white;
                padding: 12px 20px;
                border-radius: 6px;
                font-size: 14px;
                font-weight: 500;
                z-index: 10000;
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
            `;
            document.body.appendChild(hint);
        }
        hint.textContent = `Press: ${key} + ...`;
        hint.style.display = 'block';
    }

    /**
     * Hide key hint
     */
    function hideKeyHint() {
        const hint = document.getElementById('key-hint');
        if (hint) {
            hint.style.display = 'none';
        }
    }

    /**
     * Toggle header collapse
     */
    function toggleHeader() {
        if (elements.specHeader.classList.contains('collapsed')) {
            expandHeader();
        } else {
            collapseHeader();
        }
    }

    /**
     * Show keyboard shortcuts help
     */
    function showHelp() {
        // Create help overlay
        let helpOverlay = document.getElementById('help-overlay');
        if (!helpOverlay) {
            helpOverlay = document.createElement('div');
            helpOverlay.id = 'help-overlay';
            helpOverlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10000;
                display: flex;
                align-items: center;
                justify-content: center;
                backdrop-filter: blur(3px);
            `;

            const helpContent = document.createElement('div');
            helpContent.style.cssText = `
                background: white;
                border-radius: 12px;
                padding: 30px;
                max-width: 600px;
                max-height: 80vh;
                overflow-y: auto;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            `;

            helpContent.innerHTML = `
                <h2 style="margin-top: 0; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">Keyboard Shortcuts</h2>

                <h3 style="color: #2c3e50; margin-top: 20px;">Quick Navigation (press 'g' then...)</h3>
                <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>o</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">OBU Header</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>s</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Sequence Header</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>f</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Frame Header</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>t</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Tile Group</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>m</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Metadata OBU</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>c</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Color Config</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>q</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Quantization Params</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>l</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Loop Filter</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>p</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Frame Size</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>g</kbd> + <kbd>g</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Go to top</td></tr>
                </table>

                <h3 style="color: #2c3e50; margin-top: 20px;">Search & Features</h3>
                <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>/</kbd> or <kbd>⌘K</kbd> / <kbd>Ctrl+K</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Open search</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>Esc</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Clear highlights</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>h</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Toggle header</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>t</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Show syntax tree overview</td></tr>
                    <tr><td style="padding: 8px; border-bottom: 1px solid #eee;"><kbd>?</kbd></td><td style="padding: 8px; border-bottom: 1px solid #eee;">Show this help</td></tr>
                </table>

                <p style="text-align: center; margin-top: 20px;">
                    <button id="help-close-btn" style="background: #3498db; color: white; border: none; padding: 10px 30px; border-radius: 6px; font-size: 14px; cursor: pointer; font-weight: 500;">Close</button>
                </p>
            `;

            helpOverlay.appendChild(helpContent);
            document.body.appendChild(helpOverlay);

            // Close on click outside or button
            helpOverlay.addEventListener('click', function(e) {
                if (e.target === helpOverlay) {
                    helpOverlay.remove();
                }
            });

            document.getElementById('help-close-btn').addEventListener('click', function() {
                helpOverlay.remove();
            });

            // Close on Escape
            const escapeHandler = function(e) {
                if (e.key === 'Escape') {
                    helpOverlay.remove();
                    document.removeEventListener('keydown', escapeHandler);
                }
            };
            document.addEventListener('keydown', escapeHandler);
        } else {
            helpOverlay.style.display = 'flex';
        }
    }

    /**
     * Show syntax tree overview
     */
    function showTreeView() {
        // Create tree overlay
        let treeOverlay = document.getElementById('tree-overlay');
        if (!treeOverlay) {
            treeOverlay = document.createElement('div');
            treeOverlay.id = 'tree-overlay';
            treeOverlay.style.cssText = `
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0, 0, 0, 0.7);
                z-index: 10000;
                display: flex;
                align-items: center;
                justify-content: center;
                backdrop-filter: blur(3px);
            `;

            const treeContent = document.createElement('div');
            treeContent.style.cssText = `
                background: white;
                border-radius: 12px;
                padding: 30px;
                max-width: 700px;
                max-height: 80vh;
                overflow-y: auto;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
                width: 90%;
            `;

            // Build tree structure
            const h2Sections = elements.leftContent.querySelectorAll('h2');
            let treeHTML = `
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                    <h2 style="margin: 0; color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; flex: 1;">Syntax Structure Overview</h2>
                    <button id="tree-close-btn" style="background: transparent; border: none; font-size: 24px; color: #666; cursor: pointer; padding: 0 10px; margin-left: 10px;">×</button>
                </div>
            `;

            // Get all h3 and h4 headings from syntax pane
            const headings = elements.leftContent.querySelectorAll('h3[id$="_syntax"], h4[id$="_syntax"]');

            let currentH3 = null;
            const tree = [];

            headings.forEach(heading => {
                const isH3 = heading.tagName === 'H3';
                const text = heading.textContent.trim();
                const id = heading.id;

                if (isH3) {
                    currentH3 = { text, id, children: [] };
                    tree.push(currentH3);
                } else if (currentH3) {
                    currentH3.children.push({ text, id });
                }
            });

            // Render tree
            treeHTML += '<div style="font-size: 14px; line-height: 1.6;">';
            tree.forEach(h3 => {
                treeHTML += `
                    <div style="margin-bottom: 15px;">
                        <div class="tree-item tree-h3" data-id="${h3.id}" style="
                            cursor: pointer;
                            padding: 8px 12px;
                            background: #f8f9fa;
                            border-left: 3px solid #3498db;
                            border-radius: 4px;
                            font-weight: 600;
                            color: #2c3e50;
                            transition: background 0.2s ease;
                        ">${h3.text}</div>
                `;

                if (h3.children.length > 0) {
                    treeHTML += '<div style="margin-left: 20px; margin-top: 5px;">';
                    h3.children.forEach(h4 => {
                        treeHTML += `
                            <div class="tree-item tree-h4" data-id="${h4.id}" style="
                                cursor: pointer;
                                padding: 6px 10px;
                                background: white;
                                border-left: 2px solid #95a5a6;
                                border-radius: 3px;
                                margin-bottom: 3px;
                                color: #555;
                                transition: background 0.2s ease;
                            ">${h4.text}</div>
                        `;
                    });
                    treeHTML += '</div>';
                }

                treeHTML += '</div>';
            });
            treeHTML += '</div>';

            treeContent.innerHTML = treeHTML;
            treeOverlay.appendChild(treeContent);
            document.body.appendChild(treeOverlay);

            // Add hover effects via JS
            const treeItems = treeContent.querySelectorAll('.tree-item');
            treeItems.forEach(item => {
                item.addEventListener('mouseenter', function() {
                    this.style.background = '#e3f2fd';
                });
                item.addEventListener('mouseleave', function() {
                    if (this.classList.contains('tree-h3')) {
                        this.style.background = '#f8f9fa';
                    } else {
                        this.style.background = 'white';
                    }
                });
                item.addEventListener('click', function() {
                    const id = this.dataset.id;
                    treeOverlay.remove();
                    // Update URL hash
                    history.pushState(null, null, `#${id}`);
                    navigateToHash(id);
                });
            });

            // Close on click outside or button
            treeOverlay.addEventListener('click', function(e) {
                if (e.target === treeOverlay) {
                    treeOverlay.remove();
                }
            });

            document.getElementById('tree-close-btn').addEventListener('click', function() {
                treeOverlay.remove();
            });

            // Close on Escape
            const escapeHandler = function(e) {
                if (e.key === 'Escape') {
                    treeOverlay.remove();
                    document.removeEventListener('keydown', escapeHandler);
                }
            };
            document.addEventListener('keydown', escapeHandler);
        } else {
            treeOverlay.style.display = 'flex';
        }
    }

    /**
     * Initialize breadcrumb navigation
     */
    function initBreadcrumbs() {
        console.log('Initializing breadcrumbs...');

        // Update breadcrumbs on scroll
        elements.leftContent.addEventListener('scroll', function() {
            updateBreadcrumb('syntax');
        });

        elements.rightContent.addEventListener('scroll', function() {
            updateBreadcrumb('semantics');
        });

        // Initial update
        updateBreadcrumb('syntax');
        updateBreadcrumb('semantics');

        console.log('Breadcrumbs initialized');
    }

    /**
     * Update breadcrumb for a pane
     */
    function updateBreadcrumb(pane) {
        const content = pane === 'syntax' ? elements.leftContent : elements.rightContent;
        const breadcrumb = pane === 'syntax' ? elements.breadcrumbSyntax : elements.breadcrumbSemantics;
        const suffix = pane === 'syntax' ? '_syntax' : '_semantics';

        // Find current section based on scroll position
        const scrollTop = content.scrollTop;
        const height = content.clientHeight;
        const midpoint = scrollTop + height / 3; // Use top third for better UX

        const headings = content.querySelectorAll(`h3[id$="${suffix}"], h4[id$="${suffix}"]`);
        let currentH3 = null;
        let currentH4 = null;

        for (const heading of headings) {
            const headingTop = heading.offsetTop;

            if (midpoint >= headingTop) {
                if (heading.tagName === 'H3') {
                    currentH3 = heading;
                    currentH4 = null; // Reset h4 when we enter a new h3
                } else if (heading.tagName === 'H4') {
                    currentH4 = heading;
                }
            } else {
                break;
            }
        }

        // Build breadcrumb (without root label)
        let breadcrumbHTML = '';

        if (currentH3) {
            breadcrumbHTML += `<span class="breadcrumb-item clickable" data-id="${currentH3.id}">${currentH3.textContent.trim()}</span>`;
        }

        if (currentH4) {
            breadcrumbHTML += `<span class="breadcrumb-separator">›</span>`;
            breadcrumbHTML += `<span class="breadcrumb-item active" data-id="${currentH4.id}">${currentH4.textContent.trim()}</span>`;
        } else if (currentH3) {
            // Mark h3 as active if no h4
            breadcrumbHTML = breadcrumbHTML.replace('clickable"', 'clickable active"');
        }

        // If empty, show placeholder
        if (!breadcrumbHTML) {
            breadcrumbHTML = '<span class="breadcrumb-item" style="color: #adb5bd; font-style: italic;">Scroll to see breadcrumb</span>';
        }

        breadcrumb.innerHTML = breadcrumbHTML;

        // Add click handlers
        breadcrumb.querySelectorAll('.breadcrumb-item.clickable').forEach(item => {
            item.addEventListener('click', function() {
                const id = this.dataset.id;
                if (id) {
                    history.pushState(null, null, `#${id}`);
                    navigateToHash(id);
                }
            });
        });
    }

    /**
     * Initialize URL hash navigation for bookmarkable sections
     */
    function initHashNavigation() {
        console.log('Initializing hash navigation...');

        // Handle hash on page load
        if (window.location.hash) {
            // Small delay to ensure page is fully loaded
            setTimeout(() => {
                navigateToHash(window.location.hash.substring(1));
            }, 100);
        }

        // Handle hash changes (back/forward navigation)
        window.addEventListener('hashchange', function() {
            if (window.location.hash) {
                navigateToHash(window.location.hash.substring(1));
            }
        });

        // Update hash when clicking on syntax variables
        const syntaxVars = elements.leftContent.querySelectorAll('.sdl-var-with-descriptor span[data-var-name]');
        syntaxVars.forEach(span => {
            span.addEventListener('click', function() {
                // Find the nearest section heading
                const section = findNearestSection(span, '_syntax');
                if (section && section.id) {
                    // Update URL without triggering hashchange
                    history.replaceState(null, null, `#${section.id}`);
                }
            });
        });

        // Update hash when clicking on headings
        const allHeadings = document.querySelectorAll('h3[id], h4[id]');
        allHeadings.forEach(heading => {
            heading.addEventListener('click', function(e) {
                // Update hash when clicking anywhere on the heading
                history.pushState(null, null, `#${heading.id}`);
                navigateToHash(heading.id);
            });
        });

        console.log('Hash navigation initialized');
    }

    /**
     * Navigate to a specific element by hash/ID
     */
    function navigateToHash(hash) {
        if (!hash) return;

        console.log(`Navigating to hash: ${hash}`);

        // Try to find the element by ID
        let targetElement = document.getElementById(hash);

        if (!targetElement) {
            console.log(`Element with ID "${hash}" not found`);
            return;
        }

        // Determine which pane the element is in
        const isInSyntax = elements.leftContent.contains(targetElement);
        const isInSemantics = elements.rightContent.contains(targetElement);

        if (isInSyntax) {
            // Scroll to element in syntax pane
            scrollToSyntaxElement(targetElement);

            // If it's a heading, highlight the section
            if (targetElement.matches('h3, h4')) {
                highlightSection(targetElement);

                // Also try to sync to semantics (scroll only, don't highlight)
                if (hash.endsWith('_syntax')) {
                    const semanticsId = hash.replace('_syntax', '_semantics');
                    const semanticsElement = document.getElementById(semanticsId);
                    if (semanticsElement) {
                        scrollToElement(semanticsElement);
                    }
                }
            }
        } else if (isInSemantics) {
            // Scroll to element in semantics pane
            scrollToElement(targetElement);

            // If it's a heading, highlight the section
            if (targetElement.matches('h3, h4')) {
                highlightSection(targetElement);

                // Also try to sync to syntax (scroll only, don't highlight)
                if (hash.endsWith('_semantics')) {
                    const syntaxId = hash.replace('_semantics', '_syntax');
                    const syntaxElement = document.getElementById(syntaxId);
                    if (syntaxElement) {
                        scrollToSyntaxElement(syntaxElement);
                    }
                }
            }
        }
    }

    /**
     * Find nearest section heading for an element
     */
    function findNearestSection(element, suffix) {
        let current = element;
        while (current && current !== elements.leftContent && current !== elements.rightContent) {
            if (current.previousElementSibling) {
                current = current.previousElementSibling;
                if (current.matches && current.matches(`h3[id$="${suffix}"], h4[id$="${suffix}"]`)) {
                    return current;
                }
            } else {
                current = current.parentElement;
            }
        }
        return null;
    }

    /**
     * Highlight a section heading temporarily
     */
    function highlightSection(heading) {
        // Remove existing highlights
        document.querySelectorAll('.section-highlighted').forEach(el => {
            el.classList.remove('section-highlighted');
        });

        // Add highlight
        heading.classList.add('section-highlighted');

        // Remove after duration
        setTimeout(() => {
            heading.classList.remove('section-highlighted');
        }, CONFIG.highlightDuration);
    }

    /**
     * Initialize copy buttons for syntax blocks
     */
    function initCopyButtons() {
        // Find all SDL syntax tables in the syntax pane
        const syntaxTables = elements.leftContent.querySelectorAll('.sdl-syntax-table');

        syntaxTables.forEach(table => {
            // Check if table has original syntax data
            const originalSyntax = table.dataset.originalSyntax;
            if (!originalSyntax) return;

            // Create copy button
            const copyBtn = document.createElement('button');
            copyBtn.className = 'syntax-copy-btn';

            // Check if semantics is available to update tooltip
            const hasSemantics = table.dataset.semantics;
            copyBtn.title = hasSemantics ? 'Copy syntax & semantics' : 'Copy syntax';

            copyBtn.innerHTML = `
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
            `;

            // Add click handler
            copyBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                e.stopPropagation();

                try {
                    // Unescape the HTML entities for syntax
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = originalSyntax;
                    const decodedSyntax = textarea.value;

                    // Check if semantics is available
                    const semantics = table.dataset.semantics;
                    let textToCopy;

                    if (semantics) {
                        // Format with both syntax and semantics in Markdown
                        textToCopy = `## Syntax\n\n\`\`\`\n${decodedSyntax}\n\`\`\`\n\n## Semantics\n\n${semantics}`;
                    } else {
                        // Just copy syntax in code block
                        textToCopy = `\`\`\`\n${decodedSyntax}\n\`\`\``;
                    }

                    // Copy to clipboard
                    await navigator.clipboard.writeText(textToCopy);

                    // Visual feedback
                    copyBtn.classList.add('copied');
                    copyBtn.innerHTML = `
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                    `;

                    // Reset after 2 seconds
                    setTimeout(() => {
                        copyBtn.classList.remove('copied');
                        copyBtn.innerHTML = `
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                            </svg>
                        `;
                    }, 2000);

                } catch (err) {
                    console.error('Failed to copy:', err);
                    // Fallback for older browsers
                    const textarea = document.createElement('textarea');
                    textarea.innerHTML = originalSyntax;
                    const decodedSyntax = textarea.value;

                    const semantics = table.dataset.semantics;
                    if (semantics) {
                        textarea.value = `## Syntax\n\n\`\`\`\n${decodedSyntax}\n\`\`\`\n\n## Semantics\n\n${semantics}`;
                    } else {
                        textarea.value = `\`\`\`\n${decodedSyntax}\n\`\`\``;
                    }

                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);

                    copyBtn.classList.add('copied');
                    setTimeout(() => copyBtn.classList.remove('copied'), 2000);
                }
            });

            // Insert button into table header
            const tableHeader = table.querySelector('thead th.sdl-syntax-name');
            if (tableHeader) {
                tableHeader.style.position = 'relative';
                tableHeader.appendChild(copyBtn);
            }
        });

        console.log(`Added copy buttons to ${syntaxTables.length} syntax blocks`);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Export for debugging
    window.syntaxBrowser = {
        elements: elements,
        state: state,
        searchFor: findAndHighlightInSemantics
    };

})();

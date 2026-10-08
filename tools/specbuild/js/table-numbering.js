/**
 * Table Numbering - Add table numbers dynamically for screen viewing
 *
 * This script adds "Table X.Y:" numbering to table captions on page load.
 * It mirrors the behavior of the PDF preprocessing script but works in the browser.
 *
 * Tables are numbered sequentially within each top-level section (h2).
 * SDL syntax tables are excluded from numbering.
 */

(function() {
  'use strict';

  /**
   * Add table numbers to all captions
   */
  function addTableNumbers() {
    const main = document.querySelector('main');
    if (!main) {
      console.warn('Table numbering: No <main> element found');
      return;
    }

    let sectionNumber = 0;
    let tableNumber = 0;
    const tableNumbers = new Map(); // Map caption IDs to their numbers

    // Process all children of main
    for (const elem of main.children) {
      // Check if this is a numbered h2 (new section)
      if (elem.tagName === 'H2' &&
          elem.classList.contains('heading') &&
          elem.classList.contains('settled') &&
          !elem.classList.contains('no-num')) {

        // Increment section, reset table counter
        sectionNumber++;
        tableNumber = 0;
      }

      // Check if this is a table with a caption
      if (elem.tagName === 'TABLE') {
        const caption = elem.querySelector('caption');

        // Skip SDL syntax tables (they shouldn't be numbered)
        if (caption && !elem.classList.contains('sdl-syntax-table')) {
          tableNumber++;

          // Store the table number for this caption ID (for cross-references)
          if (caption.id) {
            tableNumbers.set(caption.id, `${sectionNumber}.${tableNumber}`);
          }

          // Check if number is already added (e.g., by PDF preprocessing)
          const captionText = caption.textContent.trim();
          if (!captionText.startsWith('Table ')) {
            // Add the table number at the beginning
            const prefix = document.createElement('strong');
            prefix.textContent = `Table ${sectionNumber}.${tableNumber}: `;
            caption.insertBefore(prefix, caption.firstChild);
          }
        }
      }
    }

    console.log(`Table numbering: Added numbers to tables in ${sectionNumber} sections`);

    // Update table cross-references
    updateTableReferences(tableNumbers);
  }

  /**
   * Update table cross-reference links
   */
  function updateTableReferences(tableNumbers) {
    const tableRefs = document.querySelectorAll('a.table-ref');
    let updatedCount = 0;

    for (const link of tableRefs) {
      const href = link.getAttribute('href');
      if (href && href.startsWith('#')) {
        const targetId = href.substring(1);
        if (tableNumbers.has(targetId)) {
          link.textContent = `Table ${tableNumbers.get(targetId)}`;
          updatedCount++;
        }
      }
    }

    if (updatedCount > 0) {
      console.log(`Table numbering: Updated ${updatedCount} table cross-references`);
    }
  }

  // Only run in screen mode (not for PDF generation with @media print)
  // Check if we're generating PDF by looking for Paged.js or print mode indicators
  function shouldAddNumbers() {
    // Don't add if already added by PDF preprocessing (check first table)
    const firstTable = document.querySelector('main table:not(.sdl-syntax-table)');
    if (firstTable) {
      const caption = firstTable.querySelector('caption');
      if (caption && caption.textContent.trim().startsWith('Table ')) {
        console.log('Table numbering: Numbers already present (PDF preprocessing), skipping');
        return false;
      }
    }

    return true;
  }

  // Initialize when DOM is ready
  function init() {
    if (shouldAddNumbers()) {
      addTableNumbers();
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

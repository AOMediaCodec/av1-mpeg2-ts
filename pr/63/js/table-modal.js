/**
 * Table Modal - Fetch-on-demand modal viewer for table attachments
 *
 * This script enhances attachment links to show table data in a modal overlay
 * instead of navigating to a new page. Falls back to normal link behavior
 * if JavaScript is disabled.
 *
 * Smart Activation: Only initializes if attachment links are found (i.e., --compact mode is used).
 * This allows the script to be included in all builds without overhead when not needed.
 */

(function() {
  'use strict';

  // Cache for loaded table content
  const contentCache = new Map();

  // Modal state
  let modalElement = null;
  let currentURL = null;

  /**
   * Initialize the modal system when DOM is ready
   */
  function init() {
    // Smart activation: Check if any attachment links exist
    const attachmentLinks = document.querySelectorAll('a[href^="./attachments/"]');

    if (attachmentLinks.length === 0) {
      console.log('Table modal: No attachment links found, skipping initialization (not in compact mode)');
      return;
    }

    console.log(`Table modal: Found ${attachmentLinks.length} attachment links, initializing modal viewer`);

    createModalElement();
    enhanceAttachmentLinks();
    setupKeyboardShortcuts();
  }

  /**
   * Create the modal HTML structure and add to DOM
   */
  function createModalElement() {
    const modal = document.createElement('div');
    modal.className = 'table-modal-overlay hidden';
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'modal-title');

    modal.innerHTML = `
      <div class="table-modal-content" role="document">
        <div class="table-modal-header">
          <h2 id="modal-title" class="table-modal-title"></h2>
          <div class="table-modal-actions">
            <button class="table-modal-button copy-button" title="Copy to clipboard">
              Copy
            </button>
            <button class="table-modal-close" title="Close (Esc)" aria-label="Close">
              ×
            </button>
          </div>
        </div>
        <div class="table-modal-body">
          <pre class="table-modal-code"></pre>
        </div>
      </div>
    `;

    document.body.appendChild(modal);
    modalElement = modal;

    // Close on overlay click (but not on content click)
    modal.addEventListener('click', function(e) {
      if (e.target === modal) {
        closeModal();
      }
    });

    // Close button
    const closeBtn = modal.querySelector('.table-modal-close');
    closeBtn.addEventListener('click', closeModal);

    // Copy button
    const copyBtn = modal.querySelector('.copy-button');
    copyBtn.addEventListener('click', handleCopy);
  }

  /**
   * Enhance all attachment links to use the modal
   */
  function enhanceAttachmentLinks() {
    const links = document.querySelectorAll('a[href^="./attachments/"]');

    links.forEach(link => {
      // Add visual indicator class
      link.classList.add('table-attachment-link');

      // Intercept clicks
      link.addEventListener('click', function(e) {
        e.preventDefault();
        const url = link.getAttribute('href');
        const filename = url.split('/').pop();
        openModal(url, filename);
      });
    });

    console.log(`Enhanced ${links.length} attachment links with modal viewer`);
  }

  /**
   * Setup keyboard shortcuts
   */
  function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && !modalElement.classList.contains('hidden')) {
        closeModal();
      }
    });
  }

  /**
   * Open modal and load content
   */
  async function openModal(url, filename) {
    currentURL = url;
    const titleEl = modalElement.querySelector('.table-modal-title');
    const bodyEl = modalElement.querySelector('.table-modal-body');
    const codeEl = modalElement.querySelector('.table-modal-code');

    // Set title
    titleEl.textContent = filename;

    // Show modal
    modalElement.classList.remove('hidden');
    document.body.style.overflow = 'hidden'; // Prevent background scrolling

    // Check cache first
    if (contentCache.has(url)) {
      codeEl.textContent = contentCache.get(url);
      return;
    }

    // Show loading state
    bodyEl.innerHTML = `
      <div class="table-modal-loading">
        <div class="table-modal-spinner"></div>
        <div>Loading ${filename}...</div>
      </div>
    `;

    try {
      const response = await fetch(url);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const content = await response.text();

      // Cache the content
      contentCache.set(url, content);

      // Only update if we're still showing the same URL
      if (currentURL === url) {
        bodyEl.innerHTML = '<pre class="table-modal-code"></pre>';
        modalElement.querySelector('.table-modal-code').textContent = content;
      }
    } catch (error) {
      console.error('Failed to load table:', error);

      if (currentURL === url) {
        bodyEl.innerHTML = `
          <div class="table-modal-error">
            <p><strong>Failed to load ${filename}</strong></p>
            <p>${error.message}</p>
            <p><a href="${url}" target="_blank">Open in new tab instead</a></p>
          </div>
        `;
      }
    }
  }

  /**
   * Close the modal
   */
  function closeModal() {
    modalElement.classList.add('hidden');
    document.body.style.overflow = ''; // Restore scrolling
    currentURL = null;

    // Reset copy button state
    const copyBtn = modalElement.querySelector('.copy-button');
    copyBtn.textContent = 'Copy';
    copyBtn.classList.remove('copied');
  }

  /**
   * Handle copy to clipboard
   */
  async function handleCopy() {
    const codeEl = modalElement.querySelector('.table-modal-code');
    const copyBtn = modalElement.querySelector('.copy-button');
    const content = codeEl.textContent;

    try {
      await navigator.clipboard.writeText(content);

      // Visual feedback
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');

      setTimeout(() => {
        copyBtn.textContent = 'Copy';
        copyBtn.classList.remove('copied');
      }, 2000);
    } catch (error) {
      console.error('Failed to copy:', error);

      // Fallback: select the text
      const selection = window.getSelection();
      const range = document.createRange();
      range.selectNodeContents(codeEl);
      selection.removeAllRanges();
      selection.addRange(range);

      copyBtn.textContent = 'Selected';
      setTimeout(() => {
        copyBtn.textContent = 'Copy';
      }, 2000);
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

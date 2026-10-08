/**
 * Multipage Navigation JavaScript for AV2 Specification
 *
 * This script provides interactive behavior for the multipage HTML version,
 * including current section highlighting, mobile menu, dropdown navigation,
 * and keyboard shortcuts.
 */

(function() {
  'use strict';

  // Wait for DOM to be ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function init() {
    highlightCurrentSection();
    setupDropdownNavigation();
    setupKeyboardShortcuts();
    setupMobileMenu();
    restoreScrollPosition();
    setupScrollPositionSaving();
    setupTocCollapse();
    setupSmoothScrolling();
    setupDialogEscapeHandler();
  }

  /**
   * Highlight the current section in the sidebar TOC
   */
  function highlightCurrentSection() {
    // Get current page filename
    const currentPath = window.location.pathname.split('/').pop();

    // Find all TOC links in sidebar
    const tocLinks = document.querySelectorAll('#multipage-sidebar a');

    tocLinks.forEach(link => {
      const href = link.getAttribute('href');
      if (href === currentPath) {
        // Add current class to parent li
        const listItem = link.closest('li');
        if (listItem) {
          listItem.classList.add('current-section');
        }

        // Scroll sidebar to show current section
        if (link.offsetParent) {
          const sidebar = document.getElementById('multipage-sidebar');
          if (sidebar) {
            // Center the current section in the sidebar view
            const linkTop = link.offsetTop;
            const sidebarHeight = sidebar.clientHeight;
            const scrollTarget = linkTop - (sidebarHeight / 2) + (link.clientHeight / 2);
            sidebar.scrollTop = Math.max(0, scrollTarget);
          }
        }
      }
    });
  }

  /**
   * Set up dropdown selector navigation
   */
  function setupDropdownNavigation() {
    const selector = document.getElementById('section-selector');
    if (!selector) return;

    selector.addEventListener('change', function() {
      const selectedValue = this.value;
      if (selectedValue) {
        window.location.href = selectedValue;
      }
    });
  }

  /**
   * Set up keyboard shortcuts for navigation
   */
  function setupKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
      // Don't trigger if user is typing in an input/textarea
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.isContentEditable) {
        return;
      }

      switch(e.key) {
        case 'j':
          // Next page
          e.preventDefault();
          const nextLink = document.querySelector('.nav-next:not(.nav-disabled)');
          if (nextLink) {
            nextLink.click();
          }
          break;

        case 'k':
          // Previous page
          e.preventDefault();
          const prevLink = document.querySelector('.nav-prev:not(.nav-disabled)');
          if (prevLink) {
            prevLink.click();
          }
          break;

        case 'h':
          // Home/TOC
          e.preventDefault();
          const homeLink = document.querySelector('.nav-home');
          if (homeLink) {
            homeLink.click();
          }
          break;

        case 't':
          // Toggle sidebar on mobile
          e.preventDefault();
          toggleSidebar();
          break;

        case '?':
          // Show keyboard shortcuts help
          e.preventDefault();
          showKeyboardShortcutsHelp();
          break;
      }
    });
  }

  /**
   * Set up mobile menu toggle
   */
  function setupMobileMenu() {
    // Create mobile menu toggle button if it doesn't exist
    if (window.innerWidth <= 768) {
      createMobileMenuButton();
    }

    // Add event listener for window resize
    window.addEventListener('resize', function() {
      if (window.innerWidth <= 768) {
        createMobileMenuButton();
      } else {
        removeMobileMenuButton();
        // Ensure sidebar is visible on desktop
        const sidebar = document.getElementById('multipage-sidebar');
        if (sidebar) {
          sidebar.classList.remove('open');
        }
      }
    });
  }

  /**
   * Create mobile menu toggle button
   */
  function createMobileMenuButton() {
    // Check if button already exists
    if (document.getElementById('mobile-menu-toggle')) return;

    const button = document.createElement('button');
    button.id = 'mobile-menu-toggle';
    button.className = 'mobile-menu-toggle';
    button.setAttribute('aria-label', 'Toggle navigation menu');
    button.innerHTML = '☰ Menu';

    button.addEventListener('click', toggleSidebar);

    // Insert at start of body
    document.body.insertBefore(button, document.body.firstChild);
  }

  /**
   * Remove mobile menu toggle button
   */
  function removeMobileMenuButton() {
    const button = document.getElementById('mobile-menu-toggle');
    if (button) {
      button.remove();
    }
  }

  /**
   * Toggle sidebar visibility (mobile)
   */
  function toggleSidebar() {
    const sidebar = document.getElementById('multipage-sidebar');
    if (!sidebar) return;

    sidebar.classList.toggle('open');

    // Update button text
    const button = document.getElementById('mobile-menu-toggle');
    if (button) {
      if (sidebar.classList.contains('open')) {
        button.innerHTML = '✕ Close';
      } else {
        button.innerHTML = '☰ Menu';
      }
    }

    // Close sidebar when clicking outside on mobile
    if (sidebar.classList.contains('open')) {
      // Add click listener to close sidebar
      setTimeout(function() {
        document.addEventListener('click', closeSidebarOnOutsideClick);
      }, 0);
    } else {
      document.removeEventListener('click', closeSidebarOnOutsideClick);
    }
  }

  /**
   * Close sidebar when clicking outside (mobile)
   */
  function closeSidebarOnOutsideClick(e) {
    const sidebar = document.getElementById('multipage-sidebar');
    const button = document.getElementById('mobile-menu-toggle');

    if (!sidebar || !sidebar.classList.contains('open')) {
      return;
    }

    // Check if click is outside sidebar and button
    // Treat missing button as an outside click
    if (!sidebar.contains(e.target) && (!button || !button.contains(e.target))) {
      sidebar.classList.remove('open');
      if (button) {
        button.innerHTML = '☰ Menu';
      }
      document.removeEventListener('click', closeSidebarOnOutsideClick);
    }
  }

  /**
   * Save scroll position before navigation
   */
  function setupScrollPositionSaving() {
    // Save scroll position before leaving page
    window.addEventListener('beforeunload', function() {
      const scrollPos = window.pageYOffset || document.documentElement.scrollTop;
      const currentPath = window.location.pathname;
      sessionStorage.setItem('scrollPos_' + currentPath, scrollPos);
    });
  }

  /**
   * Restore scroll position on page load
   */
  function restoreScrollPosition() {
    // Check if there's a hash in the URL
    if (window.location.hash) {
      // Let the browser handle scrolling to the anchor
      return;
    }

    // Otherwise, restore saved scroll position
    const currentPath = window.location.pathname;
    const savedScrollPos = sessionStorage.getItem('scrollPos_' + currentPath);

    if (savedScrollPos !== null) {
      window.scrollTo(0, parseInt(savedScrollPos, 10));
    }
  }

  /**
   * Show keyboard shortcuts help dialog
   */
  function showKeyboardShortcutsHelp() {
    // Check if dialog already exists
    if (document.getElementById('keyboard-shortcuts-dialog')) {
      document.getElementById('keyboard-shortcuts-dialog').style.display = 'block';
      return;
    }

    // Create help dialog
    const dialog = document.createElement('div');
    dialog.id = 'keyboard-shortcuts-dialog';
    dialog.style.cssText = `
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      background: white;
      border: 2px solid #333;
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 4px 16px rgba(0,0,0,0.3);
      z-index: 10000;
      max-width: 400px;
      width: 90%;
    `;

    dialog.innerHTML = `
      <h3 style="margin-top: 0;">Keyboard Shortcuts</h3>
      <table style="width: 100%; border-collapse: collapse;">
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;"><kbd>j</kbd></td>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;">Next page</td>
        </tr>
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;"><kbd>k</kbd></td>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;">Previous page</td>
        </tr>
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;"><kbd>h</kbd></td>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;">Home / Table of Contents</td>
        </tr>
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;"><kbd>t</kbd></td>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;">Toggle sidebar (mobile)</td>
        </tr>
        <tr>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;"><kbd>/</kbd> or <kbd>Ctrl+K</kbd></td>
          <td style="padding: 8px; border-bottom: 1px solid #ddd;">Search</td>
        </tr>
        <tr>
          <td style="padding: 8px;"><kbd>?</kbd></td>
          <td style="padding: 8px;">Show this help</td>
        </tr>
      </table>
      <button id="close-shortcuts-dialog" style="
        margin-top: 16px;
        padding: 8px 16px;
        background: #007bff;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        width: 100%;
      ">Close</button>
    `;

    // Add backdrop
    const backdrop = document.createElement('div');
    backdrop.id = 'keyboard-shortcuts-backdrop';
    backdrop.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0,0,0,0.5);
      z-index: 9999;
    `;

    document.body.appendChild(backdrop);
    document.body.appendChild(dialog);

    // Close button handler
    document.getElementById('close-shortcuts-dialog').addEventListener('click', function() {
      dialog.style.display = 'none';
      backdrop.style.display = 'none';
    });

    // Close on backdrop click
    backdrop.addEventListener('click', function() {
      dialog.style.display = 'none';
      backdrop.style.display = 'none';
    });
  }

  /**
   * Set up a single escape key handler for dialogs
   */
  function setupDialogEscapeHandler() {
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') {
        const dialog = document.getElementById('keyboard-shortcuts-dialog');
        const backdrop = document.getElementById('keyboard-shortcuts-backdrop');
        if (dialog && dialog.style.display !== 'none') {
          dialog.style.display = 'none';
          if (backdrop) {
            backdrop.style.display = 'none';
          }
        }
      }
    });
  }

  /**
   * Add smooth scrolling for anchor links
   */
  function setupSmoothScrolling() {
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
      anchor.addEventListener('click', function(e) {
        const href = this.getAttribute('href');
        if (href === '#') return;

        const target = document.querySelector(href);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
          });

          // Update URL without triggering scroll
          history.pushState(null, null, href);
        }
      });
    });
  }

  /**
   * Set up collapsible TOC sections
   */
  function setupTocCollapse() {
    // Find all toggle buttons
    const toggleButtons = document.querySelectorAll('.toc-toggle');

    toggleButtons.forEach(button => {
      button.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();

        const expanded = button.getAttribute('data-expanded') === 'true';

        // Toggle data attribute and aria-expanded
        button.setAttribute('data-expanded', !expanded);
        button.setAttribute('aria-expanded', !expanded);

        // Find the controlled sublist using aria-controls
        const controlsId = button.getAttribute('aria-controls');
        if (controlsId) {
          const sublist = document.getElementById(controlsId);
          if (sublist) {
            sublist.style.display = expanded ? 'none' : 'block';
          }
        }

        // Rotate icon
        const icon = button.querySelector('.toc-toggle-icon');
        if (icon) {
          icon.textContent = expanded ? '▶' : '▼';
        }
      });
    });
  }

  // Log initialization
  console.log('Multipage navigation initialized');
  console.log('Press ? to see keyboard shortcuts');

})();

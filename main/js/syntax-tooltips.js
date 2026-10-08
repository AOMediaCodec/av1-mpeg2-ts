/* SDL Syntax Element Tooltips
   Shows semantic descriptions when hovering over variable names
   in SDL syntax tables. */

(function () {
  "use strict";

  var TOOLTIP_ID = "sdl-tooltip";
  var SHOW_DELAY = 300;
  var HIDE_DELAY = 150;

  var tooltip = null;
  var showTimer = null;
  var hideTimer = null;

  function getOrCreate() {
    var el = document.getElementById(TOOLTIP_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = TOOLTIP_ID;
      el.setAttribute("role", "tooltip");
      document.body.appendChild(el);
      el.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
      el.addEventListener("mouseleave", function () { scheduleHide(); });
    }
    return el;
  }

  function position(tip, anchor) {
    var rect = anchor.getBoundingClientRect();
    var top = rect.bottom + window.scrollY + 6;
    var left = rect.left + window.scrollX;

    // Ensure tooltip stays within viewport
    tip.style.top = top + "px";
    tip.style.left = left + "px";

    // Adjust after rendering so we know dimensions
    requestAnimationFrame(function () {
      var tipRect = tip.getBoundingClientRect();

      // Flip above if below viewport
      if (tipRect.bottom > window.innerHeight - 8) {
        tip.style.top = (rect.top + window.scrollY - tipRect.height - 6) + "px";
      }

      // Clamp horizontal
      if (tipRect.right > window.innerWidth - 8) {
        tip.style.left = Math.max(8, window.innerWidth - tipRect.width - 8) + "px";
      }
    });
  }

  function hideActive() {
    if (tooltip) {
      tooltip.classList.remove("visible");
    }
  }

  function scheduleHide() {
    clearTimeout(showTimer);
    hideTimer = setTimeout(hideActive, HIDE_DELAY);
  }

  function showTooltip(cell) {
    clearTimeout(hideTimer);
    hideActive();

    var text = cell.getAttribute("data-tooltip");
    if (!text) return;

    var tip = getOrCreate();
    tip.textContent = text;
    tooltip = tip;
    tip.classList.add("visible");
    position(tip, cell);
  }

  function init() {
    document.addEventListener("mouseover", function (e) {
      var cell = e.target.closest("td.has-syntax-tooltip");
      if (!cell) return;

      clearTimeout(hideTimer);
      showTimer = setTimeout(function () { showTooltip(cell); }, SHOW_DELAY);
    });

    document.addEventListener("mouseout", function (e) {
      var cell = e.target.closest("td.has-syntax-tooltip");
      if (!cell) return;
      scheduleHide();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

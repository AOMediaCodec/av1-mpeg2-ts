/* Equation Tooltip Preview
   Shows a live preview of the referenced equation when hovering over
   equation cross-reference links (a[href^="#eq-"]). */

(function () {
  "use strict";

  var TOOLTIP_ID = "eq-tooltip";
  var SHOW_DELAY = 200;   // ms before tooltip appears
  var HIDE_DELAY = 150;   // ms before tooltip disappears

  var tooltip = null;
  var showTimer = null;
  var hideTimer = null;

  function createTooltip() {
    if (tooltip) return tooltip;
    tooltip = document.createElement("div");
    tooltip.id = TOOLTIP_ID;
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
    // Keep tooltip open while hovering over it
    tooltip.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    tooltip.addEventListener("mouseleave", function () { scheduleHide(); });
    return tooltip;
  }

  function positionTooltip(anchor) {
    var rect = anchor.getBoundingClientRect();
    var tip = createTooltip();
    // Position above the link, centred horizontally
    var top = rect.top + window.scrollY - tip.offsetHeight - 8;
    var left = rect.left + window.scrollX + rect.width / 2 - tip.offsetWidth / 2;
    // Keep within viewport
    left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8));
    if (top < window.scrollY + 8) {
      // If no room above, show below
      top = rect.bottom + window.scrollY + 8;
    }
    tip.style.top = top + "px";
    tip.style.left = left + "px";
  }

  /** Find the .equation-wrapper and its .equation-number span for a target ID.
   *  The target element may be:
   *  - The .equation-number span itself (auto-generated ID like "eq-5-1")
   *  - A user-defined div wrapping the .equation-wrapper (e.g. "eq-wheelbase")
   *  - The .equation-wrapper itself
   */
  function findEquation(targetId) {
    var el = document.getElementById(targetId);
    if (!el) return null;

    var wrapper, numSpan;

    // Case 1: element IS the equation-number span
    if (el.classList.contains("equation-number")) {
      wrapper = el.closest(".equation-wrapper");
      numSpan = el;
    }
    // Case 2: element IS the equation-wrapper
    else if (el.classList.contains("equation-wrapper")) {
      wrapper = el;
      numSpan = el.querySelector(".equation-number");
    }
    // Case 3: element is a parent/ancestor containing the wrapper
    else {
      wrapper = el.querySelector(".equation-wrapper");
      if (!wrapper) wrapper = el.closest(".equation-wrapper");
      numSpan = wrapper ? wrapper.querySelector(".equation-number") : null;
    }

    if (!wrapper) return null;
    return { wrapper: wrapper, numSpan: numSpan };
  }

  function showTooltip(anchor) {
    clearTimeout(hideTimer);
    var href = anchor.getAttribute("href");
    if (!href || !href.startsWith("#eq-")) return;

    var targetId = href.slice(1);
    var eq = findEquation(targetId);
    if (!eq) return;

    var tip = createTooltip();
    tip.innerHTML = "";

    // Clone the equation content (excluding the equation-number span)
    var children = eq.wrapper.childNodes;
    for (var i = 0; i < children.length; i++) {
      var node = children[i];
      if (node.nodeType === 1 && node.classList && node.classList.contains("equation-number")) {
        continue;
      }
      tip.appendChild(node.cloneNode(true));
    }

    // Add equation number label
    if (eq.numSpan) {
      var label = document.createElement("span");
      label.className = "eq-tooltip-label";
      label.textContent = eq.numSpan.textContent;
      tip.appendChild(label);
    }

    tip.classList.add("visible");
    // Position after content is in DOM so dimensions are known
    requestAnimationFrame(function () { positionTooltip(anchor); });
  }

  function scheduleHide() {
    clearTimeout(showTimer);
    hideTimer = setTimeout(function () {
      if (tooltip) tooltip.classList.remove("visible");
    }, HIDE_DELAY);
  }

  function init() {
    // Delegate hover events on equation reference links
    document.addEventListener("mouseover", function (e) {
      var link = e.target.closest('a[href^="#eq-"]');
      if (!link) return;
      clearTimeout(hideTimer);
      showTimer = setTimeout(function () { showTooltip(link); }, SHOW_DELAY);
    });

    document.addEventListener("mouseout", function (e) {
      var link = e.target.closest('a[href^="#eq-"]');
      if (!link) return;
      scheduleHide();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

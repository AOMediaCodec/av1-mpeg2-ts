/* Definition Tooltip Preview
   Shows the definition text when hovering over a definition reference
   link (<a data-link-type="dfn">). */

(function () {
  "use strict";

  var TOOLTIP_ID = "dfn-tooltip";
  var SHOW_DELAY = 250;
  var HIDE_DELAY = 150;
  var MAX_TEXT_LENGTH = 300;

  var tooltip = null;
  var showTimer = null;
  var hideTimer = null;

  function createTooltip() {
    if (tooltip) return tooltip;
    tooltip = document.createElement("div");
    tooltip.id = TOOLTIP_ID;
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
    tooltip.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
    tooltip.addEventListener("mouseleave", function () { scheduleHide(); });
    return tooltip;
  }

  function positionTooltip(anchor) {
    var rect = anchor.getBoundingClientRect();
    var tip = createTooltip();
    var top = rect.top + window.scrollY - tip.offsetHeight - 8;
    var left = rect.left + window.scrollX + rect.width / 2 - tip.offsetWidth / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8));
    if (top < window.scrollY + 8) {
      top = rect.bottom + window.scrollY + 8;
    }
    tip.style.top = top + "px";
    tip.style.left = left + "px";
  }

  /** Extract the definition text for a given dfn ID. */
  function getDefinitionText(dfnId) {
    var dfnEl = document.getElementById(dfnId);
    if (!dfnEl) return null;

    // Definitions are typically in <dt><dfn>...</dfn></dt><dd>definition text</dd>
    var dt = dfnEl.closest("dt");
    if (dt) {
      var dd = dt.nextElementSibling;
      while (dd && dd.tagName !== "DD") {
        dd = dd.nextElementSibling;
      }
      if (dd) {
        var text = dd.textContent.trim();
        if (text.length > MAX_TEXT_LENGTH) {
          text = text.slice(0, MAX_TEXT_LENGTH).replace(/\s+\S*$/, "") + "\u2026";
        }
        return text;
      }
    }

    // Fallback: definition might be inline (not in a dl). Get the
    // parent paragraph or containing block text.
    var parent = dfnEl.parentElement;
    if (parent) {
      var text = parent.textContent.trim();
      if (text.length > MAX_TEXT_LENGTH) {
        text = text.slice(0, MAX_TEXT_LENGTH).replace(/\s+\S*$/, "") + "\u2026";
      }
      return text;
    }

    return null;
  }

  function showTooltip(anchor) {
    clearTimeout(hideTimer);
    var href = anchor.getAttribute("href");
    if (!href || !href.startsWith("#")) return;

    var dfnId = href.slice(1);
    var text = getDefinitionText(dfnId);
    if (!text) return;

    var term = anchor.textContent.trim();

    var tip = createTooltip();
    tip.innerHTML = "";

    var termEl = document.createElement("strong");
    termEl.className = "dfn-tooltip-term";
    termEl.textContent = term;
    tip.appendChild(termEl);

    var defEl = document.createElement("span");
    defEl.className = "dfn-tooltip-text";
    defEl.textContent = text;
    tip.appendChild(defEl);

    tip.classList.add("visible");
    requestAnimationFrame(function () { positionTooltip(anchor); });
  }

  function scheduleHide() {
    clearTimeout(showTimer);
    hideTimer = setTimeout(function () {
      if (tooltip) tooltip.classList.remove("visible");
    }, HIDE_DELAY);
  }

  function init() {
    document.addEventListener("mouseover", function (e) {
      var link = e.target.closest('a[data-link-type="dfn"]');
      if (!link) return;
      clearTimeout(hideTimer);
      showTimer = setTimeout(function () { showTooltip(link); }, SHOW_DELAY);
    });

    document.addEventListener("mouseout", function (e) {
      var link = e.target.closest('a[data-link-type="dfn"]');
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

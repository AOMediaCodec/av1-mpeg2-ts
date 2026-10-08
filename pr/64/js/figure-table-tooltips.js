/* Figure & Table Tooltip Previews
   Shows a preview when hovering over figure-ref and table-ref links. */

(function () {
  "use strict";

  var FIG_TOOLTIP_ID = "fig-tooltip";
  var TBL_TOOLTIP_ID = "tbl-tooltip";
  var SHOW_DELAY = 250;
  var HIDE_DELAY = 150;

  var figTooltip = null;
  var tblTooltip = null;
  var showTimer = null;
  var hideTimer = null;
  var activeTooltip = null;

  function getOrCreate(id) {
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      el.setAttribute("role", "tooltip");
      document.body.appendChild(el);
      el.addEventListener("mouseenter", function () { clearTimeout(hideTimer); });
      el.addEventListener("mouseleave", function () { scheduleHide(); });
    }
    return el;
  }

  function position(tip, anchor) {
    var rect = anchor.getBoundingClientRect();
    var top = rect.top + window.scrollY - tip.offsetHeight - 8;
    var left = rect.left + window.scrollX + rect.width / 2 - tip.offsetWidth / 2;
    left = Math.max(8, Math.min(left, window.innerWidth - tip.offsetWidth - 8));
    if (top < window.scrollY + 8) {
      top = rect.bottom + window.scrollY + 8;
    }
    tip.style.top = top + "px";
    tip.style.left = left + "px";
  }

  function hideActive() {
    if (activeTooltip) {
      activeTooltip.classList.remove("visible");
      activeTooltip = null;
    }
  }

  function scheduleHide() {
    clearTimeout(showTimer);
    hideTimer = setTimeout(hideActive, HIDE_DELAY);
  }

  /* ── Figure tooltip ──────────────────────────────────────────── */

  function showFigure(anchor) {
    clearTimeout(hideTimer);
    hideActive();

    var href = anchor.getAttribute("href");
    if (!href || !href.startsWith("#")) return;

    var figEl = document.getElementById(href.slice(1));
    if (!figEl) return;

    // Find the figure element (target might be the figure or inside it)
    var figure = figEl.tagName === "FIGURE" ? figEl : figEl.closest("figure");
    if (!figure) return;

    var tip = getOrCreate(FIG_TOOLTIP_ID);
    tip.innerHTML = "";

    // Clone the image (thumbnail)
    var img = figure.querySelector("img, svg");
    if (img) {
      var imgClone = img.cloneNode(true);
      imgClone.className = "fig-tooltip-image";
      imgClone.removeAttribute("width");
      imgClone.removeAttribute("height");
      tip.appendChild(imgClone);
    }

    // Caption text
    var figcaption = figure.querySelector("figcaption");
    if (figcaption) {
      var cap = document.createElement("div");
      cap.className = "fig-tooltip-caption";
      cap.textContent = figcaption.textContent.trim();
      tip.appendChild(cap);
    }

    activeTooltip = tip;
    tip.classList.add("visible");
    requestAnimationFrame(function () { position(tip, anchor); });
  }

  /* ── Table tooltip ───────────────────────────────────────────── */

  function showTable(anchor) {
    clearTimeout(hideTimer);
    hideActive();

    var href = anchor.getAttribute("href");
    if (!href || !href.startsWith("#")) return;

    var targetEl = document.getElementById(href.slice(1));
    if (!targetEl) return;

    // Find the table element
    var table = targetEl.tagName === "TABLE" ? targetEl : targetEl.closest("table");
    if (!table) {
      // Caption ID might be on the caption itself
      table = targetEl.parentElement;
      if (!table || table.tagName !== "TABLE") return;
    }

    var tip = getOrCreate(TBL_TOOLTIP_ID);
    tip.innerHTML = "";

    // Caption
    var caption = table.querySelector("caption");
    if (caption) {
      var cap = document.createElement("div");
      cap.className = "tbl-tooltip-caption";
      cap.textContent = caption.textContent.trim();
      tip.appendChild(cap);
    }

    // Clone first few rows as preview
    var preview = document.createElement("table");
    preview.className = "tbl-tooltip-preview";

    var thead = table.querySelector("thead");
    if (thead) {
      preview.appendChild(thead.cloneNode(true));
    }

    var tbody = table.querySelector("tbody");
    if (tbody) {
      var previewBody = document.createElement("tbody");
      var rows = tbody.querySelectorAll("tr");
      var maxRows = Math.min(rows.length, 3);
      for (var i = 0; i < maxRows; i++) {
        previewBody.appendChild(rows[i].cloneNode(true));
      }
      if (rows.length > 3) {
        var ellipsis = document.createElement("tr");
        var td = document.createElement("td");
        td.colSpan = 20;
        td.className = "tbl-tooltip-ellipsis";
        td.textContent = "\u2026 " + (rows.length - 3) + " more rows";
        ellipsis.appendChild(td);
        previewBody.appendChild(ellipsis);
      }
      preview.appendChild(previewBody);
    }

    tip.appendChild(preview);

    activeTooltip = tip;
    tip.classList.add("visible");
    requestAnimationFrame(function () { position(tip, anchor); });
  }

  /* ── Event delegation ────────────────────────────────────────── */

  function init() {
    document.addEventListener("mouseover", function (e) {
      var figLink = e.target.closest("a.figure-ref");
      var tblLink = e.target.closest("a.table-ref");
      if (!figLink && !tblLink) return;

      clearTimeout(hideTimer);
      var link = figLink || tblLink;
      var handler = figLink ? showFigure : showTable;
      showTimer = setTimeout(function () { handler(link); }, SHOW_DELAY);
    });

    document.addEventListener("mouseout", function (e) {
      var link = e.target.closest("a.figure-ref, a.table-ref");
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

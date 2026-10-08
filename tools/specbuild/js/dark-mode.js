/* Dark Mode Toggle
   Cycles through: Light -> Dark -> Auto (OS preference).
   Persists choice in localStorage. */

(function () {
  "use strict";

  var STORAGE_KEY = "spec-theme";
  var MODES = ["light", "dark", "auto"];
  var ICONS = { light: "\u2600", dark: "\u263D", auto: "\u25D0" };   // sun, moon, half-circle
  var LABELS = { light: "Light", dark: "Dark", auto: "Auto" };

  /** Read saved preference, defaulting to "light". */
  function getSaved() {
    try {
      var v = localStorage.getItem(STORAGE_KEY);
      return MODES.indexOf(v) !== -1 ? v : "light";
    } catch (e) {
      return "light";
    }
  }

  /** Apply the theme to <html> and update the toggle button. */
  function apply(mode) {
    document.documentElement.setAttribute("data-theme", mode);
    var btn = document.getElementById("dark-mode-toggle");
    if (btn) {
      var icon = btn.querySelector(".dm-icon");
      var label = btn.querySelector(".dm-label");
      if (icon) icon.textContent = ICONS[mode];
      if (label) label.textContent = LABELS[mode];
      btn.setAttribute("title", "Theme: " + LABELS[mode] + " (click to cycle)");
    }
  }

  /** Cycle to the next mode and persist. */
  function cycle() {
    var current = getSaved();
    var next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
    try { localStorage.setItem(STORAGE_KEY, next); } catch (e) { /* ignore */ }
    apply(next);
  }

  // Apply saved theme immediately (before DOM ready) to prevent flash
  apply(getSaved());

  // Inject the toggle button once the DOM is ready
  function injectButton() {
    if (document.getElementById("dark-mode-toggle")) return;
    var btn = document.createElement("button");
    btn.id = "dark-mode-toggle";
    btn.type = "button";
    btn.setAttribute("aria-label", "Toggle dark mode");
    btn.innerHTML = '<span class="dm-icon"></span><span class="dm-label"></span>';
    btn.addEventListener("click", cycle);
    document.body.appendChild(btn);
    apply(getSaved());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectButton);
  } else {
    injectButton();
  }
})();

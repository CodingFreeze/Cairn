/* Terminal pane — deterministic typewriter. Each term event types out over
   TYPE_MS keyed to (t - event.t), so seeking is frame-exact. */
"use strict";

const Term = (() => {
  const TYPE_MS = 420;       // cmd lines type; out/ok lines appear in one beat
  const MAX_LINES = 18;
  let el;

  function init() { el = document.getElementById("term"); }

  function render(t, termEvents) {
    const visible = termEvents.filter(e => e.t <= t).slice(-MAX_LINES);
    const html = visible.map((e, i) => {
      let text = e.text;
      if (e.style === "cmd") {
        const k = Math.max(0, Math.min(1, (t - e.t) / TYPE_MS));
        text = text.slice(0, Math.ceil(text.length * k));
      }
      const last = i === visible.length - 1;
      const cur = last && (t - e.t) < 2200 ? '<span class="cursor"></span>' : "";
      return `<div class="ln ${e.style}">${esc(text)}${cur}</div>`;
    }).join("");
    if (el.innerHTML !== html) el.innerHTML = html;
  }

  const esc = s => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return { init, render };
})();

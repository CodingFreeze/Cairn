/* Board pane — board.jsonl table mirror (replay + live modes).
   SECURITY: ids/branches come from a USER repo's board.jsonl — always
   untrusted. Text is escaped; status values are allowlisted before being
   interpolated into class names. */
"use strict";

const Board = (() => {
  let el;
  // Full board.jsonl status set (mirrors boardcheck.VALID_STATUS).
  const VALID = new Set([
    "todo", "dispatched", "in-progress", "pr-open", "merged", "blocked", "cancelled",
  ]);
  const esc = s => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const safeStatus = s => VALID.has(s) ? s : "todo";
  function init() { el = document.getElementById("board"); }

  function row(id, state, branch, flash) {
    return `<tr class="${flash ? "flash" : ""}"><td>${esc(id)}</td>` +
      `<td><span class="st ${safeStatus(state)}">${safeStatus(state)}</span></td>` +
      `<td>${esc(branch)}</td></tr>`;
  }

  function table(rows, merged, total) {
    return `<table><thead><tr><th>ID</th><th>STATUS</th><th>BRANCH</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>` +
      `<div style="margin-top:8px;color:#768390;font-size:11.5px;letter-spacing:.1em">` +
      `${merged}/${total} MERGED</div>`;
  }

  function render(t, dag, nodeStates) {
    const rows = dag
      .filter(n => nodeStates[n.id])
      .map(n => {
        const st = nodeStates[n.id];
        const state = safeStatus(st.state);
        const flash = state === "merged" && (t - st.since) < 900;
        const branch = state === "todo" ? "—" : `cairn/${n.id}`;
        return row(n.id, state, branch, flash);
      }).join("");
    const merged = Object.values(nodeStates).filter(s => s.state === "merged").length;
    const html = table(rows, merged, dag.length);
    if (el.innerHTML !== html) el.innerHTML = html;
  }

  // LIVE mode: render raw board entries from /api/board. `flashIds` marks rows
  // whose status changed in the last poll.
  function renderEntries(entries, flashIds) {
    const rows = entries.map(e => {
      const state = safeStatus(e.status);
      const branch = e.branch ? String(e.branch) : "—";
      return row(e.id, state, branch, flashIds && flashIds.has(e.id));
    }).join("");
    const merged = entries.filter(e => e.status === "merged").length;
    const html = table(rows, merged, entries.length);
    if (el.innerHTML !== html) el.innerHTML = html;
  }

  return { init, render, renderEntries, esc, safeStatus };
})();

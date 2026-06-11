/* LIVE mode — polls GET /api/board every 1500ms and re-renders the same
   graph/board/terminal panes the replay engine uses.

   SECURITY: everything in the API payload originates in a USER repo's
   .cairn/ (board.jsonl ids/branches, vault markdown lines) — treat all of it
   as untrusted. Text nodes are escaped (Board.esc), status values are
   allowlisted (Board.safeStatus), and the graph payload is sanitized before
   it reaches the canvas renderer (canvas fillText cannot execute markup, but
   we still coerce types so a hostile payload cannot crash the layout). */
"use strict";

const Live = (() => {
  const POLL_MS = 1500;
  const FEED_MAX = 18;
  // board status -> graph node state (graph renders 4 visual states)
  const NODE_STATE = {
    todo: "todo", dispatched: "dispatched", "in-progress": "in-progress",
    "pr-open": "in-progress", merged: "merged", blocked: "todo", cancelled: "todo",
  };
  const FEED_STYLE = { merged: "ok", blocked: "warn", cancelled: "err" };

  let termEl, vaultEl, feed = [], prev = null, dagSig = "", booted = false;
  let nodeStates = {}, appeared = {}, focus = null, flashIds = new Set();
  const esc = s => Board.esc(s);
  const now = () => performance.now();

  // --- sanitize the untrusted dag payload before layout/draw ---------------
  function sanitizeDag(dag) {
    if (!Array.isArray(dag)) return [];
    const nodes = dag
      .filter(n => n && typeof n.id === "string" && n.id)
      .map(n => ({
        id: n.id,
        title: typeof n.title === "string" ? n.title : "",
        deps: Array.isArray(n.deps) ? n.deps.filter(d => typeof d === "string") : [],
        schema: n.schema === true,
        produces: Array.isArray(n.produces) ? n.produces.filter(c => typeof c === "string") : [],
        consumes: Array.isArray(n.consumes) ? n.consumes.filter(c => typeof c === "string") : [],
      }));
    const ids = new Set(nodes.map(n => n.id));
    nodes.forEach(n => { n.deps = n.deps.filter(d => ids.has(d) && d !== n.id); });
    breakCycles(nodes);
    return nodes;
  }

  // Drop dep edges that form cycles (hand-edited boards) so the layered
  // layout's depth recursion always terminates.
  function breakCycles(nodes) {
    const deps = Object.fromEntries(nodes.map(n => [n.id, new Set(n.deps)]));
    const done = new Set();
    let progress = true;
    while (progress) {
      progress = false;
      nodes.forEach(n => {
        if (!done.has(n.id) && [...deps[n.id]].every(d => done.has(d))) {
          done.add(n.id); progress = true;
        }
      });
    }
    nodes.forEach(n => {
      if (!done.has(n.id)) n.deps = n.deps.filter(d => done.has(d)); // cut back-edges
    });
  }

  // --- diff polls -> rolling status-change feed ----------------------------
  function diffFeed(entries) {
    const t = now();
    flashIds = new Set();
    const cur = {};
    entries.forEach(e => { cur[e.id] = Board.safeStatus(e.status); });
    if (prev !== null) {
      Object.keys(cur).forEach(id => {
        if (!(id in prev)) {
          pushFeed(`+ ${id} added (${cur[id]})`, "out", t);
        } else if (prev[id] !== cur[id]) {
          pushFeed(`${id}: ${prev[id]} -> ${cur[id]}`, FEED_STYLE[cur[id]] || "cmd", t);
          flashIds.add(id);
          if (cur[id] === "dispatched") focus = { id, t };
        }
      });
      Object.keys(prev).forEach(id => {
        if (!(id in cur)) pushFeed(`- ${id} removed`, "warn", t);
      });
    } else if (entries.length) {
      pushFeed(`watching ${entries.length} board entr${entries.length === 1 ? "y" : "ies"}`, "out", t);
    }
    prev = cur;
  }

  function pushFeed(text, style, t) {
    const stamp = new Date().toTimeString().slice(0, 8);
    feed.push({ text: `${stamp} ${text}`, style });
    if (feed.length > FEED_MAX) feed = feed.slice(-FEED_MAX);
  }

  function renderFeed() {
    const html = feed.map(l => `<div class="ln ${l.style}">${esc(l.text)}</div>`).join("")
      || `<div class="ln out">polling /api/board every ${POLL_MS}ms…</div>`;
    if (termEl.innerHTML !== html) termEl.innerHTML = html;
  }

  function renderVault(tail) {
    const sec = (name, lines) => `<div class="v-head">${name}</div>` +
      ((Array.isArray(lines) && lines.length)
        ? lines.map(l => `<div class="v-ln">${esc(l)}</div>`).join("")
        : `<div class="v-ln dim">(empty)</div>`);
    const html = sec("DECISIONS", tail && tail.decisions) + sec("ISSUES", tail && tail.issues);
    if (vaultEl.innerHTML !== html) vaultEl.innerHTML = html;
  }

  // --- graph state ----------------------------------------------------------
  function updateGraph(dag, entries) {
    const t = now();
    const sig = JSON.stringify(dag.map(n => [n.id, n.deps, n.produces, n.consumes]));
    if (sig !== dagSig) { Graph.init(dag); dagSig = sig; }
    const byId = {};
    entries.forEach(e => { byId[e.id] = e; });
    dag.forEach(n => {
      const st = NODE_STATE[Board.safeStatus(byId[n.id] && byId[n.id].status)] || "todo";
      if (appeared[n.id] === undefined) appeared[n.id] = t;
      if (!nodeStates[n.id] || nodeStates[n.id].state !== st) {
        nodeStates[n.id] = { state: st, since: t };
      }
    });
    Object.keys(nodeStates).forEach(id => {       // drop removed nodes
      if (!dag.some(n => n.id === id)) { delete nodeStates[id]; delete appeared[id]; }
    });
  }

  async function poll() {
    try {
      const r = await fetch("/api/board", { cache: "no-store" });
      const data = await r.json();
      const entries = Array.isArray(data.entries) ? data.entries.filter(
        e => e && typeof e.id === "string" && e.id) : [];
      diffFeed(entries);
      if (data.error) pushFeed(`board read error: ${data.error}`, "err", now());
      updateGraph(sanitizeDag(data.dag), entries);
      Board.renderEntries(entries, flashIds);
      renderFeed();
      renderVault(data.vault_tail);
      document.getElementById("caption").classList.toggle("show", !entries.length);
    } catch (err) {
      pushFeed(`poll failed: ${err.message}`, "err", now());
      renderFeed();
    }
  }

  function frame() {
    Graph.draw(now(), { nodeStates, appeared, focus });
    const sec = Math.floor(now() / 1000);
    document.getElementById("clock").textContent =
      String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0");
    requestAnimationFrame(frame);
  }

  function boot() {
    if (booted) return;
    booted = true;
    document.body.classList.add("live");
    document.getElementById("title-card").classList.add("hidden");
    document.getElementById("vault-pane").classList.remove("hidden");
    document.getElementById("runlabel").textContent = "live · polling 1.5s";
    document.getElementById("caption").textContent = "awaiting board entries — cairn board add …";
    termEl = document.getElementById("term");
    vaultEl = document.getElementById("vault");
    Board.init();
    Graph.init([]);
    poll();
    setInterval(poll, POLL_MS);
    requestAnimationFrame(frame);
    window.MC_READY = true;
  }

  return { boot };
})();

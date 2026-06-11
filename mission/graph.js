/* Canvas DAG renderer — layered topo layout, spring entrances, status states.
   Pure function of (t): every animation derives from event age, so seek(t) is
   deterministic for frame capture. */
"use strict";

const Graph = (() => {
  const SPRING_MS = 650;
  let nodes = [], edges = [], cEdges = [], pos = {}, canvas, ctx, dpr = 1;

  // critically-damped spring 0->1, closed form
  function spring(age) {
    if (age <= 0) return 0;
    const x = Math.min(age / SPRING_MS, 1.6);
    const w = 8.2;
    return 1 - Math.exp(-w * x) * (1 + w * x) * (1 - 0.06 * Math.sin(11 * x));
  }
  const clamp01 = v => Math.max(0, Math.min(1, v));

  function layout(dag) {
    nodes = dag.map(n => ({ ...n }));
    const depth = {};
    const byId = Object.fromEntries(nodes.map(n => [n.id, n]));
    const d = id => depth[id] !== undefined ? depth[id]
      : (depth[id] = (byId[id].deps.length ? Math.max(...byId[id].deps.map(d2 => d(d2))) + 1 : 0));
    nodes.forEach(n => d(n.id));
    const levels = {};
    nodes.forEach(n => (levels[depth[n.id]] = levels[depth[n.id]] || []).push(n));
    const L = Object.keys(levels).length;
    const W = canvas.width / dpr, H = canvas.height / dpr;
    const padX = 110, padTop = 96, padBot = 110;
    const rowH = (H - padTop - padBot) / Math.max(L - 1, 1);
    // Barycenter crossing-minimization: 4 top-down sweeps ordering each level
    // by the mean x-index of parents (then a bottom-up pass using children).
    const order = lv => levels[lv].map(n => n.id);
    const idx = {};
    for (let lv = 0; lv < L; lv++) order(lv).forEach((id, i) => idx[id] = i);
    const children = {};
    nodes.forEach(n => n.deps.forEach(d2 => (children[d2] = children[d2] || []).push(n.id)));
    for (let pass = 0; pass < 4; pass++) {
      for (let lv = 1; lv < L; lv++) {
        levels[lv].sort((a, b) => bary(a.deps) - bary(b.deps));
        levels[lv].forEach((n, i) => idx[n.id] = i);
      }
      for (let lv = L - 2; lv >= 0; lv--) {
        levels[lv].sort((a, b) => bary(children[a.id] || []) - bary(children[b.id] || []));
        levels[lv].forEach((n, i) => idx[n.id] = i);
      }
    }
    function bary(ids) {
      if (!ids.length) return 0;
      return ids.reduce((s, id) => s + (idx[id] ?? 0), 0) / ids.length;
    }
    Object.entries(levels).forEach(([lv, ns]) => {
      const y = padTop + rowH * lv;
      const span = W - padX * 2;
      ns.forEach((n, i) => {
        const x = ns.length === 1 ? W / 2 : padX + (span / (ns.length - 1)) * i;
        pos[n.id] = { x, y };
      });
    });
    edges = [];
    nodes.forEach(n => n.deps.forEach(dep => edges.push({ from: dep, to: n.id })));
  }

  function init(dag) {
    canvas = document.getElementById("graph");
    dpr = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * dpr;
    canvas.height = canvas.clientHeight * dpr;
    ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    layout(dag);
    cEdges = GraphFX.contractEdges(dag);
  }

  // state = {nodeStates, appeared, focus: {id, t} | null}
  function draw(t, state) {
    const W = canvas.width / dpr, H = canvas.height / dpr;
    ctx.clearRect(0, 0, W, H);
    const stOf = id => state.nodeStates[id]?.state;
    const active = id => ["dispatched", "in-progress"].includes(stOf(id));

    // 1) dependency edges (structure — quiet, with arrowheads)
    edges.forEach(e => {
      const a = pos[e.from], b = pos[e.to];
      const ta = state.appeared[e.to];
      if (ta === undefined) return;
      const k = clamp01((t - ta - 120) / 420);
      if (k <= 0) return;
      const hot = active(e.to);
      const done = stOf(e.from) === "merged" && stOf(e.to) === "merged";
      const col = done ? "rgba(63,185,80,.30)" : hot ? "rgba(240,136,62,.55)" : "rgba(76,86,96,.45)";
      ctx.strokeStyle = col;
      ctx.lineWidth = hot ? 2 : 1.3;
      ctx.beginPath();
      const my = (a.y + b.y) / 2;
      ctx.moveTo(a.x, a.y + 27);
      const ex = a.x + (b.x - a.x) * k, ey = a.y + 27 + (b.y - 27 - (a.y + 27)) * k;
      ctx.bezierCurveTo(a.x, my, b.x, my, ex, k === 1 ? b.y - 34 : ey);
      ctx.stroke();
      if (k === 1) GraphFX.arrowhead(ctx, b.x, b.y - 27, col);
    });

    // 2) data-contract edges (the WHY — labeled, amber, flowing when active)
    cEdges.forEach(e => {
      if (state.appeared[e.from] === undefined || state.appeared[e.to] === undefined) return;
      if (clamp01((t - state.appeared[e.to] - 200) / 420) <= 0) return;
      GraphFX.drawContractEdge(ctx, pos[e.from], pos[e.to], e.label, active(e.to), t);
    });

    // nodes
    nodes.forEach(n => {
      const ta = state.appeared[n.id];
      if (ta === undefined) return;
      const s = spring(t - ta);
      if (s <= 0.01) return;
      const st = state.nodeStates[n.id] || { state: "todo", since: ta };
      const age = t - st.since;
      const { x, y } = pos[n.id];
      const w = 168, h = 52;
      ctx.save();
      ctx.translate(x, y);
      let scale = 0.6 + 0.4 * s;
      if (st.state === "merged") scale *= 1 + 0.10 * Math.exp(-age / 260); // land pop
      ctx.scale(scale, scale);
      ctx.globalAlpha = clamp01(s * 1.2);

      // glow for active states
      if (st.state === "in-progress" || st.state === "dispatched") {
        const pulse = 0.5 + 0.5 * Math.sin(t / 300 + n.id.length);
        ctx.shadowColor = `rgba(240,136,62,${0.28 + 0.22 * pulse})`;
        ctx.shadowBlur = 26;
      } else if (st.state === "merged" && age < 900) {
        ctx.shadowColor = `rgba(63,185,80,${0.55 * Math.exp(-age / 500)})`;
        ctx.shadowBlur = 30;
      }

      // card
      ctx.fillStyle = st.state === "merged" ? "#16211a" : "#1c2128";
      ctx.strokeStyle = st.state === "merged" ? "rgba(63,185,80,.55)"
        : st.state === "in-progress" ? "rgba(240,136,62,.65)"
        : st.state === "dispatched" ? "rgba(210,153,34,.55)" : "#30363d";
      ctx.lineWidth = 1.4;
      roundRect(ctx, -w / 2, -h / 2, w, h, 9);
      ctx.fill(); ctx.stroke();
      ctx.shadowBlur = 0;

      // status dot
      const dot = { todo: "#576069", dispatched: "#d29922", "in-progress": "#f0883e", merged: "#3fb950" }[st.state];
      ctx.fillStyle = dot;
      ctx.beginPath(); ctx.arc(-w / 2 + 16, 0, 4.4, 0, 7); ctx.fill();

      // text
      ctx.fillStyle = "#e6edf3";
      ctx.font = "600 13.5px ui-monospace, Menlo, monospace";
      ctx.fillText(n.id, -w / 2 + 30, -3);
      ctx.fillStyle = "#768390";
      ctx.font = "11.5px -apple-system, sans-serif";
      ctx.fillText(truncate(n.title, 22), -w / 2 + 30, 13);

      // schema badge
      if (n.schema) {
        ctx.fillStyle = "rgba(216,145,95,.16)";
        ctx.strokeStyle = "rgba(216,145,95,.55)";
        roundRect(ctx, w / 2 - 24, -h / 2 + 7, 16, 14, 4);
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = "#d8915f";
        ctx.font = "700 9px ui-monospace, monospace";
        ctx.fillText("S", w / 2 - 19, -h / 2 + 17.5);
      }
      ctx.restore();
    });

    // 3) callout sidenote on the focused (just-dispatched) node — the WHY card
    if (state.focus && pos[state.focus.id]) {
      const node = nodes.find(n => n.id === state.focus.id);
      GraphFX.drawCallout(ctx, node, pos[state.focus.id], t - state.focus.t, W);
    }
  }

  function roundRect(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }
  const truncate = (s, n) => s.length > n ? s.slice(0, n - 1) + "…" : s;

  return { init, draw };
})();

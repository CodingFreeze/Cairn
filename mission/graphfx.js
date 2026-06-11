/* Graph effects layer — schema-contract edges with labels, and the live
   callout sidenote explaining WHY the focused node connects (deps + contracts). */
"use strict";

const GraphFX = (() => {
  // contract edges: producer -> consumer per shared contract name
  function contractEdges(dag) {
    const producers = {};
    dag.forEach(n => (n.produces || []).forEach(c => producers[c] = n.id));
    const out = [];
    dag.forEach(n => (n.consumes || []).forEach(c => {
      const p = producers[c];
      if (p && p !== n.id) out.push({ from: p, to: n.id, label: c });
    }));
    return out;
  }

  function drawContractEdge(ctx, a, b, label, active, t) {
    const grad = ctx.createLinearGradient(a.x, a.y, b.x, b.y);
    grad.addColorStop(0, active ? "rgba(240,136,62,.85)" : "rgba(216,145,95,.34)");
    grad.addColorStop(1, active ? "rgba(216,145,95,.55)" : "rgba(216,145,95,.16)");
    ctx.strokeStyle = grad;
    ctx.lineWidth = active ? 2.4 : 1.6;
    ctx.setLineDash([7, 5]);
    if (active) ctx.lineDashOffset = -(t / 40) % 12; // flowing dashes on active contracts
    const my = (a.y + b.y) / 2;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y + 27);
    ctx.bezierCurveTo(a.x, my, b.x, my, b.x, b.y - 27);
    ctx.stroke();
    ctx.setLineDash([]);
    // label chip at curve midpoint
    const mx = (a.x + b.x) / 2, myy = my + (b.y - a.y) * 0.02;
    ctx.font = "600 10.5px ui-monospace, Menlo, monospace";
    const w = ctx.measureText(label).width + 16;
    ctx.fillStyle = active ? "rgba(45,32,22,.96)" : "rgba(28,33,40,.92)";
    ctx.strokeStyle = active ? "rgba(240,136,62,.7)" : "rgba(216,145,95,.35)";
    ctx.lineWidth = 1;
    rr(ctx, mx - w / 2, myy - 9, w, 18, 9);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = active ? "#f0ab74" : "#b98a66";
    ctx.fillText(label, mx - w / 2 + 8, myy + 3.5);
  }

  function arrowhead(ctx, x, y, color) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(x, y); ctx.lineTo(x - 4.5, y - 8); ctx.lineTo(x + 4.5, y - 8);
    ctx.closePath(); ctx.fill();
  }

  // callout card anchored near the focused node
  function drawCallout(ctx, node, p, age, W) {
    const alpha = Math.min(1, age / 250) * (age > 3600 ? Math.max(0, 1 - (age - 3600) / 500) : 1);
    if (alpha <= 0.01) return;
    const lines = [];
    if (node.deps.length) lines.push(`after ${node.deps.join(" · ")}`);
    if ((node.consumes || []).length) lines.push(`reads  ${node.consumes.join(", ")}`);
    if ((node.produces || []).length) lines.push(`defines ${node.produces.join(", ")}`);
    if (!lines.length) lines.push("no upstream — starts immediately");
    const w = 250, h = 34 + lines.length * 19;
    const left = p.x + 110 + w < W ? p.x + 102 : p.x - 102 - w; // flip side near edge
    const top = p.y - h / 2;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = "rgba(22,27,34,.97)";
    ctx.strokeStyle = "rgba(216,145,95,.5)";
    ctx.lineWidth = 1.2;
    rr(ctx, left, top, w, h, 10);
    ctx.fill(); ctx.stroke();
    // connector tick
    ctx.strokeStyle = "rgba(216,145,95,.5)";
    ctx.beginPath();
    const cx = left > p.x ? left : left + w;
    ctx.moveTo(p.x + (left > p.x ? 86 : -86), p.y); ctx.lineTo(cx, p.y); ctx.stroke();
    ctx.fillStyle = "#e6edf3";
    ctx.font = "700 12.5px -apple-system, sans-serif";
    ctx.fillText(`${node.id} — ${node.title}`, left + 14, top + 21);
    ctx.font = "11.5px ui-monospace, Menlo, monospace";
    lines.forEach((ln, i) => {
      ctx.fillStyle = i === 0 ? "#8b949e" : "#b98a66";
      ctx.fillText(ln, left + 14, top + 41 + i * 19);
    });
    ctx.restore();
  }

  function rr(c, x, y, w, h, r) {
    c.beginPath();
    c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
  }

  return { contractEdges, drawContractEdge, drawCallout, arrowhead, rr };
})();

"""Renderer JS for the spec-graph HTML view (kept separate so spec_html.py and
the CSS module each stay under the 300-line functional cap).

Top-down layered DAG (rank = longest dependency depth), orthogonal elbow edges,
Factory-sober dark palette with accent reserved for the data-contract layer:
[SCHEMA] tickets are badged, schema-dependency edges (producer -> consumer of a
contract) are drawn in accent, and the longest schema chain — the "lock-first"
critical path — is highlighted. Deterministic: no Date/random.
"""

JS = r"""
(function () {
  var DATA = JSON.parse(document.getElementById('cairn-spec-data').textContent || '[]');
  var byId = Object.create(null);
  DATA.forEach(function (n) { byId[n.id] = n; });

  // ---- rank = longest dependency depth from a root (memoized, cycle-guarded) ----
  var depth = Object.create(null);
  function rank(id, seen) {
    if (depth[id] != null) return depth[id];
    seen = seen || Object.create(null);
    if (seen[id]) return 0;
    seen[id] = true;
    var n = byId[id], d = 0;
    (n && n.depends_on || []).forEach(function (p) { if (byId[p]) d = Math.max(d, rank(p, seen) + 1); });
    depth[id] = d; return d;
  }
  DATA.forEach(function (n) { rank(n.id); });

  // ---- data-contract layer: producer index + schema edges (producer -> consumer) ----
  var producers = Object.create(null);   // contract -> [ids that produce it]
  DATA.forEach(function (n) {
    (n.produces || []).forEach(function (c) { (producers[c] = producers[c] || []).push(n.id); });
  });
  var schemaPair = Object.create(null);  // "p>c" -> true when c consumes a contract p produces
  DATA.forEach(function (n) {
    (n.consumes || []).forEach(function (c) {
      (producers[c] || []).forEach(function (p) { if (p !== n.id) schemaPair[p + '>' + n.id] = true; });
    });
  });
  function isSchemaNode(n) { return !!n.schema || (n.produces || []).length > 0; }

  // ---- union of edges (depends_on ∪ schema), classified ----
  var edges = [], eseen = Object.create(null);
  function addEdge(p, c) {
    if (!byId[p] || !byId[c] || p === c) return;
    var k = p + '>' + c; if (eseen[k]) return; eseen[k] = true;
    edges.push({ p: p, c: c, schema: !!schemaPair[k] });
  }
  DATA.forEach(function (n) { (n.depends_on || []).forEach(function (p) { addEdge(p, n.id); }); });
  Object.keys(schemaPair).forEach(function (k) { var s = k.split('>'); addEdge(s[0], s[1]); });

  // ---- lock-first schema chain = longest path over schema edges ----
  var sadj = Object.create(null);
  edges.forEach(function (e) { if (e.schema) (sadj[e.p] = sadj[e.p] || []).push(e.c); });
  var chainLen = Object.create(null), chainNext = Object.create(null);
  function clen(id, seen) {
    if (chainLen[id] != null) return chainLen[id];
    seen = seen || Object.create(null); if (seen[id]) return 0; seen[id] = true;
    var best = 0, nx = null;
    (sadj[id] || []).forEach(function (c) { var v = clen(c, seen) + 1; if (v > best) { best = v; nx = c; } });
    chainLen[id] = best; chainNext[id] = nx; return best;
  }
  DATA.forEach(function (n) { clen(n.id); });
  var chainNodes = Object.create(null), chainEdges = Object.create(null), best = -1, head = null;
  DATA.forEach(function (n) { if (chainLen[n.id] > best && isSchemaNode(n)) { best = chainLen[n.id]; head = n.id; } });
  for (var cur = head; cur != null && chainNext[cur] != null; cur = chainNext[cur]) {
    chainNodes[cur] = true; chainNodes[chainNext[cur]] = true; chainEdges[cur + '>' + chainNext[cur]] = true;
  }
  if (head != null && best > 0) chainNodes[head] = true;

  // ---- top-down layered layout (rows by rank, centered, deterministic) ----
  var NH = 46, ROWGAP = 78, COLGAP = 34, PAD = 60;
  function cleanTitle(n) {
    var t = n.title || '';
    var re = new RegExp('^\\s*' + n.id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*[\\u2014:\\-]\\s*');
    return (t.replace(re, '') || n.id);
  }
  function nodeLabel(n) { var s = cleanTitle(n); return s.length > 22 ? s.slice(0, 21) + '…' : s; }
  function nodeW(n) { return Math.max(112, (n.id.length + nodeLabel(n).length + 1) * 7.6 + 26); }
  var rows = Object.create(null);
  DATA.forEach(function (n) { (rows[depth[n.id]] = rows[depth[n.id]] || []).push(n.id); });
  var pos = Object.create(null);
  Object.keys(rows).sort(function (a, b) { return a - b; }).forEach(function (r) {
    var ids = rows[r].sort(), total = 0;
    ids.forEach(function (id) { total += nodeW(byId[id]) + COLGAP; });
    total -= COLGAP;
    var x = -total / 2;
    ids.forEach(function (id) { var w = nodeW(byId[id]); pos[id] = { x: x, y: r * (NH + ROWGAP), w: w }; x += w + COLGAP; });
  });

  var SVGNS = ['ht', 'tp:', '//www.w3.org/2000/svg'].join('');
  var svg = document.getElementById('graph');
  function mk(t, a) { var e = document.createElementNS(SVGNS, t); for (var k in a) e.setAttribute(k, a[k]); return e; }
  var gE = mk('g', {}), gN = mk('g', {}); svg.appendChild(gE); svg.appendChild(gN);

  // right margin for routing rank-skipping edges out of the node column (Factory-style)
  var layoutMaxX = -1e9;
  DATA.forEach(function (n) { var p = pos[n.id]; if (p) layoutMaxX = Math.max(layoutMaxX, p.x + p.w); });

  // ---- orthogonal elbow edges (parent bottom -> child top); skip-edges hug a side lane ----
  var lane = 0, skipMaxX = layoutMaxX;
  edges.sort(function (a, b) { return (a.p + a.c < b.p + b.c) ? -1 : 1; }).forEach(function (e) {
    var a = pos[e.p], b = pos[e.c]; if (!a || !b) return;
    var sx = a.x + a.w / 2, sy = a.y + NH, tx = b.x + b.w / 2, ty = b.y;
    var crit = chainEdges[e.p + '>' + e.c];
    var cls = crit ? 'critEdge' : (e.schema ? 'schemaEdge' : 'depEdge');
    var d;
    if (depth[e.c] - depth[e.p] > 1) {           // skip edge: route out to the right lane
      var lx = layoutMaxX + 30 + (lane++ % 5) * 18; skipMaxX = Math.max(skipMaxX, lx);
      d = 'M' + sx + ',' + sy + ' L' + sx + ',' + (sy + 22) + ' L' + lx + ',' + (sy + 22)
        + ' L' + lx + ',' + (ty - 22) + ' L' + tx + ',' + (ty - 22) + ' L' + tx + ',' + ty;
    } else {                                       // adjacent rank: simple mid-Y elbow
      var midY = sy + (ty - sy) / 2;
      d = 'M' + sx + ',' + sy + ' L' + sx + ',' + midY + ' L' + tx + ',' + midY + ' L' + tx + ',' + ty;
    }
    gE.appendChild(mk('path', { d: d, 'class': 'edge ' + cls, 'data-kind': e.schema ? 'schema' : 'dep',
      'marker-end': 'url(#' + (crit ? 'arrowC' : (e.schema ? 'arrowS' : 'arrowD')) + ')' }));
  });

  // ---- nodes ----
  var STATUS = { todo: '#7d8590', dispatched: '#d8915f', 'in-progress': '#d8915f',
    'pr-open': '#539bf5', merged: '#57ab5a', blocked: '#e5534b' };
  DATA.forEach(function (n) {
    var p = pos[n.id]; if (!p) return;
    var sch = isSchemaNode(n), crit = chainNodes[n.id];
    var g = mk('g', { transform: 'translate(' + p.x + ',' + p.y + ')', 'class': 'node'
      + (sch ? ' schema' : '') + (crit ? ' crit' : ''), 'data-status': n.status });
    g.appendChild(mk('rect', { width: p.w, height: NH, rx: 7, 'class': 'card' }));
    if (sch) g.appendChild(mk('rect', { width: p.w, height: 3, rx: 1.5, 'class': 'schemaBar' }));
    g.appendChild(mk('circle', { cx: 13, cy: NH / 2, r: 4, fill: STATUS[n.status] || '#7d8590' }));
    var label = mk('text', { x: 26, y: NH / 2 - 3, 'class': 'nid' }); label.textContent = n.id;
    var ttl = mk('text', { x: 26, y: NH / 2 + 11, 'class': 'ntitle' }); ttl.textContent = nodeLabel(n);
    g.appendChild(label); g.appendChild(ttl);
    if (sch) { var bd = mk('text', { x: p.w - 9, y: 14, 'class': 'badge' }); bd.textContent = 'SCHEMA'; g.appendChild(bd); }
    g.addEventListener('click', function () { openDrawer(n); });
    gN.appendChild(g);
  });

  // ---- fit-to-content viewBox ----
  var minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  DATA.forEach(function (n) { var p = pos[n.id]; if (!p) return;
    minX = Math.min(minX, p.x); minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x + p.w); maxY = Math.max(maxY, p.y + NH); });
  maxX = Math.max(maxX, skipMaxX + 12);
  if (minX > maxX) { minX = 0; minY = 0; maxX = 600; maxY = 400; }
  var vb = { x: minX - PAD, y: minY - PAD, w: (maxX - minX) + 2 * PAD, h: (maxY - minY) + 2 * PAD, s: 1 };
  var home = { x: vb.x, y: vb.y, w: vb.w, h: vb.h };
  function apply() { svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + (vb.w / vb.s) + ' ' + (vb.h / vb.s)); }
  apply();
  var drag = null;
  svg.addEventListener('mousedown', function (e) { drag = { x: e.clientX, y: e.clientY, ox: vb.x, oy: vb.y }; });
  window.addEventListener('mousemove', function (e) { if (!drag) return;
    vb.x = drag.ox - (e.clientX - drag.x) / vb.s; vb.y = drag.oy - (e.clientY - drag.y) / vb.s; apply(); });
  window.addEventListener('mouseup', function () { drag = null; });
  svg.addEventListener('wheel', function (e) { e.preventDefault();
    vb.s = Math.min(4, Math.max(0.2, vb.s * (e.deltaY < 0 ? 1.1 : 0.9))); apply(); }, { passive: false });
  document.getElementById('fit').addEventListener('click', function () {
    vb.x = home.x; vb.y = home.y; vb.w = home.w; vb.h = home.h; vb.s = 1; apply(); });

  // ---- status filter chips + schema-chain focus ----
  var off = Object.create(null), focus = false;
  function relabel() {
    Array.prototype.forEach.call(gN.childNodes, function (g) {
      var st = g.getAttribute('data-status'), hidden = off[st] === true;
      var dim = focus && g.className.baseVal.indexOf('crit') < 0;
      g.style.opacity = hidden ? 0.08 : (dim ? 0.22 : 1);
    });
    Array.prototype.forEach.call(gE.childNodes, function (p) {
      p.style.opacity = focus && p.className.baseVal.indexOf('critEdge') < 0 ? 0.12 : '';
    });
  }
  var bar = document.getElementById('chips'), seen = Object.create(null);
  DATA.forEach(function (n) { seen[n.status] = true; });
  Object.keys(seen).sort().forEach(function (st) {
    var c = document.createElement('button'); c.className = 'chip on'; c.textContent = st;
    c.style.setProperty('--c', STATUS[st] || '#7d8590');
    c.addEventListener('click', function () { off[st] = !off[st]; c.classList.toggle('on'); relabel(); });
    bar.appendChild(c);
  });
  var fc = document.getElementById('focus');
  if (best > 0) fc.addEventListener('click', function () { focus = !focus; fc.classList.toggle('on'); relabel(); });
  else fc.style.display = 'none';

  // ---- drawer ----
  function list(arr) { return (arr && arr.length) ? arr.join(', ') : '(none)'; }
  function openDrawer(n) {
    document.getElementById('d-id').textContent = n.id;
    document.getElementById('d-title').textContent = cleanTitle(n);
    var sb = document.getElementById('d-status'); sb.textContent = n.status;
    sb.style.background = (STATUS[n.status] || '#7d8590') + '22'; sb.style.color = STATUS[n.status] || '#7d8590';
    sb.style.border = '1px solid ' + (STATUS[n.status] || '#7d8590');
    var badge = document.getElementById('d-schema');
    badge.style.display = isSchemaNode(n) ? 'inline-block' : 'none';
    document.getElementById('d-produces').textContent = list(n.produces);
    document.getElementById('d-consumes').textContent = list(n.consumes);
    document.getElementById('d-deps').textContent = list(n.depends_on);
    document.getElementById('d-spec').textContent = n.spec || '(no spec text)';
    document.getElementById('drawer').classList.add('open');
  }
  document.getElementById('d-close').addEventListener('click', function () {
    document.getElementById('drawer').classList.remove('open'); });
})();
"""

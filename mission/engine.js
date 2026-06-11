/* Replay engine — state is a pure function of t. window.MC.seek(ms) renders any
   frame deterministically (capture); MC.play() runs realtime (preview). */
"use strict";

const MC = (() => {
  let data, termEvents = [], playing = false, t0 = 0;
  const $ = id => document.getElementById(id);

  function computeState(t) {
    const nodeStates = {}, appeared = {};
    let scene = "title", caption = null, fileText = null, focus = null;
    for (const e of data.events) {
      if (e.t > t) break;
      switch (e.type) {
        case "node":
          if (appeared[e.id] === undefined) appeared[e.id] = e.t;
          nodeStates[e.id] = { state: e.state, since: e.t };
          // sidenote follows the latest dispatch/in-progress — the node whose
          // "why it connects" (deps + contracts) matters right now
          if (e.state === "dispatched") focus = { id: e.id, t: e.t };
          break;
        case "scene": scene = e.name; break;
        case "caption": caption = { text: e.text, t: e.t }; break;
        case "filecard": fileText = e.text; break;
      }
    }
    return { nodeStates, appeared, scene, caption, fileText, focus };
  }

  function render(t) {
    const s = computeState(t);

    Graph.draw(t, s);
    Term.render(t, termEvents);
    Board.render(t, data.dag, s.nodeStates);

    // clock
    const sec = Math.floor(t / 1000);
    $("clock").textContent =
      String(Math.floor(sec / 60)).padStart(2, "0") + ":" + String(sec % 60).padStart(2, "0");

    // caption
    const cap = $("caption");
    if (s.caption && s.caption.text && t - s.caption.t < 4200) {
      cap.textContent = s.caption.text;
      cap.classList.add("show");
    } else cap.classList.remove("show");

    // overlays per scene
    show("title-card", s.scene === "title");
    show("kill-card", s.scene === "kill" && !s.fileTextShown);
    show("end-card", s.scene === "endcard");

    // kill choreography: shake on entry, then desaturate, then filecard
    const stage = $("stage");
    const killEv = data.events.find(e => e.type === "scene" && e.name === "kill");
    if (killEv && t >= killEv.t && s.scene === "kill") {
      stage.classList.toggle("shake", t - killEv.t < 450);
      stage.classList.add("dead");
      const fc = data.events.find(e => e.type === "filecard");
      const fcOn = fc && t >= fc.t;
      show("kill-card", !fcOn);
      show("file-card", fcOn);
      if (fcOn) $("file-body").textContent = fc.text;
    } else {
      stage.classList.remove("dead", "shake");
      show("file-card", false);
    }
  }

  const show = (id, on) => $(id).classList.toggle("hidden", !on);

  function seek(ms) { render(Math.max(0, Math.min(ms, data.duration_ms))); }

  function play() {
    playing = true; t0 = performance.now();
    (function frame(now) {
      if (!playing) return;
      const t = now - t0;
      render(t);
      if (t < data.duration_ms) requestAnimationFrame(frame); else playing = false;
    })(performance.now());
  }

  async function boot() {
    // Mode switch: ?live=1 polls the local read-only API instead of a timeline.
    if (new URLSearchParams(location.search).get("live") === "1") {
      Live.boot();
      return;
    }
    data = await (await fetch("demo-events.json")).json();
    termEvents = data.events.filter(e => e.type === "term");
    Graph.init(data.dag); Term.init(); Board.init();
    render(0);
    window.MC_READY = true;
  }

  document.addEventListener("DOMContentLoaded", boot);
  window.addEventListener("keydown", e => {
    if (e.key === " " && !document.body.classList.contains("live")) play();
  });
  return { seek, play, duration: () => data.duration_ms };
})();
window.MC = MC;

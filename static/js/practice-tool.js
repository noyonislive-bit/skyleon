/*
 * Practice Lab — replica of the production video clipping tool.
 *
 *   Space  play / pause            N  cut (start / end a clip)      L  loop current segment
 *   click a clip to edit it (drag edges, [ / ] set start / end, Delete removes it)
 *
 * Shortcuts, N-key behaviour and speed steps come from the server config
 * (Admin → Practice lab → Tool settings) so they can match the production tool.
 */
(function () {
  "use strict";

  const root = document.querySelector(".pt-root");
  const dataEl = document.getElementById("practice-data");
  if (!root || !dataEl) return;
  const data = JSON.parse(dataEl.textContent);
  const cfg = data.config || {};
  const MODE = data.mode; // practice | reference
  const BASE_PPS = 10; // internal pixels per second scale
  // Zoom levels relative to "100%" — like the production tool, 100% shows the whole range.
  const ZOOMS = [0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8, 12, 16, 24, 32];
  const MIN_CLIP = 0.1;
  const FPS = cfg.frame_rate || 30;
  const SPEEDS = (cfg.speeds && cfg.speeds.length ? cfg.speeds : [1, 1.5, 2, 0.5]).map(Number);

  const $ = (sel) => root.querySelector(sel);
  const $$ = (sel) => Array.from(root.querySelectorAll(sel));
  const video = $("[data-video]");
  const stage = $("[data-stage]");
  const scroller = $("[data-scroll]");
  const inner = $("[data-inner]");
  const ruler = $("[data-ruler]");
  const track = $("[data-track]");
  const playhead = $("[data-playhead]");
  const handle = $("[data-playhead-handle]");
  const hint = $("[data-hint]");
  const uncoveredEl = $("[data-uncovered]");
  const zoomLabel = $("[data-zoom-label]");
  const speedBtn = $("[data-speed-label]");
  const loopBox = $("[data-loop]");
  const toastEl = $("[data-toast]");
  const timerEl = $("[data-timer]");
  const saveStatus = $("[data-save-status]");

  let lo = Number(data.task.rangeStart) || 0;
  let hi = Number(data.task.rangeEnd) || lo + 60;
  let uid = 0;
  const state = {
    clips: (data.clips || []).map((c) => ({ id: ++uid, start: Number(c[0]), end: Number(c[1]) })).filter((c) => c.end > c.start),
    selected: null,
    open: null, // toggle mode: start time of the clip being recorded
    zoom: 1,
    fitZoom: 1,
    speedIdx: 0,
    history: [],
    dirty: false,
    busy: false,
  };
  sortClips();

  // ── Helpers ────────────────────────────────────────────────────────────
  const pps = () => BASE_PPS * state.zoom;
  const xOf = (t) => (t - lo) * pps();
  const tOf = (x) => Math.min(hi, Math.max(lo, lo + x / pps()));
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const now = () => clamp(video.currentTime || lo, lo, hi);
  function mmss(t) {
    t = Math.max(0, Math.floor(t + 1e-6));
    return String(Math.floor(t / 60)).padStart(2, "0") + ":" + String(t % 60).padStart(2, "0");
  }
  function mmssExact(t) {
    const m = Math.floor(t / 60), s = t - m * 60;
    return String(m).padStart(2, "0") + ":" + s.toFixed(2).padStart(5, "0");
  }
  function sortClips() { state.clips.sort((a, b) => a.start - b.start); }
  function clipAt(t) { return state.clips.find((c) => t > c.start + 0.02 && t < c.end - 0.02); }
  function selectedClip() { return state.clips.find((c) => c.id === state.selected) || null; }
  function snapshot() {
    state.history.push(JSON.stringify(state.clips));
    if (state.history.length > 100) state.history.shift();
  }
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("is-visible");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toastEl.classList.remove("is-visible"), 2200);
  }
  function changed() {
    sortClips();
    state.dirty = true;
    renderClips();
    renderUncovered();
    scheduleSave();
  }

  // ── Video source ───────────────────────────────────────────────────────
  function loadSource() {
    const url = data.video.url;
    if (!url) {
      stage.classList.add("has-error");
      $("[data-stage-msg]").textContent = "This practice task has no video yet.";
      return;
    }
    const isHls = data.video.hls || /\.m3u8(\?|$)/.test(url);
    if (isHls && !video.canPlayType("application/vnd.apple.mpegurl")) {
      const s = document.createElement("script");
      s.src = "/static/vendor/hls.min.js";
      s.onload = () => {
        if (window.Hls && window.Hls.isSupported()) {
          const hls = new window.Hls();
          hls.loadSource(url);
          hls.attachMedia(video);
        } else stage.classList.add("has-error");
      };
      document.head.appendChild(s);
    } else {
      video.src = url;
    }
  }
  video.addEventListener("loadedmetadata", () => {
    if (isFinite(video.duration) && video.duration > 0) {
      if (!data.task.rangeEnd || hi > video.duration) hi = video.duration;
      if (lo >= hi) lo = 0;
    }
    if (video.currentTime < lo || video.currentTime > hi) video.currentTime = lo;
    fit();
  });
  video.addEventListener("error", () => stage.classList.add("has-error"));
  video.addEventListener("play", () => { stage.classList.add("is-playing"); tick(); });
  video.addEventListener("pause", () => { stage.classList.remove("is-playing"); updatePlayhead(); });
  video.addEventListener("seeked", updatePlayhead);
  video.addEventListener("click", () => act("play_pause"));

  function togglePlay() {
    if (video.paused) {
      if (video.currentTime >= hi - 0.05) video.currentTime = lo;
      video.play().catch(() => {});
    } else video.pause();
  }
  function seek(t) {
    video.currentTime = clamp(t, lo, hi);
    updatePlayhead();
    keepVisible(true);
  }

  // ── Playback loop ──────────────────────────────────────────────────────
  function tick() {
    const t = video.currentTime;
    if (t >= hi) { video.pause(); video.currentTime = hi; }
    if (loopBox.checked) {
      const seg = selectedClip() || clipAt(t - 0.05);
      if (seg && t >= seg.end) video.currentTime = seg.start;
    }
    updatePlayhead();
    if (state.open !== null) renderOpenClip();
    keepVisible(false);
    if (!video.paused) requestAnimationFrame(tick);
  }

  // ── Timeline rendering ─────────────────────────────────────────────────
  function contentWidth() { return Math.max(scroller.clientWidth, Math.ceil(xOf(hi)) + 24); }
  function renderAll() {
    inner.style.width = contentWidth() + "px";
    zoomLabel.textContent = Math.round((state.zoom / state.fitZoom) * 100) + "%";
    renderRuler();
    renderClips();
    renderUncovered();
    updatePlayhead();
  }
  function steps() {
    const opts = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
    const label = opts.find((s) => s * pps() >= 90) || 600;
    return { label, minor: label / 5 };
  }
  function renderRuler() {
    const { label, minor } = steps();
    const left = scroller.scrollLeft - 200, right = scroller.scrollLeft + scroller.clientWidth + 200;
    const t0 = Math.max(lo, tOf(Math.max(0, left))), t1 = Math.min(hi, tOf(right));
    const frag = document.createDocumentFragment();
    const first = Math.ceil((t0 - 1e-6) / minor) * minor;
    for (let t = first; t <= t1 + 1e-6; t += minor) {
      const isMajor = Math.abs(t / label - Math.round(t / label)) < 1e-6;
      const x = xOf(t);
      if (isMajor) {
        const lab = document.createElement("span");
        lab.className = "vp-tick-label";
        lab.style.left = x + "px";
        lab.textContent = label < 1 ? mmss(t) + (t % 1 ? ".5" : "") : mmss(t);
        const line = document.createElement("span");
        line.className = "vp-tick-major";
        line.style.left = x + "px";
        frag.append(lab, line);
      } else {
        const tk = document.createElement("span");
        tk.className = "vp-tick";
        tk.style.left = x + "px";
        frag.appendChild(tk);
      }
    }
    ruler.replaceChildren(frag);
  }
  function clipEl(c, n, extra) {
    const el = document.createElement("div");
    el.className = "vp-clip" + (extra ? " " + extra : "") + (c.id === state.selected ? " is-selected" : "");
    el.style.left = xOf(c.start) + 1 + "px";
    el.style.width = Math.max(4, xOf(c.end) - xOf(c.start) - 2) + "px";
    el.dataset.id = c.id;
    el.innerHTML = '<div class="vp-clip-title"></div><div class="vp-clip-time"></div>';
    el.firstChild.textContent = "Clip " + n;
    el.lastChild.textContent = mmss(c.start) + " - " + mmss(c.end);
    if (c.id === state.selected) {
      el.insertAdjacentHTML("beforeend", '<span class="vp-clip-handle is-start" data-edge="start"></span><span class="vp-clip-handle is-end" data-edge="end"></span>');
    }
    return el;
  }
  function renderClips() {
    const frag = document.createDocumentFragment();
    state.clips.forEach((c, i) => frag.appendChild(clipEl(c, i + 1)));
    track.replaceChildren(frag);
    renderOpenClip();
    updateHint();
  }
  function renderOpenClip() {
    let el = track.querySelector(".is-open");
    if (state.open === null) { if (el) el.remove(); return; }
    const t = now();
    const c = { id: -1, start: Math.min(state.open, t), end: Math.max(state.open, t) + 0.001 };
    const fresh = clipEl(c, state.clips.filter((x) => x.start < c.start).length + 1, "is-open");
    if (el) el.replaceWith(fresh); else track.appendChild(fresh);
  }
  function uncoveredRanges() {
    const gaps = [];
    let cur = lo;
    state.clips.forEach((c) => {
      if (c.start > cur + 0.05) gaps.push([cur, Math.min(c.start, hi)]);
      cur = Math.max(cur, c.end);
    });
    if (cur < hi - 0.05) gaps.push([cur, hi]);
    return gaps;
  }
  function renderUncovered() {
    const gaps = uncoveredRanges();
    uncoveredEl.classList.toggle("is-done", gaps.length === 0);
    uncoveredEl.textContent = gaps.length
      ? "Hands present but uncovered: " + mmss(gaps[0][0]) + "–" + mmss(gaps[gaps.length - 1][1])
      : "";
  }
  function updatePlayhead() {
    const x = xOf(now());
    playhead.style.left = x + "px";
    handle.style.left = (x < 10 ? -x : x > inner.clientWidth - 10 ? -(20 - (inner.clientWidth - x)) : -10) + "px";
  }
  function keepVisible(center) {
    const x = xOf(now()), vw = scroller.clientWidth, sl = scroller.scrollLeft;
    if (center && (x < sl || x > sl + vw)) scroller.scrollLeft = x - vw / 2;
    else if (!center && x > sl + vw * 0.9) scroller.scrollLeft = x - vw * 0.15;
    else if (!center && x < sl) scroller.scrollLeft = Math.max(0, x - vw * 0.1);
  }
  function updateHint() {
    const c = selectedClip();
    if (state.open !== null) {
      hint.innerHTML = "<strong>Recording clip…</strong> press N again at the end of the action";
    } else if (c) {
      const n = state.clips.indexOf(c) + 1;
      hint.innerHTML = "<strong>Editing Clip " + n + "</strong> · " + mmssExact(c.start) + " – " + mmssExact(c.end);
    } else hint.textContent = "Click a clip to start editing";
  }
  let rulerRaf = 0;
  scroller.addEventListener("scroll", () => {
    cancelAnimationFrame(rulerRaf);
    rulerRaf = requestAnimationFrame(renderRuler);
  });
  window.addEventListener("resize", () => {
    const rel = state.zoom / state.fitZoom;
    computeFit();
    if (Math.abs(rel - 1) < 1e-6) fit(); else renderAll();
  });

  // ── Zoom ───────────────────────────────────────────────────────────────
  function computeFit() {
    state.fitZoom = Math.max(0.01, (scroller.clientWidth - 24) / BASE_PPS / Math.max(1, hi - lo));
  }
  function setZoom(z) {
    const anchorT = now();
    const anchorOffset = xOf(anchorT) - scroller.scrollLeft;
    state.zoom = clamp(z, state.fitZoom * 0.5, state.fitZoom * 64);
    renderAll();
    scroller.scrollLeft = xOf(anchorT) - anchorOffset;
    renderRuler();
  }
  function zoomStep(dir) {
    const rel = state.zoom / state.fitZoom;
    const next = dir > 0 ? ZOOMS.find((s) => s > rel + 1e-6) : [...ZOOMS].reverse().find((s) => s < rel - 1e-6);
    setZoom((next || rel) * state.fitZoom);
  }
  function fit() { computeFit(); setZoom(state.fitZoom); scroller.scrollLeft = 0; renderRuler(); }
  scroller.addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) { e.preventDefault(); zoomStep(e.deltaY < 0 ? 1 : -1); }
    else if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { e.preventDefault(); scroller.scrollLeft += e.deltaY; }
  }, { passive: false });

  // ── Cutting ────────────────────────────────────────────────────────────
  function addClip(s, e) {
    // keep clips from overlapping: trim against neighbours
    state.clips.forEach((c) => {
      if (c.start <= s && c.end > s) s = c.end;
      if (c.start < e && c.start >= s) e = Math.min(e, c.start);
    });
    if (e - s < MIN_CLIP) { toast("Clip is too short or overlaps another clip."); return null; }
    snapshot();
    const clip = { id: ++uid, start: +s.toFixed(3), end: +e.toFixed(3) };
    state.clips.push(clip);
    return clip;
  }
  function cut() {
    const t = now();
    if ((cfg.cut_mode || "toggle") === "split") {
      const inside = clipAt(t);
      if (inside) {
        snapshot();
        state.clips.push({ id: ++uid, start: +t.toFixed(3), end: inside.end });
        inside.end = +t.toFixed(3);
      } else {
        const prevEnd = state.clips.filter((c) => c.end <= t + 1e-6).reduce((m, c) => Math.max(m, c.end), lo);
        if (!addClip(prevEnd, t)) return;
      }
      state.selected = null;
      changed();
      return;
    }
    // toggle mode
    if (state.open === null) {
      const inside = clipAt(t);
      if (inside) { toast("The playhead is inside Clip " + (state.clips.indexOf(inside) + 1) + "."); return; }
      state.open = t;
      state.selected = null;
      renderClips();
    } else {
      const s = Math.min(state.open, t), e = Math.max(state.open, t);
      state.open = null;
      addClip(s, e);
      changed();
    }
  }

  // ── Clip editing (select, drag edges) ──────────────────────────────────
  track.addEventListener("pointerdown", (e) => {
    const edge = e.target.closest("[data-edge]");
    const el = e.target.closest(".vp-clip");
    if (edge && el) { startEdgeDrag(e, Number(el.dataset.id), edge.dataset.edge); return; }
    if (el && !el.classList.contains("is-open")) {
      const c = state.clips.find((x) => x.id === Number(el.dataset.id));
      state.selected = c.id;
      renderClips();
      seek(c.start);
      return;
    }
    // empty track: deselect + seek
    state.selected = null;
    renderClips();
    startScrub(e);
  });
  function startEdgeDrag(e, id, edge) {
    e.preventDefault();
    const c = state.clips.find((x) => x.id === id);
    if (!c) return;
    snapshot();
    const idx = state.clips.indexOf(c);
    const minT = edge === "start" ? (idx > 0 ? state.clips[idx - 1].end : lo) : c.start + MIN_CLIP;
    const maxT = edge === "start" ? c.end - MIN_CLIP : (idx < state.clips.length - 1 ? state.clips[idx + 1].start : hi);
    const rect = inner.getBoundingClientRect();
    const move = (ev) => {
      const t = clamp(tOf(ev.clientX - rect.left), minT, maxT);
      c[edge] = +t.toFixed(3);
      video.currentTime = t;
      renderClips();
      updatePlayhead();
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); changed(); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  function startScrub(e) {
    e.preventDefault();
    const wasPlaying = !video.paused;
    video.pause();
    playhead.classList.add("is-dragging");
    const rect = inner.getBoundingClientRect();
    const move = (ev) => { video.currentTime = tOf(ev.clientX - rect.left); updatePlayhead(); if (state.open !== null) renderOpenClip(); };
    const up = () => {
      playhead.classList.remove("is-dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (wasPlaying) video.play().catch(() => {});
    };
    move(e);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }
  ruler.addEventListener("pointerdown", startScrub);
  handle.addEventListener("pointerdown", startScrub);

  function deleteSelected() {
    if (state.open !== null) { state.open = null; renderClips(); toast("Clip recording cancelled."); return; }
    const c = selectedClip();
    if (!c) { toast("Click a clip first, then Delete Clip."); return; }
    snapshot();
    state.clips = state.clips.filter((x) => x !== c);
    state.selected = null;
    changed();
  }
  function setEdge(edge) {
    const c = selectedClip();
    if (!c) { toast("Select a clip first."); return; }
    const t = now(), idx = state.clips.indexOf(c);
    const minT = edge === "start" ? (idx > 0 ? state.clips[idx - 1].end : lo) : c.start + MIN_CLIP;
    const maxT = edge === "start" ? c.end - MIN_CLIP : (idx < state.clips.length - 1 ? state.clips[idx + 1].start : hi);
    if (t < minT - 1e-6 || t > maxT + 1e-6) { toast("That would overlap another clip."); return; }
    snapshot();
    c[edge] = +t.toFixed(3);
    changed();
  }
  function selectRelative(dir) {
    if (!state.clips.length) return;
    const c = selectedClip();
    let idx = c ? state.clips.indexOf(c) + dir : (dir > 0 ? 0 : state.clips.length - 1);
    idx = clamp(idx, 0, state.clips.length - 1);
    state.selected = state.clips[idx].id;
    renderClips();
    seek(state.clips[idx].start);
  }
  function undo() {
    const prev = state.history.pop();
    if (!prev) { toast("Nothing to undo."); return; }
    state.clips = JSON.parse(prev);
    state.selected = null;
    changed();
  }

  // ── Speed, loop, source, realign ───────────────────────────────────────
  function cycleSpeed() {
    state.speedIdx = (state.speedIdx + 1) % SPEEDS.length;
    video.playbackRate = SPEEDS[state.speedIdx];
    speedBtn.textContent = "Speed " + SPEEDS[state.speedIdx] + "x";
  }
  speedBtn.textContent = "Speed " + SPEEDS[0] + "x";
  video.playbackRate = SPEEDS[0];
  $("[data-source]").addEventListener("change", () => {
    const t = video.currentTime, playing = !video.paused;
    video.load();
    video.addEventListener("loadedmetadata", () => { video.currentTime = t; if (playing) video.play(); }, { once: true });
  });
  function realign() {
    const t = now();
    video.currentTime = t;
    renderAll();
    keepVisible(true);
    toast("Video realigned with the timeline.");
  }

  // ── Persistence ────────────────────────────────────────────────────────
  const started = Date.now();
  let activeMs = 0, lastTick = Date.now();
  setInterval(() => {
    const t = Date.now();
    if (!document.hidden) activeMs += t - lastTick;
    lastTick = t;
    const s = Math.floor(activeMs / 1000);
    timerEl.textContent = String(Math.floor(s / 60)).padStart(2, "0") + ":" + String(s % 60).padStart(2, "0");
  }, 1000);
  const clipsPayload = () => state.clips.map((c) => [c.start, c.end]);
  function post(url, body, keepalive) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      keepalive: !!keepalive,
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.skyleon ? window.skyleon.csrfToken() : "" },
      body: JSON.stringify(body),
    }).then((r) => r.json().then((j) => { if (!r.ok) throw new Error(j.error || r.statusText); return j; }));
  }
  let saveTimer = 0;
  function scheduleSave() {
    if (!data.urls.save) { saveStatus.textContent = state.dirty ? "Unsaved changes" : ""; return; }
    saveStatus.textContent = "Saving…";
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 1200);
  }
  function saveNow(keepalive) {
    if (!data.urls.save || !state.dirty) return Promise.resolve();
    clearTimeout(saveTimer);
    return post(data.urls.save, { clips: clipsPayload(), timeSpent: Math.floor(activeMs / 1000) }, keepalive)
      .then(() => { state.dirty = false; saveStatus.textContent = "All changes saved"; })
      .catch(() => { saveStatus.textContent = "Not saved — check your connection"; });
  }
  window.addEventListener("pagehide", () => saveNow(true));
  window.addEventListener("beforeunload", (e) => {
    if (!data.urls.save && state.dirty) { e.preventDefault(); e.returnValue = ""; }
  });

  // ── Submit ─────────────────────────────────────────────────────────────
  function submit(goNext) {
    if (state.busy) return;
    if (state.open !== null) { toast("Finish the open clip first (press N), or press Delete to cancel it."); return; }
    if (!state.clips.length) { toast("Create at least one clip before submitting."); return; }
    const gaps = uncoveredRanges();
    if (MODE === "practice" && gaps.length && !window.confirm("Hands-present time is still uncovered (" + mmss(gaps[0][0]) + "–" + mmss(gaps[gaps.length - 1][1]) + "). Submit anyway?")) return;
    state.busy = true;
    video.pause();
    post(data.urls.submit, { clips: clipsPayload(), timeSpent: Math.floor(activeMs / 1000) })
      .then((res) => {
        state.dirty = false;
        saveStatus.textContent = "Submitted";
        if (MODE === "reference") {
          toast("Reference saved — " + res.clips.length + " clips.");
          if (goNext && data.urls.next) setTimeout(() => (location.href = data.urls.next), 600);
          return;
        }
        showResult(res, goNext);
      })
      .catch((err) => toast("Could not submit: " + err.message))
      .finally(() => (state.busy = false));
  }
  function showResult(res, goNext) {
    const m = res.metrics || {};
    const pass = res.passed;
    const metric = (v, label) => '<div class="pt-metric"><b>' + (v == null ? "—" : v + "%") + "</b><span>" + label + "</span></div>";
    const issues = (m.issues || []).slice(0, 6).map((i) => "<li>" + escapeHtml(i.text) + "</li>").join("");
    $("[data-result-body]").innerHTML =
      '<div class="pt-score"><div class="pt-score-ring" style="--p:' + Math.round(res.score) + ";--ring-color:" + (pass ? "#1f6e58" : "#c2410c") + '"><span>' + Math.round(res.score) + "%</span></div>" +
      "<div><span class=\"pt-pill " + (pass ? "is-pass" : "is-fail") + "\">" + (pass ? "Passed" : "Not passed yet") + "</span>" +
      '<p style="margin:8px 0 0">Passing score: ' + res.passingScore + "% · " + (m.clip_count || 0) + " clips" + (m.reference_count ? " (reference: " + m.reference_count + ")" : "") + "</p></div></div>" +
      '<div class="pt-metrics">' + metric(m.boundary_f1, "Boundary accuracy") + metric(m.mean_iou, "Clip overlap (IoU)") + metric(m.coverage, "Coverage") + "</div>" +
      (issues ? '<ul class="pt-issues">' + issues + "</ul>" : '<p style="margin:14px 0 0;color:#146c4b">No issues found — great work!</p>');
    const foot = $("[data-result-foot]");
    foot.innerHTML = "";
    const btn = (label, cls, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = "vp-fbtn " + cls; b.textContent = label; b.onclick = fn; foot.appendChild(b); };
    btn("View detailed result", "vp-fbtn-mint", () => (location.href = res.resultUrl));
    btn("Keep improving", "vp-fbtn-mint", () => closeModal($("#pt-result")));
    if (data.urls.next) btn(goNext ? "Next task →" : "Next task", "vp-fbtn-green", () => (location.href = data.urls.next));
    else btn("Back to Practice Lab", "vp-fbtn-green", () => (location.href = data.urls.back));
    openModal($("#pt-result"));
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  function navigate(dir) {
    const url = dir < 0 ? data.urls.prev : data.urls.next;
    if (!url) { toast(dir < 0 ? "This is the first task." : "This is the last task."); return; }
    if (!data.urls.save && state.dirty && !window.confirm("Leave without saving the reference?")) return;
    saveNow().finally(() => (location.href = url));
  }

  // ── Task error ─────────────────────────────────────────────────────────
  function sendTaskError() {
    if (!data.urls.taskError) { toast("Task Error is not used in reference mode."); closeModal($("#pt-task-error")); return; }
    const reason = (root.querySelector("input[name=pt-reason]:checked") || {}).value || "other";
    post(data.urls.taskError, { reason, comment: $("[data-error-comment]").value })
      .then(() => { closeModal($("#pt-task-error")); toast("Task error reported. Your trainer will review it."); })
      .catch(() => toast("Could not send the report."));
  }

  // ── Modals ─────────────────────────────────────────────────────────────
  let lastFocus = null;
  function openModal(m) { lastFocus = document.activeElement; m.hidden = false; const f = m.querySelector("button, input, textarea"); if (f) f.focus(); video.pause(); }
  function closeModal(m) { m.hidden = true; if (lastFocus && lastFocus.focus) lastFocus.blur(); }
  $$("[data-open]").forEach((b) => b.addEventListener("click", () => openModal($(b.dataset.open))));
  $$(".pt-modal").forEach((m) => {
    m.addEventListener("click", (e) => { if (e.target === m || e.target.closest("[data-close]")) closeModal(m); });
  });
  const openModalEl = () => $$(".pt-modal").find((m) => !m.hidden);

  // Shortcut list
  const labels = data.labels || {};
  const keyName = (k) => ({ " ": "Space", ArrowLeft: "←", ArrowRight: "→", ArrowUp: "↑", ArrowDown: "↓", Escape: "Esc", Backspace: "⌫", Delete: "Del" }[k] || (k.length === 1 ? k.toUpperCase() : k));
  $("[data-shortcut-table]").innerHTML = Object.keys(labels)
    .filter((a) => (cfg.shortcuts[a] || []).length)
    .map((a) => "<tr><td>" + escapeHtml(labels[a]) + "</td><td>" + cfg.shortcuts[a].map((k) => k.split("+").map((p) => '<span class="pt-kbd">' + escapeHtml(keyName(p || "+")) + "</span>").join("")).join(" ") + "</td></tr>")
    .join("");
  $("[data-cut-mode-note]").textContent = (cfg.cut_mode || "toggle") === "split"
    ? "N cuts at the playhead: each cut closes a clip that starts at the previous cut."
    : "N starts a clip at the playhead; press N again where the action ends to close it.";

  // ── Keyboard ───────────────────────────────────────────────────────────
  const bindings = {};
  Object.entries(cfg.shortcuts || {}).forEach(([action, keys]) => {
    (keys || []).forEach((k) => { bindings[normalize(k)] = action; });
  });
  function normalize(combo) {
    const parts = String(combo).split("+");
    let key = parts.pop();
    if (key === "" && combo.endsWith("+")) key = "+";
    const mods = parts.map((p) => p.toLowerCase()).sort();
    if (key.toLowerCase() === "space") key = " ";
    return mods.concat([key.length === 1 ? key.toLowerCase() : key.toLowerCase()]).join("+");
  }
  function eventCombo(e, withShift) {
    const mods = [];
    if (e.altKey) mods.push("alt");
    if (e.ctrlKey) mods.push("ctrl");
    if (e.metaKey) mods.push("meta");
    if (withShift && e.shiftKey) mods.push("shift");
    mods.sort();
    return mods.concat([e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase()]).join("+");
  }
  document.addEventListener("keydown", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" && e.target.type !== "checkbox" && e.target.type !== "radio" || tag === "textarea" || tag === "select" || e.target.isContentEditable) return;
    const modal = openModalEl();
    if (modal) { if (e.key === "Escape") closeModal(modal); return; }
    const action = bindings[eventCombo(e, true)] || (!e.ctrlKey && !e.metaKey && !e.altKey ? bindings[eventCombo(e, false)] : undefined);
    if (!action) return;
    e.preventDefault();
    act(action);
  });

  const actions = {
    play_pause: togglePlay,
    cut,
    loop: () => { loopBox.checked = !loopBox.checked; toast(loopBox.checked ? "Loop current segment: on" : "Loop current segment: off"); },
    delete_clip: deleteSelected,
    seek_back: () => seek(now() - 1),
    seek_forward: () => seek(now() + 1),
    seek_back_big: () => seek(now() - 5),
    seek_forward_big: () => seek(now() + 5),
    frame_back: () => { video.pause(); seek(now() - 1 / FPS); },
    frame_forward: () => { video.pause(); seek(now() + 1 / FPS); },
    set_start: () => setEdge("start"),
    set_end: () => setEdge("end"),
    prev_clip: () => selectRelative(-1),
    next_clip: () => selectRelative(1),
    speed: cycleSpeed,
    zoom_in: () => zoomStep(1),
    zoom_out: () => zoomStep(-1),
    zoom_fit: fit,
    undo,
    deselect: () => { state.selected = null; if (state.open !== null) state.open = null; renderClips(); },
    realign,
    submit: () => submit(false),
    submit_next: () => submit(true),
    previous: () => navigate(-1),
    next: () => navigate(1),
    send_task_error: sendTaskError,
  };
  function act(name) { const fn = actions[name]; if (fn) fn(); }
  $$("[data-action]").forEach((b) => b.addEventListener("click", (e) => { e.currentTarget.blur(); act(b.dataset.action); }));
  if (!data.urls.prev) $("[data-action=previous]").disabled = true;
  if (!data.urls.next) $("[data-action=next]").disabled = true;
  if (MODE === "reference") $("[data-action=submit]").textContent = "submit task";

  // ── Start ──────────────────────────────────────────────────────────────
  loadSource();
  fit();
  window.__practiceTool = { state, act, get range() { return [lo, hi]; } }; // exposed for automated tests
})();

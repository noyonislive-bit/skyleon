/*
 * Work guides → Video segments editor (/admin/guides/<id>/segments/).
 *
 * One screen to set, for every step and Task Error example, which video it uses and the part
 * of that video (start – end) its text describes. Players:
 *   video / hls  — <video> (uploaded files, direct MP4/WebM, HLS via hls.js)
 *   youtube      — YouTube IFrame API      vimeo — Vimeo Player API
 *   iframe/link  — no time API: the times are typed by hand
 * Admin UI → English.
 */
(function () {
  "use strict";
  const root = document.querySelector("[data-gs]");
  if (!root) return;
  const data = JSON.parse(document.getElementById("gs-data").textContent);
  const $ = (s, el = root) => el.querySelector(s);
  const $$ = (s, el = root) => Array.from(el.querySelectorAll(s));
  const HLS_LIB = (document.currentScript && document.currentScript.dataset.hls) ||
    (document.querySelector("script[data-hls]") || {}).dataset?.hls;

  // ── State ──────────────────────────────────────────────────────────────
  const sources = new Map(data.sources.map((s) => [s.key, s]));
  const items = data.items.map((it) => ({ ...it, orig: JSON.stringify([it.video, it.start, it.end]) }));
  let current = null;   // current source key
  let player = null;    // adapter
  let selected = null;  // item
  let dur = 0;

  const fmt = (t) => {
    if (t == null || isNaN(t)) return "";
    t = Math.max(0, Math.round(t));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : String(m).padStart(2, "0")) + ":" + String(s).padStart(2, "0");
  };
  const parse = (v) => {
    v = String(v || "").trim();
    if (!v) return null;
    if (/^\d+(\.\d+)?$/.test(v)) return Math.round(parseFloat(v));
    const parts = v.split(":");
    if (parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return NaN;
    return parts.reduce((acc, p) => acc * 60 + parseInt(p, 10), 0);
  };
  const toast = (msg, bad) => {
    const el = $("[data-gs-toast]");
    el.textContent = msg; el.hidden = false; el.classList.toggle("is-bad", !!bad);
    clearTimeout(el._t); el._t = setTimeout(() => (el.hidden = true), 3200);
  };
  const isDirty = (it) => JSON.stringify([it.video, it.start, it.end]) !== it.orig;

  // ── Players ────────────────────────────────────────────────────────────
  function loadScript(src) {
    return new Promise((res, rej) => {
      if (document.querySelector('script[src="' + src + '"]')) return res();
      const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = rej; document.head.appendChild(s);
    });
  }
  function html5(stage, src, kind) {
    const v = document.createElement("video");
    v.controls = true; v.playsInline = true; v.preload = "metadata";
    stage.appendChild(v);
    if (kind === "hls" && !v.canPlayType("application/vnd.apple.mpegurl") && HLS_LIB) {
      loadScript(HLS_LIB).then(() => { if (window.Hls && window.Hls.isSupported()) { const h = new window.Hls(); h.loadSource(src); h.attachMedia(v); } });
    } else v.src = src;
    return {
      time: () => v.currentTime, duration: () => v.duration || 0, seek: (t) => { v.currentTime = Math.max(0, t); },
      play: () => v.play(), pause: () => v.pause(), paused: () => v.paused, destroy: () => { v.pause(); v.remove(); },
    };
  }
  function youtube(stage, id) {
    const box = document.createElement("div"); stage.appendChild(box);
    const api = { time: () => 0, duration: () => 0, seek() {}, play() {}, pause() {}, paused: () => true, destroy: () => box.remove() };
    const ready = () => {
      const p = new window.YT.Player(box, { videoId: id, host: "https://www.youtube-nocookie.com", playerVars: { rel: 0, playsinline: 1 } });
      api.time = () => (p.getCurrentTime ? p.getCurrentTime() : 0);
      api.duration = () => (p.getDuration ? p.getDuration() : 0);
      api.seek = (t) => p.seekTo && p.seekTo(Math.max(0, t), true);
      api.play = () => p.playVideo && p.playVideo();
      api.pause = () => p.pauseVideo && p.pauseVideo();
      api.paused = () => !p.getPlayerState || p.getPlayerState() !== 1;
      api.destroy = () => { try { p.destroy(); } catch (_) { /* ignore */ } stage.innerHTML = ""; };
    };
    if (window.YT && window.YT.Player) ready();
    else {
      const prev = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => { if (prev) prev(); ready(); };
      loadScript("https://www.youtube.com/iframe_api");
    }
    return api;
  }
  function vimeo(stage, id, hash) {
    const f = document.createElement("iframe");
    f.src = "https://player.vimeo.com/video/" + id + (hash ? "?h=" + encodeURIComponent(hash) : "");
    f.allow = "autoplay; fullscreen; picture-in-picture"; f.allowFullscreen = true;
    stage.appendChild(f);
    let t = 0, d = 0, paused = true, p = null;
    loadScript("https://player.vimeo.com/api/player.js").then(() => {
      p = new window.Vimeo.Player(f);
      p.on("timeupdate", (e) => { t = e.seconds; d = e.duration; });
      p.on("play", () => (paused = false)); p.on("pause", () => (paused = true));
      p.getDuration().then((x) => (d = x));
    });
    return {
      time: () => t, duration: () => d, seek: (x) => { t = x; if (p) p.setCurrentTime(Math.max(0, x)); },
      play: () => p && p.play(), pause: () => p && p.pause(), paused: () => paused, destroy: () => f.remove(),
    };
  }
  function iframeOnly(stage, src) {
    const f = document.createElement("iframe");
    f.src = src; f.allow = "fullscreen; picture-in-picture; encrypted-media"; f.allowFullscreen = true;
    stage.appendChild(f);
    return { manual: true, time: () => null, duration: () => 0, seek() {}, play() {}, pause() {}, paused: () => true, destroy: () => f.remove() };
  }

  function load(key) {
    const src = sources.get(key);
    const stage = $("[data-gs-stage]");
    if (player) { player.destroy(); player = null; }
    stage.innerHTML = "";
    current = src ? key : null;
    $("[data-gs-select]").value = current || "";
    $("[data-gs-manual]").hidden = true;
    dur = src && src.duration ? src.duration : 0;
    if (!src) { stage.innerHTML = '<div class="gs-empty"><p>Choose a video above.</p></div>'; render(); return; }
    if (src.kind === "video" || src.kind === "hls") player = html5(stage, src.src, src.kind);
    else if (src.kind === "youtube") player = youtube(stage, src.video_id);
    else if (src.kind === "vimeo") player = vimeo(stage, src.video_id, src.hash);
    else if (src.kind === "iframe") player = iframeOnly(stage, src.src);
    else {
      stage.innerHTML = '<div class="gs-empty"><p>This link can\'t be played here.</p><a class="btn btn-white btn-sm" target="_blank" rel="noopener" href="' +
        encodeURI(src.url) + '">Open the video</a></div>';
      player = { manual: true, time: () => null, duration: () => 0, seek() {}, play() {}, pause() {}, paused: () => true, destroy() {} };
    }
    if (player.manual) {
      $("[data-gs-manual]").hidden = false;
      $("[data-gs-provider]").textContent = src.label;
    }
    root.classList.toggle("is-manual", !!player.manual);
    render();
  }

  // ── Video selector ─────────────────────────────────────────────────────
  function fillSelect() {
    const sel = $("[data-gs-select]");
    const used = new Set(items.map((i) => i.video).filter(Boolean));
    const opt = (s) => '<option value="' + s.key.replace(/"/g, "&quot;") + '">' + escapeHtml(s.label) +
      (used.has(s.key) ? " · " + items.filter((i) => i.video === s.key).length + " item(s)" : "") + "</option>";
    const inGuide = [...sources.values()].filter((s) => used.has(s.key));
    const lib = [...sources.values()].filter((s) => !used.has(s.key));
    sel.innerHTML = '<option value="">— Choose a video —</option>' +
      (inGuide.length ? '<optgroup label="Used in this guide">' + inGuide.map(opt).join("") + "</optgroup>" : "") +
      (lib.length ? '<optgroup label="Uploaded videos (library)">' + lib.map(opt).join("") + "</optgroup>" : "");
    sel.value = current || "";
  }
  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  $("[data-gs-select]").addEventListener("change", (e) => load(e.target.value));

  async function addUrl(url) {
    url = url.trim();
    if (!url) return;
    const key = "url:" + url;
    if (!sources.has(key)) {
      const res = await fetch(data.infoUrl + "?" + new URLSearchParams({ url }), { credentials: "same-origin" });
      const info = await res.json();
      if (!info.ok) { toast("Not a valid http(s) video link.", true); return; }
      const i = info.info;
      let kind = i.kind;
      if (kind === "iframe" && (i.provider === "youtube" || i.provider === "vimeo")) kind = i.provider;
      sources.set(key, { key, url, asset: "", src: (i.src || "").split("#")[0], kind, video_id: i.video_id || "", hash: i.vimeo_hash || "",
        label: i.provider_label + " · " + url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 48), duration: null });
      fillSelect();
    }
    load(key);
  }
  $("[data-gs-load]").addEventListener("click", () => addUrl($("[data-gs-url]").value));
  $("[data-gs-url]").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addUrl(e.target.value); } });
  root.addEventListener("uploader:change", (e) => {
    const a = e.detail;
    if (!a || !a.id || !a.url) return;
    const key = "asset:" + a.id;
    sources.set(key, { key, asset: a.id, url: "", src: a.url, kind: "video", label: "Uploaded · " + (a.name || "video"), duration: a.duration || null });
    fillSelect(); load(key);
    toast("Uploaded — now select items and press “Use this video”.");
  });

  // ── List ───────────────────────────────────────────────────────────────
  function renderList() {
    const list = $("[data-gs-list]");
    let html = "", section = null;
    items.forEach((it, idx) => {
      if (it.section !== section) { section = it.section; html += '<p class="gs-sec">' + escapeHtml(section) + "</p>"; }
      const src = it.video ? sources.get(it.video) : null;
      const match = it.video && it.video === current;
      html += '<div class="gs-row' + (it === selected ? " is-selected" : "") + (isDirty(it) ? " is-dirty" : "") + (it.type === "error" ? " is-error" : "") +
        '" data-idx="' + idx + '" tabindex="0">' +
        '<div class="gs-row-head"><span class="gs-num">' + escapeHtml(String(it.number)) + "</span>" +
        '<span class="gs-title" lang="bn">' + escapeHtml(it.title) + "</span>" +
        (it.verified && !isDirty(it) ? '<span class="g-ver is-ok">verified</span>' : "") + "</div>" +
        '<div class="gs-row-meta">' +
        (src ? '<span class="gs-src' + (match ? " is-match" : "") + '" title="' + escapeHtml(src.label) + '">' + (match ? "● this video" : "○ " + escapeHtml(src.label)) + "</span>"
             : '<span class="gs-src is-none">no video</span>') + "</div>" +
        '<div class="gs-row-edit">' +
        '<label>from <input class="input gs-time" data-f="start" value="' + fmt(it.start) + '" placeholder="m:ss" inputmode="numeric"></label>' +
        '<label>to <input class="input gs-time" data-f="end" value="' + fmt(it.end) + '" placeholder="m:ss" inputmode="numeric"></label>' +
        '<button type="button" class="btn btn-ghost btn-sm" data-row="use"' + (current && !match ? "" : " disabled") + '>Use this video</button>' +
        '<button type="button" class="btn btn-ghost btn-sm text-red-600" data-row="clear"' + (it.video ? "" : " disabled") + ">Remove video</button>" +
        "</div></div>";
    });
    list.innerHTML = html;
    const dirty = items.filter(isDirty).length;
    $("[data-gs-dirty]").textContent = dirty ? dirty + " unsaved change(s)" : "No changes";
    $("[data-gs-save]").disabled = !dirty;
    const withVideo = items.filter((i) => i.video).length;
    $("[data-gs-summary]").textContent = items.length + " items · " + withVideo + " with a video · " + items.filter((i) => i.video && i.end != null).length + " with a start–end part";
  }
  function select(it, seek) {
    selected = it;
    if (it && it.video && it.video !== current) load(it.video);
    if (it && seek && it.start != null && player && !player.manual) player.seek(it.start);
    render();
    const row = $('.gs-row[data-idx="' + items.indexOf(it) + '"]');
    if (row) row.scrollIntoView({ block: "nearest" });
  }
  $("[data-gs-list]").addEventListener("click", (e) => {
    const row = e.target.closest(".gs-row"); if (!row) return;
    const it = items[+row.dataset.idx];
    const act = e.target.closest("[data-row]");
    if (act) {
      if (act.dataset.row === "use" && current) { it.video = current; selected = it; }
      if (act.dataset.row === "clear") { it.video = ""; it.start = null; it.end = null; }
      render(); return;
    }
    if (e.target.closest("input")) { if (selected !== it) { selected = it; render(); row.querySelector("input")?.focus(); } return; }
    select(it, true);
  });
  $("[data-gs-list]").addEventListener("change", (e) => {
    const input = e.target.closest("input[data-f]"); if (!input) return;
    const it = items[+input.closest(".gs-row").dataset.idx];
    const v = parse(input.value);
    if (Number.isNaN(v)) { toast("Use m:ss (e.g. 1:30) or seconds.", true); input.value = fmt(it[input.dataset.f]); return; }
    it[input.dataset.f] = v;
    if (it.video === "" && current && v != null) it.video = current; // typing a time on a row without a video uses the current one
    render();
  });

  // ── Timeline ───────────────────────────────────────────────────────────
  const timeline = $("[data-gs-timeline]");
  function renderTimeline() {
    const d = dur || (player && player.duration()) || 0;
    const blocks = $("[data-gs-blocks]");
    if (!current || !d) { blocks.innerHTML = ""; return; }
    blocks.innerHTML = items.filter((it) => it.video === current && it.start != null).map((it) => {
      const s = it.start, e = it.end != null ? it.end : Math.min(d, s + 1);
      return '<div class="gs-block' + (it === selected ? " is-selected" : "") + (it.type === "error" ? " is-error" : "") + '" data-idx="' + items.indexOf(it) +
        '" style="left:' + (s / d * 100) + "%;width:" + Math.max(0.6, (e - s) / d * 100) + '%" title="' + escapeHtml(it.number + " · " + it.title) + '">' +
        '<span class="gs-h is-l" data-h="start"></span><span class="gs-block-label">' + escapeHtml(String(it.number)) + '</span><span class="gs-h is-r" data-h="end"></span></div>';
    }).join("");
  }
  let drag = null;
  timeline.addEventListener("pointerdown", (e) => {
    const d = dur || (player && player.duration()) || 0;
    if (!d || !player || player.manual) return;
    const rect = timeline.getBoundingClientRect();
    const tAt = (x) => Math.max(0, Math.min(d, (x - rect.left) / rect.width * d));
    const block = e.target.closest(".gs-block");
    const handle = e.target.closest("[data-h]");
    if (block) {
      const it = items[+block.dataset.idx];
      selected = it;
      if (handle) { drag = { it, f: handle.dataset.h, tAt }; timeline.setPointerCapture(e.pointerId); e.preventDefault(); }
      else player.seek(it.start || 0);
      render(); return;
    }
    player.seek(tAt(e.clientX));
  });
  timeline.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const t = Math.round(drag.tAt(e.clientX));
    const it = drag.it;
    if (drag.f === "start") it.start = Math.min(t, it.end != null ? it.end - 1 : t);
    else it.end = Math.max(t, (it.start || 0) + 1);
    player.seek(t); render();
  });
  timeline.addEventListener("pointerup", () => (drag = null));

  // ── Controls ───────────────────────────────────────────────────────────
  let segStop = null;
  const actions = {
    toggle: () => { if (!player) return; player.paused() ? player.play() : player.pause(); },
    back1: () => player && player.seek(player.time() - 1), fwd1: () => player && player.seek(player.time() + 1),
    back5: () => player && player.seek(player.time() - 5), fwd5: () => player && player.seek(player.time() + 5),
    setStart: () => setFromPlayer("start"), setEnd: () => setFromPlayer("end"),
    playSeg: () => {
      if (!selected || selected.start == null || !player || player.manual) { toast("Select an item with a start time first.", true); return; }
      if (selected.video !== current) load(selected.video);
      player.seek(selected.start); player.play(); segStop = selected.end;
    },
  };
  function setFromPlayer(f) {
    if (!player || player.manual) { toast("Type the time in the list for this player.", true); return; }
    if (!selected) { toast("Select a step or Task Error example in the list first.", true); return; }
    const t = Math.round(player.time());
    if (selected.video !== current) selected.video = current;
    if (f === "start") { selected.start = t; if (selected.end != null && selected.end <= t) selected.end = null; }
    else {
      if (t <= (selected.start || 0)) { toast("The end must be after the start.", true); return; }
      selected.end = t;
    }
    render();
  }
  $$("[data-gs-act]").forEach((b) => b.addEventListener("click", () => actions[b.dataset.gsAct]()));
  document.addEventListener("keydown", (e) => {
    if (e.target.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key;
    const map = { " ": "toggle", "[": "setStart", "]": "setEnd", p: "playSeg", P: "playSeg" };
    if (k === "ArrowLeft" || k === "ArrowRight") { e.preventDefault(); actions[(k === "ArrowLeft" ? "back" : "fwd") + (e.shiftKey ? "5" : "1")](); return; }
    if (k === "ArrowUp" || k === "ArrowDown") {
      e.preventDefault();
      const i = selected ? items.indexOf(selected) : -1;
      const next = items[Math.max(0, Math.min(items.length - 1, i + (k === "ArrowDown" ? 1 : -1)))];
      if (next) select(next, true);
      return;
    }
    if (map[k]) { e.preventDefault(); actions[map[k]](); }
  });

  function tick() {
    if (player && !player.manual) {
      const t = player.time() || 0, d = player.duration() || dur || 0;
      if (d && d !== dur) { dur = d; renderTimeline(); }
      $("[data-gs-clock]").textContent = fmt(t) + " / " + (d ? fmt(d) : "--:--");
      $("[data-gs-playhead]").style.left = d ? (t / d * 100) + "%" : "0";
      $("[data-gs-playlabel]").textContent = player.paused() ? "Play" : "Pause";
      if (segStop != null && t >= segStop) { player.pause(); segStop = null; }
    }
    requestAnimationFrame(tick);
  }

  function render() { renderList(); renderTimeline(); fillSelectCounts(); }
  function fillSelectCounts() { const v = $("[data-gs-select]").value; fillSelect(); $("[data-gs-select]").value = v; }

  // ── Save ───────────────────────────────────────────────────────────────
  $("[data-gs-save]").addEventListener("click", async () => {
    const changed = items.filter(isDirty);
    if (!changed.length) return;
    const body = { items: changed.map((it) => {
      const src = it.video ? sources.get(it.video) : null;
      return { type: it.type, id: it.id, start: it.start, end: it.end,
        source: src ? (src.asset ? { asset: src.asset } : { url: src.url }) : null };
    }) };
    const btn = $("[data-gs-save]"); btn.disabled = true;
    try {
      const res = await fetch(data.saveUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": window.skyleon.csrfToken() }, body: JSON.stringify(body) });
      const out = await res.json();
      if (out.errors && out.errors.length) toast(out.errors.join(" · "), true);
      else toast("Saved — " + out.changed + " item(s) updated. Verify them against the original again.");
      changed.forEach((it) => { if (!(out.errors || []).some((m) => m.startsWith(it.title))) { it.orig = JSON.stringify([it.video, it.start, it.end]); it.verified = false; } });
    } catch (_) {
      toast("Could not save — check your connection and try again.", true);
    }
    render();
  });
  window.addEventListener("beforeunload", (e) => { if (items.some(isDirty)) { e.preventDefault(); e.returnValue = ""; } });

  // ── Start ──────────────────────────────────────────────────────────────
  fillSelect();
  const focus = data.focus && items.find((it) => it.type + "-" + it.id === data.focus);
  const first = focus || items.find((it) => it.video) || items[0];
  if (first && first.video) load(first.video);
  if (first) select(first, true); else render();
  requestAnimationFrame(tick);
})();

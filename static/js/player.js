/*
 * Skyloon AI tracked video player — used for tutorials and feedback videos.
 *
 * Markup: templates/portal/includes/player.html  (<div data-player …><video data-video></video></div>)
 *
 *  - Plays MP4 directly; .m3u8 through native HLS (Safari) or a lazily loaded hls.js.
 *  - Resumes from the last saved position (from the start when it was ≥ 95 % through).
 *  - Sends heartbeats {duration, position, ranges} — ranges come from video.played — every
 *    ~10 s while playing and on pause / seeked / ended / tab hidden / page hide.
 *  - Shows only server-confirmed progress (the response of each heartbeat).
 *  - Required, unfinished videos: no seeking forward past the furthest watched point (+2 s);
 *    rewinding is allowed. Playback rate is capped at 2×.
 *
 * Events (bubble from the [data-player] element):
 *   "player:progress"  detail = server response {percent, status, completed, watched_seconds, completed_at}
 *   "player:completed" detail = same, fired once when the server first reports completion
 */
(function () {
  "use strict";

  const HEARTBEAT_MS = 10000;
  const MAX_RATE = 2;
  const SEEK_TOLERANCE = 2; // seconds beyond the furthest watched point
  const RESTART_AT = 0.95;

  const round2 = (n) => Math.round(n * 100) / 100;

  function playedRanges(video) {
    const out = [];
    const tr = video.played;
    for (let i = 0; i < tr.length; i++) {
      const s = tr.start(i);
      const e = tr.end(i);
      if (isFinite(s) && isFinite(e) && e - s > 0.05) out.push([round2(s), round2(e)]);
    }
    return out;
  }

  let hlsPromise = null;
  function loadHls(src) {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (!hlsPromise) {
      hlsPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = src;
        s.async = true;
        s.onload = () => (window.Hls ? resolve(window.Hls) : reject(new Error("hls.js missing")));
        s.onerror = () => reject(new Error("hls.js failed to load"));
        document.head.appendChild(s);
      });
    }
    return hlsPromise;
  }

  function csrf() {
    return window.skyleon && window.skyleon.csrfToken ? window.skyleon.csrfToken() : "";
  }

  class TrackedPlayer {
    constructor(root) {
      this.root = root;
      this.video = root.querySelector("video[data-video]");
      const d = root.dataset;
      this.url = d.heartbeat;
      this.enforce = d.enforce === "1";
      this.completed = d.completed === "1";
      this.knownDuration = parseFloat(d.duration) || 0;
      this.resume = parseFloat(d.resume) || 0;
      this.furthest = parseFloat(d.furthest) || 0;
      this.timer = null;
      this.inFlight = false;
      this.queued = false;
      this.lastSignature = "";
      this.toastTimer = null;
      this.ui = {
        percent: root.querySelector("[data-progress-percent]"),
        bar: root.querySelector("[data-progress-bar]"),
        meter: root.querySelector("[data-progress-meter]"),
        save: root.querySelector("[data-save-state]"),
        toast: root.querySelector("[data-player-toast]"),
      };
      this.attachSource();
      this.bind();
    }

    duration() {
      const d = this.video.duration;
      if (isFinite(d) && d > 0) return d;
      return this.knownDuration || 0;
    }

    attachSource() {
      const { src, hls, hlsLib, mime } = this.root.dataset;
      const v = this.video;
      if (hls === "1") {
        if (v.canPlayType("application/vnd.apple.mpegurl")) {
          v.src = src;
        } else {
          loadHls(hlsLib)
            .then((Hls) => {
              if (!Hls.isSupported()) throw new Error("unsupported");
              const player = new Hls({ enableWorker: true });
              player.loadSource(src);
              player.attachMedia(v);
              player.on(Hls.Events.ERROR, (_e, data) => {
                if (data && data.fatal) this.fail("The video stream could not be loaded. Please reload the page.");
              });
              this.hls = player;
            })
            .catch(() => this.fail("This browser can't play this video stream."));
        }
      } else {
        if (mime && !v.canPlayType(mime)) {
          // e.g. H.264 MP4 on a browser build without proprietary codecs — still try, but explain failures.
          this.unsupported = true;
        }
        v.src = src;
      }
      v.addEventListener("error", () => {
        const code = v.error && v.error.code;
        if (code === 4 || this.unsupported) {
          this.fail("This browser can't play this video format. Please use an up-to-date Chrome, Edge, Firefox or Safari.");
        } else {
          this.fail("The video could not be loaded. Your viewing link may have expired — reload the page.");
        }
      });
    }

    bind() {
      const v = this.video;

      const onMeta = () => {
        const d = this.duration();
        let start = this.resume;
        if (d && start >= d * RESTART_AT) start = 0;
        if (this.enforce) start = Math.min(start, this.furthest);
        if (start > 1 && (!d || start < d)) {
          try { v.currentTime = start; } catch (_) { /* ignore */ }
        }
      };
      if (v.readyState >= 1) onMeta();
      else v.addEventListener("loadedmetadata", onMeta, { once: true });

      // Track the furthest point reached through normal playback.
      v.addEventListener("timeupdate", () => {
        if (v.seeking) return;
        const t = v.currentTime;
        if (t > this.furthest && t - this.furthest <= 3) this.furthest = t;
      });

      // Block seeking forward on required, unfinished videos.
      v.addEventListener("seeking", () => {
        if (!this.enforce || this.completed) return;
        if (v.currentTime > this.furthest + SEEK_TOLERANCE) {
          v.currentTime = this.furthest;
          this.toast("Skipping ahead is disabled until you've watched the whole video.");
        }
      });

      v.addEventListener("ratechange", () => {
        if (v.playbackRate > MAX_RATE) {
          v.playbackRate = MAX_RATE;
          this.toast("Maximum playback speed is 2×.");
        }
      });

      v.addEventListener("play", () => this.startTimer());
      v.addEventListener("pause", () => { this.stopTimer(); this.send(); });
      v.addEventListener("seeked", () => this.send());
      v.addEventListener("ended", () => { this.stopTimer(); this.send(); });

      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") this.send(true);
      });
      window.addEventListener("pagehide", () => this.send(true));
    }

    startTimer() {
      this.stopTimer();
      this.timer = window.setInterval(() => this.send(), HEARTBEAT_MS);
    }

    stopTimer() {
      if (this.timer) window.clearInterval(this.timer);
      this.timer = null;
    }

    send(final = false) {
      if (!this.url) return;
      const ranges = playedRanges(this.video);
      if (!ranges.length) return; // nothing has been played yet
      const duration = this.duration();
      const payload = {
        duration: duration ? round2(duration) : null,
        position: round2(this.video.currentTime || 0),
        ranges,
      };
      const signature = JSON.stringify(payload);
      if (signature === this.lastSignature && !final) return;
      if (this.inFlight && !final) {
        this.queued = true;
        return;
      }
      this.inFlight = true;
      this.lastSignature = signature;
      fetch(this.url, {
        method: "POST",
        credentials: "same-origin",
        keepalive: true,
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf(), "X-Requested-With": "fetch" },
        body: signature,
      })
        .then((res) => res.json().catch(() => ({})).then((data) => ({ res, data })))
        .then(({ res, data }) => {
          if (res.ok) this.update(data);
          else this.saveError(res.status);
        })
        .catch(() => this.saveError(0))
        .finally(() => {
          this.inFlight = false;
          if (this.queued) {
            this.queued = false;
            this.send();
          }
        });
    }

    update(data) {
      if (typeof data.percent !== "number") return;
      if (data.throttled) {
        // The server skipped this heartbeat (too soon after the previous one); re-send shortly.
        this.lastSignature = "";
        if (this.video.paused) {
          window.clearTimeout(this.retryTimer);
          this.retryTimer = window.setTimeout(() => this.send(), 4000);
        }
      }
      const pct = Math.max(0, Math.min(100, Math.round(data.percent)));
      if (this.ui.percent) this.ui.percent.textContent = String(pct);
      if (this.ui.bar) this.ui.bar.style.width = pct + "%";
      if (this.ui.meter) this.ui.meter.setAttribute("aria-valuenow", String(pct));
      const justCompleted = data.completed && !this.completed;
      if (data.completed) {
        this.completed = true;
        this.enforce = false;
        if (this.ui.bar) this.ui.bar.classList.replace("bg-accent-400", "bg-emerald-400");
        this.setSave("done", "Completed — saved");
        document.querySelectorAll("[data-enforce-note]").forEach((el) => el.remove());
      } else {
        const time = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        this.setSave("ok", "Saved at " + time);
      }
      this.root.dispatchEvent(new CustomEvent("player:progress", { bubbles: true, detail: data }));
      if (justCompleted) this.root.dispatchEvent(new CustomEvent("player:completed", { bubbles: true, detail: data }));
    }

    saveError(status) {
      if (status === 403 || status === 401) this.setSave("error", "Session expired — reload to keep saving progress");
      else if (status === 404) this.setSave("error", "This video is no longer available");
      else this.setSave("error", "Couldn't save progress — retrying");
      this.lastSignature = ""; // allow the next heartbeat to retry the same data
    }

    setSave(kind, text) {
      const el = this.ui.save;
      if (!el) return;
      const color = kind === "error" ? "text-amber-300" : kind === "done" ? "text-emerald-300" : "text-slate-400";
      el.className = "flex items-center gap-1.5 whitespace-nowrap " + color;
      el.textContent = text;
    }

    toast(message) {
      const el = this.ui.toast;
      if (!el) return;
      el.textContent = message;
      el.classList.remove("opacity-0");
      window.clearTimeout(this.toastTimer);
      this.toastTimer = window.setTimeout(() => el.classList.add("opacity-0"), 2600);
    }

    fail(message) {
      this.stopTimer();
      const wrap = document.createElement("div");
      wrap.className = "absolute inset-0 flex items-center justify-center bg-ink-950/90 p-6 text-center text-sm text-slate-200";
      wrap.setAttribute("role", "alert");
      wrap.textContent = message;
      this.video.parentElement.appendChild(wrap);
    }
  }

  // Page widgets that mirror the server-confirmed progress -----------------
  //   [data-progress-ring] (--p), [data-ring-percent], [data-watched-seconds], [data-status-badge]
  //   [data-complete-banner] (+ [data-complete-date]) revealed on completion
  //   [data-unlock-on-complete] buttons enabled on completion; [data-hide-when-complete] hidden, [data-show-when-complete] shown
  const STATUS = { completed: ["success", "Completed"], in_progress: ["info", "In progress"], not_started: ["neutral", "Not started"] };
  const mmss = (sec) => {
    const s = Math.max(0, Math.round(sec));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const r = String(s % 60).padStart(2, "0");
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + r : m + ":" + r;
  };
  document.addEventListener("player:progress", (e) => {
    const d = e.detail || {};
    const pct = Math.max(0, Math.min(100, Math.round(d.percent || 0)));
    document.querySelectorAll("[data-progress-ring]").forEach((ring) => {
      ring.style.setProperty("--p", pct);
      ring.classList.toggle("is-complete", !!d.completed);
    });
    document.querySelectorAll("[data-ring-percent]").forEach((el) => (el.textContent = pct));
    if (typeof d.watched_seconds === "number") {
      document.querySelectorAll("[data-watched-seconds]").forEach((el) => (el.textContent = mmss(d.watched_seconds)));
    }
    const st = STATUS[d.status];
    if (st) {
      document.querySelectorAll("[data-status-badge]").forEach((el) => {
        el.innerHTML = "";
        const b = document.createElement("span");
        b.className = "badge badge-" + st[0];
        b.textContent = st[1];
        el.appendChild(b);
      });
    }
  });
  document.addEventListener("player:completed", (e) => {
    const d = e.detail || {};
    document.querySelectorAll("[data-complete-banner]").forEach((banner) => {
      const date = banner.querySelector("[data-complete-date]");
      if (date && d.completed_at) date.textContent = d.completed_at;
      banner.classList.remove("hidden");
      banner.hidden = false;
    });
    document.querySelectorAll("[data-unlock-on-complete]").forEach((el) => {
      el.disabled = false;
      el.removeAttribute("aria-disabled");
    });
    document.querySelectorAll("[data-hide-when-complete]").forEach((el) => el.classList.add("hidden"));
    document.querySelectorAll("[data-show-when-complete]").forEach((el) => { el.hidden = false; el.classList.remove("hidden"); });
  });

  window.skyleon = window.skyleon || {};
  window.skyleon.TrackedPlayer = TrackedPlayer;
  document.querySelectorAll("[data-player]").forEach((el) => {
    el.trackedPlayer = new TrackedPlayer(el);
  });
})();

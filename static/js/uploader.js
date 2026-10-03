/*
 * Admin panel — direct-to-storage uploader.
 *
 * Markup: templates/backoffice/components/uploader.html ({% uploader form.video kind="video" purpose="tutorial" %}).
 * Flow for a video:
 *   1. read duration / width / height in the browser (hidden <video>, loadedmetadata)
 *   2. capture a frame at ~10% into a <canvas> → JPEG → upload it (kind=image, purpose=thumbnail)
 *   3. POST /media/uploads/init/ → {mode: "put", url, headers} (S3 presigned) or {mode: "chunked", url, chunk_size} (local)
 *   4. upload with progress: one XHR PUT, or sequential Blob.slice chunks with X-Chunk-Offset (+ retry / resume)
 *   5. POST /media/uploads/<id>/complete/ {duration, width, height, thumbnail_id}
 *   6. the MediaAsset id goes into the hidden input; only that id is submitted with the form.
 * External HLS (.m3u8) / MP4 URLs are registered with POST /media/external/.
 *
 * Standalone use (any page, no build step): include this file and render
 *   {% load backoffice_tags %}{% uploader form.video kind="video" purpose="tutorial" %}
 * (form field: apps.backoffice.forms.MediaAssetField) — or hand-write the markup of
 * templates/backoffice/components/uploader.html: a [data-uploader][data-kind][data-purpose] root with
 * [data-uploader-value] (hidden input, the field name), [data-uploader-file], [data-uploader-drop],
 * [data-uploader-preview] … Widgets added later (e.g. cloned rows) are initialised with
 * window.skyleon.initUploaders(rootElement). Each change fires "uploader:change" (detail = asset JSON).
 */
(function () {
  "use strict";

  const INIT_URL = "/media/uploads/init/";
  const EXTERNAL_URL = "/media/external/";
  const completeUrl = (id) => `/media/uploads/${encodeURIComponent(id)}/complete/`;
  const MAX_RETRIES = 4;
  const VIDEO_EXT = /\.(mp4|webm|mov|m4v)$/i;
  const IMAGE_EXT = /\.(jpe?g|png|webp|gif)$/i;
  const DOC_EXT = /\.(pdf|docx?|txt|rtf|odt|zip|csv|xlsx|json|xml|jpe?g|png|webp)$/i;

  const S = () => window.skyleon || {};
  const csrf = () => {
    if (S().csrfToken) return S().csrfToken();
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function fmtDuration(s) {
    if (!isFinite(s) || s <= 0) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const mm = h ? String(m).padStart(2, "0") : String(m);
    return (h ? `${h}:` : "") + `${mm}:${String(sec).padStart(2, "0")}`;
  }

  function fmtSize(bytes) {
    if (!bytes && bytes !== 0) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let n = bytes, i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
    return i === 0 ? `${n} B` : `${n.toFixed(1)} ${units[i]}`;
  }

  async function postJSON(url, data) {
    const res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
      body: JSON.stringify(data || {}),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.error || `Request failed (${res.status})`), { status: res.status });
    return body;
  }

  /** XHR wrapper with upload progress + abort support. */
  function xhrSend(method, url, body, headers, onProgress, signal) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open(method, url, true);
      Object.entries(headers || {}).forEach(([k, v]) => xhr.setRequestHeader(k, v));
      if (xhr.upload && onProgress) {
        xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded, e.total); };
      }
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) return resolve(xhr);
        let msg = `Upload failed (${xhr.status})`;
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (_) { /* not JSON */ }
        reject(Object.assign(new Error(msg), { status: xhr.status }));
      };
      xhr.onerror = () => reject(Object.assign(new Error("Network error — check your connection."), { status: 0 }));
      xhr.onabort = () => reject(Object.assign(new Error("Upload cancelled."), { aborted: true }));
      if (signal) {
        if (signal.aborted) { xhr.abort(); return; }
        signal.addEventListener("abort", () => xhr.abort(), { once: true });
      }
      xhr.send(body);
    });
  }

  /** Read duration/size and grab a thumbnail frame (~10% in). Resolves {} if the browser can't decode it. */
  function readVideo(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const video = document.createElement("video");
      video.preload = "auto";
      video.muted = true;
      video.playsInline = true;
      let done = false;
      let meta = {};
      const finish = (extra) => {
        if (done) return;
        done = true;
        clearTimeout(timer);
        video.removeAttribute("src");
        try { video.load(); } catch (_) { /* ignore */ }
        URL.revokeObjectURL(url);
        resolve(Object.assign(meta, extra || {}));
      };
      const timer = setTimeout(() => finish(), 20000);
      video.addEventListener("error", () => finish(), { once: true });
      video.addEventListener("loadedmetadata", () => {
        meta = {
          duration: isFinite(video.duration) ? video.duration : null,
          width: video.videoWidth || null,
          height: video.videoHeight || null,
        };
        if (!video.videoWidth) return finish();
        const at = meta.duration ? Math.min(meta.duration * 0.1, Math.max(meta.duration - 0.2, 0)) : 0.5;
        video.addEventListener("seeked", () => {
          // Give the decoder a frame to paint before drawing.
          const draw = () => captureFrame(video).then((blob) => finish({ thumbnail: blob }));
          if ("requestVideoFrameCallback" in video) {
            let fired = false;
            video.requestVideoFrameCallback(() => { fired = true; draw(); });
            setTimeout(() => { if (!fired) draw(); }, 400);
          } else {
            setTimeout(draw, 150);
          }
        }, { once: true });
        try { video.currentTime = at || 0.1; } catch (_) { finish(); }
      }, { once: true });
      video.src = url;
    });
  }

  function captureFrame(video) {
    return new Promise((resolve) => {
      try {
        const w = video.videoWidth, h = video.videoHeight;
        if (!w || !h) return resolve(null);
        const scale = Math.min(1, 640 / w);
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(w * scale);
        canvas.height = Math.round(h * scale);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => resolve(blob && blob.size > 1000 ? blob : null), "image/jpeg", 0.82);
      } catch (_) {
        resolve(null);
      }
    });
  }

  function readImage(file) {
    return new Promise((resolve) => {
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => { resolve({ width: img.naturalWidth, height: img.naturalHeight }); URL.revokeObjectURL(url); };
      img.onerror = () => { resolve({}); URL.revokeObjectURL(url); };
      img.src = url;
    });
  }

  /** Upload a Blob/File through the storage API. Returns the init response (with id). */
  async function transfer(blob, { filename, kind, purpose, mime }, onProgress, signal) {
    const init = await postJSON(INIT_URL, {
      filename, size: blob.size, mime_type: mime || blob.type || "", kind, purpose,
    });
    if (init.mode === "put") {
      await xhrSend("PUT", init.url, blob, init.headers || {}, (loaded) => onProgress(loaded, blob.size), signal);
    } else {
      await uploadChunks(init, blob, onProgress, signal);
    }
    onProgress(blob.size, blob.size);
    return init;
  }

  async function uploadChunks(target, blob, onProgress, signal) {
    const size = blob.size;
    const chunk = Math.max(256 * 1024, target.chunk_size || 5 * 1024 * 1024);
    let offset = 0;
    while (offset < size) {
      const end = Math.min(offset + chunk, size);
      let attempt = 0;
      for (;;) {
        try {
          const xhr = await xhrSend(
            "POST", target.url, blob.slice(offset, end),
            { "X-CSRFToken": csrf(), "X-Chunk-Offset": String(offset), "Content-Type": "application/octet-stream" },
            (loaded) => onProgress(offset + loaded, size), signal,
          );
          let received = end;
          try { received = JSON.parse(xhr.responseText).received; } catch (_) { /* keep end */ }
          offset = typeof received === "number" ? received : end;
          break;
        } catch (err) {
          if (err.aborted) throw err;
          // The server already has this chunk (e.g. the response was lost): resume where it says.
          const m = err.status === 409 && /expected (\d+)/.exec(err.message);
          if (m) { offset = parseInt(m[1], 10); break; }
          attempt += 1;
          if ([400, 403, 404, 413].includes(err.status) || attempt > MAX_RETRIES) throw err;
          await sleep(800 * 2 ** (attempt - 1));
        }
      }
      onProgress(offset, size);
    }
  }

  class Uploader {
    constructor(root) {
      this.root = root;
      this.kind = root.dataset.kind || "video";
      this.purpose = root.dataset.purpose || this.kind;
      const q = (s) => root.querySelector(s);
      this.el = {
        value: q("[data-uploader-value]"), file: q("[data-uploader-file]"), drop: q("[data-uploader-drop]"),
        preview: q("[data-uploader-preview]"), thumb: q("[data-uploader-thumb]"), icon: q("[data-uploader-icon]"),
        duration: q("[data-uploader-duration]"), name: q("[data-uploader-name]"), meta: q("[data-uploader-meta]"),
        open: q("[data-uploader-open]"), progress: q("[data-uploader-progress]"), bar: q("[data-uploader-bar]"),
        percent: q("[data-uploader-percent]"), status: q("[data-uploader-status]"), error: q("[data-uploader-error]"),
        external: q("[data-uploader-external]"), externalUrl: q("[data-uploader-external-url]"),
      };
      this.controller = null;
      this.bind();
    }

    bind() {
      const { el, root } = this;
      const browse = () => el.file && el.file.click();
      root.querySelectorAll("[data-uploader-browse], [data-uploader-replace]").forEach((b) => b.addEventListener("click", browse));
      el.file && el.file.addEventListener("change", () => { if (el.file.files[0]) this.upload(el.file.files[0]); el.file.value = ""; });
      const remove = root.querySelector("[data-uploader-remove]");
      remove && remove.addEventListener("click", () => this.clear());
      const cancel = root.querySelector("[data-uploader-cancel]");
      cancel && cancel.addEventListener("click", () => this.controller && this.controller.abort());
      const toggle = root.querySelector("[data-uploader-external-toggle]");
      toggle && toggle.addEventListener("click", () => {
        el.external.hidden = !el.external.hidden;
        if (!el.external.hidden) el.externalUrl.focus();
      });
      const save = root.querySelector("[data-uploader-external-save]");
      save && save.addEventListener("click", () => this.useExternal());
      el.externalUrl && el.externalUrl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); this.useExternal(); }
      });
      if (el.drop) {
        ["dragenter", "dragover"].forEach((t) => el.drop.addEventListener(t, (e) => { e.preventDefault(); el.drop.classList.add("is-dragover"); }));
        ["dragleave", "drop"].forEach((t) => el.drop.addEventListener(t, () => el.drop.classList.remove("is-dragover")));
        el.drop.addEventListener("drop", (e) => {
          e.preventDefault();
          const file = e.dataTransfer && e.dataTransfer.files[0];
          if (file) this.upload(file);
        });
      }
    }

    kindFor(file) {
      if (this.kind === "media") return /^video\//.test(file.type) || VIDEO_EXT.test(file.name) ? "video" : "image";
      return this.kind;
    }

    validate(file, kind) {
      if (!file.size) return "This file is empty.";
      const ok = kind === "video" ? VIDEO_EXT : kind === "image" ? IMAGE_EXT : DOC_EXT;
      if (!ok.test(file.name)) {
        return kind === "video" ? "Choose an MP4, WebM, MOV or M4V video." : kind === "image"
          ? "Choose a JPG, PNG, WebP or GIF image." : "This file type is not allowed.";
      }
      if (kind !== "video" && file.size > 15 * 1024 * 1024) return "Files must be 15 MB or smaller.";
      return "";
    }

    setBusy(busy) {
      if (busy) this.root.setAttribute("data-busy", "1");
      else this.root.removeAttribute("data-busy");
      this.el.progress.hidden = !busy;
      if (busy) { this.el.drop.hidden = true; this.el.preview.hidden = true; if (this.el.external) this.el.external.hidden = true; }
    }

    progress(fraction, label) {
      const pct = Math.max(0, Math.min(100, Math.round(fraction * 100)));
      this.el.bar.style.width = `${pct}%`;
      this.el.percent.textContent = `${pct}%`;
      if (label) this.el.status.textContent = label;
    }

    error(message) {
      this.el.error.textContent = message || "";
      this.el.error.hidden = !message;
    }

    async upload(file) {
      const kind = this.kindFor(file);
      const problem = this.validate(file, kind);
      this.error("");
      if (problem) return this.error(problem);
      const previous = this.el.value.value;
      this.controller = new AbortController();
      const signal = this.controller.signal;
      this.setBusy(true);
      this.progress(0, kind === "video" ? "Reading video…" : "Preparing…");
      try {
        let meta = {};
        let thumbId = null;
        let localThumb = "";
        if (kind === "video") {
          meta = await readVideo(file);
          if (meta.thumbnail) {
            this.progress(0, "Uploading thumbnail…");
            localThumb = URL.createObjectURL(meta.thumbnail);
            const t = await transfer(meta.thumbnail, {
              filename: "thumbnail.jpg", kind: "image", purpose: "thumbnail", mime: "image/jpeg",
            }, () => {}, signal);
            const done = await postJSON(completeUrl(t.id), { width: meta.width, height: meta.height });
            thumbId = done.id;
          }
        } else if (kind === "image") {
          meta = await readImage(file);
          localThumb = URL.createObjectURL(file);
        }
        const label = `Uploading ${file.name}`;
        const started = Date.now();
        const init = await transfer(file, { filename: file.name, kind, purpose: this.purpose, mime: file.type }, (loaded, total) => {
          const secs = (Date.now() - started) / 1000;
          const rate = secs > 1 ? loaded / secs : 0;
          const left = rate ? Math.round((total - loaded) / rate) : 0;
          this.progress(loaded / total, `${label} · ${fmtSize(loaded)} of ${fmtSize(total)}${left > 2 ? ` · ${fmtDuration(left)} left` : ""}`);
        }, signal);
        this.progress(1, "Finishing…");
        const asset = await postJSON(completeUrl(init.id), {
          duration: meta.duration || null, width: meta.width || null, height: meta.height || null, thumbnail_id: thumbId,
        });
        this.show(asset, { file, meta, localThumb, kind });
      } catch (err) {
        if (previous) this.el.value.value = previous;
        this.error(err.aborted ? "Upload cancelled." : `${err.message || "Upload failed."} Please try again.`);
        this.restoreView();
      } finally {
        this.controller = null;
        this.setBusy(false);
        this.restoreView();
      }
    }

    async useExternal() {
      const url = (this.el.externalUrl.value || "").trim();
      this.error("");
      if (!/^https?:\/\//i.test(url)) return this.error("Enter a full https:// URL to an .m3u8 playlist or an .mp4 file.");
      this.setBusy(true);
      this.progress(0.3, "Checking the URL…");
      try {
        let duration = null;
        if (!/\.m3u8(\?|$)/i.test(url)) duration = await probeDuration(url);
        const asset = await postJSON(EXTERNAL_URL, { url, duration, purpose: this.purpose });
        this.el.externalUrl.value = "";
        this.show(asset, { kind: "video", external: true });
      } catch (err) {
        this.error(err.message || "Could not use this URL.");
      } finally {
        this.setBusy(false);
        this.restoreView();
      }
    }

    show(asset, { file, meta, localThumb, kind, external } = {}) {
      const { el } = this;
      el.value.value = asset.id;
      el.name.textContent = asset.name || (file && file.name) || "Uploaded file";
      const parts = [];
      parts.push(external ? "External URL / streaming service" : "Uploaded just now");
      if (asset.size || (file && file.size)) parts.push(fmtSize(asset.size || file.size));
      if (meta && meta.width) parts.push(`${meta.width}×${meta.height}`);
      el.meta.textContent = parts.join(" · ");
      const thumb = asset.thumbnail_url || (kind === "image" ? asset.url : "") || localThumb || "";
      el.thumb.hidden = !thumb;
      if (thumb) el.thumb.src = thumb;
      el.icon.hidden = !!thumb;
      const duration = asset.duration || (meta && meta.duration);
      el.duration.textContent = fmtDuration(duration);
      el.duration.hidden = !duration;
      if (el.open) {
        el.open.hidden = !asset.url;
        if (asset.url) el.open.href = asset.url;
      }
      this.root.dispatchEvent(new CustomEvent("uploader:change", { bubbles: true, detail: asset }));
      el.value.dispatchEvent(new Event("change", { bubbles: true }));
    }

    clear() {
      this.el.value.value = "";
      this.error("");
      this.restoreView();
      this.el.value.dispatchEvent(new Event("change", { bubbles: true }));
    }

    restoreView() {
      if (this.root.hasAttribute("data-busy")) return;
      const has = !!this.el.value.value;
      this.el.preview.hidden = !has;
      this.el.drop.hidden = has;
    }
  }

  /** Best-effort duration for an external MP4 (metadata loads cross-origin without CORS). */
  function probeDuration(url) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      v.preload = "metadata";
      v.muted = true;
      const timer = setTimeout(() => done(null), 6000);
      const done = (d) => { clearTimeout(timer); v.removeAttribute("src"); resolve(d); };
      v.addEventListener("loadedmetadata", () => done(isFinite(v.duration) ? v.duration : null), { once: true });
      v.addEventListener("error", () => done(null), { once: true });
      v.src = url;
    });
  }

  function init(root) {
    (root || document).querySelectorAll("[data-uploader]:not([data-uploader-ready])").forEach((el) => {
      el.setAttribute("data-uploader-ready", "1");
      el._uploader = new Uploader(el);
    });
  }

  // Don't submit a form while one of its uploads is still running.
  document.addEventListener("submit", (e) => {
    const busy = e.target.querySelector && e.target.querySelector("[data-uploader][data-busy]");
    if (busy) {
      e.preventDefault();
      e.stopImmediatePropagation();
      window.alert("Please wait until the upload has finished.");
    }
  }, true);
  window.addEventListener("beforeunload", (e) => {
    if (document.querySelector("[data-uploader][data-busy]")) { e.preventDefault(); e.returnValue = ""; }
  });

  window.skyleon = window.skyleon || {};
  window.skyleon.initUploaders = init;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init(document));
  else init(document);
})();

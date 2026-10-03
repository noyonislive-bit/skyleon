/* Admin panel — small progressive enhancements (no build step). */
(function () {
  "use strict";
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // Dependent selects: <select data-depends-on="project"> with <option data-parent="…"> -------------
  function initDependent(root) {
    $$("select[data-depends-on]", root).forEach((child) => {
      const form = child.form;
      const parent = form && form.elements[child.dataset.dependsOn];
      if (!parent || parent.tagName !== "SELECT") return;
      const sync = () => {
        const value = parent.value;
        let selectedHidden = false;
        Array.from(child.options).forEach((opt) => {
          const owner = opt.dataset.parent;
          const visible = !owner || (value && owner === value);
          opt.hidden = !visible;
          opt.disabled = !visible;
          if (!visible && opt.selected) selectedHidden = true;
        });
        if (selectedHidden) child.value = "";
      };
      parent.addEventListener("change", sync);
      sync();
    });
  }

  // People picker: search, count, select all shown, clear ------------------------------------------
  function initPickers(root) {
    $$("[data-picker]", root).forEach((picker) => {
      const search = picker.querySelector("[data-picker-search]");
      const items = $$("[data-picker-item]", picker);
      const counter = picker.querySelector("[data-picker-count]");
      const none = picker.querySelector("[data-picker-none]");
      const boxes = () => items.map((i) => i.querySelector("input"));
      const update = () => {
        const n = boxes().filter((b) => b && b.checked).length;
        if (counter) counter.textContent = items.length ? `${n} selected` : "";
      };
      const filter = () => {
        const q = (search.value || "").trim().toLowerCase();
        let shown = 0;
        items.forEach((item) => {
          const ok = !q || item.dataset.text.includes(q);
          item.hidden = !ok;
          if (ok) shown += 1;
        });
        if (none) none.hidden = shown > 0 || !items.length;
      };
      search && search.addEventListener("input", filter);
      search && search.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
      picker.addEventListener("change", update);
      const all = picker.querySelector("[data-picker-all]");
      const clear = picker.querySelector("[data-picker-clear]");
      all && all.addEventListener("click", () => { items.forEach((i) => { if (!i.hidden) i.querySelector("input").checked = true; }); update(); });
      clear && clear.addEventListener("click", () => { boxes().forEach((b) => (b.checked = false)); update(); });
      update();
    });
  }

  // Conditional fields: <div data-show-if="audience=selected"> ---------------------------------------
  function initConditional(root) {
    $$("[data-show-if]", root).forEach((el) => {
      const [name, value] = el.dataset.showIf.split("=");
      const form = el.closest("form");
      if (!form) return;
      const sync = () => {
        const field = form.elements[name];
        let current = "";
        if (field && typeof field.length === "number" && !field.tagName) {
          const checked = Array.from(field).find((f) => f.checked);
          current = checked ? checked.value : "";
        } else if (field) {
          current = field.type === "checkbox" ? (field.checked ? field.value : "") : field.value;
        }
        el.hidden = current !== value;
      };
      form.addEventListener("change", sync);
      sync();
    });
  }

  // HLS / MP4 preview players: <video data-src="…" data-hls> -----------------------------------------
  let hlsLoading = null;
  function loadHls(url) {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (!hlsLoading) {
      hlsLoading = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = url || "/static/vendor/hls.min.js";
        s.onload = () => resolve(window.Hls);
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    return hlsLoading;
  }
  function initPlayers(root) {
    $$("video[data-src]", root).forEach((video) => {
      const src = video.dataset.src;
      const isHls = video.hasAttribute("data-hls") || /\.m3u8(\?|$)/.test(src);
      if (!isHls || video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = src;
        return;
      }
      loadHls(video.dataset.hlsLib).then((Hls) => {
        if (Hls && Hls.isSupported()) {
          const hls = new Hls();
          hls.loadSource(src);
          hls.attachMedia(video);
        } else {
          video.src = src;
        }
      }).catch(() => { video.src = src; });
    });
  }

  // Select-all checkbox for tables: <input type=checkbox data-check-all="name"> -----------------------
  function initCheckAll(root) {
    $$("[data-check-all]", root).forEach((master) => {
      master.addEventListener("change", () => {
        $$(`input[type=checkbox][name="${master.dataset.checkAll}"]`).forEach((b) => (b.checked = master.checked));
      });
    });
  }

  // Character counter: <textarea data-count="300"> ---------------------------------------------------
  function initCounters(root) {
    $$("[data-count]", root).forEach((input) => {
      const max = parseInt(input.dataset.count, 10);
      const out = document.createElement("p");
      out.className = "help-text text-right font-mono";
      input.insertAdjacentElement("afterend", out);
      const sync = () => { out.textContent = `${input.value.length} / ${max}`; };
      input.addEventListener("input", sync);
      sync();
    });
  }

  function init(root) {
    initDependent(root);
    initPickers(root);
    initConditional(root);
    initPlayers(root);
    initCheckAll(root);
    initCounters(root);
  }

  window.skyleon = window.skyleon || {};
  window.skyleon.initAdmin = init;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init(document));
  else init(document);
})();

/* Work guide step editor: formatting snippets, "which button does what" rows, live video-link detection. */
(function () {
  "use strict";
  const form = document.querySelector("[data-guide-step-form]");
  if (!form) return;
  const $ = (sel, el = form) => el.querySelector(sel);
  const $$ = (sel, el = form) => Array.from(el.querySelectorAll(sel));

  // ── Snippets into the Bangla explanation ───────────────────────────────
  const body = $("textarea[name=body]");
  $$("[data-guide-snippet]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!body) return;
      const text = btn.dataset.guideSnippet;
      const start = body.selectionStart ?? body.value.length, end = body.selectionEnd ?? body.value.length;
      const before = body.value.slice(0, start), after = body.value.slice(end);
      const prefix = before && !before.endsWith("\n") && text.startsWith(">") ? "\n\n" : "";
      body.value = before + prefix + text + after;
      const pos = (before + prefix + text).length;
      body.focus();
      body.setSelectionRange(pos, pos);
    });
  });

  // ── Actions rows ⇄ JSON textarea ───────────────────────────────────────
  const raw = $("textarea[name=actions]");
  const list = $("[data-guide-actions]");
  const tpl = $("[data-guide-action-template]");
  function sync() {
    const rows = $$("[data-guide-action-row]", list).map((row) => {
      const o = {};
      $$("[data-k]", row).forEach((inp) => (o[inp.dataset.k] = inp.value.trim()));
      return o;
    }).filter((o) => o.key || o.label_bn || o.description_bn);
    raw.value = JSON.stringify(rows, null, 1);
  }
  function addRow(data) {
    const row = tpl.content.firstElementChild.cloneNode(true);
    $$("[data-k]", row).forEach((inp) => (inp.value = (data && data[inp.dataset.k]) || ""));
    $("[data-guide-action-remove]", row).addEventListener("click", () => { row.remove(); sync(); });
    $$("input", row).forEach((inp) => inp.addEventListener("input", sync));
    list.appendChild(row);
    return row;
  }
  if (raw && list && tpl) {
    let initial = [];
    try { initial = JSON.parse(raw.value || "[]"); } catch (_) { initial = null; }
    if (Array.isArray(initial)) {
      initial.forEach((r) => addRow(r));
      raw.addEventListener("change", () => {
        try {
          const rows = JSON.parse(raw.value || "[]");
          if (Array.isArray(rows)) { list.innerHTML = ""; rows.forEach((r) => addRow(r)); }
        } catch (_) { /* keep raw text; the server reports the error */ }
      });
    }
    $("[data-guide-action-add]").addEventListener("click", () => { const row = addRow(); $("input", row).focus(); sync(); });
  }

  // ── Video link detection + preview ─────────────────────────────────────
  const url = $("input[name=video_url]");
  const start = $("input[name=video_start]");
  const end = $("input[name=video_end]");
  const label = $("[data-guide-detect]");
  const preview = $("[data-guide-preview]");
  let timer = 0;
  async function detect() {
    const value = url.value.trim();
    if (!value) { label.hidden = true; preview.hidden = true; preview.innerHTML = ""; return; }
    try {
      const qs = new URLSearchParams({ url: value, start: start ? start.value : "", end: end ? end.value : "" });
      const res = await fetch("/admin/guides/video-info/?" + qs, { credentials: "same-origin" });
      const data = await res.json();
      label.hidden = false;
      label.textContent = data.ok ? data.label : "Not a valid http(s) link";
      label.className = "g-detect " + (data.ok ? (data.info && data.info.kind === "link" ? "is-warn" : "is-ok") : "is-bad");
      preview.hidden = !data.html;
      preview.innerHTML = data.html || "";
    } catch (_) { /* offline: ignore */ }
  }
  if (url && label && preview) {
    url.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(detect, 500); });
    if (start) start.addEventListener("change", detect);
    if (end) end.addEventListener("change", detect);
  }
})();

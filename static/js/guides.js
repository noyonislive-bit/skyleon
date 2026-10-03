/*
 * Work guides reader (/portal/guides/…): table of contents with scrollspy, smooth
 * scrolling + deep links, mobile TOC drawer, "বুঝেছি" (understood) progress without
 * reloads, copy-step-link, in-guide search, step-by-step mode keyboard navigation.
 * Everything degrades gracefully: links are plain #anchors and forms post normally.
 */
(function () {
  "use strict";

  const root = document.querySelector("[data-g-reader]");
  if (!root) return;
  const MODE = root.dataset.gMode || "doc"; // doc | step
  const $ = (sel, el = root) => el.querySelector(sel);
  const $$ = (sel, el = root) => Array.from(el.querySelectorAll(sel));
  const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
  const bn = (v) => String(v).replace(/[0-9]/g, (d) => BN_DIGITS[d]);
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const csrf = () => (window.skyleon && window.skyleon.csrfToken ? window.skyleon.csrfToken() : "");

  // ── Toast ──────────────────────────────────────────────────────────────
  const toastEl = $("[data-g-toast]");
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.hidden = false;
    toastEl.classList.add("is-visible");
    clearTimeout(toast.t);
    toast.t = setTimeout(() => { toastEl.classList.remove("is-visible"); toastEl.hidden = true; }, 2200);
  }

  // ── Scrolling helpers ──────────────────────────────────────────────────
  function headerOffset() {
    const bar = document.querySelector("header.sticky");
    const mbar = $(".g-mbar");
    let h = bar ? bar.getBoundingClientRect().height : 64;
    if (mbar && getComputedStyle(mbar).display !== "none") h += mbar.getBoundingClientRect().height;
    return h + 12;
  }
  function scrollToAnchor(anchor, { smooth = true, focus = true, flash = false } = {}) {
    const el = anchor && document.getElementById(anchor);
    if (!el) return false;
    const y = el.getBoundingClientRect().top + window.scrollY - headerOffset();
    window.scrollTo({ top: Math.max(0, y), behavior: smooth && !reduceMotion ? "smooth" : "auto" });
    if (history.replaceState) history.replaceState(null, "", "#" + anchor);
    if (focus && el.focus) el.focus({ preventScroll: true });
    if (flash && el.classList.contains("g-step")) {
      el.classList.remove("is-flash");
      void el.offsetWidth;
      el.classList.add("is-flash");
    }
    return true;
  }

  // ── TOC drawer (mobile) ────────────────────────────────────────────────
  const drawer = $("[data-g-drawer]");
  const backdrop = $("[data-g-backdrop]");
  const openers = $$("[data-g-drawer-open]");
  const isDrawerMode = () => window.matchMedia("(max-width: 1023.98px)").matches || MODE === "step";
  function setDrawer(open) {
    if (!drawer) return;
    drawer.classList.toggle("is-open", open);
    if (backdrop) backdrop.hidden = !open;
    openers.forEach((b) => b.setAttribute("aria-expanded", String(open)));
    document.body.classList.toggle("overflow-hidden", open);
    if (open) {
      const active = $(".g-toc-link.is-active, .g-toc-link[aria-current]", drawer);
      if (active) active.scrollIntoView({ block: "center" });
      const first = $("a, button, input", drawer);
      if (first) first.focus({ preventScroll: true });
    }
  }
  openers.forEach((b) => b.addEventListener("click", () => setDrawer(!drawer.classList.contains("is-open"))));
  $$("[data-g-drawer-close]").forEach((b) => b.addEventListener("click", () => setDrawer(false)));
  if (backdrop) backdrop.addEventListener("click", () => setDrawer(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && drawer && drawer.classList.contains("is-open")) setDrawer(false);
  });

  // ── In-page links (doc mode) ───────────────────────────────────────────
  if (MODE === "doc") {
    root.addEventListener("click", (e) => {
      const a = e.target.closest("a[href^='#']");
      if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey) return;
      const anchor = decodeURIComponent(a.getAttribute("href").slice(1));
      if (!anchor) return;
      if (a.hasAttribute("data-g-copy-link")) return; // handled below
      if (scrollToAnchor(anchor, { flash: a.hasAttribute("data-g-link") || a.hasAttribute("data-g-jump") })) {
        e.preventDefault();
        if (isDrawerMode()) setDrawer(false);
      }
    });
  }

  // ── Copy a step link ───────────────────────────────────────────────────
  $$("[data-g-copy-link]").forEach((a) => {
    a.addEventListener("click", async (e) => {
      e.preventDefault();
      const url = location.origin + location.pathname + a.getAttribute("href");
      try {
        await navigator.clipboard.writeText(url);
        toast("লিংক কপি হয়েছে");
      } catch (_) {
        window.prompt("এই লিংকটি কপি করুন:", url);
      }
    });
  });

  // ── Scrollspy + reading progress (doc mode) ────────────────────────────
  const readbar = $("[data-g-readbar]");
  const tocScroll = $("[data-g-toc-scroll]");
  const mbarTitle = $("[data-g-mbar-title]");
  const mbarEyebrow = $("[data-g-mbar-eyebrow]");
  const sections = $$("section.g-section");
  const spyTargets = $$("[data-g-spy]");
  let currentAnchor = null;

  function setActive(stepAnchor, sectionEl) {
    if (stepAnchor === currentAnchor) return;
    currentAnchor = stepAnchor;
    $$(".g-toc-link.is-active").forEach((l) => { l.classList.remove("is-active"); l.removeAttribute("aria-current"); });
    const secAnchor = sectionEl ? sectionEl.id : null;
    const links = [];
    if (stepAnchor) links.push(...$$(`[data-g-link="${CSS.escape(stepAnchor)}"]`));
    if (secAnchor) links.push(...$$(`[data-g-link="${CSS.escape(secAnchor)}"]`));
    links.forEach((l) => { l.classList.add("is-active"); if (l.classList.contains("is-step") || !stepAnchor) l.setAttribute("aria-current", "location"); });
    // keep the active TOC entry visible inside the (sticky) TOC without moving the page
    const active = stepAnchor ? $(`.g-toc-link.is-step[data-g-link="${CSS.escape(stepAnchor)}"]`, tocScroll || root) : null;
    if (tocScroll && active && !drawer.classList.contains("is-open")) {
      const box = tocScroll.getBoundingClientRect(), r = active.getBoundingClientRect();
      if (r.top < box.top + 8 || r.bottom > box.bottom - 8) tocScroll.scrollTop += r.top - box.top - box.height / 3;
    }
    if (sectionEl && mbarTitle) {
      const idx = sections.indexOf(sectionEl);
      const title = $(".g-sec-title", sectionEl) || $("h2", sectionEl);
      mbarTitle.textContent = title ? title.textContent.trim() : "";
      if (mbarEyebrow) mbarEyebrow.textContent = "অধ্যায় " + bn(idx + 1);
    }
  }

  function onScroll() {
    const line = headerOffset() + 24;
    let sectionEl = null, stepAnchor = null;
    for (const s of sections) { if (s.getBoundingClientRect().top <= line) sectionEl = s; else break; }
    for (const st of spyTargets) { if (st.getBoundingClientRect().top <= line) stepAnchor = st.dataset.gSpy; else break; }
    if (stepAnchor && sectionEl && !sectionEl.contains(document.getElementById(stepAnchor))) stepAnchor = null;
    if (!sectionEl && sections.length) sectionEl = sections[0];
    setActive(stepAnchor, sectionEl);
    if (readbar) {
      const main = $("[data-g-main]") || root;
      const rect = main.getBoundingClientRect();
      const total = rect.height - window.innerHeight + headerOffset();
      const pct = total > 0 ? Math.min(100, Math.max(0, ((headerOffset() - rect.top) / total) * 100)) : 0;
      readbar.style.width = pct + "%";
    }
  }
  if (MODE === "doc" && sections.length) {
    let raf = 0;
    window.addEventListener("scroll", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(onScroll); }, { passive: true });
    window.addEventListener("resize", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(onScroll); });
    onScroll();
  }

  // ── Initial deep link (#anchor or ?step=) ──────────────────────────────
  if (MODE === "doc") {
    const target = (location.hash ? decodeURIComponent(location.hash.slice(1)) : "") || root.dataset.gTarget || "";
    if (target) {
      const go = () => scrollToAnchor(target, { smooth: false, flash: true });
      if (document.readyState === "complete") go(); else window.addEventListener("load", go, { once: true });
      setTimeout(go, 50);
    }
    window.addEventListener("hashchange", () => scrollToAnchor(decodeURIComponent(location.hash.slice(1)), { flash: true }));
  }

  // ── "বুঝেছি" progress ──────────────────────────────────────────────────
  function firstUnreadAnchor() {
    const st = $$("[data-g-step]").find((el) => !el.classList.contains("is-done"));
    return st ? st.id : null;
  }
  function applyProgress(p) {
    const card = $(`[data-g-step="${p.stepId}"]`);
    if (card) {
      card.classList.toggle("is-done", p.done);
      const chip = $("[data-g-done-chip]", card);
      if (chip) chip.hidden = !p.done;
    }
    $$(`[data-g-done-form]`).forEach((form) => {
      if (!form.action.includes(`/step/${p.stepId}/done/`)) return;
      const btn = $("[data-g-done-btn]", form);
      const input = $("[data-g-done-input]", form);
      if (btn) btn.setAttribute("aria-pressed", String(p.done));
      if (input) input.value = p.done ? "0" : "1";
    });
    $$(`[data-g-step-id="${p.stepId}"]`).forEach((l) => {
      l.dataset.done = String(p.done);
      const sr = $("[data-g-sr-done]", l);
      if (sr) sr.textContent = p.done ? " (পড়া হয়েছে)" : "";
    });
    $$(`[data-g-seg="${p.stepId}"]`).forEach((li) => li.classList.toggle("is-done", p.done));
    if (p.section) {
      $$(`[data-g-sec-count="${CSS.escape(p.section.anchor)}"]`).forEach((el) => (el.textContent = bn(p.section.done) + "/" + bn(p.section.total)));
      $$(`.g-toc-link.is-section[data-g-link="${CSS.escape(p.section.anchor)}"]`).forEach((el) => (el.dataset.done = String(p.section.total > 0 && p.section.done >= p.section.total)));
    }
    $$("[data-g-done-count]").forEach((el) => (el.textContent = bn(p.doneCount)));
    $$("[data-g-percent]").forEach((el) => (el.textContent = bn(p.percent) + "%"));
    $$("[data-g-ring]").forEach((el) => { el.style.setProperty("--p", p.percent); el.classList.toggle("is-complete", p.complete); });
    $$("[data-g-progress]").forEach((el) => el.setAttribute("aria-valuenow", p.percent));
    $$("[data-g-progress-bar]").forEach((el) => { el.style.width = p.percent + "%"; el.classList.toggle("is-complete", p.complete); });
    const finDone = $("[data-g-finish-done]"), finTodo = $("[data-g-finish-todo]");
    if (finDone) finDone.hidden = !p.complete;
    if (finTodo) finTodo.hidden = p.complete;
    $$("[data-g-remaining]").forEach((el) => (el.textContent = bn(p.total - p.doneCount)));
    const unread = firstUnreadAnchor();
    $$("[data-g-first-unread]").forEach((a) => (a.href = "#" + (unread || "")));
    const note = $("[data-g-hero-note]");
    if (note) note.textContent = p.complete ? "পুরো গাইড পড়া শেষ।" : p.doneCount ? `আরও ${bn(p.total - p.doneCount)}টি ধাপ বাকি।` : "প্রথম ধাপ থেকে শুরু করুন।";
  }

  async function submitDone(form, e) {
    e.preventDefault();
    if (form.classList.contains("is-busy")) return;
    const input = $("[data-g-done-input]", form);
    const wantDone = input ? input.value === "1" : true;
    form.classList.add("is-busy");
    try {
      const res = await fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-CSRFToken": csrf() },
        body: JSON.stringify({ done: wantDone }),
      });
      if (!res.ok) throw new Error(res.status);
      const p = await res.json();
      applyProgress(p);
      if (MODE === "step") {
        if (form.hasAttribute("data-g-advance") && p.done && root.dataset.gNext) { location.href = root.dataset.gNext; return; }
        if (form.hasAttribute("data-g-advance") && p.done && !root.dataset.gNext) { toast(p.complete ? "অভিনন্দন! পুরো গাইড শেষ।" : "ধাপটি পড়া হয়েছে"); location.reload(); return; }
        location.reload();
        return;
      }
      if (p.done) {
        toast(p.complete ? "অভিনন্দন! পুরো গাইড শেষ।" : "চমৎকার! পরের ধাপে যাচ্ছি…");
        const card = form.closest("[data-g-step]");
        const next = card && $("[data-g-next]", card);
        if (next) setTimeout(() => scrollToAnchor(next.dataset.gNext, { flash: true }), 350);
      } else {
        toast("ধাপটি আবার অপঠিত হিসেবে রাখা হলো");
      }
    } catch (_) {
      form.submit(); // fall back to a normal POST
    } finally {
      form.classList.remove("is-busy");
    }
  }
  $$("[data-g-done-form], [data-g-undo-form]").forEach((form) => form.addEventListener("submit", (e) => submitDone(form, e)));

  // ── Search inside the guide (TOC filter) ───────────────────────────────
  const search = $("[data-g-search]");
  if (search) {
    const status = $("[data-g-search-status]");
    const empty = $("[data-g-search-empty]");
    const norm = (s) => s.toLocaleLowerCase().normalize("NFC").trim();
    const bodyText = {};
    $$("[data-g-step]").forEach((el) => (bodyText[el.id] = norm(el.textContent || "")));
    search.addEventListener("input", () => {
      const q = norm(search.value);
      let hits = 0;
      $$(".g-toc-sec", drawer || root).forEach((li) => {
        const secLink = $(".g-toc-link.is-section", li);
        const secMatch = !q || norm(secLink ? secLink.textContent : "").includes(q);
        let anyStep = false;
        $$(".g-toc-steps > li", li).forEach((sli) => {
          const link = $(".g-toc-link", sli);
          const anchor = link ? link.dataset.gLink : "";
          const match = !q || norm(link.textContent).includes(q) || (bodyText[anchor] || "").includes(q);
          sli.hidden = !(match || secMatch);
          if (match && q) hits++;
          anyStep = anyStep || match;
        });
        li.hidden = !(secMatch || anyStep);
        if (secMatch && q) hits++;
      });
      if (status) { status.hidden = !q; status.textContent = q ? `${bn(hits)}টি মিল পাওয়া গেছে` : ""; }
      if (empty) empty.hidden = !q || hits > 0;
    });
  }

  // ── Step mode: ← / → keys ──────────────────────────────────────────────
  if (MODE === "step") {
    document.addEventListener("keydown", (e) => {
      const tag = (e.target.tagName || "").toLowerCase();
      if (["input", "textarea", "select"].includes(tag) || e.target.isContentEditable || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "ArrowRight" && root.dataset.gNext) location.href = root.dataset.gNext;
      if (e.key === "ArrowLeft" && root.dataset.gPrev) location.href = root.dataset.gPrev;
    });
  }
})();

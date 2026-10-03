/* Skyloon AI employee portal — small progressive enhancements (no build step). */
(function () {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // A submitted test: drop its local answer draft (kept until now in case the submit failed).
  $$("[data-clear-test-draft]").forEach((el) => {
    try { window.localStorage.removeItem("skyleon:test-attempt:" + el.dataset.clearTestDraft); } catch (_) { /* ignore */ }
  });

  // Notification dropdown ---------------------------------------------------
  // The bell is a normal link to the notifications page; with JS it opens a
  // panel whose content is fetched (HTML fragment) the first time it opens.
  const wrap = $("[data-notif]");
  if (wrap) {
    const toggle = $("[data-notif-toggle]", wrap);
    const panel = $("[data-notif-panel]", wrap);
    let loaded = false;

    const setOpen = (open) => {
      panel.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      if (open && !loaded) load();
    };
    const load = async () => {
      loaded = true;
      try {
        const res = await fetch(panel.dataset.src, { credentials: "same-origin", headers: { "X-Requested-With": "fetch" } });
        if (res.redirected && /\/login\//.test(res.url)) { window.location.href = res.url; return; } // session expired
        if (!res.ok) throw new Error(res.statusText);
        panel.innerHTML = await res.text();
        $$("[data-next-here]", panel).forEach((input) => (input.value = window.location.pathname + window.location.search));
      } catch (_) {
        loaded = false;
        panel.innerHTML = '<p class="p-6 text-center text-sm text-slate-500">নোটিফিকেশন লোড করা যায়নি। <a class="font-medium text-brand-600" href="' +
          toggle.getAttribute("href") + '">পুরো তালিকা খুলুন</a></p>';
      }
    };
    toggle.addEventListener("click", (e) => {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return; // let modified clicks open the page
      e.preventDefault();
      setOpen(panel.hidden);
    });
    document.addEventListener("click", (e) => {
      if (!panel.hidden && !wrap.contains(e.target)) setOpen(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !panel.hidden) {
        setOpen(false);
        toggle.focus();
      }
    });
  }

  // Announcements: expanding a <details data-mark-read="url"> marks it read --
  $$("details[data-mark-read]").forEach((details) => {
    details.addEventListener("toggle", async () => {
      if (!details.open || details.dataset.read === "1") return;
      details.dataset.read = "1";
      try {
        const data = await window.skyleon.postJSON(details.dataset.markRead, {});
        details.classList.remove("is-unread");
        $$("[data-unread-marker]", details).forEach((el) => el.remove());
        $$("[data-unread-title]", details).forEach((el) => el.classList.remove("font-semibold", "text-slate-900"));
        const counter = $("[data-announcements-unread]");
        if (counter) {
          counter.textContent = data.unread;
          if (!data.unread) counter.closest("[data-unread-wrap]")?.remove();
        }
      } catch (_) {
        details.dataset.read = "0";
      }
    });
  });

  // Copy to clipboard with Bangla feedback: <button data-portal-copy="text"> --
  // (site.js's [data-copy] shows English text and loses icon-only content.)
  $$("[data-portal-copy]").forEach((btn) => {
    const original = { html: btn.innerHTML, title: btn.getAttribute("title"), label: btn.getAttribute("aria-label") };
    const iconOnly = !btn.textContent.trim();
    const restoreAttr = (name, value) => (value === null ? btn.removeAttribute(name) : btn.setAttribute(name, value));
    let timer = null;
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.portalCopy);
      } catch (_) {
        return;
      }
      if (iconOnly) btn.classList.add("text-emerald-600");
      else btn.textContent = "কপি হয়েছে";
      btn.setAttribute("title", "কপি হয়েছে");
      btn.setAttribute("aria-label", "কপি হয়েছে");
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        btn.innerHTML = original.html;
        btn.classList.remove("text-emerald-600");
        restoreAttr("title", original.title);
        restoreAttr("aria-label", original.label);
      }, 1400);
    });
  });

  // Keep the selected tab visible when tab bars overflow on small screens ---
  $$(".tabs .tab.is-active").forEach((tab) => {
    const bar = tab.parentElement;
    if (bar.scrollWidth > bar.clientWidth) bar.scrollLeft = Math.max(0, tab.offsetLeft - bar.clientWidth / 2 + tab.offsetWidth / 2);
  });
})();

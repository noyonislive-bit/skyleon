/* Skyloon AI — small progressive-enhancement helpers shared by every page. */
(function () {
  "use strict";
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // App-shell sidebar (portal / admin) -------------------------------------
  const sidebar = document.querySelector("[data-sidebar]");
  const backdrop = document.querySelector("[data-sidebar-backdrop]");
  const setSidebar = (open) => {
    if (!sidebar) return;
    sidebar.classList.toggle("-translate-x-full", !open);
    backdrop && backdrop.classList.toggle("hidden", !open);
    document.body.classList.toggle("overflow-hidden", open);
  };
  $$("[data-sidebar-open]").forEach((b) => b.addEventListener("click", () => setSidebar(true)));
  $$("[data-sidebar-close]").forEach((b) => b.addEventListener("click", () => setSidebar(false)));
  backdrop && backdrop.addEventListener("click", () => setSidebar(false));

  // Generic toggles: <button data-toggle="#id"> shows/hides the target ------
  $$("[data-toggle]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = document.querySelector(btn.dataset.toggle);
      if (!target) return;
      const open = target.hasAttribute("hidden");
      target.toggleAttribute("hidden", !open);
      btn.setAttribute("aria-expanded", String(open));
    });
  });

  // Dismissible alerts -----------------------------------------------------
  $$("[data-dismiss]").forEach((b) => b.addEventListener("click", () => b.closest(".alert")?.remove()));

  // Confirm before submitting dangerous forms: <form data-confirm="Sure?"> --
  document.addEventListener("submit", (e) => {
    const form = e.target;
    const msg = form.dataset && form.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  }, true);
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-confirm-click]");
    if (el && !window.confirm(el.dataset.confirmClick)) e.preventDefault();
  });

  // Auto-submit filter forms when a select/checkbox changes ----------------
  $$("form[data-autosubmit]").forEach((form) => {
    form.addEventListener("change", (e) => {
      if (e.target.matches("select, input[type=checkbox], input[type=radio], input[type=date]")) form.requestSubmit();
    });
  });

  // Copy to clipboard: <button data-copy="text"> ---------------------------
  $$("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(btn.dataset.copy);
        const old = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => (btn.textContent = old), 1400);
      } catch (_) { /* ignore */ }
    });
  });

  // Reveal-on-scroll for marketing sections: add class="reveal" -----------
  const reveals = $$(".reveal");
  if (reveals.length) {
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            io.unobserve(entry.target);
          }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
      reveals.forEach((el) => io.observe(el));
    } else {
      reveals.forEach((el) => el.classList.add("is-visible"));
    }
  }

  // Helper for fetch() calls that need Django's CSRF token -----------------
  window.skyleon = window.skyleon || {};
  window.skyleon.csrfToken = function () {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
    const input = document.querySelector("input[name=csrfmiddlewaretoken]");
    return input ? input.value : "";
  };
  window.skyleon.postJSON = async function (url, data) {
    const res = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": window.skyleon.csrfToken() },
      body: JSON.stringify(data || {}),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.error || res.statusText), { status: res.status, body });
    return body;
  };
})();

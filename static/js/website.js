/* Public marketing website — progressive enhancement only (everything works without JS). */
(function () {
  "use strict";
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  document.documentElement.classList.add("js");

  // Sticky header: transparent over the hero, solid once the page scrolls --------
  const header = document.querySelector("[data-site-header]");
  if (header) {
    let ticking = false;
    const update = () => {
      header.classList.toggle("is-scrolled", window.scrollY > 8);
      ticking = false;
    };
    window.addEventListener("scroll", () => {
      if (!ticking) { window.requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    update();
  }

  // Desktop dropdowns: click / keyboard toggle (hover is handled in CSS) ---------
  const items = $$("[data-nav-item]");
  const closeAll = (except) => items.forEach((item) => {
    if (item === except) return;
    item.classList.remove("is-open");
    const t = item.querySelector("[data-nav-trigger]");
    t && t.setAttribute("aria-expanded", "false");
  });
  items.forEach((item) => {
    const trigger = item.querySelector("[data-nav-trigger]");
    if (!trigger) return;
    trigger.addEventListener("click", (e) => {
      e.preventDefault();
      const open = !item.classList.contains("is-open");
      closeAll(item);
      item.classList.toggle("is-open", open);
      trigger.setAttribute("aria-expanded", String(open));
      if (open) {
        const first = item.querySelector(".nav-panel a");
        if (e.detail === 0 && first) window.setTimeout(() => first.focus(), 40); // keyboard activation
      }
    });
    item.addEventListener("mouseenter", () => trigger.setAttribute("aria-expanded", "true"));
    item.addEventListener("mouseleave", () => {
      if (!item.classList.contains("is-open")) trigger.setAttribute("aria-expanded", "false");
    });
    item.addEventListener("focusout", (e) => {
      if (!item.contains(e.relatedTarget)) {
        item.classList.remove("is-open");
        trigger.setAttribute("aria-expanded", "false");
      }
    });
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-nav-item]")) closeAll();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = items.find((i) => i.classList.contains("is-open"));
    if (open) {
      closeAll();
      const t = open.querySelector("[data-nav-trigger]");
      t && t.focus();
    }
    const mobile = document.querySelector("[data-mobile-nav][open]");
    if (mobile) {
      mobile.open = false;
      mobile.querySelector("summary").focus();
    }
  });

  // Mobile menu (<details>): scroll lock, aria state, close on link click --------
  const mobile = document.querySelector("[data-mobile-nav]");
  if (mobile) {
    const summary = mobile.querySelector("summary");
    const sync = () => {
      const open = mobile.open;
      document.body.classList.toggle("overflow-hidden", open);
      summary.setAttribute("aria-expanded", String(open));
      summary.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    };
    summary.setAttribute("aria-controls", "mobile-menu");
    mobile.addEventListener("toggle", sync);
    sync();
    $$("a", mobile).forEach((a) => a.addEventListener("click", () => { mobile.open = false; }));
    const mq = window.matchMedia("(min-width: 1280px)");
    const onChange = () => { if (mq.matches && mobile.open) mobile.open = false; };
    mq.addEventListener ? mq.addEventListener("change", onChange) : mq.addListener(onChange);
  }

  // File inputs inside .dropzone: show the selected file name and size ----------
  $$(".dropzone input[type=file]").forEach((input) => {
    const zone = input.closest(".dropzone");
    const label = zone.querySelector("[data-file-label]");
    const original = label ? label.textContent : "";
    input.addEventListener("change", () => {
      const f = input.files && input.files[0];
      zone.classList.toggle("has-file", !!f);
      if (!label) return;
      if (f) {
        const mb = f.size / (1024 * 1024);
        label.textContent = `${f.name} · ${mb < 0.1 ? "<0.1" : mb.toFixed(1)} MB`;
        const max = parseFloat(input.dataset.maxMb || "0");
        if (max && mb > max) {
          label.textContent += ` — too large (max ${max} MB)`;
          zone.classList.add("ring-2", "ring-red-300");
        } else {
          zone.classList.remove("ring-2", "ring-red-300");
        }
      } else {
        label.textContent = original;
      }
    });
  });

  // Prevent double submits on public forms -------------------------------------
  $$("form[data-public-form]").forEach((form) => {
    form.addEventListener("submit", () => {
      const btn = form.querySelector("button[type=submit]");
      if (!btn) return;
      window.setTimeout(() => {
        btn.disabled = true;
        btn.dataset.label = btn.innerHTML;
        btn.innerHTML = "Sending…";
      }, 0);
    });
  });
})();

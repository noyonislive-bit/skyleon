/*
 * Test taker (templates/portal/test_take.html)
 *  - live "answered" counter + question navigator
 *  - countdown (server-computed remaining seconds) that auto-submits at zero
 *  - confirmation dialog when submitting with unanswered questions
 *  - answers kept as a local draft (per attempt) so a reload doesn't lose them
 * The page never receives the correct answers — grading happens on the server.
 * Texts are Bangla (employee portal — see docs/BANGLA_STYLE.md).
 */
(function () {
  "use strict";
  const form = document.querySelector("[data-test-form]");
  if (!form) return;

  const questions = Array.from(form.querySelectorAll("[data-question]"));
  const dialog = document.querySelector("[data-confirm-dialog]");
  const autoField = form.querySelector("[data-auto-field]");
  const storageKey = "skyleon:test-attempt:" + form.dataset.attempt;
  let submitting = false;

  const isAnswered = (fs) => !!fs.querySelector("input:checked");
  const unanswered = () => questions.filter((fs) => !isAnswered(fs));

  // Draft --------------------------------------------------------------------
  const saveDraft = () => {
    const data = {};
    form.querySelectorAll("input[name^='q_']:checked").forEach((i) => {
      (data[i.name] = data[i.name] || []).push(i.value);
    });
    try { window.localStorage.setItem(storageKey, JSON.stringify(data)); } catch (_) { /* private mode */ }
  };
  const restoreDraft = () => {
    let data = null;
    try { data = JSON.parse(window.localStorage.getItem(storageKey) || "null"); } catch (_) { data = null; }
    if (!data) return;
    Object.keys(data).forEach((name) => {
      (data[name] || []).forEach((value) => {
        const input = form.querySelector('input[name="' + CSS.escape(name) + '"][value="' + CSS.escape(String(value)) + '"]');
        if (input) input.checked = true;
      });
    });
  };

  // Progress -----------------------------------------------------------------
  const counter = document.querySelector("[data-answered-count]");
  const hint = document.querySelector("[data-unanswered-hint]");
  const refresh = () => {
    let answered = 0;
    questions.forEach((fs) => {
      const done = isAnswered(fs);
      if (done) answered += 1;
      const nav = document.querySelector('[data-nav="' + fs.dataset.question + '"]');
      if (nav) {
        nav.classList.toggle("bg-brand-600", done);
        nav.classList.toggle("text-white", done);
        nav.classList.toggle("ring-brand-600", done);
        nav.classList.toggle("bg-slate-100", !done);
        nav.classList.toggle("text-slate-500", !done);
        nav.setAttribute("aria-label", "প্রশ্ন " + nav.textContent.trim() + (done ? " (উত্তর দেওয়া হয়েছে)" : " (উত্তর দেওয়া হয়নি)"));
      }
    });
    if (counter) counter.textContent = String(answered);
    if (hint) {
      const left = questions.length - answered;
      hint.textContent = left ? "এখনো " + left + "টি প্রশ্নের উত্তর দেওয়া হয়নি।" : "সব প্রশ্নের উত্তর দেওয়া হয়েছে।";
    }
  };
  form.addEventListener("change", (e) => {
    if (e.target.matches("input[name^='q_']")) {
      refresh();
      saveDraft();
    }
  });

  // Submit -------------------------------------------------------------------
  const reallySubmit = (auto) => {
    if (submitting) return;
    submitting = true;
    if (auto && autoField) autoField.value = "1";
    // The draft is kept until the result page confirms the submission (portal.js clears it there),
    // so answers survive a failed submit (expired session, network error).
    form.querySelectorAll("[data-submit]").forEach((b) => {
      b.disabled = true;
      b.textContent = "জমা হচ্ছে…";
    });
    form.submit(); // native submit — skips the submit handler below
  };

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (submitting) return;
    const missing = unanswered();
    if (!missing.length || !dialog || typeof dialog.showModal !== "function") {
      if (missing.length && !window.confirm(missing.length + "টি প্রশ্নের উত্তর দেওয়া হয়নি। তবুও জমা দেবেন?")) return;
      reallySubmit(false);
      return;
    }
    const n = missing.length;
    dialog.querySelector("[data-unanswered-count]").textContent = n + "টি প্রশ্নের";
    dialog.querySelector("[data-unanswered-list]").textContent =
      "প্রশ্ন নম্বর: " + missing.map((fs) => questions.indexOf(fs) + 1).join(", ");
    dialog.showModal();
  });

  if (dialog) {
    dialog.querySelector("[data-confirm-cancel]").addEventListener("click", () => {
      dialog.close();
      const first = unanswered()[0];
      if (first) {
        first.scrollIntoView({ behavior: "smooth", block: "start" });
        const input = first.querySelector("input");
        if (input) input.focus({ preventScroll: true });
      }
    });
    dialog.querySelector("[data-confirm-submit]").addEventListener("click", () => {
      dialog.close();
      reallySubmit(false);
    });
  }

  // Countdown ----------------------------------------------------------------
  const timer = document.querySelector("[data-timer]");
  const timerText = document.querySelector("[data-timer-text]");
  if (timer && form.dataset.remaining !== undefined) {
    const total = parseInt(form.dataset.remaining, 10) || 0;
    const started = performance.now();
    const fmt = (s) => {
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      const r = String(s % 60).padStart(2, "0");
      return h ? h + ":" + String(m).padStart(2, "0") + ":" + r : m + ":" + r;
    };
    let warned = false;
    const tick = () => {
      const left = Math.max(0, total - Math.floor((performance.now() - started) / 1000));
      if (timerText) timerText.textContent = fmt(left);
      if (left <= 60) {
        timer.classList.remove("bg-slate-100", "ring-slate-200", "text-slate-900");
        timer.classList.add("bg-red-50", "ring-red-200", "text-red-700");
        if (!warned) {
          warned = true;
          timer.setAttribute("aria-live", "assertive");
        }
      }
      if (left <= 0) {
        reallySubmit(true);
        return;
      }
      window.setTimeout(tick, 500);
    };
    tick();
  }

  restoreDraft();
  refresh();
})();

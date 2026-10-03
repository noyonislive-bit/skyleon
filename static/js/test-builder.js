/*
 * Admin panel — question builder (templates/backoffice/tests/_question_form.html).
 * Server-rendered Django formset for the answer options; this script only adds/removes rows,
 * switches the True/False editor and keeps single-answer questions to one correct option.
 */
(function () {
  "use strict";

  const MAX_OPTIONS = 12;

  function init(form) {
    const qtype = form.querySelector("select[name$='qtype']");
    const optionsBlock = form.querySelector("[data-options-block]");
    const tfBlock = form.querySelector("[data-tf-block]");
    const list = form.querySelector("[data-option-list]");
    const template = form.querySelector("template[data-option-template]");
    const addBtn = form.querySelector("[data-option-add]");
    const hint = form.querySelector("[data-options-hint]");
    const total = form.querySelector("input[name$='-TOTAL_FORMS']");
    if (!qtype || !list || !template || !total) return;

    const rows = () => Array.from(list.querySelectorAll("[data-option-row]")).filter((r) => !r.hidden);
    const correctBoxes = () => rows().map((r) => r.querySelector("input[type=checkbox][name$='-is_correct']")).filter(Boolean);

    function syncType() {
      const type = qtype.value;
      const tf = type === "true_false";
      optionsBlock.hidden = tf;
      tfBlock.hidden = !tf;
      if (hint) {
        hint.textContent = type === "multi"
          ? "Tick every correct answer — employees must select exactly those to score the points."
          : "Tick the one correct answer. Add an image to an option for “select the correct segmentation / description” questions.";
      }
      if (type === "single") {
        const checked = correctBoxes().filter((b) => b.checked);
        checked.slice(1).forEach((b) => (b.checked = false));
      }
      syncAdd();
    }

    function syncAdd() {
      if (addBtn) addBtn.disabled = rows().length >= MAX_OPTIONS;
    }

    function bindRow(row) {
      const remove = row.querySelector("[data-option-remove]");
      const imageBtn = row.querySelector("[data-option-image]");
      const media = row.querySelector("[data-option-media]");
      const del = row.querySelector("input[name$='-DELETE']");
      const box = row.querySelector("input[type=checkbox][name$='-is_correct']");
      remove && remove.addEventListener("click", () => {
        if (del) del.checked = true;
        if (box) box.checked = false;
        row.hidden = true;
        syncAdd();
      });
      imageBtn && media && imageBtn.addEventListener("click", () => {
        media.hidden = !media.hidden;
        if (!media.hidden) {
          const browse = media.querySelector("[data-uploader-browse]");
          if (browse && !media.querySelector("[data-uploader-value]").value) browse.click();
        }
      });
      box && box.addEventListener("change", () => {
        if (box.checked && qtype.value === "single") {
          correctBoxes().forEach((b) => { if (b !== box) b.checked = false; });
        }
      });
    }

    function addRow() {
      if (rows().length >= MAX_OPTIONS) return;
      const index = parseInt(total.value, 10) || 0;
      const html = template.innerHTML.replace(/__prefix__/g, String(index));
      const wrap = document.createElement("div");
      wrap.innerHTML = html.trim();
      const row = wrap.firstElementChild;
      list.appendChild(row);
      total.value = String(index + 1);
      bindRow(row);
      if (window.skyleon && window.skyleon.initUploaders) window.skyleon.initUploaders(row);
      const text = row.querySelector("input[name$='-text']");
      text && text.focus();
      syncAdd();
    }

    list.querySelectorAll("[data-option-row]").forEach(bindRow);
    addBtn && addBtn.addEventListener("click", addRow);
    qtype.addEventListener("change", syncType);

    // Enter in an option field adds the next option instead of submitting the form.
    list.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.matches("input[name$='-text']")) {
        e.preventDefault();
        const visible = rows();
        const current = e.target.closest("[data-option-row]");
        if (visible[visible.length - 1] === current) addRow();
        else {
          const next = visible[visible.indexOf(current) + 1];
          next && next.querySelector("input[name$='-text']").focus();
        }
      }
    });

    // Client-side check mirrors the server rules (the server validates again).
    form.addEventListener("submit", (e) => {
      if (qtype.value === "true_false") {
        if (!form.querySelector("input[name$='tf_answer']:checked")) {
          e.preventDefault();
          window.alert("Choose whether the statement is true or false.");
        }
        return;
      }
      const filled = rows().filter((r) => {
        const text = r.querySelector("input[name$='-text']");
        const media = r.querySelector("input[name$='-media']");
        return (text && text.value.trim()) || (media && media.value);
      });
      const correct = filled.filter((r) => r.querySelector("input[name$='-is_correct']").checked).length;
      let msg = "";
      if (filled.length < 2) msg = "Add at least two answer options.";
      else if (correct < 1) msg = "Mark at least one option as correct.";
      else if (qtype.value === "single" && correct !== 1) msg = "A single-answer question needs exactly one correct option.";
      if (msg) {
        e.preventDefault();
        window.alert(msg);
      }
    });

    syncType();
  }

  function boot() {
    document.querySelectorAll("form[data-question-form]").forEach(init);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();

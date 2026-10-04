/* Practice task form: upload a video straight to storage (or register an external URL)
   and select it in the "Video" field. Uses the /media/uploads API (see docs/ARCHITECTURE.md). */
(function () {
  "use strict";
  const box = document.querySelector("[data-practice-upload]");
  const select = document.getElementById("id_video");
  if (!box || !select) return;
  const fileInput = box.querySelector("[data-practice-file]");
  const progress = box.querySelector("[data-practice-progress]");
  const post = (url, data) => window.skyleon.postJSON(url, data);

  function readMeta(file) {
    return new Promise((resolve) => {
      const v = document.createElement("video");
      v.preload = "metadata";
      v.muted = true;
      v.src = URL.createObjectURL(file);
      v.onloadedmetadata = () => resolve({ duration: v.duration, width: v.videoWidth, height: v.videoHeight });
      v.onerror = () => resolve({});
    });
  }
  function sendXHR(method, url, body, headers, onProgress) {
    return new Promise((resolve, reject) => {
      const x = new XMLHttpRequest();
      x.open(method, url);
      Object.entries(headers || {}).forEach(([k, v]) => x.setRequestHeader(k, v));
      x.upload.onprogress = (e) => e.lengthComputable && onProgress && onProgress(e.loaded);
      x.onload = () => (x.status < 300 ? resolve(x) : reject(new Error(x.responseText || x.status)));
      x.onerror = () => reject(new Error("network error"));
      x.send(body);
    });
  }
  function choose(asset, label) {
    const opt = document.createElement("option");
    opt.value = asset.id;
    opt.textContent = label;
    select.appendChild(opt);
    select.value = asset.id;
  }

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    progress.textContent = "Preparing…";
    try {
      const meta = await readMeta(file);
      const init = await post("/media/uploads/init/", { filename: file.name, size: file.size, mime_type: file.type, kind: "video", purpose: "practice" });
      const pct = (n) => (progress.textContent = "Uploading… " + Math.round((n / file.size) * 100) + "%");
      if (init.mode === "put") {
        await sendXHR("PUT", init.url, file, init.headers, pct);
      } else {
        const csrf = window.skyleon.csrfToken();
        for (let off = 0; off < file.size; off += init.chunk_size) {
          const chunk = file.slice(off, off + init.chunk_size);
          let tries = 0;
          for (;;) {
            try {
              await sendXHR("POST", init.url, chunk, { "X-CSRFToken": csrf, "X-Chunk-Offset": String(off), "Content-Type": "application/octet-stream" }, (n) => pct(off + n));
              break;
            } catch (err) {
              if (++tries >= 3) throw err;
            }
          }
        }
      }
      const asset = await post("/media/uploads/" + init.id + "/complete/", { duration: meta.duration, width: meta.width, height: meta.height });
      choose(asset, file.name);
      progress.textContent = "Uploaded ✓ — remember to save the task.";
    } catch (err) {
      progress.textContent = "Upload failed: " + err.message;
    }
  });

  box.querySelector("[data-practice-url-add]").addEventListener("click", async () => {
    const url = box.querySelector("[data-practice-url]").value.trim();
    if (!url) return;
    try {
      const asset = await post("/media/external/", { url, purpose: "practice" });
      choose(asset, asset.name || url);
      progress.textContent = "External video added ✓ — remember to save the task.";
    } catch (err) {
      progress.textContent = "Could not add URL: " + err.message;
    }
  });
})();

/* Practice task form: the "Submit by" date only applies to weekly review tasks. */
(function () {
  "use strict";
  const box = document.querySelector("[data-review-only]");
  const radios = Array.from(document.querySelectorAll("input[name=kind]"));
  if (!box || !radios.length) return;
  const sync = () => { box.hidden = !radios.some((r) => r.checked && r.value === "review"); };
  radios.forEach((r) => r.addEventListener("change", sync));
  sync();
})();

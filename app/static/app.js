/* Label Verification — client
 *
 * No framework and no build step. The whole interface is one page with three
 * states, which does not justify a bundler, and a prototype a reviewer can run
 * with `uvicorn` alone is worth more than one that needs npm first.
 */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    dropzone: $("dropzone"), fileInput: $("file-input"), filelist: $("filelist"),
    modeForm: $("mode-form"), modeBatch: $("mode-batch"),
    singlePanel: $("single-panel"), batchPanel: $("batch-panel"),
    batchJson: $("batch-json"), loadSamples: $("load-samples"),
    verify: $("verify"), verifyHelp: $("verify-help"),
    results: $("results"), summary: $("summary"), cards: $("cards"),
    engine: $("engine"),
  };

  let files = [];
  let batchMode = false;

  const VERDICT = {
    match:    { word: "Match",    glyph: "\u2713" },
    review:   { word: "Review",   glyph: "\u26A0" },
    mismatch: { word: "Mismatch", glyph: "\u2715" },
  };

  const escapeHtml = (value) =>
    String(value).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const formatBytes = (bytes) =>
    bytes < 1024 * 1024
      ? `${Math.round(bytes / 1024)} KB`
      : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;

  // --- File selection ------------------------------------------------------

  function setFiles(incoming) {
    files = Array.from(incoming).filter((f) => f.type.startsWith("image/"));
    renderFileList();
    els.verify.disabled = files.length === 0;
    els.verifyHelp.textContent = files.length === 0
      ? "Choose at least one image first."
      : `${files.length} image${files.length === 1 ? "" : "s"} ready.`;
    if (files.length > 1 && !batchMode) setMode(true);
  }

  function renderFileList() {
    els.filelist.innerHTML = "";
    files.forEach((file) => {
      const li = document.createElement("li");
      const img = document.createElement("img");
      img.className = "thumb";
      img.alt = "";
      img.src = URL.createObjectURL(file);
      img.onload = () => URL.revokeObjectURL(img.src);
      const name = document.createElement("span");
      name.textContent = file.name;
      const size = document.createElement("span");
      size.className = "size";
      size.textContent = formatBytes(file.size);
      li.append(img, name, size);
      els.filelist.appendChild(li);
    });
  }

  els.fileInput.addEventListener("change", (e) => setFiles(e.target.files));

  ["dragenter", "dragover"].forEach((evt) =>
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.add("is-over");
    }));
  ["dragleave", "drop"].forEach((evt) =>
    els.dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      els.dropzone.classList.remove("is-over");
    }));
  els.dropzone.addEventListener("drop", (e) => setFiles(e.dataTransfer.files));

  // --- Mode ----------------------------------------------------------------

  function setMode(useBatch) {
    batchMode = useBatch;
    els.modeBatch.classList.toggle("is-active", useBatch);
    els.modeForm.classList.toggle("is-active", !useBatch);
    els.modeBatch.setAttribute("aria-pressed", String(useBatch));
    els.modeForm.setAttribute("aria-pressed", String(!useBatch));
    els.batchPanel.hidden = !useBatch;
    els.singlePanel.hidden = useBatch;
    if (useBatch && !els.batchJson.value.trim()) prefillBatch();
  }

  els.modeForm.addEventListener("click", () => setMode(false));
  els.modeBatch.addEventListener("click", () => setMode(true));

  function currentApplication() {
    const app = {
      brand_name: $("brand_name").value.trim(),
      class_type: $("class_type").value.trim(),
      alcohol_content: $("alcohol_content").value.trim(),
      net_contents: $("net_contents").value.trim(),
      beverage_type: $("beverage_type").value,
    };
    const bottler = $("bottler_name").value.trim();
    if (bottler) app.bottler_name = bottler;
    return app;
  }

  function prefillBatch() {
    const base = currentApplication();
    const records = (files.length ? files : [{ name: "label.jpg" }]).map((f) =>
      Object.assign({ filename: f.name }, base));
    els.batchJson.value = JSON.stringify(records, null, 2);
  }

  els.loadSamples.addEventListener("click", async () => {
    try {
      const response = await fetch("/api/sample-applications");
      const samples = await response.json();
      els.batchJson.value = JSON.stringify(samples, null, 2);
    } catch {
      prefillBatch();
    }
  });

  // --- Verification --------------------------------------------------------

  els.verify.addEventListener("click", async () => {
    if (!files.length) return;

    els.verify.disabled = true;
    els.verify.innerHTML = '<span class="spinner" aria-hidden="true"></span>Checking\u2026';
    els.results.hidden = false;
    els.summary.innerHTML = "";
    els.cards.innerHTML = "";

    const started = performance.now();
    const form = new FormData();

    try {
      let payload;
      if (batchMode || files.length > 1) {
        if (!els.batchJson.value.trim()) prefillBatch();
        files.forEach((f) => form.append("files", f));
        form.append("applications", els.batchJson.value);
        payload = await send("/api/verify-batch", form);
      } else {
        form.append("file", files[0]);
        form.append("application", JSON.stringify(currentApplication()));
        const single = await send("/api/verify", form);
        payload = {
          results: [single],
          total_ms: single.total_ms,
          counts: { [single.overall]: 1 },
        };
      }
      render(payload, performance.now() - started);
    } catch (error) {
      els.summary.innerHTML =
        `<p class="notice error">${escapeHtml(error.message)}</p>`;
    } finally {
      els.verify.disabled = false;
      els.verify.textContent = "Verify labels";
      els.results.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  async function send(url, form) {
    const response = await fetch(url, { method: "POST", body: form });
    if (!response.ok) {
      let detail = `The server returned ${response.status}.`;
      try {
        const body = await response.json();
        if (body.detail) detail = typeof body.detail === "string"
          ? body.detail : JSON.stringify(body.detail);
      } catch { /* keep the status message */ }
      throw new Error(detail);
    }
    return response.json();
  }

  // --- Rendering -----------------------------------------------------------

  function render(payload, wallClockMs) {
    const counts = payload.counts || {};
    const results = payload.results || [];

    // Sarah Chen's five second requirement is about how long an agent waits for
    // a label, so it is judged against the slowest individual label, not against
    // the batch. A 300 label import is a throughput question and is reported
    // separately as labels per second.
    const slowest = results.reduce((max, r) => Math.max(max, r.total_ms || 0), 0);
    const overTarget = slowest > 5000;
    const batchSeconds = (wallClockMs / 1000).toFixed(1);

    const throughput = results.length > 1
      ? `<span class="timing">${results.length} labels in ${batchSeconds}s
           (${(results.length / (wallClockMs / 1000)).toFixed(1)}/sec)</span>`
      : "";

    els.summary.innerHTML = `
      <div class="summary-bar">
        ${tally(counts.match || 0, "matched")}
        ${tally(counts.review || 0, "need review")}
        ${tally(counts.mismatch || 0, "mismatched")}
        ${throughput}
        <span class="timing${overTarget ? " is-slow" : ""}">slowest label
          ${(slowest / 1000).toFixed(1)}s${overTarget ? " \u2014 over the 5 second target" : ""}</span>
      </div>`;

    els.cards.innerHTML = results.map(card).join("");
  }

  const tally = (count, label) =>
    `<span class="tally"><strong>${count}</strong> ${label}</span>`;

  function card(result) {
    const verdict = VERDICT[result.overall];
    const body = result.error
      ? `<p class="notice error">${escapeHtml(result.error)}</p>`
      : `<ul class="checklist">${result.checks.map(row).join("")}</ul>`;
    const legibility = result.legibility_notes
      ? `<p class="notice">Image quality: ${escapeHtml(result.legibility_notes)}</p>` : "";

    return `
      <article class="card ${result.overall}">
        <div class="card-head">
          <span class="name">${escapeHtml(result.filename)}</span>
          ${stamp(result.overall)}
          <span class="timing">${(result.total_ms / 1000).toFixed(1)}s
            <span class="help" style="display:inline">(read ${result.extraction_ms}ms, compared ${result.comparison_ms}ms)</span>
          </span>
        </div>
        ${body}
        ${legibility}
      </article>`;
  }

  const stamp = (verdict) =>
    `<span class="stamp ${verdict}"><span class="glyph" aria-hidden="true">${VERDICT[verdict].glyph}</span>${VERDICT[verdict].word}</span>`;

  function row(check) {
    // Only show the side-by-side comparison when the values actually differ.
    // On a clean label the checklist should read as a clean checklist.
    const differs = check.verdict !== "match" || check.expected !== check.found;
    const comparison = differs && check.expected ? `
      <dl class="compare">
        <div><dt>Application</dt><dd>${escapeHtml(check.expected)}</dd></div>
        <div><dt>Label</dt><dd>${check.found ? escapeHtml(check.found) : "\u2014 not found \u2014"}</dd></div>
      </dl>` : "";

    return `
      <li>
        <div class="check-head">
          <span class="field-name">${escapeHtml(check.label)}</span>
          ${stamp(check.verdict)}
        </div>
        <p class="check-explanation">${escapeHtml(check.explanation)}</p>
        ${comparison}
      </li>`;
  }

  // --- Boot ----------------------------------------------------------------

  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      els.engine.textContent = h.live_model
        ? h.extractor
        : `${h.extractor} (offline sample mode \u2014 set ANTHROPIC_API_KEY for live extraction)`;
    })
    .catch(() => { els.engine.textContent = "unavailable"; });
})();

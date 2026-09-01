"use strict";

const form = document.querySelector("#estimate-form");
const accessoryList = document.querySelector("#accessory-list");
const loadDialog = document.querySelector("#load-dialog");
const ratesDialog = document.querySelector("#rates-dialog");
let defaults = null;
let rateLibrary = null;
let rateEntries = [];
let rateData = null;
let activeRateStamp = null;
let currentResults = null;
let projectId = null;
let revision = null;
let calculateTimer = null;
let toastTimer = null;

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

function getAtPath(object, path) {
  return path.split(".").reduce((value, part) => value?.[part], object);
}

function setAtPath(object, path, value) {
  const parts = path.split(".");
  let cursor = object;
  parts.slice(0, -1).forEach((part) => {
    cursor[part] ??= {};
    cursor = cursor[part];
  });
  cursor[parts.at(-1)] = value;
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function readForm() {
  const payload = clone(defaults || {});
  form.querySelectorAll("[data-path]").forEach((control) => {
    let value = control.value;
    if (control.type === "number") value = value === "" ? 0 : Number(value);
    setAtPath(payload, control.dataset.path, value);
  });
  payload.accessories = [...accessoryList.querySelectorAll(".accessory-row")].map((row) => ({
    description: row.querySelector('[data-accessory="description"]').value,
    stage: row.querySelector('[data-accessory="stage"]').value,
    quantity: Number(row.querySelector('[data-accessory="quantity"]').value || 0),
    unit_cost: Number(row.querySelector('[data-accessory="unit_cost"]').value || 0),
  }));
  payload.rate_library = activeRateStamp ? clone(activeRateStamp) : null;
  return payload;
}

function writeForm(payload) {
  form.querySelectorAll("[data-path]").forEach((control) => {
    const value = getAtPath(payload, control.dataset.path);
    control.value = value ?? "";
  });
  accessoryList.innerHTML = "";
  (payload.accessories || []).forEach(addAccessoryRow);
  syncConditionalFields();
  updateMainPanelCount();
}

function addAccessoryRow(item = {}) {
  const row = document.createElement("div");
  row.className = "accessory-row";
  row.innerHTML = `
    <label>Description<input data-accessory="description" type="text" value="${escapeAttribute(item.description || "")}" placeholder="Door, lightning protection, base ring…"></label>
    <label>Cost stage<select data-accessory="stage">
      <option value="manufacturing">Manufacturing</option>
      <option value="delivered">Delivered</option>
      <option value="installed">Installed</option>
      <option value="fully_loaded">Fully loaded</option>
    </select></label>
    <label>Quantity<input data-accessory="quantity" type="number" min="0" step="0.1" value="${Number(item.quantity ?? 1)}"></label>
    <label>Unit cost ($)<input data-accessory="unit_cost" type="number" min="0" step="10" value="${Number(item.unit_cost ?? 0)}"></label>
    <button class="remove-accessory" type="button" aria-label="Remove accessory">×</button>`;
  row.querySelector('[data-accessory="stage"]').value = item.stage || "manufacturing";
  row.querySelector(".remove-accessory").addEventListener("click", () => {
    row.remove();
    scheduleCalculate();
  });
  row.querySelectorAll("input, select").forEach((control) => {
    control.addEventListener("input", scheduleCalculate);
    control.addEventListener("change", scheduleCalculate);
  });
  accessoryList.append(row);
}

function escapeAttribute(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function scheduleCalculate() {
  document.querySelector("#save-status").textContent = revision ? `Revision ${revision} · modified` : "Unsaved estimate";
  updateMainPanelCount();
  clearTimeout(calculateTimer);
  calculateTimer = setTimeout(calculate, 180);
}

async function calculate() {
  const response = await fetch("/api/calculate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(readForm()),
  });
  const results = await response.json();
  currentResults = results;
  renderResults(results);
}

function renderResults(results) {
  const price = results.pricing || {};
  setText("selling-price", price.selling_price ? money.format(price.selling_price) : "—");
  setText("selected-cost", money.format(price.selected_cost || 0));
  setText("gross-margin", `${number.format(price.gross_margin_pct || 0)}%`);
  setText("gross-profit", money.format(price.gross_profit || 0));
  setText("markup", `${number.format(price.markup_pct || 0)}%`);
  setText("basis-label", `${titleCase((price.basis || "fully_loaded").replaceAll("_", " "))} basis`);
  setText("class-label", results.estimate_class || "ROM");

  ["low", "base", "high"].forEach((scenario) => {
    const value = results.scenarios?.[scenario]?.cost_bases?.fully_loaded || 0;
    setText(`scenario-${scenario}`, money.format(value));
  });

  const geo = results.geometry || {};
  setText("geo-height", `${number.format(geo.height_ft || 0)} ft`);
  setText("geo-base-diameter", `${number.format(geo.base_diameter_ft || 0)} ft`);
  setText("geo-truncation", `${number.format(geo.truncation_pct || 0)}%`);
  setText("geo-shell-area", `${number.format(geo.shell_area_sqft || 0)} ft²`);
  setText("geo-fabric-area", `${number.format(geo.purchased_membrane_area_sqft || 0)} ft²`);
  setText("geo-panel-area", `${number.format(geo.average_panel_area_sqft || 0)} ft²`);
  setText("geo-edge", `${number.format(geo.average_equilateral_edge_ft || 0)} ft`);
  const installDays = results.quantities?.installation_days || 0;
  setText("install-days", installDays ? `${installDays} crew-day${installDays === 1 ? "" : "s"}` : "Not included");

  renderMessages(results.errors || [], results.warnings || []);
  renderBreakdown(results.breakdown || {});
}

function renderMessages(errors, warnings) {
  const errorBox = document.querySelector("#errors");
  const warningBox = document.querySelector("#warnings");
  errorBox.innerHTML = errors.map((message) => `<div class="message error">${escapeHtml(message)}</div>`).join("");
  warningBox.innerHTML = warnings.map((message) => `<div class="message warning">${escapeHtml(message)}</div>`).join("");
  if (!errors.length && !warnings.length) {
    warningBox.innerHTML = '<div class="message ok">No estimate checks require attention.</div>';
  }
}

function renderBreakdown(breakdown) {
  const rows = Object.entries(breakdown)
    .filter(([, value]) => Number(value) !== 0)
    .map(([label, value]) => `<div class="breakdown-row"><span>${escapeHtml(label)}</span><strong>${money.format(value)}</strong></div>`)
    .join("");
  document.querySelector("#breakdown").innerHTML = rows || '<div class="empty-state">No costs entered.</div>';
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function titleCase(value) {
  return value.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function syncConditionalFields() {
  const frameMethod = document.querySelector("#frame-method").value;
  document.querySelector("#panel-set-fields").hidden = frameMethod !== "panel_set";
  document.querySelector("#component-fields").hidden = frameMethod !== "components";
  const pricingMode = document.querySelector("#pricing-mode").value;
  document.querySelector("#target-margin-field").hidden = pricingMode !== "target_margin";
  document.querySelector("#entered-price-field").hidden = pricingMode !== "entered_price";
}

function updateMainPanelCount() {
  const total = Number(document.querySelector('[data-path="geometry.total_panels"]').value || 0);
  const base = Number(document.querySelector('[data-path="geometry.total_base_panels"]').value || 0);
  setText("main-panel-count", Math.max(0, total - base).toLocaleString("en-US"));
}

async function saveEstimate() {
  const button = document.querySelector("#save-button");
  button.disabled = true;
  try {
    const response = await fetch("/api/estimates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, payload: readForm() }),
    });
    const data = await response.json();
    if (!response.ok) {
      currentResults = data;
      renderResults(data);
      showToast("Resolve estimate errors before saving.");
      return;
    }
    projectId = data.saved.project_id;
    revision = data.saved.revision;
    currentResults = data.results;
    renderResults(currentResults);
    document.querySelector("#save-status").textContent = `Revision ${revision} saved`;
    showToast(`Saved revision ${revision}.`);
  } catch (error) {
    showToast("Could not save the estimate.");
  } finally {
    button.disabled = false;
  }
}

async function openSavedEstimates() {
  const response = await fetch("/api/estimates");
  const data = await response.json();
  const container = document.querySelector("#saved-estimates");
  if (!data.estimates?.length) {
    container.innerHTML = '<div class="empty-state">No saved revisions yet.</div>';
  } else {
    container.innerHTML = data.estimates.map((item) => `
      <div class="saved-row">
        <div><strong>${escapeHtml(item.name)}</strong><small>${escapeHtml(item.customer || "No customer")} · Revision ${item.revision} · ${formatDate(item.created_at)}</small></div>
        <button class="button button-secondary" type="button" data-open-id="${item.id}">Open</button>
      </div>`).join("");
    container.querySelectorAll("[data-open-id]").forEach((button) => {
      button.addEventListener("click", () => loadEstimate(button.dataset.openId));
    });
  }
  loadDialog.showModal();
}

async function loadEstimate(id) {
  const response = await fetch(`/api/estimates/${encodeURIComponent(id)}`);
  const record = await response.json();
  if (!response.ok) {
    showToast(record.error || "Could not open estimate.");
    return;
  }
  projectId = record.project_id;
  revision = record.revision;
  activeRateStamp = record.payload.rate_library || null;
  writeForm(record.payload);
  renderRateStamp();
  currentResults = record.results;
  renderResults(record.results);
  document.querySelector("#save-status").textContent = `Revision ${revision} opened`;
  loadDialog.close();
  window.scrollTo({ top: 0, behavior: "smooth" });
  showToast(`Opened revision ${revision}.`);
}

function formatDate(value) {
  return new Date(value).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

function newEstimate() {
  if (!window.confirm("Start a new estimate? Unsaved changes will be discarded.")) return;
  projectId = null;
  revision = null;
  activeRateStamp = rateLibrary ? clone(rateLibrary) : defaults.rate_library || null;
  writeForm(defaults);
  renderRateStamp();
  document.querySelector("#save-status").textContent = "New estimate";
  calculate();
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}

function rateAttention(entry) {
  return entry.unvalidated || entry.stale;
}

function renderRateStamp() {
  const element = document.querySelector("#rate-stamp");
  const stamp = activeRateStamp;
  if (!stamp) {
    element.textContent = "No rate library stamp on this estimate.";
    element.className = "rate-stamp";
    return;
  }
  const parts = [`Rates v${stamp.version}`, `newest ${stamp.newest_effective_date}`];
  if (stamp.unvalidated) parts.push(`${stamp.unvalidated} unvalidated`);
  if (stamp.stale) parts.push(`${stamp.stale} overdue`);
  const behind = rateLibrary && rateLibrary.version !== stamp.version;
  if (behind) parts.push(`library v${rateLibrary.version} available`);
  element.textContent = parts.join(" · ");
  element.className = `rate-stamp${stamp.unvalidated || stamp.stale ? " caution" : ""}${behind ? " behind" : ""}`;
}

async function refreshRateLibrary() {
  const response = await fetch("/api/rates");
  const data = await response.json();
  rateData = data;
  rateLibrary = data.library;
  rateEntries = data.entries;
  renderRates();
  return data;
}

function renderRates() {
  const data = rateData;
  if (!data) return;
  const notice = document.querySelector("#rates-notice");
  notice.innerHTML = data.load_error
    ? `<div class="message warning">${escapeHtml(data.load_error)}</div>`
    : "";
  const stamp = data.library;
  document.querySelector("#rates-summary").textContent =
    `Version ${stamp.version} · ${stamp.total} rates · newest effective ${stamp.newest_effective_date} · ` +
    `${stamp.unvalidated} unvalidated · ${stamp.stale} past review date`;

  const attentionOnly = document.querySelector("#rates-attention-only").checked;
  const confidenceOptions = data.confidence_levels;
  const body = document.querySelector("#rates-body");
  const groups = data.categories
    .map((category) => {
      const entries = data.entries.filter(
        (entry) => entry.category === category && (!attentionOnly || rateAttention(entry)),
      );
      if (!entries.length) return "";
      return `<section class="rate-group"><h3>${escapeHtml(category)}</h3>${entries
        .map((entry) => rateRowMarkup(entry, confidenceOptions))
        .join("")}</section>`;
    })
    .join("");
  body.innerHTML = groups || '<div class="empty-state">No rates match this filter.</div>';

  body.querySelectorAll(".rate-row").forEach((row) => {
    const path = row.dataset.ratePath;
    const entry = data.entries.find((item) => item.path === path);
    row.querySelector('[data-rate="confidence"]').value = entry.confidence;
    row.querySelectorAll("input, select, textarea").forEach((control) => {
      control.addEventListener("input", updateRateDirtyState);
      control.addEventListener("change", updateRateDirtyState);
    });
  });
  updateRateDirtyState();
}

function rateRowMarkup(entry, confidenceOptions) {
  const badges = [
    entry.unvalidated ? '<span class="badge badge-caution">Unvalidated</span>' : "",
    entry.stale ? '<span class="badge badge-warn">Review overdue</span>' : "",
    entry.at_seed_value ? '<span class="badge badge-quiet">Seed value</span>' : "",
  ].join("");
  const options = confidenceOptions
    .map((option) => `<option value="${escapeAttribute(option.value)}">${escapeHtml(option.label)}</option>`)
    .join("");
  const maximum = entry.maximum === null ? "" : `max="${entry.maximum}"`;
  return `
    <div class="rate-row" data-rate-path="${escapeAttribute(entry.path)}">
      <div class="rate-head">
        <div class="rate-identity">
          <strong>${escapeHtml(entry.label)}</strong>
          <small>${escapeHtml(entry.unit)}${entry.help ? ` · ${escapeHtml(entry.help)}` : ""}</small>
        </div>
        <div class="rate-badges">${badges}</div>
      </div>
      <div class="rate-fields">
        <label class="field"><span>Value</span>
          <input data-rate="value" type="number" step="${entry.step}" min="${entry.minimum}" ${maximum} value="${entry.value}"></label>
        <label class="field"><span>Confidence</span>
          <select data-rate="confidence">${options}</select></label>
        <label class="field"><span>Effective</span>
          <input data-rate="effective_date" type="date" value="${escapeAttribute(entry.effective_date)}"></label>
        <label class="field"><span>Review by</span>
          <input data-rate="review_by" type="date" value="${escapeAttribute(entry.review_by)}"></label>
        <label class="field field-wide"><span>Source</span>
          <input data-rate="source" type="text" placeholder="Quote number, vendor, job number, or data set" value="${escapeAttribute(entry.source)}"></label>
        <label class="field field-wide"><span>Note</span>
          <input data-rate="note" type="text" placeholder="Scope, exclusions, validity window" value="${escapeAttribute(entry.note)}"></label>
      </div>
    </div>`;
}

function collectRateUpdates() {
  const updates = {};
  document.querySelectorAll("#rates-body .rate-row").forEach((row) => {
    const path = row.dataset.ratePath;
    const entry = rateEntries.find((item) => item.path === path);
    if (!entry) return;
    const proposed = {
      value: Number(row.querySelector('[data-rate="value"]').value || 0),
      confidence: row.querySelector('[data-rate="confidence"]').value,
      effective_date: row.querySelector('[data-rate="effective_date"]').value,
      review_by: row.querySelector('[data-rate="review_by"]').value,
      source: row.querySelector('[data-rate="source"]').value.trim(),
      note: row.querySelector('[data-rate="note"]').value.trim(),
    };
    const changed =
      proposed.value !== entry.value ||
      proposed.confidence !== entry.confidence ||
      proposed.effective_date !== entry.effective_date ||
      proposed.review_by !== (entry.review_by || "") ||
      proposed.source !== entry.source ||
      proposed.note !== (entry.note || "");
    row.classList.toggle("dirty", changed);
    if (changed) updates[path] = proposed;
  });
  return updates;
}

function updateRateDirtyState() {
  const count = Object.keys(collectRateUpdates()).length;
  document.querySelector("#rates-dirty").textContent = count
    ? `${count} unsaved rate change${count === 1 ? "" : "s"}`
    : "No unsaved rate changes";
}

async function openRates() {
  document.querySelector("#rates-history-panel").hidden = true;
  await refreshRateLibrary();
  ratesDialog.showModal();
}

async function saveRates() {
  const updates = collectRateUpdates();
  const notice = document.querySelector("#rates-notice");
  if (!Object.keys(updates).length) {
    showToast("No rate changes to save.");
    return;
  }
  const button = document.querySelector("#rates-save");
  button.disabled = true;
  try {
    const response = await fetch("/api/rates", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        updates,
        changed_by: document.querySelector("#rates-changed-by").value.trim(),
        reason: document.querySelector("#rates-reason").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      const details = data.details || [data.error || "The rate change was rejected."];
      notice.innerHTML = details
        .map((message) => `<div class="message error">${escapeHtml(message)}</div>`)
        .join("");
      return;
    }
    rateData = data;
    rateLibrary = data.library;
    rateEntries = data.entries;
    renderRates();
    document.querySelector("#rates-reason").value = "";
    const refreshed = await fetch("/api/defaults");
    defaults = await refreshed.json();
    renderRateStamp();
    showToast(
      `Saved ${data.changes.length} rate change${data.changes.length === 1 ? "" : "s"} as library v${data.library.version}. The open estimate keeps its values.`,
    );
  } catch (error) {
    notice.innerHTML = '<div class="message error">Could not save the rate library.</div>';
  } finally {
    button.disabled = false;
  }
}

function applyLibraryToEstimate() {
  const changed = rateEntries.filter((entry) => {
    const control = form.querySelector(`[data-path="${entry.path}"]`);
    return control && Number(control.value) !== entry.value;
  });
  if (!changed.length) {
    showToast("The open estimate already matches the library.");
    return;
  }
  const preview = changed
    .slice(0, 6)
    .map((entry) => `• ${entry.label}: ${entry.value}`)
    .join("\n");
  const suffix = changed.length > 6 ? `\n…and ${changed.length - 6} more` : "";
  if (!window.confirm(`Overwrite ${changed.length} value(s) in the open estimate?\n\n${preview}${suffix}`)) {
    return;
  }
  changed.forEach((entry) => {
    const control = form.querySelector(`[data-path="${entry.path}"]`);
    if (control) control.value = entry.value;
  });
  activeRateStamp = clone(rateLibrary);
  renderRateStamp();
  ratesDialog.close();
  scheduleCalculate();
  showToast(`Applied library v${rateLibrary.version} to the open estimate.`);
}

async function toggleRateHistory() {
  const panel = document.querySelector("#rates-history-panel");
  if (!panel.hidden) {
    panel.hidden = true;
    return;
  }
  const response = await fetch("/api/rates/history?limit=100");
  const data = await response.json();
  const records = data.history || [];
  panel.innerHTML = records.length
    ? `<h3>Change log</h3>${records
        .map(
          (record) => `
      <div class="history-row">
        <div><strong>${escapeHtml(record.label || record.path)}</strong>
          <small>${escapeHtml(String(record.previous_value))} → ${escapeHtml(String(record.value))} ${escapeHtml(record.unit || "")}</small></div>
        <div class="history-meta">
          <span>v${escapeHtml(String(record.library_version))} · ${formatDate(record.timestamp)}</span>
          <span>${escapeHtml(record.previous_confidence || "")} → ${escapeHtml(record.confidence || "")}${record.changed_by ? ` · ${escapeHtml(record.changed_by)}` : ""}</span>
          ${record.source ? `<span>${escapeHtml(record.source)}</span>` : ""}
          ${record.reason ? `<span>${escapeHtml(record.reason)}</span>` : ""}
        </div>
      </div>`,
        )
        .join("")}`
    : '<h3>Change log</h3><div class="empty-state">No rate changes recorded yet.</div>';
  panel.hidden = false;
}

async function initialize() {
  try {
    const response = await fetch("/api/defaults");
    defaults = await response.json();
    activeRateStamp = defaults.rate_library || null;
    writeForm(defaults);
    renderRateStamp();
    await calculate();
    await refreshRateLibrary();
    renderRateStamp();
  } catch (error) {
    renderMessages(["The local calculation service is unavailable."], []);
  }
}

form.addEventListener("input", scheduleCalculate);
form.addEventListener("change", () => { syncConditionalFields(); scheduleCalculate(); });
document.querySelector("#add-accessory").addEventListener("click", () => { addAccessoryRow(); scheduleCalculate(); });
document.querySelector("#save-button").addEventListener("click", saveEstimate);
document.querySelector("#load-button").addEventListener("click", openSavedEstimates);
document.querySelector("#new-button").addEventListener("click", newEstimate);
document.querySelector("#print-button").addEventListener("click", () => window.print());
document.querySelector("#close-dialog").addEventListener("click", () => loadDialog.close());
document.querySelector("#rates-button").addEventListener("click", openRates);
document.querySelector("#close-rates").addEventListener("click", () => ratesDialog.close());
document.querySelector("#rates-save").addEventListener("click", saveRates);
document.querySelector("#rates-apply").addEventListener("click", applyLibraryToEstimate);
document.querySelector("#rates-history-button").addEventListener("click", toggleRateHistory);
document.querySelector("#rates-attention-only").addEventListener("change", renderRates);
ratesDialog.addEventListener("click", (event) => { if (event.target === ratesDialog) ratesDialog.close(); });
loadDialog.addEventListener("click", (event) => { if (event.target === loadDialog) loadDialog.close(); });

initialize();

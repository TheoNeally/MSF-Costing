"use strict";

const form = document.querySelector("#estimate-form");
const accessoryList = document.querySelector("#accessory-list");
const loadDialog = document.querySelector("#load-dialog");
let defaults = null;
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
  writeForm(record.payload);
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
  writeForm(defaults);
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

async function initialize() {
  try {
    const response = await fetch("/api/defaults");
    defaults = await response.json();
    writeForm(defaults);
    await calculate();
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
loadDialog.addEventListener("click", (event) => { if (event.target === loadDialog) loadDialog.close(); });

initialize();

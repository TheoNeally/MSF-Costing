import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const playwrightPath = process.argv[2];
const chromePath = process.argv[3];
const screenshotDirectory = process.argv[4] || process.cwd();

if (!playwrightPath) throw new Error("Pass the path to Playwright's index.mjs");
const { chromium } = await import(pathToFileURL(playwrightPath).href);

const port = 8876;
const baseUrl = `http://127.0.0.1:${port}`;
const temporary = await mkdtemp(path.join(tmpdir(), "msf-costing-smoke-"));
const database = path.join(temporary, "smoke.db");
const server = spawn(
  "python",
  ["app.py", "--no-browser", "--port", String(port), "--database", database],
  { cwd: process.cwd(), windowsHide: true, stdio: ["ignore", "pipe", "pipe"] },
);

let browser;
const consoleErrors = [];
try {
  let ready = false;
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(`${baseUrl}/api/health`);
      if (response.ok) { ready = true; break; }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  if (!ready) throw new Error("Local server did not become ready");

  browser = await chromium.launch({
    headless: true,
    ...(chromePath ? { executablePath: chromePath } : {}),
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector("#selling-price:not(:has-text('—'))");
  if (await page.locator("#entered-price-field").isVisible()) {
    throw new Error("Inactive entered-price field should be hidden");
  }
  if (await page.locator("#component-fields").isVisible()) {
    throw new Error("Inactive component frame fields should be hidden");
  }
  await page.locator("#frame-method").selectOption("components");
  if (!(await page.locator("#component-fields").isVisible())) {
    throw new Error("Component frame fields did not appear");
  }
  await page.locator("#frame-method").selectOption("panel_set");
  await page.locator("#pricing-mode").selectOption("entered_price");
  if (!(await page.locator("#entered-price-field").isVisible())) {
    throw new Error("Entered-price field did not appear");
  }
  if (await page.locator("#target-margin-field").isVisible()) {
    throw new Error("Inactive target-margin field should be hidden");
  }
  await page.locator('[data-path="pricing.entered_price"]').fill("200000");
  await page.locator("#pricing-mode").selectOption("target_margin");
  await page.waitForTimeout(300);
  const initialPrice = await page.locator("#selling-price").innerText();
  if (!initialPrice.startsWith("$")) throw new Error("Initial price did not render");

  await page.locator('[data-path="geometry.total_panels"]').fill("100");
  await page.waitForTimeout(500);
  const updatedPrice = await page.locator("#selling-price").innerText();
  if (updatedPrice === initialPrice) throw new Error("Live recalculation did not update price");

  await page.locator("#add-accessory").click();
  const accessory = page.locator(".accessory-row").last();
  await accessory.locator('[data-accessory="description"]').fill("Visual smoke test door");
  await accessory.locator('[data-accessory="quantity"]').fill("2");
  await accessory.locator('[data-accessory="unit_cost"]').fill("1000");
  await page.waitForTimeout(500);

  await page.locator("#save-button").click();
  await page.waitForSelector("#save-status:text-is('Revision 1 saved')");
  await page.locator("#load-button").click();
  await page.waitForSelector("#load-dialog[open] .saved-row");
  await page.locator("#close-dialog").click();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);

  await page.screenshot({
    path: path.join(screenshotDirectory, "msf-costing-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(screenshotDirectory, "msf-costing-mobile.png"),
    fullPage: true,
  });

  if (consoleErrors.length) {
    throw new Error(`Browser console errors: ${consoleErrors.join(" | ")}`);
  }
  process.stdout.write(
    JSON.stringify({ ok: true, initialPrice, updatedPrice, consoleErrors }, null, 2),
  );
} finally {
  if (browser) await browser.close();
  server.kill();
  await new Promise((resolve) => server.once("exit", resolve));
  await rm(temporary, { recursive: true, force: true });
}

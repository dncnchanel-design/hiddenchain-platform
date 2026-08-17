import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:5173";
const browserExecutable = process.env.BROWSER_EXECUTABLE;
const allowTestCopy = /^(1|true|yes)$/i.test(process.env.UI_ALLOW_TEST_COPY || "");
const outputDir = resolve(process.env.UI_QA_OUTPUT || "runtime/visual-regression");
const viewports = [
  { width: 1366, height: 768, code: "1366x768" },
  { width: 1440, height: 900, code: "1440x900" },
  { width: 1920, height: 1080, code: "1920x1080" },
];
const credentials = {
  exchange: ["exchange", "exchange123"],
  generator: ["generator", "generator123"],
  admin: ["admin", "admin123"],
};
function exchangeRoutes(taskId) {
  const query = `task_id=${encodeURIComponent(taskId)}`;
  return [
  "/workbench",
  `/data-space?${query}`,
  "/data/generation",
  "/data/retail",
  `/rules?${query}`,
  `/compute?${query}`,
  "/settlements",
  "/settlements/new",
  `/settlements/${encodeURIComponent(taskId)}`,
  `/results?${query}`,
  `/evidence?${query}`,
  `/audit?${query}`,
  `/reports?${query}`,
  `/anomalies?${query}`,
  ];
}
const adminRoutes = ["/overview", "/system", "/agents", "/metrics", "/logs"];
const bannedVisibleCopy = /演示|模拟|\bmock\b|\bmvp\b|占位/i;

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: browserExecutable || undefined,
  args: ["--disable-gpu", "--force-device-scale-factor=1"],
});
const results = [];

function fileCode(path) {
  const value = path.replace(/^\//, "").replace(/[?=&/]+/g, "-");
  return value || "root";
}

async function settle(page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
  await page.locator(".route-loading").waitFor({ state: "detached", timeout: 12_000 }).catch(() => {});
}

async function login(viewport, role) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  const [username, password] = credentials[role];
  await page.goto(`${baseUrl}/login`);
  await settle(page);
  await page.locator('input[autocomplete="username"]').fill(username);
  await page.locator('input[autocomplete="current-password"]').fill(password);
  await page.getByRole("button", { name: "登录" }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 15_000 });
  await settle(page);
  return { context, page };
}

async function resolveTaskId(page) {
  return page.evaluate(async () => {
    const token = sessionStorage.getItem("hiddenchain_token");
    const response = await fetch("/api/settlement/tasks", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new Error(`Unable to load settlement tasks (${response.status})`);
    const tasks = await response.json();
    const preferred = tasks.find((item) => item.status !== "AUDITED") || tasks[0];
    if (!preferred?.task_id) throw new Error("No settlement task is available for UI regression");
    return preferred.task_id;
  });
}

async function inspect(page, path, viewport, role, screenshot = true) {
  const consoleErrors = [];
  const handler = (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  };
  page.on("console", handler);
  await page.goto(`${baseUrl}${path}`);
  await settle(page);
  const metrics = await page.evaluate(() => ({
    href: window.location.href,
    title: document.title,
    bodyText: document.body.innerText,
    innerWidth: window.innerWidth,
    bodyScrollWidth: document.documentElement.scrollWidth,
    h1: document.querySelector("h1")?.textContent?.trim() || "",
  }));
  const overflow = metrics.bodyScrollWidth > metrics.innerWidth + 1;
  const banned = allowTestCopy ? "" : metrics.bodyText.match(bannedVisibleCopy)?.[0] || "";
  const filename = `${viewport.code}-${role}-${fileCode(path)}.png`;
  if (screenshot) {
    await page.screenshot({ path: resolve(outputDir, filename), fullPage: false, animations: "disabled" });
  }
  page.off("console", handler);
  results.push({
    viewport: viewport.code,
    role,
    path,
    finalUrl: metrics.href,
    title: metrics.title,
    h1: metrics.h1,
    overflow,
    bannedVisibleCopy: banned,
    consoleErrors,
    screenshot: screenshot ? filename : null,
  });
}

async function inspectSettlementMenu(page, viewport) {
  await page.goto(`${baseUrl}/workbench`);
  await settle(page);
  const trigger = page.locator(".primary-navigation-trigger").filter({ hasText: "结算管理" }).first();
  await trigger.hover();
  await page.locator(".primary-navigation-menu").first().waitFor({ state: "visible", timeout: 5_000 });
  const filename = `${viewport.code}-exchange-settlement-menu.png`;
  await page.screenshot({ path: resolve(outputDir, filename), fullPage: false, animations: "disabled" });
  results.push({ viewport: viewport.code, role: "exchange", specialState: "settlement-menu", screenshot: filename });
}

async function inspectTrustedChain(page, viewport, taskId) {
  await page.goto(`${baseUrl}/settlements/${encodeURIComponent(taskId)}`);
  await settle(page);
  const chain = page.locator(".trusted-chain");
  await chain.waitFor({ state: "visible", timeout: 8_000 });
  await chain.evaluate((element) => window.scrollTo({ top: element.getBoundingClientRect().top + window.scrollY - 148 }));
  const filename = `${viewport.code}-exchange-trusted-chain.png`;
  await page.screenshot({ path: resolve(outputDir, filename), fullPage: false, animations: "disabled" });
  results.push({ viewport: viewport.code, role: "exchange", specialState: "trusted-chain", screenshot: filename });
}

try {
  for (const viewport of viewports) {
    const anonymous = await browser.newContext({ viewport });
    const loginPage = await anonymous.newPage();
    await inspect(loginPage, "/login", viewport, "anonymous");
    await anonymous.close();

    const exchange = await login(viewport, "exchange");
    const taskId = await resolveTaskId(exchange.page);
    for (const path of exchangeRoutes(taskId)) await inspect(exchange.page, path, viewport, "exchange");
    await inspectSettlementMenu(exchange.page, viewport);
    await inspectTrustedChain(exchange.page, viewport, taskId);
    await exchange.page.goto(`${baseUrl}/system`);
    await settle(exchange.page);
    results.push({ viewport: viewport.code, role: "exchange", permissionCheck: "/system", finalPath: new URL(exchange.page.url()).pathname });
    await exchange.context.close();

    const admin = await login(viewport, "admin");
    for (const path of adminRoutes) await inspect(admin.page, path, viewport, "admin");
    await admin.page.goto(`${baseUrl}/settlements/new`);
    await settle(admin.page);
    results.push({ viewport: viewport.code, role: "admin", permissionCheck: "/settlements/new", finalPath: new URL(admin.page.url()).pathname });
    await admin.context.close();

    const generator = await login(viewport, "generator");
    await inspect(generator.page, `/results?task_id=${encodeURIComponent(taskId)}`, viewport, "generator");
    await generator.page.goto(`${baseUrl}/rules`);
    await settle(generator.page);
    results.push({ viewport: viewport.code, role: "generator", permissionCheck: "/rules", finalPath: new URL(generator.page.url()).pathname });
    await generator.context.close();
  }
} finally {
  await browser.close();
}

const pageResults = results.filter((item) => item.path);
const permissionResults = results.filter((item) => item.permissionCheck);
const specialStateResults = results.filter((item) => item.specialState);
const failures = [
  ...pageResults.filter((item) => item.overflow || item.bannedVisibleCopy || item.consoleErrors.length || item.finalUrl.includes("/403")),
  ...permissionResults.filter((item) => item.finalPath !== "/403"),
];
const report = {
  generatedAt: new Date().toISOString(),
  baseUrl,
  fixtureCopyAllowed: allowTestCopy,
  viewports: viewports.map((item) => item.code),
  pageCount: pageResults.length,
  permissionCheckCount: permissionResults.length,
  specialStateCount: specialStateResults.length,
  failureCount: failures.length,
  failures,
  results,
};
await writeFile(resolve(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputDir, pageCount: report.pageCount, permissionCheckCount: report.permissionCheckCount, failureCount: report.failureCount }, null, 2));
if (failures.length) process.exitCode = 1;

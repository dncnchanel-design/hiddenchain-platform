import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:5173";
const outputDir = resolve(process.env.UI_TRUSTED_OUTPUT || "runtime/trusted-space-regression");
const credentials = process.env.UI_ROLE === "regulator"
  ? ["regulator", "regulator123"]
  : ["exchange", "exchange123"];
const routes = [
  "/trusted-space/workbench",
  "/trusted-space/query",
  "/trusted-space/catalog",
  "/trusted-space/connector",
  "/trusted-space/authorizations",
  "/trusted-space/identity",
  "/trusted-space/ttc",
  "/trusted-space/mpc",
  "/trusted-space/results",
  "/trusted-space/audit",
];

const results = [];
const failures = [];

function record(name, details = {}) {
  results.push({ name, ...details });
}

function fail(name, error, details = {}) {
  failures.push({ name, error: error instanceof Error ? error.message : String(error), ...details });
}

async function settle(page, selector = ".trusted-page") {
  await page.waitForLoadState("domcontentloaded");
  await page.locator(selector).waitFor({ state: "visible", timeout: 12_000 });
  await page.waitForLoadState("networkidle", { timeout: 6_000 }).catch(() => {});
}

async function login(page) {
  await page.goto(`${baseUrl}/login`);
  await page.locator('input[autocomplete="username"]').fill(credentials[0]);
  await page.locator('input[autocomplete="current-password"]').fill(credentials[1]);
  const started = Date.now();
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL((url) => url.pathname.startsWith("/trusted-space/"), { timeout: 15_000 });
  await settle(page);
  record("login", { kind: "login", duration_ms: Date.now() - started, path: new URL(page.url()).pathname });
}

async function visit(page, path) {
  const started = Date.now();
  await page.goto(`${baseUrl}${path}`);
  await settle(page);
  const duration = Date.now() - started;
  const finalPath = new URL(page.url()).pathname;
  const body = await page.locator("body").innerText();
  if (finalPath !== path || /页面不存在|服务暂时不可用|可信数据空间上下文不可用|权限不足/.test(body)) {
    throw new Error(`最终路径 ${finalPath}，页面包含异常或未到达目标`);
  }
  record("route", { kind: "route", path, finalPath, duration_ms: duration });
}

async function measureButton(page, name, trigger, ready) {
  const started = Date.now();
  await trigger();
  await ready();
  record(name, { kind: "button", duration_ms: Date.now() - started });
}

async function run() {
  await mkdir(outputDir, { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.BROWSER_EXECUTABLE || undefined,
    args: ["--disable-gpu", "--force-device-scale-factor=1"],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const consoleErrors = [];
  const httpErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() >= 400) httpErrors.push({ status: response.status(), url: response.url() });
  });
  try {
    await login(page);
    for (const path of routes) {
      try {
        await visit(page, path);
      } catch (error) {
        fail("route", error, { path });
      }
    }

    await page.goto(`${baseUrl}/trusted-space/catalog?focus=search`);
    await settle(page);
    await measureButton(
      page,
      "打开数据目录搜索",
      async () => page.locator('input[aria-label="搜索数据资产"]').focus(),
      async () => page.locator('input[aria-label="搜索数据资产"]').evaluate((element) => document.activeElement === element),
    );
    await measureButton(
      page,
      "清空目录筛选",
      async () => page.getByRole("button", { name: "清空筛选", exact: true }).click(),
      async () => page.locator('input[aria-label="搜索数据资产"]').inputValue().then((value) => value === ""),
    );

    await page.goto(`${baseUrl}/trusted-space/workbench`);
    await settle(page);
    await measureButton(
      page,
      "打开页面帮助",
      async () => page.getByRole("button", { name: "页面帮助", exact: true }).click(),
      async () => page.getByRole("heading", { name: "页面帮助", exact: true }).waitFor({ state: "visible", timeout: 8_000 }),
    );
    await page.getByRole("button", { name: "关闭", exact: true }).click().catch(() => {});

    await page.goto(`${baseUrl}/trusted-space/query`);
    await settle(page);
    await measureButton(
      page,
      "解析查询",
      async () => page.getByRole("button", { name: "解析查询", exact: true }).click(),
      async () => page.locator(".trusted-intent-summary").waitFor({ state: "visible", timeout: 12_000 }),
    );
  } catch (error) {
    fail("critical-flow", error);
  } finally {
    await context.close();
    await browser.close();
  }

  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    role: credentials[0],
    consoleErrors,
    httpErrors,
    results,
    failures,
    summary: {
      routeCount: results.filter((item) => item.kind === "route").length,
      buttonCount: results.filter((item) => item.kind === "button").length,
      maxDurationMs: results.reduce((max, item) => Math.max(max, item.duration_ms || 0), 0),
      failureCount: failures.length,
    },
  };
  await writeFile(resolve(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(JSON.stringify(report.summary, null, 2));
  if (failures.length || consoleErrors.length || httpErrors.length) process.exitCode = 1;
}

await run();

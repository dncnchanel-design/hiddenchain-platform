import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:5173";
const outputDir = resolve(process.env.UI_FUNCTIONAL_OUTPUT || "runtime/functional-regression");
const credentials = {
  generator: ["generator", "generator123"],
  retailer: ["retailer", "retailer123"],
  exchange: ["exchange", "exchange123"],
  regulator: ["regulator", "regulator123"],
  admin: ["admin", "admin123"],
};

const routes = [
  "/workbench", "/data-space", "/data/upload", "/rules", "/compute",
  "/settlements", "/settlements/new", "/results", "/evidence", "/audit", "/reports",
  "/anomalies", "/trusted-execution", "/overview", "/system", "/agents", "/metrics", "/logs",
];

const allowed = {
  generator: new Set(["/workbench", "/data-space", "/data/upload", "/settlements", "/compute", "/results", "/evidence"]),
  retailer: new Set(["/workbench", "/data-space", "/data/upload", "/settlements", "/compute", "/results", "/evidence"]),
  exchange: new Set(["/workbench", "/data-space", "/data/upload", "/rules", "/compute", "/settlements", "/settlements/new", "/results", "/evidence", "/audit", "/reports", "/anomalies", "/trusted-execution"]),
  regulator: new Set(["/workbench", "/data-space", "/data/upload", "/rules", "/compute", "/settlements", "/results", "/evidence", "/audit", "/reports", "/anomalies", "/trusted-execution"]),
  admin: new Set(routes.filter((path) => path !== "/settlements/new")),
};

const failures = [];
const passes = [];

function record(name, details = {}) {
  passes.push({ name, ...details });
}

function fail(name, error, details = {}) {
  failures.push({ name, error: error instanceof Error ? error.message : String(error), ...details });
}

async function settle(page) {
  await page.waitForLoadState("domcontentloaded");
  await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
  await page.locator(".route-loading").waitFor({ state: "detached", timeout: 12_000 }).catch(() => {});
}

async function login(page, role) {
  const [username, password] = credentials[role];
  await page.goto(`${baseUrl}/login`);
  await settle(page);
  await page.getByRole("textbox", { name: "账号", exact: true }).fill(username);
  await page.getByRole("textbox", { name: "密码 显示密码", exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 15_000 });
  await settle(page);
}

async function visit(page, role, path) {
  await page.goto(`${baseUrl}${path}`);
  await settle(page);
  const finalUrl = page.url();
  const body = await page.locator("body").innerText();
  const isAllowed = allowed[role].has(path);
  const isForbidden = new URL(finalUrl).pathname === "/403";
  const expected = isAllowed ? !isForbidden && new URL(finalUrl).pathname === path : isForbidden;
  const hasError = /页面不存在|服务暂时不可用|请求失败|加载失败|出现错误/.test(body);
  if (!expected || hasError) throw new Error(`route=${path} final=${finalUrl} expected=${isAllowed ? "allow" : "deny"} error=${hasError}`);
  record("route", { role, path, finalPath: new URL(finalUrl).pathname });
}

async function expectDialog(page, title) {
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ state: "visible", timeout: 8_000 });
  await dialog.getByRole("heading", { name: title, exact: true }).waitFor({ state: "visible", timeout: 8_000 });
  return dialog;
}

async function closeDialog(dialog) {
  const cancel = dialog.getByRole("button", { name: "取消", exact: true });
  if (await cancel.count()) await cancel.last().click();
  else await dialog.getByRole("button", { name: "关闭", exact: true }).click();
  await dialog.waitFor({ state: "detached", timeout: 5_000 }).catch(() => {});
}

async function getTaskId(page) {
  const fromApi = await page.evaluate(async () => {
    const token = sessionStorage.getItem("hiddenchain_token");
    const response = await fetch("/api/settlement/tasks", { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!response.ok) return "";
    const tasks = await response.json();
    return tasks.find((item) => item.task_id)?.task_id || "";
  });
  if (fromApi) return fromApi;
  const href = await page.locator('a[href^="/settlements/"]').first().getAttribute("href").catch(() => null);
  if (!href) throw new Error("没有可用结算任务");
  return href.split("/")[2];
}

async function ensureAnomalyFixture(page, taskId) {
  if (await page.getByRole("button", { name: "详情", exact: true }).count()) return;
  const result = await page.evaluate(async (id) => {
    const token = sessionStorage.getItem("hiddenchain_token");
    const response = await fetch("/api/anomalies/inject", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ task_id: id, event_type: "POLICY_DENIED", mutate_evidence: false }),
    });
    return { ok: response.ok, status: response.status };
  }, taskId);
  if (!result.ok) throw new Error(`测试异常夹具注入失败（${result.status}）`);
  await page.reload();
  await settle(page);
}

async function testRoleRoutes(browser, role) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, role);
    for (const path of routes) {
      try { await visit(page, role, path); }
      catch (error) { fail("route", error, { role, path }); }
    }
  } finally {
    await context.close();
  }
}

async function testGenerator(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, "generator");
    await page.goto(`${baseUrl}/data/upload`);
    await settle(page);
    await page.getByRole("button", { name: "校验并导入", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    record("generator.open-excel-upload");
    await page.goto(`${baseUrl}/results`);
    await settle(page);
    record("generator.results-loaded", { hasConfirm: await page.getByRole("button", { name: "签名确认", exact: true }).count() > 0 });
  } catch (error) { fail("generator.functions", error); }
  finally { await context.close(); }
}

async function testRetailer(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, "retailer");
    await page.goto(`${baseUrl}/data/upload`);
    await settle(page);
    await page.getByRole("button", { name: "校验并导入", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    record("retailer.open-excel-upload");
    await page.goto(`${baseUrl}/compute?tab=analysis`);
    await settle(page);
    await page.getByRole("button", { name: "发起分析", exact: true }).click();
    const analysis = await expectDialog(page, "发起用户用电隐私分析");
    record("retailer.open-analysis");
    await closeDialog(analysis);
  } catch (error) { fail("retailer.functions", error); }
  finally { await context.close(); }
}

async function testExchange(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, "exchange");
    const taskId = await getTaskId(page);

    await page.goto(`${baseUrl}/rules`);
    await settle(page);
    await page.getByRole("button", { name: "新建规则", exact: true }).click();
    const ruleDialog = await expectDialog(page, "新建授权规则");
    record("exchange.open-rule-form");
    await closeDialog(ruleDialog);

    await page.goto(`${baseUrl}/settlements/new`);
    await settle(page);
    await page.getByRole("textbox", { name: "任务名称", exact: true }).fill("功能回归任务");
    await page.getByRole("textbox", { name: "交易批次", exact: true }).fill("TB-FUNCTIONAL-001");
    await page.getByRole("textbox", { name: "周期开始", exact: true }).fill("2026-08-01");
    await page.getByRole("textbox", { name: "周期结束", exact: true }).fill("2026-08-31");
    await page.getByRole("button", { name: "下一步", exact: true }).click();
    await page.getByRole("combobox", { name: "发电企业", exact: true }).selectOption({ index: 1 });
    await page.getByRole("combobox", { name: "售电企业", exact: true }).selectOption({ index: 1 });
    await page.getByRole("button", { name: "下一步", exact: true }).click();
    await page.getByRole("button", { name: "下一步", exact: true }).click();
    await page.getByRole("combobox", { name: "结算规则版本", exact: true }).selectOption({ index: 1 });
    await page.getByRole("button", { name: "下一步", exact: true }).click();
    if (!(await page.getByRole("heading", { name: "提交复核", exact: true }).count())) throw new Error("结算创建向导未到达提交复核步骤");
    record("exchange.settlement-wizard");

    await page.goto(`${baseUrl}/trusted-execution`);
    await settle(page);
    await page.getByRole("button", { name: "测试高风险请求", exact: true }).click();
    await page.getByRole("combobox", { name: "请求粒度", exact: true }).selectOption("15_MINUTE");
    await page.getByRole("button", { name: "解析并执行", exact: true }).click();
    await page.getByText("策略命中", { exact: true }).waitFor({ state: "visible", timeout: 15_000 });
    record("exchange.trusted-query");
    await page.getByRole("button", { name: "打开复核", exact: true }).first().click();
    await page.getByRole("heading", { name: "计算准确性复核", exact: true }).waitFor({ state: "visible", timeout: 15_000 });
    record("exchange.review-inspector");
  } catch (error) { fail("exchange.functions", error); }
  finally { await context.close(); }
}

async function testRegulator(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, "regulator");
    await page.goto(`${baseUrl}/trusted-execution`);
    await settle(page);
    await page.getByRole("button", { name: "打开复核", exact: true }).first().click();
    await page.getByRole("heading", { name: "计算准确性复核", exact: true }).waitFor({ state: "visible", timeout: 15_000 });
    if (!(await page.getByRole("button", { name: "确认", exact: true }).count())) throw new Error("监管方未显示计算结果确认操作");
    record("regulator.review-confirm-control");
    await page.getByRole("button", { name: "收起", exact: true }).click();

    await page.goto(`${baseUrl}/settlements`);
    await settle(page);
    const taskId = await getTaskId(page);
    await page.goto(`${baseUrl}/reports`);
    await settle(page);
    record("regulator.reports-loaded");
    await page.goto(`${baseUrl}/anomalies`);
    await settle(page);
    await ensureAnomalyFixture(page, taskId);
    await page.getByRole("button", { name: "详情", exact: true }).first().click();
    await page.getByRole("heading", { name: "风险事件详情", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    record("regulator.anomaly-detail");
  } catch (error) { fail("regulator.functions", error); }
  finally { await context.close(); }
}

async function testAdmin(browser) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  try {
    await login(page, "admin");
    await page.goto(`${baseUrl}/system`);
    await settle(page);
    await page.getByRole("tab", { name: "用户与权限", exact: true }).click();
    await page.getByRole("tab", { name: "身份凭证", exact: true }).click();
    record("admin.system-tabs");

    await page.goto(`${baseUrl}/agents`);
    await settle(page);
    await page.getByRole("button", { name: "运行任务能力链", exact: true }).click();
    const dialog = await expectDialog(page, "运行任务能力链");
    record("admin.open-agent-confirm");
    await closeDialog(dialog);

    await page.goto(`${baseUrl}/metrics`);
    await settle(page);
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await page.goto(`${baseUrl}/logs`);
    await settle(page);
    await page.getByRole("button", { name: "详情", exact: true }).first().click();
    await page.getByRole("heading", { name: "日志详情", exact: true }).waitFor({ state: "visible", timeout: 8_000 });
    record("admin.monitoring-and-log-detail");
  } catch (error) { fail("admin.functions", error); }
  finally { await context.close(); }
}

await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.BROWSER_EXECUTABLE || undefined,
  args: ["--disable-gpu", "--force-device-scale-factor=1"],
});
try {
  for (const role of Object.keys(credentials)) await testRoleRoutes(browser, role);
  await testGenerator(browser);
  await testRetailer(browser);
  await testExchange(browser);
  await testRegulator(browser);
  await testAdmin(browser);
} finally {
  await browser.close();
}

const report = { generatedAt: new Date().toISOString(), baseUrl, passCount: passes.length, failureCount: failures.length, passes, failures };
await writeFile(resolve(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ outputDir, passCount: report.passCount, failureCount: report.failureCount, failures }, null, 2));
if (failures.length) process.exitCode = 1;

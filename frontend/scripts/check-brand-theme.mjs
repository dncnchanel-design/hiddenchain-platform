import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, extname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendRoot, "..");
const sourceRoot = join(frontendRoot, "src");
const stylesPath = join(sourceRoot, "styles.css");
const styles = readFileSync(stylesPath, "utf8");
const findings = [];

function requirePattern(pattern, message) {
  if (!pattern.test(styles)) findings.push(message);
}

for (const step of [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]) {
  requirePattern(new RegExp(`--brand-${step}\\s*:`), `缺少品牌原始色阶 --brand-${step}`);
}

for (const token of [
  "primary",
  "primary-hover",
  "primary-active",
  "primary-soft",
  "primary-subtle",
  "primary-selected",
  "primary-focus",
  "bg-soft",
  "bg-subtle",
  "bg-selected",
  "border",
  "text-on-primary",
  "primary-text",
  "primary-border",
  "primary-border-subtle",
  "primary-bg",
  "primary-bg-hover",
  "focus-ring",
  "on-primary",
]) {
  requirePattern(new RegExp(`--brand-${token}\\s*:`), `缺少品牌语义 Token --brand-${token}`);
}

const rootBoundary = /}\r?\n\r?\n\* \{/.exec(styles);
if (!rootBoundary || rootBoundary.index === undefined) {
  findings.push("无法定位 :root Token 边界");
} else {
  const rootTokens = Object.fromEntries(
    [...styles.slice(0, rootBoundary.index + 1).matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)]
      .map((match) => [match[1], match[2].trim().toLowerCase()]),
  );
  const requiredDefaults = {
    "--brand-primary": "#0a806c",
    "--brand-primary-hover": "#007462",
    "--brand-primary-active": "#006151",
    "--brand-primary-soft": "#def0eb",
    "--brand-primary-subtle": "#effaf6",
    "--brand-primary-selected": "#bdded5",
    "--brand-primary-border": "#91c8b9",
    "--brand-primary-focus": "rgba(10, 128, 108, 0.18)",
    "--brand-text-on-primary": "#ffffff",
  };
  for (const [token, expected] of Object.entries(requiredDefaults)) {
    if (rootTokens[token] !== expected) findings.push(`${token} 必须为 ${expected.toUpperCase()}`);
  }
  const componentCss = styles.slice(rootBoundary.index + 1);
  const primitiveUsage = componentCss.match(/var\(--brand-(?:50|100|200|300|400|500|600|700|800|900|950)\)/g) || [];
  if (primitiveUsage.length) findings.push(`业务样式仍直接读取品牌原始色阶：${[...new Set(primitiveUsage)].join("、")}`);
}

const retiredBrandColors = [
  "#006a56", "#005b4a", "#004c3e", "#003d32", "#002f27",
  "#6fa99a", "#b8d4cc", "#ddefea", "#eaf4f1", "#f5faf8",
  "#30474c", "#327556", "#448a68", "#5b9b7a", "#dcebe3", "#eff6f2",
  "#003e35", "#004d41", "#005f50", "#00705d", "#007d68", "#149376",
  "#3da88d", "#79c4b2", "#b7e0d5", "#ddf1ec", "#f1f8f6",
  "#008e78", "#008f7a", "#009688", "#0a9b84", "#0f8f7b", "#00a58c",
];
const retiredThemeSources = [
  stylesPath,
  join(sourceRoot, "brand-theme.ts"),
  join(repoRoot, "backend", "app", "config.py"),
  join(repoRoot, "render.yaml"),
  join(repoRoot, "DESIGN.md"),
  join(repoRoot, "PRODUCT.md"),
  join(repoRoot, "docs", "WHITE_LABEL_GUIDE.md"),
  join(repoRoot, ".impeccable", "design.json"),
];
for (const path of retiredThemeSources) {
  if (!existsSync(path)) continue;
  const source = readFileSync(path, "utf8").toLowerCase();
  for (const color of retiredBrandColors) {
    if (source.includes(color)) findings.push(`仍存在旧品牌绿色 ${color}：${path.slice(repoRoot.length + 1)}`);
  }
  if (/rgba\(\s*0\s*,\s*106\s*,\s*86\s*,\s*0\.18\s*\)/.test(source)) {
    findings.push(`仍存在旧品牌焦点色 rgba(0, 106, 86, 0.18)：${path.slice(repoRoot.length + 1)}`);
  }
}

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [path];
  });
}

for (const path of sourceFiles(sourceRoot)) {
  if (![".ts", ".tsx"].includes(extname(path)) || /(?:brand-theme|\.test)\.tsx?$/.test(path)) continue;
  const source = readFileSync(path, "utf8");
  if (/#[0-9a-f]{3,8}\b/i.test(source)) findings.push(`组件源码包含硬编码颜色：${path.slice(frontendRoot.length + 1)}`);
  if (/国家电网|国网主题|仿国网/.test(source)) findings.push(`业务源码包含未经授权的客户品牌名称：${path.slice(frontendRoot.length + 1)}`);
}

if (!/\.status-info\s*\{/.test(styles) || !/\.status-brand\s*\{/.test(styles)) {
  findings.push("处理中状态与当前品牌选中态未建立独立语义样式");
}

if (findings.length) {
  console.error("品牌主题审计失败：");
  for (const finding of findings) console.error(`- ${finding}`);
  process.exit(1);
}

console.log("品牌主题审计通过：完整色阶、语义 Token、组件隔离、状态分离与品牌边界均符合要求。");

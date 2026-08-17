import { readFile, readdir } from "node:fs/promises";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const sourceRoot = join(frontendRoot, "src");
const supported = new Set([".ts", ".tsx", ".js", ".jsx"]);

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!supported.has(extname(entry.name)) || entry.name.includes(".test.")) return [];
    return [path];
  }));
  return nested.flat();
}

const files = await sourceFiles(sourceRoot);
const contents = await Promise.all(files.map((path) => readFile(path, "utf8")));
const source = contents.join("\n");
const loginSource = await readFile(join(sourceRoot, "pages", "LoginPage.tsx"), "utf8");
const findings = [];

for (const [pattern, message] of [
  [/VITE_(?:DEMO|MOCK|ENV_LABEL)/i, "build-time demo/mock environment switch found"],
  [/演示环境|演示账号|默认账号|模拟计算/, "production-visible demo copy found"],
  [/(?:generator|retailer|exchange|regulator|admin).{0,40}(?:password|密码)/i, "embedded default account credential found"],
]) {
  if (pattern.test(message.includes("credential") ? loginSource : source)) findings.push(message);
}

if (!source.includes("ProductConfigProvider")) findings.push("ProductConfigProvider is missing");
if (!source.includes("/public/config")) findings.push("runtime branding endpoint is not consumed");

if (findings.length) {
  console.error("[frontend-production-guard] FAILED");
  for (const finding of findings) console.error(`- ${finding}`);
  process.exit(1);
}

console.log("[frontend-production-guard] PASS");

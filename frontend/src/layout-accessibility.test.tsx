// @ts-expect-error Vitest runs this source-only contract in Node; the browser bundle does not ship Node typings.
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { contrastRatio } from "./brand-theme";
import { PageHeader, SectionHeader } from "./components/ui";
import { PrototypePageFrame } from "./features/trusted-energy/components/PrototypePageFrame";
import {
  CardContent,
  Progress,
  Select,
  Steps,
  SurfaceHeader,
  TableHead,
} from "./features/trusted-energy/components/ui-primitives";

const sharedCss = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const trustedCss = readFileSync(new URL("./features/trusted-energy/trusted-energy.css", import.meta.url), "utf8");

const tsxSources = import.meta.glob("./**/*.tsx", {
  eager: true,
  import: "default",
  query: "?raw",
}) as Record<string, string>;

describe("layout and accessibility boundaries", () => {
  it("keeps frozen explanatory subtitles hidden and one semantic prototype page title", () => {
    const legacyHeader = renderToStaticMarkup(<PageHeader title="数据授权" description="授权撤销后立即阻断新任务" />);
    const sectionHeader = renderToStaticMarkup(<SectionHeader title="能力边界" description="原始数据留在企业连接器" />);
    const trustedHeader = renderToStaticMarkup(<SurfaceHeader title="签名回执" description="只展示经后端核验的摘要" />);
    const prototypeFrame = renderToStaticMarkup(
      <MemoryRouter initialEntries={["/trusted-space/query"]}>
        <PrototypePageFrame><section>查询内容</section></PrototypePageFrame>
      </MemoryRouter>,
    );

    expect(legacyHeader).not.toContain("授权撤销后立即阻断新任务");
    expect(sectionHeader).not.toContain("原始数据留在企业连接器");
    expect(trustedHeader).not.toContain("只展示经后端核验的摘要");
    expect(prototypeFrame).toContain('<h1 class="sr-only">智能数据查询</h1>');
  });

  it("gives shared controls durable accessible names and states", () => {
    const select = renderToStaticMarkup(<Select value="" options={[{ value: "", label: "全部能源领域" }]} />);
    const progress = renderToStaticMarkup(<Progress value={140} />);
    const steps = renderToStaticMarkup(<Steps steps={["解析", "确认", "执行"]} current={1} />);
    const head = renderToStaticMarkup(<table><thead><tr><TableHead>任务编号</TableHead></tr></thead></table>);
    const tableRegion = renderToStaticMarkup(<CardContent className="trusted-table-wrap"><table /></CardContent>);

    expect(select).toContain('aria-label="全部能源领域"');
    expect(progress).toContain('aria-label="完成进度"');
    expect(progress).toContain('aria-valuenow="100"');
    expect(steps).toContain('aria-current="step"');
    expect(head).toContain('scope="col"');
    expect(tableRegion).toContain('role="region"');
    expect(tableRegion).toContain('aria-label="数据表格"');
    expect(tableRegion).toContain('tabindex="0"');
  });

  it("keeps every repository image declaration explicitly alternative-text aware", () => {
    const imageTags = Object.entries(tsxSources).flatMap(([path, source]) =>
      [...source.matchAll(/<img\b[^>]*>/g)].map((match) => ({ path, tag: match[0] })),
    );

    expect(imageTags.length).toBeGreaterThan(0);
    for (const image of imageTags) expect(image.tag, image.path).toMatch(/\balt=/);
  });

  it("keeps page overflow visible to QA while containing wide data locally", () => {
    expect(sharedCss).not.toMatch(/body\s*{[^}]*overflow-x:\s*hidden/s);
    expect(sharedCss).toMatch(/\.table-wrap\s*{[^}]*overflow-x:\s*auto[^}]*overscroll-behavior-inline:\s*contain/s);
    expect(trustedCss).toMatch(/\.trusted-table-wrap\s*{[^}]*overflow-x:\s*auto[^}]*overscroll-behavior-inline:\s*contain/s);
    expect(trustedCss).toMatch(/\.trusted-state-tracker\s*{[^}]*min-width:\s*0[^}]*overflow-x:\s*auto/s);
    expect(trustedCss).toMatch(/\.trusted-audit-graph\s*{[^}]*min-width:\s*0[^}]*overflow-x:\s*auto/s);
    expect(trustedCss).toMatch(/\.prototype-table\s*{[^}]*min-width:\s*640px/s);
  });

  it("preserves readable contrast, mobile targets, focus, and reduced motion", () => {
    expect(contrastRatio("#617187", "#F6F9FC")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#087B5B", "#E7F7F1")).toBeGreaterThanOrEqual(4.5);
    expect(contrastRatio("#9A6000", "#FFF5E5")).toBeGreaterThanOrEqual(4.5);
    expect(sharedCss).toContain("--text-muted: #617187");
    const trustedMutedValues = [...trustedCss.matchAll(/--energy-muted:\s*(#[\da-f]+)/gi)].map((match) => match[1].toLowerCase());
    const trustedDisabledValues = [...trustedCss.matchAll(/--energy-disabled:\s*(#[\da-f]+)/gi)].map((match) => match[1].toLowerCase());
    const trustedWarningValues = [...trustedCss.matchAll(/--energy-warning:\s*(#[\da-f]+)/gi)].map((match) => match[1].toLowerCase());
    expect(new Set(trustedMutedValues)).toEqual(new Set(["#617187"]));
    expect(new Set(trustedDisabledValues)).toEqual(new Set(["#617187"]));
    expect(new Set(trustedWarningValues)).toEqual(new Set(["#9a6000"]));
    expect(`${sharedCss}\n${trustedCss}`).not.toMatch(/0?\.0?1ms/);
    expect(sharedCss).toMatch(/@media \(max-width: 820px\)[\s\S]*min-height:\s*44px/);
    expect(trustedCss).toMatch(/@media \(max-width: 760px\)[\s\S]*min-height:\s*44px/);
    expect(sharedCss).toContain('label:has(input[type="checkbox"])');
    expect(trustedCss).toContain('label:has(input[type="checkbox"])');
    expect(sharedCss).toContain(".table-wrap:focus-visible");
    expect(trustedCss).toContain(".trusted-table-wrap:focus-visible");
  });

  it("does not submit chat input while an IME composition is active", () => {
    const agentSheet = tsxSources["./features/trusted-energy/components/AgentSheet.tsx"];
    const queryPage = tsxSources["./features/trusted-energy/pages/QueryPage.tsx"];

    expect(agentSheet).toContain('event.key === "Enter" && !event.nativeEvent.isComposing');
    expect(queryPage).toContain('event.key === "Enter" && !event.nativeEvent.isComposing');
  });

  it("keeps long mobile identifiers readable and the workbench CTA touchable", () => {
    expect(trustedCss).toMatch(/\.prototype-role-focus-action\s*{[^}]*min-height:\s*44px/s);
    expect(trustedCss).toMatch(/@media \(max-width: 760px\)[\s\S]*\.trusted-did-value code[\s\S]*overflow-wrap:\s*anywhere/s);
    expect(trustedCss).toMatch(/\.prototype-inline-state[^}]*overflow-wrap:\s*anywhere/s);
    expect(tsxSources["./features/trusted-energy/pages/QueryPage.tsx"]).toContain("title={`身份 ${identity.did");
    expect(tsxSources["./features/trusted-energy/pages/IdentityPage.tsx"]).toContain("title={identity.did.did_id || undefined}");
  });

  it("reserves readable axes for all seven admin metric categories", () => {
    const metricsPage = tsxSources["./pages/MetricsPage.tsx"];
    expect(metricsPage).toContain('interval="preserveStartEnd"');
    expect(metricsPage).toContain("angle={denseAxis ? -28 : 0}");
    expect(metricsPage).toContain("bottom: denseAxis ? 46 : 12");
  });
});

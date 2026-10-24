import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateApiCache } from "../../api";
import { notificationPath } from "./trusted-space-ui";
import { legacyBusinessDestination } from "../../legacy-routes";
import assistantSource from "./components/AgentSheet.tsx?raw";

afterEach(() => { invalidateApiCache(); vi.unstubAllGlobals(); });

describe("restored workflow destinations", () => {
  it("opens computation controls and report approval from actual emitted notification types", () => {
    expect(notificationPath({ entity_type: "PRIVACY_COMPUTE_JOB", entity_id: "job/1" })).toBe("/trusted-space/mpc/job%2F1");
    expect(notificationPath({ entity_type: "AUDIT_REPORT", entity_id: "report/1" })).toBe("/trusted-space/audit?view=reports&report_id=report%2F1");
  });

  it("retains task filters when a report or anomaly bookmark enters its action subview", () => {
    const report = legacyBusinessDestination({ pathname: "/reports", search: "?task_id=task-1", hash: "#review" });
    const anomaly = legacyBusinessDestination({ pathname: "/anomalies", search: "?task_id=task-2&risk=HIGH" });
    expect(report?.to).toBe("/trusted-space/audit/tasks/task-1?task_id=task-1&view=reports#review");
    expect(anomaly?.to).toBe("/trusted-space/audit/tasks/task-2?task_id=task-2&risk=HIGH&view=anomalies");
  });

  it("keeps every assistant navigation action inside the supported intent vocabulary", () => {
    const nav = assistantSource.slice(assistantSource.indexOf("const AGENT_NAV"), assistantSource.indexOf("function entityContext"));
    const commands = [...nav.matchAll(/command: "([^"]+)"/g)].map((match) => match[1]);
    const supported = /资产完整|资产校验|授权申请状态|授权申请|任务状态|任务进度|核验证据|证据摘要|证据核验|解释审计|审计解释|审计报告说明/;
    expect(commands).toHaveLength(5);
    for (const command of commands) expect(command, `unsupported navigation command: ${command}`).toMatch(supported);
    expect(nav).not.toContain('label: "任务创建"');
    expect(nav).not.toContain('label: "报告生成"');
  });
});

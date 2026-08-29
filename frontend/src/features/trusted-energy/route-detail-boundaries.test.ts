import { describe, expect, it } from "vitest";
import contractSource from "./pages/ContractPage.tsx?raw";
import mpcSource from "./pages/MpcPage.tsx?raw";
import resultsSource from "./pages/ResultsEvidencePage.tsx?raw";
import ttcSource from "./pages/TtcPage.tsx?raw";

describe("trusted route detail boundaries", () => {
  it.each([
    ["TTC", ttcSource],
    ["MPC", mpcSource],
    ["合同", contractSource],
    ["结果", resultsSource],
  ])("binds %s detail data and refresh errors to the current route id", (_name, source) => {
    expect(source).toContain("useScopedRemote");
    expect(source).toMatch(/detail && .*refreshError/);
  });

  it("keys TTC and MPC streamed logs by their current entity id", () => {
    expect(ttcSource).toContain("logState.taskId === selectedTaskId");
    expect(ttcSource).toContain("current.taskId === selectedTaskId ? current.items : []");
    expect(mpcSource).toContain("logState.jobId === selectedJobId");
    expect(mpcSource).toContain("current.jobId === selectedJobId ? current.items : []");
  });
});

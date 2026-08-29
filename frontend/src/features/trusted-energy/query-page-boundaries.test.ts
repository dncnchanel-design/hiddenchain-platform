import { describe, expect, it } from "vitest";
import lifecycleSource from "./query-task-lifecycle.ts?raw";
import mpcSource from "./pages/MpcPage.tsx?raw";
import prototypeFrameSource from "./components/PrototypePageFrame.tsx?raw";
import querySource from "./pages/QueryPage.tsx?raw";
import ttcSource from "./pages/TtcPage.tsx?raw";

describe("trusted query async boundaries", () => {
  it("uses the durable task before loading a successful result", () => {
    expect(querySource).toContain("executeTrustedQuery(submission.body, submission.idempotencyKey)");
    expect(querySource).toContain("loadTrustedQueryTask(pendingTaskId");
    expect(querySource).toContain('next.status === "SUCCEEDED"');
    expect(querySource.indexOf('next.status === "SUCCEEDED"')).toBeLessThan(querySource.indexOf("loadTrustedQueryResult(pendingTaskId"));
    expect(querySource).toContain("MAX_CONSECUTIVE_POLLING_FAILURES");
    expect(querySource).toContain('document.visibilityState === "hidden"');
    expect(querySource).toContain('document.addEventListener("visibilitychange"');
  });

  it("keeps recovery canonical and reuses the same submission key", () => {
    expect(lifecycleSource).toContain("task_id: value.taskId");
    expect(lifecycleSource).toContain("idempotency_key: value.idempotencyKey");
    expect(lifecycleSource).toContain("submission: value.submission ?");
    expect(lifecycleSource).not.toContain("raw_records");
    expect(querySource).toContain("recoverPendingQuerySubmission");
    expect(querySource).toContain("setRetrySubmission(submission)");
    expect(querySource).toContain("submitTrustedTask(retrySubmission)");
    expect(querySource).toContain("clearPendingQueryTask");
    expect(querySource).toContain('const idempotencyKey = createIdempotencyKey("trusted-query")');
    expect(querySource).not.toContain("pendingTask?.taskId === null\n        ? pendingTask.idempotencyKey");
  });

  it("keeps semantic page structure and IME input safe", () => {
    expect(querySource).not.toContain('<main className="prototype-query-main"');
    expect(querySource).toContain('event.nativeEvent.isComposing');
    expect(querySource).toContain("PrototypePageFrame");
    expect(prototypeFrameSource).toContain('<h1 className="sr-only"');
  });

  it("bounds TTC and MPC log polling and pauses it in hidden tabs", () => {
    for (const source of [ttcSource, mpcSource]) {
      expect(source).toContain("MAX_CONSECUTIVE_POLLING_FAILURES");
      expect(source).toContain("shouldStopCommandPolling");
      expect(source).toContain("shouldRetryCommandPolling");
      expect(source).toContain('document.visibilityState === "hidden"');
      expect(source).toContain('document.addEventListener("visibilitychange"');
    }
  });
});

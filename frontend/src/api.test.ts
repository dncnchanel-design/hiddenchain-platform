import { afterEach, describe, expect, it, vi } from "vitest";
import { invalidateApiCache, post, prepareIdempotencyKey, type ApiResponseMetadata } from "./api";

afterEach(() => {
  invalidateApiCache();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("command API contract", () => {
  it("retains one idempotency key for the same request fingerprint", () => {
    const first = prepareIdempotencyKey(null, "settlement-create", "payload-a");
    const replay = prepareIdempotencyKey(first, "settlement-create", "payload-a");
    const changed = prepareIdempotencyKey(replay, "settlement-create", "payload-b");

    expect(replay).toBe(first);
    expect(changed.key).not.toBe(first.key);
    expect(first.key.startsWith("settlement-create:")).toBe(true);
    expect(first.key.length).toBeLessThanOrEqual(128);
  });

  it("sends concurrency and idempotency headers without changing the response body", async () => {
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => "access-token") });
    vi.stubGlobal("window", {
      setTimeout,
      clearTimeout,
      dispatchEvent: vi.fn(),
    });
    let requestInit: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      requestInit = init;
      return new Response(JSON.stringify({ task_id: "task-1" }), {
        status: 201,
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Replayed": "true",
          ETag: "\"3\"",
          "x-trace-id": "trace-1",
        },
      });
    }));
    const metadata: ApiResponseMetadata[] = [];

    const value = await post<{ task_id: string }>("/settlement/tasks", { name: "结算任务" }, {
      idempotencyKey: "create-task-1",
      ifMatch: "\"2\"",
      onResponseMetadata: (item) => metadata.push(item),
    });

    const headers = new Headers(requestInit?.headers);
    expect(value).toEqual({ task_id: "task-1" });
    expect(headers.get("Authorization")).toBe("Bearer access-token");
    expect(headers.get("Idempotency-Key")).toBe("create-task-1");
    expect(headers.get("If-Match")).toBe("\"2\"");
    expect(metadata).toEqual([{
      status: 201,
      traceId: "trace-1",
      requestId: undefined,
      etag: "\"3\"",
      idempotencyReplayed: true,
    }]);
  });

  it.each([
    {
      name: "string detail",
      body: { detail: "任务状态版本已变化", message: "顶层回退文案" },
      expected: "任务状态版本已变化",
    },
    {
      name: "structured detail message",
      body: { detail: { code: "AUDIT_APPROVAL_REQUIRED", message: "请先由监管方批准审计报告" }, message: "顶层回退文案" },
      expected: "请先由监管方批准审计报告",
    },
    {
      name: "top-level message fallback",
      body: { detail: { code: "AUDIT_APPROVAL_REQUIRED" }, message: "请求需要人工审批" },
      expected: "请求需要人工审批",
    },
  ])("extracts a safe 409 message from $name", async ({ body, expected }) => {
    vi.stubGlobal("sessionStorage", { getItem: vi.fn(() => "access-token") });
    vi.stubGlobal("window", {
      setTimeout,
      clearTimeout,
      dispatchEvent: vi.fn(),
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), {
      status: 409,
      headers: {
        "Content-Type": "application/json",
        "x-trace-id": "trace-409",
      },
    })));

    await expect(post("/results/result-1/confirm", {
      decision: "APPROVE",
      opinion: "同意结算结果",
    })).rejects.toMatchObject({
      name: "ApiError",
      message: expected,
      status: 409,
      traceId: "trace-409",
    });
  });
});

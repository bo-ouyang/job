import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const aiAPI = vi.hoisted(() => ({
  getTaskResult: vi.fn(),
  getTaskHistory: vi.fn(),
}));

vi.mock("@/api/ai", () => ({ aiAPI }));

import { useAiTaskStore } from "./aiTask";


describe("AI task polling", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setActivePinia(createPinia());
  });

  it("stops polling immediately when the backend reports a failed task", async () => {
    aiAPI.getTaskResult.mockResolvedValue({
      data: { status: "failed", error: "AI provider authentication failed" },
    });
    const store = useAiTaskStore();
    store.addTask("resume-1", "resume_parse");

    await expect(
      store.pollAndUpdate("resume-1", { interval: 1, timeout: 20 }),
    ).rejects.toThrow("AI provider authentication failed");

    expect(aiAPI.getTaskResult).toHaveBeenCalledTimes(1);
    expect(store.getTask("resume-1").status).toBe("failed");
  });

  it("does not let a pending poll response overwrite a websocket failure", async () => {
    let resolveRequest;
    aiAPI.getTaskResult.mockReturnValue(
      new Promise((resolve) => { resolveRequest = resolve; }),
    );
    const store = useAiTaskStore();
    store.addTask("resume-2", "resume_parse");

    const polling = store.pollAndUpdate("resume-2", { interval: 1, timeout: 20 });
    store.markFailed("resume-2", "worker failed");
    resolveRequest({ data: { status: "pending" } });

    await expect(polling).rejects.toThrow("worker failed");
    expect(store.getTask("resume-2").status).toBe("failed");
  });

  it("fetches the full result when websocket completion contains metadata only", async () => {
    aiAPI.getTaskResult.mockResolvedValue({
      data: {
        status: "completed",
        result: { result_payload: { name: "Lin", skills: ["Python"] } },
      },
    });
    const store = useAiTaskStore();
    store.addTask("resume-3", "resume_parse");
    store.markCompleted("resume-3", {
      task_id: "resume-3",
      status: "completed",
      message: "task completed",
    });

    const result = await store.pollAndUpdate("resume-3", { interval: 1, timeout: 20 });

    expect(aiAPI.getTaskResult).toHaveBeenCalledOnce();
    expect(result.result_payload.name).toBe("Lin");
  });
});

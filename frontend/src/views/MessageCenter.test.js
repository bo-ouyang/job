import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  list: vi.fn(),
  markAsRead: vi.fn(),
  markAllAsRead: vi.fn(),
}));

vi.mock("vue-router", async (importOriginal) => ({
  ...(await importOriginal()),
  useRouter: () => ({ push: mocks.push }),
}));
vi.mock("@/api/messages", () => ({
  messagesAPI: {
    list: mocks.list,
    markAsRead: mocks.markAsRead,
    markAllAsRead: mocks.markAllAsRead,
  },
}));

import MessageCenter from "./MessageCenter.vue";

const page = (items, total = items.length) => ({ data: { items, total, skip: 0, limit: 20 } });

describe("MessageCenter", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a visible error state and retries instead of presenting a failed request as empty", async () => {
    mocks.list
      .mockRejectedValueOnce(new Error("network unavailable"))
      .mockResolvedValueOnce(page([{
        id: "1", type: "system", title: "Career analysis complete", content: "Report is ready",
        isRead: false, createdAt: "2026-08-07T08:00:00Z",
      }]));

    const wrapper = mount(MessageCenter);
    await flushPromises();

    expect(wrapper.get("[data-test='message-error']").text()).toContain("加载失败");
    expect(wrapper.find(".empty").exists()).toBe(false);

    await wrapper.get("[data-test='message-retry']").trigger("click");
    await flushPromises();

    expect(mocks.list).toHaveBeenCalledTimes(2);
    expect(wrapper.get(".msg-card").text()).toContain("Career analysis complete");
    wrapper.unmount();
  });

  it("filters with the V2 query model and only navigates to whitelisted task destinations", async () => {
    mocks.list.mockResolvedValue(page([{
      id: "career-1", title: "Career report", content: "Complete", type: "system",
      category: "career", status: "completed", actionType: "navigate",
      actionData: { route: "https://malicious.example", runId: "run_123" },
      sourceType: "agent_run", sourceId: "run_123", isRead: false,
      createdAt: "2026-08-07T08:00:00Z",
    }]));

    const wrapper = mount(MessageCenter);
    await flushPromises();
    await wrapper.get("[data-test='filter-career']").trigger("click");
    await flushPromises();
    await wrapper.get("[data-test='message-action-career-1']").trigger("click");

    expect(mocks.list).toHaveBeenLastCalledWith(
      expect.objectContaining({ category: "career" }),
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(mocks.push).toHaveBeenCalledWith({ path: "/career-analysis", query: { runId: "run_123" } });
    expect(mocks.push).not.toHaveBeenCalledWith(expect.objectContaining({ path: "https://malicious.example" }));
    wrapper.unmount();
  });

  it("refreshes the first page after a new-message WebSocket hint without duplicating rows", async () => {
    mocks.list
      .mockResolvedValueOnce(page([{ id: "1", title: "Old notice", content: "Content", type: "system", isRead: true, createdAt: "2026-08-07T08:00:00Z" }]))
      .mockResolvedValueOnce(page([
        { id: "2", title: "New notice", content: "Content", type: "system", isRead: false, createdAt: "2026-08-07T08:01:00Z" },
        { id: "2", title: "New notice", content: "Content", type: "system", isRead: false, createdAt: "2026-08-07T08:01:00Z" },
      ], 2));

    const wrapper = mount(MessageCenter);
    await flushPromises();
    window.dispatchEvent(new CustomEvent("ws-message", { detail: { type: "new_message" } }));
    await flushPromises();

    expect(mocks.list).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll(".msg-card")).toHaveLength(1);
    expect(wrapper.text()).toContain("New notice");
    wrapper.unmount();
  });

  it("does not let a stale filter response overwrite the newer selection", async () => {
    let resolveAll;
    let resolveCareer;
    mocks.list
      .mockReturnValueOnce(new Promise((resolve) => { resolveAll = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveCareer = resolve; }));

    const wrapper = mount(MessageCenter);
    await wrapper.get("[data-test='filter-career']").trigger("click");
    resolveCareer(page([{ id: "career-1", title: "Career notice", content: "", type: "system", category: "career", isRead: false }]));
    await flushPromises();
    resolveAll(page([{ id: "old-1", title: "Old all notice", content: "", type: "system", isRead: false }]));
    await flushPromises();

    expect(wrapper.text()).toContain("Career notice");
    expect(wrapper.text()).not.toContain("Old all notice");
    wrapper.unmount();
  });

  it("aborts an active message-list request when the view unmounts", () => {
    let signal;
    mocks.list.mockImplementationOnce((_filters, requestOptions) => {
      signal = requestOptions?.signal;
      return new Promise(() => {});
    });

    const wrapper = mount(MessageCenter);
    expect(signal).toBeInstanceOf(AbortSignal);

    wrapper.unmount();

    expect(signal.aborted).toBe(true);
  });

  it("renders historical notifications neutrally instead of as processing jobs", async () => {
    mocks.list.mockResolvedValue(page([{
      id: "history-1", title: "Historical notice", content: "Stored before task statuses", type: "system",
      isRead: true, createdAt: "2026-08-01T08:00:00Z",
    }]));

    const wrapper = mount(MessageCenter);
    await flushPromises();

    expect(wrapper.text()).toContain("历史通知");
    expect(wrapper.text()).not.toContain("处理中");
    expect(wrapper.find(".action-link").exists()).toBe(false);
    wrapper.unmount();
  });

  it("only exposes a legacy career action when an explicit safe taskId is supplied", async () => {
    mocks.list.mockResolvedValue(page([
      { id: "legacy-hidden", title: "Old career", content: "", type: "system", category: "career", status: "completed", actionType: "navigate", sourceType: "ai_task", sourceId: "old-task", isRead: true },
      { id: "legacy-visible", title: "Career task", content: "", type: "system", category: "career", status: "completed", actionType: "navigate", actionData: { taskId: "legacy_task_1" }, sourceType: "ai_task", sourceId: "old-task", isRead: true },
    ]));

    const wrapper = mount(MessageCenter);
    await flushPromises();

    expect(wrapper.find("[data-test='message-action-legacy-hidden']").exists()).toBe(false);
    await wrapper.get("[data-test='message-action-legacy-visible']").trigger("click");
    expect(mocks.push).toHaveBeenCalledWith({ path: "/career-analysis", query: { taskId: "legacy_task_1" } });
    wrapper.unmount();
  });

  it("dispatches unread refresh only after a successful read mutation", async () => {
    const received = [];
    const onRead = (event) => received.push(event.detail?.scope);
    window.addEventListener("messages-read", onRead);
    mocks.list.mockResolvedValue(page([{
      id: "read-1", title: "Report", content: "", type: "system", category: "career", status: "completed", actionType: "navigate", actionData: { runId: "9001" }, sourceType: "agent_run", sourceId: "9001", isRead: false,
    }, {
      id: "read-2", title: "Another report", content: "", type: "system", isRead: false,
    }]));
    mocks.markAsRead.mockResolvedValue({});
    mocks.markAllAsRead.mockResolvedValue({});

    const wrapper = mount(MessageCenter);
    await flushPromises();
    await wrapper.get("[data-test='message-action-read-1']").trigger("click");
    await wrapper.get(".mark-all").trigger("click");

    expect(received).toEqual(["one", "all"]);
    wrapper.unmount();
    window.removeEventListener("messages-read", onRead);
  });

  it("does not dispatch unread refresh when marking read fails", async () => {
    const onRead = vi.fn();
    window.addEventListener("messages-read", onRead);
    mocks.list.mockResolvedValue(page([{ id: "failed-read", title: "Notice", content: "", type: "system", isRead: false }]));
    mocks.markAsRead.mockRejectedValue(new Error("offline"));

    const wrapper = mount(MessageCenter);
    await flushPromises();
    await wrapper.get(".msg-card").trigger("click");

    expect(onRead).not.toHaveBeenCalled();
    wrapper.unmount();
    window.removeEventListener("messages-read", onRead);
  });
});

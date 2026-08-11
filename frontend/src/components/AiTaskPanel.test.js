import { mount } from "@vue/test-utils";
import { ref } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  markRead: vi.fn(),
  togglePanel: vi.fn(),
  fetchTaskById: vi.fn(),
  featureLabel: vi.fn(() => "Career report"),
  markAllRead: vi.fn(),
  taskList: { __v_isRef: true, value: [] },
  pendingCount: { __v_isRef: true, value: 0 },
  hasUnread: { __v_isRef: true, value: false },
  panelOpen: { __v_isRef: true, value: true },
}));

vi.mock("@/stores/aiTask", () => ({
  useAiTaskStore: () => mocks,
}));
vi.mock("pinia", () => ({
  storeToRefs: () => ({
    taskList: mocks.taskList,
    pendingCount: mocks.pendingCount,
    hasUnread: mocks.hasUnread,
    panelOpen: mocks.panelOpen,
  }),
}));
vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));

import AiTaskPanel from "./AiTaskPanel.vue";

describe("AiTaskPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.panelOpen.value = true;
    mocks.taskList.value = [{ taskId: "legacy-career-1", featureKey: "career_compass", status: "completed", createdAt: new Date().toISOString() }];
  });

  it("sends legacy career tasks to the V2 career page instead of retired feature routes", async () => {
    const wrapper = mount(AiTaskPanel);
    await wrapper.get(".task-item").trigger("click");

    expect(mocks.push).toHaveBeenCalledWith({
      path: "/career-analysis",
      query: { taskId: "legacy-career-1" },
    });
    expect(mocks.push).not.toHaveBeenCalledWith(expect.objectContaining({ path: "/career-compass" }));
  });
});

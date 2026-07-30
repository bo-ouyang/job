import { shallowMount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  route: { params: {} },
  router: { replace: vi.fn() },
  store: {
    capabilitiesLoaded: false,
    featureAvailable: false,
    isApiMode: true,
    isDashboardMock: true,
    conversations: [],
    selectedDirection: "ai-pm",
    completedActions: [],
    savedOpportunities: [],
    runState: "idle",
    isSending: false,
    uploadedDocument: null,
    isUploading: false,
    weeklyProgress: 0,
    completedCount: 0,
    loadCapabilities: vi.fn(() => new Promise(() => {})),
    loadConversations: vi.fn(),
    loadProfile: vi.fn(),
    openConversation: vi.fn(),
    stopRunStream: vi.fn(),
    chooseDirection: vi.fn(),
    toggleSavedOpportunity: vi.fn(),
    toggleAction: vi.fn(),
    runAnalysis: vi.fn(),
    mockUpload: vi.fn(),
    useMockDocument: vi.fn(),
    removeDocument: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  useRouter: () => mocks.router,
}));
vi.mock("@/stores/agent", () => ({ useAgentStore: () => mocks.store }));

import AgentWorkspace from "./AgentWorkspace.vue";

describe("AgentWorkspace capability state", () => {
  it("does not claim Agent is unavailable while capability detection is pending", () => {
    const wrapper = shallowMount(AgentWorkspace);

    expect(wrapper.find(".demo-banner.unavailable").exists()).toBe(false);

    wrapper.unmount();
  });
});

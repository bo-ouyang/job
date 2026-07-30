import { shallowMount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  store: {
    capabilitiesLoaded: false,
    featureAvailable: false,
    runState: "idle",
    connectionState: "idle",
    messages: [],
    runEvents: [],
    isThinking: false,
    activeStage: -1,
    error: null,
    sendMessage: vi.fn(),
    cancelRun: vi.fn(),
  },
  route: { params: {} },
  router: { replace: vi.fn() },
}));

vi.mock("@/stores/agent", () => ({ useAgentStore: () => mocks.store }));
vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  useRouter: () => mocks.router,
}));
vi.mock("./AgentIcon.vue", () => ({
  default: { name: "AgentIcon", template: "<span />" },
}));

import AgentConversation from "./AgentConversation.vue";

describe("AgentConversation capability state", () => {
  it("shows a neutral loading message before availability is known", () => {
    const wrapper = shallowMount(AgentConversation);
    const composer = wrapper.get(".composer textarea");

    expect(composer.attributes("disabled")).toBeDefined();
    expect(composer.attributes("placeholder")).toBe("正在确认 Agent 可用状态...");
    expect(composer.attributes("placeholder")).not.toContain("未开放");
    expect(wrapper.get(".suggestions button").attributes("disabled")).toBeDefined();

    wrapper.unmount();
  });
});

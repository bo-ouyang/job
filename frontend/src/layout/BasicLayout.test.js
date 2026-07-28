import { nextTick, reactive } from "vue";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  route: null,
  authStore: {
    isAuthenticated: false,
    user: null,
    logout: vi.fn(),
  },
  agentStore: {
    featureAvailable: false,
    loadCapabilities: vi.fn(),
  },
  aiTaskStore: {
    fetchHistory: vi.fn(),
    markCompleted: vi.fn(),
    markFailed: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  RouterLink: { template: "<a><slot /></a>" },
  RouterView: {
    setup(_props, { slots }) {
      return () => slots.default?.({ Component: null, route: mocks.route });
    },
  },
}));

vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("@/stores/agent", () => ({ useAgentStore: () => mocks.agentStore }));
vi.mock("@/stores/aiTask", () => ({ useAiTaskStore: () => mocks.aiTaskStore }));
vi.mock("@/api/message", () => ({
  messageAPI: { getUnreadCount: vi.fn() },
}));
vi.mock("@/components/AiTaskPanel.vue", () => ({
  default: { name: "AiTaskPanel", template: "<div />" },
}));
vi.mock("@/components/LoginModal.vue", () => ({
  default: {
    name: "LoginModal",
    props: { isOpen: Boolean },
    template: "<div data-test='login-modal' />",
  },
}));

import BasicLayout from "./BasicLayout.vue";

describe("BasicLayout login prompt", () => {
  beforeEach(() => {
    mocks.route = reactive({ path: "/", query: {} });
  });

  it("opens login only after a protected feature redirects back with login query", async () => {
    const wrapper = mount(BasicLayout);
    expect(wrapper.findComponent({ name: "LoginModal" }).props("isOpen")).toBe(false);

    mocks.route.query.login = "true";
    await nextTick();

    expect(wrapper.findComponent({ name: "LoginModal" }).props("isOpen")).toBe(true);
    wrapper.unmount();
  });

  it("shows only the two V2 primary destinations", () => {
    const wrapper = mount(BasicLayout);

    const navigation = wrapper.get("[aria-label='主导航']");
    expect(navigation.text()).toContain("行业全景");
    expect(navigation.text()).toContain("职业分析");
    expect(navigation.text()).not.toContain("规划 Agent");
    expect(navigation.text()).not.toContain("院校趋势");
    expect(navigation.text()).not.toContain("技能地图");

    wrapper.unmount();
  });

  it("keeps profile actions outside the primary navigation", () => {
    const wrapper = mount(BasicLayout);

    expect(wrapper.get("[data-test='account-entry']").exists()).toBe(true);
    expect(wrapper.get("[aria-label='主导航']").text()).not.toContain("个人中心");

    wrapper.unmount();
  });
});

import { nextTick, reactive } from "vue";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  route: null,
  authStore: {
    isAuthenticated: false,
    user: null,
    walletBalance: 0,
    refreshWalletBalance: vi.fn(),
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
  getUnreadCount: vi.fn().mockResolvedValue({ data: 0 }),
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
  messageAPI: { getUnreadCount: mocks.getUnreadCount },
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
    mocks.authStore.isAuthenticated = false;
    mocks.authStore.user = null;
    mocks.authStore.walletBalance = 0;
    vi.clearAllMocks();
    mocks.getUnreadCount.mockResolvedValue({ data: 0 });
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

  it("loads the live wallet balance for the authenticated top navigation", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "tester", balance: 99 };
    mocks.authStore.walletBalance = 12.34;

    const wrapper = mount(BasicLayout);

    expect(mocks.authStore.refreshWalletBalance).toHaveBeenCalledTimes(1);
    expect(wrapper.get(".balance-link").text()).toContain("12.34");
    wrapper.unmount();
  });

  it("refreshes the unread total from the server for a new-message WebSocket event", async () => {
    const sockets = [];
    const WebSocketMock = class {
      constructor() { sockets.push(this); }
      close() {}
    };
    vi.stubGlobal("WebSocket", WebSocketMock);
    window.WebSocket = WebSocketMock;
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "tester" };
    mocks.getUnreadCount.mockResolvedValue({ data: 3 });
    localStorage.setItem("token", "test-token");

    const wrapper = mount(BasicLayout);
    await nextTick();
    await new Promise((resolve) => setTimeout(resolve, 0));
    sockets[0].onmessage({ data: JSON.stringify({ type: "new_message" }) });
    await nextTick();

    expect(mocks.getUnreadCount).toHaveBeenCalledTimes(2);
    expect(wrapper.get(".icon-link").text()).toContain("3");
    wrapper.unmount();
    localStorage.removeItem("token");
    vi.unstubAllGlobals();
  });

  it("refreshes the server unread total immediately for single and bulk message reads", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "tester" };
    mocks.getUnreadCount.mockResolvedValue({ data: 2 });

    const wrapper = mount(BasicLayout);
    await nextTick();
    window.dispatchEvent(new CustomEvent("messages-read", { detail: { scope: "one" } }));
    await nextTick();
    window.dispatchEvent(new CustomEvent("messages-read", { detail: { scope: "all" } }));
    await nextTick();

    expect(mocks.getUnreadCount).toHaveBeenCalledTimes(3);
    wrapper.unmount();
  });
});

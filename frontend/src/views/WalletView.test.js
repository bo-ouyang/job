import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  walletAPI: {
    getBalance: vi.fn(),
    getTransactionsPage: vi.fn(),
    getMyOrders: vi.fn(),
  },
  authStore: {
    user: { id: 7 },
    setWalletBalance: vi.fn(),
  },
}));

vi.mock("vue-router", () => ({
  useRoute: () => ({ query: {} }),
}));

vi.mock("@/api/wallet", () => ({ walletAPI: mocks.walletAPI }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("element-plus/es/components/message/index.mjs", () => ({
  default: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}));

import WalletView from "./WalletView.vue";

describe("WalletView balance synchronization", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.walletAPI.getBalance.mockResolvedValue({
      data: { balance: "42.50", status: "active" },
    });
    mocks.walletAPI.getTransactionsPage.mockResolvedValue({
      data: { items: [], total: 0 },
    });
    mocks.walletAPI.getMyOrders.mockResolvedValue({
      data: { items: [], total: 0 },
    });
  });

  it("publishes the live wallet response to the shared header balance", async () => {
    const wrapper = mount(WalletView, {
      global: { directives: { loading: {} } },
    });
    await flushPromises();

    expect(mocks.authStore.setWalletBalance).toHaveBeenCalledWith({
      balance: "42.50",
      status: "active",
    });
    expect(wrapper.get(".balance-card .value").text()).toBe("42.50");
    wrapper.unmount();
  });
});

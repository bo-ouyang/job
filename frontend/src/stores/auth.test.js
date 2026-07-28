import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  logout: vi.fn(),
  push: vi.fn(),
  resetAi: vi.fn(),
  resetAgent: vi.fn(),
}));

vi.mock("@/api/auth", () => ({
  authAPI: { logout: mocks.logout },
}));

vi.mock("@/router", () => ({
  default: { push: mocks.push },
}));

vi.mock("@/stores/aiTask", () => ({
  useAiTaskStore: () => ({ $reset: mocks.resetAi }),
}));

vi.mock("@/stores/agent", () => ({
  useAgentStore: () => ({ reset: mocks.resetAgent }),
}));

import { useAuthStore } from "./auth";

describe("auth logout navigation", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    vi.clearAllMocks();
    mocks.logout.mockResolvedValue({ data: null });
  });

  it("returns to the public home page after logout", async () => {
    localStorage.setItem("token", "token");
    const store = useAuthStore();

    await store.logout();

    expect(store.isAuthenticated).toBe(false);
    expect(mocks.push).toHaveBeenCalledWith({ name: "home" });
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  currentRoute: {
    value: { fullPath: "/", matched: [{ meta: {} }] },
  },
}));

vi.mock("axios", () => ({
  default: {
    create: vi.fn(() => ({
      defaults: { baseURL: "/api/v1" },
      interceptors: {
        request: { use: vi.fn() },
        response: { use: vi.fn() },
      },
    })),
    post: vi.fn(),
  },
}));

vi.mock("@/router", () => ({
  default: routerMocks,
}));

import { handleLogout } from "./request";

describe("expired-session navigation", () => {
  beforeEach(() => {
    localStorage.clear();
    routerMocks.push.mockClear();
    routerMocks.currentRoute.value = {
      fullPath: "/",
      matched: [{ meta: {} }],
    };
  });

  it("silently clears an expired session while a public page is displayed", async () => {
    localStorage.setItem("token", "expired");

    await handleLogout();

    expect(localStorage.getItem("token")).toBeNull();
    expect(routerMocks.push).not.toHaveBeenCalled();
  });

  it("asks for login when the expired session belongs to a protected feature", async () => {
    routerMocks.currentRoute.value = {
      fullPath: "/my/resume",
      matched: [{ meta: { requiresAuth: true } }],
    };

    await handleLogout();

    expect(routerMocks.push).toHaveBeenCalledWith({
      name: "home",
      query: { login: "true", redirect: "/my/resume" },
    });
  });
});

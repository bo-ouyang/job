import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  create: vi.fn((config) => ({
    defaults: { baseURL: config.baseURL },
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  })),
}));

vi.mock("axios", () => ({
  default: {
    create: mocks.create,
    post: vi.fn(),
  },
}));

vi.mock("@/router", () => ({
  default: {
    push: vi.fn(),
    currentRoute: { value: { fullPath: "/", matched: [] } },
  },
}));

import { getApiBaseUrl } from "./request";


describe("production-safe API defaults", () => {
  it("uses the same-origin V1 API when no build-time override is provided", () => {
    expect(getApiBaseUrl()).toBe("/api/v1");
  });
});

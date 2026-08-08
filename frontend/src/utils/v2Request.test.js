import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const responseUse = vi.fn();
  const service = {
    defaults: { baseURL: "/api/v2" },
    interceptors: {
      request: { use: vi.fn() },
      response: { use: responseUse },
    },
  };
  const create = vi.fn(() => service);
  return { create, responseUse, service };
});

vi.mock("axios", () => ({
  default: { create: mocks.create },
}));
vi.mock("@/utils/request", () => ({
  getAccessToken: vi.fn(() => null),
  refreshAccessToken: vi.fn(),
}));

import { handleV2ResponseError } from "./v2Request.js";

describe("V2 response errors", () => {
  beforeEach(() => {
    window.history.replaceState({}, "", "/my/wallet");
  });

  it("uses the standard backend msg for billing-required events", async () => {
    const eventPromise = new Promise((resolve) => {
      window.addEventListener("billing-required", resolve, { once: true });
    });
    const error = {
      config: {},
      response: {
        status: 402,
        data: { code: "INSUFFICIENT_BALANCE", msg: "余额不足，请先充值。" },
      },
    };

    await expect(handleV2ResponseError(error)).rejects.toBe(error);
    const event = await eventPromise;

    expect(event.detail.message).toBe("余额不足，请先充值。");
  });
});

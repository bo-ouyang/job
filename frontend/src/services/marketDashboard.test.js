import { describe, expect, it, vi } from "vitest";

import { loadMarketDashboard } from "./marketDashboard";

const sample = {
  updatedAt: "2026-07-28T10:00:00+08:00",
  kpis: [{ label: "在招岗位", value: "1,284,760" }],
};

describe("market dashboard service", () => {
  it("returns normalized API data when the public endpoint succeeds", async () => {
    const client = {
      getDashboard: vi.fn().mockResolvedValue({ data: sample }),
    };

    const result = await loadMarketDashboard({ city: "杭州" }, { client, fallback: {} });

    expect(client.getDashboard).toHaveBeenCalledWith({ city: "杭州" });
    expect(result).toEqual({
      data: sample,
      source: "api",
      updatedAt: sample.updatedAt,
    });
  });

  it("returns fallback data when the public endpoint is unavailable", async () => {
    const client = {
      getDashboard: vi.fn().mockRejectedValue(new Error("offline")),
    };

    const result = await loadMarketDashboard({}, { client, fallback: sample });

    expect(result).toEqual({
      data: sample,
      source: "fallback",
      updatedAt: sample.updatedAt,
    });
  });

  it("accepts unified response payloads without leaking transport details", async () => {
    const client = {
      getDashboard: vi.fn().mockResolvedValue({
        data: { code: 200, data: sample },
      }),
    };

    const result = await loadMarketDashboard({}, { client, fallback: {} });

    expect(result.data).toEqual(sample);
    expect(result.source).toBe("api");
  });
});

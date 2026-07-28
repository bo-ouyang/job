import { marketAPI } from "@/api/market";
import homeMockData from "@/data/homeMockData";

const unwrapPayload = (payload) => {
  if (payload?.code === 200 && payload.data !== undefined) return payload.data;
  return payload;
};

const getUpdatedAt = (data) => data?.updatedAt || data?.updated_at || null;

export async function loadMarketDashboard(
  params = {},
  { client = marketAPI, fallback = homeMockData } = {},
) {
  try {
    const response = await client.getDashboard(params);
    const data = unwrapPayload(response?.data);
    if (!data || typeof data !== "object") throw new Error("Invalid market payload");
    return { data, source: "api", updatedAt: getUpdatedAt(data) };
  } catch {
    return {
      data: fallback,
      source: "fallback",
      updatedAt: getUpdatedAt(fallback),
    };
  }
}

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  markAsRead: vi.fn(),
  markAllAsRead: vi.fn(),
  getUnreadCount: vi.fn(),
}));

vi.mock("@/utils/v2Request", () => ({ default: { get: mocks.get } }));
vi.mock("@/api/message", () => ({
  messageAPI: {
    markAsRead: mocks.markAsRead,
    markAllAsRead: mocks.markAllAsRead,
    getUnreadCount: mocks.getUnreadCount,
  },
}));

import { messagesAPI } from "./messages";

describe("messagesAPI", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the V2 list endpoint and maps the unread UI filter to its real query parameter", async () => {
    mocks.get.mockResolvedValue({
      data: { items: [{ id: "42", isRead: false, actionData: { runId: "18" } }], total: 1, skip: 0, limit: 20 },
    });

    const response = await messagesAPI.list({ category: "career", status: "completed", isRead: false, skip: 0, limit: 20 });

    expect(mocks.get).toHaveBeenCalledWith("/messages/", {
      params: { category: "career", status: "completed", unreadOnly: true, skip: 0, limit: 20 },
    });
    expect(response.data.items[0]).toMatchObject({ id: "42", isRead: false, actionData: { runId: "18" } });
  });

  it("contains the temporary V1 mutation boundary in this adapter", async () => {
    await messagesAPI.markAsRead("42");
    await messagesAPI.markAllAsRead();
    await messagesAPI.getUnreadCount();

    expect(mocks.markAsRead).toHaveBeenCalledWith("42");
    expect(mocks.markAllAsRead).toHaveBeenCalledTimes(1);
    expect(mocks.getUnreadCount).toHaveBeenCalledTimes(1);
  });
});

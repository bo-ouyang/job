import { beforeEach, describe, expect, it, vi } from "vitest";

const authMocks = vi.hoisted(() => ({
  getAccessToken: vi.fn(),
  getApiBaseUrl: vi.fn(),
  refreshAccessToken: vi.fn(),
}));

vi.mock("@/utils/request", () => authMocks);

import { connectAgentEventStream, parseSSEFrame } from "./sseClient";

beforeEach(() => {
  vi.restoreAllMocks();
  authMocks.getAccessToken.mockReturnValue("expired-token");
  authMocks.getApiBaseUrl.mockReturnValue("http://localhost:8000/api/v1");
  authMocks.refreshAccessToken.mockResolvedValue("fresh-token");
});

describe("parseSSEFrame", () => {
  it("parses an Agent event frame", () => {
    const frame = [
      "id: 1710000000-2",
      "event: tool_completed",
      'data: {"event":"tool_completed","sequence":2,"run_id":"100"}',
    ].join("\n");

    expect(parseSSEFrame(frame)).toEqual({
      id: "1710000000-2",
      event: "tool_completed",
      data: { event: "tool_completed", sequence: 2, run_id: "100" },
    });
  });

  it("ignores heartbeat and malformed frames", () => {
    expect(parseSSEFrame(": heartbeat 123")).toBeNull();
    expect(parseSSEFrame("event: bad\ndata: not-json")).toBeNull();
  });

  it("supports CRLF and multiline data", () => {
    const frame = "id: 1-0\r\nevent: message\r\ndata: {\"ok\":\r\ndata: true}";
    expect(parseSSEFrame(frame)?.data).toEqual({ ok: true });
  });

  it("refreshes an expired access token and retries the stream once", async () => {
    const headers = new Headers({ "content-type": "text/event-stream" });
    const emptyBody = () => ({
      getReader: () => ({ read: vi.fn().mockResolvedValue({ done: true }) }),
    });
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({ ok: false, status: 401, headers })
      .mockResolvedValueOnce({ ok: true, status: 200, headers, body: emptyBody() });

    await connectAgentEventStream({ runId: "run-1", onEvent: vi.fn() });

    expect(authMocks.refreshAccessToken).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe("Bearer expired-token");
    expect(fetchMock.mock.calls[1][1].headers.Authorization).toBe("Bearer fresh-token");
  });
});

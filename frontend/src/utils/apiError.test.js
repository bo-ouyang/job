import { describe, expect, it } from "vitest";

import { extractAgentRunReference, extractApiError } from "./apiError";


describe("extractApiError", () => {
  it("prefers the standard API msg and preserves error metadata", () => {
    expect(extractApiError({
      response: {
        status: 409,
        data: {
          code: "AGENT_ACTIVE_RUN_EXISTS",
          msg: "任务已经创建。",
          data: { runId: "9001", retryable: true },
        },
      },
    }, "请求失败")).toEqual({
      message: "任务已经创建。",
      code: "AGENT_ACTIVE_RUN_EXISTS",
      data: { runId: "9001", retryable: true },
      httpStatus: 409,
      retryable: true,
    });
  });

  it.each([
    [{ response: { data: { detail: "字符串详情" } } }, "字符串详情"],
    [{ response: { data: { detail: { message: "嵌套详情" } } } }, "嵌套详情"],
    [{ response: { data: { detail: { detail: "二级嵌套详情" } } } }, "二级嵌套详情"],
    [{ response: { data: { msg: { message: "对象消息" } } } }, "对象消息"],
    [{ response: { data: { message: "兼容消息" } } }, "兼容消息"],
    [{ response: { data: "字符串错误" } }, "字符串错误"],
    [new Error("网络连接失败"), "网络连接失败"],
    [{}, "默认错误"],
  ])("extracts supported message shapes %#", (error, expected) => {
    expect(extractApiError(error, "默认错误").message).toBe(expected);
  });

  it("marks transient HTTP failures retryable when the API did not decide", () => {
    expect(extractApiError({ response: { status: 503, data: {} } }, "服务繁忙").retryable)
      .toBe(true);
    expect(extractApiError({ response: { status: 400, data: {} } }, "参数错误").retryable)
      .toBe(false);
  });

  it("does not expose an Axios message when an HTTP response has no friendly error", () => {
    const result = extractApiError({
      message: "Request failed with status code 500",
      response: { status: 500, data: { traceId: "secret" } },
    }, "服务暂时不可用");

    expect(result.message).toBe("服务暂时不可用");
  });

  it("only accepts explicit boolean retryable values", () => {
    expect(extractApiError({
      response: { status: 400, data: { retryable: "true" } },
    }, "参数错误").retryable).toBe(false);
    expect(extractApiError({
      response: { status: 400, data: { retryable: true } },
    }, "参数错误").retryable).toBe(true);
  });

  it("whitelists active run recovery fields", () => {
    expect(extractAgentRunReference({
      runId: 9001,
      conversationId: "8001",
      status: "running",
      messageType: "career_report_request",
      internalPrompt: "do not expose",
    })).toEqual({
      runId: "9001",
      conversationId: "8001",
      status: "running",
      messageType: "career_report_request",
    });
    expect(extractAgentRunReference({ runId: "9001", status: "unknown" })).toBeNull();
  });
});

import { describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import { useAgentRunStream } from "./useAgentRunStream";

describe("useAgentRunStream", () => {
  it("deduplicates replayed events and batches deltas into one rendered value", async () => {
    let options;
    const stream = useAgentRunStream({
      connect: vi.fn((nextOptions) => {
        options = nextOptions;
        return new Promise(() => {});
      }),
      getRun: vi.fn(),
    });

    stream.start({ runId: "run-1", conversationId: "conversation-1" });
    await vi.waitFor(() => expect(options).toBeTruthy());

    await options.onEvent({
      event_id: "1-0", sequence: 1, event: "message_started", run_id: "run-1",
      data: { streamId: "stream-a" },
    });
    await options.onEvent({
      event_id: "2-0", sequence: 2, event: "message_delta", run_id: "run-1",
      data: { streamId: "stream-a", delta: "第一段" },
    });
    await options.onEvent({
      event_id: "2-0", sequence: 2, event: "message_delta", run_id: "run-1",
      data: { streamId: "stream-a", delta: "重复" },
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    await nextTick();

    expect(stream.content.value).toBe("第一段");
    expect(stream.lastEventId.value).toBe("2-0");
    stream.stop();
  });

  it("clears partial output when the server starts a newer stream attempt", async () => {
    let options;
    const stream = useAgentRunStream({
      connect: vi.fn((nextOptions) => {
        options = nextOptions;
        return new Promise(() => {});
      }),
      getRun: vi.fn(),
    });

    stream.start({ runId: "run-1" });
    await vi.waitFor(() => expect(options).toBeTruthy());
    await options.onEvent({ event_id: "1-0", event: "message_started", run_id: "run-1", data: { streamId: "old" } });
    await options.onEvent({ event_id: "2-0", event: "message_delta", run_id: "run-1", data: { streamId: "old", delta: "旧内容" } });
    await new Promise((resolve) => setTimeout(resolve, 20));
    await options.onEvent({ event_id: "3-0", event: "message_started", run_id: "run-1", data: { streamId: "new" } });
    await options.onEvent({ event_id: "4-0", event: "message_delta", run_id: "run-1", data: { streamId: "new", delta: "新内容" } });
    await new Promise((resolve) => setTimeout(resolve, 20));

    expect(stream.content.value).toBe("新内容");
    stream.stop();
  });

  it("uses message_completed content as canonical output and rejects legacy chunks after a stream id", async () => {
    let options;
    const stream = useAgentRunStream({
      connect: vi.fn((nextOptions) => {
        options = nextOptions;
        return new Promise(() => {});
      }),
      getRun: vi.fn(),
    });
    stream.start({ runId: "run-1", conversationId: "conversation-1" });
    await vi.waitFor(() => expect(options).toBeTruthy());

    await options.onEvent({ event_id: "1-0", event: "message_started", run_id: "run-1", data: { streamId: "attempt-1" } });
    await options.onEvent({ event_id: "2-0", event: "message_delta", run_id: "run-1", data: { delta: "must-ignore" } });
    await options.onEvent({ event_id: "3-0", event: "message_completed", run_id: "run-1", data: { streamId: "attempt-1", content: "canonical final" } });
    await options.onEvent({ event_id: "4-0", event: "run_completed", run_id: "run-1", data: {} });

    expect(stream.content.value).toBe("canonical final");
    expect(stream.isSuccessful.value).toBe(true);
    expect(stream.run.value).toMatchObject({ id: "run-1", conversationId: "conversation-1" });
    stream.stop();
  });

  it("delivers only the first terminal event for a generation", async () => {
    let options;
    const onTerminal = vi.fn();
    const stream = useAgentRunStream({
      connect: vi.fn((nextOptions) => {
        options = nextOptions;
        return new Promise(() => {});
      }),
      getRun: vi.fn(),
      onTerminal,
    });
    stream.start({ runId: "run-1" });
    await vi.waitFor(() => expect(options).toBeTruthy());
    await options.onEvent({ event_id: "1-0", event: "run_failed", run_id: "run-1", data: {} });
    await options.onEvent({ event_id: "2-0", event: "run_cancelled", run_id: "run-1", data: {} });

    expect(onTerminal).toHaveBeenCalledOnce();
    expect(onTerminal).toHaveBeenCalledWith(expect.objectContaining({ event: expect.objectContaining({ event: "run_failed" }) }));
    stream.stop();
  });

  it("merges terminal event data into the current run for error handling", async () => {
    let options;
    const stream = useAgentRunStream({
      connect: vi.fn((nextOptions) => {
        options = nextOptions;
        return new Promise(() => {});
      }),
      getRun: vi.fn(),
    });
    stream.start({ runId: "run-1", conversationId: "conversation-1" });
    await vi.waitFor(() => expect(options).toBeTruthy());
    await options.onEvent({
      event_id: "1-0", event: "run_failed", run_id: "run-1",
      data: { status: "failed", error_code: "AGENT_LLM_TIMEOUT", error_message: "provider timeout" },
    });

    expect(stream.run.value).toMatchObject({ status: "failed", error_code: "AGENT_LLM_TIMEOUT", error_message: "provider timeout" });
    stream.stop();
  });
});

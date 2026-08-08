import { computed, ref } from "vue";

const ACTIVE_STATUSES = new Set(["queued", "running"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled", "waiting_user"]);

const scheduleFrame = (callback) => (
  globalThis.requestAnimationFrame?.(callback) || setTimeout(callback, 16)
);
const cancelFrame = (id) => {
  if (globalThis.cancelAnimationFrame) globalThis.cancelAnimationFrame(id);
  else clearTimeout(id);
};

/**
 * Shared, lifecycle-owned transport for an AgentRun SSE stream.
 *
 * Components own presentation and recovery snapshots.  This utility owns exactly
 * one EventSource-like fetch stream, event replay de-duplication, delta batching,
 * reconnecting and the serial polling fallback used after repeated SSE failures.
 */
export function useAgentRunStream({
  connect,
  getRun,
  onEvent,
  onTerminal,
  onFallback,
  maxStreamFailures = 2,
  reconnectDelayMs = 900,
  pollDelayMs = 3000,
  fallbackInitialDelayMs = 3000,
  maxPollAttempts = 80,
  maxConsecutivePollErrors = 3,
  maxPollDelayMs = 15000,
} = {}) {
  const run = ref(null);
  const content = ref("");
  const status = ref("idle");
  const connectionState = ref("idle");
  const lastEventId = ref(null);
  const streamId = ref(null);
  const messageCompleted = ref(false);
  const runCompleted = ref(false);
  const isActive = computed(() => ACTIVE_STATUSES.has(status.value));
  const isSuccessful = computed(() => messageCompleted.value && runCompleted.value);

  let controller = null;
  let retryTimer = null;
  let pollTimer = null;
  let frameId = null;
  let generation = 0;
  let failures = 0;
  let pollAttempts = 0;
  let pollErrors = 0;
  let finalized = false;
  let queuedDelta = "";
  const seenEventIds = new Set();

  const clearTimers = () => {
    if (retryTimer) clearTimeout(retryTimer);
    if (pollTimer) clearTimeout(pollTimer);
    retryTimer = null;
    pollTimer = null;
    if (frameId !== null) cancelFrame(frameId);
    frameId = null;
    queuedDelta = "";
  };

  const flushDeltas = () => {
    frameId = null;
    if (!queuedDelta) return;
    content.value += queuedDelta;
    queuedDelta = "";
  };

  const queueDelta = (delta) => {
    if (!delta) return;
    queuedDelta += String(delta);
    if (frameId === null) frameId = scheduleFrame(flushDeltas);
  };

  const resetOutputForStream = (nextStreamId) => {
    if (!nextStreamId || nextStreamId === streamId.value) return;
    if (frameId !== null) cancelFrame(frameId);
    frameId = null;
    queuedDelta = "";
    streamId.value = nextStreamId;
    content.value = "";
    messageCompleted.value = false;
  };

  const stop = () => {
    generation += 1;
    controller?.abort();
    controller = null;
    clearTimers();
    if (connectionState.value !== "closed") connectionState.value = "closed";
  };

  const finish = async (event, expectedGeneration) => {
    if (expectedGeneration !== generation || finalized) return;
    finalized = true;
    clearTimers();
    controller?.abort();
    controller = null;
    connectionState.value = "closed";
    await onTerminal?.({
      event,
      run: run.value,
      content: content.value,
      successful: isSuccessful.value,
    });
  };

  const poll = async (runId, expectedGeneration) => {
    if (expectedGeneration !== generation || !ACTIVE_STATUSES.has(status.value)) return;
    if (pollAttempts >= maxPollAttempts) {
      status.value = "failed";
      run.value = { ...run.value, status: "failed", error_code: "AGENT_POLL_TIMEOUT" };
      await finish({ event: "run_failed", data: run.value }, expectedGeneration);
      return;
    }
    pollAttempts += 1;
    try {
      if (typeof getRun !== "function") throw new Error("Missing getRun transport");
      const response = await getRun(String(runId));
      if (expectedGeneration !== generation) return;
      const nextRun = response?.data || {};
      run.value = { ...run.value, ...nextRun };
      status.value = nextRun.status || status.value;
      if (TERMINAL_STATUSES.has(status.value)) {
        if (status.value === "completed") runCompleted.value = true;
        await finish({ event: `run_${status.value}`, data: nextRun }, expectedGeneration);
        return;
      }
      pollErrors = 0;
    } catch {
      pollErrors += 1;
      if (pollErrors >= maxConsecutivePollErrors) {
        status.value = "failed";
        run.value = { ...run.value, status: "failed", error_code: "AGENT_POLL_UNAVAILABLE" };
        await finish({ event: "run_failed", data: run.value }, expectedGeneration);
        return;
      }
    }
    if (expectedGeneration === generation && ACTIVE_STATUSES.has(status.value)) {
      const delay = pollErrors
        ? Math.min(pollDelayMs * (2 ** pollErrors), maxPollDelayMs)
        : pollDelayMs;
      pollTimer = setTimeout(() => poll(runId, expectedGeneration), delay);
    }
  };

  const fallBackToPolling = (runId, expectedGeneration) => {
    if (expectedGeneration !== generation || !ACTIVE_STATUSES.has(status.value)) return;
    connectionState.value = "polling";
    controller?.abort();
    controller = null;
    // Later attempts are scheduled only by poll(), so requests never overlap.
    if (!pollTimer && fallbackInitialDelayMs > 0) {
      pollTimer = setTimeout(() => poll(runId, expectedGeneration), fallbackInitialDelayMs);
    } else if (!pollTimer) {
      void poll(runId, expectedGeneration);
    }
  };

  const open = async (runId, expectedGeneration) => {
    if (expectedGeneration !== generation || !ACTIVE_STATUSES.has(status.value)) return;
    controller = new AbortController();
    connectionState.value = failures ? "reconnecting" : "connecting";
    try {
      if (typeof connect !== "function") throw new Error("Missing SSE transport");
      await connect({
        runId: String(runId),
        lastEventId: lastEventId.value,
        signal: controller.signal,
        onOpen: () => {
          if (expectedGeneration === generation) connectionState.value = "streaming";
        },
        onEvent: (event) => handleEvent(event, expectedGeneration),
      });
      if (expectedGeneration !== generation || controller?.signal.aborted) return;
      if (!ACTIVE_STATUSES.has(status.value)) return;
      failures += 1;
    } catch (error) {
      if (expectedGeneration !== generation || controller?.signal.aborted) return;
      failures += 1;
      connectionState.value = "reconnecting";
    }
    if (failures > maxStreamFailures) {
      if (onFallback?.({ run: run.value, failures })) return;
      fallBackToPolling(runId, expectedGeneration);
      return;
    }
    retryTimer = setTimeout(() => open(runId, expectedGeneration), reconnectDelayMs);
  };

  const handleEvent = async (event, expectedGeneration = generation) => {
    if (expectedGeneration !== generation || !event || String(event.run_id) !== String(run.value?.id)) return;
    const eventId = event.event_id;
    const eventKey = eventId && `${event.run_id}:${eventId}`;
    if (eventKey && seenEventIds.has(eventKey)) return;
    if (eventKey) seenEventIds.add(eventKey);
    if (eventId && eventId !== "0-0") lastEventId.value = eventId;

    const data = event.data || {};
    const eventStreamId = data.streamId || data.stream_id || null;
    if (event.event === "message_started") resetOutputForStream(eventStreamId);
    if (event.event === "message_delta") {
      if (streamId.value && eventStreamId !== streamId.value) return;
      if (eventStreamId && streamId.value && eventStreamId !== streamId.value) return;
      if (eventStreamId && !streamId.value) streamId.value = eventStreamId;
      status.value = "running";
      queueDelta(data.delta);
    }
    if (event.event === "run_started") status.value = "running";
    if (event.event === "clarification_required") status.value = "waiting_user";
    if (event.event === "message_completed") {
      if (!streamId.value || eventStreamId === streamId.value) {
        flushDeltas();
        if (typeof data.content === "string") content.value = data.content;
        messageCompleted.value = true;
      }
    }
    if (["run_completed", "run_failed", "run_cancelled"].includes(event.event)) {
      status.value = event.event.replace("run_", "");
      if (status.value === "completed") runCompleted.value = true;
    }
    run.value = {
      ...run.value,
      ...(["run_completed", "run_failed", "run_cancelled"].includes(event.event) ? data : {}),
      status: status.value,
    };
    await onEvent?.(event, { content: content.value, status: status.value });
    if (TERMINAL_STATUSES.has(status.value)) await finish(event, expectedGeneration);
  };

  const start = ({ runId, conversationId = null, initialStatus = "queued" } = {}) => {
    if (!runId) return;
    stop();
    const expectedGeneration = ++generation;
    run.value = { id: String(runId), conversationId: conversationId ? String(conversationId) : null, status: initialStatus };
    status.value = initialStatus;
    connectionState.value = "connecting";
    content.value = "";
    streamId.value = null;
    lastEventId.value = null;
    messageCompleted.value = false;
    runCompleted.value = false;
    failures = 0;
    pollAttempts = 0;
    pollErrors = 0;
    finalized = false;
    seenEventIds.clear();
    void open(runId, expectedGeneration);
  };

  return {
    run,
    content,
    status,
    connectionState,
    lastEventId,
    streamId,
    messageCompleted,
    runCompleted,
    isActive,
    isSuccessful,
    start,
    stop,
    handleEvent,
    getCurrentRun: () => run.value,
  };
}

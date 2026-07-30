import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  getProfile: vi.fn(),
  getRun: vi.fn(),
  connect: vi.fn(),
}));

vi.mock("@/api/agent", () => ({
  agentAPI: {
    getCapabilities: mocks.getCapabilities,
    listConversations: mocks.listConversations,
    getConversation: mocks.getConversation,
    getProfile: mocks.getProfile,
    getRun: mocks.getRun,
  },
}));

vi.mock("@/utils/sseClient", () => ({
  connectAgentEventStream: mocks.connect,
}));

import { useAgentStore } from "./agent";

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

describe("Agent store", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    localStorage.clear();
    vi.clearAllMocks();
  });

  it("discards stale conversation responses", async () => {
    const first = deferred();
    const second = deferred();
    mocks.getConversation
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const store = useAgentStore();

    const openingA = store.openConversation("A");
    const openingB = store.openConversation("B");
    second.resolve({ data: { conversation: { id: "B" }, messages: [], latest_run: null } });
    await openingB;
    first.resolve({ data: { conversation: { id: "A" }, messages: [], latest_run: null } });
    await openingA;

    expect(store.activeConversation.id).toBe("B");
  });

  it("clears all persisted user state on reset", () => {
    const store = useAgentStore();
    store.uploadedDocument = { name: "private.pdf" };
    store.selectedDirection = "secret-direction";
    store.completedActions = ["task-1"];
    store.savedOpportunities = ["job-1"];
    localStorage.setItem("agentWorkspace", "private");

    store.reset();

    expect(store.uploadedDocument).toBeNull();
    expect(store.selectedDirection).toBe("ai-pm");
    expect(store.completedActions).toEqual([]);
    expect(store.savedOpportunities).toEqual([]);
    expect(localStorage.getItem("agentWorkspace")).toBeNull();
  });

  it("uses the backend capability as the runtime feature gate", async () => {
    mocks.getCapabilities.mockResolvedValue({ data: { enabled: false } });
    const store = useAgentStore();
    expect(await store.loadCapabilities()).toBe(false);
    expect(store.featureAvailable).toBe(false);
  });

  it("allows the backend to enable Agent when the frontend flag is omitted", async () => {
    mocks.getCapabilities.mockResolvedValue({ data: { enabled: true } });
    const store = useAgentStore();

    expect(store.capabilitiesLoaded).toBe(false);
    expect(await store.loadCapabilities()).toBe(true);
    expect(store.featureAvailable).toBe(true);
    expect(store.capabilitiesLoaded).toBe(true);
    expect(mocks.getCapabilities).toHaveBeenCalledOnce();
  });

  it("keeps Agent availability pending until the backend capability resolves", async () => {
    const capability = deferred();
    mocks.getCapabilities.mockReturnValue(capability.promise);
    const store = useAgentStore();

    const loading = store.loadCapabilities();

    expect(store.capabilitiesLoaded).toBe(false);
    capability.resolve({ data: { enabled: true } });
    await loading;
    expect(store.capabilitiesLoaded).toBe(true);
  });

  it("does not reconnect after a terminal run event", async () => {
    mocks.getConversation.mockResolvedValue({
      data: {
        conversation: { id: "conversation-1" },
        messages: [],
        latest_run: { id: "run-1", status: "completed" },
      },
    });
    mocks.connect.mockImplementation(async ({ onOpen, onEvent }) => {
      onOpen();
      await onEvent({
        event_id: "1-0",
        event: "run_completed",
        sequence: 1,
        run_id: "run-1",
        data: {},
      });
    });
    const store = useAgentStore();
    store.activeConversation = { id: "conversation-1" };
    store.activeRun = { id: "run-1", status: "running" };

    await store.startRunStream("run-1");

    expect(store.activeRun.status).toBe("completed");
    expect(store.connectionState).not.toBe("reconnecting");
    expect(store.reconnectAttempt).toBe(0);
    expect(mocks.connect).toHaveBeenCalledOnce();
  });

  it("restores a waiting run without reopening the event stream", async () => {
    mocks.getRun.mockResolvedValue({ data: { id: "run-1", status: "waiting_user" } });
    mocks.getConversation.mockResolvedValue({
      data: {
        conversation: { id: "conversation-1" },
        messages: [],
        latest_run: { id: "run-1", status: "waiting_user" },
      },
    });
    const store = useAgentStore();
    store.activeConversation = { id: "conversation-1" };

    await store.recoverRun("run-1", { reconnectActive: true });

    expect(store.activeRun.status).toBe("waiting_user");
    expect(store.connectionState).toBe("paused");
    expect(mocks.connect).not.toHaveBeenCalled();
  });

  it("does not let an old terminal snapshot overwrite a newly opened conversation", async () => {
    const staleSnapshot = deferred();
    mocks.connect.mockImplementation(async ({ onEvent }) => {
      await onEvent({
        event_id: "1-0",
        event: "run_completed",
        sequence: 1,
        run_id: "run-A",
        data: {},
      });
    });
    mocks.getConversation
      .mockReturnValueOnce(staleSnapshot.promise)
      .mockResolvedValueOnce({
        data: { conversation: { id: "B" }, messages: [], latest_run: null },
      });
    const store = useAgentStore();
    store.activeConversation = { id: "A" };
    store.activeRun = { id: "run-A", status: "running" };

    const terminalRefresh = store.startRunStream("run-A");
    await vi.waitFor(() => expect(mocks.getConversation).toHaveBeenCalledWith("A"));
    await store.openConversation("B");
    staleSnapshot.resolve({
      data: {
        conversation: { id: "A" },
        messages: [],
        latest_run: { id: "run-A", status: "completed" },
      },
    });
    await terminalRefresh;

    expect(store.activeConversation.id).toBe("B");
  });
});

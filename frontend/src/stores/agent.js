import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { agentAPI } from "@/api/agent";
import {
  documentMock,
  initialMessages,
  responseLibrary,
  runStages,
  weeklyActions,
} from "@/data/agentMockData";
import { connectAgentEventStream } from "@/utils/sseClient";

const wait = (duration) => new Promise((resolve) => setTimeout(resolve, duration));
const DATA_SOURCE = import.meta.env.VITE_AGENT_DATA_SOURCE || "hybrid";
const FRONTEND_AGENT_ENABLED = import.meta.env.VITE_AGENT_ENABLED !== "false";
const ACTIVE_STATUSES = new Set(["queued", "running"]);
const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

function currentTime(value = new Date()) {
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function makeIdempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `agent-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalizeMessage(message) {
  return {
    ...message,
    id: String(message.id),
    conversation_id: message.conversation_id ? String(message.conversation_id) : null,
    time: currentTime(message.created_at || Date.now()),
    metadata: message.metadata || {},
  };
}

export const useAgentStore = defineStore(
  "agentWorkspace",
  () => {
    const conversations = ref([]);
    const activeConversation = ref(null);
    const messages = ref(
      DATA_SOURCE === "mock" ? initialMessages.map((message) => ({ ...message })) : [],
    );
    const activeRun = ref(null);
    const runEvents = ref([]);
    const careerProfile = ref(null);
    const connectionState = ref("idle");
    const lastEventId = ref(null);
    const lastEventSequence = ref(0);
    const reconnectAttempt = ref(0);
    const isSending = ref(false);
    const error = ref(null);
    const structuredResult = ref(null);
    const activeMessageStreamId = ref(null);
    const activeStreamingMessageId = ref(null);
    const featureAvailable = ref(
      DATA_SOURCE === "mock" && FRONTEND_AGENT_ENABLED,
    );
    const capabilitiesLoaded = ref(DATA_SOURCE === "mock");

    const uploadedDocument = ref(null);
    const isUploading = ref(false);
    const selectedDirection = ref("ai-pm");
    const completedActions = ref([]);
    const savedOpportunities = ref([]);

    let streamController = null;
    let reconnectTimer = null;
    let streamGeneration = 0;
    let openGeneration = 0;
    const seenEvents = new Set();

    const isApiMode = computed(() => DATA_SOURCE !== "mock");
    // Dashboard modules remain mock until dedicated plan/task/recommendation APIs exist.
    const isDashboardMock = computed(() => true);
    const isThinking = computed(
      () => isSending.value || ACTIVE_STATUSES.has(activeRun.value?.status),
    );
    const runState = computed(() => {
      const status = activeRun.value?.status;
      if (status === "completed") return "complete";
      if (status === "waiting_user") return "waiting";
      if (status === "failed") return "failed";
      if (status === "cancelled") return "cancelled";
      if (ACTIVE_STATUSES.has(status)) return "running";
      return "idle";
    });
    const activeStage = computed(() => {
      const events = runEvents.value;
      if (events.some((event) => event.event === "message_completed")) return 3;
      if (events.some((event) => event.event === "tool_completed")) return 2;
      if (events.some((event) => event.event === "tool_started")) return 1;
      if (events.some((event) => event.event === "plan_created")) return 0;
      return activeRun.value?.status === "running" ? 0 : -1;
    });
    const completedCount = computed(() => completedActions.value.length);
    const weeklyProgress = computed(() =>
      Math.round((completedCount.value / weeklyActions.length) * 100),
    );

    async function loadConversations() {
      if (!isApiMode.value) return [];
      const response = await agentAPI.listConversations({ page: 1, page_size: 50 });
      conversations.value = response.data?.items || [];
      return conversations.value;
    }

    async function loadCapabilities() {
      if (!isApiMode.value || !FRONTEND_AGENT_ENABLED) {
        featureAvailable.value = false;
        capabilitiesLoaded.value = true;
        return false;
      }
      try {
        const response = await agentAPI.getCapabilities();
        featureAvailable.value = Boolean(response.data?.enabled);
      } catch {
        featureAvailable.value = false;
      } finally {
        capabilitiesLoaded.value = true;
      }
      return featureAvailable.value;
    }

    async function loadProfile() {
      if (!isApiMode.value) return null;
      try {
        const response = await agentAPI.getProfile();
        careerProfile.value = response.data;
        return careerProfile.value;
      } catch {
        return null;
      }
    }

    async function createConversation(title = "新的职业规划") {
      const response = await agentAPI.createConversation({
        title,
        context: { source: "agent_workspace" },
      });
      activeConversation.value = response.data;
      conversations.value = [
        response.data,
        ...conversations.value.filter((item) => item.id !== response.data.id),
      ];
      messages.value = [];
      return response.data;
    }

    async function openConversation(conversationId) {
      if (!isApiMode.value || !conversationId) return null;
      stopRunStream();
      connectionState.value = "recovering";
      error.value = null;
      const generation = ++openGeneration;
      try {
        const response = await agentAPI.getConversation(String(conversationId));
        if (generation !== openGeneration) return null;
        const detail = response.data;
        activeConversation.value = detail.conversation;
        messages.value = (detail.messages || []).map(normalizeMessage);
        activeRun.value = detail.latest_run || null;
        structuredResult.value = extractLatestResult(messages.value);
        runEvents.value = [];
        lastEventId.value = null;
        lastEventSequence.value = 0;
        seenEvents.clear();
        connectionState.value = "idle";
        if (ACTIVE_STATUSES.has(activeRun.value?.status)) {
          void startRunStream(activeRun.value.id);
        }
        return detail;
      } catch (requestError) {
        if (generation !== openGeneration) return null;
        connectionState.value = "failed";
        error.value = requestError?.response?.data?.msg || "会话加载失败";
        throw requestError;
      }
    }

    async function sendMessage(content, context = {}) {
      const text = content.trim();
      if (!text || isSending.value || ACTIVE_STATUSES.has(activeRun.value?.status)) return null;
      if (!isApiMode.value) return sendMockMessage(text);
      if (!featureAvailable.value && activeRun.value?.status !== "waiting_user") {
        error.value = "职业规划 Agent 当前未对该账号开放";
        return null;
      }

      isSending.value = true;
      error.value = null;
      try {
        if (!activeConversation.value) {
          await createConversation(text.slice(0, 30) || "新的职业规划");
        }
        const response = await agentAPI.sendMessage(
          activeConversation.value.id,
          { content: text, message_type: "text", context },
          makeIdempotencyKey(),
        );
        const payload = response.data;
        if (!messages.value.some((message) => message.id === String(payload.message.id))) {
          messages.value.push(normalizeMessage(payload.message));
        }
        activeRun.value = payload.run;
        runEvents.value = [];
        lastEventId.value = null;
        lastEventSequence.value = 0;
        reconnectAttempt.value = 0;
        seenEvents.clear();
        void startRunStream(payload.run.id);
        return {
          conversationId: String(activeConversation.value.id),
          runId: String(payload.run.id),
        };
      } catch (requestError) {
        error.value = requestError?.response?.data?.msg || "消息发送失败";
        throw requestError;
      } finally {
        isSending.value = false;
      }
    }

    async function startRunStream(runId, { preserveAttempts = false } = {}) {
      if (!isApiMode.value || !runId) return;
      stopRunStream({ clearReconnect: false });
      if (!preserveAttempts) reconnectAttempt.value = 0;
      const generation = ++streamGeneration;
      streamController = new AbortController();
      connectionState.value = reconnectAttempt.value ? "reconnecting" : "connecting";

      try {
        await connectAgentEventStream({
          runId: String(runId),
          lastEventId: lastEventId.value,
          signal: streamController.signal,
          onOpen: () => {
            if (generation === streamGeneration) connectionState.value = "streaming";
          },
          onEvent: async (event) => {
            if (generation !== streamGeneration) return;
            await handleEvent(event);
          },
        });
        if (generation !== streamGeneration) return;
        if (activeRun.value?.status === "waiting_user" || TERMINAL_STATUSES.has(activeRun.value?.status)) {
          connectionState.value = activeRun.value.status === "waiting_user" ? "paused" : "closed";
          return;
        }
        scheduleReconnect(runId);
      } catch (streamError) {
        if (streamController?.signal.aborted || generation !== streamGeneration) return;
        error.value = streamError.message || "实时连接中断";
        scheduleReconnect(runId);
      }
    }

    async function handleEvent(event) {
      const eventId = event.event_id;
      const eventKey = `${event.run_id}:${eventId}:${event.event}`;
      if (eventId !== "0-0" && seenEvents.has(eventKey)) return;
      seenEvents.add(eventKey);
      if (eventId && eventId !== "0-0") lastEventId.value = eventId;
      if (event.event_id !== "0-0" && event.sequence > lastEventSequence.value) {
        lastEventSequence.value = event.sequence;
      }
      runEvents.value.push(event);
      if (runEvents.value.length > 100) runEvents.value.shift();

      if (!activeRun.value || String(activeRun.value.id) !== String(event.run_id)) return;
      if (event.event === "run_started") activeRun.value.status = "running";
      if (event.event === "clarification_required") activeRun.value.status = "waiting_user";
      const eventStreamId = event.data?.streamId || event.data?.stream_id || null;
      if (event.event === "message_started") {
        activeMessageStreamId.value = eventStreamId;
        activeStreamingMessageId.value = `stream-${event.run_id}`;
        messages.value = messages.value.filter((message) => message.id !== activeStreamingMessageId.value);
        messages.value.push({
          id: activeStreamingMessageId.value,
          role: "assistant",
          content: "",
          message_type: "streaming",
          created_at: new Date().toISOString(),
          time: currentTime(),
          metadata: { runId: String(event.run_id), streamId: eventStreamId },
        });
      }
      if (event.event === "message_delta") {
        if (activeMessageStreamId.value && eventStreamId !== activeMessageStreamId.value) return;
        const streamingMessage = messages.value.find((message) => message.id === activeStreamingMessageId.value);
        if (streamingMessage) streamingMessage.content += String(event.data?.delta || "");
      }
      if (event.event === "message_completed") {
        if (activeMessageStreamId.value && eventStreamId !== activeMessageStreamId.value) return;
        const streamingMessage = messages.value.find((message) => message.id === activeStreamingMessageId.value);
        if (streamingMessage && typeof event.data?.content === "string") streamingMessage.content = event.data.content;
        structuredResult.value = event.data?.result || null;
      }
      if (event.event === "run_completed") activeRun.value.status = "completed";
      if (event.event === "run_failed") {
        activeRun.value.status = "failed";
        const streamingMessage = messages.value.find((message) => message.id === activeStreamingMessageId.value);
        if (streamingMessage) streamingMessage.content = "本次分析未完成，未生成可用回答。";
        error.value = event.data?.message || event.data?.error_code || "Agent 分析失败";
      }
      if (event.event === "run_cancelled") activeRun.value.status = "cancelled";

      if (
        event.event === "clarification_required" ||
        event.event === "run_completed" ||
        event.event === "run_failed" ||
        event.event === "run_cancelled"
      ) {
        stopRunStream({ clearReconnect: true });
        await refreshActiveSnapshot();
      }
    }

    async function refreshActiveSnapshot() {
      const conversationId = activeConversation.value?.id;
      if (!conversationId) return;
      const generation = openGeneration;
      try {
        const response = await agentAPI.getConversation(conversationId);
        if (
          generation !== openGeneration ||
          String(activeConversation.value?.id) !== String(conversationId)
        ) return;
        const detail = response.data;
        activeConversation.value = detail.conversation;
        messages.value = (detail.messages || []).map(normalizeMessage);
        activeRun.value = detail.latest_run || activeRun.value;
        if (activeRun.value?.status === "failed") {
          error.value = activeRun.value.error_message || activeRun.value.error_code || error.value;
        }
        structuredResult.value = extractLatestResult(messages.value) || structuredResult.value;
      } catch (requestError) {
        error.value = requestError?.response?.data?.msg || "运行结果恢复失败";
      }
    }

    function scheduleReconnect(runId) {
      if (reconnectTimer || !ACTIVE_STATUSES.has(activeRun.value?.status)) return;
      if (reconnectAttempt.value >= 5) {
        connectionState.value = "degraded";
        reconnectTimer = setTimeout(async () => {
          reconnectTimer = null;
          await recoverRun(runId, { reconnectActive: false });
        }, 15000);
        return;
      }
      reconnectAttempt.value += 1;
      connectionState.value = "reconnecting";
      const baseDelay = Math.min(1000 * 2 ** (reconnectAttempt.value - 1), 15000);
      const delay = baseDelay + Math.round(Math.random() * 350);
      reconnectTimer = setTimeout(async () => {
        reconnectTimer = null;
        await recoverRun(runId, { reconnectActive: true });
      }, delay);
    }

    async function recoverRun(runId, { reconnectActive = false } = {}) {
      if (!isApiMode.value || !runId) return;
      try {
        const response = await agentAPI.getRun(runId);
        activeRun.value = response.data;
        if (ACTIVE_STATUSES.has(response.data.status) && reconnectActive) {
          void startRunStream(runId, { preserveAttempts: true });
          return;
        }
        await refreshActiveSnapshot();
        connectionState.value = response.data.status === "waiting_user"
          ? "paused"
          : ACTIVE_STATUSES.has(response.data.status) ? "degraded" : "closed";
      } catch (requestError) {
        connectionState.value = "failed";
        error.value = requestError?.response?.data?.msg || "运行状态恢复失败";
      }
    }

    async function cancelRun() {
      if (!isApiMode.value || !activeRun.value || !ACTIVE_STATUSES.has(activeRun.value.status)) return;
      const response = await agentAPI.cancelRun(activeRun.value.id);
      activeRun.value = response.data;
      stopRunStream();
      connectionState.value = "closed";
      await refreshActiveSnapshot();
    }

    function stopRunStream({ clearReconnect = true } = {}) {
      streamGeneration += 1;
      streamController?.abort();
      streamController = null;
      if (clearReconnect && reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    }

    async function runAnalysis() {
      if (isApiMode.value) {
        return sendMessage("请基于我的最新信息和当前市场数据，重新生成职业规划建议。", {
          source: "reanalyze_button",
        });
      }
      if (activeRun.value?.status === "running") return;
      activeRun.value = { id: `mock-${Date.now()}`, status: "running" };
      for (let index = 0; index < runStages.length; index += 1) {
        runEvents.value.push({ event: index ? "tool_started" : "plan_created" });
        await wait(620);
      }
      activeRun.value.status = "completed";
      messages.value.push({
        id: `run-${Date.now()}`,
        role: "assistant",
        time: currentTime(),
        content: "分析已完成。我更新了方向匹配、技能差距和本周行动建议。",
      });
    }

    async function sendMockMessage(text) {
      messages.value.push({ id: `user-${Date.now()}`, role: "user", time: currentTime(), content: text });
      isSending.value = true;
      await wait(850);
      messages.value.push({
        id: `assistant-${Date.now()}`,
        role: "assistant",
        time: currentTime(),
        content: responseLibrary[text] || responseLibrary.default,
      });
      isSending.value = false;
      return { conversationId: "mock", runId: "mock" };
    }

    async function mockUpload(file) {
      if (!file || isUploading.value) return;
      isUploading.value = true;
      await wait(900);
      uploadedDocument.value = {
        ...documentMock,
        name: file.name || documentMock.name,
        meta: `${file.name?.split(".").pop()?.toUpperCase() || "PDF"} · ${file.size ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "1.8 MB"}`,
      };
      isUploading.value = false;
    }

    function useMockDocument() { uploadedDocument.value = { ...documentMock }; }
    function removeDocument() { uploadedDocument.value = null; }
    function toggleAction(id) {
      completedActions.value = completedActions.value.includes(id)
        ? completedActions.value.filter((actionId) => actionId !== id)
        : [...completedActions.value, id];
    }
    function toggleSavedOpportunity(id) {
      savedOpportunities.value = savedOpportunities.value.includes(id)
        ? savedOpportunities.value.filter((opportunityId) => opportunityId !== id)
        : [...savedOpportunities.value, id];
    }
    function chooseDirection(id) { selectedDirection.value = id; }

    function reset() {
      openGeneration += 1;
      stopRunStream();
      conversations.value = [];
      activeConversation.value = null;
      messages.value = DATA_SOURCE === "mock" ? initialMessages.map((message) => ({ ...message })) : [];
      activeRun.value = null;
      runEvents.value = [];
      careerProfile.value = null;
      connectionState.value = "idle";
      lastEventId.value = null;
      lastEventSequence.value = 0;
      reconnectAttempt.value = 0;
      isSending.value = false;
      error.value = null;
      structuredResult.value = null;
      activeMessageStreamId.value = null;
      activeStreamingMessageId.value = null;
      featureAvailable.value = DATA_SOURCE === "mock" && import.meta.env.VITE_AGENT_ENABLED === "true";
      capabilitiesLoaded.value = DATA_SOURCE === "mock";
      uploadedDocument.value = null;
      isUploading.value = false;
      selectedDirection.value = "ai-pm";
      completedActions.value = [];
      savedOpportunities.value = [];
      seenEvents.clear();
      localStorage.removeItem("agentWorkspace");
    }

    function extractLatestResult(messageList) {
      for (let index = messageList.length - 1; index >= 0; index -= 1) {
        const result = messageList[index]?.metadata?.result;
        if (result) return result;
      }
      return null;
    }

    return {
      dataSource: DATA_SOURCE,
      conversations,
      activeConversation,
      messages,
      activeRun,
      runEvents,
      careerProfile,
      connectionState,
      lastEventId,
      reconnectAttempt,
      isSending,
      error,
      structuredResult,
      activeMessageStreamId,
      featureAvailable,
      capabilitiesLoaded,
      isApiMode,
      isDashboardMock,
      isThinking,
      runState,
      activeStage,
      uploadedDocument,
      isUploading,
      selectedDirection,
      completedActions,
      savedOpportunities,
      completedCount,
      weeklyProgress,
      loadConversations,
      loadCapabilities,
      loadProfile,
      createConversation,
      openConversation,
      sendMessage,
      startRunStream,
      recoverRun,
      cancelRun,
      stopRunStream,
      runAnalysis,
      mockUpload,
      useMockDocument,
      removeDocument,
      toggleAction,
      toggleSavedOpportunity,
      chooseDirection,
      reset,
    };
  },
  {
    persist: {
      pick: [
        "selectedDirection",
        "completedActions",
        "savedOpportunities",
      ],
    },
  },
);

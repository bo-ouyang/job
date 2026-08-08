<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { agentAPI } from "@/api/agent";
import { careerAPI } from "@/api/career";
import careerMockData from "@/data/careerMockData";
import { useAuthStore } from "@/stores/auth";
import { useAiTaskStore } from "@/stores/aiTask";
import { extractAgentRunReference, extractApiError } from "@/utils/apiError";
import { useAgentRunStream } from "@/composables/useAgentRunStream";
import { connectAgentEventStream } from "@/utils/sseClient";

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const aiTaskStore = useAiTaskStore();
const loading = ref(false);
const generating = ref(false);
const overview = ref(careerMockData);
const pricing = ref({});
const question = ref("");
const asking = ref(false);
const questionRunActive = ref(false);
const activeQuestionRun = ref(null);
const questionCancelling = ref(false);
const answer = ref("");
const errorMessage = ref("");
const filters = reactive({ city: "杭州", industry: "互联网 / AI", direction: "AI 产品经理" });
const run = ref(null);
const latestReport = ref(null);
const clarification = ref(null);
const clarificationAnswer = ref("");
const clarificationSubmitting = ref(false);
let runPollTimer = null;
let questionPollTimer = null;
let runPollGeneration = 0;
let questionPollGeneration = 0;
let clarificationLoadGeneration = 0;
let reportRefreshGeneration = 0;
let lifecycleGeneration = 0;
let reportSubmissionGeneration = 0;
let questionSubmissionGeneration = 0;
let mounted = false;

const POLL_INTERVAL_MS = 3000;
const POLL_DEADLINE_MS = 5 * 60 * 1000;
const MAX_POLL_ATTEMPTS = 80;
const MAX_CONSECUTIVE_POLL_ERRORS = 3;
const POLLING_TIMEOUT_MESSAGE = "AI 分析等待时间过长，请稍后重试。";
const POLLING_NETWORK_MESSAGE = "网络连接不稳定，已停止等待。请检查网络后重试。";
const POLLING_STATUS_MESSAGE = "AI 任务状态异常，已停止等待。请重新发起分析。";
const UNKNOWN_AGENT_ERROR = "AI 分析暂时失败，请稍后重试。";

const ERROR_MAP = {
  AGENT_DEADLINE_EXCEEDED: "分析超过最长处理时间，请稍后重试。",
  AGENT_LIMIT_EXCEEDED: "本次分析步骤超过安全上限，请调整问题后重试。",
  AGENT_RUNTIME_ERROR: "AI 分析运行异常，请稍后重试。",
  AGENT_RUN_STALE: "分析任务已失效，请重新发起。",
  AGENT_LLM_NOT_CONFIGURED: "AI 服务尚未正确配置，请联系管理员。",
  AGENT_LLM_QUOTA_EXCEEDED: "AI 模型服务余额不足，请联系管理员充值后重试。",
  AGENT_LLM_UNAVAILABLE: "AI 服务暂时不可用，请稍后重试。",
  AGENT_LLM_TIMEOUT: "模型响应超时，请稍后重试。",
  AGENT_LLM_INVALID_OUTPUT: "AI 返回内容格式异常，请稍后重试。",
  AGENT_EVIDENCE_UNAVAILABLE: "当前职位过于小众或市场数据不足，请更换关键词或放宽筛选条件。",
  AGENT_DISPATCH_FAILED: "分析任务暂时无法启动，请稍后重试。",
};

const agentFailureMessage = (code) => ERROR_MAP[code] || UNKNOWN_AGENT_ERROR;

const STAGE_LABELS = {
  load_context: "读取个人资料…",
  understand_and_plan: "分析需求与规划…",
  clarification_required: "等待补充信息…",
  execute_tools: "查询市场数据…",
  evaluate_evidence: "评估证据…",
  compose_answer: "生成报告…",
  save_result: "保存结果…",
  completed: "分析完成",
  failed: "分析失败",
  cancelled: "已取消",
};
const ACTIVE_RUN_STATUSES = ["queued", "running", "waiting_user"];

const reportPrice = computed(() => pricing.value.careerReport?.amount || "");
const questionPrice = computed(() => pricing.value.careerQuestion?.amount || "");
const syntheticDimensionCount = computed(
  () => overview.value?.dataStatus?.syntheticDimensions?.length || 0,
);
const runActive = computed(() => ACTIVE_RUN_STATUSES.includes(run.value?.status));
const ordinaryQuestionDisabled = computed(
  () => asking.value || questionRunActive.value || Boolean(clarification.value),
);
const runStage = computed(() => {
  if (!run.value) return "";
  if (run.value.status === "waiting_user") return STAGE_LABELS.clarification_required;
  if (["completed", "failed", "cancelled"].includes(run.value.status)) {
    return STAGE_LABELS[run.value.status];
  }
  return STAGE_LABELS[run.value.current_node] || "正在准备…";
});
const generateLabel = computed(() => {
  if (generating.value || runActive.value) return "分析中…";
  if (!authStore.isAuthenticated) return "登录后生成职业分析";
  return reportPrice.value ? `重新分析 · ¥${reportPrice.value}` : "重新生成职业分析";
});

const loadPersonalizedData = async () => {
  if (!authStore.isAuthenticated) return;
  loading.value = true;
  const [overviewResult, pricingResult] = await Promise.allSettled([
    careerAPI.getOverview({ ...filters }),
    careerAPI.getPricing(),
  ]);
  if (overviewResult.status === "fulfilled" && overviewResult.value?.data) {
    overview.value = overviewResult.value.data;
  }
  if (pricingResult.status === "fulfilled" && pricingResult.value?.data) {
    pricing.value = pricingResult.value.data;
  }
  loading.value = false;
};

const requireLogin = (action) => router.push({
  name: "career-analysis",
  query: { login: "true", redirect: "/career-analysis", action },
});

const stopRunPolling = () => {
  runPollGeneration += 1;
  if (runPollTimer) {
    clearTimeout(runPollTimer);
    runPollTimer = null;
  }
};

const failReportPolling = (runId, message, expectedGeneration) => {
  if (expectedGeneration !== runPollGeneration) return;
  stopRunPolling();
  if (run.value && String(run.value.id) === String(runId)) {
    run.value = { ...run.value, status: "failed", current_node: "failed" };
  }
  errorMessage.value = message;
};

const stopQuestionPolling = ({ keepActive = false, keepRun = false } = {}) => {
  questionPollGeneration += 1;
  if (questionPollTimer) {
    clearTimeout(questionPollTimer);
    questionPollTimer = null;
  }
  if (!keepActive) questionRunActive.value = false;
  if (!keepRun) activeQuestionRun.value = null;
};

const failQuestionPolling = (message, expectedGeneration) => {
  if (expectedGeneration !== questionPollGeneration) return;
  stopQuestionPolling();
  answer.value = "";
  errorMessage.value = message;
};

const refreshAfterReport = async () => {
  if (!mounted) return;
  const refreshGeneration = ++reportRefreshGeneration;
  const expectedLifecycle = lifecycleGeneration;
  const [overviewResult, reportResult] = await Promise.allSettled([
    careerAPI.getOverview({ ...filters }),
    careerAPI.getLatestReport(),
  ]);
  if (
    !mounted
    || expectedLifecycle !== lifecycleGeneration
    || refreshGeneration !== reportRefreshGeneration
  ) return;
  if (overviewResult.status === "fulfilled" && overviewResult.value?.data) {
    overview.value = overviewResult.value.data;
  }
  if (reportResult.status === "fulfilled" && reportResult.value?.data?.content) {
    latestReport.value = reportResult.value.data;
  }
};

const validRunId = (value) => {
  const runId = String(value ?? "").trim();
  return /^\d{1,20}$/.test(runId) ? runId : null;
};

const loadReportForRequestedRun = async (candidateRunId) => {
  const runId = validRunId(candidateRunId);
  if (!authStore.isAuthenticated || !runId) return;
  try {
    // Both V1 calls enforce current-user ownership server-side.  Do not use
    // the latest-report endpoint here: a notification must open its own run.
    const runResponse = await agentAPI.getRun(runId);
    const ownedRun = runResponse.data || {};
    if (String(ownedRun.id) !== runId) return;
    const conversationId = ownedRun.conversationId || ownedRun.conversation_id;
    if (!validRunId(conversationId)) return;
    const detailResponse = await agentAPI.getConversation(String(conversationId));
    const messages = detailResponse.data?.messages || [];
    const inputMessageId = String(ownedRun.inputMessageId || ownedRun.input_message_id || "");
    const input = messages.find((message) => String(message.id) === inputMessageId);
    const messageType = input?.messageType || input?.message_type;
    if (!["career_report_request", "career_question"].includes(messageType)) return;
    const matchingResult = [...messages].reverse().find((message) => {
      const metadata = message.metadata || message.metadata_json || {};
      const resultRunId = metadata.runId || metadata.run_id;
      const resultType = message.messageType || message.message_type;
      return message.role === "assistant"
        && resultType === "analysis_result"
        && String(resultRunId) === runId;
    });
    if (!matchingResult) return;
    const metadata = matchingResult.metadata || matchingResult.metadata_json || {};
    run.value = { ...ownedRun, id: runId };
    latestReport.value = {
      runId,
      content: matchingResult.content,
      report: metadata.result || null,
      createdAt: matchingResult.createdAt || matchingResult.created_at || null,
    };
  } catch {
    // Invalid, deleted, or non-owned run IDs intentionally do not reveal data.
  }
};

const validTaskId = (value) => {
  const taskId = String(value ?? "").trim();
  return /^[A-Za-z0-9_-]{1,128}$/.test(taskId) ? taskId : null;
};

const loadReportForRequestedTask = async (candidateTaskId) => {
  const taskId = validTaskId(candidateTaskId);
  if (!authStore.isAuthenticated || !taskId) return;
  try {
    const task = await aiTaskStore.fetchTaskById(taskId, "career_compass");
    if (!task || !["career_compass", "career_advice"].includes(task.featureKey)) return;
    if (task.status === "failed" || task.status === "cancelled") {
      run.value = { id: taskId, status: task.status, current_node: task.status };
      errorMessage.value = task.error || "该职业分析任务未能完成。";
      return;
    }
    if (task.status !== "completed") return;
    const result = task.result || {};
    const content = typeof result.report === "string"
      ? result.report
      : (typeof result.advice === "string" ? result.advice : "");
    if (!content) return;
    latestReport.value = { taskId, content, report: result.report || null, createdAt: task.createdAt || null };
  } catch {
    // Invalid or no-longer-owned task IDs are intentionally silent.
  }
};

const loadClarification = async ({
  runId,
  conversationId,
  resume,
  isCurrent = () => true,
  kind = "report",
}) => {
  const loadGeneration = ++clarificationLoadGeneration;
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted
    && expectedLifecycle === lifecycleGeneration
    && loadGeneration === clarificationLoadGeneration
    && isCurrent();
  if (!canApply()) return;
  if (!conversationId) {
    errorMessage.value = "分析需要补充信息，但缺少原会话标识。你可以取消任务后重试。";
    clarification.value = {
      runId: String(runId), conversationId: null, question: "", resume, kind,
    };
    return;
  }
  try {
    const response = await agentAPI.getConversation(conversationId);
    if (!canApply()) return;
    const messages = response.data?.messages || [];
    const prompt = [...messages].reverse().find(
      (message) => message.role === "assistant"
        && message.message_type === "clarification_required",
    );
    clarification.value = {
      runId: String(runId),
      conversationId: String(conversationId),
      question: prompt?.content || "请补充更多信息后继续分析。",
      resume,
      kind,
    };
    clarificationAnswer.value = "";
    errorMessage.value = "";
  } catch (error) {
    if (!canApply()) return;
    clarification.value = {
      runId: String(runId),
      conversationId: String(conversationId),
      question: "暂时无法读取需要补充的问题。你可以取消任务后重试。",
      resume,
      kind,
    };
    errorMessage.value = extractApiError(error, "澄清问题加载失败，请稍后重试。").message;
  }
};

const submitClarification = async () => {
  const content = clarificationAnswer.value.trim();
  const current = clarification.value;
  if (!content || !current?.conversationId || clarificationSubmitting.value) return;
  clarificationSubmitting.value = true;
  errorMessage.value = "";
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted && expectedLifecycle === lifecycleGeneration;
  try {
    const key = globalThis.crypto?.randomUUID?.() || `career-clarify-${Date.now()}`;
    const response = await agentAPI.sendMessage(
      current.conversationId,
      {
        content,
        message_type: "clarification_response",
        context: { source: "career_analysis" },
      },
      key,
    );
    const resumed = response.data?.run;
    if (!canApply()) return;
    clarification.value = null;
    clarificationAnswer.value = "";
    run.value = resumed || { id: current.runId, status: "queued" };
    current.resume();
  } catch (error) {
    if (!canApply()) return;
    errorMessage.value = extractApiError(error, "补充信息发送失败，请稍后重试。").message;
  } finally {
    if (canApply()) clarificationSubmitting.value = false;
  }
};

const cancelClarificationRun = async () => {
  const current = clarification.value;
  if (!current || clarificationSubmitting.value) return;
  clarificationSubmitting.value = true;
  errorMessage.value = "";
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted && expectedLifecycle === lifecycleGeneration;
  try {
    const response = await agentAPI.cancelRun(current.runId);
    if (!canApply()) return;
    run.value = response.data;
    clarification.value = null;
    clarificationAnswer.value = "";
    if (current.kind === "question") stopQuestionPolling();
  } catch (error) {
    if (!canApply()) return;
    errorMessage.value = extractApiError(error, "任务取消失败，请稍后重试。").message;
  } finally {
    if (canApply()) clarificationSubmitting.value = false;
  }
};

const cancelActiveQuestion = async () => {
  const current = activeQuestionRun.value;
  if (!current || questionCancelling.value) return;
  questionCancelling.value = true;
  errorMessage.value = "";
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted && expectedLifecycle === lifecycleGeneration;
  stopQuestionPolling({ keepActive: true, keepRun: true });
  try {
    await agentAPI.cancelRun(current.runId);
    if (!canApply() || activeQuestionRun.value?.runId !== current.runId) return;
    stopQuestionPolling();
    answer.value = "本次问题分析已取消，你可以重新提问。";
  } catch (error) {
    if (!canApply() || activeQuestionRun.value?.runId !== current.runId) return;
    errorMessage.value = extractApiError(error, "问题取消失败，已继续等待结果。").message;
    startQuestionStream(current.runId, current.conversationId);
  } finally {
    if (canApply()) questionCancelling.value = false;
  }
};

const reportStream = useAgentRunStream({
  connect: connectAgentEventStream,
  getRun: agentAPI.getRun,
  maxStreamFailures: 0,
  fallbackInitialDelayMs: POLL_INTERVAL_MS,
  pollDelayMs: POLL_INTERVAL_MS,
  onEvent: (event) => {
    if (String(run.value?.id) !== String(event.run_id)) return;
    if (event.event === "run_started") run.value = { ...run.value, status: "running" };
    if (event.event === "tool_started") run.value = { ...run.value, status: "running", current_node: "execute_tools" };
    if (["message_started", "message_delta"].includes(event.event)) {
      run.value = { ...run.value, status: "running", current_node: "compose_answer" };
    }
  },
  onTerminal: async ({ run: terminalRun }) => {
    if (!mounted || String(run.value?.id) !== String(terminalRun?.id)) return;
    run.value = { ...run.value, ...terminalRun };
    if (terminalRun.status === "completed") await refreshAfterReport();
    else if (terminalRun.status === "waiting_user") {
      await loadClarification({
        runId: terminalRun.id,
        conversationId: terminalRun.conversationId,
        kind: "report",
        resume: () => startReportStream(terminalRun.id, terminalRun.conversationId),
      });
    } else if (terminalRun.status === "failed") errorMessage.value = agentFailureMessage(terminalRun.error_code);
    else if (terminalRun.status === "cancelled") errorMessage.value = "分析任务已取消。";
  },
  onFallback: ({ run: fallbackRun }) => {
    startRunPolling(fallbackRun.id, {
      conversationId: fallbackRun.conversationId,
      onComplete: refreshAfterReport,
      onFailed: (next) => { errorMessage.value = agentFailureMessage(next.error_code); },
      fromStream: true,
    });
    return true;
  },
});

const startReportStream = (runId, conversationId) => {
  stopRunPolling();
  run.value = { id: String(runId), conversationId: conversationId ? String(conversationId) : null, status: "queued" };
  reportStream.start({ runId, conversationId, initialStatus: "queued" });
};

const startRunPolling = (runId, { conversationId, onComplete, onFailed, fromStream = false } = {}) => {
  if (!fromStream) reportStream.stop();
  stopRunPolling();
  const generation = runPollGeneration;
  const startedAt = Date.now();
  let attempts = 0;
  let consecutiveErrors = 0;
  run.value = { id: String(runId), status: "queued" };
  const poll = async () => {
    runPollTimer = null;
    if (generation !== runPollGeneration) return;
    if (Date.now() - startedAt >= POLL_DEADLINE_MS || attempts >= MAX_POLL_ATTEMPTS) {
      failReportPolling(runId, POLLING_TIMEOUT_MESSAGE, generation);
      return;
    }
    attempts += 1;
    let next;
    try {
      const response = await agentAPI.getRun(runId);
      next = response.data;
    } catch (pollError) {
      if (generation !== runPollGeneration) return;
      consecutiveErrors += 1;
      if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
        failReportPolling(runId, POLLING_NETWORK_MESSAGE, generation);
        return;
      }
      if (generation === runPollGeneration) {
        runPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      }
      return;
    }
    if (
      generation !== runPollGeneration
      || !run.value
      || String(run.value.id) !== String(runId)
    ) return;
    consecutiveErrors = 0;
    run.value = next;
    if (next.status === "completed") {
      stopRunPolling();
      if (onComplete) await onComplete();
    } else if (next.status === "failed") {
      stopRunPolling();
      if (onFailed) await onFailed(next);
    } else if (["cancelled", "waiting_user"].includes(next.status)) {
      stopRunPolling();
      if (next.status === "cancelled") {
        errorMessage.value = "分析任务已取消。";
      } else {
        await loadClarification({
          runId,
          conversationId,
          kind: "report",
          resume: () => startRunPolling(runId, { conversationId, onComplete, onFailed }),
        });
      }
    } else if (["queued", "running"].includes(next.status)) {
      runPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
    } else {
      failReportPolling(runId, POLLING_STATUS_MESSAGE, generation);
    }
  };
  runPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
};

const generateReport = async () => {
  if (!authStore.isAuthenticated) return requireLogin("generate");
  if (generating.value || runActive.value) return;
  generating.value = true;
  const submissionGeneration = ++reportSubmissionGeneration;
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted
    && expectedLifecycle === lifecycleGeneration
    && submissionGeneration === reportSubmissionGeneration;
  errorMessage.value = "";
  answer.value = "";
  latestReport.value = null;
  try {
    const key = globalThis.crypto?.randomUUID?.() || `career-${Date.now()}`;
    const response = await careerAPI.generateReport({ filters: { ...filters } }, key);
    if (!canApply()) return;
    const runId = response.data?.runId;
    const conversationId = response.data?.conversationId;
    if (!runId) throw new Error("分析任务响应缺少 runId");
    startReportStream(runId, conversationId);
  } catch (error) {
    if (!canApply()) return;
    const apiError = extractApiError(error, "分析任务创建失败，请稍后重试。");
    const active = extractAgentRunReference(apiError.data);
    if (
      apiError.code === "AGENT_ACTIVE_RUN_EXISTS"
      && active?.messageType === "career_report_request"
    ) {
      startReportStream(active.runId, active.conversationId);
    } else {
      run.value = null;
      errorMessage.value = apiError.message;
    }
  } finally {
    if (canApply()) generating.value = false;
  }
};

const questionStream = useAgentRunStream({
  connect: connectAgentEventStream,
  getRun: agentAPI.getRun,
  maxStreamFailures: 0,
  fallbackInitialDelayMs: POLL_INTERVAL_MS,
  pollDelayMs: POLL_INTERVAL_MS,
  onEvent: (event, snapshot) => {
    if (String(activeQuestionRun.value?.runId) !== String(event.run_id)) return;
    if (event.event === "message_delta") answer.value = snapshot.content;
  },
  onTerminal: async ({ run: terminalRun, content, successful }) => {
    if (!mounted || String(activeQuestionRun.value?.runId) !== String(terminalRun?.id)) return;
    if (terminalRun.status === "completed") {
      questionRunActive.value = false;
      if (successful) answer.value = content;
      try {
        const detail = await agentAPI.getConversation(activeQuestionRun.value.conversationId);
        const lastAssistant = [...(detail.data?.messages || [])].reverse().find((item) => item.role === "assistant");
        if (lastAssistant?.content) answer.value = lastAssistant.content;
      } catch {
        if (!answer.value) answer.value = "AI 顾问已完成回答。";
      }
      activeQuestionRun.value = null;
    } else if (terminalRun.status === "waiting_user") {
      await loadClarification({
        runId: terminalRun.id,
        conversationId: terminalRun.conversationId,
        kind: "question",
        resume: () => startQuestionStream(terminalRun.id, terminalRun.conversationId),
      });
    } else if (terminalRun.status === "failed") {
      questionRunActive.value = false;
      activeQuestionRun.value = null;
      answer.value = "本次问题未完成，不会扣除余额。";
      errorMessage.value = agentFailureMessage(terminalRun.error_code);
    } else if (terminalRun.status === "cancelled") {
      questionRunActive.value = false;
      activeQuestionRun.value = null;
      answer.value = "本次问题分析已取消，你可以重新提问。";
    }
  },
  onFallback: ({ run: fallbackRun }) => {
    pollQuestionRun(fallbackRun.id, fallbackRun.conversationId, { fromStream: true });
    return true;
  },
});

const startQuestionStream = (runId, conversationId) => {
  stopQuestionPolling({ keepActive: true, keepRun: true });
  questionRunActive.value = true;
  activeQuestionRun.value = { runId: String(runId), conversationId: String(conversationId) };
  questionStream.start({ runId, conversationId, initialStatus: "queued" });
};

watch(
  () => questionStream.content.value,
  (content) => {
    if (questionRunActive.value && content) answer.value = content;
  },
);

watch(
  () => route.query.runId,
  (runId, previousRunId) => {
    if (mounted && runId !== previousRunId) void loadReportForRequestedRun(runId);
  },
);

watch(
  () => route.query.taskId,
  (taskId, previousTaskId) => {
    if (mounted && taskId !== previousTaskId) void loadReportForRequestedTask(taskId);
  },
);

const pollQuestionRun = (runId, conversationId, { fromStream = false } = {}) => {
  if (!fromStream) questionStream.stop();
  stopQuestionPolling({ keepActive: true });
  questionRunActive.value = true;
  activeQuestionRun.value = {
    runId: String(runId),
    conversationId: String(conversationId),
  };
  const generation = questionPollGeneration;
  const startedAt = Date.now();
  let attempts = 0;
  let consecutiveErrors = 0;
  const poll = async () => {
    questionPollTimer = null;
    if (generation !== questionPollGeneration) return;
    if (Date.now() - startedAt >= POLL_DEADLINE_MS || attempts >= MAX_POLL_ATTEMPTS) {
      failQuestionPolling(POLLING_TIMEOUT_MESSAGE, generation);
      return;
    }
    attempts += 1;
    let next;
    try {
      const response = await agentAPI.getRun(runId);
      next = response.data;
    } catch (pollError) {
      if (generation !== questionPollGeneration) return;
      consecutiveErrors += 1;
      if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
        failQuestionPolling(POLLING_NETWORK_MESSAGE, generation);
        return;
      }
      if (generation === questionPollGeneration) {
        questionPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      }
      return;
    }
    if (generation !== questionPollGeneration) return;
    consecutiveErrors = 0;
    if (next.status === "completed") {
      questionPollTimer = null;
      questionRunActive.value = false;
      activeQuestionRun.value = null;
      try {
        const detail = await agentAPI.getConversation(conversationId);
        if (generation !== questionPollGeneration) return;
        const messages = detail.data?.messages || [];
        const lastAssistant = [...messages].reverse().find((item) => item.role === "assistant");
        answer.value = lastAssistant?.content || "AI 顾问已完成回答，可重新生成职业分析查看完整报告。";
      } catch (detailError) {
        if (generation !== questionPollGeneration) return;
        answer.value = "AI 顾问已完成回答，可重新生成职业分析查看完整报告。";
      } finally {
        if (generation === questionPollGeneration) stopQuestionPolling();
      }
    } else if (["failed", "cancelled", "waiting_user"].includes(next.status)) {
      questionPollTimer = null;
      answer.value = "";
      if (next.status === "waiting_user") {
        await loadClarification({
          runId,
          conversationId,
          kind: "question",
          resume: () => pollQuestionRun(runId, conversationId),
          isCurrent: () => generation === questionPollGeneration,
        });
        if (generation === questionPollGeneration) {
          stopQuestionPolling({ keepActive: true, keepRun: true });
        }
      } else if (next.status === "cancelled") {
        stopQuestionPolling();
        errorMessage.value = "问题分析任务已取消。";
      } else {
        stopQuestionPolling();
        errorMessage.value = agentFailureMessage(next.error_code);
      }
    } else if (["queued", "running"].includes(next.status)) {
      if (generation === questionPollGeneration) {
        questionPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
      }
    } else {
      failQuestionPolling(POLLING_STATUS_MESSAGE, generation);
    }
  };
  questionPollTimer = setTimeout(poll, POLL_INTERVAL_MS);
};

const recoverActiveCareerRuns = async () => {
  if (!authStore.isAuthenticated) return;
  try {
    const response = await agentAPI.listConversations({ page: 1, page_size: 50 });
    const details = await Promise.all((response.data?.items || []).map(async (conversation) => {
      try { return await agentAPI.getConversation(conversation.id); } catch { return null; }
    }));
    for (const result of details) {
      const detail = result?.data;
      const latestRun = detail?.latest_run || detail?.latestRun;
      if (!latestRun || !["queued", "running", "waiting_user"].includes(latestRun.status)) continue;
      const input = (detail.messages || []).find(
        (message) => String(message.id) === String(latestRun.input_message_id || latestRun.inputMessageId),
      );
      const kind = input?.message_type || input?.messageType;
      const conversationId = String(latestRun.conversation_id || latestRun.conversationId || detail.conversation?.id);
      if (kind === "career_report_request") {
        if (latestRun.status === "waiting_user") {
          run.value = { ...latestRun, id: String(latestRun.id), status: "waiting_user" };
          await loadClarification({
            runId: latestRun.id,
            conversationId,
            kind: "report",
            resume: () => startReportStream(latestRun.id, conversationId),
          });
        } else startReportStream(latestRun.id, conversationId);
      }
      if (kind === "career_question") {
        if (latestRun.status === "waiting_user") {
          questionRunActive.value = true;
          activeQuestionRun.value = { runId: String(latestRun.id), conversationId };
          await loadClarification({
            runId: latestRun.id,
            conversationId,
            kind: "question",
            resume: () => startQuestionStream(latestRun.id, conversationId),
          });
        } else startQuestionStream(latestRun.id, conversationId);
      }
    }
  } catch {
    // Active-run recovery is best effort; normal submission remains available.
  }
};

const sendQuestion = async () => {
  const content = question.value.trim();
  if (!content || ordinaryQuestionDisabled.value) return;
  if (!authStore.isAuthenticated) return requireLogin("career-question");
  asking.value = true;
  const submissionGeneration = ++questionSubmissionGeneration;
  const expectedLifecycle = lifecycleGeneration;
  const canApply = () => mounted
    && expectedLifecycle === lifecycleGeneration
    && submissionGeneration === questionSubmissionGeneration;
  errorMessage.value = "";
  try {
    const key = globalThis.crypto?.randomUUID?.() || `career-question-${Date.now()}`;
    const response = await careerAPI.askQuestion(
      { question: content, filters: { ...filters } },
      key,
    );
    if (!canApply()) return;
    const runId = response.data?.runId;
    const conversationId = response.data?.conversationId;
    if (!runId || !conversationId) {
      answer.value = response.data?.answer || "问题已提交，AI 顾问正在整理建议。";
      question.value = "";
      return;
    }
    question.value = "";
    answer.value = "AI 顾问正在整理建议…";
    startQuestionStream(runId, conversationId);
  } catch (error) {
    if (!canApply()) return;
    questionRunActive.value = false;
    answer.value = "";
    const apiError = extractApiError(error, "问题发送失败，请稍后重试。");
    const active = extractAgentRunReference(apiError.data);
    if (
      apiError.code === "AGENT_ACTIVE_RUN_EXISTS"
      && active?.messageType === "career_question"
    ) {
      answer.value = "AI 顾问正在整理建议…";
      startQuestionStream(active.runId, active.conversationId);
    } else {
      errorMessage.value = apiError.message;
    }
  } finally {
    if (canApply()) asking.value = false;
  }
};

onMounted(() => {
  mounted = true;
  lifecycleGeneration += 1;
  loadPersonalizedData();
  void loadReportForRequestedRun(route.query.runId);
  void loadReportForRequestedTask(route.query.taskId);
  void recoverActiveCareerRuns();
});
onBeforeUnmount(() => {
  mounted = false;
  lifecycleGeneration += 1;
  clarificationLoadGeneration += 1;
  reportRefreshGeneration += 1;
  reportSubmissionGeneration += 1;
  questionSubmissionGeneration += 1;
  stopRunPolling();
  stopQuestionPolling();
  reportStream.stop();
  questionStream.stop();
});
</script>

<template>
  <main class="career-page">
    <header class="career-hero">
      <div><p class="eyebrow"><i /> PERSONAL CAREER REPORT</p><h1 v-if="authStore.isAuthenticated">你好，{{ overview.profile.name }}。<br><span>这是你的职业机会地图。</span></h1><h1 v-else>把你的专业和能力，<br><span>放进真实市场里分析。</span></h1><p>{{ authStore.isAuthenticated ? "基于你的学校、专业、课程、技能与当前市场数据生成。" : "登录并完善资料后，我们会回答适合方向、城市选择、能力差距和下一步行动。" }}</p></div>
      <div class="hero-actions"><span v-if="authStore.isAuthenticated">市场证据：{{ overview.evidence.sampleSize }} · {{ overview.evidence.updatedAt }}</span><button data-test="generate-analysis" :disabled="generating || runActive" @click="generateReport">{{ generateLabel }}</button></div>
    </header>

    <section v-if="!authStore.isAuthenticated" class="guest-intro">
      <div class="intro-copy"><p>PERSONALIZED, EVIDENCE-BASED</p><h2>职业分析如何帮助你</h2><span>不是简单生成一段建议，而是把你的真实资料与岗位市场逐项对齐。</span></div>
      <div class="intro-grid"><article><b>01</b><h3>发现适合方向</h3><p>给出 Top 3 方向、匹配理由和市场证据。</p></article><article><b>02</b><h3>选择目标城市</h3><p>比较岗位量、薪资、增长率和竞争程度。</p></article><article><b>03</b><h3>识别技能差距</h3><p>对照目标岗位要求，定位优先补全能力。</p></article><article><b>04</b><h3>形成行动计划</h3><p>把结论转化为 30/60/90 天可执行任务。</p></article></div>
      <button data-test="guest-start" @click="generateReport">登录并完善个人资料 →</button>
    </section>

    <template v-else>
      <section class="profile-strip">
        <div class="completion"><strong>{{ overview.profile.completion }}%</strong><span>画像完整度</span></div>
        <div class="profile-tags"><span>{{ overview.profile.school }}</span><span>{{ overview.profile.major }}</span><span>{{ overview.profile.graduation }}</span></div>
        <p>本次分析综合个人资料、简历确认字段与当前市场数据。</p>
        <button @click="router.push('/my/profile')">完善资料 →</button>
      </section>

      <p v-if="syntheticDimensionCount" class="data-notice" data-test="career-source">
        <span>i</span> 分析部分使用测试数据（{{ syntheticDimensionCount }} 个维度），真实用户资料未被替换；完成 AI 分析后将自动更新。
      </p>

      <form class="analysis-filter" @submit.prevent="loadPersonalizedData"><label><span>目标城市</span><select v-model="filters.city"><option>杭州</option><option>上海</option><option>深圳</option><option>北京</option></select></label><label><span>目标行业</span><select v-model="filters.industry"><option>互联网 / AI</option><option>智能制造</option><option>新能源</option></select></label><label><span>职业方向</span><select v-model="filters.direction"><option>AI 产品经理</option><option>数据产品经理</option><option>商业分析师</option></select></label><button :disabled="loading">{{ loading ? "更新中…" : "更新结果" }}</button></form>

      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

      <div v-if="run" class="run-banner" :data-status="run.status" data-test="run-status"><span v-if="runActive" class="spinner" />{{ runStage }}</div>

      <section v-if="clarification" class="clarification-panel" data-test="clarification-panel">
        <div>
          <small>AI 需要你补充信息</small>
          <strong>{{ clarification.question }}</strong>
        </div>
        <form data-test="clarification-form" @submit.prevent="submitClarification">
          <textarea
            v-model="clarificationAnswer"
            data-test="clarification-input"
            placeholder="输入补充信息…"
          />
          <div>
            <button
              type="button"
              class="cancel"
              data-test="clarification-cancel"
              :disabled="clarificationSubmitting"
              @click="cancelClarificationRun"
            >取消本次任务</button>
            <button
              type="submit"
              :disabled="clarificationSubmitting || !clarificationAnswer.trim()"
            >{{ clarificationSubmitting ? "提交中…" : "补充并继续" }}</button>
          </div>
        </form>
      </section>

      <div class="career-layout">
        <div class="career-main">
          <section><div class="section-heading"><div><p>TOP DIRECTIONS</p><h2>推荐职业方向</h2></div><span>匹配度综合资料、技能和市场机会</span></div><div class="direction-grid"><article v-for="(item, index) in overview.directions" :key="item.title" :class="{ featured: index === 0 }"><header><span>{{ index === 0 ? "首选方向" : `方向 ${index + 1}` }}</span><strong>{{ item.match }}<small>%</small></strong></header><h3>{{ item.title }}</h3><p>{{ item.reason }}</p><div><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div></article></div></section>

          <section class="analysis-grid"><article class="analysis-card city-card"><div class="section-heading"><div><p>CITY COMPARISON</p><h2>城市机会对比</h2></div></div><div class="city-table"><div class="table-head"><span>城市</span><span>岗位量</span><span>月薪中位数</span><span>增长</span><span>竞争度</span></div><div v-for="item in overview.cities" :key="item.city"><strong>{{ item.city }}</strong><span>{{ item.jobs }}</span><span>{{ item.salary }}</span><em>{{ item.growth }}</em><span>{{ item.competition }}</span></div></div></article>
            <article class="analysis-card skill-card"><div class="section-heading"><div><p>SKILL GAP</p><h2>能力与目标差距</h2></div></div><div class="skill-list"><div v-for="item in overview.skills" :key="item.name"><span>{{ item.name }}</span><i><b :style="{ width: `${item.current}%` }" /><em :style="{ left: `${item.target}%` }" /></i><strong>{{ item.current }} / {{ item.target }}</strong></div></div></article></section>

          <section class="analysis-card plan-card"><div class="section-heading"><div><p>ACTION PLAN</p><h2>30 / 60 / 90 天行动计划</h2></div></div><div class="plan-grid"><article v-for="(item, index) in overview.plan" :key="item.period"><span>{{ index + 1 }}</span><div><small>{{ item.period }}</small><h3>{{ item.title }}</h3><ul><li v-for="action in item.items" :key="action">{{ action }}</li></ul></div></article></div></section>

          <section v-if="latestReport?.content" class="analysis-card report-card" data-test="latest-report"><div class="section-heading"><div><p>FULL REPORT</p><h2>完整职业分析报告</h2></div><span>{{ latestReport.createdAt ? `更新于 ${new Date(latestReport.createdAt).toLocaleString("zh-CN")}` : "" }}</span></div><pre class="report-content">{{ latestReport.content }}</pre></section>
        </div>

        <aside class="career-ai-card"><header><span>AI</span><div><small>职业顾问</small><strong>基于你的报告提问</strong></div><i /></header><div class="context"><span>当前上下文</span><p>{{ filters.direction }} · {{ filters.city }}<br>{{ overview.evidence.sampleSize }}市场样本</p></div><div class="assistant-message">我可以解释推荐理由、比较城市选择，或帮你细化行动计划。</div><p v-if="answer" class="assistant-answer">{{ answer }}</p><button v-if="questionRunActive && activeQuestionRun && !clarification" class="question-cancel" data-test="question-cancel" :disabled="questionCancelling" @click="cancelActiveQuestion">{{ questionCancelling ? "取消中…" : "取消当前问题" }}</button><form @submit.prevent="sendQuestion"><textarea v-model="question" :disabled="ordinaryQuestionDisabled" placeholder="输入你的职业问题…" /><div><span data-test="career-ai-price">{{ questionPrice ? `预计 ¥${questionPrice}/次` : "价格以发送前确认为准" }}</span><button :disabled="ordinaryQuestionDisabled">{{ asking || questionRunActive ? "…" : "↑" }}</button></div></form></aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.career-page { width: min(1420px,calc(100% - 32px)); margin: 0 auto; padding: 42px 0 88px; color: #17253d; }.career-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 36px; padding: 20px 6px 34px; }.eyebrow,.section-heading p,.intro-copy>p { margin: 0 0 10px; color: #55708f; font-size: 10px; font-weight: 800; letter-spacing: .16em; }.eyebrow i { display: inline-block; width: 6px; height: 6px; margin: 0 7px 1px 0; background: #20aa91; border-radius: 50%; }.career-hero h1 { margin: 0; color: #13233c; font-size: clamp(36px,4vw,52px); line-height: 1.1; letter-spacing: -.05em; }.career-hero h1 span { color: #1767dc; }.career-hero>div>p:last-child { color: #5d7088; font-size: 14px; }.hero-actions { display: flex; align-items: center; gap: 12px; }.hero-actions>span { color: #687a91; font-size: 11px; }.hero-actions button,.guest-intro>button,.analysis-filter button { padding: 11px 16px; color: #fff; background: #1767dc; border: 0; border-radius: 9px; font-size: 13px; font-weight: 700; cursor: pointer; }.hero-actions button:disabled { opacity: .6; }
.guest-intro { padding: 34px; background: #fff; border: 1px solid #e0e7f0; border-radius: 18px; box-shadow: 0 18px 50px rgba(36,67,107,.06); }.intro-copy h2 { margin: 0; font-size: 28px; }.intro-copy>span { display: block; margin-top: 9px; color: #60728a; font-size: 14px; }.intro-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin: 28px 0; }.intro-grid article { min-height: 175px; padding: 20px; background: #f7f9fc; border: 1px solid #e6ebf2; border-radius: 13px; }.intro-grid b { color: #1767dc; font-size: 12px; }.intro-grid h3 { margin: 25px 0 9px; font-size: 17px; }.intro-grid p { color: #63758c; font-size: 12px; line-height: 1.7; }.guest-intro>button { display: block; margin: 0 auto; padding-inline: 24px; }
.profile-strip,.analysis-filter,.analysis-card,.direction-grid article,.career-ai-card { background: #fff; border: 1px solid #e0e7f0; border-radius: 14px; box-shadow: 0 8px 25px rgba(42,67,101,.04); }.profile-strip { display: grid; grid-template-columns: auto 1fr 1.2fr auto; align-items: center; gap: 20px; padding: 16px 18px; }.completion { display: flex; align-items: baseline; gap: 8px; }.completion strong { color: #1767dc; font-size: 24px; }.completion span,.profile-strip p { color: #5d7088; font-size: 11px; }.profile-tags { display: flex; flex-wrap: wrap; gap: 6px; }.profile-tags span { padding: 5px 8px; color: #445e7e; background: #f0f5fb; border-radius: 5px; font-size: 10px; }.profile-strip button { color: #1767dc; background: transparent; border: 0; font-size: 11px; cursor: pointer; }.analysis-filter { display: grid; grid-template-columns: repeat(3,1fr) auto; align-items: end; gap: 12px; margin-top: 12px; padding: 14px 16px; }.analysis-filter label { display: grid; gap: 6px; }.analysis-filter label span { color: #5d7088; font-size: 11px; }.analysis-filter select { padding: 9px 10px; color: #344760; background: #f8fafc; border: 1px solid #dfe6ef; border-radius: 7px; font-size: 12px; }.error-message { padding: 10px 12px; color: #b64e58; background: #fff0f1; border-radius: 8px; font-size: 12px; }
.data-notice { display:flex; align-items:center; gap:8px; margin:12px 2px 0; color:#7a6539; font-size:13px; }.data-notice span { display:grid; width:18px; height:18px; place-items:center; color:#9b701c; background:#fff3d5; border-radius:50%; font-size:11px; font-weight:800; }
.run-banner { display:flex; align-items:center; gap:8px; margin:12px 2px 0; padding:10px 12px; color:#174f8a; background:#eaf2ff; border-radius:8px; font-size:13px; }.run-banner[data-status="failed"]{color:#b64e58;background:#fff0f1}.run-banner[data-status="completed"]{color:#117a63;background:#e7f7f2}.run-banner .spinner{width:14px;height:14px;border:2px solid #bcd6f7;border-top-color:#1767dc;border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.report-card{margin-top:13px}.report-content{margin:0;padding:16px;color:#40566f;background:#f7f9fc;border-radius:10px;font-size:13px;line-height:1.8;white-space:pre-wrap;word-break:break-word}
.clarification-panel { display:grid; grid-template-columns:minmax(220px,.8fr) minmax(320px,1.2fr); gap:18px; margin:12px 2px 0; padding:18px; background:#fffaf0; border:1px solid #f0dcae; border-radius:12px; }.clarification-panel small,.clarification-panel strong { display:block; }.clarification-panel small { margin-bottom:6px; color:#97701e; font-size:12px; font-weight:700; }.clarification-panel strong { color:#523f1e; font-size:15px; line-height:1.6; }.clarification-panel form { display:grid; gap:8px; }.clarification-panel textarea { min-height:72px; padding:10px 12px; resize:vertical; color:#344760; background:#fff; border:1px solid #dec996; border-radius:8px; font:inherit; font-size:14px; }.clarification-panel form>div { display:flex; justify-content:flex-end; gap:8px; }.clarification-panel button { padding:8px 13px; color:#fff; background:#1767dc; border:0; border-radius:8px; font-weight:700; cursor:pointer; }.clarification-panel button.cancel { color:#6b5731; background:transparent; border:1px solid #d7bd80; }.clarification-panel button:disabled { opacity:.55; cursor:not-allowed; }
.career-layout { display: grid; grid-template-columns: minmax(0,1fr) 315px; align-items: start; gap: 17px; margin-top: 30px; }.career-main { min-width: 0; }.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 15px; margin-bottom: 14px; }.section-heading p { margin-bottom: 5px; }.section-heading h2 { margin: 0; color: #1e314b; font-size: 19px; }.section-heading>span { color: #65778e; font-size: 11px; }.direction-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }.direction-grid article { min-height: 260px; padding: 18px; }.direction-grid article.featured { border-color: #80adf0; box-shadow: 0 12px 28px rgba(29,105,215,.1); }.direction-grid header { display: flex; justify-content: space-between; }.direction-grid header>span { padding: 4px 7px; color: #1767dc; background: #e9f2ff; border-radius: 5px; font-size: 10px; }.direction-grid header strong { color: #1767dc; font-size: 25px; }.direction-grid header small { font-size: 10px; }.direction-grid h3 { margin: 32px 0 9px; font-size: 18px; }.direction-grid>article>p { min-height: 62px; color: #5f7188; font-size: 12px; line-height: 1.7; }.direction-grid article>div { display: flex; flex-wrap: wrap; gap: 6px; }.direction-grid article>div span { padding: 5px 7px; color: #445e7e; background: #f0f5fb; border-radius: 5px; font-size: 10px; }.analysis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; margin-top: 26px; }.analysis-card { padding: 19px; }.city-table { display: grid; }.city-table>div { display: grid; min-height: 45px; grid-template-columns: repeat(5,1fr); align-items: center; border-bottom: 1px solid #edf1f5; color: #596d85; font-size: 11px; }.city-table .table-head { min-height: 32px; color: #687a91; background: #f7f9fb; border: 0; }.city-table em { color: #159277; font-style: normal; }.skill-list { display: grid; gap: 15px; margin-top: 20px; }.skill-list>div { display: grid; grid-template-columns: 80px 1fr 55px; align-items: center; gap: 10px; color: #52677f; font-size: 11px; }.skill-list i { position: relative; height: 7px; background: #e9eef4; border-radius: 7px; }.skill-list i b { display: block; height: 100%; background: #1767dc; border-radius: inherit; }.skill-list i em { position: absolute; top: -3px; width: 2px; height: 13px; background: #18a88c; }.plan-card { margin-top: 13px; }.plan-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 25px; margin-top: 22px; }.plan-grid article { display: flex; gap: 12px; }.plan-grid article>span { display: grid; width: 29px; height: 29px; flex: 0 0 auto; place-items: center; color: #1767dc; background: #eaf2ff; border-radius: 50%; font-size: 11px; font-weight: 800; }.plan-grid small { color: #61748c; font-size: 10px; }.plan-grid h3 { margin: 5px 0 8px; font-size: 14px; }.plan-grid ul { margin: 0; padding-left: 16px; color: #66788e; font-size: 11px; line-height: 1.8; }
.career-ai-card { position: sticky; top: 92px; min-height: 575px; overflow: hidden; }.career-ai-card>header { display: flex; align-items: center; gap: 10px; padding: 17px; color: #fff; background: linear-gradient(135deg,#173c70,#176bff); }.career-ai-card>header>span { display: grid; width: 36px; height: 36px; place-items: center; background: rgba(255,255,255,.14); border-radius: 10px; font-size: 10px; font-weight: 800; }.career-ai-card header small,.career-ai-card header strong { display: block; }.career-ai-card header small { color: #d2e2f8; font-size: 9px; }.career-ai-card header strong { margin-top: 3px; font-size: 12px; }.career-ai-card header i { width: 7px; height: 7px; margin-left: auto; background: #41d4a5; border-radius: 50%; }.context { margin: 13px; padding: 11px; background: #f1f5fa; border-radius: 8px; }.context span { color: #62758d; font-size: 10px; }.context p { margin: 4px 0 0; color: #425b76; font-size: 11px; line-height: 1.6; }.assistant-message,.assistant-answer { margin: 12px; padding: 12px; color: #405b77; background: #edf4fc; border-radius: 5px 11px 11px; font-size: 12px; line-height: 1.7; }.assistant-answer { background: #e8f7f3; }.career-ai-card form { position: absolute; right: 13px; bottom: 13px; left: 13px; padding: 10px; border: 1px solid #dbe4ee; border-radius: 9px; }.career-ai-card textarea { width: 100%; height: 60px; resize: none; border: 0; outline: 0; font-size: 12px; }.career-ai-card form>div { display: flex; align-items: center; justify-content: space-between; }.career-ai-card form span { color: #687a90; font-size: 10px; }.career-ai-card form button { display: grid; width: 29px; height: 29px; place-items: center; color: #fff; background: #1767dc; border: 0; border-radius: 7px; }
.question-cancel { display:block; margin:8px 13px 92px auto; padding:7px 10px; color:#8a4b55; background:#fff; border:1px solid #e7c8cd; border-radius:7px; font-size:12px; cursor:pointer; }.question-cancel:disabled { opacity:.55; cursor:not-allowed; }
@media(max-width:1080px){.career-layout{grid-template-columns:1fr}.career-ai-card{position:static;min-height:400px}.career-ai-card form{position:static;margin:13px}.direction-grid{grid-template-columns:1fr 1fr}.direction-grid article:last-child{grid-column:1/-1}.profile-strip{grid-template-columns:auto 1fr auto}.profile-strip>p{grid-column:1/-1}}
@media(max-width:760px){.career-page{width:calc(100% - 24px);padding:26px 0 85px}.career-hero{align-items:flex-start;flex-direction:column}.career-hero h1{font-size:34px}.hero-actions{align-items:flex-start;flex-wrap:wrap}.intro-grid,.direction-grid,.analysis-grid,.plan-grid,.clarification-panel{grid-template-columns:1fr}.direction-grid article:last-child{grid-column:auto}.profile-strip{grid-template-columns:1fr auto}.profile-tags,.profile-strip>p{grid-column:1/-1}.analysis-filter{grid-template-columns:1fr}.city-card{overflow-x:auto}.city-table{min-width:600px}}

/* Readability baseline for muted values and evidence inside cards. */
.eyebrow,.section-heading p,.intro-copy>p { font-size: 12px; }.hero-actions>span { color: #52657d; font-size: 13px; }.intro-grid b,.intro-grid p { font-size: 14px; }.completion span,.profile-strip p { color: #4f637b; font-size: 13px; }.profile-tags span,.profile-strip button { font-size: 12px; }.analysis-filter label span { color: #4f637b; font-size: 13px; }.analysis-filter select { font-size: 14px; }.section-heading>span { color: #52657d; font-size: 13px; }.direction-grid header>span,.direction-grid article>div span { font-size: 12px; }.direction-grid header small { font-size: 12px; }.direction-grid>article>p { color: #4e627a; font-size: 14px; }.city-table>div { color: #40566f; font-size: 13px; }.city-table .table-head { color: #52657d; }.skill-list>div { color: #40566f; font-size: 13px; }.plan-grid small { color: #52657d; font-size: 12px; }.plan-grid ul { color: #52657d; font-size: 13px; }.career-ai-card header small { font-size: 11px; }.career-ai-card header strong { font-size: 14px; }.context span,.context p { font-size: 12px; }.assistant-message,.assistant-answer,.career-ai-card textarea { font-size: 14px; }.career-ai-card form span { color: #52657d; font-size: 12px; }
</style>

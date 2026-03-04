/**
 * AI 任务全局状态管理 (Pinia Store)
 *
 * 核心职责：
 * 1. 跨页面保持 AI 任务状态和结果（页面切换不丢失）
 * 2. 监听 WS 消息自动更新任务状态
 * 3. 提供通知列表数据源
 */
import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { aiAPI } from "@/api/ai";

export const useAiTaskStore = defineStore("aiTask", () => {
  // ─── State ────────────────────────────────────────
  // 所有已知任务 { [taskId]: { taskId, featureKey, status, result, error, createdAt, ... } }
  const tasks = ref({});

  // 通知面板是否展开
  const panelOpen = ref(false);

  // ─── Getters ──────────────────────────────────────
  const taskList = computed(() =>
    Object.values(tasks.value).sort(
      (a, b) => new Date(b.createdAt) - new Date(a.createdAt),
    ),
  );

  const pendingCount = computed(
    () =>
      Object.values(tasks.value).filter(
        (t) => t.status === "pending" || t.status === "processing",
      ).length,
  );

  const hasUnread = computed(() =>
    Object.values(tasks.value).some(
      (t) => !t.read && t.status !== "pending" && t.status !== "processing",
    ),
  );

  // ─── Actions ──────────────────────────────────────

  /** 提交新任务后调用 */
  function addTask(taskId, featureKey, extraData = {}) {
    tasks.value[taskId] = {
      taskId,
      featureKey,
      status: "pending",
      result: null,
      error: null,
      read: false,
      createdAt: new Date().toISOString(),
      ...extraData,
    };
  }

  /** WS 收到 ai_task_completed 时调用 */
  function markCompleted(taskId, result, extra = {}) {
    if (tasks.value[taskId]) {
      tasks.value[taskId].status = "completed";
      tasks.value[taskId].result = result;
      tasks.value[taskId].read = false;
      Object.assign(tasks.value[taskId], extra);
    } else {
      // WS 先于 addTask 到达（罕见）
      tasks.value[taskId] = {
        taskId,
        featureKey: extra.featureKey || "unknown",
        status: "completed",
        result,
        error: null,
        read: false,
        createdAt: new Date().toISOString(),
        ...extra,
      };
    }
  }

  /** WS 收到 ai_task_failed 时调用 */
  function markFailed(taskId, error, extra = {}) {
    if (tasks.value[taskId]) {
      tasks.value[taskId].status = "failed";
      tasks.value[taskId].error = error;
      tasks.value[taskId].read = false;
      Object.assign(tasks.value[taskId], extra);
    } else {
      tasks.value[taskId] = {
        taskId,
        featureKey: extra.featureKey || "unknown",
        status: "failed",
        result: null,
        error,
        read: false,
        createdAt: new Date().toISOString(),
        ...extra,
      };
    }
  }

  /** 标记通知已读 */
  function markRead(taskId) {
    if (tasks.value[taskId]) {
      tasks.value[taskId].read = true;
    }
  }

  function markAllRead() {
    Object.values(tasks.value).forEach((t) => (t.read = true));
  }

  /** 清除已完成/失败的旧任务（保留最近 20 条） */
  function pruneOld() {
    const sorted = Object.values(tasks.value).sort(
      (a, b) => new Date(b.createdAt) - new Date(a.createdAt),
    );
    if (sorted.length > 20) {
      const toRemove = sorted.slice(20);
      toRemove.forEach((t) => delete tasks.value[t.taskId]);
    }
  }

  /** 获取特定功能的最新已完成结果 */
  function getLatestResult(featureKey) {
    const matching = Object.values(tasks.value)
      .filter((t) => t.featureKey === featureKey && t.status === "completed")
      .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    return matching.length > 0 ? matching[0] : null;
  }

  /** 获取特定任务 */
  function getTask(taskId) {
    return tasks.value[taskId] || null;
  }

  /** 轮询任务结果并更新 store（替代 pollTaskResult 直接在组件中调用） */
  async function pollAndUpdate(
    taskId,
    { interval = 2000, timeout = 120000 } = {},
  ) {
    const deadline = Date.now() + timeout;

    while (Date.now() < deadline) {
      try {
        const res = await aiAPI.getTaskResult(taskId);
        const data = res.data;

        if (data.status === "completed") {
          markCompleted(taskId, data.result, {
            executionTime: data.result?.execution_time,
          });
          return data.result;
        }

        if (data.status === "failed") {
          markFailed(taskId, data.error);
          throw new Error(data.error || "AI 任务执行失败");
        }

        // Update intermediate status
        if (tasks.value[taskId]) {
          tasks.value[taskId].status = data.status;
        }
      } catch (e) {
        if (e.message && !e.message.includes("任务执行失败")) {
          console.error("Poll error:", e);
        }
        throw e;
      }

      await new Promise((resolve) => setTimeout(resolve, interval));
    }

    throw new Error("AI 任务超时，请稍后重试");
  }

  /** 功能名称映射 */
  function featureLabel(featureKey) {
    return (
      {
        career_advice: "AI 职业建议",
        career_compass: "职业罗盘分析",
        resume_parse: "简历智能解析",
      }[featureKey] || "AI 任务"
    );
  }

  function togglePanel() {
    panelOpen.value = !panelOpen.value;
  }

  return {
    tasks,
    panelOpen,
    taskList,
    pendingCount,
    hasUnread,
    addTask,
    markCompleted,
    markFailed,
    markRead,
    markAllRead,
    pruneOld,
    getLatestResult,
    getTask,
    pollAndUpdate,
    featureLabel,
    togglePanel,
  };
});

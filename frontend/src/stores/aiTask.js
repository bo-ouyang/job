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

export const useAiTaskStore = defineStore(
  "aiTask",
  () => {
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

    const normalizeResultData = (resultObj) => {
      if (!resultObj || typeof resultObj !== "object") return resultObj;

      const raw = resultObj.result_data;
      let parsed = null;
      if (typeof raw === "string") {
        const trimmed = raw.trim();
        if (trimmed.startsWith("{") && trimmed.endsWith("}")) {
          try {
            parsed = JSON.parse(trimmed);
          } catch (e) {
            parsed = null;
          }
        }
      } else if (raw && typeof raw === "object") {
        parsed = raw;
      }

      let normalized = resultObj;
      if (parsed && typeof parsed === "object") {
        normalized = { ...resultObj, ...parsed };
      }
      if (
        normalized.analysis_input &&
        typeof normalized.analysis_input === "object"
      ) {
        normalized = {
          ...normalized.analysis_input,
          ...normalized,
          analysis_input: normalized.analysis_input,
        };
      }
      return normalized;
    };

    const hasUsableContent = (task) => {
      if (!task || task.status !== "completed" || !task.result) return false;
      const result = task.result;
      return Boolean(
        result.report ||
          result.advice ||
          result.es_stats ||
          result.analysis_result ||
          result.analysis_input?.es_stats ||
          result.analysis_input?.analysis_result ||
          result.analysis_input?.skill_cloud_data ||
          result.skill_cloud_data ||
          result.skillCloudData ||
          result.result_data,
      );
    };

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
        extraData: extraData, // 保存额外的上下文（如查询参数、图表数据等）
      };
    }

    /** 标记完成并保存结果 */
    function markCompleted(taskId, resultObj, additionalMeta = {}) {
      if (tasks.value[taskId]) {
        tasks.value[taskId].status = "completed";
        // 如果当时新建任务时存了 extraData，我们将它合并进最终的 result 对象中
        // 这样前端可以直接读取 result.es_stats 等数据
        let finalResult = { ...resultObj };
        if (tasks.value[taskId].extraData) {
          finalResult = { ...tasks.value[taskId].extraData, ...finalResult };
        }
        tasks.value[taskId].result = finalResult;
        tasks.value[taskId].executionTime = additionalMeta.executionTime;
        tasks.value[taskId].read = false; // Mark as unread when completed
      } else {
        // WS 先于 addTask 到达（罕见）
        tasks.value[taskId] = {
          taskId,
          featureKey: additionalMeta.featureKey || "unknown",
          status: "completed",
          result: resultObj,
          error: null,
          read: false,
          createdAt: new Date().toISOString(),
          ...additionalMeta,
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
    function getLatestResult(featureKey, { requireUsable = true } = {}) {
      const matching = Object.values(tasks.value)
        .filter((t) => t.featureKey === featureKey && t.status === "completed")
        .sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
      if (!requireUsable) {
        return matching.length > 0 ? matching[0] : null;
      }
      const usable = matching.find((item) => hasUsableContent(item));
      return usable || null;
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
      let lastError = null;

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
          const msg = String(e?.message || "");
          const isBusinessFailure = msg.includes("任务执行失败");
          if (isBusinessFailure) {
            throw e;
          }
          lastError = e;
          console.error("Poll transient error, will retry:", e);
        }

        await new Promise((resolve) => setTimeout(resolve, interval));
      }

      if (lastError) {
        throw new Error(
          `AI 任务轮询超时（最后错误: ${lastError.message || "unknown"}）`,
        );
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

    /** Reset store state (used by logout / token-expire handlers) */
    function $reset() {
      tasks.value = {};
      panelOpen.value = false;
      try {
        localStorage.removeItem("aiTask");
      } catch (e) {
        // ignore storage errors
      }
    }

    /** 获取历史任务（页面初始加载用） */
    async function fetchHistory() {
      try {
        const res = await aiAPI.getTaskHistory({ page_size: 50 });
        const items = Array.isArray(res?.data?.items) ? res.data.items : [];
        const nextTasks = {};

        items.forEach((item) => {
          const existing = tasks.value[item.celery_task_id];
          const result =
            item.status === "completed"
              ? {
                  result_data: item.result_data,
                  request_params: item.request_params,
                  analysis_input: item.analysis_input,
                  execution_time: item.execution_time,
                }
              : null;
          const normalizedResult = result ? normalizeResultData(result) : result;
          const mergedResult =
            existing?.result && normalizedResult
              ? { ...existing.result, ...normalizedResult }
              : normalizedResult;

          nextTasks[item.celery_task_id] = {
            taskId: item.celery_task_id,
            featureKey: item.feature_key || existing?.featureKey || "unknown",
            status: item.status || existing?.status || "pending",
            result: mergedResult,
            error: item.error_message || null,
            read: existing?.read ?? true, // 历史记录默认已读
            createdAt: item.created_at || existing?.createdAt || new Date().toISOString(),
            executionTime: item.execution_time || existing?.executionTime,
            extraData: existing?.extraData,
          };
        });

        // Keep only current in-flight local tasks that have not been persisted yet.
        Object.values(tasks.value).forEach((t) => {
          if (
            (t.status === "pending" || t.status === "processing") &&
            !nextTasks[t.taskId]
          ) {
            nextTasks[t.taskId] = t;
          }
        });

        // Server snapshot is the source of truth for historical tasks.
        tasks.value = nextTasks;
      } catch (e) {
        console.error("Failed to fetch AI task history", e);
      }
    }

    /** 按 taskId 拉取单个任务结果并写入 store */
    async function fetchTaskById(taskId, featureKeyHint = null) {
      if (!taskId) return null;
      try {
        const res = await aiAPI.getTaskResult(taskId);
        const data = res.data || {};
        const existing = tasks.value[taskId] || {};
        const featureKey =
          data.result?.feature_key || featureKeyHint || existing.featureKey || "unknown";

        if (data.status === "completed") {
          const resultObj = normalizeResultData(data.result || {});
          let finalResult = resultObj;
          if (existing?.result) {
            if (
              typeof existing.result === "object" &&
              existing.result !== null &&
              typeof resultObj === "object" &&
              resultObj !== null
            ) {
              finalResult = { ...existing.result, ...resultObj };
            } else if (!resultObj) {
              finalResult = existing.result;
            }
          }
          tasks.value[taskId] = {
            taskId,
            featureKey,
            status: "completed",
            result: finalResult,
            error: null,
            read: existing.read ?? true,
            createdAt: resultObj.created_at || existing.createdAt || new Date().toISOString(),
            executionTime: resultObj.execution_time || existing.executionTime,
            extraData: existing.extraData,
          };
        } else if (data.status === "failed") {
          tasks.value[taskId] = {
            taskId,
            featureKey,
            status: "failed",
            result: null,
            error: data.error || existing.error,
            read: existing.read ?? true,
            createdAt: existing.createdAt || new Date().toISOString(),
            executionTime: existing.executionTime,
            extraData: existing.extraData,
          };
        } else if (data.status) {
          tasks.value[taskId] = {
            taskId,
            featureKey,
            status: data.status,
            result: existing.result || null,
            error: existing.error || null,
            read: existing.read ?? true,
            createdAt: existing.createdAt || new Date().toISOString(),
            executionTime: existing.executionTime,
            extraData: existing.extraData,
          };
        }
        return tasks.value[taskId] || null;
      } catch (e) {
        console.error("Failed to fetch AI task by id", e);
        return null;
      }
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
      $reset,
      fetchHistory,
      fetchTaskById,
    };
  },
  { persist: true },
);

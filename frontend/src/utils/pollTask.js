/**
 * Shared polling utility for async Celery task results.
 *
 * Usage:
 *   const result = await pollTaskResult(api, '/analysis/ai/task', taskId);
 */
import api from "@/utils/request";

/**
 * Poll a Celery task endpoint until it reaches a terminal state.
 *
 * @param {string} baseUrl - Polling endpoint path prefix, e.g. '/analysis/ai/task'
 * @param {string} taskId  - The Celery task ID
 * @param {Object} opts
 * @param {number} opts.interval  - Polling interval in ms (default 2000)
 * @param {number} opts.timeout   - Max wait time in ms (default 120000)
 * @param {function} opts.onStatus - Optional callback for each poll with current status
 * @returns {Promise<Object>} - The final task result
 * @throws {Error} - On timeout or task failure
 */
export async function pollTaskResult(
  baseUrl,
  taskId,
  { interval = 2000, timeout = 120000, onStatus = null } = {},
) {
  const deadline = Date.now() + timeout;

  while (Date.now() < deadline) {
    const res = await api.get(`${baseUrl}/${taskId}`);
    const data = res.data;

    if (onStatus) onStatus(data.status || data);

    if (data.status === "completed") {
      return data.result;
    }

    if (data.status === "failed") {
      throw new Error(data.error || "AI 任务执行失败");
    }

    // Still pending/processing — wait and retry
    await new Promise((resolve) => setTimeout(resolve, interval));
  }

  throw new Error("AI 任务超时，请稍后重试");
}

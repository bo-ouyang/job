/**
 * AI 相关 API 模块
 *
 * 所有 AI 异步任务的前端接口集中管理。
 * 端点已从 /analysis/... 和 /resumes/... 迁移至 /ai/...
 */
import api from "@/utils/request";

export const aiAPI = {
  /**
   * 获取 AI 职业建议 (异步任务)
   * @param {Object} payload - { major_name, skills, engine? }
   * @returns {Promise} - { task_id, status }
   */
  getAIAdvice(payload) {
    return api.post("/ai/advice", payload, { timeout: 10000 });
  },

  /**
   * 获取职业罗盘 AI 报告 (异步任务)
   * @param {Object} params - { major_name, target_industry?, target_industry_name? }
   * @returns {Promise} - { task_id, status, es_stats } 或 { report, es_stats, cached }
   */
  getCareerCompass(params) {
    return api.post("/ai/career-compass", params);
  },

  /**
   * 上传简历进行 AI 解析 (异步任务)
   * @param {FormData} formData - 含 file 字段的 FormData
   * @returns {Promise} - { message, task_id }
   */
  parseResume(formData) {
    return api.post("/ai/parse-resume", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 30000,
    });
  },

  /**
   * 轮询 AI 任务结果
   * @param {string} taskId
   * @returns {Promise} - { task_id, status, result? | error? }
   */
  getTaskResult(taskId) {
    return api.get(`/ai/task/${taskId}`);
  },

  /**
   * 查询 AI 任务历史
   * @param {Object} params - { feature_key?, page?, page_size? }
   * @returns {Promise} - { items, total, page, size }
   */
  getTaskHistory(params = {}) {
    return api.get("/ai/tasks/history", { params });
  },
};

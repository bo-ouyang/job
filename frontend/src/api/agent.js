import request from "@/utils/request";

export const agentAPI = {
  getCapabilities() {
    return request.get("/agent/capabilities");
  },
  createConversation(payload = {}) {
    return request.post("/agent/conversations", payload);
  },
  listConversations(params = {}) {
    return request.get("/agent/conversations", { params });
  },
  getConversation(conversationId) {
    return request.get(`/agent/conversations/${conversationId}`);
  },
  sendMessage(conversationId, payload, idempotencyKey) {
    return request.post(`/agent/conversations/${conversationId}/messages`, payload, {
      headers: { "Idempotency-Key": idempotencyKey },
    });
  },
  getRun(runId) {
    return request.get(`/agent/runs/${runId}`);
  },
  cancelRun(runId) {
    return request.post(`/agent/runs/${runId}/cancel`);
  },
  getProfile() {
    return request.get("/agent/profile");
  },
};

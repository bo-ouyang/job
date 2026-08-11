import v2Request from "@/utils/v2Request";

export const marketAPI = {
  getDashboard(params = {}) {
    return v2Request.get("/market/dashboard", { params });
  },
  getHistory(params = {}) {
    return v2Request.get("/market/history", { params });
  },
  askQuestion(payload, idempotencyKey) {
    return v2Request.post("/market/questions", payload, {
      headers: { "Idempotency-Key": idempotencyKey },
    });
  },
};

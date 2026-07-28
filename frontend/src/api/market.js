import request from "@/utils/request";

export const marketAPI = {
  getDashboard(params = {}) {
    return request.get("/analysis/market/dashboard", { params });
  },
  askQuestion(payload, idempotencyKey) {
    return request.post("/analysis/market/questions", payload, {
      headers: { "Idempotency-Key": idempotencyKey },
    });
  },
};

export default marketAPI;

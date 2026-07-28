import request from "@/utils/request";

const idempotent = (key) => ({ headers: { "Idempotency-Key": key } });

export const careerAPI = {
  getPricing() {
    return request.get("/ai/pricing");
  },
  getOverview(params = {}) {
    return request.get("/career-analysis/overview", { params });
  },
  getLatestReport() {
    return request.get("/career-analysis/reports/latest");
  },
  generateReport(payload, idempotencyKey) {
    return request.post(
      "/career-analysis/reports",
      payload,
      idempotent(idempotencyKey),
    );
  },
  askQuestion(payload, idempotencyKey) {
    return request.post(
      "/career-analysis/questions",
      payload,
      idempotent(idempotencyKey),
    );
  },
};

export default careerAPI;

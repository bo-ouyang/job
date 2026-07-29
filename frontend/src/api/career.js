import v2Request from "@/utils/v2Request";

const idempotent = (key) => ({ headers: { "Idempotency-Key": key } });

export const careerAPI = {
  getPricing() {
    return v2Request.get("/ai/pricing");
  },
  getOverview(params = {}) {
    return v2Request.get("/career-analysis/overview", { params });
  },
  getLatestReport() {
    return v2Request.get("/career-analysis/reports/latest");
  },
  generateReport(payload, idempotencyKey) {
    return v2Request.post(
      "/career-analysis/reports",
      payload,
      idempotent(idempotencyKey),
    );
  },
  askQuestion(payload, idempotencyKey) {
    return v2Request.post(
      "/career-analysis/questions",
      payload,
      idempotent(idempotencyKey),
    );
  },
};

export default careerAPI;

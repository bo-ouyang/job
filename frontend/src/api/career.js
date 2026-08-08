import v2Request from "@/utils/v2Request";

const idempotent = (key) => ({ headers: { "Idempotency-Key": key } });

const pickCareerData = (data, keys) => {
  if (!data || typeof data !== "object" || Array.isArray(data)) return data;
  return keys.reduce((result, key) => {
    if (data[key] !== undefined) {
      result[key] = data[key];
    }
    return result;
  }, {});
};

const normalizeCareerResponse = async (request, keys) => {
  const response = await request;
  return { ...response, data: pickCareerData(response?.data, keys) };
};

const SUBMISSION_KEYS = ["conversationId", "runId", "status", "answer"];
const LATEST_REPORT_KEYS = ["status", "runId", "content", "report", "createdAt"];

export const careerAPI = {
  getPricing() {
    return v2Request.get("/ai/pricing");
  },
  getOverview(params = {}) {
    return v2Request.get("/career-analysis/overview", { params });
  },
  getLatestReport() {
    return normalizeCareerResponse(
      v2Request.get("/career-analysis/reports/latest"),
      LATEST_REPORT_KEYS,
    );
  },
  generateReport(payload, idempotencyKey) {
    return normalizeCareerResponse(v2Request.post(
      "/career-analysis/reports",
      payload,
      idempotent(idempotencyKey),
    ), SUBMISSION_KEYS);
  },
  askQuestion(payload, idempotencyKey) {
    return normalizeCareerResponse(v2Request.post(
      "/career-analysis/questions",
      payload,
      idempotent(idempotencyKey),
    ), SUBMISSION_KEYS);
  },
};

export default careerAPI;

const firstText = (...values) => values.find(
  (value) => typeof value === "string" && value.trim(),
);

const detailMessage = (detail, depth = 0) => {
  if (typeof detail === "string") return detail;
  if (!detail || typeof detail !== "object" || depth >= 3) return null;
  return firstText(
    detail.msg,
    detail.message,
    detailMessage(detail.detail, depth + 1),
  );
};

export const extractApiError = (error, fallback = "请求失败，请稍后重试。") => {
  const response = error?.response;
  const responseBody = response?.data;
  const body = responseBody && typeof responseBody === "object"
    ? response.data
    : {};
  const detail = body.detail;
  const data = body.data ?? null;
  const httpStatus = response?.status ?? null;
  const retryableCandidates = [body.retryable, data?.retryable, error?.retryable];
  const explicitRetryable = retryableCandidates.find(
    (value) => typeof value === "boolean",
  );

  return {
    message: firstText(
      detailMessage(body.msg),
      detailMessage(detail),
      body.message,
      typeof responseBody === "string" ? responseBody : null,
      response ? null : error?.message,
      fallback,
    ) || fallback,
    code: body.code ?? error?.code ?? null,
    data,
    httpStatus,
    retryable: explicitRetryable == null
      ? httpStatus === 408 || httpStatus === 429 || httpStatus >= 500
      : explicitRetryable,
  };
};

const RUN_STATUSES = new Set([
  "queued",
  "running",
  "waiting_user",
  "completed",
  "failed",
  "cancelled",
]);

export const extractAgentRunReference = (data) => {
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const runId = data.runId == null ? "" : String(data.runId);
  const conversationId = data.conversationId == null ? "" : String(data.conversationId);
  if (!runId || !conversationId || !RUN_STATUSES.has(data.status)) return null;
  return {
    runId,
    conversationId,
    status: data.status,
    messageType: typeof data.messageType === "string" ? data.messageType : null,
  };
};

export default extractApiError;

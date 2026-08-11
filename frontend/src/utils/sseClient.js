import {
  getAccessToken,
  getApiBaseUrl,
  refreshAccessToken,
} from "@/utils/request";

class SSERequestError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "SSERequestError";
    this.status = status;
  }
}

export function parseSSEFrame(frame) {
  const normalized = frame.replace(/\r\n/g, "\n").trimEnd();
  if (!normalized || normalized.startsWith(":")) return null;
  let id = null;
  let event = "message";
  const dataLines = [];

  normalized.split("\n").forEach((line) => {
    if (!line || line.startsWith(":")) return;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    let value = separator === -1 ? "" : line.slice(separator + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    if (field === "event") event = value;
    if (field === "data") dataLines.push(value);
  });

  if (!dataLines.length) return null;
  try {
    const data = JSON.parse(dataLines.join("\n"));
    return { id, event, data };
  } catch {
    return null;
  }
}

async function openStream({ runId, lastEventId, signal, onOpen, onEvent, token }) {
  const baseUrl = String(getApiBaseUrl()).replace(/\/$/, "");
  const headers = {
    Accept: "text/event-stream",
    Authorization: `Bearer ${token}`,
  };
  if (lastEventId && /^\d+-\d+$/.test(lastEventId)) {
    headers["Last-Event-ID"] = lastEventId;
  }

  const response = await fetch(`${baseUrl}/agent/runs/${runId}/events`, {
    method: "GET",
    headers,
    signal,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new SSERequestError(`SSE request failed with ${response.status}`, response.status);
  }
  if (!response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new SSERequestError("Server did not return an event stream", response.status);
  }

  onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let latestId = lastEventId || null;

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    buffer = buffer.replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSSEFrame(frame);
      if (parsed) {
        latestId = parsed.id || latestId;
        await onEvent?.(parsed.data, parsed);
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  return { lastEventId: latestId };
}

export async function connectAgentEventStream(options) {
  const token = getAccessToken();
  if (!token) throw new SSERequestError("Missing access token", 401);
  try {
    return await openStream({ ...options, token });
  } catch (error) {
    if (error?.status !== 401 || options.signal?.aborted) throw error;
    const refreshedToken = await refreshAccessToken();
    return openStream({ ...options, token: refreshedToken });
  }
}

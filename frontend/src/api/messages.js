import { messageAPI as legacyMessageAPI } from "@/api/message";
import v2Request from "@/utils/v2Request";

const normalizeMessage = (message = {}) => ({
  id: String(message.id ?? ""),
  title: message.title ?? null,
  content: message.content ?? "",
  type: message.type ?? "system",
  isRead: Boolean(message.isRead),
  category: message.category ?? null,
  status: message.status ?? null,
  actionType: message.actionType ?? null,
  actionData: message.actionData && typeof message.actionData === "object"
    ? message.actionData
    : null,
  sourceType: message.sourceType ?? null,
  sourceId: message.sourceId == null ? null : String(message.sourceId),
  createdAt: message.createdAt ?? null,
});

const normalizePage = (page = {}) => ({
  items: Array.isArray(page.items) ? page.items.map(normalizeMessage) : [],
  total: Number(page.total ?? 0),
  skip: Number(page.skip ?? 0),
  limit: Number(page.limit ?? 20),
});

const listParams = ({ category, status, isRead, skip = 0, limit = 20 } = {}) => {
  const params = { skip, limit };
  if (category) params.category = category;
  if (status) params.status = status;
  // The V2 API has no isRead=true predicate.  Omit it for "all" and send
  // unreadOnly only for the explicit unread filter.
  if (isRead === false) params.unreadOnly = true;
  return params;
};

export const messagesAPI = {
  async list(filters = {}, requestOptions = {}) {
    const response = await v2Request.get("/messages/", { ...requestOptions, params: listParams(filters) });
    return { ...response, data: normalizePage(response?.data) };
  },

  // V2 has not exposed notification mutations yet.  Keep this short-lived
  // compatibility boundary here so views remain V2-only.
  markAsRead(messageId) {
    return legacyMessageAPI.markAsRead(messageId);
  },

  markAllAsRead() {
    return legacyMessageAPI.markAllAsRead();
  },

  getUnreadCount() {
    return legacyMessageAPI.getUnreadCount();
  },
};

export default messagesAPI;

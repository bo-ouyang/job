import request from "@/utils/request";

export const messageAPI = {
  getMessages(params) {
    return request.get("/messages/", { params });
  },
  getUnreadCount() {
    return request.get("/messages/unread-count");
  },
  markAsRead(messageId) {
    return request.put(`/messages/${messageId}/read`);
  },
  markAllAsRead() {
    return request.post("/messages/mark-all-read");
  },
};

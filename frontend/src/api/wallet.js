import request from "@/utils/request";

export const walletAPI = {
  getBalance() {
    return request.get("/wallet/balance");
  },
  getTransactions(params = {}) {
    return request.get("/wallet/transactions", { params });
  },
  getTransactionsPage(params = {}) {
    return request.get("/wallet/transactions/page", { params });
  },
  simulateTopup(data) {
    return request.post("/wallet/topup/simulate", data);
  },
  createPayment(data) {
    return request.post("/payment/create", data);
  },
  checkPaymentStatus(orderNo) {
    return request.get(`/payment/check/${orderNo}`);
  },
  getMyOrders(params = {}) {
    return request.get("/payment/my/orders", { params });
  },
  adminGetOrders(params = {}) {
    return request.get("/payment/admin/orders", { params });
  },
  adminRepairOrder(orderNo) {
    return request.post(`/payment/admin/repair/${orderNo}`);
  },
  adminMarkFailed(orderNo, reason) {
    return request.post(`/payment/admin/mark-failed/${orderNo}`, null, {
      params: { reason },
    });
  },
  adminManualTopup(data) {
    return request.post("/wallet/admin/manual-topup", data);
  },
};

import request from "@/utils/request";

export const walletAPI = {
  getBalance() {
    return request.get("/wallet/balance");
  },
  getTransactionsPage(params = {}) {
    return request.get("/wallet/transactions/page", { params });
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
};

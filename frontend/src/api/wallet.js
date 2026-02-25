import request from "@/utils/request";

export const walletAPI = {
  getBalance() {
    return request.get("/wallet/balance");
  },
  createPayment(data) {
    return request.post("/payment/create", data);
  },
  checkPaymentStatus(orderNo) {
    return request.get(`/payment/check/${orderNo}`);
  },
};

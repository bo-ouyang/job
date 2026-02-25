import request from "@/utils/request";

export const authAPI = {
  login(username, password) {
    return request.post("/auth/login", { username, password });
  },
  register(userData) {
    return request.post("/auth/register", userData);
  },
  loginWithPhone(phone, code) {
    return request.post("/auth/login/phone", {
      phone,
      verification_code: code,
    });
  },
  loginWithWechat(code) {
    return request.post("/auth/login/wechat", { code });
  },
  sendSmsCode(phone, type = "login") {
    return request.post("/auth/send-sms", { phone, type });
  },
  getQrCode() {
    return request.get("/auth/qrcode/generate");
  },
  checkQrCodeStatus(ticket) {
    return request.get(`/auth/qrcode/status?ticket=${ticket}`);
  },
  mockScanQrCode(ticket) {
    return request.post(`/auth/qrcode/dev/scan?ticket=${ticket}`);
  },
  mockConfirmQrCode(ticket) {
    return request.post(`/auth/qrcode/dev/confirm?ticket=${ticket}`);
  },
  logout() {
    return request.post("/auth/logout");
  },
  updateProfile(userData) {
    return request.put("/users/me", userData);
  },
};

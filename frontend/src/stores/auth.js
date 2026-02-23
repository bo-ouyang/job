import { defineStore } from "pinia";
import { ref, computed } from "vue";
import api from "../core/api";

export const useAuthStore = defineStore("auth", () => {
  // State
  const user = ref(JSON.parse(localStorage.getItem("user")) || null);
  const token = ref(localStorage.getItem("token") || null);
  const refreshToken = ref(localStorage.getItem("refresh_token") || null);

  // Getters
  const isAuthenticated = computed(() => !!token.value);

  // Actions
  const login = async (username, password) => {
    const response = await api.post("/auth/login", { username, password });
    handleLoginSuccess(response.data);
    return response.data;
  };

  const register = async (userData) => {
    const response = await api.post("/auth/register", userData);
    handleLoginSuccess(response.data);
    return response.data;
  };

  const loginWithPhone = async (phone, code) => {
    const response = await api.post("/auth/login/phone", {
      phone,
      verification_code: code,
    });
    handleLoginSuccess(response.data);
    return response.data;
  };

  const loginWithWechat = async (code) => {
    const response = await api.post("/auth/login/wechat", { code });
    handleLoginSuccess(response.data);
    return response.data;
  };

  const sendSmsCode = async (phone, type = "login") => {
    const response = await api.post("/auth/send-sms", { phone, type });
    return response.data;
  };

  // QR Code Login Actions
  const getQrCode = async () => {
    const response = await api.get("/auth/qrcode/generate");
    return response.data;
  };

  const checkQrCodeStatus = async (ticket) => {
    const response = await api.get(`/auth/qrcode/status?ticket=${ticket}`);
    return response.data;
  };

  const mockScanQrCode = async (ticket) => {
    return await api.post(`/auth/qrcode/dev/scan?ticket=${ticket}`);
  };

  const mockConfirmQrCode = async (ticket) => {
    return await api.post(`/auth/qrcode/dev/confirm?ticket=${ticket}`);
  };

  const handleLoginSuccess = (data) => {
    token.value = data.token.access_token;
    refreshToken.value = data.token.refresh_token;
    user.value = data.user;

    // Persist to localStorage
    localStorage.setItem("token", token.value);
    localStorage.setItem("refresh_token", refreshToken.value);
    localStorage.setItem("user", JSON.stringify(user.value));
  };

  const logout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (e) {
      console.error("Logout error:", e);
    } finally {
      user.value = null;
      token.value = null;
      refreshToken.value = null;
      localStorage.removeItem("token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("user");
    }
  };

  const updateProfile = async (userData) => {
    const response = await api.put("/users/me", userData);
    user.value = response.data;
    localStorage.setItem("user", JSON.stringify(user.value));
    return response.data;
  };

  return {
    user,
    token,
    isAuthenticated,
    login,
    register,
    loginWithPhone,
    loginWithWechat,
    sendSmsCode,
    logout,
    updateProfile,
  };
});

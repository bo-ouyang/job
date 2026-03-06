import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { authAPI } from "@/api/auth";
import router from "@/router";

export const useAuthStore = defineStore("auth", () => {
  // State
  const user = ref(JSON.parse(localStorage.getItem("user")) || null);
  const token = ref(localStorage.getItem("token") || null);
  const refreshToken = ref(localStorage.getItem("refresh_token") || null);

  // Getters
  const isAuthenticated = computed(() => !!token.value);

  // Actions
  const login = async (username, password) => {
    const response = await authAPI.login(username, password);
    handleLoginSuccess(response.data);
    return response.data;
  };

  const register = async (userData) => {
    const response = await authAPI.register(userData);
    handleLoginSuccess(response.data);
    return response.data;
  };

  const loginWithPhone = async (phone, code) => {
    const response = await authAPI.loginWithPhone(phone, code);
    handleLoginSuccess(response.data);
    return response.data;
  };

  const loginWithWechat = async (code) => {
    const response = await authAPI.loginWithWechat(code);
    handleLoginSuccess(response.data);
    return response.data;
  };

  const sendSmsCode = async (phone, type = "login") => {
    const response = await authAPI.sendSmsCode(phone, type);
    return response.data;
  };

  // QR Code Login Actions
  const getQrCode = async () => {
    const response = await authAPI.getQrCode();
    return response.data;
  };

  const checkQrCodeStatus = async (ticket) => {
    const response = await authAPI.checkQrCodeStatus(ticket);
    return response.data;
  };

  const mockScanQrCode = async (ticket) => {
    return await authAPI.mockScanQrCode(ticket);
  };

  const mockConfirmQrCode = async (ticket) => {
    return await authAPI.mockConfirmQrCode(ticket);
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
      await authAPI.logout();
    } catch (e) {
      console.error("Logout error:", e);
    } finally {
      user.value = null;
      token.value = null;
      refreshToken.value = null;
      localStorage.removeItem("token");
      localStorage.removeItem("refresh_token");
      localStorage.removeItem("user");
      // Explicitly clear AI Task persisted state
      localStorage.removeItem("aiTask");
      try {
        const aiTaskStore = (await import("@/stores/aiTask")).useAiTaskStore();
        aiTaskStore.$reset();
      } catch (e) {
        console.error("Failed to reset aiTask store:", e);
      }
      // Force redirect to login page cleanly via router
      if (window.location.pathname !== "/login") {
        router.push("/login");
      }
    }
  };

  const updateProfile = async (userData) => {
    const response = await authAPI.updateProfile(userData);
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
    getQrCode,
    checkQrCodeStatus,
    mockScanQrCode,
    mockConfirmQrCode,
    logout,
    updateProfile,
  };
});

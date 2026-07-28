import axios from "axios";
import router from "@/router";

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1",
  timeout: 5000,
});

let refreshPromise = null;
const WALLET_PENDING_ORDER_KEY = "wallet_pending_order_no";

export const getApiBaseUrl = () => service.defaults.baseURL;
export const getAccessToken = () => localStorage.getItem("token");

export const refreshAccessToken = async () => {
  if (refreshPromise) return refreshPromise;
  const refreshToken = localStorage.getItem("refresh_token");
  if (!refreshToken) {
    await handleLogout();
    throw new Error("Missing refresh token");
  }

  refreshPromise = axios
    .post(`${service.defaults.baseURL}/auth/refresh-token`, {
      refresh_token: refreshToken,
    })
    .then((refreshRes) => {
      const payload = refreshRes.data?.code === 200 ? refreshRes.data.data : refreshRes.data;
      const accessToken = payload?.access_token;
      if (!accessToken) throw new Error("Token refresh returned no access token");
      localStorage.setItem("token", accessToken);
      window.dispatchEvent(
        new CustomEvent("auth-token-refreshed", { detail: { token: accessToken } }),
      );
      return accessToken;
    })
    .catch(async (error) => {
      await handleLogout();
      throw error;
    })
    .finally(() => {
      refreshPromise = null;
    });

  return refreshPromise;
};

const extractErrorMessage = (response) => {
  if (!response) return "";
  const data = response.data || {};
  return String(data.detail || data.msg || data.message || "").trim();
};

const isAuthForbidden = (response) => {
  const token = localStorage.getItem("token");
  const message = extractErrorMessage(response).toLowerCase();

  if (!token) {
    return true;
  }

  return [
    "not authenticated",
    "could not validate credentials",
    "credentials",
    "token",
    "bearer",
    "login required",
    "请先登录",
    "无法验证凭据",
    "未登录",
  ].some((keyword) => message.includes(keyword));
};

const clearWalletPendingOrders = () => {
  Object.keys(localStorage).forEach((key) => {
    if (key === WALLET_PENDING_ORDER_KEY || key.startsWith(`${WALLET_PENDING_ORDER_KEY}:`)) {
      localStorage.removeItem(key);
    }
  });
};

// Request interceptor
service.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

// Response interceptor
service.interceptors.response.use(
  (response) => {
    // Auto-unwrap unified response structure
    if (
      response.data &&
      response.data.code === 200 &&
      response.data.data !== undefined
    ) {
      // Keep the original status but replace data with the inner data
      // We might want to keep properties like 'msg' somewhere if needed,
      // but for compatibility with existing code that expects 'response.data' to be the payload:
      response.data = response.data.data;
    }
    return response;
  },
  async (error) => {
    const { config, response } = error;
    const originalRequest = config;

    // Handle 401 Unauthorized
    if (response && response.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const token = await refreshAccessToken();
        originalRequest.headers.Authorization = `Bearer ${token}`;
        return service(originalRequest);
      } catch (refreshError) {
        return Promise.reject(refreshError);
      }
    }

    // 403 不一定表示未登录，也可能是权限不足或安全策略拦截。
    if (response && response.status === 403) {
      const detail = extractErrorMessage(response) || "当前请求被拒绝";
      if (isAuthForbidden(response) && window.location.pathname !== "/login") {
        import("element-plus/es/components/message/index.mjs")
          .then(({ ElMessage }) => {
            ElMessage.warning("请先登录后使用此功能");
          })
          .catch(() => {
            alert("请先登录后使用此功能");
          });

        setTimeout(() => {
          router.push({
            path: "/login",
            query: { redirect: window.location.pathname },
          });
        }, 1000);
      } else {
        import("element-plus/es/components/message/index.mjs")
          .then(({ ElMessage }) => {
            ElMessage.error(detail);
          })
          .catch(() => {
            alert(detail);
          });
      }
    }

    if (response && response.status === 402) {
      const detail =
        response?.data?.detail || "余额不足，请先充值后继续使用该 AI 功能";
      window.dispatchEvent(
        new CustomEvent("billing-required", { detail: { message: detail } }),
      );
      if (window.location.pathname !== "/my/wallet") {
        alert(`${detail}\n将为你跳转到钱包页面。`);
        window.location.href = "/my/wallet";
      }
    }

    return Promise.reject(error);
  },
);

export async function handleLogout() {
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");
  clearWalletPendingOrders();

  // Clear persistent AI Task store
  try {
    const aiTaskStore = (await import("@/stores/aiTask")).useAiTaskStore();
    aiTaskStore.$reset();
  } catch (e) {
    /* ignore */
  }
  try {
    const agentStore = (await import("@/stores/agent")).useAgentStore();
    agentStore.reset?.();
  } catch (e) {
    /* ignore */
  }

  const currentRoute = router.currentRoute?.value;
  const requiresAuth = currentRoute?.matched?.some(
    (record) => record.meta?.requiresAuth,
  );
  if (requiresAuth) {
    router.push({
      name: "home",
      query: {
        login: "true",
        redirect: currentRoute.fullPath,
      },
    });
  }
}

export default service;


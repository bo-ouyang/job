import axios from "axios";
import router from "@/router";

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1",
  timeout: 5000,
});

let isRefreshing = false;
let refreshSubscribers = [];

const subscribeTokenRefresh = (cb) => {
  refreshSubscribers.push(cb);
};

const onRefreshed = (token) => {
  refreshSubscribers.map((cb) => cb(token));
  refreshSubscribers = [];
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

      const refreshToken = localStorage.getItem("refresh_token");
      if (!refreshToken) {
        handleLogout();
        return Promise.reject(error);
      }

      if (!isRefreshing) {
        isRefreshing = true;
        try {
          // No interceptors for this specific call to avoid loop
          // Use the same baseURL as the main service instance
          const refreshUrl = `${service.defaults.baseURL}/auth/refresh-token`;
          console.log(
            `Token expired (401). Attempting silent refresh via ${refreshUrl}...`,
          );

          const refreshRes = await axios.post(refreshUrl, {
            refresh_token: refreshToken,
          });

          // Handle Unified Response Structure
          let access_token;
          if (
            refreshRes.data &&
            refreshRes.data.code === 200 &&
            refreshRes.data.data
          ) {
            access_token = refreshRes.data.data.access_token;
          } else {
            // Fallback for non-wrapped or direct response
            access_token = refreshRes.data.access_token;
          }

          if (!access_token) {
            throw new Error("Token refresh failed: No access token received");
          }

          localStorage.setItem("token", access_token);

          isRefreshing = false;
          onRefreshed(access_token);
        } catch (refreshError) {
          isRefreshing = false;
          console.error("Silent token refresh failed:", refreshError);
          handleLogout();
          return Promise.reject(refreshError);
        }
      }

      // Wait for token refresh and retry original request
      return new Promise((resolve) => {
        subscribeTokenRefresh((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          resolve(service(originalRequest));
        });
      });
    }

    // Handle 403 Forbidden (Usually means user is not logged in but tries to access protected resource)
    if (response && response.status === 403) {
      if (window.location.pathname !== "/login") {
        import("element-plus")
          .then(({ ElMessage }) => {
            ElMessage.warning("请先登录后使用此功能");
          })
          .catch(() => {
            alert("请先登录后使用此功能");
          });

        // Small delay to let the user see the message before redirect
        setTimeout(() => {
          router.push({
            path: "/login",
            query: { redirect: window.location.pathname },
          });
        }, 1000);
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

async function handleLogout() {
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");

  // Clear persistent AI Task store
  try {
    const aiTaskStore = (await import("@/stores/aiTask")).useAiTaskStore();
    aiTaskStore.$reset();
  } catch (e) {
    /* ignore */
  }

  // Force redirect to login page and refresh to clear Pinia state
  if (window.location.pathname !== "/login") {
    // We intentionally avoid window.location.href or window.location.reload()
    // because that causes a hard page request to the server, which results
    // in a 404 Nginx error if try_files is not properly configured.
    // Instead, we use Vue router to navigate safely as an SPA.
    router.push({
      path: "/login",
      query: { redirect: window.location.pathname },
    });
  }
}

export default service;

import axios from "axios";

const api = axios.create({
  baseURL: "http://127.0.0.1:8000/api", // Consistent with settings.API_V1_STR
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
api.interceptors.request.use(
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
api.interceptors.response.use(
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
          // Use the same baseURL as the main api instance
          const refreshUrl = `${api.defaults.baseURL}/auth/refresh-token`;
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
          resolve(api(originalRequest));
        });
      });
    }

    return Promise.reject(error);
  },
);

function handleLogout() {
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user");

  // Force redirect to login page and refresh to clear Pinia state
  if (window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
}

export default api;

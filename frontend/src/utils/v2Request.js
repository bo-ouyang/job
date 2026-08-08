import axios from "axios";

import { getAccessToken, refreshAccessToken } from "@/utils/request";
import { extractApiError } from "@/utils/apiError";


const service = axios.create({
  baseURL: import.meta.env.VITE_API_V2_BASE_URL || "/api/v2",
  timeout: 8000,
});

export const getV2ApiBaseUrl = () => service.defaults.baseURL;

service.interceptors.request.use(
  (config) => {
    const token = getAccessToken();
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error),
);

export const handleV2ResponseError = async (error) => {
  const { config, response } = error;
  const originalRequest = config || {};

  if (response?.status === 401 && !originalRequest._retry) {
    originalRequest._retry = true;
    try {
      const token = await refreshAccessToken();
      originalRequest.headers = originalRequest.headers || {};
      originalRequest.headers.Authorization = `Bearer ${token}`;
      return service(originalRequest);
    } catch (refreshError) {
      return Promise.reject(refreshError);
    }
  }

  if (response?.status === 402) {
    const detail = extractApiError(
      error,
      "余额不足，请先充值后继续使用该 AI 功能",
    ).message;
    window.dispatchEvent(
      new CustomEvent("billing-required", { detail: { message: detail } }),
    );
    if (window.location.pathname !== "/my/wallet") {
      window.location.assign("/my/wallet");
    }
  }

  return Promise.reject(error);
};

service.interceptors.response.use(
  (response) => {
    if (
      response.data
      && response.data.code === 200
      && response.data.data !== undefined
    ) {
      response.data = response.data.data;
    }
    return response;
  },
  handleV2ResponseError,
);

export default service;

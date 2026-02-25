import request from "@/utils/request";

export const jobAPI = {
  getJobs(params) {
    return request.get("/jobs/", { params });
  },
  getJobDetail(id) {
    return request.get(`/jobs/${id}`);
  },
  getFavoriteJobs(params) {
    return request.get("/favorites/jobs", { params });
  },
  addFavorite(jobId) {
    return request.post(`/favorites/jobs/${jobId}`);
  },
  removeFavorite(jobId) {
    return request.delete(`/favorites/jobs/${jobId}`);
  },
  checkFavorite(jobId) {
    return request.get(`/favorites/jobs/${jobId}/check`);
  },
  getRecommendedJobs(params) {
    return request.get("/jobs/recommendations", { params });
  },
};

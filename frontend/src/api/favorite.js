import request from "@/utils/request";

export const favoriteAPI = {
  getFavoriteJobs() {
    return request.get("/favorites/jobs");
  },
  getFollowedCompanies() {
    return request.get("/favorites/companies");
  },
  addFavoriteJob(jobId) {
    return request.post(`/favorites/jobs/${jobId}`);
  },
  removeFavoriteJob(jobId) {
    return request.delete(`/favorites/jobs/${jobId}`);
  },
  addFollowCompany(companyId) {
    return request.post(`/favorites/companies/${companyId}`);
  },
  removeFollowCompany(companyId) {
    return request.delete(`/favorites/companies/${companyId}`);
  },
};

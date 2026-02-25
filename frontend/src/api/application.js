import request from "@/utils/request";

export const applicationAPI = {
  applyForJob(jobId) {
    return request.post("/applications/", { job_id: jobId });
  },
  getMyApplications(params) {
    return request.get("/applications/me", { params });
  },
  updateApplicationStatus(applicationId, status) {
    return request.put(`/applications/${applicationId}/status`, { status });
  },
};

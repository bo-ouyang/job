import request from "@/utils/request";

export const resumeAPI = {
  getMyResume() {
    return request.get("/resumes/me");
  },
  createResume(data) {
    return request.post("/resumes/me", data);
  },
  updateResume(data) {
    return request.put("/resumes/me", data);
  },
  addEducation(data) {
    return request.post("/resumes/me/educations", data);
  },
  deleteEducation(id) {
    return request.delete(`/resumes/me/educations/${id}`);
  },
  addWorkExperience(data) {
    return request.post("/resumes/me/works", data);
  },
  deleteWorkExperience(id) {
    return request.delete(`/resumes/me/works/${id}`);
  },
  uploadFile(file) {
    const formData = new FormData();
    formData.append("file", file);
    return request.post("/upload/", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },
  parseResume(formData) {
    return request.post("/resumes/parse", formData, {
      headers: { "Content-Type": "multipart/form-data" },
      timeout: 60000, // 60s timeout for parsing
    });
  },
};

import v2Request from "@/utils/v2Request";

export const profileAPI = {
  getProfile() {
    return v2Request.get("/profile");
  },
  updateProfile(payload) {
    return v2Request.patch("/profile", payload);
  },
  applyResumeCandidates(payload) {
    return v2Request.post("/profile/resume-candidates", payload);
  },
  getCourses() {
    return v2Request.get("/profile/courses");
  },
  saveCourses(payload) {
    return v2Request.put("/profile/courses", payload);
  },
  getSkills() {
    return v2Request.get("/profile/skills");
  },
  saveSkills(payload) {
    return v2Request.put("/profile/skills", payload);
  },
};

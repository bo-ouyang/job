import request from "@/utils/request";

export const profileAPI = {
  getProfile() {
    return request.get("/profile");
  },
  updateProfile(payload) {
    return request.patch("/profile", payload);
  },
  getCourses() {
    return request.get("/profile/courses");
  },
  saveCourses(payload) {
    return request.put("/profile/courses", payload);
  },
  getSkills() {
    return request.get("/profile/skills");
  },
  saveSkills(payload) {
    return request.put("/profile/skills", payload);
  },
};

export default profileAPI;

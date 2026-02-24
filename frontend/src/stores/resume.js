import { defineStore } from "pinia";
import { ref } from "vue";
import api from "../core/api";

export const useResumeStore = defineStore("resume", () => {
  const resume = ref(null);
  const isLoading = ref(false);
  const error = ref(null);

  const fetchMyResume = async () => {
    isLoading.value = true;
    error.value = null;
    try {
      const res = await api.get("/resumes/me");
      resume.value = res.data;
    } catch (err) {
      if (err.response && err.response.status === 404) {
        resume.value = null; // No resume yet
      } else {
        error.value = err.response?.data?.detail || "获取简历失败";
      }
    } finally {
      isLoading.value = false;
    }
  };

  const createResume = async (data) => {
    isLoading.value = true;
    try {
      const res = await api.post("/resumes/me", data);
      resume.value = res.data;
      return res.data;
    } catch (err) {
      throw err.response?.data?.detail || "创建简历失败";
    } finally {
      isLoading.value = false;
    }
  };

  const updateResume = async (data) => {
    isLoading.value = true;
    try {
      const res = await api.put("/resumes/me", data);
      resume.value = res.data; // Update local
      return res.data;
    } catch (err) {
      throw err.response?.data?.detail || "更新简历失败";
    } finally {
      isLoading.value = false;
    }
  };

  const addEducation = async (data) => {
    const res = await api.post("/resumes/me/educations", data);
    resume.value = res.data;
  };

  const deleteEducation = async (id) => {
    const res = await api.delete(`/resumes/me/educations/${id}`);
    resume.value = res.data;
  };

  // Work Experience Actions
  const addWorkExperience = async (data) => {
    const res = await api.post("/resumes/me/works", data);
    resume.value = res.data;
  };

  const deleteWorkExperience = async (id) => {
    const res = await api.delete(`/resumes/me/works/${id}`);
    resume.value = res.data;
  };

  // Upload File
  const uploadFile = async (file) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await api.post("/upload/", formData, {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    });
    return res.data; // { filename, url, content_type }
  };

  return {
    resume,
    isLoading,
    error,
    fetchMyResume,
    createResume,
    updateResume,
    addEducation,
    deleteEducation,
    addWorkExperience,
    deleteWorkExperience,
    uploadFile,
  };
});

import { defineStore } from "pinia";
import { ref } from "vue";
import { resumeAPI } from "@/api/resume";

export const useResumeStore = defineStore("resume", () => {
  const resume = ref(null);
  const isLoading = ref(false);
  const error = ref(null);

  const fetchMyResume = async () => {
    isLoading.value = true;
    error.value = null;
    try {
      const res = await resumeAPI.getMyResume();
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
      const res = await resumeAPI.createResume(data);
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
      const res = await resumeAPI.updateResume(data);
      resume.value = res.data; // Update local
      return res.data;
    } catch (err) {
      throw err.response?.data?.detail || "更新简历失败";
    } finally {
      isLoading.value = false;
    }
  };

  const addEducation = async (data) => {
    const res = await resumeAPI.addEducation(data);
    resume.value = res.data;
  };

  const deleteEducation = async (id) => {
    const res = await resumeAPI.deleteEducation(id);
    resume.value = res.data;
  };

  const addWorkExperience = async (data) => {
    const res = await resumeAPI.addWorkExperience(data);
    resume.value = res.data;
  };

  const deleteWorkExperience = async (id) => {
    const res = await resumeAPI.deleteWorkExperience(id);
    resume.value = res.data;
  };

  const uploadFile = async (file) => {
    const res = await resumeAPI.uploadFile(file);
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

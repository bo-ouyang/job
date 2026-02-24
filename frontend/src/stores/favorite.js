import { defineStore } from "pinia";
import { ref } from "vue";
import api from "../core/api";

export const useFavoriteStore = defineStore("favorite", () => {
  const favoriteJobs = ref([]);
  const followedCompanies = ref([]);
  const isLoading = ref(false);

  const fetchFavoriteJobs = async () => {
    const res = await api.get("/favorites/jobs");
    favoriteJobs.value = res.data;
  };

  const fetchFollowedCompanies = async () => {
    const res = await api.get("/favorites/companies");
    followedCompanies.value = res.data;
  };

  const toggleFavoriteJob = async (jobId) => {
    // Toggle logic: Check if exists to decide delete or post?
    // Backend provides specific endpoints.
    // Ideally we should know current state.
    // For simplicity, we assume the caller knows or we try add, if fails/exists we treat as success or ignore.
    // But usually toggle needs 'isFavorited' state.
    // Let's provide add and remove.
  };

  const addFavoriteJob = async (jobId) => {
    await api.post(`/favorites/jobs/${jobId}`);
    await fetchFavoriteJobs();
  };

  const removeFavoriteJob = async (jobId) => {
    await api.delete(`/favorites/jobs/${jobId}`);
    await fetchFavoriteJobs();
  };

  const addFollowCompany = async (companyId) => {
    await api.post(`/favorites/companies/${companyId}`);
    await fetchFollowedCompanies();
  };

  const removeFollowCompany = async (companyId) => {
    await api.delete(`/favorites/companies/${companyId}`);
    await fetchFollowedCompanies();
  };

  return {
    favoriteJobs,
    followedCompanies,
    fetchFavoriteJobs,
    fetchFollowedCompanies,
    addFavoriteJob,
    removeFavoriteJob,
    addFollowCompany,
    removeFollowCompany,
  };
});

import { defineStore } from "pinia";
import { ref } from "vue";
import { favoriteAPI } from "@/api/favorite";

export const useFavoriteStore = defineStore("favorite", () => {
  const favoriteJobs = ref([]);
  const followedCompanies = ref([]);
  const isLoading = ref(false);

  const fetchFavoriteJobs = async () => {
    const res = await favoriteAPI.getFavoriteJobs();
    favoriteJobs.value = res.data;
  };

  const fetchFollowedCompanies = async () => {
    const res = await favoriteAPI.getFollowedCompanies();
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
    await favoriteAPI.addFavoriteJob(jobId);
    await fetchFavoriteJobs();
  };

  const removeFavoriteJob = async (jobId) => {
    await favoriteAPI.removeFavoriteJob(jobId);
    await fetchFavoriteJobs();
  };

  const addFollowCompany = async (companyId) => {
    await favoriteAPI.addFollowCompany(companyId);
    await fetchFollowedCompanies();
  };

  const removeFollowCompany = async (companyId) => {
    await favoriteAPI.removeFollowCompany(companyId);
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

<script setup>
import { ref, onMounted, watch, reactive, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { jobAPI } from '@/api/job';
import { commonAPI } from '@/api/common';

const route = useRoute();
const router = useRouter(); // Added router
const jobs = ref([]);
const loading = ref(true);
const total = ref(0);
const selectedJob = ref(null); // 当前选中的职位

// 筛选状态
const filters = reactive({
  location: "", // Now stores City Code (int) or empty string
  experience: "",
  education: "",
  industry: "", // Now stores Industry Code (int) or empty string
  salary_range: "",
  q: route.query.q || "",
  ai_q: route.query.ai_q || "", // ⚡ 捕获 AI 查询意图
});

const isAiLoading = ref(false); // AI 专属加载遮罩状态

// 选项配置
const locations = ref([]); // Changed to ref for API data
const experiences = [
  "应届生",
  "1年以内",
  "1-3年",
  "3-5年",
  "5-10年",
  "10年以上",
];
const educations = ["大专", "本科", "硕士", "博士", "不限"];
const industryOptions = ref([]);

const salaryRanges = [
  { label: "不限", min: null, max: null },
  { label: "10k以下", min: 0, max: 10 },
  { label: "10k-20k", min: 10, max: 20 },
  { label: "20k-30k", min: 20, max: 30 },
  { label: "30k-50k", min: 30, max: 50 },
  { label: "50k以上", min: 50, max: null },
];

const currentPage = ref(1);
const pageSize = ref(20);

// Data Fetching for Metadata
const fetchMetadata = async () => {
  try {
    const [cityRes, industryRes] = await Promise.all([
      commonAPI.getCities(1), // Fetch Level 1 Cities
      commonAPI.getIndustries(0), // Fetch Level 1 Industries
    ]);
    locations.value = cityRes.data;
    industryOptions.value = industryRes.data;
  } catch (e) {
    console.error("Failed to fetch metadata", e);
  }
};

const fetchJobs = async () => {
  // 💡 智能分流逻辑：如果是 AI 模式，转走专门的通道
  if (filters.ai_q) {
    await executeAiSearch();
    return;
  }

  loading.value = true;
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
    };

    if (filters.q) params.q = filters.q;

    // Pass Code for Location if selected (filters.location is now bound to code)
    if (filters.location) params.location = filters.location;

    if (filters.experience && filters.experience !== "不限")
      params.experience = filters.experience;
    if (filters.education && filters.education !== "不限")
      params.education = filters.education;

    // Pass Code for Industry if selected
    if (filters.industry) params.industry = filters.industry;

    if (filters.salary_range) {
      const range = salaryRanges.find((r) => r.label === filters.salary_range);
      if (range) {
        if (range.min !== null) params.salary_min = range.min;
        if (range.max !== null) params.salary_max = range.max;
      }
    }

    const response = await jobAPI.getJobs(params);
    jobs.value = response.data.items;
    total.value = response.data.total;

    // 默认选中第一个
    if (jobs.value.length > 0) {
      selectedJob.value = jobs.value[0];
    } else {
      selectedJob.value = null;
    }
  } catch (error) {
    console.error("Failed to fetch jobs:", error);
  } finally {
    loading.value = false;
  }
};

const executeAiSearch = async () => {
  loading.value = true;
  isAiLoading.value = true;
  try {
    const params = {
      q: filters.ai_q,
      page: currentPage.value,
      page_size: pageSize.value,
    };
    const response = await api.get("/jobs/ai_search", { params });
    jobs.value = response.data.items;
    total.value = response.data.total;

    if (jobs.value.length > 0) {
      selectedJob.value = jobs.value[0];
    } else {
      selectedJob.value = null;
    }
  } catch (e) {
    console.error("AI Search Failed", e);
  } finally {
    isAiLoading.value = false;
    loading.value = false;
  }
};

const handlePageChange = (page) => {
  currentPage.value = page;
  fetchJobs();
  document
    .querySelector(".job-list-panel")
    ?.scrollTo({ top: 0, behavior: "smooth" });
};

const selectJob = (job) => {
  selectedJob.value = job;
  checkFavoriteStatus(job.id);
};

const parseTags = (tagStr) => {
  if (!tagStr) return [];
  try {
    return JSON.parse(tagStr);
  } catch (e) {
    if (typeof tagStr === "string")
      return tagStr.split(",").filter((t) => t.trim());
    return [];
  }
};

const handleImageError = (e) => {
  e.target.src = "https://via.placeholder.com/50";
};

import { useAuthStore } from "../stores/auth";
const authStore = useAuthStore();
const isFavorite = ref(false);

const checkFavoriteStatus = async (jobId) => {
  if (!authStore.isAuthenticated) return;
  try {
    // Query favorite jobs for current user to see if this one is favorited
    const res = await api.get("/favorites/jobs");
    const favList = res.data || [];
    isFavorite.value = favList.some((item) => item.job_id === jobId);
  } catch (e) {
    console.error("Check favorite failed", e);
  }
};

const toggleFavorite = async () => {
  if (!authStore.isAuthenticated) {
    alert("请先登录再执行此操作！"); // Or trigger login modal
    return;
  }
  if (!selectedJob.value) return;

  const jobId = selectedJob.value.id;
  try {
    if (isFavorite.value) {
      await api.delete(`/favorites/jobs/${jobId}`);
      isFavorite.value = false;
    } else {
      await api.post(`/favorites/jobs/${jobId}`);
      isFavorite.value = true;
    }
  } catch (e) {
    alert("操作失败：" + (e.response?.data?.detail || e.message));
  }
};


onMounted(async () => {
  await fetchMetadata();
  fetchJobs();
});

watch(
  filters,
  () => {
    currentPage.value = 1; // 重置页码
    fetchJobs();
  },
  { deep: true },
);
</script>

<template>
  <div class="market-view">
    <!-- 顶部搜索栏 (保持不变) -->
    <div class="page-header">
      <div class="header-content">
        <div class="search-section" :class="{ 'ai-active': !!filters.ai_q }">
          <div class="search-bar" :class="{ 'ai-mode': !!filters.ai_q }">
            <span class="search-icon" v-if="!filters.ai_q">🔍</span>
            <span class="search-icon ai-sparkle" v-else>✨</span>
            <input
              v-if="!filters.ai_q"
              v-model.lazy="filters.q"
              placeholder="搜索职位、公司、技能..."
              @keyup.enter="fetchJobs"
            />
            <input
              v-else
              v-model.lazy="filters.ai_q"
              class="ai-input"
              placeholder="请用一段话描述您的求职意向，大模型将为您精准匹配..."
              @keyup.enter="fetchJobs"
            />
            <div
              class="ai-toggle"
              @click="
                filters.ai_q = filters.ai_q ? '' : ' ';
                filters.q = '';
              "
              title="切换 AI 语义引擎"
            >
              <span class="toggle-track" :class="{ active: !!filters.ai_q }"
                ><span class="toggle-thumb"></span
              ></span>
              <span class="toggle-label">AI引擎</span>
            </div>
          </div>
          <button
            class="primary-search-btn"
            :class="{ 'ai-btn': !!filters.ai_q }"
            @click="fetchJobs"
          >
            {{ filters.ai_q ? "精准发现" : "搜 索" }}
          </button>
        </div>
        <!-- 简化的筛选栏，放顶部 -->
        <div class="filters-bar" :class="{ disabled: !!filters.ai_q }">
          <!-- Location Filter: Binds to City Code -->
          <select v-model="filters.location" :disabled="!!filters.ai_q">
            <option value="">城市</option>
            <option v-for="l in locations" :key="l.code" :value="l.code">
              {{ l.name }}
            </option>
          </select>

          <!-- Industry Filter: Binds to Industry Code -->
          <select v-model="filters.industry" :disabled="!!filters.ai_q">
            <option value="">行业</option>
            <option v-for="i in industryOptions" :key="i.code" :value="i.code">
              {{ i.name }}
            </option>
          </select>

          <select v-model="filters.experience" :disabled="!!filters.ai_q">
            <option value="">经验</option>
            <option v-for="e in experiences" :value="e">{{ e }}</option>
          </select>
          <select v-model="filters.education" :disabled="!!filters.ai_q">
            <option value="">学历</option>
            <option v-for="e in educations" :value="e">{{ e }}</option>
          </select>
          <select v-model="filters.salary_range" :disabled="!!filters.ai_q">
            <option value="">薪资</option>
            <option v-for="r in salaryRanges" :value="r.label">
              {{ r.label }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <!-- 主体：左右分栏布局 -->
    <div class="main-container">
      <!-- 左侧：职位列表 -->
      <div class="job-list-panel">
        <div v-if="isAiLoading" class="ai-loading-state">
          <div class="ai-scanner"></div>
          <div class="ai-text">
            <span class="icon">🧠</span>
            <p>正在理解您的求职意图...</p>
            <small>由大模型进行深度语义树解析与匹配</small>
          </div>
        </div>
        <div v-else-if="loading" class="loading-state">
          <div class="spinner"></div>
          加载中...
        </div>
        <div v-else-if="jobs.length === 0" class="empty-state">
          未匹配到符合您要求的职位
        </div>

        <div v-else class="job-cards-wrapper">
          <div
            class="job-card-item"
            v-for="job in jobs"
            :key="job.id"
            :class="{ active: selectedJob?.id === job.id }"
            @click="selectJob(job)"
          >
            <div class="card-top">
              <span class="job-card-title">{{ job.title }}</span>
              <span class="job-card-salary">{{
                job.salary_desc || `${job.salary_min}-${job.salary_max}K`
              }}</span>
            </div>
            <div class="card-mid">
              <span class="tag-item" v-if="job.area_district">{{
                job.area_district
              }}</span>
              <span class="tag-item">{{ job.experience }}</span>
              <span class="tag-item">{{ job.education }}</span>
            </div>
            <div class="card-bot">
              <div class="card-company">
                <img
                  v-if="job.company?.logo"
                  :src="job.company.logo"
                  class="mini-logo"
                />
                <span>{{ job.company?.name }}</span>
              </div>
            </div>
          </div>

          <!-- 分页控件 (放在列表底部) -->
          <div class="pagination-mini" v-if="total > 0">
            <button
              class="btn-outline small"
              :disabled="currentPage === 1"
              @click="handlePageChange(currentPage - 1)"
            >
              &lt;
            </button>
            <span>{{ currentPage }}/{{ Math.ceil(total / pageSize) }}</span>
            <button
              class="btn-outline small"
              :disabled="currentPage >= Math.ceil(total / pageSize)"
              @click="handlePageChange(currentPage + 1)"
            >
              &gt;
            </button>
          </div>
        </div>
      </div>

      <!-- 右侧：职位详情 -->
      <div class="job-detail-panel">
        <div v-if="selectedJob" class="detail-content">
          <div class="detail-header">
            <div class="header-main">
              <h1>
                {{ selectedJob.title }}
                <span class="salary-highlight">{{
                  selectedJob.salary_desc ||
                  `${selectedJob.salary_min}-${selectedJob.salary_max}K`
                }}</span>
              </h1>
              <div class="job-badges">
                <span
                  ><i class="icon-loc">📍</i> {{ selectedJob.location }}
                  {{ selectedJob.area_district }}</span
                >
                <span
                  ><i class="icon-exp">💼</i> {{ selectedJob.experience }}</span
                >
                <span
                  ><i class="icon-edu">🎓</i> {{ selectedJob.education }}</span
                >
              </div>
            </div>
            <div class="header-actions">
              <button
                class="favorite-btn"
                @click="toggleFavorite"
                :class="{ 'is-active': isFavorite }"
              >
                {{ isFavorite ? "❤️ 已收藏" : "🤍 收藏" }}
              </button>
              <a
                :href="selectedJob.source_url"
                target="_blank"
                class="apply-btn"
                >立即沟通</a
              >
            </div>
          </div>

          <div class="detail-section hr-section" v-if="selectedJob.boss_name">
            <img
              :src="selectedJob.boss_avatar"
              class="hr-avatar-lg"
              @error="handleImageError"
            />
            <div>
              <div class="hr-name-lg">{{ selectedJob.boss_name }}</div>
              <div class="hr-title-lg">
                {{ selectedJob.boss_title }} · {{ selectedJob.company?.name }}
              </div>
            </div>
          </div>

          <div class="detail-section">
            <h3>职位描述</h3>
            <div class="text-content">
              <div class="skills-row">
                <span
                  class="skill-pill"
                  v-for="tag in parseTags(selectedJob.tags)"
                  :key="tag"
                  >{{ tag }}</span
                >
              </div>
              <p class="description-text">
                {{ selectedJob.description || "暂无职位描述" }}
              </p>
              <h3>职位要求</h3>
              <p class="description-text">
                {{ selectedJob.requirements || "暂无职位要求" }}
              </p>
            </div>
          </div>

          <div class="detail-section">
            <h3>公司信息</h3>
            <div
              class="company-detail-card"
              @click="router.push(`/companies/${selectedJob.company?.id}`)"
            >
              <img
                v-if="selectedJob.company?.logo"
                :src="selectedJob.company.logo"
                class="company-logo-lg"
              />
              <div class="company-info-lg">
                <h4>{{ selectedJob.company?.name }}</h4>
                <p>
                  {{ selectedJob.company?.industry }} ·
                  {{ selectedJob.company?.scale }} ·
                  {{ selectedJob.company?.stage }}
                </p>
              </div>
              <div class="arrow">&gt;</div>
            </div>
          </div>

          <div class="detail-section" v-if="selectedJob.location">
            <h3>工作地点</h3>
            <p>
              {{ selectedJob.location }} {{ selectedJob.area_district }}
              {{ selectedJob.business_district }}
            </p>
          </div>
        </div>

        <div v-else class="empty-detail">
          <p>👈 点击左侧职位查看详情</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.market-view {
  height: calc(100vh - 64px); /* 减去导航栏高度 */
  display: flex;
  flex-direction: column;
  background: var(--color-background);
  overflow: hidden;
  animation: fadeIn var(--transition-slow);
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.page-header {
  background: var(--color-glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--color-border);
  padding: 1.25rem 2rem;
  z-index: 10;
}

.header-content {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1.5rem;
  flex-wrap: wrap;
}

.search-section {
  display: flex;
  flex: 1;
  max-width: 650px;
  gap: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.search-section.ai-active {
  max-width: 800px;
}

.search-bar {
  display: flex;
  flex: 1;
  position: relative;
  align-items: center;
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  padding: 0.3rem 0.5rem 0.3rem 1.2rem;
  transition: all var(--transition-normal);
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.02);
}
.search-bar:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
  background: var(--color-background);
}
.search-bar.ai-mode {
  border-color: rgba(139, 92, 246, 0.5);
  background: linear-gradient(
    to right,
    rgba(139, 92, 246, 0.05),
    rgba(56, 189, 248, 0.05)
  );
}
.search-bar.ai-mode:focus-within {
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15);
}

.search-icon {
  font-size: 1.1rem;
  color: var(--color-text-mute);
  margin-right: 0.5rem;
}
.ai-sparkle {
  color: #8b5cf6;
  animation: sparkle 2s infinite;
}
@keyframes sparkle {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.5;
    transform: scale(0.8);
  }
}

.search-bar input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 1rem;
  color: var(--color-text);
  padding: 0.5rem 0;
}
.search-bar input::placeholder {
  color: var(--color-text-mute);
}
.ai-input::placeholder {
  color: #8b5cf6;
  opacity: 0.7;
  font-weight: 500;
}

/* AI Toggle Switch */
.ai-toggle {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 12px;
  border-left: 1px solid var(--color-border);
  margin-left: 4px;
  border-radius: 0 20px 20px 0;
}
.toggle-track {
  width: 32px;
  height: 18px;
  background: var(--color-border);
  border-radius: 20px;
  position: relative;
  transition: all 0.3s;
  display: inline-block;
}
.toggle-track.active {
  background: linear-gradient(135deg, #8b5cf6, #38bdf8);
}
.toggle-thumb {
  width: 14px;
  height: 14px;
  background: white;
  border-radius: 50%;
  position: absolute;
  top: 2px;
  left: 2px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}
.toggle-track.active .toggle-thumb {
  left: 16px;
}
.toggle-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--color-text-mute);
}
.active + .toggle-label {
  background: linear-gradient(135deg, #8b5cf6 0%, #38bdf8 100%);
  -webkit-background-clip: text;
  color: transparent;
}

.primary-search-btn {
  background: var(--color-text);
  color: var(--color-background);
  border: none;
  padding: 0 2.2rem;
  border-radius: var(--radius-full);
  cursor: pointer;
  font-weight: 600;
  font-size: 1rem;
  transition: all cubic-bezier(0.4, 0, 0.2, 1) 0.3s;
  letter-spacing: 1px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}
.primary-search-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.15);
}
.primary-search-btn.ai-btn {
  background: linear-gradient(135deg, #8b5cf6 0%, #38bdf8 100%);
  color: white;
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3);
}
.primary-search-btn.ai-btn:hover {
  box-shadow: 0 6px 20px rgba(139, 92, 246, 0.5);
}

.filters-bar {
  display: flex;
  gap: 0.8rem;
  flex-wrap: wrap;
}
.filters-bar select {
  appearance: none;
  padding: 0.6rem 2.5rem 0.6rem 1.2rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-full);
  background: var(--color-background-soft);
  color: var(--color-text);
  cursor: pointer;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 1rem center;
  background-size: 1em;
  transition: all var(--transition-normal);
}
.filters-bar select:focus {
  outline: none;
  border-color: var(--color-primary);
}

/* 主容器 */
.main-container {
  flex: 1;
  display: flex;
  max-width: 1400px;
  margin: 1.5rem auto;
  width: 100%;
  gap: 1.5rem;
  padding: 0 1rem;
  overflow: hidden;
}

/* 左侧列表 */
.job-list-panel {
  width: 400px;
  flex-shrink: 0;
  background: var(--color-glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
}

.job-card-item {
  padding: 1.25rem;
  border-bottom: 1px solid var(--color-border);
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  background: transparent;
  overflow: hidden;
}

.job-card-item::after {
  /* Hover highlight effect */
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.03),
    transparent
  );
  transform: translateX(-100%);
  transition: transform 0.6s ease;
  pointer-events: none;
}

.job-card-item:hover {
  background: var(--color-background-soft);
  padding-left: 1.75rem; /* Slide effect */
}
.job-card-item:hover::after {
  transform: translateX(100%);
}
.job-card-item.active {
  background: rgba(14, 165, 233, 0.08);
}
.job-card-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
  background: var(--color-primary);
  border-radius: 0 4px 4px 0;
}

.card-top {
  display: flex;
  justify-content: space-between;
  margin-bottom: 0.6rem;
  align-items: start;
}
.job-card-title {
  font-weight: 600;
  font-size: 1.05rem;
  color: var(--color-text);
  max-width: 65%;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.job-card-salary {
  color: #f43f5e;
  font-weight: bold;
  font-size: 1.1rem;
}

.card-mid {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}
.tag-item {
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  color: var(--color-text-mute);
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: var(--radius-full);
}

.card-bot {
  display: flex;
  align-items: center;
}
.card-company {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.85rem;
  color: var(--color-text-mute);
}
.mini-logo {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-sm);
  object-fit: cover;
}

/* 分页控件 */
.pagination-mini {
  padding: 1.5rem 1rem;
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 1rem;
  border-top: 1px solid var(--color-border);
}
.pagination-mini button {
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  color: var(--color-text);
  width: 36px;
  height: 36px;
  border-radius: 50%;
  cursor: pointer;
  transition: all 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pagination-mini button:not(:disabled):hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  background: rgba(14, 165, 233, 0.1);
}
.pagination-mini button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 右侧详情 */
.job-detail-panel {
  flex: 1;
  background: var(--color-glass-bg);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  overflow-y: auto;
  padding: 3rem;
  position: relative;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
}

.detail-header {
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 2rem;
  margin-bottom: 2rem;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-main h1 {
  margin: 0 0 1rem 0;
  font-size: 2rem;
  color: var(--color-text);
  font-weight: 700;
}
.salary-highlight {
  color: #f43f5e;
  margin-left: 1rem;
  font-size: 1.8rem;
}
.job-badges {
  display: flex;
  gap: 1.5rem;
  color: var(--color-text-mute);
  font-size: 1rem;
}

.apply-btn {
  background: linear-gradient(135deg, var(--color-primary) 0%, #818cf8 100%);
  color: white;
  padding: 0.8rem 2.5rem;
  border-radius: var(--radius-huge);
  text-decoration: none;
  font-weight: 600;
  font-size: 1.05rem;
  display: inline-block;
  transition: all var(--transition-fast);
  box-shadow: 0 4px 15px rgba(56, 189, 248, 0.3);
}
.apply-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(56, 189, 248, 0.5);
}

.detail-section {
  margin-bottom: 3rem;
}
.detail-section h3 {
  font-size: 1.25rem;
  margin-bottom: 1.5rem;
  color: var(--color-text);
  font-weight: 600;
  display: inline-block;
  position: relative;
}
.detail-section h3::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 40%;
  height: 3px;
  background: var(--color-primary);
  border-radius: 2px;
}

.text-content {
  line-height: 1.8;
  color: var(--color-text-mute);
  white-space: pre-wrap;
  font-size: 1.05rem;
}
.skills-row {
  margin-bottom: 1.5rem;
  display: flex;
  gap: 0.8rem;
  flex-wrap: wrap;
}
.skill-pill {
  background: rgba(14, 165, 233, 0.08);
  border: 1px solid rgba(14, 165, 233, 0.2);
  padding: 6px 16px;
  border-radius: var(--radius-full);
  font-size: 0.95rem;
  color: var(--color-primary);
  transition: all 0.2s;
}
.skill-pill:hover {
  background: rgba(14, 165, 233, 0.15);
  transform: translateY(-1px);
}

.hr-section {
  display: flex;
  align-items: center;
  gap: 1.2rem;
  background: var(--color-background-soft);
  padding: 1.5rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}
.hr-avatar-lg {
  width: 60px;
  height: 60px;
  border-radius: 50%;
  object-fit: cover;
}
.hr-name-lg {
  font-weight: 600;
  font-size: 1.15rem;
  color: var(--color-text);
  margin-bottom: 0.2rem;
}
.hr-title-lg {
  color: var(--color-text-mute);
  font-size: 0.95rem;
}

.company-detail-card {
  display: flex;
  align-items: center;
  gap: 1.5rem;
  border: 1px solid var(--color-border);
  padding: 1.5rem;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  background: var(--color-background-soft);
}
.company-detail-card:hover {
  border-color: rgba(14, 165, 233, 0.4);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.05);
  transform: translateY(-3px);
}
.company-logo-lg {
  width: 70px;
  height: 70px;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  object-fit: contain;
  background: white;
}
.company-info-lg h4 {
  margin: 0 0 0.5rem 0;
  font-size: 1.2rem;
  color: var(--color-text);
}
.company-info-lg p {
  margin: 0;
  color: var(--color-text-mute);
  font-size: 0.95rem;
}
.arrow {
  margin-left: auto;
  color: var(--color-primary);
  font-size: 1.5rem;
  font-weight: 300;
}

.empty-detail,
.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: var(--color-text-mute);
  font-size: 1.2rem;
}

.loading-state {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: var(--color-primary);
  gap: 10px;
  font-weight: 500;
}
.spinner {
  width: 24px;
  height: 24px;
  border: 3px solid rgba(14, 165, 233, 0.3);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: spin 1s infinite linear;
}
@keyframes spin {
  100% {
    transform: rotate(360deg);
  }
}

/* AI 专属加载态 */
.ai-loading-state {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
  height: 100%;
  text-align: center;
  position: relative;
  overflow: hidden;
  padding: 2rem;
}
.ai-scanner {
  width: 80px;
  height: 80px;
  border: 2px solid rgba(129, 140, 248, 0.3);
  border-radius: 50%;
  position: relative;
  margin-bottom: 2rem;
}
.ai-scanner::before {
  content: "";
  position: absolute;
  top: -2px;
  left: -2px;
  right: -2px;
  bottom: -2px;
  border-radius: 50%;
  border: 2px solid transparent;
  border-top-color: #818cf8;
  border-right-color: #38bdf8;
  animation: spin 1.5s linear infinite;
}
.ai-text .icon {
  font-size: 3rem;
  display: block;
  margin-bottom: 1rem;
  animation: pulse 2s infinite;
}
.ai-text p {
  font-size: 1.15rem;
  color: var(--color-heading);
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.ai-text small {
  color: var(--color-text-mute);
  font-size: 0.9rem;
}
@keyframes pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
    filter: drop-shadow(0 0 10px rgba(129, 140, 248, 0.5));
  }
}

/* 禁用状态 */
.filters-bar.disabled {
  opacity: 0.5;
  pointer-events: none;
  filter: grayscale(1);
}

/* 滚动条美化 */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 4px;
}
::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.8);
}

/* 空详情状态 */
.empty-detail {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100%;
  color: var(--color-text-mute);
  font-size: 1.1rem;
  font-weight: 500;
}

/* 详情面板头与操作区域 */
.header-actions {
  display: flex;
  gap: 1rem;
  align-items: center;
}

.favorite-btn {
  padding: 0.6rem 1.2rem;
  font-size: 0.95rem;
  font-weight: 500;
  border-radius: 2rem;
  background: var(--color-background);
  border: 1px solid var(--color-border);
  color: var(--color-text);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.favorite-btn:hover {
  border-color: #ef4444;
  color: #ef4444;
}

.favorite-btn.is-active {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
  border-color: rgba(239, 68, 68, 0.3);
}

@media (max-width: 1024px) {
  .main-container {
    flex-direction: column;
    overflow: visible;
  }
  .job-list-panel {
    width: 100%;
    height: 500px;
  }
  .job-detail-panel {
    min-height: 600px;
    overflow: visible;
    padding: 1.5rem;
  }
  .market-view {
    overflow: auto;
    height: auto;
    min-height: calc(100vh - 64px);
  }
  .header-main h1 {
    font-size: 1.5rem;
  }
}
</style>

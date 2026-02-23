<script setup>
import { ref, onMounted, watch, reactive, computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import api from '../core/api';

const route = useRoute();
const router = useRouter(); // Added router
const jobs = ref([]);
const loading = ref(true);
const total = ref(0);
const selectedJob = ref(null); // 当前选中的职位

// 筛选状态
const filters = reactive({
    location: '', // Now stores City Code (int) or empty string
    experience: '',
    education: '',
    industry: '', // Now stores Industry Code (int) or empty string
    salary_range: '',
    q: route.query.q || ''
});

// 选项配置
const locations = ref([]); // Changed to ref for API data
const experiences = ['应届生', '1年以内', '1-3年', '3-5年', '5-10年', '10年以上'];
const educations = ['大专', '本科', '硕士', '博士', '不限'];
const industryOptions = ref([]);

const salaryRanges = [
    { label: '不限', min: null, max: null },
    { label: '10k以下', min: 0, max: 10 },
    { label: '10k-20k', min: 10, max: 20 },
    { label: '20k-30k', min: 20, max: 30 },
    { label: '30k-50k', min: 30, max: 50 },
    { label: '50k以上', min: 50, max: null }
];

const currentPage = ref(1);
const pageSize = ref(20);

// Data Fetching for Metadata
const fetchMetadata = async () => {
    try {
        const [cityRes, industryRes] = await Promise.all([
            api.get('/cities/level/1'),      // Fetch Level 1 Cities
            api.get('/industries/industries/level/0')   // Fetch Level 1 Industries
        ]);
        locations.value = cityRes.data;
        industryOptions.value = industryRes.data;
    } catch (e) {
        console.error("Failed to fetch metadata", e);
    }
};

const fetchJobs = async () => {
    loading.value = true;
    try {
        const params = {
            page: currentPage.value,
            page_size: pageSize.value,
        };
        
        if (filters.q) params.q = filters.q;

        // Pass Code for Location if selected (filters.location is now bound to code)
        if (filters.location) params.location = filters.location;
        
        if (filters.experience && filters.experience !== '不限') params.experience = filters.experience;
        if (filters.education && filters.education !== '不限') params.education = filters.education;
        
        // Pass Code for Industry if selected
        if (filters.industry) params.industry = filters.industry;

        if (filters.salary_range) {
            const range = salaryRanges.find(r => r.label === filters.salary_range);
            if (range) {
                if (range.min !== null) params.salary_min = range.min;
                if (range.max !== null) params.salary_max = range.max;
            }
        }

        const response = await api.get('/jobs/jobs', { params });
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

const handlePageChange = (page) => {
    currentPage.value = page;
    fetchJobs();
    document.querySelector('.job-list-panel')?.scrollTo({ top: 0, behavior: 'smooth' });
};

const selectJob = (job) => {
    selectedJob.value = job;
};

const parseTags = (tagStr) => {
    if (!tagStr) return [];
    try {
        return JSON.parse(tagStr);
    } catch (e) {
        if (typeof tagStr === 'string') return tagStr.split(',').filter(t => t.trim());
        return [];
    }
};

const handleImageError = (e) => {
    e.target.src = 'https://via.placeholder.com/50';
};

onMounted(async () => {
    await fetchMetadata();
    fetchJobs();
});

watch(filters, () => {
    currentPage.value = 1; // 重置页码
    fetchJobs();
}, { deep: true });

</script>

<template>
  <div class="market-view">
    <!-- 顶部搜索栏 (保持不变) -->
    <div class="page-header">
        <div class="header-content">
            <div class="search-bar">
                <input v-model.lazy="filters.q" placeholder="搜索职位、公司..." @keyup.enter="fetchJobs" />
                <button @click="fetchJobs">搜索</button>
            </div>
            <!-- 简化的筛选栏，放顶部 -->
            <div class="filters-bar">
                <!-- Location Filter: Binds to City Code -->
                <select v-model="filters.location">
                    <option value="">城市</option>
                    <option v-for="l in locations" :key="l.code" :value="l.code">{{l.name}}</option>
                </select>
                
                <!-- Industry Filter: Binds to Industry Code -->
                <select v-model="filters.industry">
                    <option value="">行业</option>
                    <option v-for="i in industryOptions" :key="i.code" :value="i.code">{{i.name}}</option>
                </select>

                <select v-model="filters.experience"><option value="">经验</option><option v-for="e in experiences" :value="e">{{e}}</option></select>
                <select v-model="filters.education"><option value="">学历</option><option v-for="e in educations" :value="e">{{e}}</option></select>
                <select v-model="filters.salary_range"><option value="">薪资</option><option v-for="r in salaryRanges" :value="r.label">{{r.label}}</option></select>
            </div>
        </div>
    </div>

    <!-- 主体：左右分栏布局 -->
    <div class="main-container">
        <!-- 左侧：职位列表 -->
        <div class="job-list-panel">
            <div v-if="loading" class="loading-state"><div class="spinner"></div> 加载中...</div>
            <div v-else-if="jobs.length === 0" class="empty-state">暂无职位</div>
            
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
                        <span class="job-card-salary">{{ job.salary_desc || `${job.salary_min}-${job.salary_max}K` }}</span>
                    </div>
                    <div class="card-mid">
                        <span class="tag-item" v-if="job.area_district">{{ job.area_district }}</span>
                        <span class="tag-item">{{ job.experience }}</span>
                        <span class="tag-item">{{ job.education }}</span>
                    </div>
                    <div class="card-bot">
                        <div class="card-company">
                            <img v-if="job.company?.logo" :src="job.company.logo" class="mini-logo">
                            <span>{{ job.company?.name }}</span>
                        </div>
                    </div>
                </div>

                <!-- 分页控件 (放在列表底部) -->
                <div class="pagination-mini" v-if="total > 0">
                    <button :disabled="currentPage === 1" @click="handlePageChange(currentPage - 1)"> &lt; </button>
                    <span>{{ currentPage }}/{{ Math.ceil(total / pageSize) }}</span>
                    <button :disabled="currentPage >= Math.ceil(total / pageSize)" @click="handlePageChange(currentPage + 1)"> &gt; </button>
                </div>
            </div>
        </div>

        <!-- 右侧：职位详情 -->
        <div class="job-detail-panel">
            <div v-if="selectedJob" class="detail-content">
                <div class="detail-header">
                    <div class="header-main">
                        <h1>{{ selectedJob.title }} <span class="salary-highlight">{{ selectedJob.salary_desc || `${selectedJob.salary_min}-${selectedJob.salary_max}K` }}</span></h1>
                        <div class="job-badges">
                            <span><i class="icon-loc">📍</i> {{ selectedJob.location }} {{ selectedJob.area_district }}</span>
                            <span><i class="icon-exp">💼</i> {{ selectedJob.experience }}</span>
                            <span><i class="icon-edu">🎓</i> {{ selectedJob.education }}</span>
                        </div>
                    </div>
                    <div class="header-actions">
                         <a :href="selectedJob.source_url" target="_blank" class="apply-btn">立即沟通</a>
                    </div>
                </div>

                <div class="detail-section hr-section" v-if="selectedJob.boss_name">
                    <img :src="selectedJob.boss_avatar" class="hr-avatar-lg" @error="handleImageError" />
                    <div>
                        <div class="hr-name-lg">{{ selectedJob.boss_name }}</div>
                        <div class="hr-title-lg">{{ selectedJob.boss_title }} · {{ selectedJob.company?.name }}</div>
                    </div>
                </div>

                <div class="detail-section">
                    <h3>职位描述</h3>
                    <div class="text-content">
                        <div class="skills-row">
                            <span class="skill-pill" v-for="tag in parseTags(selectedJob.tags)" :key="tag">{{ tag }}</span>
                        </div>
                        <p class="description-text">{{ selectedJob.description || '暂无职位描述' }}</p>
                         <h3>职位要求</h3>
                        <p class="description-text">{{ selectedJob.requirements || '暂无职位要求' }}</p>
                    </div>
                </div>

                <div class="detail-section">
                    <h3>公司信息</h3>
                    <div class="company-detail-card" @click="router.push(`/companies/${selectedJob.company?.id}`)">
                        <img v-if="selectedJob.company?.logo" :src="selectedJob.company.logo" class="company-logo-lg">
                        <div class="company-info-lg">
                            <h4>{{ selectedJob.company?.name }}</h4>
                            <p>{{ selectedJob.company?.industry }} · {{ selectedJob.company?.scale }} · {{ selectedJob.company?.stage }}</p>
                        </div>
                        <div class="arrow"> &gt; </div>
                    </div>
                </div>
                
                 <div class="detail-section" v-if="selectedJob.location">
                    <h3>工作地点</h3>
                    <p>{{ selectedJob.location }} {{ selectedJob.area_district }} {{ selectedJob.business_district }}</p>
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
    background: #f6f6f8;
    overflow: hidden;
}

.page-header {
    background: white;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    padding: 1rem 2rem;
    z-index: 10;
}

.header-content {
    max-width: 1200px;
    margin: 0 auto;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.search-bar { display: flex; gap: 0.5rem; }
.search-bar input {
    padding: 0.5rem 1rem;
    border: 2px solid var(--color-primary);
    border-radius: 4px 0 0 4px;
    width: 300px;
    outline: none;
}
.search-bar button {
    background: var(--color-primary);
    color: white;
    border: none;
    padding: 0 1.5rem;
    border-radius: 0 4px 4px 0;
    cursor: pointer;
    font-weight: bold;
}

.filters-bar { display: flex; gap: 0.5rem; }
.filters-bar select {
    padding: 0.4rem;
    border: 1px solid #ddd;
    border-radius: 4px;
    background: #fff;
    min-width: 80px;
}

/* 主容器：固定高度，不随页面滚动 */
.main-container {
    flex: 1;
    display: flex;
    max-width: 1200px;
    margin: 1rem auto;
    width: 100%;
    gap: 1rem;
    padding: 0 1rem;
    overflow: hidden; /* 防止主容器滚动 */
}

/* 左侧列表：独立滚动 */
.job-list-panel {
    width: 380px;
    flex-shrink: 0;
    background: white;
    border-radius: 8px;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
}

.job-cards-wrapper {
    flex: 1;
}

.job-card-item {
    padding: 1rem;
    border-bottom: 1px solid #eee;
    cursor: pointer;
    transition: all 0.2s;
}

.job-card-item:hover { background: #fbfbfb; }
.job-card-item.active { background: #e6f7ff; border-left: 3px solid var(--color-primary); }

.card-top { display: flex; justify-content: space-between; margin-bottom: 0.5rem; }
.job-card-title { font-weight: 600; font-size: 1rem; color: #333; max-width: 70%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.job-card-salary { color: var(--color-accent); font-weight: bold; }

.card-mid { display: flex; gap: 0.5rem; margin-bottom: 0.8rem; flex-wrap: wrap; }
.tag-item { background: #f4f4f5; color: #666; font-size: 0.75rem; padding: 2px 6px; border-radius: 2px; }

.card-bot { display: flex; align-items: center; }
.card-company { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: #666; }
.mini-logo { width: 20px; height: 20px; border-radius: 4px; }

/* 右侧详情：独立滚动 */
.job-detail-panel {
    flex: 1;
    background: white;
    border-radius: 8px;
    overflow-y: auto;
    padding: 2rem;
    position: relative;
}

.detail-header {
    border-bottom: 1px solid #eee;
    padding-bottom: 1.5rem;
    margin-bottom: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}

.header-main h1 { margin: 0 0 0.5rem 0; font-size: 1.8rem; color: #333; }
.salary-highlight { color: var(--color-accent); margin-left: 1rem; font-size: 1.5rem; }
.job-badges { display: flex; gap: 1.5rem; color: #444; font-size: 1rem; }

.apply-btn {
    background: var(--color-primary);
    color: white;
    padding: 0.8rem 2rem;
    border-radius: 4px;
    text-decoration: none;
    font-weight: bold;
    display: inline-block;
}
.apply-btn:hover { opacity: 0.9; }

.detail-section { margin-bottom: 2rem; }
.detail-section h3 { font-size: 1.1rem; border-left: 4px solid var(--color-primary); padding-left: 0.8rem; margin-bottom: 1rem; color: #222; font-weight: 600; }

.text-content { line-height: 1.8; color: #444; white-space: pre-wrap; }
.skills-row { margin-bottom: 1rem; display: flex; gap: 0.5rem; flex-wrap: wrap; }
.skill-pill { border: 1px solid #ddd; padding: 4px 12px; border-radius: 20px; font-size: 0.9rem; color: #555; }

.hr-section { display: flex; align-items: center; gap: 1rem; background: #f9f9fa; padding: 1rem; border-radius: 8px; }
.hr-avatar-lg { width: 50px; height: 50px; border-radius: 50%; }
.hr-name-lg { font-weight: bold; margin-bottom: 0.2rem; }
.hr-title-lg { color: #888; font-size: 0.9rem; }

.company-detail-card {
    display: flex;
    align-items: center;
    gap: 1rem;
    border: 1px solid #eee;
    padding: 1rem;
    border-radius: 8px;
    cursor: pointer;
    transition: 0.2s;
}
.company-detail-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.05); }
.company-logo-lg { width: 60px; height: 60px; border-radius: 8px; border: 1px solid #f0f0f0; }
.company-info-lg h4 { margin: 0 0 0.4rem 0; }
.company-info-lg p { margin: 0; color: #888; font-size: 0.9rem; }
.arrow { margin-left: auto; color: #ccc; }

.empty-detail {
    display: flex;
    justify-content: center;
    align-items: center;
    height: 100%;
    color: #ccc;
    font-size: 1.2rem;
}

.list-footer {
    padding: 1rem;
    text-align: center;
    color: #999;
    font-size: 0.85rem;
}
.mini-loading { color: var(--color-primary); }

/* 滚动条美化 */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #f1f1f1; }
::-webkit-scrollbar-thumb { background: #ccc; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #bbb; }
</style>

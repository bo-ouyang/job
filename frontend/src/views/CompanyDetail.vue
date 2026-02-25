<script setup>
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { companyAPI } from '@/api/company';
import { jobAPI } from '@/api/job';

const route = useRoute();
const router = useRouter();
const company = ref(null);
const jobs = ref([]);
const loading = ref(true);

const fetchCompanyData = async () => {
    loading.value = true;
    try {
        const id = route.params.id;
        
        // Parallel requests
        const [compRes, jobsRes] = await Promise.all([
            companyAPI.getCompanyDetail(id),
            jobAPI.getJobs({ company_id: id })
        ]);
        
        company.value = compRes.data;
        jobs.value = jobsRes.data.items;
        
    } catch (e) {
        console.error(e);
    } finally {
        loading.value = false;
    }
};

onMounted(fetchCompanyData);
</script>

<template>
  <div class="company-detail-container">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="!company" class="loading">公司不存在</div>
    <div v-else class="content">
        
        <!-- Header -->
        <div class="company-header">
             <div class="header-left">
                <img :src="company.logo || 'https://via.placeholder.com/100'" class="logo-lg"/>
                <div class="header-info">
                    <h1>{{ company.name }}</h1>
                    <div class="meta">
                        <span>{{ company.industry }}</span>
                        <span class="dot">·</span>
                        <span>{{ company.stage }}</span>
                        <span class="dot">·</span>
                        <span>{{ company.scale }}</span>
                        <span class="dot">·</span>
                        <span>{{ company.location }}</span>
                    </div>
                </div>
             </div>
             <a v-if="company.website" :href="company.website" target="_blank" class="web-btn">访问官网</a>
        </div>

        <div class="main-grid">
            <div class="left-col">
                <div class="section">
                    <h3>公司介绍</h3>
                    <div class="intro-text">{{ company.introduction || company.description }}</div>
                </div>

                <div class="section">
                    <h3>在招职位 ({{ jobs.length }})</h3>
                    <div class="job-list">
                        <div class="job-item" v-for="job in jobs" :key="job.id" @click="router.push(`/jobs/${job.id}`)">
                            <div class="job-main">
                                <div class="job-title">{{ job.title }}</div>
                                <div class="job-salary">{{ job.salary_desc || `${job.salary_min}-${job.salary_max}K` }}</div>
                                <div class="job-req">{{ job.experience }} · {{ job.education }}</div>
                            </div>
                            <button class="job-btn">查看</button>
                        </div>
                         <div v-if="jobs.length === 0" class="no-jobs">暂无在招职位</div>
                    </div>
                </div>
            </div>
            
            <div class="right-col">
                <div class="sidebar-card">
                    <h3>基本信息</h3>
                    <div class="info-item">
                        <label>行业</label>
                        <span>{{ company.industry }}</span>
                    </div>
                    <div class="info-item">
                        <label>规模</label>
                        <span>{{ company.scale }}</span>
                    </div>
                     <div class="info-item">
                        <label>地点</label>
                        <span>{{ company.location }}</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.company-detail-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

.loading {
    text-align: center;
    padding: 4rem;
}

.company-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 2rem;
    border-bottom: 1px solid var(--color-border);
    margin-bottom: 2rem;
}

.header-left {
    display: flex;
    align-items: center;
    gap: 1.5rem;
}

.logo-lg {
    width: 100px;
    height: 100px;
    border-radius: 1rem;
    background: #fff;
    padding: 10px;
    object-fit: contain;
}

.header-info h1 {
    margin: 0 0 0.5rem 0;
    font-size: 2rem;
}

.meta {
    color: var(--color-text-mute);
    font-size: 1.1rem;
}

.dot {
    margin: 0 0.5rem;
}

.web-btn {
    padding: 0.6rem 1.2rem;
    border: 1px solid var(--color-border);
    color: var(--color-text);
    border-radius: 4px;
    text-decoration: none;
    transition: 0.3s;
}

.web-btn:hover {
    border-color: var(--color-primary);
    color: var(--color-primary);
}

.main-grid {
    display: grid;
    grid-template-columns: 1fr 300px;
    gap: 2rem;
}

.section {
    margin-bottom: 3rem;
}

.section h3 {
    margin-bottom: 1.5rem;
    font-size: 1.5rem;
}

.intro-text {
    line-height: 1.8;
    color: var(--color-text);
    white-space: pre-line;
}

.job-list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.job-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1.5rem;
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 0.8rem;
    cursor: pointer;
    transition: 0.3s;
}

.job-item:hover {
    border-color: var(--color-primary);
    transform: translateX(5px);
}

.job-title {
    font-size: 1.1rem;
    font-weight: bold;
    margin-bottom: 0.5rem;
}

.job-salary {
    color: #fca5a5;
    font-weight: bold;
    margin-bottom: 0.3rem;
}

.job-req {
    color: var(--color-text-mute);
    font-size: 0.9rem;
}

.job-btn {
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-text-mute);
    padding: 0.5rem 1rem;
    border-radius: 4px;
}

.sidebar-card {
    background: var(--color-background-soft);
    padding: 1.5rem;
    border-radius: 1rem;
}

.info-item {
    margin-bottom: 1rem;
    display: flex;
    flex-direction: column;
}

.info-item label {
    color: var(--color-text-mute);
    font-size: 0.9rem;
    margin-bottom: 0.3rem;
}
</style>

<script setup>
import { ref, onMounted } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import api from '../core/api';

const route = useRoute();
const router = useRouter();
const job = ref(null);
const loading = ref(true);
const error = ref(null);

const fetchJob = async () => {
    loading.value = true;
    try {
        const res = await api.get(`/jobs/${route.params.id}`);
        job.value = res.data;
    } catch (e) {
        error.value = "职位不存在或已被移除";
        console.error(e);
    } finally {
        loading.value = false;
    }
};

import { useFavoriteStore } from '../stores/favorite';
const favoriteStore = useFavoriteStore();
const isFavorited = ref(false); // Ideally fetch state from backend

const handleFavorite = async () => {
    try {
        await favoriteStore.addFavoriteJob(job.value.id);
        isFavorited.value = true;
        alert('收藏成功');
    } catch (e) {
        // If already favorited or error
        alert('操作提示: ' + (e.response?.data?.detail || '已收藏或操作失败'));
        isFavorited.value = true;
    }
};

const isApplied = ref(false);

const handleApply = async () => {
    try {
        await api.post('/applications/', { job_id: job.value.id });
        alert("投递成功！HR将尽快与您联系。");
        isApplied.value = true;
    } catch (e) {
        alert('投递失败: ' + (e.response?.data?.detail || '未知错误'));
        // Check if already applied
        if (e.response?.data?.detail?.includes("already applied")) {
            isApplied.value = true;
        }
    }
};

const formatDate = (dateStr) => {
    if (!dateStr) return '';
    return new Date(dateStr).toLocaleDateString();
};

onMounted(fetchJob);
</script>

<template>
  <div class="job-detail-container">
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="error" class="error">
        <p>{{ error }}</p>
        <button @click="router.back()">返回</button>
    </div>
    <div v-else class="content">
        <!-- Header Section -->
        <div class="header-card">
            <div class="job-main">
                <div class="job-title-row">
                    <h1>{{ job.title }}</h1>
                    <span class="salary">{{ job.salary_desc || `${job.salary_min}-${job.salary_max}K` }}</span>
                </div>
                <div class="job-props">
                    <span>{{ job.location }}</span>
                    <span class="divider">|</span>
                    <span>{{ job.experience }}</span>
                    <span class="divider">|</span>
                    <span>{{ job.education }}</span>
                </div>
                <div class="tags">
                    <span v-for="tag in JSON.parse(job.tags || '[]')" :key="tag">{{ tag }}</span>
                </div>
                <div class="publish-time">发布于 {{ formatDate(job.updated_at) }}</div>
            </div>
            <div class="action-area">
                <button class="icon-btn" @click="handleFavorite" :class="{ active: isFavorited }">
                    {{ isFavorited ? '❤️ 已收藏' : '🤍 收藏' }}
                </button>
                <button class="apply-btn" @click="handleApply" :disabled="isApplied" :class="{ disabled: isApplied }">
                    {{ isApplied ? '已投递' : '立即沟通' }}
                </button> 
            </div>
        </div>

        <!-- Body Section -->
        <div class="body-grid">
            <div class="left-col">
                <!-- HR Info -->
                <div class="section-card">
                    <h3>职位发布者</h3>
                    <div class="hr-row">
                        <img :src="job.boss_avatar" class="hr-avatar" />
                        <div>
                            <div class="hr-name">{{ job.boss_name }}</div>
                            <div class="hr-title">{{ job.boss_title }}</div>
                        </div>
                    </div>
                </div>

                <!-- Description -->
                <div class="section-card">
                    <h3>职位描述</h3>
                    <div class="desc-text" style="white-space: pre-line;">{{ job.description }}</div>
                    
                    <h3 style="margin-top: 1.5rem">任职要求</h3>
                    <div class="desc-text" style="white-space: pre-line;">{{ job.requirements }}</div>
                </div>
                
                 <!-- Address -->
                 <div class="section-card">
                    <h3>工作地点</h3>
                    <p>{{ job.location }} {{ job.area_district }} {{ job.business_district }}</p>
                </div>
            </div>

            <div class="right-col">
                <!-- Company Info -->
                <div class="section-card company-card">
                    <h3>公司信息</h3>
                    <div class="company-header" @click="router.push(`/companies/${job.company.id}`)">
                         <img :src="job.company.logo || 'https://via.placeholder.com/60'" class="company-logo"/>
                         <div class="company-name">{{ job.company.name }}</div>
                    </div>
                    <div class="company-props">
                        <div class="prop-item">
                            <i class="icon">🏭</i>
                            <span>{{ job.company.industry }}</span>
                        </div>
                        <div class="prop-item">
                            <i class="icon">📈</i>
                            <span>{{ job.company.stage }}</span>
                        </div>
                        <div class="prop-item">
                            <i class="icon">👥</i>
                            <span>{{ job.company.scale }}</span>
                        </div>
                    </div>
                     <div class="company-intro line-clamp-3">
                        {{ job.company.introduction }}
                     </div>
                     <button class="view-company-btn" @click="router.push(`/companies/${job.company.id}`)">查看公司</button>
                </div>
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
.job-detail-container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

.loading, .error {
    text-align: center;
    padding: 4rem;
    color: var(--color-text-mute);
}

.header-card {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 1rem;
    padding: 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
}

.job-title-row {
    display: flex;
    align-items: center;
    gap: 1.5rem;
    margin-bottom: 1rem;
}

.job-title-row h1 {
    font-size: 2rem;
    margin: 0;
}

.salary {
    color: #fca5a5;
    font-size: 1.5rem;
    font-weight: bold;
}

.job-props {
    display: flex;
    align-items: center;
    gap: 0.8rem;
    color: var(--color-text);
    margin-bottom: 1rem;
    font-size: 1.1rem;
}

.divider {
    color: var(--color-border);
}

.tags {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
}

.tags span {
    background: rgba(255, 255, 255, 0.1);
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    font-size: 0.9rem;
}

.publish-time {
    color: var(--color-text-mute);
    font-size: 0.9rem;
}

.apply-btn {
    background: var(--color-primary);
    color: #0f172a;
    border: none;
    padding: 0.8rem 2.5rem;
    border-radius: 0.5rem;
    font-size: 1.1rem;
    font-weight: 600;
    cursor: pointer;
    transition: 0.3s;
}

.apply-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
}

.apply-btn.disabled {
    background: var(--color-border);
    color: var(--color-text-mute);
    cursor: not-allowed;
    transform: none;
    box-shadow: none;
}

.action-area { display: flex; gap: 1rem; }

.icon-btn {
    background: var(--color-background);
    border: 1px solid var(--color-border);
    color: var(--color-text);
    padding: 0.8rem 1.5rem;
    border-radius: 0.5rem;
    font-size: 1rem;
    cursor: pointer;
    transition: 0.3s;
}
.icon-btn:hover { border-color: var(--color-primary); color: var(--color-primary); }
.icon-btn.active { color: #fe2e2e; border-color: #fe2e2e; }

.body-grid {
    display: grid;
    grid-template-columns: 1fr 350px;
    gap: 1.5rem;
}

.section-card {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 1rem;
    padding: 1.5rem;
    margin-bottom: 1.5rem;
}

.section-card h3 {
    border-left: 4px solid var(--color-primary);
    padding-left: 0.8rem;
    margin-bottom: 1.5rem;
    font-size: 1.2rem;
}

.hr-row {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.hr-avatar {
    width: 60px;
    height: 60px;
    border-radius: 50%;
    object-fit: cover;
}

.hr-name {
    font-weight: bold;
    font-size: 1.1rem;
}

.hr-title {
    color: var(--color-text-mute);
}

.desc-text {
    line-height: 1.8;
    color: var(--color-text);
}

.company-header {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.5rem;
    cursor: pointer;
}

.company-logo {
    width: 60px;
    height: 60px;
    border-radius: 8px;
    object-fit: contain;
    background: #fff;
    padding: 4px;
}

.company-name {
    font-weight: bold;
    font-size: 1.1rem;
}

.company-props {
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
    margin-bottom: 1.5rem;
}

.prop-item {
    display: flex;
    gap: 0.8rem;
    color: var(--color-text-mute);
}

.view-company-btn {
    width: 100%;
    padding: 0.6rem;
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-text);
    border-radius: 4px;
    cursor: pointer;
    transition: 0.3s;
}

.view-company-btn:hover {
     border-color: var(--color-primary);
     color: var(--color-primary);
}

.line-clamp-3 {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: 1rem;
    color: var(--color-text-mute);
    font-size: 0.9rem;
}
</style>

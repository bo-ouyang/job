<script setup>
import { ref, onMounted } from 'vue';
import { useFavoriteStore } from '../stores/favorite';
import { useRouter } from 'vue-router';

const store = useFavoriteStore();
const router = useRouter();
const activeTab = ref('jobs'); // 'jobs' | 'companies'

onMounted(() => {
    store.fetchFavoriteJobs();
    store.fetchFollowedCompanies();
});

const handleUnfavoriteJob = async (jobId) => {
    if (confirm('确定取消收藏吗？')) {
        await store.removeFavoriteJob(jobId);
    }
};

const handleUnfollowCompany = async (companyId) => {
    if (confirm('确定取消关注吗？')) {
        await store.removeFollowCompany(companyId);
    }
};
</script>

<template>
    <div class="favorites-view">
        <div class="page-header">
            <h2>我的收藏</h2>
            <div class="tabs">
                <button :class="{ active: activeTab === 'jobs' }" @click="activeTab = 'jobs'">
                    收藏的职位 ({{ store.favoriteJobs.length }})
                </button>
                <button :class="{ active: activeTab === 'companies' }" @click="activeTab = 'companies'">
                    关注的公司 ({{ store.followedCompanies.length }})
                </button>
            </div>
        </div>

        <div v-if="store.isLoading" class="loading">加载中...</div>

        <!-- Jobs List -->
        <div v-else-if="activeTab === 'jobs'" class="list-container">
            <div v-if="store.favoriteJobs.length === 0" class="empty">暂无收藏的职位</div>
            
            <div v-for="fav in store.favoriteJobs" :key="fav.id" class="job-item">
                <!-- Using optional chaining as job might be null if deleted -->
                <div class="job-info" v-if="fav.job">
                    <div class="title-row">
                        <h3>{{ fav.job.title }} <span class="salary">{{ fav.job.salary_desc || `${fav.job.salary_min}-${fav.job.salary_max}K` }}</span></h3>
                        <span class="date">{{ new Date(fav.created_at).toLocaleDateString() }} 收藏</span>
                    </div>
                    <div class="tags">
                        <span>{{ fav.job.experience }}</span> | 
                        <span>{{ fav.job.education }}</span> | 
                        <span>{{ fav.job.location }}</span>
                    </div>
                    <div class="company" v-if="fav.job.company">
                        {{ fav.job.company.name }} · {{ fav.job.company.industry }}
                    </div>
                </div>
                <div class="job-info" v-else>
                    <h3>职位已失效</h3>
                </div>
                
                <div class="actions">
                    <button class="btn-outline" @click="fav.job && router.push(`/jobs/${fav.job.id}`)" :disabled="!fav.job">查看</button>
                    <button class="btn-danger" @click="handleUnfavoriteJob(fav.job_id)">取消收藏</button>
                </div>
            </div>
        </div>

        <!-- Companies List -->
        <div v-else class="list-container">
            <div v-if="store.followedCompanies.length === 0" class="empty">暂无关注的公司</div>

            <div v-for="follow in store.followedCompanies" :key="follow.id" class="company-item">
                <div class="company-info" v-if="follow.company">
                    <img v-if="follow.company.logo" :src="follow.company.logo" class="logo" />
                    <div class="info-text">
                        <h3>{{ follow.company.name }}</h3>
                        <p>{{ follow.company.industry }} | {{ follow.company.scale }}</p>
                    </div>
                </div>
                 <div class="company-info" v-else>
                    <h3>公司已失效</h3>
                </div>

                <div class="actions">
                     <button class="btn-outline" @click="follow.company && router.push(`/companies/${follow.company.id}`)" :disabled="!follow.company">查看</button>
                    <button class="btn-danger" @click="handleUnfollowCompany(follow.company_id)">取消关注</button>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.favorites-view {
    max-width: 1000px;
    margin: 0 auto;
    padding: 2rem;
}

.page-header {
    margin-bottom: 2rem;
}

.tabs {
    display: flex;
    gap: 1rem;
    margin-top: 1rem;
    border-bottom: 1px solid var(--color-border);
}

.tabs button {
    padding: 0.8rem 1.5rem;
    background: none;
    border: none;
    cursor: pointer;
    font-size: 1rem;
    color: var(--color-text-mute);
    border-bottom: 2px solid transparent;
}

.tabs button.active {
    color: var(--color-primary);
    border-bottom-color: var(--color-primary);
    font-weight: 600;
}

.list-container {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.job-item, .company-item {
    background: var(--color-background-soft);
    padding: 1.5rem;
    border-radius: 8px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.job-info {
    flex: 1;
}

.title-row {
    display: flex;
    align-items: baseline;
    gap: 1rem;
    margin-bottom: 0.5rem;
}
.title-row h3 { margin: 0; font-size: 1.2rem; display: flex; align-items: center; gap: 10px;}
.salary { color: var(--color-accent); font-weight: bold; font-size: 1.1rem; }
.date { font-size: 0.8rem; color: #999; margin-left: auto; }

.tags { color: var(--color-text-mute); font-size: 0.9rem; margin-bottom: 0.5rem; }
.company { color: var(--color-heading); font-weight: 500; font-size: 0.9rem; }

.company-info { display: flex; align-items: center; gap: 1rem; }
.logo { width: 50px; height: 50px; border-radius: 8px; object-fit: cover; background: #fff;}
.info-text h3 { margin: 0 0 5px 0; font-size: 1.1rem;}
.info-text p { margin: 0; color: var(--color-text-mute); font-size: 0.9rem; }

.actions { display: flex; gap: 0.8rem; }
button { padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-size: 0.9rem; }
.btn-outline { background: white; border: 1px solid var(--color-border); color: var(--color-text); }
.btn-danger { background: #fee2e2; border: 1px solid #fecaca; color: #dc2626; }
.btn-danger:hover { background: #fecaca; }

.empty { text-align: center; padding: 3rem; color: #999; }
</style>

<script setup>
import { ref, onMounted } from 'vue';
import api from '../core/api';

const applications = ref([]);
const loading = ref(true);

const fetchApplications = async () => {
    try {
        const res = await api.get('/applications/');
        applications.value = res.data;
    } catch (e) {
        console.error(e);
    } finally {
        loading.value = false;
    }
};

const formatDate = (dateStr) => {
    return new Date(dateStr).toLocaleString();
};

const getStatusLabel = (status) => {
    const map = {
        'applied': '已投递',
        'viewed': '被查看',
        'communicating': '沟通中',
        'interview': '面试',
        'offer': '录用',
        'rejected': '不合适'
    };
    return map[status] || status;
};

const getStatusClass = (status) => {
    if (status === 'applied') return 'status-gray';
    if (status === 'viewed') return 'status-blue';
    if (status === 'communicating') return 'status-info';
    if (status === 'interview') return 'status-warning';
    if (status === 'offer') return 'status-success';
    if (status === 'rejected') return 'status-danger';
    return '';
};

onMounted(fetchApplications);
</script>

<template>
    <div class="app-container">
        <h1>我的投递记录</h1>
        <div v-if="loading" class="loading">加载中...</div>
        <div v-else-if="applications.length === 0" class="empty">
            暂无投递记录
        </div>
        <div v-else class="list">
            <div v-for="app in applications" :key="app.id" class="app-card">
                <div class="job-info">
                    <h3 @click="$router.push(`/jobs/${app.job.id}`)" class="job-link">{{ app.job.title }}</h3>
                    <div class="company">{{ app.job.company_name || '未知公司' }}</div>
                    <div class="salary">{{ app.job.salary_min }}-{{ app.job.salary_max }}</div>
                </div>
                <div class="status-col">
                    <span class="status-tag" :class="getStatusClass(app.status)">
                        {{ getStatusLabel(app.status) }}
                    </span>
                    <div class="date">{{ formatDate(app.created_at) }}</div>
                </div>
            </div>
        </div>
    </div>
</template>

<style scoped>
.app-container {
    max-width: 800px;
    margin: 2rem auto;
    padding: 0 1rem;
}

.empty {
    text-align: center;
    color: var(--color-text-mute);
    padding: 4rem;
}

.list {
    display: flex;
    flex-direction: column;
    gap: 1rem;
}

.app-card {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 8px;
    padding: 1.5rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.job-link {
    cursor: pointer;
    margin: 0 0 0.5rem 0;
    color: var(--color-heading);
}

.job-link:hover {
    color: var(--color-primary);
}

.company {
    color: var(--color-text);
    margin-bottom: 0.3rem;
}

.salary {
    color: #fca5a5;
    font-weight: bold;
}

.status-col {
    text-align: right;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    align-items: flex-end;
}

.status-tag {
    padding: 0.3rem 0.8rem;
    border-radius: 4px;
    font-size: 0.9rem;
    background: var(--color-background);
    border: 1px solid var(--color-border);
}

.status-gray { color: #999; }
.status-blue { color: #60a5fa; border-color: #60a5fa; }
.status-info { color: #38bdf8; border-color: #38bdf8; }
.status-warning { color: #fbbf24; border-color: #fbbf24; }
.status-success { color: #34d399; border-color: #34d399; }
.status-danger { color: #f87171; border-color: #f87171; }

.date {
    font-size: 0.8rem;
    color: var(--color-text-mute);
}
</style>

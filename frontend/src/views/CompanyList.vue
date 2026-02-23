<script setup>
import { ref, onMounted, reactive, watch } from 'vue';
import { useRouter } from 'vue-router';
import api from '../core/api';

const router = useRouter();
const companies = ref([]);
const loading = ref(false);
const total = ref(0);
const currentPage = ref(1);
const totalPages = ref(1);

const filters = reactive({
    keyword: '',
    industry: '',
    location: ''
});

const locations = ['北京', '上海', '广州', '深圳', '杭州', '成都', '武汉', '合肥', '南京', '西安'];
const industryOptions = ref([]);

const fetchIndustries = async () => {
    try {
        const res = await api.get('/industries/industries/level/0');
        industryOptions.value = res.data;
    } catch (e) {
        console.error("Failed to fetch industries", e);
    }
};

const fetchCompanies = async () => {
    loading.value = true;
    try {
        const params = {
            page_size: 20,
            page: currentPage.value,
            q: filters.keyword,
            industry: filters.industry !== '不限' ? filters.industry : '',
            location: filters.location !== '全部' ? filters.location : ''
        };
        const res = await api.get('/companies', { params });
        companies.value = res.data.items;
        total.value = res.data.total;
        totalPages.value = res.data.pages;
    } catch (e) {
        console.error(e);
    } finally {
        loading.value = false;
    }
};

const changePage = (page) => {
    if (page < 1 || page > totalPages.value) return;
    currentPage.value = page;
    fetchCompanies();
};

watch(filters, () => {
    currentPage.value = 1; // Reset to page 1 on filter change
    fetchCompanies();
}, { deep: true });

onMounted(() => {
    fetchIndustries();
    fetchCompanies();
});
</script>

<template>
  <div class="company-view">
    <div class="header">
        <h2>热门招聘企业</h2>
        <div class="search-bar">
            <input v-model.lazy="filters.keyword" placeholder="搜索公司名称、描述..." @keyup.enter="fetchCompanies" />
            <button @click="fetchCompanies">搜索</button>
        </div>
    </div>

    <div class="filters">
         <div class="filter-group">
            <label>城市</label>
            <select v-model="filters.location">
                <option value="">全部</option>
                <option v-for="loc in locations" :key="loc" :value="loc">{{ loc }}</option>
            </select>
        </div>
        <div class="filter-group">
            <label>行业</label>
            <select v-model="filters.industry">
                <option value="">不限</option>
                <option v-for="ind in industryOptions" :key="ind.id" :value="ind.name">{{ ind.name }}</option>
            </select>
        </div>
        <div class="total-count">
            共找到 <span>{{ total }}</span> 家企业
        </div>
    </div>

    <div v-if="loading" style="text-align:center; padding: 2rem;">加载中...</div>
    <div v-else-if="companies.length === 0" style="text-align:center; padding: 4rem; color: #888;">暂无匹配的企业</div>
    
    <div v-else class="company-grid">
        <div class="company-card" v-for="company in companies" :key="company.id" @click="router.push(`/companies/${company.id}`)">
            <div class="card-top">
                <img v-if="company.logo" :src="company.logo" class="logo-img" />
                <div v-else class="logo-placeholder">{{ company.name.substring(0,1) }}</div>
                
                <div class="info">
                    <h3>{{ company.name }}</h3>
                    <p>{{ company.industry }} <span v-if="company.location">· {{ company.location }}</span></p>
                </div>
            </div>
            <div class="card-body">
                <p class="desc line-clamp-2">{{ company.description || '暂无描述' }}</p>
                <div class="tags">
                    <span v-if="company.scale">{{ company.scale }}</span>
                    <span v-if="company.stage">{{ company.stage }}</span>
                </div>
            </div>
            <button class="view-btn">查看在招职位</button>
        </div>
    </div>

    <div class="pagination" v-if="totalPages > 1">
        <button :disabled="currentPage === 1" @click="changePage(currentPage - 1)">上一页</button>
        <span>{{ currentPage }} / {{ totalPages }}</span>
        <button :disabled="currentPage === totalPages" @click="changePage(currentPage + 1)">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.company-view {
    max-width: 1280px;
    margin: 0 auto;
    padding: 2rem;
}

.header {
    margin-bottom: 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.search-bar { display: flex; gap: 0.5rem; }
.search-bar input {
    padding: 0.6rem 1rem;
    border-radius: 4px;
    border: 1px solid var(--color-border);
    background: var(--color-background-soft);
    color: var(--color-text);
    width: 300px;
}
.search-bar button {
    padding: 0.6rem 2rem;
    border-radius: 4px;
    background: var(--color-primary);
    color: white;
    font-weight: 600;
    border: none;
    cursor: pointer;
}

.filters {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    padding: 1.5rem;
    background: var(--color-background-soft);
    border-radius: 8px;
    margin-bottom: 2rem;
    align-items: center;
}

.filter-group { display: flex; align-items: center; gap: 0.8rem; }
.filter-group label { font-weight: 500; color: var(--color-text-mute); }
select {
    padding: 0.4rem 1rem;
    border-radius: 4px;
    border: 1px solid var(--color-border);
    background: var(--color-background);
    color: var(--color-text);
}

.total-count {
    margin-left: auto;
    color: var(--color-text-mute);
    font-size: 0.9rem;
}
.total-count span { color: var(--color-primary); font-weight: bold; }

.company-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 2rem;
}

.company-card {
    background: var(--color-background-soft);
    border: 1px solid var(--color-border);
    border-radius: 1rem;
    padding: 2rem;
    transition: 0.3s;
    display: flex;
    flex-direction: column;
    cursor: pointer;
}

.company-card:hover {
    border-color: var(--color-primary);
    transform: translateY(-5px);
}

.card-top {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1.5rem;
}

.logo-img {
    width: 60px;
    height: 60px;
    border-radius: 0.8rem;
    object-fit: contain;
    background: #fff;
    padding: 4px;
}

.logo-placeholder {
    width: 60px;
    height: 60px;
    background: var(--color-background-mute);
    border-radius: 0.8rem;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.5rem;
    font-weight: bold;
    color: var(--color-heading);
}

.info h3 {
    margin: 0;
    font-size: 1.25rem;
}

.info p {
    color: var(--color-text-mute);
    font-size: 0.9rem;
    margin-top: 0.2rem;
}

.desc {
    color: var(--color-text);
    font-size: 0.95rem;
    margin-bottom: 1.5rem;
    line-height: 1.5;
    flex: 1;
}

.line-clamp-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}

.tags {
    display: flex;
    gap: 0.5rem;
}

.tags span {
    background: rgba(255, 255, 255, 0.05);
    padding: 0.2rem 0.6rem;
    border-radius: 0.3rem;
    font-size: 0.8rem;
    color: var(--color-text-mute);
}

.view-btn {
    margin-top: 1.5rem;
    width: 100%;
    padding: 0.8rem;
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-primary);
    border-radius: 0.5rem;
    font-weight: 500;
    transition: 0.3s;
}

.view-btn:hover {
    background: var(--color-primary);
    color: #0f172a;
    border-color: var(--color-primary);
}

.pagination {
    margin-top: 3rem;
    display: flex;
    justify-content: center;
    gap: 1.5rem;
    align-items: center;
}

.pagination button {
    padding: 0.5rem 1rem;
    border: 1px solid var(--color-border);
    border-radius: 4px;
    background: var(--color-background-soft);
    color: var(--color-text);
    cursor: pointer;
}
.pagination button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
</style>

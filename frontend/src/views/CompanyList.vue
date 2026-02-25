<script setup>
import { ref, onMounted, reactive, watch } from 'vue';
import { useRouter } from 'vue-router';
import { companyAPI } from '@/api/company';
import { commonAPI } from '@/api/common';

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
        const res = await commonAPI.getIndustries(0);
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
        const res = await companyAPI.getCompanies(params);
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
    max-width: 1400px;
    margin: 0 auto;
    padding: 3rem 2rem;
    animation: fadeIn var(--transition-slow);
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}

.header {
    margin-bottom: 3rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 1.5rem;
}

.header h2 {
    font-size: 2.2rem;
    color: var(--color-text);
    margin: 0;
    font-weight: 700;
}

.search-bar { display: flex; position: relative; width: 100%; max-width: 450px; }
.search-bar input {
    flex: 1;
    padding: 0.8rem 1.5rem;
    border-radius: var(--radius-full) 0 0 var(--radius-full);
    border: 1px solid var(--color-border);
    background: rgba(0, 0, 0, 0.05); /* light mode default */
    color: var(--color-text);
    font-size: 0.95rem;
    outline: none;
    transition: all var(--transition-normal);
}
:root[data-theme='dark'] .search-bar input {
    background: rgba(0, 0, 0, 0.3);
}

.search-bar input:focus {
    border-color: var(--color-primary);
    box-shadow: inset 0 0 0 1px var(--color-primary);
}
.search-bar button {
    padding: 0 2.5rem;
    border-radius: 0 var(--radius-full) var(--radius-full) 0;
    background: linear-gradient(135deg, var(--color-primary) 0%, #818cf8 100%);
    color: white;
    font-weight: 600;
    font-size: 1rem;
    border: none;
    cursor: pointer;
    transition: all var(--transition-fast);
}
.search-bar button:hover {
    filter: brightness(1.1);
}

.filters {
    display: flex;
    flex-wrap: wrap;
    gap: 1.5rem;
    padding: 1.5rem 2.5rem;
    background: var(--color-glass-bg);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    border-radius: var(--radius-lg);
    border: 1px solid var(--color-border);
    margin-bottom: 4rem;
    align-items: center;
    box-shadow: 0 4px 20px rgba(0,0,0,0.04);
}

.filter-group { display: flex; align-items: center; gap: 0.8rem; }
.filter-group label { font-weight: 600; color: var(--color-text); font-size: 0.95rem; }
select {
    appearance: none;
    padding: 0.6rem 2.5rem 0.6rem 1.2rem;
    border-radius: var(--radius-full);
    border: 1px solid var(--color-border);
    background: rgba(0, 0, 0, 0.05);
    color: var(--color-text);
    cursor: pointer;
    background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
    background-repeat: no-repeat;
    background-position: right 1rem center;
    background-size: 1em;
    transition: all var(--transition-normal);
}
:root[data-theme='dark'] select { background: rgba(0, 0, 0, 0.3); }
select:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15); }

.total-count {
    margin-left: auto;
    color: var(--color-text-mute);
    font-size: 1rem;
}
.total-count span { color: var(--color-primary); font-weight: bold; font-size: 1.25rem; margin: 0 0.4rem; }

.company-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 2.5rem;
}

.company-card {
    background: var(--color-glass-bg);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 2.5rem 2rem 2rem 2rem;
    transition: all var(--transition-normal);
    display: flex;
    flex-direction: column;
    cursor: pointer;
    position: relative;
    box-shadow: 0 4px 20px rgba(0,0,0,0.03);
}

.company-card::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
    border-radius: inherit; box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02); pointer-events: none;
}

.company-card:hover {
    border-color: rgba(14, 165, 233, 0.3);
    transform: translateY(-6px);
    box-shadow: 0 15px 40px rgba(0,0,0,0.08), 0 0 20px rgba(14, 165, 233, 0.05);
}

.card-top {
    display: flex;
    align-items: center;
    gap: 1.2rem;
    margin-bottom: 1.5rem;
}

.logo-img {
    width: 68px;
    height: 68px;
    border-radius: var(--radius-md);
    object-fit: contain;
    background: white;
    padding: 8px;
    border: 1px solid var(--color-border);
}

.logo-placeholder {
    width: 68px;
    height: 68px;
    background: rgba(14, 165, 233, 0.08);
    border-radius: var(--radius-md);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.8rem;
    font-weight: 800;
    color: var(--color-primary);
    border: 1px solid rgba(14, 165, 233, 0.2);
}

.info h3 { margin: 0 0 0.4rem 0; font-size: 1.3rem; color: var(--color-text); font-weight: 700; }
.info p { color: var(--color-text-mute); font-size: 0.95rem; margin: 0; }

.card-body { flex: 1; display: flex; flex-direction: column; }
.desc { color: var(--color-text-mute); font-size: 1rem; margin-bottom: 2rem; line-height: 1.6; flex: 1; }
.line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

.tags { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 2rem; }
.tags span {
    background: rgba(14, 165, 233, 0.06); border: 1px solid rgba(14, 165, 233, 0.15);
    padding: 6px 14px; border-radius: var(--radius-full); font-size: 0.85rem; color: var(--color-primary);
}

.view-btn {
    width: 100%;
    padding: 0.9rem;
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-text);
    border-radius: var(--radius-full);
    font-weight: 600;
    font-size: 1rem;
    transition: all var(--transition-fast);
    cursor: pointer;
}

.company-card:hover .view-btn {
    background: linear-gradient(135deg, var(--color-primary) 0%, #818cf8 100%);
    color: white;
    border-color: transparent;
    box-shadow: 0 4px 15px rgba(56, 189, 248, 0.3);
}

.pagination {
    margin-top: 4rem;
    display: flex;
    justify-content: center;
    gap: 1.5rem;
    align-items: center;
}

.pagination button {
    padding: 0.8rem 2rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-full);
    background: var(--color-glass-bg);
    backdrop-filter: blur(8px);
    color: var(--color-text);
    cursor: pointer;
    font-weight: 600;
    transition: all var(--transition-fast);
}
.pagination button:not(:disabled):hover {
    border-color: var(--color-primary); color: var(--color-primary); background: rgba(14, 165, 233, 0.05);
}
.pagination button:disabled { opacity: 0.4; cursor: not-allowed; }

@media (max-width: 768px) {
    .header { flex-direction: column; align-items: stretch; }
    .search-bar { max-width: 100%; }
    .filters { flex-direction: column; align-items: stretch; }
    .total-count { margin-left: 0; text-align: center; margin-top: 1rem; }
}
</style>

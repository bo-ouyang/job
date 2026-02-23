<script setup>
import { onMounted, ref, reactive } from 'vue';
import * as echarts from 'echarts';
import api from '../core/api';

const chartContainer = ref(null);
const salaryChartContainer = ref(null);
const industryChartContainer = ref(null);
const loading = ref(false);

// Preset Majors (Hierarchical)
const presets = ref([]);
const categoryOptions = ref([]);
const majorOptions = ref([]);

const selectedCategory = ref('');
const selectedPreset = ref('');
const customKeywords = ref('');
const location = ref('');

// Charts
let skillsChart = null;
let salaryChart = null;
let industryChart = null;

const fetchPresets = async () => {
    try {
        const res = await api.get('/analysis/major/presets');
        // Structure: [{name: 'Category', majors: [...]}, ...]
        presets.value = res.data; 
        categoryOptions.value = res.data.map(c => c.name);
    } catch (e) {
        console.error("Failed to fetch presets", e);
    }
};

const handleCategoryChange = () => {
    selectedPreset.value = '';
    majorOptions.value = [];
    
    if (selectedCategory.value) {
        const category = presets.value.find(c => c.name === selectedCategory.value);
        if (category) {
            majorOptions.value = category.majors.map(m => ({
                name: m.major_name,
                keywords: m.keywords,
                name: m.major_name,
                keywords: m.keywords,
                hot: m.hot_index > 500,
                hotIndex: m.hot_index
            }));
        }
    }
};

const handlePresetChange = () => {
    if (selectedPreset.value) {
        const major = majorOptions.value.find(m => m.name === selectedPreset.value);
        if (major) {
            customKeywords.value = major.keywords;
            fetchAnalysis();
        }
    }
};

const fetchAnalysis = async () => {
    if (!customKeywords.value) return;
    
    loading.value = true;
    try {
        const keywordsList = customKeywords.value.split(/[,，]/).map(k => k.trim()).filter(k => k);
        const payload = {
            keywords: keywordsList,
            location: location.value || null,
            major_name: selectedPreset.value || null // Send selected preset name if any
        };

        const res = await api.post('/analysis/major/analyze', payload);
        updateCharts(res.data);
    } catch (e) {
        console.error("Failed to analyze major", e);
        alert('分析失败，请稍后重试');
    } finally {
        loading.value = false;
    }
};

const updateCharts = (data) => {
    currentAnalysisData.value = data;
    // 1. Skills
    if (skillsChart) {
        const skillsData = data.skills;
        const names = skillsData.map(i => i.name);
        const values = skillsData.map(i => i.value);
        skillsChart.setOption({
            yAxis: { data: names.reverse() },
            series: [{ data: values.reverse() }]
        });
    }

    // 2. Salary
    if (salaryChart) {
        salaryChart.setOption({
            series: [{ data: data.salary }]
        });
    }

    // 3. Industry
    if (industryChart) {
        industryChart.setOption({
            series: [{ data: data.industries }]
        });
    }
};

const initCharts = () => {
    // Skills
    skillsChart = echarts.init(chartContainer.value);
    skillsChart.setOption({
        title: { text: '核心技能需求 TOP 15', left: 'center', textStyle: { color: '#f8fafc' } },
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
        xAxis: { type: 'value', splitLine: { show: false }, axisLabel: { color: '#94a3b8' } },
        yAxis: { type: 'category', data: [], axisLabel: { color: '#94a3b8' } },
        series: [{
            type: 'bar',
            data: [],
            itemStyle: {
                color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
                    { offset: 0, color: '#f472b6' },
                    { offset: 1, color: '#c084fc' }
                ]),
                borderRadius: [0, 4, 4, 0]
            }
        }]
    });

    // Salary
    salaryChart = echarts.init(salaryChartContainer.value);
    salaryChart.setOption({
        title: { text: '薪资分布情况', left: 'center', textStyle: { color: '#f8fafc' } },
        tooltip: { trigger: 'item' },
        legend: { top: 'bottom', textStyle: { color: '#94a3b8' } },
        series: [{
            name: '薪资范围',
            type: 'pie',
            radius: ['40%', '70%'],
            itemStyle: { borderRadius: 10, borderColor: '#1e293b', borderWidth: 2 },
            label: { show: false },
            emphasis: { label: { show: true, fontSize: 18, fontWeight: 'bold' } },
            data: []
        }]
    });

    // Industry
    industryChart = echarts.init(industryChartContainer.value);
    industryChart.setOption({
        title: { text: '热门就业行业', left: 'center', textStyle: { color: '#f8fafc' } },
        tooltip: { trigger: 'item' },
        legend: { top: 'bottom', textStyle: { color: '#94a3b8' } },
        series: [{
            name: '行业',
            type: 'pie',
            radius: '60%',
            itemStyle: { borderColor: '#1e293b', borderWidth: 2 },
            label: { color: '#94a3b8' },
            data: []
        }]
    });

    window.addEventListener('resize', () => {
        skillsChart.resize();
        salaryChart.resize();
        industryChart.resize();
    });
};

// AI Advisor
const currentAnalysisData = ref(null);
const aiAdvice = ref('');
const loadingAI = ref(false);

const fetchAIAdvice = async () => {
    if (!currentAnalysisData.value || !customKeywords.value) return;

    loadingAI.value = true;
    try {
        let topSkills = [];
        if (currentAnalysisData.value && currentAnalysisData.value.skills) {
            topSkills = currentAnalysisData.value.skills.slice(0, 10).map(s => s.name);
        }
        
        // Fallback: Use input keywords if analysis didn't find specific skills
        if (topSkills.length === 0 && customKeywords.value) {
            topSkills = customKeywords.value.split(/[,，\s]+/).slice(0, 5);
        }

        const payload = {
            major_name: selectedPreset.value || customKeywords.value.split(/[,，\s]+/)[0],
            skills: topSkills
        };
        
        console.log("AI Payload:", payload); // Debug log
        
        // AI response can be slow (up to 30-60s), so we override the default 5s timeout
        const res = await api.post('/analysis/ai/advice', payload, { timeout: 60000 });
        aiAdvice.value = res.data;
    } catch (e) {
        console.error("AI Advice failed", e);
        aiAdvice.value = "无法获取建议，请稍后再试。";
    } finally {
        loadingAI.value = false;
    }
};

onMounted(() => {
    fetchPresets();
    initCharts();
});
</script>

<template>
  <div class="major-analysis-view">
    <div class="header">
      <h2>🎓 大学校专业技能分析</h2>
      <p>输入你的专业或关键词，洞察就业前景与技能需求</p>
    </div>

    <div class="control-panel">
        <div class="input-group">
            <label>专业大类</label>
            <select v-model="selectedCategory" @change="handleCategoryChange">
                <option value="">-- 请选择大类 --</option>
                <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
            </select>
        </div>

        <div class="input-group">
            <label>具体专业</label>
            <select v-model="selectedPreset" @change="handlePresetChange" :disabled="!selectedCategory">
                <option value="">-- 请选择专业 --</option>
                <option v-for="p in majorOptions" :key="p.name" :value="p.name">
                    {{ p.name }} {{ p.hot ? '🔥' : '' }} ({{ p.hotIndex }})
                </option>
            </select>
        </div>

        <div class="input-group flex-2">
            <label>分析关键词 (可手动修改，逗号分隔)</label>
            <input v-model="customKeywords" placeholder="例如: Java, Python, 后端" />
        </div>

        <div class="input-group">
            <label>意向城市</label>
            <input v-model="location" placeholder="例如: 上海" />
        </div>

        <div class="action-group">
            <button class="analyze-btn" @click="fetchAnalysis" :disabled="loading">
                <span v-if="loading">分析中...</span>
                <span v-else>开始分析</span>
            </button>
        </div>
    </div>

    <div class="charts-grid">
        <div class="chart-card large" ref="chartContainer"></div>
        <div class="chart-card" ref="salaryChartContainer"></div>
        <div class="chart-card" ref="industryChartContainer"></div>
    </div>

    <!-- AI Advisor Section -->
    <div class="ai-section" v-if="currentAnalysisData">
        <div class="chart-card ai-card">
            <div class="ai-header">
                <h3>🤖 AI 职业发展向导</h3>
                <button v-if="!aiAdvice && !loadingAI" class="ai-btn" @click="fetchAIAdvice">生成职业建议</button>
            </div>
            
            <div v-if="loadingAI" class="ai-loading">
                <span class="loader"></span> 正在分析市场数据与技能图谱...
            </div>
            
            <div v-if="aiAdvice" class="ai-content markdown-body">
                {{ aiAdvice }}
            </div>
        </div>
    </div>
  </div>
</template>

<style scoped>
/* New Styles for AI Section */
.ai-section {
    margin-top: 2rem;
}

.ai-card {
    min-height: 200px;
    background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%);
}

.ai-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    padding-bottom: 1rem;
}

.ai-header h3 {
    color: #38bdf8;
    margin: 0;
}

.ai-btn {
    background: #8b5cf6;
    border: none;
    color: white;
    padding: 0.5rem 1.5rem;
    border-radius: 20px;
    cursor: pointer;
    font-weight: bold;
    transition: all 0.3s;
}

.ai-btn:hover {
    background: #a78bfa;
    transform: scale(1.05);
}

.ai-content {
    white-space: pre-wrap;
    color: #e2e8f0;
    line-height: 1.8;
    font-size: 1.05rem;
}

.ai-loading {
    color: #94a3b8;
    text-align: center;
    padding: 2rem;
    font-style: italic;
}

.major-analysis-view {
    max-width: 1400px;
    margin: 0 auto;
    padding: 2rem;
}

.header {
    text-align: center;
    margin-bottom: 3rem;
}

.header h2 {
    font-size: 2rem;
    background: linear-gradient(to right, #38bdf8, #818cf8);
    -webkit-background-clip: text;
    color: transparent;
    margin-bottom: 0.5rem;
}

.header p {
    color: var(--color-text-mute);
}

.control-panel {
    background: rgba(30, 41, 59, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.1);
    padding: 1.5rem;
    border-radius: 1rem;
    display: flex;
    gap: 1.5rem;
    margin-bottom: 2rem;
    align-items: flex-end;
    flex-wrap: wrap;
}

.input-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex: 1;
    min-width: 200px;
}

.input-group.flex-2 {
    flex: 2;
}

.input-group label {
    font-size: 0.9rem;
    color: #94a3b8;
}

.input-group input, .input-group select {
    background: #0f172a;
    border: 1px solid #334155;
    color: white;
    padding: 0.6rem 1rem;
    border-radius: 0.5rem;
    font-size: 1rem;
    outline: none;
    transition: border-color 0.3s;
}

.input-group input:focus, .input-group select:focus {
    border-color: #38bdf8;
}

.action-group {
    padding-bottom: 2px;
}

.analyze-btn {
    background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
    border: none;
    padding: 0.6rem 2rem;
    border-radius: 0.5rem;
    color: white;
    font-weight: bold;
    font-size: 1rem;
    cursor: pointer;
    transition: transform 0.2s, opacity 0.2s;
    white-space: nowrap;
    height: 42px;
}

.analyze-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(56, 189, 248, 0.3);
}

.analyze-btn:disabled {
    opacity: 0.7;
    cursor: wait;
    transform: none;
}

.charts-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    grid-template-rows: 400px 400px;
    gap: 1.5rem;
}

.chart-card {
    background: #1e293b;
    border-radius: 1rem;
    padding: 1rem;
    border: 1px solid rgba(255, 255, 255, 0.05);
}

.chart-card.large {
    grid-row: 1 / 3;
    height: 100%;
}

@media (max-width: 1024px) {
    .charts-grid {
        grid-template-columns: 1fr;
        grid-template-rows: auto;
    }
    
    .chart-card.large {
        grid-row: auto;
        height: 500px;
    }

    .chart-card {
        height: 400px;
    }
}
</style>

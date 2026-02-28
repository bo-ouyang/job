<script setup>
import { onMounted, ref, reactive } from "vue";
import * as echarts from "echarts";
import { analysisAPI } from '@/api/analysis';

const chartContainer = ref(null);
const salaryChartContainer = ref(null);
const industryChartContainer = ref(null);
const loading = ref(false);

// Preset Majors (Hierarchical)
const presets = ref([]);
const categoryOptions = ref([]);
const majorOptions = ref([]);

const selectedCategory = ref("");
const selectedPreset = ref("");
const customKeywords = ref("");
const location = ref("");

// Charts
let skillsChart = null;
let salaryChart = null;
let industryChart = null;

const fetchPresets = async () => {
  try {
    const res = await analysisAPI.getMajorPresets();
    // Structure: [{name: 'Category', majors: [...]}, ...]
    presets.value = res.data;
    categoryOptions.value = res.data.map((c) => c.name);
  } catch (e) {
    console.error("Failed to fetch presets", e);
  }
};

const handleCategoryChange = () => {
  selectedPreset.value = "";
  majorOptions.value = [];

  if (selectedCategory.value) {
    const category = presets.value.find(
      (c) => c.name === selectedCategory.value,
    );
    if (category) {
      majorOptions.value = category.majors.map((m) => ({
        name: m.major_name,
        keywords: m.keywords,
        name: m.major_name,
        keywords: m.keywords,
        hot: m.hot_index > 500,
        hotIndex: m.hot_index,
      }));
    }
  }
};

const handlePresetChange = () => {
  if (selectedPreset.value) {
    const major = majorOptions.value.find(
      (m) => m.name === selectedPreset.value,
    );
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
    const keywordsList = customKeywords.value
      .split(/[,，]/)
      .map((k) => k.trim())
      .filter((k) => k);
    const payload = {
      keywords: keywordsList,
      location: location.value || null,
      major_name: selectedPreset.value || null, // Send selected preset name if any
    };

    const res = await analysisAPI.analyzeMajor(payload);
    updateCharts(res.data);
  } catch (e) {
    console.error("Failed to analyze major", e);
    alert("分析失败，请稍后重试");
  } finally {
    loading.value = false;
  }
};

const updateCharts = (data) => {
  currentAnalysisData.value = data;
  // 1. Skills
  if (skillsChart) {
    const skillsData = data.skills;
    const names = skillsData.map((i) => i.name);
    const values = skillsData.map((i) => i.value);
    skillsChart.setOption({
      yAxis: { data: names.reverse() },
      series: [{ data: values.reverse() }],
    });
  }

  // 2. Salary
  if (salaryChart) {
    salaryChart.setOption({
      series: [{ data: data.salary }],
    });
  }

  // 3. Industry
  if (industryChart) {
    industryChart.setOption({
      series: [{ data: data.industries }],
    });
  }
};

const initCharts = () => {
  // Skills
  skillsChart = echarts.init(chartContainer.value);
  skillsChart.setOption({
    title: {
      text: "核心技能需求 TOP 15",
      left: "center",
      textStyle: { color: "#f8fafc" },
    },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
    xAxis: {
      type: "value",
      splitLine: { show: false },
      axisLabel: { color: "#94a3b8" },
    },
    yAxis: { type: "category", data: [], axisLabel: { color: "#94a3b8" } },
    series: [
      {
        type: "bar",
        data: [],
        itemStyle: {
          color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
            { offset: 0, color: "#38bdf8" },
            { offset: 1, color: "#8b5cf6" },
          ]),
          borderRadius: [0, 4, 4, 0],
        },
      },
    ],
  });

  // Salary
  salaryChart = echarts.init(salaryChartContainer.value);
  salaryChart.setOption({
    title: {
      text: "薪资分布情况",
      left: "center",
      textStyle: { color: "#f8fafc" },
    },
    tooltip: { trigger: "item" },
    legend: { top: "bottom", textStyle: { color: "#94a3b8" } },
    series: [
      {
        name: "薪资范围",
        type: "pie",
        radius: ["40%", "70%"],
        itemStyle: { borderRadius: 10, borderColor: "#1e293b", borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 18, fontWeight: "bold" } },
        data: [],
      },
    ],
  });

  // Industry
  industryChart = echarts.init(industryChartContainer.value);
  industryChart.setOption({
    title: {
      text: "热门就业行业",
      left: "center",
      textStyle: { color: "#f8fafc" },
    },
    tooltip: { trigger: "item" },
    legend: { top: "bottom", textStyle: { color: "#94a3b8" } },
    series: [
      {
        name: "行业",
        type: "pie",
        radius: ["45%", "70%"],
        itemStyle: {
          borderRadius: 5,
          borderColor: "#1e293b",
          borderWidth: 2,
        },
        label: { color: "#94a3b8", show: false },
        emphasis: { label: { show: true, fontSize: "14", fontWeight: "bold" } },
        data: [],
      },
    ],
  });

  window.addEventListener("resize", () => {
    skillsChart.resize();
    salaryChart.resize();
    industryChart.resize();
  });
};

// AI Advisor
const currentAnalysisData = ref(null);
const aiAdvice = ref("");
const loadingAI = ref(false);

import api from "@/utils/request";
import { pollTaskResult } from "@/utils/pollTask";

const fetchAIAdvice = async () => {
  if (!currentAnalysisData.value || !customKeywords.value) return;

  loadingAI.value = true;
  try {
    let topSkills = [];
    if (currentAnalysisData.value && currentAnalysisData.value.skills) {
      topSkills = currentAnalysisData.value.skills
        .slice(0, 10)
        .map((s) => s.name);
    }

    // Fallback: Use input keywords if analysis didn't find specific skills
    if (topSkills.length === 0 && customKeywords.value) {
      topSkills = customKeywords.value.split(/[,，\s]+/).slice(0, 5);
    }

    const payload = {
      major_name:
        selectedPreset.value || customKeywords.value.split(/[,，\s]+/)[0],
      skills: topSkills,
    };

    console.log("AI Payload:", payload);

    // Step 1: Submit async task
    const res = await api.post("/analysis/ai/advice", payload, {
      timeout: 10000,
    });
    const taskId = res.data?.task_id;
    if (!taskId) {
      // Fallback: old sync response (if backend hasn't updated)
      aiAdvice.value = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      return;
    }

    // Step 2: Poll for result
    const result = await pollTaskResult("/analysis/ai/task", taskId, {
      interval: 2000,
      timeout: 120000,
    });
    aiAdvice.value = result?.advice || result || "未能获取建议";
  } catch (e) {
    console.error("AI Advice failed", e);
    aiAdvice.value = e.message || "无法获取建议，请稍后再试。";
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
          <option v-for="c in categoryOptions" :key="c" :value="c">
            {{ c }}
          </option>
        </select>
      </div>

      <div class="input-group">
        <label>具体专业</label>
        <select
          v-model="selectedPreset"
          @change="handlePresetChange"
          :disabled="!selectedCategory"
        >
          <option value="">-- 请选择专业 --</option>
          <option v-for="p in majorOptions" :key="p.name" :value="p.name">
            {{ p.name }} {{ p.hot ? "🔥" : "" }} ({{ p.hotIndex }})
          </option>
        </select>
      </div>

      <div class="input-group flex-2">
        <label>分析关键词 (可手动修改，逗号分隔)</label>
        <input
          v-model="customKeywords"
          placeholder="例如: Java, Python, 后端"
        />
      </div>

      <div class="input-group">
        <label>意向城市</label>
        <input v-model="location" placeholder="例如: 上海" />
      </div>

      <div class="action-group">
        <button
          class="analyze-btn"
          @click="fetchAnalysis"
          :disabled="loading"
          :class="{ 'is-loading': loading }"
        >
          <span v-if="loading">📡 数据洞察中...</span>
          <span v-else>🔮 生成职业罗盘</span>
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
          <button
            v-if="!aiAdvice && !loadingAI"
            class="ai-btn"
            @click="fetchAIAdvice"
          >
            生成职业建议
          </button>
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
.major-analysis-view {
  max-width: 1440px;
  margin: 0 auto;
  padding: 2rem;
  animation: fadeIn var(--transition-slow);
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.header {
  text-align: center;
  margin-bottom: 3rem;
}

.header h2 {
  font-size: 2.5rem;
  margin-bottom: 0.5rem;
  letter-spacing: -0.02em;
  background: linear-gradient(to right, #38bdf8, #818cf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header p {
  color: var(--color-text-mute);
  font-size: 1.1rem;
}

/* 筛选项控制台 */
.control-panel {
  background: var(--color-glass-bg);
  border: 1px solid rgba(255, 255, 255, 0.05);
  padding: 1.5rem 2rem;
  border-radius: var(--radius-lg);
  display: flex;
  gap: 1.5rem;
  margin-bottom: 3rem;
  align-items: flex-end;
  flex-wrap: wrap;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  flex: 1;
  min-width: 220px;
}

.input-group.flex-2 {
  flex: 2;
}

.input-group label {
  font-size: 0.9rem;
  color: var(--color-text-mute);
  font-weight: 500;
}

.input-group input,
.input-group select {
  appearance: none;
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: var(--color-text);
  padding: 0.75rem 1.25rem;
  border-radius: var(--radius-sm);
  font-size: 0.95rem;
  outline: none;
  transition: all var(--transition-normal);
  backdrop-filter: blur(4px);
}

.input-group select {
  cursor: pointer;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 1rem center;
  background-size: 1em;
  padding-right: 2.5rem;
}

.input-group select option {
  background: #1e293b;
  color: #f8fafc;
}

.input-group input:focus,
.input-group select:focus {
  border-color: rgba(14, 165, 233, 0.5);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
  background: rgba(0, 0, 0, 0.4);
}

.action-group {
  padding-bottom: 2px;
}

.analyze-btn {
  background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
  border: none;
  padding: 0 2.5rem;
  border-radius: var(--radius-sm);
  color: white;
  font-weight: 600;
  font-size: 1.05rem;
  cursor: pointer;
  transition: all var(--transition-fast);
  white-space: nowrap;
  height: 44px;
  box-shadow: 0 4px 15px rgba(56, 189, 248, 0.3);
  position: relative;
  overflow: hidden;
}

.analyze-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(56, 189, 248, 0.5);
  filter: brightness(1.1);
}

.analyze-btn:disabled {
  opacity: 0.8;
  cursor: not-allowed;
}

.analyze-btn.is-loading::after {
  content: "";
  position: absolute;
  top: 0;
  left: -100%;
  width: 50%;
  height: 100%;
  background: linear-gradient(
    90deg,
    transparent,
    rgba(255, 255, 255, 0.2),
    transparent
  );
  animation: loading-sweep 1.5s infinite linear;
}

/* 毛玻璃图表网格 */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  grid-template-rows: 420px 420px;
  gap: 2.5rem;
}

.chart-card {
  position: relative;
  background: var(--color-card-bg);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  border: 1px solid rgba(255, 255, 255, 0.06);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition:
    transform var(--transition-normal),
    box-shadow var(--transition-normal);
  overflow: hidden;
}

.chart-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  border-radius: inherit;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
  pointer-events: none;
}

.chart-card:hover {
  transform: translateY(-4px);
  box-shadow:
    0 15px 50px rgba(0, 0, 0, 0.3),
    0 0 30px rgba(14, 165, 233, 0.05);
  border-color: rgba(14, 165, 233, 0.2);
}

.chart-card.large {
  grid-row: 1 / 3;
  height: 100%;
}

/* AI 指导模块 */
.ai-section {
  margin-top: 3rem;
}

.ai-card {
  min-height: 200px;
  background: linear-gradient(
    145deg,
    hsla(222, 47%, 16%, 0.8) 0%,
    hsla(222, 47%, 11%, 0.9) 100%
  );
  border: 1px solid rgba(139, 92, 246, 0.4); /* Purple tint for AI */
  position: relative;
  padding: 2.5rem;
}
.ai-card::before {
  content: "";
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 2px;
  background: linear-gradient(90deg, #38bdf8, #8b5cf6, #38bdf8);
}

.ai-card:hover {
  box-shadow:
    0 15px 50px rgba(0, 0, 0, 0.4),
    0 0 40px rgba(139, 92, 246, 0.2);
}

.ai-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  padding-bottom: 1.5rem;
}

.ai-header h3 {
  background: linear-gradient(90deg, #c084fc, #38bdf8);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin: 0;
  font-size: 1.5rem;
  letter-spacing: 0.5px;
}

.ai-btn {
  background: linear-gradient(135deg, #8b5cf6, #6366f1);
  border: none;
  color: white;
  padding: 0.6rem 2rem;
  border-radius: var(--radius-huge);
  cursor: pointer;
  font-weight: 600;
  font-size: 0.95rem;
  transition: all var(--transition-fast);
  box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);
}

.ai-btn:hover {
  filter: brightness(1.2);
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(139, 92, 246, 0.6);
}

.ai-content {
  white-space: pre-wrap;
  color: #e2e8f0;
  line-height: 1.8;
  font-size: 1.05rem;
}

.ai-loading {
  color: var(--color-text-mute);
  text-align: center;
  padding: 3rem;
  font-style: italic;
  font-size: 1.1rem;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}

/* 简单的 Spinner 动画 */
.loader {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(139, 92, 246, 0.3);
  border-radius: 50%;
  border-top-color: #8b5cf6;
  animation: spin 1s ease-in-out infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 1024px) {
  .charts-grid {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
  }
  .chart-card.large {
    grid-row: auto;
    height: 550px;
  }
  .chart-card {
    height: 450px;
  }
}
</style>

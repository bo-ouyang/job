<script setup>
import { onMounted, ref, reactive, watch, nextTick } from "vue";
import { useRoute } from "vue-router";
import * as echarts from "echarts";
import { analysisAPI } from '@/api/analysis';
import { commonAPI } from '@/api/common';

const route = useRoute();
const chartContainer = ref(null);
const salaryChartContainer = ref(null);
const loading = ref(false);

const industryOptions = ref([]); // Level 1
const subIndustryOptions = ref([]); // Level 2
const cityOptions = ref([]);

const selectedParentIndustry = ref(""); // Level 1 ID/Name (we use ID for fetching children, but maybe keep object)
// Actually we need to track local state for L1 selection

// Filters
const filters = reactive({
  location: "", // Stores City Code now
  experience: "",
  education: "",
  industry: "", // Stores Industry Code (Level 2)
  q: route.query.q || "",
});

const isInitializing = ref(true); // Flag to prevent redundant fetches during init

// Options
const experiences = [
  "应届生",
  "1年以内",
  "1-3年",
  "3-5年",
  "5-10年",
  "10年以上",
];
const educations = ["大专", "本科", "硕士", "博士", "不限"];

let skillsChart = null;
let salaryChart = null;

const fetchIndustries = async () => {
  try {
    const res = await commonAPI.getIndustries(0);
    industryOptions.value = res.data || [];

    // Default L1
    if (industryOptions.value.length > 0) {
      selectedParentIndustry.value = industryOptions.value[0].code;
      // Fetch L2 based on this default
      await fetchSubIndustries(selectedParentIndustry.value);
    }
  } catch (e) {
    console.error("Failed to fetch industries", e);
  }
};

const fetchSubIndustries = async (parentCode) => {
  if (!parentCode) {
    subIndustryOptions.value = [];
    filters.industry = "";
    return;
  }

  // Find ID from Code
  const parent = industryOptions.value.find((i) => i.code === parentCode);
  const parentId = parent ? parent.code : null;

  if (!parentId) {
    console.warn("Parent Industry ID not found for code:", parentCode);
    return;
  }

  try {
    const res = await commonAPI.getIndustries(parentId);
    subIndustryOptions.value = res.data || [];
    filters.industry = ""; // Default to All (Level 2)
  } catch (e) {
    console.error("Failed to fetch sub-industries", e);
  }
};

const fetchCities = async () => {
  try {
    const res = await commonAPI.getCities(1);
    cityOptions.value = res.data || [];
    // Set default if not set
    if (!filters.location && cityOptions.value.length > 0) {
      filters.location = cityOptions.value[0].code.toString(); // Use Code
    }
  } catch (e) {
    console.error("Failed to fetch cities", e);
  }
};

const onParentIndustryChange = async () => {
  // When user changes L1 manually
  loading.value = true; // Show loading while fetching subs (optional, typically fast)
  filters.industry = ""; // Reset L2 selection
  await fetchSubIndustries(selectedParentIndustry.value);

  // Explicitly trigger fetch because watch(filters) might not trigger if filters.industry remained ""
  fetchData();
  loading.value = false;
};

const fetchData = async () => {
  loading.value = true;
  try {
    const params = { q: filters.q };

    if (filters.location) params.location = filters.location;
    if (filters.experience && filters.experience !== "不限")
      params.experience = filters.experience;
    if (filters.education && filters.education !== "不限")
      params.education = filters.education;

    // Industry Logic:
    // industry = Parent Code
    // industry_2 = Sub Code (if present)

    if (selectedParentIndustry.value) {
      params.industry = selectedParentIndustry.value.toString();
    }

    if (filters.industry) {
      params.industry_2 = filters.industry;
    }

    const res = await analysisAPI.getJobStats(params);
    updateCharts(res.data);
  } catch (e) {
    console.error("Failed to fetch analysis stats", e);
  } finally {
    loading.value = false;
  }
};

const updateCharts = (data) => {
  if (!data) return;

  // 1. Skills Chart
  if (skillsChart) {
    const skillsData = data.skills || [];
    const names = skillsData.map((i) => i.name);
    const values = skillsData.map((i) => i.value);

    skillsChart.setOption({
      yAxis: { data: names.reverse() },
      series: [{ data: values.reverse() }],
    });
  }

  // 2. Salary Chart
  if (salaryChart) {
    salaryChart.setOption({
      series: [{ data: data.salary || [] }],
    });
  }
};

const initSkillsChart = () => {
  skillsChart = echarts.init(chartContainer.value);

  const options = {
    title: {
      text: "热门技能需求 TOP 10",
      left: "center",
      textStyle: { color: "#f8fafc" },
    },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
    },
    grid: {
      left: "3%",
      right: "4%",
      bottom: "3%",
      containLabel: true,
    },
    xAxis: {
      type: "value",
      splitLine: { show: false },
      axisLabel: { color: "#94a3b8" },
    },
    yAxis: {
      type: "category",
      data: [],
      axisLabel: { color: "#94a3b8" },
    },
    series: [
      {
        name: "需求量",
        type: "bar",
        data: [],
        itemStyle: {
          color: new echarts.graphic.LinearGradient(1, 0, 0, 0, [
            { offset: 0, color: "#8b5cf6" },
            { offset: 1, color: "#38bdf8" },
          ]),
          borderRadius: [0, 4, 4, 0],
        },
      },
    ],
  };

  skillsChart.setOption(options);
  window.addEventListener("resize", () => skillsChart.resize());
};

const initSalaryChart = () => {
  salaryChart = echarts.init(salaryChartContainer.value);

  const options = {
    title: {
      text: "薪资分布",
      left: "center",
      textStyle: { color: "#f8fafc" },
    },
    tooltip: {
      trigger: "item",
    },
    legend: {
      top: "bottom",
      textStyle: { color: "#94a3b8" },
    },
    series: [
      {
        name: "薪资范围",
        type: "pie",
        radius: ["40%", "70%"],
        avoidLabelOverlap: false,
        itemStyle: {
          borderRadius: 8,
          borderColor: "#1e293b",
          borderWidth: 2,
        },
        label: { show: false, position: "center" },
        emphasis: {
          label: {
            show: true,
            fontSize: 20,
            fontWeight: "bold",
            color: "#f8fafc",
          },
        },
        labelLine: { show: false },
        data: [],
      },
    ],
  };

  salaryChart.setOption(options);
  window.addEventListener("resize", () => salaryChart.resize());
};

onMounted(async () => {
  initSkillsChart();
  initSalaryChart();

  // Initialization Sequence
  try {
    await Promise.all([fetchCities(), fetchIndustries()]);

    isInitializing.value = false; // Enable watcher
    // Initial fetch
    fetchData();
  } catch (e) {
    console.error("Init failed", e);
    isInitializing.value = false;
  }
});

watch(
  filters,
  () => {
    if (!isInitializing.value) {
      fetchData();
    }
  },
  { deep: true },
);
</script>

<template>
  <div class="analysis-view">
    <div class="header">
      <h2>技能与市场分析</h2>
      <p>基于实时招聘数据生成的分析报告</p>
    </div>

    <!-- Filters -->
    <div class="filters">
      <div class="filter-group">
        <select v-model="filters.location">
          <option value="">全部城市</option>
          <option v-for="city in cityOptions" :key="city.id" :value="city.code">
            {{ city.name }}
          </option>
        </select>
      </div>
      <div class="filter-group">
        <select
          v-model="selectedParentIndustry"
          @change="onParentIndustryChange"
        >
          <option value="">一级行业</option>
          <option
            v-for="ind in industryOptions"
            :key="ind.id"
            :value="ind.code"
          >
            {{ ind.name }}
          </option>
        </select>
      </div>
      <div class="filter-group">
        <select v-model="filters.industry">
          <option value="">二级行业</option>
          <option
            v-for="ind in subIndustryOptions"
            :key="ind.id"
            :value="ind.code"
          >
            {{ ind.name }}
          </option>
        </select>
      </div>
      <div class="filter-group">
        <select v-model="filters.experience">
          <option value="">经验不限</option>
          <option v-for="exp in experiences" :key="exp" :value="exp">
            {{ exp }}
          </option>
        </select>
      </div>
      <div class="filter-group">
        <input
          v-model.lazy="filters.q"
          placeholder="关键词搜索 (如 Java)"
          class="search-input"
          @keyup.enter="fetchData"
        />
      </div>
    </div>

    <div class="charts-grid">
      <div class="chart-card" ref="chartContainer"></div>
      <div class="chart-card" ref="salaryChartContainer"></div>
    </div>
  </div>
</template>

<style scoped>
.analysis-view {
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
  margin-bottom: 3rem;
  text-align: center;
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

/* 筛选项指挥舱控制台风格 */
.filters {
  display: flex;
  justify-content: center;
  gap: 1.25rem;
  margin-bottom: 3rem;
  flex-wrap: wrap;
  background: var(--color-glass-bg);
  padding: 1.5rem;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}

.filter-group {
  position: relative;
}

.filter-group select,
.search-input {
  appearance: none;
  padding: 0.75rem 2.5rem 0.75rem 1.25rem;
  border-radius: var(--radius-sm);
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(0, 0, 0, 0.2);
  color: var(--color-text);
  font-size: 0.95rem;
  transition: all var(--transition-normal);
  min-width: 160px;
  backdrop-filter: blur(4px);
}

.filter-group select:focus,
.search-input:focus {
  outline: none;
  border-color: rgba(14, 165, 233, 0.5);
  box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.15);
  background: rgba(0, 0, 0, 0.4);
}

.filter-group select {
  cursor: pointer;
  background-image: url("data:image/svg+xml;charset=UTF-8,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2394a3b8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3e%3cpolyline points='6 9 12 15 18 9'%3e%3c/polyline%3e%3c/svg%3e");
  background-repeat: no-repeat;
  background-position: right 0.75rem center;
  background-size: 1em;
}

.filter-group select option {
  background: #1e293b;
  color: #f8fafc;
}

/* 玻璃仪表盘卡片 */
.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
  gap: 2.5rem;
}

.chart-card {
  position: relative;
  background: var(--color-card-bg);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-lg);
  height: 480px;
  padding: 1.5rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition:
    transform var(--transition-normal),
    box-shadow var(--transition-normal);
  overflow: hidden;
}

/* 高级折射边缘内发光 */
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

@media (max-width: 768px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }
  .filter-group select,
  .search-input {
    min-width: 100%;
    width: 100%;
  }
}
</style>

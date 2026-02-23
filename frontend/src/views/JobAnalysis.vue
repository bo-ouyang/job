<script setup>
import { onMounted, ref, reactive, watch, nextTick } from "vue";
import { useRoute } from "vue-router";
import * as echarts from "echarts";
import api from "../core/api";

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
    const res = await api.get("/industries/industries/level/0");
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
  const parent = industryOptions.value.find(i => i.code === parentCode);
  const parentId = parent ? parent.code : null;

  if (!parentId) {
      console.warn("Parent Industry ID not found for code:", parentCode);
      return;
  }

  try {
    const res = await api.get(`/industries/industries/parent/${parentId}`);
    subIndustryOptions.value = res.data || [];
    filters.industry = ""; // Default to All (Level 2)
  } catch (e) {
    console.error("Failed to fetch sub-industries", e);
  }
};

const fetchCities = async () => {
  try {
    const res = await api.get("/cities/level/1");
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

    const res = await api.get("/analysis/stats", { params });
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
            { offset: 0, color: "#818cf8" },
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
          borderRadius: 10,
          borderColor: "#1e293b",
          borderWidth: 2,
        },
        label: { show: false, position: "center" },
        emphasis: {
          label: {
            show: true,
            fontSize: 20,
            fontWeight: "bold",
            color: "#fff",
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
          <option v-for="ind in industryOptions" :key="ind.id" :value="ind.code">
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
  max-width: 1280px;
  margin: 0 auto;
  padding: 2rem;
}

.header {
  margin-bottom: 2rem;
  text-align: center;
}

.header p {
  color: var(--color-text-mute);
}

.filters {
  display: flex;
  justify-content: center;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
}

.filter-group select,
.search-input {
  padding: 0.5rem 1rem;
  border-radius: 4px;
  border: 1px solid var(--color-border);
  background: var(--color-background-soft);
  color: var(--color-text);
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(500px, 1fr));
  gap: 2rem;
}

.chart-card {
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  border-radius: 1rem;
  height: 400px;
  padding: 1rem;
}
</style>

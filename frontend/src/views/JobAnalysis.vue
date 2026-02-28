<script setup>
import { onMounted, ref, reactive, watch } from "vue";
import { useRoute } from "vue-router";
import * as echarts from "echarts";
import { analysisAPI } from "@/api/analysis";
import { commonAPI } from "@/api/common";

const route = useRoute();
const chartContainer = ref(null);
const salaryChartContainer = ref(null);
const loading = ref(false);

// 一级行业列表
const industryOptions = ref([]);
// 二级行业列表
const subIndustryOptions = ref([]);
const cityOptions = ref([]);

// 当前选中的一级行业 code
const selectedParentIndustry = ref("");

// 查询筛选条件
const filters = reactive({
  location: "",
  experience: "",
  education: "",
  industry: "",
  q: route.query.q || "",
});

// 初始化阶段避免重复触发查询
const isInitializing = ref(true);

const experiences = ["应届生", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"];
const educations = ["大专", "本科", "硕士", "博士", "不限"];

let skillsChart = null;
let salaryChart = null;

const fetchIndustries = async () => {
  try {
    const res = await commonAPI.getIndustries(0);
    industryOptions.value = res.data || [];

    if (industryOptions.value.length > 0) {
      selectedParentIndustry.value = industryOptions.value[0].code;
      await fetchSubIndustries(selectedParentIndustry.value);
    }
  } catch (e) {
    console.error("获取行业列表失败", e);
  }
};

const fetchSubIndustries = async (parentCode) => {
  if (!parentCode) {
    subIndustryOptions.value = [];
    filters.industry = "";
    return;
  }

  const parent = industryOptions.value.find(
    (i) => String(i.code) === String(parentCode),
  );
  const parentId = parent ? parent.code : null;

  if (!parentId) {
    console.warn("未找到对应的一级行业编码:", parentCode);
    return;
  }

  try {
    const res = await commonAPI.getIndustries(parentId);
    subIndustryOptions.value = res.data || [];
    filters.industry = "";
  } catch (e) {
    console.error("获取二级行业失败", e);
  }
};

const fetchCities = async () => {
  try {
    const res = await commonAPI.getCities(1);
    cityOptions.value = res.data || [];
    if (!filters.location && cityOptions.value.length > 0) {
      filters.location = cityOptions.value[0].code.toString();
    }
  } catch (e) {
    console.error("获取城市列表失败", e);
  }
};

const onParentIndustryChange = async () => {
  loading.value = true;
  filters.industry = "";
  await fetchSubIndustries(selectedParentIndustry.value);
  await fetchData();
  loading.value = false;
};

const fetchData = async () => {
  loading.value = true;
  try {
    const params = { q: filters.q };

    if (filters.location) params.location = filters.location;
    if (filters.experience && filters.experience !== "不限") {
      params.experience = filters.experience;
    }
    if (filters.education && filters.education !== "不限") {
      params.education = filters.education;
    }

    // 参数约定：industry=一级行业，industry_2=二级行业
    if (selectedParentIndustry.value) {
      params.industry = Number(selectedParentIndustry.value);
      const parentOption = industryOptions.value.find(
        (i) => String(i.code) === String(selectedParentIndustry.value),
      );
      if (parentOption?.name) {
        params.industry_name = parentOption.name;
      }
    }

    if (filters.industry) {
      params.industry_2 = Number(filters.industry);
      const subOption = subIndustryOptions.value.find(
        (i) => String(i.code) === String(filters.industry),
      );
      if (subOption?.name) {
        params.industry_2_name = subOption.name;
      }
    }

    const res = await analysisAPI.getJobStats(params);
    updateCharts(res.data);
  } catch (e) {
    console.error("获取分析统计失败", e);
  } finally {
    loading.value = false;
  }
};

const updateCharts = (data) => {
  if (!data) return;

  if (skillsChart) {
    const skillsData = data.skills || [];
    const names = skillsData.map((i) => i.name);
    const values = skillsData.map((i) => i.value);

    skillsChart.setOption({
      yAxis: { data: names.reverse() },
      series: [{ data: values.reverse() }],
    });
  }

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

  try {
    await Promise.all([fetchCities(), fetchIndustries()]);
    isInitializing.value = false;
    await fetchData();
  } catch (e) {
    console.error("初始化分析页面失败", e);
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

    <!-- 筛选条件 -->
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
        <select v-model="selectedParentIndustry" @change="onParentIndustryChange">
          <option value="">一级行业</option>
          <option v-for="ind in industryOptions" :key="ind.id" :value="ind.code">
            {{ ind.name }}
          </option>
        </select>
      </div>

      <div class="filter-group">
        <select v-model="filters.industry">
          <option value="">二级行业</option>
          <option v-for="ind in subIndustryOptions" :key="ind.id" :value="ind.code">
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
          placeholder="关键词搜索（如 Java）"
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

/* 筛选面板样式 */
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

/* 图表网格 */
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

/* 卡片内边框高光 */
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

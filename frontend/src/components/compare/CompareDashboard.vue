<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { analysisAPI } from "@/api/analysis";
import { commonAPI } from "@/api/common";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
]);

const props = defineProps({
  mode: {
    type: String,
    required: true,
    validator: (value) => ["city", "industry"].includes(value),
  },
});

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const cityOptions = ref([]);
const industryOptions = ref([]);
const subIndustryOptions = ref([]);
const compareData = ref(null);

const salaryChartRef = ref(null);
const trendChartRef = ref(null);
const skillsChartRef = ref(null);

let salaryChart = null;
let trendChart = null;
let skillsChart = null;

const form = reactive({
  keyword: "",
  leftValue: "",
  rightValue: "",
  cityCode: "",
  industry: "",
  industry2: "",
  experience: "",
  education: "",
  days: 30,
});

const experienceOptions = ["应届生", "1年以内", "1-3年", "3-5年", "5-10年", "10年以上"];
const educationOptions = ["大专", "本科", "硕士", "博士", "不限"];
const dayOptions = [7, 15, 30, 60, 90];

const pageTitle = computed(() =>
  props.mode === "city" ? "城市薪资对比" : "行业薪资对比",
);
const pageDesc = computed(() =>
  props.mode === "city"
    ? "同一岗位在不同城市的薪资、岗位量和技能结构对比"
    : "同一岗位在不同行业的薪资、岗位量和门槛结构对比",
);
const leftLabel = computed(() => (props.mode === "city" ? "左侧城市" : "左侧行业"));
const rightLabel = computed(() => (props.mode === "city" ? "右侧城市" : "右侧行业"));

const leftOverviewCards = computed(() => buildOverviewCards(compareData.value?.left));
const rightOverviewCards = computed(() => buildOverviewCards(compareData.value?.right));

function buildOverviewCards(side) {
  const overview = side?.overview || {};
  return [
    { label: "样本量", value: formatInteger(overview.sample_size) },
    { label: "平均薪资", value: formatCurrency(overview.salary_avg) },
    { label: "中位薪资", value: formatCurrency(overview.salary_median) },
    { label: "高薪占比", value: formatPercent(overview.high_salary_ratio) },
  ];
}

function formatInteger(value) {
  return Number(value || 0).toLocaleString();
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  if (!amount) return "-";
  if (amount >= 1000) {
    return `${Math.round(amount / 100) / 10}k`;
  }
  return `${amount}`;
}

function formatPercent(value) {
  return `${Math.round(Number(value || 0) * 100)}%`;
}

function getQueryValue(key) {
  const raw = route.query[key];
  return Array.isArray(raw) ? raw[0] : raw;
}

function initFormFromRoute() {
  form.keyword = getQueryValue("keyword") || "";
  form.leftValue = getQueryValue("left") || "";
  form.rightValue = getQueryValue("right") || "";
  form.cityCode = getQueryValue("city_code") || "";
  form.industry = getQueryValue("industry") || "";
  form.industry2 = getQueryValue("industry_2") || "";
  form.experience = getQueryValue("experience") || "";
  form.education = getQueryValue("education") || "";
  form.days = Number(getQueryValue("days") || 30);
}

async function fetchBaseOptions() {
  const tasks = [commonAPI.getCities(1), commonAPI.getIndustries(0)];
  const [cityRes, industryRes] = await Promise.all(tasks);
  cityOptions.value = cityRes.data || [];
  industryOptions.value = industryRes.data || [];

  if (props.mode === "city" && form.industry) {
    await fetchSubIndustries(form.industry);
  }

  if (!form.leftValue || !form.rightValue) {
    if (props.mode === "city" && cityOptions.value.length >= 2) {
      form.leftValue = form.leftValue || String(cityOptions.value[0].code);
      form.rightValue = form.rightValue || String(cityOptions.value[1].code);
    }
    if (props.mode === "industry" && industryOptions.value.length >= 2) {
      form.leftValue = form.leftValue || String(industryOptions.value[0].code);
      form.rightValue = form.rightValue || String(industryOptions.value[1].code);
    }
  }
}

async function fetchSubIndustries(parentCode) {
  if (!parentCode) {
    subIndustryOptions.value = [];
    form.industry2 = "";
    return;
  }
  const res = await commonAPI.getIndustries(Number(parentCode));
  subIndustryOptions.value = res.data || [];
  if (
    form.industry2 &&
    !subIndustryOptions.value.some((item) => String(item.code) === String(form.industry2))
  ) {
    form.industry2 = "";
  }
}

function syncRouteQuery() {
  const query = {
    keyword: form.keyword || undefined,
    left: form.leftValue || undefined,
    right: form.rightValue || undefined,
    experience: form.experience || undefined,
    education: form.education || undefined,
    days: String(form.days || 30),
  };

  if (props.mode === "city") {
    query.industry = form.industry || undefined;
    query.industry_2 = form.industry2 || undefined;
  } else {
    query.city_code = form.cityCode || undefined;
  }

  router.replace({ query });
}

async function fetchCompareData() {
  if (!form.leftValue || !form.rightValue || form.leftValue === form.rightValue) {
    compareData.value = null;
    return;
  }

  loading.value = true;
  try {
    const params = {
      keyword: form.keyword || undefined,
      experience: form.experience || undefined,
      education: form.education || undefined,
      days: form.days || 30,
    };

    let res;
    if (props.mode === "city") {
      params.left_city_code = Number(form.leftValue);
      params.right_city_code = Number(form.rightValue);
      if (form.industry) params.industry = Number(form.industry);
      if (form.industry2) params.industry_2 = Number(form.industry2);
      res = await analysisAPI.getCitySalaryCompare(params);
    } else {
      params.left_industry_code = Number(form.leftValue);
      params.right_industry_code = Number(form.rightValue);
      if (form.cityCode) params.city_code = Number(form.cityCode);
      res = await analysisAPI.getIndustrySalaryCompare(params);
    }

    compareData.value = res.data || null;
    syncRouteQuery();
    await nextTick();
    renderCharts();
  } catch (error) {
    console.error("Failed to fetch compare data", error);
    compareData.value = null;
  } finally {
    loading.value = false;
  }
}

function initCharts() {
  if (salaryChartRef.value && !salaryChart) {
    salaryChart = echarts.init(salaryChartRef.value);
  }
  if (trendChartRef.value && !trendChart) {
    trendChart = echarts.init(trendChartRef.value);
  }
  if (skillsChartRef.value && !skillsChart) {
    skillsChart = echarts.init(skillsChartRef.value);
  }
}

function renderCharts() {
  initCharts();
  renderSalaryChart();
  renderTrendChart();
  renderSkillsChart();
}

function renderSalaryChart() {
  if (!salaryChart || !compareData.value) return;
  const leftBuckets = compareData.value.left?.salary_distribution || [];
  const rightBuckets = compareData.value.right?.salary_distribution || [];
  const labels = leftBuckets.map((item) => item.name);

  salaryChart.setOption({
    title: { text: "薪资分布对比", left: "center", textStyle: { color: "#f8fafc" } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      top: 28,
      textStyle: { color: "#cbd5e1" },
      data: [compareData.value.left.name, compareData.value.right.name],
    },
    grid: { top: 80, left: 50, right: 24, bottom: 36 },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: { color: "#94a3b8" },
      axisLine: { lineStyle: { color: "rgba(148,163,184,0.35)" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,0.12)" } },
    },
    series: [
      {
        name: compareData.value.left.name,
        type: "bar",
        barMaxWidth: 26,
        data: leftBuckets.map((item) => item.value),
        itemStyle: { color: "#38bdf8", borderRadius: [4, 4, 0, 0] },
      },
      {
        name: compareData.value.right.name,
        type: "bar",
        barMaxWidth: 26,
        data: rightBuckets.map((item) => item.value),
        itemStyle: { color: "#818cf8", borderRadius: [4, 4, 0, 0] },
      },
    ],
  });
}

function renderTrendChart() {
  if (!trendChart || !compareData.value) return;
  const leftTrend = compareData.value.left?.trend || [];
  const rightTrend = compareData.value.right?.trend || [];
  const labels = leftTrend.map((item) => item.date);

  trendChart.setOption({
    title: { text: "岗位数量趋势", left: "center", textStyle: { color: "#f8fafc" } },
    tooltip: { trigger: "axis" },
    legend: {
      top: 28,
      textStyle: { color: "#cbd5e1" },
      data: [compareData.value.left.name, compareData.value.right.name],
    },
    grid: { top: 80, left: 50, right: 24, bottom: 36 },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: { color: "#94a3b8" },
      axisLine: { lineStyle: { color: "rgba(148,163,184,0.35)" } },
    },
    yAxis: {
      type: "value",
      axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,0.12)" } },
    },
    series: [
      {
        name: compareData.value.left.name,
        type: "line",
        smooth: true,
        data: leftTrend.map((item) => item.value),
        lineStyle: { color: "#22d3ee", width: 3 },
        itemStyle: { color: "#22d3ee" },
      },
      {
        name: compareData.value.right.name,
        type: "line",
        smooth: true,
        data: rightTrend.map((item) => item.value),
        lineStyle: { color: "#a78bfa", width: 3 },
        itemStyle: { color: "#a78bfa" },
      },
    ],
  });
}

function renderSkillsChart() {
  if (!skillsChart || !compareData.value) return;
  const leftSkills = compareData.value.left?.top_skills || [];
  const rightSkills = compareData.value.right?.top_skills || [];
  const labels = Array.from(
    new Set([...leftSkills, ...rightSkills].map((item) => item.name)),
  ).slice(0, 10);
  const leftMap = new Map(leftSkills.map((item) => [item.name, item.value]));
  const rightMap = new Map(rightSkills.map((item) => [item.name, item.value]));

  skillsChart.setOption({
    title: { text: "热门技能对比", left: "center", textStyle: { color: "#f8fafc" } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: {
      top: 28,
      textStyle: { color: "#cbd5e1" },
      data: [compareData.value.left.name, compareData.value.right.name],
    },
    grid: { top: 80, left: 80, right: 24, bottom: 36 },
    xAxis: {
      type: "value",
      axisLabel: { color: "#94a3b8" },
      splitLine: { lineStyle: { color: "rgba(148,163,184,0.12)" } },
    },
    yAxis: {
      type: "category",
      data: labels.reverse(),
      axisLabel: { color: "#94a3b8" },
      axisLine: { lineStyle: { color: "rgba(148,163,184,0.35)" } },
    },
    series: [
      {
        name: compareData.value.left.name,
        type: "bar",
        data: [...labels].reverse().map((label) => leftMap.get(label) || 0),
        itemStyle: { color: "#0ea5e9", borderRadius: [0, 4, 4, 0] },
      },
      {
        name: compareData.value.right.name,
        type: "bar",
        data: [...labels].reverse().map((label) => rightMap.get(label) || 0),
        itemStyle: { color: "#8b5cf6", borderRadius: [0, 4, 4, 0] },
      },
    ],
  });
}

function resizeCharts() {
  salaryChart?.resize();
  trendChart?.resize();
  skillsChart?.resize();
}

watch(
  () => form.industry,
  async (value) => {
    if (props.mode === "city") {
      await fetchSubIndustries(value);
    }
  },
);

onMounted(async () => {
  initFormFromRoute();
  await fetchBaseOptions();
  await nextTick();
  initCharts();
  await fetchCompareData();
  window.addEventListener("resize", resizeCharts);
});

onUnmounted(() => {
  window.removeEventListener("resize", resizeCharts);
  salaryChart?.dispose();
  trendChart?.dispose();
  skillsChart?.dispose();
  salaryChart = null;
  trendChart = null;
  skillsChart = null;
});
</script>

<template>
  <section class="compare-page">
    <div class="hero">
      <div>
        <p class="eyebrow">Compare</p>
        <h1>{{ pageTitle }}</h1>
        <p class="desc">{{ pageDesc }}</p>
      </div>
      <div v-if="compareData" class="summary-card">
        <span class="summary-label">结论</span>
        <strong>{{ compareData.summary?.insight || "暂无结论" }}</strong>
      </div>
    </div>

    <div class="filters">
      <div class="field wide">
        <label>岗位关键词</label>
        <input v-model.trim="form.keyword" placeholder="例如：Java后端 / 产品经理 / 数据分析" />
      </div>

      <div class="field">
        <label>{{ leftLabel }}</label>
        <select v-model="form.leftValue">
          <option value="">请选择</option>
          <option
            v-for="item in props.mode === 'city' ? cityOptions : industryOptions"
            :key="item.code"
            :value="String(item.code)"
          >
            {{ item.name }}
          </option>
        </select>
      </div>

      <div class="field">
        <label>{{ rightLabel }}</label>
        <select v-model="form.rightValue">
          <option value="">请选择</option>
          <option
            v-for="item in props.mode === 'city' ? cityOptions : industryOptions"
            :key="item.code"
            :value="String(item.code)"
          >
            {{ item.name }}
          </option>
        </select>
      </div>

      <div v-if="props.mode === 'city'" class="field">
        <label>一级行业</label>
        <select v-model="form.industry">
          <option value="">不限</option>
          <option v-for="item in industryOptions" :key="item.code" :value="String(item.code)">
            {{ item.name }}
          </option>
        </select>
      </div>

      <div v-if="props.mode === 'city'" class="field">
        <label>二级行业</label>
        <select v-model="form.industry2">
          <option value="">不限</option>
          <option
            v-for="item in subIndustryOptions"
            :key="item.code"
            :value="String(item.code)"
          >
            {{ item.name }}
          </option>
        </select>
      </div>

      <div v-if="props.mode === 'industry'" class="field">
        <label>城市范围</label>
        <select v-model="form.cityCode">
          <option value="">全部城市</option>
          <option v-for="item in cityOptions" :key="item.code" :value="String(item.code)">
            {{ item.name }}
          </option>
        </select>
      </div>

      <div class="field">
        <label>经验</label>
        <select v-model="form.experience">
          <option value="">不限</option>
          <option v-for="item in experienceOptions" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <div class="field">
        <label>学历</label>
        <select v-model="form.education">
          <option value="">不限</option>
          <option v-for="item in educationOptions" :key="item" :value="item">{{ item }}</option>
        </select>
      </div>

      <div class="field">
        <label>时间范围</label>
        <select v-model.number="form.days">
          <option v-for="item in dayOptions" :key="item" :value="item">最近 {{ item }} 天</option>
        </select>
      </div>

      <div class="actions">
        <button class="primary-btn" :disabled="loading" @click="fetchCompareData">
          {{ loading ? "分析中..." : "开始对比" }}
        </button>
      </div>
    </div>

    <div v-if="compareData" class="overview-grid">
      <section class="side-panel">
        <div class="panel-head">
          <h2>{{ compareData.left.name }}</h2>
          <span>左侧样本</span>
        </div>
        <div class="metric-grid">
          <article v-for="item in leftOverviewCards" :key="item.label" class="metric-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </article>
        </div>
      </section>

      <section class="side-panel">
        <div class="panel-head">
          <h2>{{ compareData.right.name }}</h2>
          <span>右侧样本</span>
        </div>
        <div class="metric-grid">
          <article v-for="item in rightOverviewCards" :key="item.label" class="metric-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </article>
        </div>
      </section>
    </div>

    <div v-if="compareData" class="charts-grid">
      <div ref="salaryChartRef" class="chart-card"></div>
      <div ref="trendChartRef" class="chart-card"></div>
      <div ref="skillsChartRef" class="chart-card full"></div>
    </div>

    <div v-if="compareData" class="dist-grid">
      <section class="dist-card">
        <h3>学历结构</h3>
        <div class="dist-columns">
          <div>
            <strong>{{ compareData.left.name }}</strong>
            <ul>
              <li v-for="item in compareData.left.education_distribution" :key="item.name">
                <span>{{ item.name }}</span>
                <b>{{ item.value }}</b>
              </li>
            </ul>
          </div>
          <div>
            <strong>{{ compareData.right.name }}</strong>
            <ul>
              <li v-for="item in compareData.right.education_distribution" :key="item.name">
                <span>{{ item.name }}</span>
                <b>{{ item.value }}</b>
              </li>
            </ul>
          </div>
        </div>
      </section>

      <section class="dist-card">
        <h3>经验结构</h3>
        <div class="dist-columns">
          <div>
            <strong>{{ compareData.left.name }}</strong>
            <ul>
              <li v-for="item in compareData.left.experience_distribution" :key="item.name">
                <span>{{ item.name }}</span>
                <b>{{ item.value }}</b>
              </li>
            </ul>
          </div>
          <div>
            <strong>{{ compareData.right.name }}</strong>
            <ul>
              <li v-for="item in compareData.right.experience_distribution" :key="item.name">
                <span>{{ item.name }}</span>
                <b>{{ item.value }}</b>
              </li>
            </ul>
          </div>
        </div>
      </section>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <h3>先选择两个{{ props.mode === "city" ? "城市" : "行业" }}再开始对比</h3>
      <p>第一版会重点展示薪资、岗位量与技能差异，适合做求职决策展示。</p>
    </div>
  </section>
</template>

<style scoped>
.compare-page {
  max-width: 1400px;
  margin: 0 auto;
  padding: 2rem;
  color: var(--color-text);
}

.hero {
  display: flex;
  justify-content: space-between;
  gap: 1.5rem;
  align-items: end;
  margin-bottom: 1.5rem;
}

.eyebrow {
  margin: 0 0 0.35rem;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: #67e8f9;
  font-size: 0.75rem;
}

.hero h1 {
  margin: 0;
  font-size: 2.8rem;
  color: #f8fafc;
}

.desc {
  margin: 0.6rem 0 0;
  color: #94a3b8;
  max-width: 620px;
}

.summary-card {
  max-width: 420px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.16), rgba(99, 102, 241, 0.18));
  border: 1px solid rgba(129, 140, 248, 0.2);
  border-radius: 18px;
  padding: 1rem 1.2rem;
}

.summary-label {
  display: block;
  font-size: 0.8rem;
  color: #cbd5e1;
  margin-bottom: 0.4rem;
}

.summary-card strong {
  color: #f8fafc;
  line-height: 1.6;
}

.filters {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
  padding: 1.2rem;
  border-radius: 20px;
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.06);
  margin-bottom: 1.5rem;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 0.45rem;
}

.field.wide {
  grid-column: span 2;
}

.field label {
  font-size: 0.86rem;
  color: #94a3b8;
}

.field input,
.field select {
  height: 42px;
  border-radius: 12px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(15, 23, 42, 0.85);
  color: #f8fafc;
  padding: 0 0.95rem;
  outline: none;
}

.actions {
  display: flex;
  align-items: end;
}

.primary-btn {
  width: 100%;
  height: 42px;
  border: none;
  border-radius: 12px;
  cursor: pointer;
  color: white;
  font-weight: 700;
  background: linear-gradient(135deg, #0ea5e9, #6366f1);
}

.primary-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.side-panel,
.dist-card {
  background: rgba(15, 23, 42, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 20px;
  padding: 1.1rem;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.9rem;
}

.panel-head h2,
.dist-card h3 {
  margin: 0;
  color: #f8fafc;
}

.panel-head span {
  color: #94a3b8;
  font-size: 0.85rem;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.8rem;
}

.metric-card {
  background: rgba(30, 41, 59, 0.7);
  border-radius: 16px;
  padding: 0.95rem 1rem;
}

.metric-card span {
  display: block;
  color: #94a3b8;
  font-size: 0.82rem;
}

.metric-card strong {
  display: block;
  margin-top: 0.35rem;
  color: #f8fafc;
  font-size: 1.3rem;
}

.charts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.chart-card {
  height: 360px;
  background: rgba(15, 23, 42, 0.62);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 20px;
  padding: 0.5rem;
}

.chart-card.full {
  grid-column: 1 / -1;
}

.dist-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.dist-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1.25rem;
  margin-top: 0.9rem;
}

.dist-columns strong {
  display: block;
  margin-bottom: 0.75rem;
  color: #e2e8f0;
}

.dist-columns ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}

.dist-columns li {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  color: #cbd5e1;
}

.empty-state {
  background: rgba(15, 23, 42, 0.62);
  border: 1px dashed rgba(148, 163, 184, 0.25);
  border-radius: 20px;
  padding: 2rem;
  text-align: center;
}

.empty-state h3 {
  margin: 0;
  color: #f8fafc;
}

.empty-state p {
  margin: 0.6rem 0 0;
  color: #94a3b8;
}

@media (max-width: 1024px) {
  .filters,
  .overview-grid,
  .charts-grid,
  .dist-grid,
  .dist-columns {
    grid-template-columns: 1fr;
  }

  .field.wide,
  .chart-card.full {
    grid-column: auto;
  }

  .hero {
    flex-direction: column;
    align-items: stretch;
  }
}

@media (max-width: 768px) {
  .compare-page {
    padding: 1rem;
  }

  .hero h1 {
    font-size: 2.2rem;
  }

  .metric-grid {
    grid-template-columns: 1fr;
  }
}
</style>

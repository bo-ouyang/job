<script setup>
defineOptions({ name: "CareerCompass" });
import {
  ref,
  onMounted,
  onActivated,
  onUnmounted,
  nextTick,
  watch,
} from "vue";
import { useRoute } from "vue-router";
import { analysisAPI } from "../api/analysis";
import { aiAPI } from "../api/ai";
import { useAiTaskStore } from "@/stores/aiTask";
import { ElMessage } from "element-plus";
import { marked } from "marked";
import DOMPurify from "dompurify";
import * as echarts from "echarts";
import "echarts-wordcloud";

const loading = ref(false);
const submitting = ref(false);
const selectedCategory = ref("");
const majorName = ref("");
const targetIndustry = ref([]);
const reportMarkdown = ref("");

const majorPresets = ref([]);
const categoryOptions = ref([]);
const majorOptions = ref([]);
const industryOptions = ref([]);
const targetIndustryLoading = ref(false);
const restoringForm = ref(false);

const statsData = ref({ salary: [], skills: [], industries: [] });
const skillCloudData = ref([]);

let salaryChartInstance = null;
let industryChartInstance = null;
let skillChartInstance = null;

const salaryChartRef = ref(null);
const industryChartRef = ref(null);
const skillChartRef = ref(null);

const aiTaskStore = useAiTaskStore();
const route = useRoute();

const getRouteTaskId = () => {
  const taskId = route.query.task_id;
  return Array.isArray(taskId) ? taskId[0] : taskId;
};

const getTaskParams = (task) => {
  const result = task?.result || {};
  const params =
    result.request_params || task?.extraData?.request_params || task?.extraData || {};
  return {
    major: params.major_name || params.majorName || "",
    industry1: params.target_industry ?? params.industry1 ?? null,
    industry2: params.target_industry_2 ?? params.industry2 ?? null,
    industry1Name: params.target_industry_name ?? null,
    industry2Name: params.target_industry_2_name ?? null,
  };
};

const handleResize = () => {
  salaryChartInstance?.resize();
  industryChartInstance?.resize();
  skillChartInstance?.resize();
};

const fetchPresets = async () => {
  try {
    const res = await analysisAPI.getMajorPresets();
    majorPresets.value = res.data || [];
    categoryOptions.value = majorPresets.value.map((c) => c.name);
  } catch (error) {
    console.error("Failed to load major presets", error);
  }
};

const fetchMajorIndustries = async (major, preserveSelection = false) => {
  if (!major) {
    industryOptions.value = [];
    if (!preserveSelection) targetIndustry.value = [];
    return;
  }

  targetIndustryLoading.value = true;
  try {
    const res = await analysisAPI.getMajorIndustries(major);
    const treeData = res.data || [];
    industryOptions.value = treeData.map((l0) => {
      const parent = {
        value: l0.code,
        label: l0.name,
        children: [],
      };
      if (l0.children && l0.children.length > 0) {
        parent.children = l0.children.map((l1) => ({
          value: l1.code,
          label: l1.name,
        }));
      } else {
        delete parent.children;
      }
      return parent;
    });
    if (!preserveSelection) {
      targetIndustry.value = [];
    }
  } catch (error) {
    console.error("Failed to load major-specific industries tree", error);
    ElMessage.error("加载行业选项失败");
    industryOptions.value = [];
  } finally {
    targetIndustryLoading.value = false;
  }
};

const applyTaskResult = async (task) => {
  if (!task || !task.result) return false;

  const raw = task.result?.report || task.result?.result_data || "";
  if (raw) {
    const reportText = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
    reportMarkdown.value = DOMPurify.sanitize(marked.parse(reportText));
  }

  const params = getTaskParams(task);
  if (params.major) {
    restoringForm.value = true;
    majorName.value = params.major;
    await fetchMajorIndustries(params.major, true);
    restoringForm.value = false;
  }

  const selectedIndustry = [];
  if (params.industry1 !== null && params.industry1 !== undefined) {
    selectedIndustry.push(params.industry1);
  }
  if (params.industry2 !== null && params.industry2 !== undefined) {
    selectedIndustry.push(params.industry2);
  }
  targetIndustry.value = selectedIndustry;

  const result = task.result || {};
  const restoredStats = result.es_stats || result.analysis_input?.es_stats;
  const restoredSkillCloud =
    result.skillCloudData ||
    result.skill_cloud_data ||
    result.analysis_input?.skill_cloud_data ||
    result.analysis_input?.skillCloudData;

  if (restoredStats) {
    statsData.value = restoredStats;
  }
  if (Array.isArray(restoredSkillCloud) && restoredSkillCloud.length > 0) {
    skillCloudData.value = restoredSkillCloud;
  }

  if (
    restoredStats ||
    (Array.isArray(restoredSkillCloud) && restoredSkillCloud.length > 0)
  ) {
    nextTick(() => {
      updateCharts();
    });
    return true;
  }

  if (majorName.value) {
    try {
      const [statsRes, skillRes] = await Promise.all([
        analysisAPI.getJobStats({
          q: majorName.value,
          major_name: majorName.value,
          industry: params.industry1,
          industry_2: params.industry2,
        }),
        analysisAPI.getSkillCloud(
          majorName.value,
          params.industry1,
          params.industry2,
          params.industry1Name,
          params.industry2Name,
        ),
      ]);
      if (statsRes?.data) {
        statsData.value = statsRes.data;
      }
      if (skillRes?.data) {
        skillCloudData.value = skillRes.data;
      }
      nextTick(() => {
        updateCharts();
      });
    } catch (e) {
      console.error("Failed to restore fallback stats", e);
    }
  }
  return Boolean(raw);
};

const applyLatestCompletedResult = async () => {
  const lastResult = aiTaskStore.getLatestResult("career_compass");
  if (!lastResult) return false;
  return applyTaskResult(lastResult);
};

const restoreFromRouteOrLatest = async () => {
  const routeTaskId = getRouteTaskId();
  if (routeTaskId) {
    await aiTaskStore.fetchTaskById(
      routeTaskId,
      route.query.feature_key || "career_compass",
    );
    const task = aiTaskStore.getTask(routeTaskId);
    if (await applyTaskResult(task)) {
      return;
    }
  }

  if (await applyLatestCompletedResult()) {
    return;
  }

  await aiTaskStore.fetchHistory();
  await applyLatestCompletedResult();
};

const handleCategoryChange = () => {
  majorName.value = "";
  majorOptions.value = [];
  targetIndustry.value = [];
  industryOptions.value = [];

  if (selectedCategory.value) {
    const category = majorPresets.value.find((c) => c.name === selectedCategory.value);
    if (category) {
      majorOptions.value = category.majors.map((m) => ({
        name: m.major_name,
        hotIndex: m.hot_index,
      }));
    }
  }
};

watch(majorName, (newVal) => {
  if (restoringForm.value) return;
  fetchMajorIndustries(newVal);
});

const initCharts = () => {
  if (salaryChartRef.value) {
    if (salaryChartInstance) salaryChartInstance.dispose();
    salaryChartInstance = echarts.init(salaryChartRef.value);
  }
  if (industryChartRef.value) {
    if (industryChartInstance) industryChartInstance.dispose();
    industryChartInstance = echarts.init(industryChartRef.value);
  }
  if (skillChartRef.value) {
    if (skillChartInstance) skillChartInstance.dispose();
    skillChartInstance = echarts.init(skillChartRef.value);
  }
};

const updateCharts = () => {
  if (!statsData.value) return;

  const salaryOptions = {
    title: { text: "薪资区间分布", left: "center", textStyle: { color: "#333" } },
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    grid: { left: "3%", right: "4%", bottom: "3%", containLabel: true },
    xAxis: {
      type: "category",
      data: (statsData.value.salary || []).map((item) => item.name),
    },
    yAxis: { type: "value", name: "岗位数" },
    series: [
      {
        name: "岗位数量",
        type: "bar",
        data: (statsData.value.salary || []).map((item) => item.value),
        itemStyle: { color: "#409EFF", borderRadius: [4, 4, 0, 0] },
      },
    ],
  };
  salaryChartInstance?.setOption(salaryOptions);

  const industryOptionsConfig = {
    title: { text: "行业分布占比", left: "center" },
    tooltip: { trigger: "item" },
    legend: { orient: "vertical", left: "left" },
    series: [
      {
        name: "行业分布",
        type: "pie",
        radius: ["40%", "70%"],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: "#fff", borderWidth: 2 },
        label: { show: false, position: "center" },
        emphasis: { label: { show: true, fontSize: 18, fontWeight: "bold" } },
        labelLine: { show: false },
        data: statsData.value.industries || [],
      },
    ],
  };
  industryChartInstance?.setOption(industryOptionsConfig);

  if (Array.isArray(skillCloudData.value) && skillCloudData.value.length > 0) {
    const skillOptions = {
      title: { text: "核心技能词云", left: "center" },
      tooltip: { show: true },
      series: [
        {
          type: "wordCloud",
          shape: "circle",
          keepAspect: false,
          left: "center",
          top: "center",
          width: "90%",
          height: "90%",
          sizeRange: [12, 50],
          rotationRange: [-45, 45],
          rotationStep: 45,
          gridSize: 8,
          drawOutOfBound: false,
          layoutAnimation: true,
          textStyle: {
            fontFamily: "sans-serif",
            fontWeight: "bold",
            color() {
              return `rgb(${Math.round(Math.random() * 160)},${Math.round(Math.random() * 160)},${Math.round(Math.random() * 160)})`;
            },
          },
          emphasis: {
            focus: "self",
            textStyle: { textShadowBlur: 10, textShadowColor: "#333" },
          },
          data: skillCloudData.value,
        },
      ],
    };
    skillChartInstance?.setOption(skillOptions);
  }
};

const handleAnalyze = async () => {
  if (!majorName.value) {
    ElMessage.warning("请先选择具体专业后再分析。");
    return;
  }

  if (!Array.isArray(targetIndustry.value) || targetIndustry.value.length === 0) {
    ElMessage.warning("请先选择目标行业后再分析。");
    return;
  }

  const industry1 = targetIndustry.value[0] ?? null;
  const industry2 = targetIndustry.value[1] ?? null;

  let industry1Name = null;
  let industry2Name = null;
  if (industry1) {
    const l0 = industryOptions.value.find((item) => item.value === industry1);
    if (l0) {
      industry1Name = l0.label;
      if (industry2 && l0.children) {
        const l1 = l0.children.find((child) => child.value === industry2);
        if (l1) industry2Name = l1.label;
      }
    }
  }

  loading.value = true;
  submitting.value = true;
  reportMarkdown.value = "";

  try {
    const skillRes = await analysisAPI.getSkillCloud(
      majorName.value,
      industry1,
      industry2,
      industry1Name,
      industry2Name,
      30,
    );
    skillCloudData.value = skillRes.data || [];

    const requestParams = {
      major_name: majorName.value,
      target_industry: industry1,
      target_industry_2: industry2,
      target_industry_name: industry1Name,
      target_industry_2_name: industry2Name,
    };

    const reportRes = await aiAPI.getCareerCompass({
      ...requestParams,
      skill_cloud_data: skillCloudData.value,
    });
    const responseData = reportRes.data;

    if (responseData?.es_stats) {
      statsData.value = responseData.es_stats;
      nextTick(() => {
        updateCharts();
      });
    }

    let reportRaw;
    if (responseData?.task_id) {
      aiTaskStore.addTask(responseData.task_id, "career_compass", {
        request_params: requestParams,
        es_stats: responseData?.es_stats || statsData.value,
        skill_cloud_data: skillCloudData.value,
      });
      const result = await aiTaskStore.pollAndUpdate(responseData.task_id, {
        interval: 2000,
        timeout: 120000,
      });
      reportRaw =
        result?.report || result?.result_data || result || "未获取到报告内容。";
    } else {
      reportRaw = responseData?.report || "未获取到报告内容。";
    }
    const reportText =
      typeof reportRaw === "string" ? reportRaw : JSON.stringify(reportRaw, null, 2);
    reportMarkdown.value = DOMPurify.sanitize(marked.parse(reportText));
  } catch (error) {
    console.error("Analyze error:", error);
    if (error.response?.status === 409 || error.response?.data?.code === 40902) {
      const runningTaskId = error.response?.data?.data?.task_id;
      ElMessage.warning(
        `当前已有任务正在执行，请等待完成后再重试${runningTaskId ? `（任务ID: ${runningTaskId}）` : ""}`,
      );
    } else {
      ElMessage.error(error.message || "生成职业导航报告失败，请稍后重试。");
    }
  } finally {
    loading.value = false;
    submitting.value = false;
    nextTick(() => {
      initCharts();
      updateCharts();
    });
  }
};

onMounted(async () => {
  await fetchPresets();
  initCharts();
  window.addEventListener("resize", handleResize);
  await restoreFromRouteOrLatest();
});

onActivated(async () => {
  const taskId = getRouteTaskId();
  if (!taskId) return;
  await aiTaskStore.fetchTaskById(taskId, route.query.feature_key || "career_compass");
  const task = aiTaskStore.getTask(taskId);
  await applyTaskResult(task);
});

onUnmounted(() => {
  window.removeEventListener("resize", handleResize);
  salaryChartInstance?.dispose();
  industryChartInstance?.dispose();
  skillChartInstance?.dispose();
});

watch(
  () => route.query.task_id,
  async () => {
    const taskId = getRouteTaskId();
    if (!taskId) return;
    await aiTaskStore.fetchTaskById(taskId, route.query.feature_key || "career_compass");
    const task = aiTaskStore.getTask(taskId);
    await applyTaskResult(task);
  },
);
</script>

<template>
  <div class="career-compass-container">
    <div class="header-section">
      <h1 class="page-title">职业导航罗盘</h1>
      <p class="subtitle">基于真实岗位数据，展示专业到行业的趋势并生成 AI 报告。</p>

      <div class="search-box">
        <el-select
          v-model="selectedCategory"
          placeholder="专业大类"
          size="large"
          class="category-select"
          @change="handleCategoryChange"
        >
          <el-option
            v-for="cat in categoryOptions"
            :key="cat"
            :label="cat"
            :value="cat"
          ></el-option>
        </el-select>

        <el-select
          v-model="majorName"
          filterable
          allow-create
          default-first-option
          placeholder="搜索或输入具体专业"
          size="large"
          class="major-select"
          :disabled="!selectedCategory"
        >
          <el-option
            v-for="item in majorOptions"
            :key="item.name"
            :label="item.name"
            :value="item.name"
          >
            <span style="float: left">{{ item.name }}</span>
            <span style="float: right; color: #8492a6; font-size: 13px">
              热度 {{ item.hotIndex }}
            </span>
          </el-option>
        </el-select>

        <el-cascader
          v-model="targetIndustry"
          :options="industryOptions"
          :props="{ expandTrigger: 'hover' }"
          :placeholder="industryOptions.length === 0 ? '请先选择具体专业' : '向往行业（必填）'"
          size="large"
          class="target-input"
          clearable
          filterable
          :disabled="industryOptions.length === 0 || targetIndustryLoading"
          v-loading="targetIndustryLoading"
        ></el-cascader>

        <el-button
          type="primary"
          size="large"
          @click="handleAnalyze"
          :loading="submitting"
          :disabled="!majorName || !targetIndustry || targetIndustry.length === 0"
          color="#1e3a8a"
          dark
        >
          启动数据罗盘
        </el-button>
      </div>
    </div>

    <div class="content-section" v-loading="loading" element-loading-text="AI 正在分析中...">
      <div v-if="!reportMarkdown && !loading" class="empty-state">
        <el-empty description="输入你的专业，查看职业趋势与 AI 建议" />
      </div>

      <div class="dashboard-grid" v-else-if="!loading">
        <div class="bi-dashboard-panel">
          <h2 class="section-heading">市场数据看板</h2>
          <div class="chart-card">
            <div ref="salaryChartRef" class="echart-container"></div>
          </div>
          <div class="double-chart-row">
            <div class="chart-card half">
              <div ref="industryChartRef" class="echart-container"></div>
            </div>
            <div class="chart-card half">
              <div ref="skillChartRef" class="echart-container"></div>
            </div>
          </div>
        </div>

        <div class="ai-report-panel">
          <h2 class="section-heading">AI 诊断报告</h2>
          <el-card class="markdown-body-card" shadow="hover">
            <div class="markdown-container" v-html="reportMarkdown"></div>
          </el-card>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.career-compass-container {
  padding: 24px;
  background-color: #f8fafc;
  min-height: calc(100vh - 60px);
}

.header-section {
  text-align: center;
  padding: 40px 20px;
  background: linear-gradient(135deg, #1e3a8a 0%, #3b82f6 100%);
  color: white;
  border-radius: 12px;
  margin-bottom: 24px;
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
}

.page-title {
  margin: 0 0 16px 0;
  font-size: 2.5rem;
  font-weight: 800;
  letter-spacing: -0.025em;
}

.subtitle {
  font-size: 1.1rem;
  opacity: 0.9;
  margin-bottom: 32px;
}

.search-box {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  max-width: 1100px;
  width: 100%;
  margin: 0 auto;
}

.category-select {
  flex: 1;
  min-width: 150px;
}

.major-select {
  flex: 1.5;
  min-width: 200px;
}

.target-input {
  flex: 1.5;
  min-width: 200px;
}

.search-box .el-button {
  flex: 0 0 auto;
}

/* Dashboard Grid */
.dashboard-grid {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.bi-dashboard-panel {
  flex: 1;
  min-width: 0;
}

.ai-report-panel {
  flex: 1;
  min-width: 0;
}

.section-heading {
  font-size: 1.25rem;
  color: #1e293b;
  margin-bottom: 16px;
  font-weight: 600;
  border-left: 4px solid #3b82f6;
  padding-left: 12px;
}

.chart-card {
  background: white;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 24px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
  border: 1px solid #e2e8f0;
}

.double-chart-row {
  display: flex;
  gap: 24px;
}

.chart-card.half {
  flex: 1;
  min-width: 0;
}

.echart-container {
  height: 300px;
  width: 100%;
}

/* Markdown Rendering Customization */
.markdown-body-card {
  border-radius: 12px;
  background: #ffffff;
  min-height: 600px;
}

.markdown-container {
  font-family:
    -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.6;
  color: #334155;
  padding: 12px;
}

.markdown-container :deep(h2) {
  color: #1e3a8a;
  border-bottom: 2px solid #e2e8f0;
  padding-bottom: 8px;
  margin-top: 24px;
  font-size: 1.5rem;
}

.markdown-container :deep(h3) {
  color: #3b82f6;
  margin-top: 16px;
}

.markdown-container :deep(ul) {
  padding-left: 20px;
}

.markdown-container :deep(li) {
  margin-bottom: 8px;
}

.markdown-container :deep(strong) {
  color: #0f172a;
  background: #fef08a;
  padding: 0 4px;
  border-radius: 2px;
}

.empty-state {
  margin-top: 60px;
}

/* Responsive */
@media (max-width: 1024px) {
  .dashboard-grid {
    flex-direction: column;
  }
}

@media (max-width: 768px) {
  .search-box {
    flex-direction: column;
  }
  .double-chart-row {
    flex-direction: column;
  }
}
</style>

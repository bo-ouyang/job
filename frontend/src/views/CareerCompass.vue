<script setup>
import { ref, onMounted, computed, nextTick } from 'vue';
import { analysisAPI } from '../api/analysis';
import { ElMessage } from 'element-plus';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import * as echarts from 'echarts';
import 'echarts-wordcloud';

// State
const loading = ref(false);
const submitting = ref(false);
const majorName = ref('');
const targetIndustry = ref(''); // Optional
const reportMarkdown = ref('');

const majorPresets = ref([]);
const statsData = ref({ salary: [], skills: [], industries: [] });
const skillCloudData = ref([]);

// Charts
let salaryChartInstance = null;
let industryChartInstance = null;
let skillChartInstance = null;

const salaryChartRef = ref(null);
const industryChartRef = ref(null);
const skillChartRef = ref(null);

onMounted(async () => {
  await fetchPresets();
  initCharts();
  window.addEventListener('resize', handleResize);
});

const handleResize = () => {
  salaryChartInstance?.resize();
  industryChartInstance?.resize();
  skillChartInstance?.resize();
};

const fetchPresets = async () => {
  try {
    const res = await analysisAPI.getMajorPresets();
    majorPresets.value = res.data || [];
  } catch (error) {
    console.error("Failed to load major presets", error);
  }
};

const initCharts = () => {
  if (salaryChartRef.value) {
    salaryChartInstance = echarts.init(salaryChartRef.value);
  }
  if (industryChartRef.value) {
    industryChartInstance = echarts.init(industryChartRef.value);
  }
  if (skillChartRef.value) {
    skillChartInstance = echarts.init(skillChartRef.value);
  }
};

const updateCharts = () => {
  if (!statsData.value) return;

  // 1. Salary Distribution (Bar / Funnel like)
  const salaryOptions = {
    title: { text: '薪资漏斗透视', left: 'center', textStyle: { color: '#333' } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: statsData.value.salary.map(item => item.name) },
    yAxis: { type: 'value', name: '需求量(个)' },
    series: [
      {
        name: '招聘机会',
        type: 'bar',
        data: statsData.value.salary.map(item => item.value),
        itemStyle: { color: '#409EFF', borderRadius: [4, 4, 0, 0] }
      }
    ]
  };
  salaryChartInstance?.setOption(salaryOptions);

  // 2. Industry Distribution (Pie)
  const industryOptions = {
    title: { text: '核心落地行业', left: 'center' },
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', left: 'left' },
    series: [
      {
        name: '行业占比',
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
        label: { show: false, position: 'center' },
        emphasis: { label: { show: true, fontSize: 18, fontWeight: 'bold' } },
        labelLine: { show: false },
        data: statsData.value.industries
      }
    ]
  };
  industryChartInstance?.setOption(industryOptions);

  // 3. Skill Cloud
  if (skillCloudData.value.length > 0) {
    const skillOptions = {
      title: { text: '硬核心技能图谱', left: 'center' },
      tooltip: { show: true },
      series: [{
        type: 'wordCloud',
        shape: 'circle',
        keepAspect: false,
        left: 'center', top: 'center', width: '90%', height: '90%',
        sizeRange: [12, 50],
        rotationRange: [-45, 45],
        rotationStep: 45,
        gridSize: 8,
        drawOutOfBound: false,
        layoutAnimation: true,
        textStyle: {
          fontFamily: 'sans-serif',
          fontWeight: 'bold',
          color: function () {
            return 'rgb(' + [
              Math.round(Math.random() * 160),
              Math.round(Math.random() * 160),
              Math.round(Math.random() * 160)
            ].join(',') + ')';
          }
        },
        emphasis: { focus: 'self', textStyle: { textShadowBlur: 10, textShadowColor: '#333' } },
        data: skillCloudData.value
      }]
    };
    skillChartInstance?.setOption(skillOptions);
  }
};

const handleAnalyze = async () => {
  if (!majorName.value) {
    ElMessage.warning('请输入或选择您在读的专业名称');
    return;
  }

  loading.value = true;
  submitting.value = true;
  reportMarkdown.value = '';

  try {
    // 1. Fetch Skill Cloud
    const skillRes = await analysisAPI.getSkillCloud(majorName.value, 30);
    skillCloudData.value = skillRes.data || [];

    // 2. Fetch Job Stats (Macro Dashboard)
    const statsRes = await analysisAPI.getJobStats({ q: majorName.value });
    statsData.value = statsRes.data || { salary: [], industries: [], skills: [] };
    
    // Update Charts Immediately after fetching stats
    nextTick(() => { updateCharts(); });

    // 3. Fetch AI Diagnostic Report
    const reportRes = await analysisAPI.getCareerCompass(majorName.value, targetIndustry.value);
    const reportRaw = reportRes.data?.report || '未能生成报告。';
    
    // Parse Markdown securely
    reportMarkdown.value = DOMPurify.sanitize(marked.parse(reportRaw));

  } catch (error) {
    console.error("Analyze error:", error);
    ElMessage.error('生成罗盘报告时发生错误');
  } finally {
    loading.value = false;
    submitting.value = false;
  }
};

</script>

<template>
  <div class="career-compass-container">
    <div class="header-section">
      <h1 class="page-title">🧭 职业导航罗盘</h1>
      <p class="subtitle">打通校园到职场的信息差，基于 10w+ 真实岗位数据驱动的职业生涯诊断评测。</p>
      
      <div class="search-box">
        <el-select
          v-model="majorName"
          filterable
          allow-create
          default-first-option
          placeholder="搜索或直接输入您的大学专业 (例: 软件工程)"
          size="large"
          class="major-select"
        >
          <el-option-group
            v-for="group in majorPresets"
            :key="group.name"
            :label="group.name"
          >
            <el-option
              v-for="item in group.majors"
              :key="item.major_name"
              :label="item.major_name"
              :value="item.major_name"
            >
              <span style="float: left">{{ item.major_name }}</span>
              <span style="float: right; color: #8492a6; font-size: 13px">
                🔥 热度 {{ item.hot_index }}
              </span>
            </el-option>
          </el-option-group>
        </el-select>

        <el-input 
          v-model="targetIndustry" 
          placeholder="向往行业 (选填：如 互联网)" 
          size="large" 
          class="target-input" 
        />
        
        <el-button 
          type="primary" 
          size="large" 
          @click="handleAnalyze" 
          :loading="submitting"
          color="#1e3a8a"
          dark
        >
          🚀 启动数据罗盘
        </el-button>
      </div>
    </div>

    <!-- Results Section -->
    <div class="content-section" v-loading="loading" element-loading-text="AI导师正在研读大盘数据...">
      
      <!-- Placeholder when empty -->
      <div v-if="!reportMarkdown && !loading" class="empty-state">
        <el-empty description="输入您的专业，揭示真实的职业图景" />
      </div>

      <div class="dashboard-grid" v-else-if="!loading">
        <!-- Left: BI Dashboard -->
        <div class="bi-dashboard-panel">
          <h2 class="section-heading">📊 宏观市场透视仪</h2>
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

        <!-- Right: AI Diagnostic Report -->
        <div class="ai-report-panel">
          <h2 class="section-heading">🧠 AI 专属诊断报告</h2>
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
  justify-content: center;
  gap: 16px;
  max-width: 800px;
  margin: 0 auto;
}

.major-select {
  flex: 2;
}

.target-input {
  flex: 1;
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
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
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
  background: #fef08a; /* Soft highlighter yellow */
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

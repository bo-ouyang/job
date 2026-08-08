<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import DOMPurify from "dompurify";
import { marked } from "marked";

import { marketAPI } from "@/api/market";
import { agentAPI } from "@/api/agent";
import { careerAPI } from "@/api/career";
import HomePanel from "@/components/home/HomePanel.vue";
import KpiCard from "@/components/home/KpiCard.vue";
import IndustryTrendChart from "@/components/charts/IndustryTrendChart.vue";
import SalaryBarChart from "@/components/charts/SalaryBarChart.vue";
import SkillDonutChart from "@/components/charts/SkillDonutChart.vue";
import homeMockData from "@/data/homeMockData";
import { loadMarketDashboard } from "@/services/marketDashboard";
import { useAuthStore } from "@/stores/auth";
import { extractAgentRunReference, extractApiError } from "@/utils/apiError";
import { useAgentRunStream } from "@/composables/useAgentRunStream";
import { connectAgentEventStream } from "@/utils/sseClient";

const router = useRouter();
const authStore = useAuthStore();
const dashboard = ref(null);
const dataSource = ref("loading");
const updatedAt = ref(null);
const pricing = ref({});
const loading = ref(true);
const aiOpen = ref(true);
const aiSending = ref(false);
const aiQuestion = ref("");
const aiError = ref("");
const marketClarification = ref(null);
const clarificationAnswer = ref("");
const clarificationSubmitting = ref(false);
const marketAiWelcome = {
  role: "assistant",
  content: "你好，我可以基于当前招聘市场数据，回答行业趋势、城市薪资和技能需求问题。",
};
const aiMessages = ref([{ ...marketAiWelcome }]);
const marketRun = useAgentRunStream({
  connect: connectAgentEventStream,
  getRun: agentAPI.getRun,
  onEvent: (event) => {
    const provisional = aiMessages.value.find(
      (message) => message.provisional && String(message.runId) === String(event.run_id),
    );
    if (!provisional) return;
    const stages = {
      run_started: "running",
      tool_started: "tool",
      message_started: "generating",
      message_delta: "streaming",
    };
    provisional.status = stages[event.event] || provisional.status;
  },
  onTerminal: async ({ event, run: finishedRun, content, successful }) => {
    const runId = finishedRun?.id || event.run_id;
    const provisional = aiMessages.value.find(
      (message) => message.provisional && String(message.runId) === String(runId),
    );
    if (!provisional) return;
    if (finishedRun?.status === "waiting_user") {
      provisional.status = "waiting_user";
      marketClarification.value = {
        runId: String(runId),
        conversationId: finishedRun.conversationId || event.conversation_id || null,
        question: event.data?.question || event.data?.message || "请补充必要信息后继续分析。",
      };
      return;
    }
    if (event.event === "run_completed") {
      if (successful) {
        // The confirmed stream is already the latest answer. Avoid replacing it
        // with a stale history response from another conversation.
        provisional.status = "completed";
        provisional.content = content;
        return;
      }
      // The fallback snapshot is scoped to this exact run/conversation. An
      // unrelated historical assistant answer must never settle this run.
      const snapshot = await readCurrentRunAnswer(runId, finishedRun?.conversationId || event.conversation_id)
        .catch(() => null);
      if (snapshot) {
        provisional.status = "completed";
        provisional.content = snapshot;
      } else {
        provisional.status = "failed";
        provisional.content = "回答生成未完成，本次不会扣除余额。请重新提问。";
      }
      return;
    }
    provisional.status = event.event === "run_cancelled" ? "cancelled" : "failed";
    provisional.content = event.event === "run_cancelled"
      ? "本次问题已取消，未生成完整回答，不会扣除余额。"
      : "本次回答未完成，不会扣除余额。请稍后重新提问。";
  },
});
const filters = reactive({ range: "12m", city: "", industry: "", education: "" });

const market = computed(() => dashboard.value || homeMockData);
const filterOptions = computed(() => market.value.filters || homeMockData.filters);
const questionPrice = computed(() => pricing.value.marketQuestion?.amount || "");
const priceHint = computed(() => questionPrice.value
  ? `预计 ¥${questionPrice.value}/次`
  : "价格以发送前确认为准");
const sourceNotice = computed(() => {
  if (dataSource.value === "fallback") {
    return `数据服务已降级，当前展示最近一次可用数据 · ${formatUpdatedAt(updatedAt.value)}`;
  }
  if (["mixed", "synthetic"].includes(dataSource.value)) {
    const count = dashboard.value?.dataStatus?.syntheticDimensions?.length || 0;
    const prefix = dataSource.value === "synthetic" ? "当前展示测试数据" : "部分展示使用测试数据";
    return `${prefix}（${count} 个维度），数据缺口已记录，真实数据接入后会自动替换。`;
  }
  return "";
});

const formatUpdatedAt = (value) => {
  if (!value) return "更新时间待同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return `更新于 ${date.toLocaleString("zh-CN", { hour12: false })}`;
};
const formatSalary = (value) => {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return `¥${value.toLocaleString("zh-CN")}`;
  return String(value);
};

const renderAssistantContent = (content) => DOMPurify.sanitize(
  marked.parse(String(content || ""), { breaks: true }),
);

const historyMessages = (items) => {
  const messages = [];
  for (const item of items || []) {
    const conversationMessages = (item.messages || [])
      .filter((message) => ["user", "assistant"].includes(message.role))
      .map((message) => ({
        id: String(message.id),
        role: message.role,
        content: message.content,
        createdAt: message.createdAt || "",
        metadata: message.metadata || {},
        runId: message.runId || message.run_id || message.metadata?.runId || message.metadata?.run_id || null,
        conversationId: item.conversationId || message.conversationId || message.conversation_id || null,
      }));
    messages.push(...conversationMessages);
    if (
      item.latestRunStatus === "failed"
      && !conversationMessages.some((message) => message.role === "assistant")
    ) {
      messages.push({
        id: `failed-${item.latestRunId || item.conversationId}`,
        role: "assistant",
        content: "上次行业问数分析失败，请重新发送问题。",
        createdAt: item.updatedAt || item.createdAt || "",
      });
    }
  }
  return messages.sort((left, right) => String(left.createdAt).localeCompare(String(right.createdAt)));
};

const readCurrentRunAnswer = async (runId, conversationId) => {
  if (!runId || !conversationId) return null;
  const response = await agentAPI.getConversation(String(conversationId));
  const detail = response?.data || {};
  const messages = detail.messages || [];
  const explicit = [...messages].reverse().find((message) => (
    message.role === "assistant"
      && String(message.runId || message.run_id || message.metadata?.runId || message.metadata?.run_id || "") === String(runId)
  ));
  if (explicit?.content) return explicit.content;
  if (String(detail.latest_run?.id || detail.latestRun?.id || "") !== String(runId)) return null;
  return [...messages].reverse().find((message) => message.role === "assistant")?.content || null;
};

const restoreMarketClarification = async (runId, conversationId) => {
  const response = await agentAPI.getConversation(String(conversationId));
  const prompt = [...(response?.data?.messages || [])].reverse().find(
    (message) => message.role === "assistant" && message.message_type === "clarification_required",
  );
  marketClarification.value = {
    runId: String(runId),
    conversationId: String(conversationId),
    question: prompt?.content || "请补充必要信息后继续分析。",
  };
};

const loadAiHistory = async ({ resumeActive = false } = {}) => {
  if (!authStore.isAuthenticated) return [];
  const response = await marketAPI.getHistory({ limit: 30 });
  const items = response?.data?.items || [];
  aiMessages.value = [{ ...marketAiWelcome }, ...historyMessages(items)];
  if (resumeActive) {
    const active = items.find((item) => ["queued", "running", "waiting_user"].includes(item.latestRunStatus));
    if (active?.latestRunId) {
      aiMessages.value.push({
        id: `stream-${active.latestRunId}`,
        runId: String(active.latestRunId),
        role: "assistant",
        provisional: true,
        status: active.latestRunStatus,
        content: "",
      });
      if (active.latestRunStatus === "waiting_user") {
        await restoreMarketClarification(active.latestRunId, active.conversationId);
      } else {
        marketRun.start({
          runId: active.latestRunId,
          conversationId: active.conversationId,
          initialStatus: active.latestRunStatus,
        });
      }
    }
  }
  return items;
};

const refreshDashboard = async () => {
  loading.value = true;
  const result = await loadMarketDashboard({ ...filters });
  dashboard.value = result.data;
  dataSource.value = result.source;
  updatedAt.value = result.updatedAt;
  loading.value = false;
};

const loadPricing = async () => {
  try {
    const response = await careerAPI.getPricing();
    pricing.value = response?.data || {};
  } catch {
    pricing.value = {};
  }
};

const matrixStyle = (item) => ({
  left: `${Math.min(84, Math.max(10, (Number(item.salary) - 10) * 10))}%`,
  bottom: `${Math.min(76, Math.max(12, (Number(item.growth) - 7) * 5.2))}%`,
  width: `${item.size || 64}px`,
  height: `${item.size || 64}px`,
});

const goCareerAnalysis = () => router.push({ name: "career-analysis" });

const startMarketRun = (runId, conversationId, initialStatus = "queued") => {
  if (!aiMessages.value.some((message) => message.provisional && String(message.runId) === String(runId))) {
    aiMessages.value.push({
      id: `stream-${runId}`,
      runId: String(runId),
      role: "assistant",
      provisional: true,
      status: initialStatus,
      content: "",
    });
  }
  marketRun.start({ runId, conversationId, initialStatus });
};

const submitMarketClarification = async () => {
  const current = marketClarification.value;
  const content = clarificationAnswer.value.trim();
  if (!current?.conversationId || !content || clarificationSubmitting.value) return;
  clarificationSubmitting.value = true;
  aiError.value = "";
  try {
    const key = globalThis.crypto?.randomUUID?.() || `market-clarify-${Date.now()}`;
    const response = await agentAPI.sendMessage(
      current.conversationId,
      { content, message_type: "clarification_response", context: { source: "market_ai" } },
      key,
    );
    const resumed = response?.data?.run;
    marketClarification.value = null;
    clarificationAnswer.value = "";
    startMarketRun(resumed?.id || current.runId, current.conversationId, resumed?.status || "queued");
  } catch (error) {
    aiError.value = extractApiError(error, "补充信息发送失败，请稍后重试。").message;
  } finally {
    clarificationSubmitting.value = false;
  }
};

const cancelMarketClarification = async () => {
  const current = marketClarification.value;
  if (!current || clarificationSubmitting.value) return;
  clarificationSubmitting.value = true;
  try {
    await agentAPI.cancelRun(current.runId);
    const provisional = aiMessages.value.find((message) => String(message.runId) === current.runId);
    if (provisional) {
      provisional.status = "cancelled";
      provisional.content = "本次问题已取消，未生成完整回答，不会扣除余额。";
    }
    marketClarification.value = null;
    clarificationAnswer.value = "";
  } catch (error) {
    aiError.value = extractApiError(error, "任务取消失败，请稍后重试。").message;
  } finally {
    clarificationSubmitting.value = false;
  }
};

const sendAiQuestion = async () => {
  const question = aiQuestion.value.trim();
  if (!question || aiSending.value || marketClarification.value) return;
  if (!authStore.isAuthenticated) {
    router.push({
      name: "home",
      query: { login: "true", redirect: "/", action: "market-ai" },
    });
    return;
  }

  aiSending.value = true;
  aiError.value = "";
  aiMessages.value.push({ role: "user", content: question });
  aiQuestion.value = "";
  try {
    const idempotencyKey = globalThis.crypto?.randomUUID?.()
      || `market-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const response = await marketAPI.askQuestion(
      { question, context: { filters: { ...filters } } },
      idempotencyKey,
    );
    const runId = response?.data?.runId;
    if (!runId) throw new Error("分析任务创建失败，请稍后重试。");
    startMarketRun(runId, response?.data?.conversationId, response?.data?.status || "queued");
  } catch (error) {
    const apiError = extractApiError(
      error,
      "问题暂时发送失败，请稍后重试。",
    );
    const active = extractAgentRunReference(apiError.data);
    if (apiError.code === "AGENT_ACTIVE_RUN_EXISTS" && active?.messageType === "market_question") {
      startMarketRun(active.runId, active.conversationId, active.status || "queued");
    } else {
      aiError.value = apiError.message;
    }
  } finally {
    aiSending.value = false;
  }
};

onMounted(() => {
  refreshDashboard();
  loadPricing();
});

watch(
  () => authStore.isAuthenticated,
  (authenticated) => {
    if (authenticated) {
      loadAiHistory({ resumeActive: true }).catch(() => {
        aiError.value = "聊天记录暂时加载失败，请稍后重试。";
      });
    } else {
      marketRun.stop();
      marketClarification.value = null;
      clarificationAnswer.value = "";
      aiMessages.value = [{ ...marketAiWelcome }];
    }
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  marketRun.stop();
});
</script>

<template>
  <main class="market-page">
    <section class="market-hero">
      <div class="hero-copy">
        <p class="eyebrow"><i /> LIVE LABOR MARKET · 2026</p>
        <h1>看懂全行业就业市场，<br><span>再决定你的职业方向。</span></h1>
        <p class="hero-description">聚合真实招聘市场数据，观察行业需求、城市薪资、人才结构和技能变化。首页无需登录，所有人都可以自由探索。</p>
        <div class="hero-actions">
          <button class="primary-action" @click="goCareerAnalysis">生成我的职业分析 <span>→</span></button>
          <span class="freshness"><i /> {{ formatUpdatedAt(updatedAt) }}</span>
        </div>
      </div>
      <div class="hero-visual" aria-label="市场活跃指数 82.6">
        <div class="orbit orbit-one" /><div class="orbit orbit-two" />
        <div class="hero-stat"><small>市场活跃指数</small><strong>82.6</strong><em>较上月 +4.8%</em></div>
        <div v-for="(signal, index) in market.heroSignals" :key="signal.label" class="hero-signal" :class="`signal-${index}`"><span>{{ signal.label }}</span><b>{{ signal.value }}</b></div>
      </div>
    </section>

    <form class="filter-card" @submit.prevent="refreshDashboard">
      <label><span>时间范围</span><select v-model="filters.range"><option v-for="item in filterOptions.ranges" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label><span>城市</span><select v-model="filters.city"><option v-for="item in filterOptions.cities" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label><span>行业</span><select v-model="filters.industry"><option v-for="item in filterOptions.industries" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <label><span>学历</span><select v-model="filters.education"><option v-for="item in filterOptions.educations" :key="item.value" :value="item.value">{{ item.label }}</option></select></label>
      <button class="filter-submit" :disabled="loading">{{ loading ? "加载中…" : "应用筛选" }}</button>
    </form>

    <p v-if="sourceNotice" class="source-notice" data-test="market-source"><span>i</span> {{ sourceNotice }}</p>

    <section class="kpi-grid" :aria-busy="loading">
      <KpiCard v-for="item in market.kpis" :key="item.label" :item="item" />
    </section>

    <section class="dashboard-grid primary-grid">
      <HomePanel class="trend-panel" title="行业岗位需求趋势" subtitle="重点行业 · 近 12 个月" :action="''"><IndustryTrendChart :data="market.trend" /></HomePanel>
      <HomePanel title="城市薪资中位数" subtitle="月薪 · 单位：千元" :action="''"><SalaryBarChart :data="market.citySalaries" /></HomePanel>
    </section>

    <section class="market-detail-grid">
      <article class="data-card salary-card">
        <header><div><p>SALARY DISTRIBUTION</p><h2>全行业月薪分布</h2></div><span>样本 86.4 万</span></header>
        <div class="histogram" aria-label="全行业薪资区间柱状图">
          <div v-for="item in market.salaryDistribution" :key="item.label" :class="{ featured: item.featured }"><b>{{ item.value }}%</b><i :style="{ height: `${Math.max(8, item.value * 3)}px` }" /><span>{{ item.label }}</span></div>
        </div>
        <footer class="salary-summary"><div><small>薪资中位数</small><strong>{{ formatSalary(market.salarySummary?.median) }}</strong></div><div><small>P75 薪资</small><strong>{{ formatSalary(market.salarySummary?.p75) }}</strong></div></footer>
      </article>

      <article class="data-card talent-card">
        <header><div><p>TALENT STRUCTURE</p><h2>学历与经验结构</h2></div></header>
        <section><div class="structure-heading"><span>学历要求</span><b>本科仍是主流</b></div><div class="stacked-bar"><i v-for="item in market.talentStructure.education" :key="item.label" :style="{ width: `${item.value}%` }" /></div><div class="structure-legend"><span v-for="item in market.talentStructure.education" :key="item.label">{{ item.label }} {{ item.value }}%</span></div></section>
        <section class="experience-block"><div class="structure-heading"><span>经验要求</span><b>1–3 年需求最高</b></div><div class="experience-ring"><strong>42%</strong><small>1–3 年</small></div><div class="experience-list"><span v-for="item in market.talentStructure.experience" :key="item.label"><i :style="{ width: `${item.value}%` }" />{{ item.label }} {{ item.value }}%</span></div></section>
      </article>

      <article class="data-card matrix-card">
        <header><div><p>CITY OPPORTUNITY MATRIX</p><h2>城市机会矩阵</h2></div><span>横轴薪资 · 纵轴增长</span></header>
        <div class="matrix-plot"><i class="axis-x" /><i class="axis-y" /><small class="zone-label">高增长 / 高薪资</small><button v-for="item in market.cityMatrix" :key="item.city" class="city-bubble" :class="item.tone" :style="matrixStyle(item)"><b>{{ item.city }}</b><span>+{{ item.growth }}%</span></button><em class="axis-label-x">薪资中位数 →</em><em class="axis-label-y">岗位增长率 →</em></div>
      </article>
    </section>

    <section class="signal-section">
      <div class="section-heading"><div><p>MONTHLY SIGNALS</p><h2>本月关键变化</h2></div><span>从岗位发布、薪资和技能频率中识别</span></div>
      <div class="signal-grid"><article v-for="item in market.signals" :key="item.title"><span class="signal-icon" :class="item.tone">{{ item.icon }}</span><div><small>{{ item.type }}</small><strong>{{ item.title }}</strong><p>{{ item.detail }}</p></div><em :class="item.tone">{{ item.delta }}</em></article></div>
    </section>

    <section class="dashboard-grid bottom-grid">
      <HomePanel title="热门技能需求" subtitle="招聘文本出现频率" :action="''"><SkillDonutChart :data="market.skills" /></HomePanel>
      <article class="data-card ranking-card">
        <header><div><p>OPPORTUNITY RANK</p><h2>行业机会榜</h2></div><span>综合岗位增长、薪资与人才缺口</span></header>
        <div class="ranking-table"><div class="table-head"><span>行业</span><span>岗位增长</span><span>薪资中位数</span><span>人才缺口</span><span>机会指数</span></div><div v-for="(item, index) in market.rankings" :key="item.name"><span><b :class="{ first: index === 0 }">{{ index + 1 }}</b>{{ item.name }}</span><span>{{ item.growth }}</span><span>{{ item.salary }}</span><span>{{ item.gap }}</span><strong>{{ item.score }}</strong></div></div>
      </article>
    </section>

    <section class="personal-cta"><div><p>PERSONAL CAREER ANALYSIS</p><h2>市场数据只是起点，更重要的是它与你有什么关系。</h2><span>完善学校、专业、课程和技能资料，生成属于你的职业机会地图。</span></div><button @click="goCareerAnalysis">开始职业分析 →</button></section>

    <aside v-show="aiOpen" class="market-ai-dialog" data-test="market-ai-dialog" aria-label="AI 行业问数">
      <header><span>AI</span><div><small>MARKET DATA COPILOT</small><strong>AI 行业问数</strong></div><i /><em>在线</em><button data-test="market-ai-close" aria-label="收起 AI 对话框" @click="aiOpen = false">×</button></header>
      <div class="ai-message-list">
        <div v-for="(message, index) in aiMessages" :key="message.id || index" :class="message.role">
          <div v-if="message.provisional" class="ai-stream-state" data-test="market-ai-streaming-message">
            <span v-if="message.status === 'queued'">正在回答（排队中）…</span>
            <span v-else-if="message.status === 'tool'">正在查询市场数据…</span>
            <span v-else-if="message.status === 'generating'">正在生成回答…</span>
            <span v-else-if="message.status === 'streaming'">正在回答</span>
            <span v-else-if="message.status === 'failed' || message.status === 'cancelled'">回答未完成</span>
            <span v-else>正在分析…</span>
            <div
              class="ai-markdown"
              v-html="renderAssistantContent(['failed', 'cancelled'].includes(message.status) ? message.content : (message.runId === marketRun.run?.id ? marketRun.content : message.content))"
            />
          </div>
          <div
            v-else-if="message.role === 'assistant'"
            class="ai-markdown"
            v-html="renderAssistantContent(message.content)"
          />
          <template v-else>{{ message.content }}</template>
        </div>
      </div>
      <form v-if="marketClarification" class="market-clarification" data-test="market-ai-clarification" @submit.prevent="submitMarketClarification">
        <p>{{ marketClarification.question }}</p>
        <textarea v-model="clarificationAnswer" data-test="market-ai-clarification-input" placeholder="补充信息后继续" />
        <div><button type="button" :disabled="clarificationSubmitting" @click="cancelMarketClarification">取消任务</button><button :disabled="clarificationSubmitting || !clarificationAnswer.trim()">继续分析</button></div>
      </form>
      <form class="ai-composer" @submit.prevent="sendAiQuestion"><textarea v-model="aiQuestion" data-test="market-ai-input" :disabled="Boolean(marketClarification)" placeholder="例如：新能源行业未来一年需要哪些技能？" /><p v-if="aiError" class="ai-error">{{ aiError }}</p><div><span>发送时需要登录 · {{ priceHint }}</span><button data-test="market-ai-send" :disabled="aiSending || Boolean(marketClarification)">{{ aiSending ? "发送中…" : "发送问题 ↑" }}</button></div></form>
    </aside>
    <button v-show="!aiOpen" class="ai-launcher" data-test="market-ai-launcher" aria-label="打开 AI 行业问数" @click="aiOpen = true"><span>AI</span><b>问行业数据</b><i /></button>
  </main>
</template>

<style scoped>
.market-page { width: min(1540px,calc(100% - 32px)); margin: 0 auto; padding: 36px 0 88px; color: #17253d; }.market-hero { display: grid; min-height: 365px; grid-template-columns: 1.05fr .95fr; align-items: center; gap: 56px; }.hero-copy { padding-left: 8px; }.eyebrow,.data-card header p,.section-heading p,.personal-cta p { margin: 0 0 10px; color: #55708f; font-size: 11px; font-weight: 800; letter-spacing: .16em; }.eyebrow i,.freshness i { display: inline-block; width: 6px; height: 6px; margin: 0 7px 1px 0; background: #20aa91; border-radius: 50%; box-shadow: 0 0 0 4px #dcf5ee; }.market-hero h1 { margin: 0; color: #13233c; font-size: clamp(39px,4vw,61px); line-height: 1.08; letter-spacing: -.055em; }.market-hero h1 span { color: #1767dc; }.hero-description { max-width: 650px; margin: 25px 0; color: #596d87; font-size: 16px; line-height: 1.9; }.hero-actions { display: flex; align-items: center; gap: 22px; }.primary-action,.filter-submit,.personal-cta button { padding: 12px 18px; color: #fff; background: linear-gradient(135deg,#176bff,#1257c9); border: 0; border-radius: 9px; box-shadow: 0 8px 20px rgba(23,107,255,.2); font-size: 13px; font-weight: 700; cursor: pointer; }.primary-action span { margin-left: 15px; }.freshness { color: #64778e; font-size: 12px; }.hero-visual { position: relative; height: 320px; background: radial-gradient(circle at 50% 48%,#ddecff 0,#f4f8fc 52%,transparent 73%); border-radius: 50%; }.orbit { position: absolute; border: 1px solid #bfd5ef; border-radius: 50%; }.orbit-one { inset: 45px; transform: rotate(-12deg); }.orbit-two { inset: 88px 32px; transform: rotate(30deg); }.hero-stat { position: absolute; top: 82px; left: 50%; width: 158px; height: 158px; padding-top: 33px; background: rgba(255,255,255,.96); border: 1px solid #d9e5f2; border-radius: 50%; box-shadow: 0 14px 40px rgba(39,64,98,.08); text-align: center; transform: translateX(-50%); }.hero-stat small,.hero-stat strong,.hero-stat em { display: block; }.hero-stat small { color: #63768e; font-size: 11px; }.hero-stat strong { margin: 4px 0; color: #1767dc; font-size: 42px; letter-spacing: -.06em; }.hero-stat em { color: #17846e; font-size: 11px; font-style: normal; }.hero-signal { position: absolute; display: flex; align-items: center; gap: 12px; padding: 11px 14px; background: #fff; border: 1px solid #dce7f2; border-radius: 10px; box-shadow: 0 14px 40px rgba(39,64,98,.08); font-size: 12px; }.hero-signal b { color: #159278; }.signal-0 { top: 48px; right: 24px; }.signal-1 { bottom: 34px; left: 24px; }
.filter-card { display: grid; grid-template-columns: repeat(4,1fr) auto; align-items: end; gap: 14px; padding: 17px 18px; background: #fff; border: 1px solid #e1e8f0; border-radius: 14px; box-shadow: 0 8px 25px rgba(42,67,101,.04); }.filter-card label { display: grid; gap: 7px; }.filter-card label span { color: #5d7088; font-size: 12px; }.filter-card select { width: 100%; padding: 10px 11px; color: #344760; background: #f8fafc; border: 1px solid #dde5ee; border-radius: 7px; outline: none; font-size: 13px; }.filter-submit { min-width: 98px; padding: 11px 15px; background: #173d70; box-shadow: none; }.filter-submit:disabled { opacity: .65; cursor: wait; }.source-notice { display: flex; align-items: center; gap: 8px; margin: 10px 2px 0; color: #7a6539; font-size: 12px; }.source-notice span { display: grid; width: 17px; height: 17px; place-items: center; color: #9b701c; background: #fff3d5; border-radius: 50%; font-size: 10px; font-weight: 800; }
.kpi-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin: 14px 0; }.dashboard-grid { display: grid; gap: 14px; }.primary-grid { grid-template-columns: 1.8fr 1fr; }.dashboard-grid :deep(.panel) { min-width: 0; height: 365px; }.data-card { min-width: 0; padding: 21px; background: #fff; border: 1px solid #e1e8f0; border-radius: 14px; box-shadow: 0 8px 25px rgba(42,67,101,.04); }.data-card header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }.data-card header p,.section-heading p { margin-bottom: 5px; font-size: 10px; }.data-card h2,.section-heading h2 { margin: 0; color: #1e314b; font-size: 19px; }.data-card header>span,.section-heading>span { color: #687a91; font-size: 11px; }.market-detail-grid { display: grid; grid-template-columns: 1.15fr .85fr 1fr; gap: 14px; margin-top: 14px; }.market-detail-grid>article { min-height: 380px; }
.histogram { display: grid; height: 220px; grid-template-columns: repeat(6,1fr); align-items: end; gap: 10px; margin-top: 22px; padding: 15px 5px 0; border-bottom: 1px solid #dfe6ee; background: repeating-linear-gradient(to bottom,#fff 0,#fff 52px,#edf1f5 53px); }.histogram>div { display: grid; height: 100%; grid-template-rows: 26px 1fr 38px; align-items: end; text-align: center; }.histogram b { color: #60728a; font-size: 11px; }.histogram i { display: block; width: 100%; min-height: 8px; max-height: 135px; background: linear-gradient(180deg,#7db3e9,#d7e8f7); border-radius: 7px 7px 2px 2px; }.histogram .featured i { background: linear-gradient(180deg,#176bff,#83b4f5); box-shadow: 0 6px 15px rgba(23,107,255,.16); }.histogram span { align-self: center; color: #66778d; font-size: 10px; }.salary-summary { display: flex; gap: 34px; margin-top: 17px; }.salary-summary div { padding-right: 34px; border-right: 1px solid #e3e9ef; }.salary-summary small,.salary-summary strong { display: block; }.salary-summary small { color: #78899f; font-size: 10px; }.salary-summary strong { margin-top: 4px; font-size: 16px; }.talent-card>section { margin-top: 25px; }.structure-heading { display: flex; justify-content: space-between; color: #596c84; font-size: 11px; }.structure-heading b { color: #1b6ad5; }.stacked-bar { display: flex; height: 14px; margin: 12px 0; overflow: hidden; border-radius: 10px; }.stacked-bar i:nth-child(1) { background: #cdd8e6; }.stacked-bar i:nth-child(2) { background: #176bff; }.stacked-bar i:nth-child(3) { background: #18a88c; }.stacked-bar i:nth-child(4) { background: #7561d5; }.structure-legend { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; color: #687991; font-size: 10px; }.experience-block { position: relative; }.experience-ring { position: absolute; left: 5px; top: 37px; display: grid; width: 84px; height: 84px; place-items: center; background: radial-gradient(circle,#fff 51%,transparent 53%),conic-gradient(#176bff 0 42%,#18a88c 42% 69%,#7561d5 69% 82%,#d5deea 82%); border-radius: 50%; }.experience-ring strong,.experience-ring small { grid-area: 1/1; }.experience-ring strong { margin-top: -12px; color: #176bff; font-size: 18px; }.experience-ring small { margin-top: 20px; color: #718299; font-size: 9px; }.experience-list { display: grid; gap: 8px; margin: 15px 0 0 108px; color: #63758c; font-size: 10px; }.experience-list span { position: relative; padding-left: 15px; }.experience-list i { position: absolute; left: 0; top: 4px; max-width: 9px; height: 7px; background: #176bff; border-radius: 2px; }
.matrix-plot { position: relative; height: 285px; margin-top: 20px; overflow: hidden; background: linear-gradient(90deg,rgba(236,241,247,.7) 50%,rgba(232,244,255,.8) 50%); border: 1px solid #e3eaf2; border-radius: 10px; }.axis-x,.axis-y { position: absolute; background: #cbd7e5; }.axis-x { right: 12px; left: 12px; top: 50%; height: 1px; }.axis-y { top: 12px; bottom: 12px; left: 50%; width: 1px; }.zone-label { position: absolute; top: 10px; right: 12px; color: #13846f; font-size: 10px; }.city-bubble { position: absolute; display: grid; place-items: center; color: #fff; background: rgba(23,107,255,.9); border: 4px solid rgba(255,255,255,.84); border-radius: 50%; box-shadow: 0 7px 17px rgba(31,87,164,.18); transform: translate(-50%,50%); }.city-bubble b,.city-bubble span { display: block; }.city-bubble b { font-size: 11px; }.city-bubble span { margin-top: -5px; font-size: 8px; }.city-bubble.green { background: #18a88c; }.city-bubble.violet { background: #7561d5; }.city-bubble.navy { background: #2c5b94; }.city-bubble.amber { background: #dda036; }.axis-label-x,.axis-label-y { position: absolute; color: #73849b; font-size: 9px; font-style: normal; }.axis-label-x { right: 12px; bottom: 7px; }.axis-label-y { left: 7px; top: 50%; transform: translate(-44%,-50%) rotate(-90deg); }
.signal-section { margin-top: 30px; }.section-heading { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 14px; }.signal-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 12px; }.signal-grid article { display: grid; min-height: 118px; grid-template-columns: auto 1fr auto; align-items: center; gap: 11px; padding: 16px; background: #fff; border: 1px solid #e1e8f0; border-radius: 13px; }.signal-icon { display: grid; width: 39px; height: 39px; place-items: center; color: #137f6b; background: #e6f7f1; border-radius: 10px; font-size: 17px; }.signal-icon.salary { color: #1767dc; background: #e9f2ff; }.signal-icon.skill { color: #6c55ca; background: #f0edfc; }.signal-icon.down { color: #d26870; background: #fff0f1; }.signal-grid small,.signal-grid strong,.signal-grid p { display: block; }.signal-grid small { color: #708198; font-size: 10px; }.signal-grid strong { margin-top: 5px; font-size: 14px; }.signal-grid p { margin: 4px 0 0; color: #6d7d91; font-size: 10px; }.signal-grid em { align-self: start; color: #13836d; font-size: 11px; font-style: normal; font-weight: 700; }.signal-grid em.down { color: #cf5d66; }.bottom-grid { grid-template-columns: .8fr 1.2fr; margin-top: 14px; }.ranking-card { height: 365px; }.ranking-table { display: grid; margin-top: 18px; }.ranking-table>div { display: grid; min-height: 52px; grid-template-columns: 1.7fr repeat(4,1fr); align-items: center; border-bottom: 1px solid #edf1f5; color: #455a74; font-size: 12px; }.ranking-table .table-head { min-height: 34px; color: #65768c; background: #f7f9fb; border: 0; border-radius: 6px; }.ranking-table>div>* { padding: 0 8px; }.ranking-table>div>span:first-child { display: flex; align-items: center; }.ranking-table b { display: inline-grid; width: 22px; height: 22px; margin-right: 8px; place-items: center; background: #f0f3f7; border-radius: 6px; }.ranking-table b.first { color: #fff; background: #1c6bdd; }.ranking-table strong { color: #1767dc; }.personal-cta { display: flex; align-items: center; justify-content: space-between; gap: 30px; margin-top: 14px; padding: 24px 28px; color: #fff; background: linear-gradient(120deg,#14325c,#1767dc); border-radius: 16px; box-shadow: 0 16px 30px rgba(21,72,142,.18); }.personal-cta p { color: #bbd4f5; }.personal-cta h2 { margin: 0 0 8px; font-size: 22px; }.personal-cta span { color: #d1e0f4; font-size: 13px; }.personal-cta button { color: #1767dc; background: #fff; box-shadow: none; white-space: nowrap; }
.market-ai-dialog { position: fixed; right: 24px; bottom: 24px; z-index: 950; display: flex; width: min(420px,calc(100vw - 32px)); height: min(590px,calc(100vh - 125px)); flex-direction: column; overflow: hidden; background: #fff; border: 1px solid #c9d8eb; border-radius: 15px; box-shadow: 0 24px 70px rgba(18,48,89,.24); }.market-ai-dialog>header { display: flex; align-items: center; gap: 10px; padding: 18px; }.market-ai-dialog>header>span { display: grid; width: 42px; height: 42px; place-items: center; color: #fff; background: linear-gradient(145deg,#153a6d,#176bff); border-radius: 12px; font-size: 12px; font-weight: 800; }.market-ai-dialog header small,.market-ai-dialog header strong { display: block; }.market-ai-dialog header small { color: #55708f; font-size: 9px; font-weight: 800; letter-spacing: .14em; }.market-ai-dialog header strong { margin-top: 4px; font-size: 19px; }.market-ai-dialog header i { width: 7px; height: 7px; margin-left: auto; background: #22af8e; border-radius: 50%; box-shadow: 0 0 0 4px #e1f7f1; }.market-ai-dialog header em { color: #17846e; font-size: 12px; font-style: normal; }.market-ai-dialog header button { display: grid; width: 29px; height: 29px; place-items: center; color: #61738a; background: #edf3fa; border: 0; border-radius: 8px; font-size: 20px; cursor: pointer; }.ai-message-list { display: grid; flex: 1; align-content: start; gap: 10px; min-height: 0; padding: 4px 18px 12px; overflow-y: auto; }.ai-message-list>div { max-width: 91%; padding: 12px 14px; border-radius: 5px 13px 13px; font-size: 13px; line-height: 1.65; }.ai-message-list .assistant { color: #415b78; background: #edf4fc; }.ai-message-list .user { justify-self: end; color: #fff; background: #1b66cc; border-radius: 13px 5px 13px 13px; }.ai-markdown :deep(h2),.ai-markdown :deep(h3) { margin: 14px 0 7px; color: #183b68; line-height: 1.35; }.ai-markdown :deep(h2:first-child),.ai-markdown :deep(h3:first-child) { margin-top: 0; }.ai-markdown :deep(h2) { font-size: 16px; }.ai-markdown :deep(h3) { font-size: 14px; }.ai-markdown :deep(p) { margin: 0 0 9px; }.ai-markdown :deep(p:last-child) { margin-bottom: 0; }.ai-markdown :deep(ul),.ai-markdown :deep(ol) { margin: 6px 0 11px; padding-left: 21px; }.ai-markdown :deep(li) { margin: 4px 0; }.ai-markdown :deep(strong) { color: #244d7c; }.ai-markdown :deep(blockquote) { margin: 11px 0 0; padding: 8px 10px; color: #61748b; background: rgba(255,255,255,.62); border-left: 3px solid #78a8e2; border-radius: 0 7px 7px 0; }.ai-markdown :deep(blockquote p) { margin: 0; }.ai-composer { margin: 0 18px 18px; padding: 11px 12px; background: #fff; border: 1px solid #cfdbea; border-radius: 11px; box-shadow: 0 6px 16px rgba(38,72,117,.05); }.ai-composer textarea { width: 100%; height: 48px; resize: none; border: 0; outline: 0; font-size: 13px; }.ai-composer>div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }.ai-composer span { color: #697b91; font-size: 10px; }.ai-composer button { padding: 8px 12px; color: #fff; background: #1767dc; border: 0; border-radius: 7px; font-size: 11px; font-weight: 700; cursor: pointer; }.ai-composer button:disabled { opacity: .65; }.ai-error { margin: 0 0 8px; color: #c75560; font-size: 11px; }.ai-launcher { position: fixed; right: 24px; bottom: 24px; z-index: 950; display: flex; align-items: center; gap: 9px; padding: 10px 14px 10px 10px; color: #fff; background: linear-gradient(135deg,#143864,#176bff); border: 1px solid rgba(255,255,255,.18); border-radius: 28px; box-shadow: 0 16px 38px rgba(19,69,140,.28); cursor: pointer; }.ai-launcher span { display: grid; width: 31px; height: 31px; place-items: center; background: rgba(255,255,255,.14); border-radius: 50%; font-size: 11px; font-weight: 800; }.ai-launcher b { font-size: 13px; }.ai-launcher i { width: 7px; height: 7px; background: #57ddb2; border-radius: 50%; }
@media (max-width: 1080px) { .market-hero { grid-template-columns: 1fr 420px; }.kpi-grid { grid-template-columns: repeat(2,1fr); }.market-detail-grid { grid-template-columns: 1fr 1fr; }.matrix-card { grid-column: 1/-1; }.signal-grid { grid-template-columns: repeat(2,1fr); } }
@media (max-width: 760px) { .market-page { width: calc(100% - 24px); padding: 26px 0 86px; }.market-hero { display: block; min-height: 0; }.market-hero h1 { font-size: 38px; }.hero-description { font-size: 14px; }.hero-actions { align-items: flex-start; flex-direction: column; }.hero-visual { height: 260px; margin-top: 14px; }.filter-card { grid-template-columns: 1fr 1fr; }.filter-submit { grid-column: 1/-1; }.primary-grid,.market-detail-grid,.bottom-grid { grid-template-columns: 1fr; }.dashboard-grid :deep(.panel),.ranking-card { height: auto; min-height: 350px; }.matrix-card { grid-column: auto; }.signal-grid { grid-template-columns: 1fr; }.personal-cta { align-items: flex-start; flex-direction: column; }.market-ai-dialog { right: 12px; bottom: 70px; width: calc(100vw - 24px); height: min(560px,calc(100vh - 105px)); }.ai-launcher { right: 14px; bottom: 72px; } }
@media (max-width: 460px) { .market-hero h1 { font-size: 33px; }.kpi-grid,.filter-card { grid-template-columns: 1fr; }.filter-submit { grid-column: auto; }.histogram { gap: 5px; }.histogram span { font-size: 9px; }.section-heading { align-items: flex-start; flex-direction: column; gap: 5px; }.ranking-card { overflow-x: auto; }.ranking-table { min-width: 650px; }.market-ai-dialog>header { padding: 15px; }.ai-composer>div { align-items: stretch; flex-direction: column; }.ai-composer button { width: 100%; } }
@media (prefers-reduced-motion: reduce) { *,*::before,*::after { scroll-behavior: auto!important; transition-duration: .01ms!important; animation-duration: .01ms!important; } }

/* Readability baseline: card metadata and secondary numbers remain legible. */
.data-card header p,.section-heading p { font-size: 12px; }.data-card header>span,.section-heading>span { color: #52657d; font-size: 13px; }.histogram b { color: #43566f; font-size: 13px; }.histogram span { color: #4e6179; font-size: 12px; }.salary-summary small { color: #5c6f87; font-size: 12px; }.salary-summary strong { font-size: 19px; }.structure-heading { color: #435870; font-size: 13px; }.structure-legend,.experience-list { color: #4f627a; font-size: 12px; }.experience-ring small { color: #53667d; font-size: 11px; }.zone-label { font-size: 12px; }.city-bubble b { font-size: 13px; }.city-bubble span { font-size: 10px; }.axis-label-x,.axis-label-y { color: #53667d; font-size: 11px; }.signal-grid small { color: #52657d; font-size: 12px; }.signal-grid strong { font-size: 16px; }.signal-grid p { color: #566981; font-size: 12px; }.signal-grid em { font-size: 13px; }.ranking-table>div { color: #344a64; font-size: 14px; }.ranking-table .table-head { color: #52657d; }.ai-composer span { color: #53667d; font-size: 12px; }.ai-composer button { font-size: 13px; }
</style>

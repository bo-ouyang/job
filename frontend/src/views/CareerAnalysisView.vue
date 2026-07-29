<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { careerAPI } from "@/api/career";
import careerMockData from "@/data/careerMockData";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const loading = ref(false);
const generating = ref(false);
const overview = ref(careerMockData);
const pricing = ref({});
const question = ref("");
const asking = ref(false);
const answer = ref("");
const errorMessage = ref("");
const filters = reactive({ city: "杭州", industry: "互联网 / AI", direction: "AI 产品经理" });

const reportPrice = computed(() => pricing.value.careerReport?.amount || "");
const questionPrice = computed(() => pricing.value.careerQuestion?.amount || "");
const syntheticDimensionCount = computed(
  () => overview.value?.dataStatus?.syntheticDimensions?.length || 0,
);
const generateLabel = computed(() => {
  if (generating.value) return "正在生成…";
  if (!authStore.isAuthenticated) return "登录后生成职业分析";
  return reportPrice.value ? `重新分析 · ¥${reportPrice.value}` : "重新生成职业分析";
});

const loadPersonalizedData = async () => {
  if (!authStore.isAuthenticated) return;
  loading.value = true;
  const [overviewResult, pricingResult] = await Promise.allSettled([
    careerAPI.getOverview({ ...filters }),
    careerAPI.getPricing(),
  ]);
  if (overviewResult.status === "fulfilled" && overviewResult.value?.data) {
    overview.value = overviewResult.value.data;
  }
  if (pricingResult.status === "fulfilled" && pricingResult.value?.data) {
    pricing.value = pricingResult.value.data;
  }
  loading.value = false;
};

const requireLogin = (action) => router.push({
  name: "career-analysis",
  query: { login: "true", redirect: "/career-analysis", action },
});

const generateReport = async () => {
  if (!authStore.isAuthenticated) return requireLogin("generate");
  if (generating.value) return;
  generating.value = true;
  errorMessage.value = "";
  try {
    const key = globalThis.crypto?.randomUUID?.() || `career-${Date.now()}`;
    await careerAPI.generateReport({ filters: { ...filters } }, key);
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || "分析任务创建失败，请稍后重试。";
  } finally {
    generating.value = false;
  }
};

const sendQuestion = async () => {
  const content = question.value.trim();
  if (!content || asking.value) return;
  if (!authStore.isAuthenticated) return requireLogin("career-question");
  asking.value = true;
  errorMessage.value = "";
  try {
    const key = globalThis.crypto?.randomUUID?.() || `career-question-${Date.now()}`;
    const response = await careerAPI.askQuestion(
      { question: content, filters: { ...filters } },
      key,
    );
    answer.value = response?.data?.answer || "问题已提交，AI 顾问正在整理建议。";
    question.value = "";
  } catch (error) {
    errorMessage.value = error?.response?.data?.detail || "问题发送失败，请稍后重试。";
  } finally {
    asking.value = false;
  }
};

onMounted(loadPersonalizedData);
</script>

<template>
  <main class="career-page">
    <header class="career-hero">
      <div><p class="eyebrow"><i /> PERSONAL CAREER REPORT</p><h1 v-if="authStore.isAuthenticated">你好，{{ overview.profile.name }}。<br><span>这是你的职业机会地图。</span></h1><h1 v-else>把你的专业和能力，<br><span>放进真实市场里分析。</span></h1><p>{{ authStore.isAuthenticated ? "基于你的学校、专业、课程、技能与当前市场数据生成。" : "登录并完善资料后，我们会回答适合方向、城市选择、能力差距和下一步行动。" }}</p></div>
      <div class="hero-actions"><span v-if="authStore.isAuthenticated">市场证据：{{ overview.evidence.sampleSize }} · {{ overview.evidence.updatedAt }}</span><button data-test="generate-analysis" :disabled="generating" @click="generateReport">{{ generateLabel }}</button></div>
    </header>

    <section v-if="!authStore.isAuthenticated" class="guest-intro">
      <div class="intro-copy"><p>PERSONALIZED, EVIDENCE-BASED</p><h2>职业分析如何帮助你</h2><span>不是简单生成一段建议，而是把你的真实资料与岗位市场逐项对齐。</span></div>
      <div class="intro-grid"><article><b>01</b><h3>发现适合方向</h3><p>给出 Top 3 方向、匹配理由和市场证据。</p></article><article><b>02</b><h3>选择目标城市</h3><p>比较岗位量、薪资、增长率和竞争程度。</p></article><article><b>03</b><h3>识别技能差距</h3><p>对照目标岗位要求，定位优先补全能力。</p></article><article><b>04</b><h3>形成行动计划</h3><p>把结论转化为 30/60/90 天可执行任务。</p></article></div>
      <button data-test="guest-start" @click="generateReport">登录并完善个人资料 →</button>
    </section>

    <template v-else>
      <section class="profile-strip">
        <div class="completion"><strong>{{ overview.profile.completion }}%</strong><span>画像完整度</span></div>
        <div class="profile-tags"><span>{{ overview.profile.school }}</span><span>{{ overview.profile.major }}</span><span>{{ overview.profile.graduation }}</span></div>
        <p>本次分析综合个人资料、简历确认字段与当前市场数据。</p>
        <button @click="router.push('/my/profile')">完善资料 →</button>
      </section>

      <p v-if="syntheticDimensionCount" class="data-notice" data-test="career-source">
        <span>i</span> 分析部分使用测试数据（{{ syntheticDimensionCount }} 个维度），真实用户资料未被替换；完成 AI 分析后将自动更新。
      </p>

      <form class="analysis-filter" @submit.prevent="loadPersonalizedData"><label><span>目标城市</span><select v-model="filters.city"><option>杭州</option><option>上海</option><option>深圳</option><option>北京</option></select></label><label><span>目标行业</span><select v-model="filters.industry"><option>互联网 / AI</option><option>智能制造</option><option>新能源</option></select></label><label><span>职业方向</span><select v-model="filters.direction"><option>AI 产品经理</option><option>数据产品经理</option><option>商业分析师</option></select></label><button :disabled="loading">{{ loading ? "更新中…" : "更新结果" }}</button></form>

      <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>

      <div class="career-layout">
        <div class="career-main">
          <section><div class="section-heading"><div><p>TOP DIRECTIONS</p><h2>推荐职业方向</h2></div><span>匹配度综合资料、技能和市场机会</span></div><div class="direction-grid"><article v-for="(item, index) in overview.directions" :key="item.title" :class="{ featured: index === 0 }"><header><span>{{ index === 0 ? "首选方向" : `方向 ${index + 1}` }}</span><strong>{{ item.match }}<small>%</small></strong></header><h3>{{ item.title }}</h3><p>{{ item.reason }}</p><div><span v-for="tag in item.tags" :key="tag">{{ tag }}</span></div></article></div></section>

          <section class="analysis-grid"><article class="analysis-card city-card"><div class="section-heading"><div><p>CITY COMPARISON</p><h2>城市机会对比</h2></div></div><div class="city-table"><div class="table-head"><span>城市</span><span>岗位量</span><span>月薪中位数</span><span>增长</span><span>竞争度</span></div><div v-for="item in overview.cities" :key="item.city"><strong>{{ item.city }}</strong><span>{{ item.jobs }}</span><span>{{ item.salary }}</span><em>{{ item.growth }}</em><span>{{ item.competition }}</span></div></div></article>
            <article class="analysis-card skill-card"><div class="section-heading"><div><p>SKILL GAP</p><h2>能力与目标差距</h2></div></div><div class="skill-list"><div v-for="item in overview.skills" :key="item.name"><span>{{ item.name }}</span><i><b :style="{ width: `${item.current}%` }" /><em :style="{ left: `${item.target}%` }" /></i><strong>{{ item.current }} / {{ item.target }}</strong></div></div></article></section>

          <section class="analysis-card plan-card"><div class="section-heading"><div><p>ACTION PLAN</p><h2>30 / 60 / 90 天行动计划</h2></div></div><div class="plan-grid"><article v-for="(item, index) in overview.plan" :key="item.period"><span>{{ index + 1 }}</span><div><small>{{ item.period }}</small><h3>{{ item.title }}</h3><ul><li v-for="action in item.items" :key="action">{{ action }}</li></ul></div></article></div></section>
        </div>

        <aside class="career-ai-card"><header><span>AI</span><div><small>职业顾问</small><strong>基于你的报告提问</strong></div><i /></header><div class="context"><span>当前上下文</span><p>{{ filters.direction }} · {{ filters.city }}<br>{{ overview.evidence.sampleSize }}市场样本</p></div><div class="assistant-message">我可以解释推荐理由、比较城市选择，或帮你细化行动计划。</div><p v-if="answer" class="assistant-answer">{{ answer }}</p><form @submit.prevent="sendQuestion"><textarea v-model="question" placeholder="输入你的职业问题…" /><div><span data-test="career-ai-price">{{ questionPrice ? `预计 ¥${questionPrice}/次` : "价格以发送前确认为准" }}</span><button :disabled="asking">{{ asking ? "…" : "↑" }}</button></div></form></aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.career-page { width: min(1420px,calc(100% - 32px)); margin: 0 auto; padding: 42px 0 88px; color: #17253d; }.career-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 36px; padding: 20px 6px 34px; }.eyebrow,.section-heading p,.intro-copy>p { margin: 0 0 10px; color: #55708f; font-size: 10px; font-weight: 800; letter-spacing: .16em; }.eyebrow i { display: inline-block; width: 6px; height: 6px; margin: 0 7px 1px 0; background: #20aa91; border-radius: 50%; }.career-hero h1 { margin: 0; color: #13233c; font-size: clamp(36px,4vw,52px); line-height: 1.1; letter-spacing: -.05em; }.career-hero h1 span { color: #1767dc; }.career-hero>div>p:last-child { color: #5d7088; font-size: 14px; }.hero-actions { display: flex; align-items: center; gap: 12px; }.hero-actions>span { color: #687a91; font-size: 11px; }.hero-actions button,.guest-intro>button,.analysis-filter button { padding: 11px 16px; color: #fff; background: #1767dc; border: 0; border-radius: 9px; font-size: 13px; font-weight: 700; cursor: pointer; }.hero-actions button:disabled { opacity: .6; }
.guest-intro { padding: 34px; background: #fff; border: 1px solid #e0e7f0; border-radius: 18px; box-shadow: 0 18px 50px rgba(36,67,107,.06); }.intro-copy h2 { margin: 0; font-size: 28px; }.intro-copy>span { display: block; margin-top: 9px; color: #60728a; font-size: 14px; }.intro-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin: 28px 0; }.intro-grid article { min-height: 175px; padding: 20px; background: #f7f9fc; border: 1px solid #e6ebf2; border-radius: 13px; }.intro-grid b { color: #1767dc; font-size: 12px; }.intro-grid h3 { margin: 25px 0 9px; font-size: 17px; }.intro-grid p { color: #63758c; font-size: 12px; line-height: 1.7; }.guest-intro>button { display: block; margin: 0 auto; padding-inline: 24px; }
.profile-strip,.analysis-filter,.analysis-card,.direction-grid article,.career-ai-card { background: #fff; border: 1px solid #e0e7f0; border-radius: 14px; box-shadow: 0 8px 25px rgba(42,67,101,.04); }.profile-strip { display: grid; grid-template-columns: auto 1fr 1.2fr auto; align-items: center; gap: 20px; padding: 16px 18px; }.completion { display: flex; align-items: baseline; gap: 8px; }.completion strong { color: #1767dc; font-size: 24px; }.completion span,.profile-strip p { color: #5d7088; font-size: 11px; }.profile-tags { display: flex; flex-wrap: wrap; gap: 6px; }.profile-tags span { padding: 5px 8px; color: #445e7e; background: #f0f5fb; border-radius: 5px; font-size: 10px; }.profile-strip button { color: #1767dc; background: transparent; border: 0; font-size: 11px; cursor: pointer; }.analysis-filter { display: grid; grid-template-columns: repeat(3,1fr) auto; align-items: end; gap: 12px; margin-top: 12px; padding: 14px 16px; }.analysis-filter label { display: grid; gap: 6px; }.analysis-filter label span { color: #5d7088; font-size: 11px; }.analysis-filter select { padding: 9px 10px; color: #344760; background: #f8fafc; border: 1px solid #dfe6ef; border-radius: 7px; font-size: 12px; }.error-message { padding: 10px 12px; color: #b64e58; background: #fff0f1; border-radius: 8px; font-size: 12px; }
.data-notice { display:flex; align-items:center; gap:8px; margin:12px 2px 0; color:#7a6539; font-size:13px; }.data-notice span { display:grid; width:18px; height:18px; place-items:center; color:#9b701c; background:#fff3d5; border-radius:50%; font-size:11px; font-weight:800; }
.career-layout { display: grid; grid-template-columns: minmax(0,1fr) 315px; align-items: start; gap: 17px; margin-top: 30px; }.career-main { min-width: 0; }.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 15px; margin-bottom: 14px; }.section-heading p { margin-bottom: 5px; }.section-heading h2 { margin: 0; color: #1e314b; font-size: 19px; }.section-heading>span { color: #65778e; font-size: 11px; }.direction-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }.direction-grid article { min-height: 260px; padding: 18px; }.direction-grid article.featured { border-color: #80adf0; box-shadow: 0 12px 28px rgba(29,105,215,.1); }.direction-grid header { display: flex; justify-content: space-between; }.direction-grid header>span { padding: 4px 7px; color: #1767dc; background: #e9f2ff; border-radius: 5px; font-size: 10px; }.direction-grid header strong { color: #1767dc; font-size: 25px; }.direction-grid header small { font-size: 10px; }.direction-grid h3 { margin: 32px 0 9px; font-size: 18px; }.direction-grid>article>p { min-height: 62px; color: #5f7188; font-size: 12px; line-height: 1.7; }.direction-grid article>div { display: flex; flex-wrap: wrap; gap: 6px; }.direction-grid article>div span { padding: 5px 7px; color: #445e7e; background: #f0f5fb; border-radius: 5px; font-size: 10px; }.analysis-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 13px; margin-top: 26px; }.analysis-card { padding: 19px; }.city-table { display: grid; }.city-table>div { display: grid; min-height: 45px; grid-template-columns: repeat(5,1fr); align-items: center; border-bottom: 1px solid #edf1f5; color: #596d85; font-size: 11px; }.city-table .table-head { min-height: 32px; color: #687a91; background: #f7f9fb; border: 0; }.city-table em { color: #159277; font-style: normal; }.skill-list { display: grid; gap: 15px; margin-top: 20px; }.skill-list>div { display: grid; grid-template-columns: 80px 1fr 55px; align-items: center; gap: 10px; color: #52677f; font-size: 11px; }.skill-list i { position: relative; height: 7px; background: #e9eef4; border-radius: 7px; }.skill-list i b { display: block; height: 100%; background: #1767dc; border-radius: inherit; }.skill-list i em { position: absolute; top: -3px; width: 2px; height: 13px; background: #18a88c; }.plan-card { margin-top: 13px; }.plan-grid { display: grid; grid-template-columns: repeat(3,1fr); gap: 25px; margin-top: 22px; }.plan-grid article { display: flex; gap: 12px; }.plan-grid article>span { display: grid; width: 29px; height: 29px; flex: 0 0 auto; place-items: center; color: #1767dc; background: #eaf2ff; border-radius: 50%; font-size: 11px; font-weight: 800; }.plan-grid small { color: #61748c; font-size: 10px; }.plan-grid h3 { margin: 5px 0 8px; font-size: 14px; }.plan-grid ul { margin: 0; padding-left: 16px; color: #66788e; font-size: 11px; line-height: 1.8; }
.career-ai-card { position: sticky; top: 92px; min-height: 575px; overflow: hidden; }.career-ai-card>header { display: flex; align-items: center; gap: 10px; padding: 17px; color: #fff; background: linear-gradient(135deg,#173c70,#176bff); }.career-ai-card>header>span { display: grid; width: 36px; height: 36px; place-items: center; background: rgba(255,255,255,.14); border-radius: 10px; font-size: 10px; font-weight: 800; }.career-ai-card header small,.career-ai-card header strong { display: block; }.career-ai-card header small { color: #d2e2f8; font-size: 9px; }.career-ai-card header strong { margin-top: 3px; font-size: 12px; }.career-ai-card header i { width: 7px; height: 7px; margin-left: auto; background: #41d4a5; border-radius: 50%; }.context { margin: 13px; padding: 11px; background: #f1f5fa; border-radius: 8px; }.context span { color: #62758d; font-size: 10px; }.context p { margin: 4px 0 0; color: #425b76; font-size: 11px; line-height: 1.6; }.assistant-message,.assistant-answer { margin: 12px; padding: 12px; color: #405b77; background: #edf4fc; border-radius: 5px 11px 11px; font-size: 12px; line-height: 1.7; }.assistant-answer { background: #e8f7f3; }.career-ai-card form { position: absolute; right: 13px; bottom: 13px; left: 13px; padding: 10px; border: 1px solid #dbe4ee; border-radius: 9px; }.career-ai-card textarea { width: 100%; height: 60px; resize: none; border: 0; outline: 0; font-size: 12px; }.career-ai-card form>div { display: flex; align-items: center; justify-content: space-between; }.career-ai-card form span { color: #687a90; font-size: 10px; }.career-ai-card form button { display: grid; width: 29px; height: 29px; place-items: center; color: #fff; background: #1767dc; border: 0; border-radius: 7px; }
@media(max-width:1080px){.career-layout{grid-template-columns:1fr}.career-ai-card{position:static;min-height:400px}.career-ai-card form{position:static;margin:13px}.direction-grid{grid-template-columns:1fr 1fr}.direction-grid article:last-child{grid-column:1/-1}.profile-strip{grid-template-columns:auto 1fr auto}.profile-strip>p{grid-column:1/-1}}
@media(max-width:760px){.career-page{width:calc(100% - 24px);padding:26px 0 85px}.career-hero{align-items:flex-start;flex-direction:column}.career-hero h1{font-size:34px}.hero-actions{align-items:flex-start;flex-wrap:wrap}.intro-grid,.direction-grid,.analysis-grid,.plan-grid{grid-template-columns:1fr}.direction-grid article:last-child{grid-column:auto}.profile-strip{grid-template-columns:1fr auto}.profile-tags,.profile-strip>p{grid-column:1/-1}.analysis-filter{grid-template-columns:1fr}.city-card{overflow-x:auto}.city-table{min-width:600px}}

/* Readability baseline for muted values and evidence inside cards. */
.eyebrow,.section-heading p,.intro-copy>p { font-size: 12px; }.hero-actions>span { color: #52657d; font-size: 13px; }.intro-grid b,.intro-grid p { font-size: 14px; }.completion span,.profile-strip p { color: #4f637b; font-size: 13px; }.profile-tags span,.profile-strip button { font-size: 12px; }.analysis-filter label span { color: #4f637b; font-size: 13px; }.analysis-filter select { font-size: 14px; }.section-heading>span { color: #52657d; font-size: 13px; }.direction-grid header>span,.direction-grid article>div span { font-size: 12px; }.direction-grid header small { font-size: 12px; }.direction-grid>article>p { color: #4e627a; font-size: 14px; }.city-table>div { color: #40566f; font-size: 13px; }.city-table .table-head { color: #52657d; }.skill-list>div { color: #40566f; font-size: 13px; }.plan-grid small { color: #52657d; font-size: 12px; }.plan-grid ul { color: #52657d; font-size: 13px; }.career-ai-card header small { font-size: 11px; }.career-ai-card header strong { font-size: 14px; }.context span,.context p { font-size: 12px; }.assistant-message,.assistant-answer,.career-ai-card textarea { font-size: 14px; }.career-ai-card form span { color: #52657d; font-size: 12px; }
</style>

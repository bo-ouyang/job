<script setup>
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { analysisAPI } from "@/api/analysis";

const router = useRouter();
const searchQuery = ref("");
const isAiMode = ref(false); // AI search mode toggle
const snapshotLoading = ref(false);
const snapshot = ref({
  total_jobs: 0,
  salary: [],
  skills: [],
  industries: [],
});

const topSkill = computed(() => snapshot.value.skills?.[0]?.name || "-");
const topIndustry = computed(() => snapshot.value.industries?.[0]?.name || "-");
const topSalaryBand = computed(() => {
  const salary = snapshot.value.salary || [];
  if (!salary.length) return "-";
  const maxBand = salary.reduce((best, item) => {
    if (!best || (item.value || 0) > (best.value || 0)) return item;
    return best;
  }, null);
  return maxBand?.name || "-";
});
const topSkills = computed(() => (snapshot.value.skills || []).slice(0, 6));
const leadingIndustries = computed(() => (snapshot.value.industries || []).slice(0, 4));
const salaryBreakdown = computed(() => {
  const total = Number(snapshot.value.total_jobs || 0) || 1;
  return (snapshot.value.salary || [])
    .slice(0, 5)
    .map((item) => ({
      ...item,
      percent: Math.min(100, Math.round(((item.value || 0) / total) * 100)),
    }));
});

const goToAnalysis = () => {
  router.push({ name: "home", hash: "#analysis-panel" });
};

const handleSearch = () => {
  if (searchQuery.value.trim()) {
    if (isAiMode.value) {
      router.push({ name: "jobs", query: { ai_q: searchQuery.value } });
    } else {
      router.push({ name: "jobs", query: { q: searchQuery.value } });
    }
  }
};

const fetchSnapshot = async () => {
  snapshotLoading.value = true;
  try {
    const res = await analysisAPI.getJobStats({});
    if (res?.data) {
      snapshot.value = {
        total_jobs: res.data.total_jobs || 0,
        salary: res.data.salary || [],
        skills: res.data.skills || [],
        industries: res.data.industries || [],
      };
    }
  } catch (error) {
    console.error("Failed to fetch home snapshot", error);
  } finally {
    snapshotLoading.value = false;
  }
};

onMounted(() => {
  fetchSnapshot();
});
</script>

<template>
  <div class="home">
    <section class="hero">
      <div class="hero-content">
        <h1>洞察职场，<span class="gradient-text">掌握未来</span></h1>
        <p class="hero-subtitle">基于大数据的大学生就业技能分析平台，助你精准定位理想职位。</p>
        
        <div class="search-tabs">
          <button :class="{ active: !isAiMode }" @click="isAiMode = false; searchQuery = ''">精准搜索</button>
          <button :class="{ active: isAiMode, 'ai-tab': true }" @click="isAiMode = true; searchQuery = ''">✨ AI 智能匹配</button>
        </div>
        
        <div class="search-box" :class="{ 'ai-focus': isAiMode }">
          <input 
            type="text" 
            v-model="searchQuery" 
            :placeholder="isAiMode ? '请输入您一整段口语化的求职期望 (例如：想在杭州找Go开发，不要外包，薪资大于20k...)' : '搜索职位 (如: Python开发, 数据分析师...)'"
            @keyup.enter="handleSearch"
          >
          <button class="action-btn" :class="{ 'ai-btn': isAiMode }" @click="handleSearch">
             {{ isAiMode ? 'AI 发现' : '搜索' }}
          </button>
        </div>

        <div class="hero-actions">
          <button class="ghost-btn" @click="goToAnalysis">查看全站分析</button>
          <button class="ghost-btn" @click="router.push('/career-compass')">进入职业罗盘</button>
        </div>
      </div>
    </section>

    <section class="pulse-strip">
      <article class="pulse-item">
        <span>市场热技能</span>
        <strong>{{ snapshotLoading ? "..." : topSkill }}</strong>
      </article>
      <article class="pulse-item">
        <span>主导行业</span>
        <strong>{{ snapshotLoading ? "..." : topIndustry }}</strong>
      </article>
      <article class="pulse-item">
        <span>薪资高峰带</span>
        <strong>{{ snapshotLoading ? "..." : topSalaryBand }}</strong>
      </article>
      <article class="pulse-item">
        <span>有效岗位样本</span>
        <strong>{{ snapshotLoading ? "..." : Number(snapshot.total_jobs || 0).toLocaleString() }}</strong>
      </article>
    </section>

    <section class="snapshot">
      <div class="snapshot-head">
        <h2>全站数据快照</h2>
        <p>基于实时职位样本生成，帮助你快速判断市场热度</p>
        <div class="industry-chips">
          <span v-for="item in leadingIndustries" :key="item.name">{{ item.name }}</span>
        </div>
      </div>

      <div class="snapshot-grid">
        <article class="snapshot-card">
          <span class="snapshot-label">岗位总量</span>
          <strong class="snapshot-value">
            {{ snapshotLoading ? "..." : Number(snapshot.total_jobs || 0).toLocaleString() }}
          </strong>
        </article>
        <article class="snapshot-card">
          <span class="snapshot-label">当前热门技能</span>
          <strong class="snapshot-value">{{ snapshotLoading ? "..." : topSkill }}</strong>
        </article>
        <article class="snapshot-card">
          <span class="snapshot-label">热度行业</span>
          <strong class="snapshot-value">{{ snapshotLoading ? "..." : topIndustry }}</strong>
        </article>
        <article class="snapshot-card">
          <span class="snapshot-label">高峰薪资带</span>
          <strong class="snapshot-value">{{ snapshotLoading ? "..." : topSalaryBand }}</strong>
        </article>
      </div>

      <div class="insight-panels">
        <article class="insight-panel">
          <h3>Top 技能需求</h3>
          <ul>
            <li v-for="item in topSkills" :key="item.name">
              <span>{{ item.name }}</span>
              <b>{{ item.value }}</b>
            </li>
          </ul>
        </article>
        <article class="insight-panel">
          <h3>薪资分布占比</h3>
          <ul>
            <li v-for="item in salaryBreakdown" :key="item.name">
              <span>{{ item.name }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${item.percent}%` }"></div>
              </div>
              <b>{{ item.percent }}%</b>
            </li>
          </ul>
        </article>
      </div>
    </section>

    <section class="features">
      <div class="feature-card" @click="goToAnalysis">
        <div class="icon">📊</div>
        <h3>全站分析面板</h3>
        <p>一键下探到分析模块，查看技能热度与薪资结构。</p>
      </div>
      <div class="feature-card" @click="router.push('/jobs')">
        <div class="icon">💼</div>
        <h3>海量职位</h3>
        <p>汇聚各大平台招聘信息，一站式浏览筛选。</p>
      </div>
      <div class="feature-card" @click="router.push('/companies')">
        <div class="icon">🏢</div>
        <h3>名企风向</h3>
        <p>关注顶尖企业的招聘动态和人才偏好。</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 4.5rem;
  padding-bottom: 6rem;
}

.pulse-strip {
  max-width: 1280px;
  margin: -2rem auto 0;
  padding: 0 2rem;
  width: 100%;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.9rem;
}

.pulse-item {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 14px;
  padding: 0.85rem 1rem;
  background:
    linear-gradient(120deg, rgba(34, 211, 238, 0.08), rgba(99, 102, 241, 0.08)),
    rgba(15, 23, 42, 0.5);
}

.pulse-item span {
  display: block;
  font-size: 0.8rem;
  color: rgba(203, 213, 225, 0.85);
}

.pulse-item strong {
  display: block;
  margin-top: 0.35rem;
  font-size: 1.05rem;
  color: #f8fafc;
}

.snapshot {
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  padding: 0 2rem;
}

.snapshot-head {
  margin-bottom: 1.25rem;
}

.snapshot-head h2 {
  font-size: 2rem;
  margin: 0;
  color: var(--color-heading);
}

.snapshot-head p {
  margin-top: 0.4rem;
  color: var(--color-text-mute);
}

.industry-chips {
  display: flex;
  gap: 0.55rem;
  flex-wrap: wrap;
  margin-top: 0.75rem;
}

.industry-chips span {
  font-size: 0.78rem;
  line-height: 1;
  padding: 0.4rem 0.6rem;
  border-radius: 999px;
  color: #dbeafe;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(96, 165, 250, 0.35);
}

.snapshot-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1rem;
}

.snapshot-card {
  background: var(--color-card-bg);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem;
}

.snapshot-label {
  display: block;
  color: var(--color-text-mute);
  font-size: 0.9rem;
}

.snapshot-value {
  margin-top: 0.4rem;
  display: block;
  font-size: 1.55rem;
  color: #f8fafc;
  line-height: 1.1;
}

.insight-panels {
  margin-top: 1rem;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1rem;
}

.insight-panel {
  background: var(--color-card-bg);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: var(--radius-md);
  padding: 1rem 1.1rem;
}

.insight-panel h3 {
  margin: 0 0 0.75rem;
  font-size: 1rem;
  color: #e2e8f0;
}

.insight-panel ul {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.insight-panel li {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 0.75rem;
  align-items: center;
  color: #cbd5e1;
}

.bar-track {
  height: 8px;
  min-width: 140px;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 999px;
  overflow: hidden;
}

.bar-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #22d3ee, #6366f1);
}

/* 惊艳深空渐变 Hero 区域 */
.hero {
  height: 65vh;
  min-height: 500px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0 1.5rem;
  position: relative;
  overflow: hidden;
}

/* 顶部背景微光点缀 */
.hero::before {
  content: '';
  position: absolute;
  top: -30%;
  left: 50%;
  transform: translateX(-50%);
  width: 80vw;
  height: 80vw;
  background: radial-gradient(circle, hsla(var(--color-primary-h), var(--color-primary-s), var(--color-primary-l), 0.15) 0%, transparent 60%);
  z-index: -1;
  pointer-events: none;
}

.hero h1 {
  font-size: 4.5rem;
  font-weight: 800;
  margin-bottom: 1.5rem;
  letter-spacing: -0.04em;
  line-height: 1.1;
  color: var(--color-heading);
}

.gradient-text {
  background: linear-gradient(135deg, #0ea5e9, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: inline-block;
}

.hero-subtitle {
  font-size: 1.25rem;
  color: var(--color-text-mute);
  max-width: 650px;
  margin: 0 auto 3rem;
  line-height: 1.7;
}

.hero-actions {
  margin-top: 1rem;
  display: flex;
  justify-content: center;
  gap: 0.8rem;
}

.ghost-btn {
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.45);
  border-radius: 999px;
  padding: 0.55rem 1.1rem;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.2s ease;
}

.ghost-btn:hover {
  border-color: rgba(56, 189, 248, 0.75);
  color: #f8fafc;
  transform: translateY(-1px);
}



/* 具有呼吸感的超级搜索框 */
.search-tabs {
  display: flex;
  justify-content: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.search-tabs button {
  background: transparent;
  border: none;
  color: var(--color-text-mute);
  font-size: 1.1rem;
  font-weight: 600;
  padding: 0.5rem 1rem;
  cursor: pointer;
  position: relative;
  transition: color var(--transition-fast);
}

.search-tabs button::after {
  content: '';
  position: absolute;
  bottom: 0; left: 50%;
  transform: translateX(-50%);
  width: 0; height: 3px;
  background: var(--color-primary);
  border-radius: 2px;
  transition: width var(--transition-fast);
}

.search-tabs button.active { color: var(--color-text); }
.search-tabs button.active::after { width: 80%; }
.search-tabs button.ai-tab.active { color: #818cf8; }
.search-tabs button.ai-tab.active::after { background: linear-gradient(90deg, #38bdf8, #818cf8); }

.search-box {
  display: flex;
  max-width: 700px;
  width: 100%;
  margin: 0 auto;
  background: var(--color-glass-bg);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: var(--radius-huge);
  padding: 0.5rem;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  transition: all var(--transition-normal);
}

.search-box:focus-within {
  border-color: rgba(14, 165, 233, 0.5);
  box-shadow: 0 0 0 4px rgba(14, 165, 233, 0.15), 0 10px 40px rgba(0, 0, 0, 0.5);
  transform: translateY(-2px);
}

.search-box.ai-focus:focus-within {
  border-color: rgba(129, 140, 248, 0.6);
  box-shadow: 0 0 0 4px rgba(129, 140, 248, 0.15), 0 10px 40px rgba(0, 0, 0, 0.5);
}

.search-box input {
  flex: 1;
  background: transparent;
  border: none;
  padding: 1rem 1.5rem;
  color: var(--color-text);
  font-size: 1.05rem;
  outline: none;
}

.search-box input::placeholder {
  color: rgba(255, 255, 255, 0.3);
  font-size: 0.95rem;
}

.search-box .action-btn {
  background: var(--color-primary);
  color: #fff;
  padding: 0 2.5rem;
  border-radius: var(--radius-huge);
  font-size: 1.05rem;
  font-weight: 600;
  letter-spacing: 0.5px;
  transition: all var(--transition-fast);
  box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3);
  border: none;
  cursor: pointer;
}

.search-box .action-btn.ai-btn {
  background: linear-gradient(135deg, #38bdf8 0%, #818cf8 100%);
  box-shadow: 0 4px 15px rgba(129, 140, 248, 0.4);
}

.search-box .action-btn:hover {
  filter: brightness(1.1);
  box-shadow: 0 6px 20px rgba(14, 165, 233, 0.5);
}

.search-box .action-btn.ai-btn:hover {
  box-shadow: 0 6px 20px rgba(129, 140, 248, 0.6);
}

.search-box .action-btn:active {
  transform: scale(0.97);
}

/* 功能特性 悬浮瀑布卡片 (Hover Uplift) */
.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 2.5rem;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 2rem;
  width: 100%;
}

.feature-card {
  background: var(--color-card-bg);
  border: 1px solid rgba(255, 255, 255, 0.05);
  padding: 2.5rem 2rem;
  border-radius: var(--radius-lg);
  transition: all var(--transition-normal);
  cursor: pointer;
  position: relative;
  overflow: hidden;
  box-shadow: var(--shadow-md);
}

/* 高级折射边缘内发光 */
.feature-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  border-radius: inherit;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.02);
  pointer-events: none;
}

.feature-card:hover {
  transform: translateY(-8px);
  border-color: rgba(14, 165, 233, 0.3);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4), 0 0 20px rgba(14, 165, 233, 0.1);
  background: hsla(222, 47%, 16%, 0.8);
}

.icon {
  font-size: 3rem;
  margin-bottom: 1.5rem;
  display: inline-block;
  transition: transform var(--transition-normal);
}

.feature-card:hover .icon {
  transform: scale(1.1) rotate(-5deg);
}

.feature-card h3 {
  font-size: 1.6rem;
  margin-bottom: 0.75rem;
  color: var(--color-heading);
}

.feature-card p {
  color: var(--color-text-mute);
  font-size: 1.05rem;
  line-height: 1.6;
}

@media (max-width: 768px) {
  .pulse-strip {
    grid-template-columns: 1fr 1fr;
    padding: 0 1rem;
    margin-top: -2.5rem;
  }
  .hero-actions {
    flex-wrap: wrap;
  }
  .snapshot {
    padding: 0 1rem;
  }
  .snapshot-grid {
    grid-template-columns: 1fr 1fr;
  }
  .insight-panels {
    grid-template-columns: 1fr;
  }
  .bar-track {
    min-width: 90px;
  }
  .hero h1 { font-size: 3rem; }
  .hero-subtitle { font-size: 1.1rem; }
  .search-box { flex-direction: column; border-radius: var(--radius-md); padding: 0; }
  .search-box input { border-radius: var(--radius-md) var(--radius-md) 0 0; padding: 1.2rem; }
  .search-box button { border-radius: 0 0 var(--radius-md) var(--radius-md); padding: 1.2rem; }
}
</style>

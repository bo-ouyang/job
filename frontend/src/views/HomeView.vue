<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';

const router = useRouter();
const searchQuery = ref('');
const isAiMode = ref(false); // 💡 新增：AI 模式锁定开关

const handleSearch = () => {
  if (searchQuery.value.trim()) {
    if (isAiMode.value) {
      // 携带 ai_q 路由参数，进入 AI 接管模式
      router.push({ name: 'jobs', query: { ai_q: searchQuery.value } });
    } else {
      // 普通 SQL/ES 硬匹配模式
      router.push({ name: 'jobs', query: { q: searchQuery.value } });
    }
  }
};
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
      </div>
    </section>

    <section class="features">
      <div class="feature-card" @click="router.push('/analysis')">
        <div class="icon">📊</div>
        <h3>技能图谱</h3>
        <p>可视化的技能需求分析，了解市场真正需要什么。</p>
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
  gap: 6rem;
  padding-bottom: 6rem;
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
  .hero h1 { font-size: 3rem; }
  .hero-subtitle { font-size: 1.1rem; }
  .search-box { flex-direction: column; border-radius: var(--radius-md); padding: 0; }
  .search-box input { border-radius: var(--radius-md) var(--radius-md) 0 0; padding: 1.2rem; }
  .search-box button { border-radius: 0 0 var(--radius-md) var(--radius-md); padding: 1.2rem; }
}
</style>

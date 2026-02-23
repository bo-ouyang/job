<script setup>
import { ref } from 'vue';
import { useRouter } from 'vue-router';

const router = useRouter();
const searchQuery = ref('');

const handleSearch = () => {
  if (searchQuery.value.trim()) {
    router.push({ name: 'jobs', query: { q: searchQuery.value } });
  }
};
</script>

<template>
  <div class="home">
    <section class="hero">
      <div class="hero-content">
        <h1>洞察职场，<span class="gradient-text">掌握未来</span></h1>
        <p class="hero-subtitle">基于大数据的大学生就业技能分析平台，助你精准定位理想职位。</p>
        
        <div class="search-box">
          <input 
            type="text" 
            v-model="searchQuery" 
            placeholder="搜索职位 (如: Python开发, 数据分析师...)"
            @keyup.enter="handleSearch"
          >
          <button @click="handleSearch">搜索</button>
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
  gap: 4rem;
  padding-bottom: 4rem;
}

.hero {
  height: 60vh;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 0 1rem;
}

.hero h1 {
  font-size: 4rem;
  margin-bottom: 1.5rem;
  letter-spacing: -0.05em;
}

.gradient-text {
  background: linear-gradient(135deg, var(--color-primary), var(--color-accent));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero-subtitle {
  font-size: 1.25rem;
  color: var(--color-text-mute);
  max-width: 600px;
  margin: 0 auto 3rem;
}

.search-box {
  display: flex;
  max-width: 500px;
  margin: 0 auto;
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  border-radius: 50px;
  padding: 0.5rem;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.search-box:focus-within {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 4px rgba(56, 189, 248, 0.2);
}

.search-box input {
  flex: 1;
  background: transparent;
  border: none;
  padding: 0.8rem 1.5rem;
  color: var(--color-text);
  font-size: 1rem;
  outline: none;
}

.search-box button {
  background: var(--color-primary);
  color: #0f172a;
  padding: 0 2rem;
  border-radius: 40px;
  font-weight: 600;
  transition: transform 0.2s;
}

.search-box button:hover {
  transform: scale(1.05);
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 2rem;
  width: 100%;
}

.feature-card {
  background: var(--color-background-soft);
  border: 1px solid var(--color-border);
  padding: 2rem;
  border-radius: 1rem;
  transition: transform 0.3s, border-color 0.3s;
  cursor: pointer;
}

.feature-card:hover {
  transform: translateY(-5px);
  border-color: var(--color-primary);
}

.icon {
  font-size: 2.5rem;
  margin-bottom: 1rem;
}

.feature-card h3 {
  font-size: 1.5rem;
  margin-bottom: 0.5rem;
}

.feature-card p {
  color: var(--color-text-mute);
}
</style>

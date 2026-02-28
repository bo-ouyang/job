<script setup>
import { nextTick, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import HomeView from "@/views/HomeView.vue";
import JobAnalysis from "@/views/JobAnalysis.vue";

const route = useRoute();

const scrollToAnalysis = async () => {
  await nextTick();
  const el = document.getElementById("analysis-panel");
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
};

onMounted(async () => {
  if (route.hash === "#analysis-panel") {
    await scrollToAnalysis();
  }
});

watch(
  () => route.hash,
  async (hash) => {
    if (hash === "#analysis-panel") {
      await scrollToAnalysis();
    }
  },
);
</script>

<template>
  <div class="insights-hub">
    <HomeView />
    <section id="analysis-panel" class="analysis-section">
      <div class="analysis-intro">
        <h2>全站分析模块</h2>
        <p>筛选行业、城市与关键词，查看技能趋势和薪资分布。</p>
      </div>
      <JobAnalysis />
    </section>
  </div>
</template>

<style scoped>
.analysis-section {
  margin-top: 1.5rem;
  scroll-margin-top: 86px;
}

.analysis-intro {
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 2rem;
}

.analysis-intro h2 {
  margin: 0;
  font-size: 2rem;
  color: #f8fafc;
}

.analysis-intro p {
  margin: 0.5rem 0 0;
  color: #94a3b8;
}

@media (max-width: 768px) {
  .analysis-intro {
    padding: 0 1rem;
  }
}
</style>

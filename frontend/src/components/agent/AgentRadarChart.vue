<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RadarChart } from "echarts/charts";
import { TooltipComponent } from "echarts/components";
import { init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

use([RadarChart, TooltipComponent, CanvasRenderer]);

const props = defineProps({ skills: { type: Array, required: true } });
const chartElement = ref(null);
let chart = null;

function renderChart() {
  if (!chartElement.value) return;
  if (!chart) chart = init(chartElement.value);
  chart.setOption({
    animationDuration: 700,
    radar: {
      indicator: props.skills.map((skill) => ({ name: skill.name, max: 100 })),
      radius: "64%",
      splitNumber: 4,
      axisName: { color: "#6f7890", fontSize: 11 },
      splitArea: { areaStyle: { color: ["rgba(116,87,232,.02)", "rgba(116,87,232,.05)"] } },
      splitLine: { lineStyle: { color: "#e8eaf1" } },
      axisLine: { lineStyle: { color: "#e8eaf1" } },
    },
    series: [{
      type: "radar",
      data: [
        {
          value: props.skills.map((skill) => skill.target),
          name: "岗位期望",
          lineStyle: { color: "#c7cbd8", width: 1.5, type: "dashed" },
          itemStyle: { color: "#b8bdca" },
          areaStyle: { color: "rgba(180,185,199,.06)" },
        },
        { value: props.skills.map((skill) => skill.score), name: "当前能力" },
      ],
      symbol: "circle",
      symbolSize: 5,
      lineStyle: { color: "#7457e8", width: 2 },
      itemStyle: { color: "#7457e8" },
      areaStyle: { color: "rgba(116,87,232,.18)" },
    }],
  });
}

function resizeChart() { chart?.resize(); }
onMounted(() => { nextTick(renderChart); window.addEventListener("resize", resizeChart); });
watch(() => props.skills, renderChart, { deep: true });
onBeforeUnmount(() => { window.removeEventListener("resize", resizeChart); chart?.dispose(); chart = null; });
</script>

<template><div ref="chartElement" class="radar-chart" /></template>

<style scoped>
.radar-chart { width: 100%; height: 275px; }
</style>

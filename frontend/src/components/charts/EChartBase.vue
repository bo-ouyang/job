<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { BarChart, HeatmapChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from "echarts/components";

echarts.use([CanvasRenderer, BarChart, HeatmapChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent]);

const props = defineProps({ option: { type: Object, required: true } });
const chartRef = ref(null);
let chart = null;

function render() {
  if (!chartRef.value) return;
  chart ||= echarts.init(chartRef.value);
  chart.setOption(props.option, true);
}
function resize() { chart?.resize(); }
onMounted(async () => { await nextTick(); render(); window.addEventListener("resize", resize); });
watch(() => props.option, render, { deep: true });
onUnmounted(() => { window.removeEventListener("resize", resize); chart?.dispose(); chart = null; });
</script>

<template><div ref="chartRef" class="echart-base" /></template>

<style scoped>
.echart-base { width: 100%; height: 100%; min-height: 220px; }
</style>

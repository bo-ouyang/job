<script setup>
import { computed } from "vue";
import EChartBase from "./EChartBase.vue";
const props = defineProps({ data: { type: Object, required: true } });
const option = computed(() => ({
  color: props.data.series.map((item) => item.color), tooltip: { trigger: "axis" },
  legend: { top: 0, left: 0, itemWidth: 12, itemHeight: 8, textStyle: { color: "#52647a", fontSize: 13 } },
  grid: { top: 36, left: 38, right: 12, bottom: 28 },
  xAxis: { type: "category", data: props.data.years, boundaryGap: false, axisLabel: { color: "#64748b" }, axisLine: { lineStyle: { color: "#e5edf6" } } },
  yAxis: { type: "value", min: 60, max: 190, axisLabel: { color: "#64748b" }, splitLine: { lineStyle: { color: "#edf2f8" } } },
  series: props.data.series.map((item) => ({ name: item.name, type: "line", smooth: true, symbol: "circle", symbolSize: 5, data: item.values, lineStyle: { width: 2, color: item.color }, itemStyle: { color: item.color } })),
}));
</script>
<template><EChartBase :option="option" /></template>

<script setup>
import { computed } from "vue";
import EChartBase from "./EChartBase.vue";
const props = defineProps({ data: { type: Array, required: true } });
const option = computed(() => ({ tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, grid: { top: 8, left: 82, right: 38, bottom: 24 }, xAxis: { type: "value", max: 30, axisLabel: { color: "#52647a", fontSize: 12 }, splitLine: { lineStyle: { color: "#edf2f8" } } }, yAxis: { type: "category", inverse: true, data: props.data.map((item) => item.name), axisLabel: { color: "#263851", fontSize: 13 } }, series: [{ type: "bar", barWidth: 14, data: props.data.map((item) => ({ value: item.value, itemStyle: { color: "#4d91ee", borderRadius: [0, 7, 7, 0] } })), label: { show: true, position: "right", color: "#263851", fontSize: 13, fontWeight: 600, formatter: "{c}" } }] }));
</script>
<template><EChartBase :option="option" /></template>

<script setup>
import { computed } from "vue";
import EChartBase from "./EChartBase.vue";
const props = defineProps({ data: { type: Object, required: true } });
const option = computed(() => ({ tooltip: { position: "top", formatter: (params) => `${props.data.rows[params.value[1]]} · ${props.data.columns[params.value[0]]}<br/>匹配度：${params.value[2]}%` }, grid: { top: 28, left: 126, right: 40, bottom: 20 }, xAxis: { type: "category", data: props.data.columns, axisLabel: { color: "#334155", fontSize: 10, interval: 0 }, splitArea: { show: true } }, yAxis: { type: "category", data: props.data.rows, axisLabel: { color: "#334155", fontSize: 10 }, splitArea: { show: true } }, visualMap: { min: 40, max: 100, calculable: false, orient: "vertical", right: 0, top: "center", itemHeight: 120, text: ["高", "低"], textStyle: { color: "#64748b", fontSize: 10 }, inRange: { color: ["#eef4fd", "#bdd6f7", "#70a8ee", "#2169dd"] } }, series: [{ type: "heatmap", data: props.data.values.map((value, index) => [index % 5, Math.floor(index / 5), value]), label: { show: true, color: "#1e3a6b", fontSize: 11 }, itemStyle: { borderColor: "#fff", borderWidth: 1 } }] }));
</script>
<template><EChartBase :option="option" /></template>

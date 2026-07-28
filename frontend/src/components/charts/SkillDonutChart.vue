<script setup>
import { computed } from "vue";
import EChartBase from "./EChartBase.vue";
const props = defineProps({ data: { type: Array, required: true } });
const option = computed(() => ({ tooltip: { trigger: "item", formatter: "{b}: {d}%", textStyle: { fontSize: 13 } }, legend: { orient: "vertical", right: 0, top: "middle", itemWidth: 11, itemHeight: 11, textStyle: { color: "#394c64", fontSize: 13 } }, series: [{ type: "pie", radius: ["48%", "72%"], center: ["32%", "52%"], avoidLabelOverlap: true, label: { show: true, position: "center", formatter: "总需求占比\n{big|100%}", color: "#52647a", fontSize: 13, rich: { big: { color: "#0f172a", fontSize: 20, fontWeight: 700, lineHeight: 29 } } }, data: props.data, color: ["#266fe8", "#16b8b0", "#7c59e8", "#f4bd43", "#c2798b", "#9ab8ee"] }] }));
</script>
<template><EChartBase :option="option" /></template>

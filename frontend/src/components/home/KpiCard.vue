<script setup>
defineProps({ item: { type: Object, required: true } });
</script>
<template><article class="kpi"><div><span class="label">{{ item.label }} <i>i</i></span><strong>{{ item.value }}</strong><small>{{ item.note }} <em>{{ item.delta }}</em></small></div><div class="kpi-icon" :class="item.tone">{{ item.icon }}</div></article></template>
<style scoped>
.kpi { display:flex; justify-content:space-between; align-items:center; min-height:120px; padding:18px 20px; border:1px solid #e7eef7; border-radius:15px; background:rgba(255,255,255,.92); box-shadow:0 7px 24px rgba(39,87,145,.06); }
.label { display:block; color:#34425e; font-size:15px; font-weight:650; }.label i { display:inline-grid; place-items:center; width:15px; height:15px; border:1px solid #8797ad; border-radius:50%; font-size:10px; font-style:normal; color:#6f8097; margin-left:3px; }
strong { display:block; margin:8px 0 4px; color:#12203d; font-size:27px; letter-spacing:-.03em; font-weight:750; } small { color:#60738b; font-size:13px; } em { color:#168a73; font-size:13px; font-style:normal; font-weight:700; margin-left:5px; }.kpi-icon { display:grid; place-items:center; width:58px; height:58px; border-radius:17px; font-size:27px; font-weight:700; }.blue{color:#2773ea;background:#eaf2ff}.mint{color:#0ca999;background:#e3f8f4}.violet{color:#7659e8;background:#f0ecff}.orange{color:#ea951f;background:#fff3df}
</style>

<script setup>
defineProps({ title: { type: String, required: true }, subtitle: { type: String, default: "" }, action: { type: String, default: "查看全部" } });
</script>

<template>
  <section class="panel">
    <header class="panel-head"><div><h2>{{ title }}</h2><span v-if="subtitle">{{ subtitle }}</span></div><button v-if="action">{{ action }} <b>›</b></button></header>
    <div class="panel-body"><slot /></div>
  </section>
</template>

<style scoped>
.panel { min-width: 0; background: rgba(255,255,255,.9); border: 1px solid #e7eef7; border-radius: 15px; box-shadow: 0 7px 24px rgba(39,87,145,.06); padding: 16px 18px; }
.panel-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom: 6px; }
.panel-head h2 { display:inline; margin:0; font-size:19px; color:#13203b; }
.panel-head span { margin-left:8px; color:#64758c; font-size:13px; }
.panel-head button { color:#2876e7; background:none; font-size:13px; white-space:nowrap; }
.panel-head button b { font-size:17px; vertical-align:-1px; font-weight:400; }
.panel-body { min-width:0; }
</style>

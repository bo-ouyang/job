<script setup>
defineProps({
  name: { type: String, default: "spark" },
  size: { type: Number, default: 18 },
});
</script>

<template>
  <svg class="agent-icon" :width="size" :height="size" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path v-if="name === 'spark'" d="m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7L12 2Zm7 14 .7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7L19 16Z" fill="currentColor" />
    <path v-else-if="name === 'arrow'" d="M5 12h13m-5-5 5 5-5 5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
    <path v-else-if="name === 'check'" d="m5 12 4 4L19 6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    <path v-else-if="name === 'upload'" d="M12 16V4m0 0L7 9m5-5 5 5M5 20h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
    <path v-else-if="name === 'file'" d="M6 3h8l4 4v14H6V3Zm8 0v5h4" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
    <path v-else-if="name === 'bookmark'" d="M6 4.5A1.5 1.5 0 0 1 7.5 3h9A1.5 1.5 0 0 1 18 4.5V21l-6-3.5L6 21V4.5Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" />
    <path v-else-if="name === 'send'" d="m3 11 18-8-7 18-3-7-8-3Z" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round" /><path v-if="name === 'send'" d="m11 14 4-5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" />
    <path v-else-if="name === 'menu'" d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
    <circle v-else-if="name === 'dot'" cx="12" cy="12" r="4" fill="currentColor" />
    <path v-else d="M12 3a9 9 0 1 0 9 9" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
  </svg>
</template>

<style scoped>
.agent-icon { display: block; flex: 0 0 auto; }
</style>

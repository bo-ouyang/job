<script setup>
import AgentConversationPanel from "@/components/agent/AgentConversation.vue";

defineOptions({ name: "AgentConversation" });
</script>

<template>
  <main class="conversation-view"><AgentConversationPanel /></main>
</template>

<style scoped>
.conversation-view { width: min(100% - 32px, 720px); min-height: 100vh; margin: 0 auto; padding: 32px 0; }
</style>

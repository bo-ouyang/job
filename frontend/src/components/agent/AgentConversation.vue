<script setup>
import { computed, nextTick, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { agentSuggestions, runStages } from "@/data/agentMockData";
import { useAgentStore } from "@/stores/agent";
import AgentIcon from "./AgentIcon.vue";

const store = useAgentStore();
const route = useRoute();
const router = useRouter();
const input = ref("");
const messagesElement = ref(null);

async function submit(text = input.value) {
  if (!text.trim()) return;
  input.value = "";
  try {
    const result = await store.sendMessage(text);
    if (result?.conversationId && result.conversationId !== "mock" && route.params.conversationId !== result.conversationId) {
      await router.replace({ name: "agent-conversation", params: { conversationId: result.conversationId } });
    }
  } catch {
    // Store exposes the user-facing error state.
  }
}
function onKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
}
watch(() => store.messages.length, () => nextTick(() => { if (messagesElement.value) messagesElement.value.scrollTop = messagesElement.value.scrollHeight; }));
const connectionLabel = computed(() => ({
  idle: "待命",
  connecting: "连接中",
  streaming: "实时分析",
  reconnecting: "重连中",
  recovering: "恢复中",
  paused: "等待回复",
  closed: "已同步",
  failed: "连接失败",
}[store.connectionState] || "在线"));
const recentToolEvents = computed(() => store.runEvents.filter((event) => ["tool_started", "tool_completed"].includes(event.event)).slice(-4));
const composerDisabled = computed(() => (
  store.runState !== "waiting" && (!store.capabilitiesLoaded || !store.featureAvailable)
));
const composerPlaceholder = computed(() => {
  if (store.runState === "waiting") return "补充 Agent 需要的信息...";
  if (!store.capabilitiesLoaded) return "正在确认 Agent 可用状态...";
  if (!store.featureAvailable) return "当前账号暂未开放新分析";
  return "输入你想探索的职业问题...";
});
function renderContent(content) {
  return DOMPurify.sanitize(marked.parse(String(content || ""), { breaks: true }));
}
</script>

<template>
  <section class="conversation-panel">
    <div class="conversation-header">
      <div class="agent-orb"><AgentIcon name="spark" :size="20" /></div>
      <div><p class="eyebrow">AI CAREER COPILOT</p><h2>你的职业探索助手</h2></div>
       <span class="live-status" :class="store.connectionState"><i /> {{ connectionLabel }}</span>
    </div>
    <div ref="messagesElement" class="messages">
      <div v-for="message in store.messages" :key="message.id" class="message-row" :class="message.role">
        <div v-if="message.role === 'assistant'" class="message-avatar"><AgentIcon name="spark" :size="15" /></div>
        <div class="message-content" :class="message.message_type"><div class="message-body" v-html="renderContent(message.content)" /><time>{{ message.time }}</time></div>
        <div v-if="message.role === 'user'" class="user-avatar">LY</div>
      </div>
      <div v-if="store.isThinking" class="message-row assistant"><div class="message-avatar"><AgentIcon name="spark" :size="15" /></div><div class="message-content thinking"><i /><i /><i /></div></div>
    </div>
    <div v-if="store.runState === 'running'" class="run-card">
      <div class="run-heading"><span class="run-spinner" /><strong>正在生成你的专属方案</strong><span>{{ store.activeStage + 1 }}/{{ runStages.length }}</span></div>
      <div v-for="(stage, index) in runStages" :key="stage.id" class="run-stage" :class="{ active: index === store.activeStage, done: index < store.activeStage }"><span class="stage-dot"><AgentIcon v-if="index < store.activeStage" name="check" :size="11" /></span><span>{{ stage.label }}</span><small>{{ stage.detail }}</small></div>
      <div v-for="event in recentToolEvents" :key="`${event.event_id}-${event.event}`" class="tool-event"><AgentIcon :name="event.event === 'tool_completed' ? 'check' : 'spark'" :size="11" /><span>{{ event.data?.tool || '市场分析工具' }}</span><small>{{ event.event === 'tool_completed' ? `${event.data?.sample_size || 0} 个样本` : '查询中' }}</small></div>
      <button class="cancel-run" @click="store.cancelRun">停止分析</button>
    </div>
    <div v-else-if="store.runState === 'complete'" class="complete-note"><AgentIcon name="check" :size="15" /> 方案已更新 · 你可以继续向我提问</div>
    <div v-else-if="store.runState === 'waiting'" class="waiting-note">Agent 需要你补充一项信息，请直接回复上方问题。</div>
    <div v-else-if="store.runState === 'failed'" class="error-note">分析未完成：{{ store.error || '数据或模型服务暂时不可用' }}</div>
    <div v-else-if="store.runState === 'cancelled'" class="waiting-note">本次分析已取消，你可以重新提出问题。</div>
    <div v-if="store.error && store.runState !== 'failed'" class="error-note">{{ store.error }}</div>
    <div class="suggestions"><span>你可以问我</span><button v-for="suggestion in agentSuggestions" :key="suggestion" :disabled="!store.capabilitiesLoaded && store.runState !== 'waiting'" @click="submit(suggestion)">{{ suggestion }} <AgentIcon name="arrow" :size="13" /></button></div>
    <form class="composer" @submit.prevent="submit()"><textarea v-model="input" rows="1" :disabled="composerDisabled" :placeholder="composerPlaceholder" @keydown="onKeydown" /><button type="submit" aria-label="发送" :disabled="!input.trim() || store.isThinking || composerDisabled"><AgentIcon name="send" :size="17" /></button></form>
    <p class="privacy-note">AI 生成内容仅供参考 · 对话将保存用于会话恢复，并可能由配置的模型服务处理</p>
  </section>
</template>

<style scoped>
.conversation-panel { display: flex; flex-direction: column; height: 100%; min-height: 650px; background: #fff; border: 1px solid #e9e8f1; border-radius: 22px; box-shadow: 0 20px 55px rgba(51, 44, 92, .07); overflow: hidden; }
.message-body { padding: 12px 13px; color: #4b5264; white-space: normal; background: #f7f7fb; border-radius: 4px 14px 14px 14px; font-size: 12px; line-height: 1.75; }.message-body :deep(p) { margin: 0 0 7px; }.message-body :deep(p:last-child) { margin-bottom: 0; }.message-body :deep(ul),.message-body :deep(ol) { margin: 6px 0; padding-left: 18px; }.user .message-body { color: #fff; background: #7457e8; border-radius: 14px 4px 14px 14px; }.tool-event { display: flex; align-items: center; gap: 7px; margin-top: 8px; padding-top: 8px; color: #736a91; border-top: 1px dashed #e8e2f8; font-size: 9px; }.tool-event small { margin-left: auto; color: #aaa2bb; }.cancel-run { width: 100%; margin-top: 11px; padding: 7px; color: #8c6598; background: #fff; border: 1px solid #eadff0; border-radius: 8px; font-size: 9px; }.waiting-note,.error-note { margin: 0 19px 13px; padding: 9px 11px; border-radius: 9px; font-size: 10px; }.waiting-note { color: #8a681e; background: #fff8e8; }.error-note { color: #a74755; background: #fff0f2; }.live-status.failed { color: #b94c5b; }
.conversation-header { display: flex; align-items: center; gap: 11px; padding: 21px 22px; border-bottom: 1px solid #f0eff4; }.conversation-header h2 { font-size: 15px; margin: 1px 0 0; letter-spacing: -.2px; }.eyebrow { color: #8b84aa; font-size: 9px; font-weight: 800; letter-spacing: 1.4px; }.agent-orb,.message-avatar { display: grid; place-items: center; color: #fff; background: linear-gradient(135deg,#a77cf6,#6953dd); box-shadow: 0 6px 15px rgba(116,87,232,.24); }.agent-orb { width: 37px; height: 37px; border-radius: 13px; }.live-status { margin-left: auto; color: #54a889; font-size: 11px; }.live-status i { display: inline-block; width: 6px; height: 6px; margin-right: 4px; border-radius: 50%; background: #55c598; }.messages { flex: 1; min-height: 280px; padding: 23px 19px; overflow: auto; }.message-row { display: flex; gap: 9px; align-items: flex-start; margin-bottom: 21px; }.message-row.user { justify-content: flex-end; }.message-avatar,.user-avatar { width: 27px; height: 27px; flex: 0 0 27px; border-radius: 9px; }.user-avatar { display: grid; place-items: center; color: #6252bb; background: #eeeafd; font-size: 9px; font-weight: 800; }.message-content { max-width: 78%; }.message-content p { padding: 12px 13px; color: #4b5264; background: #f7f7fb; border-radius: 4px 14px 14px 14px; font-size: 12px; line-height: 1.75; }.user .message-content p { color: #fff; background: #7457e8; border-radius: 14px 4px 14px 14px; }.message-content time { display: block; margin-top: 4px; color: #b0afba; font-size: 9px; }.user .message-content time { text-align: right; }.thinking { display: flex; gap: 4px; align-items: center; height: 37px; padding: 0 13px; background: #f7f7fb; border-radius: 4px 14px 14px 14px; }.thinking i { width: 5px; height: 5px; border-radius: 50%; background: #a99de3; animation: bounce 1s infinite alternate; }.thinking i:nth-child(2) { animation-delay: .18s; }.thinking i:nth-child(3) { animation-delay: .36s; }@keyframes bounce { to { transform: translateY(-4px); opacity: .4; } }
.run-card { margin: 0 18px 14px; padding: 14px; border: 1px solid #e5ddff; border-radius: 14px; background: #fbfaff; }.run-heading { display: flex; align-items: center; gap: 8px; color: #43338e; font-size: 11px; }.run-heading > span:last-child { margin-left: auto; color: #988cbf; font-size: 10px; }.run-spinner { width: 12px; height: 12px; border: 2px solid #ddd5ff; border-top-color: #7457e8; border-radius: 50%; animation: spin .8s linear infinite; }@keyframes spin { to { transform: rotate(360deg); } }.run-stage { display: flex; align-items: center; gap: 7px; margin-top: 10px; color: #aaa7b8; font-size: 10px; }.run-stage small { margin-left: auto; font-size: 9px; }.run-stage.active { color: #7457e8; font-weight: 700; }.run-stage.done { color: #58ae8e; }.stage-dot { display: grid; place-items: center; width: 15px; height: 15px; border: 1px solid currentColor; border-radius: 50%; }.complete-note { display: flex; gap: 6px; align-items: center; margin: 0 19px 13px; padding: 9px 11px; color: #3a9476; background: #effaf5; border-radius: 9px; font-size: 10px; }.suggestions { padding: 0 19px 13px; }.suggestions > span { display: block; margin-bottom: 8px; color: #a09eaa; font-size: 10px; }.suggestions button { display: inline-flex; align-items: center; gap: 6px; margin: 0 5px 5px 0; padding: 7px 9px; color: #716c82; background: #fafafd; border: 1px solid #ecebf2; border-radius: 7px; font-size: 10px; transition: .2s; }.suggestions button:hover { color: #7457e8; border-color: #cfc5ff; background: #f7f4ff; }.composer { display: flex; gap: 9px; margin: 0 17px; padding: 8px 8px 8px 12px; border: 1px solid #e5e3ec; border-radius: 13px; transition: .2s; }.composer:focus-within { border-color: #9d8bf0; box-shadow: 0 0 0 3px rgba(116,87,232,.08); }.composer textarea { flex: 1; min-width: 0; resize: none; border: 0; outline: 0; color: #525968; font-size: 11px; line-height: 22px; }.composer textarea::placeholder { color: #b7b5c0; }.composer button { display: grid; place-items: center; width: 31px; height: 31px; align-self: center; color: #fff; background: #7457e8; border-radius: 9px; }.composer button:disabled { cursor: default; opacity: .35; }.privacy-note { padding: 12px 18px 15px; color: #bbb9c3; text-align: center; font-size: 9px; }
@media (max-width: 700px) { .conversation-panel { min-height: 620px; border-radius: 16px; }.conversation-header { padding: 17px; }.messages { padding: 18px 14px; }.suggestions { padding: 0 14px 10px; }.composer { margin: 0 13px; } }
@media (max-width: 700px) { .conversation-panel { min-height: calc(100dvh - 150px); max-height: calc(100dvh - 110px); }.conversation-header h2 { font-size: 14px; }.messages { min-height: 0; }.suggestions button,.composer textarea,.message-body { font-size: 12px; }.composer button,.cancel-run { min-width: 44px; min-height: 44px; } }
</style>

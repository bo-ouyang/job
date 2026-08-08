<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";

import { messagesAPI } from "@/api/messages";

const PAGE_SIZE = 20;
const router = useRouter();
const messages = ref([]);
const total = ref(0);
const loading = ref(true);
const loadingMore = ref(false);
const error = ref("");
const activeFilter = ref("all");
let requestGeneration = 0;
let activeRequestController = null;

const filters = [
  { key: "all", label: "全部" },
  { key: "unread", label: "未读" },
  { key: "resume", label: "简历" },
  { key: "career", label: "职业分析" },
];

const filterParams = () => {
  if (activeFilter.value === "unread") return { isRead: false };
  if (activeFilter.value === "resume" || activeFilter.value === "career") {
    return { category: activeFilter.value };
  }
  return {};
};

const dedupe = (items) => [...new Map(items.map((message) => [message.id, message])).values()];
const hasUnread = computed(() => messages.value.some((message) => !message.isRead));
const hasMore = computed(() => messages.value.length < total.value);
const empty = computed(() => !loading.value && !error.value && messages.value.length === 0);

const loadMessages = async ({ reset = false } = {}) => {
  if (!reset && (loading.value || loadingMore.value)) return;
  if (reset) {
    requestGeneration += 1;
    activeRequestController?.abort();
    activeRequestController = new AbortController();
  }
  const generation = requestGeneration;
  const controller = reset ? activeRequestController : null;
  if (reset) {
    loading.value = true;
    error.value = "";
  } else {
    loadingMore.value = true;
  }
  try {
    const response = await messagesAPI.list({
      ...filterParams(),
      skip: reset ? 0 : messages.value.length,
      limit: PAGE_SIZE,
    }, controller ? { signal: controller.signal } : undefined);
    if (generation !== requestGeneration) return;
    const page = response.data;
    total.value = page.total;
    messages.value = reset ? dedupe(page.items) : dedupe([...messages.value, ...page.items]);
  } catch (requestError) {
    if (generation !== requestGeneration || requestError?.name === "CanceledError" || requestError?.name === "AbortError") return;
    error.value = "加载失败，请检查网络后重试。";
  } finally {
    if (generation !== requestGeneration) return;
    loading.value = false;
    loadingMore.value = false;
  }
};

const retry = () => loadMessages({ reset: true });
const changeFilter = (filter) => {
  if (activeFilter.value === filter) return;
  activeFilter.value = filter;
  loadMessages({ reset: true });
};

const markAsRead = async (message) => {
  if (message.isRead) return;
  try {
    await messagesAPI.markAsRead(message.id);
    message.isRead = true;
    window.dispatchEvent(new CustomEvent("messages-read", { detail: { scope: "one" } }));
  } catch (_) {
    // A failed mutation must not pretend the message is read.
  }
};

const markAllAsRead = async () => {
  try {
    await messagesAPI.markAllAsRead();
    messages.value.forEach((message) => { message.isRead = true; });
    window.dispatchEvent(new CustomEvent("messages-read", { detail: { scope: "all" } }));
  } catch (_) {
    error.value = "标记已读失败，请稍后重试。";
  }
};

const safeId = (value) => {
  const id = String(value ?? "").trim();
  return /^[A-Za-z0-9_-]{1,128}$/.test(id) ? id : null;
};

const actionFor = (message) => {
  if (message.actionType !== "navigate") return null;
  const actionData = message.actionData || {};

  if (message.category === "resume" && message.sourceType === "ai_task") {
    const taskId = safeId(actionData.taskId || message.sourceId);
    return taskId ? { label: "查看简历解析", path: "/my/resume", query: { taskId } } : null;
  }
  if (message.category === "career" && message.sourceType === "agent_run") {
    const runId = safeId(actionData.runId || message.sourceId);
    return runId ? { label: "查看职业分析", path: "/career-analysis", query: { runId } } : null;
  }
  if (message.category === "career" && message.sourceType === "ai_task") {
    const taskId = safeId(actionData.taskId);
    return taskId ? { label: "查看职业分析", path: "/career-analysis", query: { taskId } } : null;
  }
  return null;
};

const statusMeta = (status) => {
  if (!status) return { label: "历史通知", icon: "i", tone: "neutral" };
  if (status === "completed") return { label: "已完成", icon: "✓", tone: "success" };
  if (status === "failed" || status === "cancelled") return { label: status === "cancelled" ? "已取消" : "处理失败", icon: "!", tone: "danger" };
  return { label: "处理中", icon: "…", tone: "pending" };
};

const openAction = async (message) => {
  await markAsRead(message);
  const action = actionFor(message);
  if (action) router.push({ path: action.path, query: action.query });
};

const onMessageClick = (message) => markAsRead(message);
const formatDate = (value) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString();
};

const onWebSocketMessage = (event) => {
  const payload = event.detail?.message || event.detail;
  if (payload?.type === "new_message") loadMessages({ reset: true });
};

onMounted(() => {
  window.addEventListener("ws-message", onWebSocketMessage);
  loadMessages({ reset: true });
});
onUnmounted(() => {
  // Prevent a late response from mutating an unmounted view and release the
  // active browser request when users navigate away mid-load.
  requestGeneration += 1;
  activeRequestController?.abort();
  activeRequestController = null;
  window.removeEventListener("ws-message", onWebSocketMessage);
});
</script>

<template>
  <section class="message-center" aria-labelledby="message-title">
    <header class="message-header">
      <div>
        <p class="eyebrow">通知与任务</p>
        <h1 id="message-title">消息中心</h1>
      </div>
      <button v-if="hasUnread" class="mark-all" type="button" @click="markAllAsRead">全部标为已读</button>
    </header>

    <div class="filters" role="tablist" aria-label="消息分类">
      <button
        v-for="filter in filters"
        :key="filter.key"
        :data-test="`filter-${filter.key}`"
        class="filter"
        :class="{ active: activeFilter === filter.key }"
        type="button"
        role="tab"
        :aria-selected="activeFilter === filter.key"
        @click="changeFilter(filter.key)"
      >{{ filter.label }}</button>
    </div>

    <div v-if="loading" class="skeleton-list" aria-label="消息加载中">
      <div v-for="index in 3" :key="index" class="skeleton-card"><span /><span /><span /></div>
    </div>
    <div v-else-if="error" class="message-state error-state" data-test="message-error" role="alert">
      <strong>加载失败</strong><span>{{ error }}</span>
      <button data-test="message-retry" type="button" @click="retry">重新加载</button>
    </div>
    <div v-else-if="empty" class="message-state empty">
      <strong>暂无消息</strong><span>简历解析和职业分析完成后，会在这里通知你。</span>
    </div>
    <div v-else class="message-list" aria-live="polite">
      <article
        v-for="message in messages"
        :key="message.id"
        class="msg-card"
        :class="{ unread: !message.isRead }"
        tabindex="0"
        @click="onMessageClick(message)"
        @keydown.enter.prevent="onMessageClick(message)"
      >
        <span class="status-icon" :class="statusMeta(message.status).tone" aria-hidden="true">{{ statusMeta(message.status).icon }}</span>
        <div class="message-content">
          <div class="message-meta">
            <h2>{{ message.title || "系统通知" }}</h2>
            <time :datetime="message.createdAt || undefined">{{ formatDate(message.createdAt) }}</time>
          </div>
          <p>{{ message.content }}</p>
          <div class="message-footer">
            <span class="status-tag" :class="statusMeta(message.status).tone">{{ statusMeta(message.status).label }}</span>
            <button
              v-if="actionFor(message)"
              :data-test="`message-action-${message.id}`"
              type="button"
              class="action-link"
              @click.stop="openAction(message)"
            >{{ actionFor(message).label }}</button>
          </div>
        </div>
        <span v-if="!message.isRead" class="unread-dot" aria-label="未读" />
      </article>
      <button v-if="hasMore" class="load-more" type="button" :disabled="loadingMore" @click="loadMessages()">
        {{ loadingMore ? "加载中…" : "加载更多" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.message-center { width: min(960px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 64px; color: #1b2d47; }
.message-header { display:flex; align-items:center; justify-content:space-between; gap:20px; margin-bottom:22px; }.eyebrow { margin:0 0 5px; color:#52739d; font-size:13px; font-weight:700; letter-spacing:.08em; }.message-header h1 { margin:0; font-size:30px; letter-spacing:-.03em; }.mark-all,.filter,.load-more,.action-link,.message-state button { font:inherit; cursor:pointer; }.mark-all { padding:9px 13px; color:#2563bf; background:#f2f7ff; border:1px solid #cfe0fb; border-radius:9px; font-size:14px; font-weight:700; }.filters { display:flex; gap:8px; padding:5px; margin-bottom:18px; overflow:auto; background:#eaf0f7; border-radius:11px; }.filter { flex:1 0 auto; padding:9px 14px; color:#667993; background:transparent; border:0; border-radius:8px; font-size:14px; font-weight:650; }.filter.active { color:#165fca; background:#fff; box-shadow:0 2px 6px rgba(33,69,110,.1); }.message-list,.skeleton-list { display:grid; gap:12px; }.msg-card { position:relative; display:flex; gap:14px; padding:19px; background:#fff; border:1px solid #dce6f1; border-radius:14px; box-shadow:0 4px 13px rgba(34,59,91,.035); outline:none; }.msg-card:hover,.msg-card:focus-visible { border-color:#76a7ed; box-shadow:0 0 0 3px rgba(38,112,222,.12); }.msg-card.unread { border-left:4px solid #2877dc; padding-left:16px; }.status-icon { display:grid; flex:none; width:31px; height:31px; place-items:center; border-radius:50%; font-weight:800; }.success { color:#138252; background:#dcf8e9; }.danger { color:#bf3b4b; background:#fde7e9; }.pending { color:#9b6200; background:#fff1ce; }.neutral { color:#61738b; background:#edf2f7; }.message-content { min-width:0; flex:1; }.message-meta { display:flex; align-items:start; justify-content:space-between; gap:16px; }.message-meta h2 { margin:0; color:#1c304d; font-size:16px; line-height:1.45; }.message-meta time { flex:none; color:#8493a7; font-size:12px; white-space:nowrap; }.message-content p { margin:7px 0 12px; color:#5b6e86; font-size:14px; line-height:1.65; overflow-wrap:anywhere; }.message-footer { display:flex; align-items:center; justify-content:space-between; gap:12px; }.status-tag { padding:3px 8px; border-radius:20px; font-size:12px; font-weight:700; }.action-link { padding:0; color:#216bd2; background:transparent; border:0; font-size:13px; font-weight:750; }.unread-dot { width:8px; height:8px; margin-top:6px; background:#e34f5c; border-radius:50%; }.message-state { display:grid; justify-items:center; gap:9px; padding:60px 20px; color:#61738b; background:#fff; border:1px solid #dbe5f0; border-radius:14px; text-align:center; }.message-state strong { color:#29405e; font-size:18px; }.error-state { border-color:#f2c7cc; }.error-state button { padding:8px 13px; color:#fff; background:#2a70d1; border:0; border-radius:8px; font-weight:700; }.skeleton-card { display:grid; gap:10px; padding:20px; background:#fff; border:1px solid #e3ebf3; border-radius:14px; }.skeleton-card span { display:block; height:13px; background:linear-gradient(90deg,#edf2f7,#f8fafc,#edf2f7); border-radius:6px; animation:pulse 1.2s infinite; }.skeleton-card span:nth-child(2) { width:70%; }.skeleton-card span:nth-child(3) { width:35%; }.load-more { justify-self:center; padding:10px 18px; color:#316dc2; background:#fff; border:1px solid #cfe0f6; border-radius:9px; font-weight:700; }.load-more:disabled { opacity:.65; cursor:wait; }@keyframes pulse { 50% { opacity:.55; } }@media (max-width:640px) { .message-center { width:min(100% - 24px,960px); padding-top:26px; }.message-header h1 { font-size:25px; }.message-header { align-items:start; }.mark-all { padding:8px 10px; font-size:12px; }.msg-card { padding:15px; gap:11px; }.message-meta { display:block; }.message-meta time { display:block; margin-top:4px; }.message-footer { align-items:start; flex-direction:column; gap:8px; }.filters { gap:3px; }.filter { padding:8px 10px; font-size:13px; } }@media (prefers-reduced-motion:reduce) { .skeleton-card span { animation:none; } }
</style>

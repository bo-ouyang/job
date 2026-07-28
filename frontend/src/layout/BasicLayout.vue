<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import ElNotification from "element-plus/es/components/notification/index.mjs";

import LoginModal from "@/components/LoginModal.vue";
import AiTaskPanel from "@/components/AiTaskPanel.vue";
import { messageAPI } from "@/api/message";
import { useAiTaskStore } from "@/stores/aiTask";
import { useAgentStore } from "@/stores/agent";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const authStore = useAuthStore();
const aiTaskStore = useAiTaskStore();
const agentStore = useAgentStore();
const showLoginModal = ref(false);
const unreadCount = ref(0);

const navItems = [
  { label: "行业全景", to: "/" },
  { label: "职业分析", to: "/career-analysis" },
];

const profileCompletion = computed(() => authStore.user?.profile_completion ?? 60);
const userName = computed(() => authStore.user?.username || authStore.user?.phone || "张同学");
const walletBalance = computed(() => Number(authStore.user?.balance || 0).toFixed(2));

let interval = null;
let ws = null;
let reconnectInterval = null;

const fetchUnreadCount = async () => {
  if (!authStore.isAuthenticated) return;
  try {
    const res = await messageAPI.getUnreadCount();
    unreadCount.value = Number(res.data || 0);
  } catch (error) {
    console.error("Failed to fetch unread count", error);
  }
};

const connectWebSocket = () => {
  const token = localStorage.getItem("token");
  if (!token) return;

  const baseUrl = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";
  const fullUrl = baseUrl.startsWith("/") ? `${window.location.origin}${baseUrl}` : baseUrl;
  const wsUrl = fullUrl.replace(/^http/, "ws") + `/ws/${token}`;
  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    if (reconnectInterval) {
      clearInterval(reconnectInterval);
      reconnectInterval = null;
    }
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "new_message") unreadCount.value += 1;

    if (data.type === "ai_task_completed" && data.data) {
      aiTaskStore.markCompleted(data.data.task_id, data.data, {
        featureKey: data.data.feature_key,
        executionTime: data.data.execution_time,
      });
      ElNotification({ title: "任务完成", message: data.data.message || "AI 任务已完成。", type: "success", duration: 5000 });
    }

    if (data.type === "ai_task_failed" && data.data) {
      aiTaskStore.markFailed(data.data.task_id, data.data.error, { featureKey: data.data.feature_key });
      ElNotification({ title: "任务失败", message: data.data.message || "AI 任务执行失败。", type: "error", duration: 8000 });
    }

    window.dispatchEvent(new CustomEvent("ws-message", { detail: data }));
  };

  ws.onclose = () => {
    if (!reconnectInterval) {
      reconnectInterval = setInterval(() => {
        if (authStore.isAuthenticated) connectWebSocket();
      }, 5000);
    }
  };

  ws.onerror = () => ws?.close();
};

const handleLogout = () => {
  if (confirm("确定退出登录吗？")) {
    authStore.logout();
    unreadCount.value = 0;
  }
};

const isActive = (item) => route.path === item.to || (item.to !== "/" && route.path.startsWith(item.to));

watch(
  () => route.query.login,
  (loginRequested) => {
    if (loginRequested === "true") showLoginModal.value = true;
  },
  { immediate: true },
);

onMounted(() => {
  fetchUnreadCount();
  interval = setInterval(fetchUnreadCount, 30000);
  if (authStore.isAuthenticated) {
    agentStore.loadCapabilities();
    connectWebSocket();
    aiTaskStore.fetchHistory();
  }
});

onUnmounted(() => {
  if (interval) clearInterval(interval);
  if (reconnectInterval) clearInterval(reconnectInterval);
  ws?.close();
});
</script>

<template>
  <div class="basic-layout">
    <header class="app-topbar">
      <div class="topbar-inner">
        <RouterLink to="/" class="brand" aria-label="返回行业全景">
          <span class="brand-symbol">途</span>
          <span class="brand-copy"><strong>职途</strong><small>CAREER INTELLIGENCE</small></span>
        </RouterLink>

        <nav class="primary-nav" aria-label="主导航">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :class="{ active: isActive(item) }"
          >{{ item.label }}</RouterLink>
        </nav>

        <div class="topbar-actions">
          <RouterLink v-if="authStore.isAuthenticated" to="/my/wallet" class="balance-link">
            <span>余额</span><strong>¥ {{ walletBalance }}</strong>
          </RouterLink>
          <RouterLink v-if="authStore.isAuthenticated" to="/my/messages" class="icon-link" aria-label="消息">
            ◌<b v-if="unreadCount">{{ unreadCount }}</b>
          </RouterLink>

          <details v-if="authStore.isAuthenticated" class="account-menu" data-test="account-entry">
            <summary>
              <span class="user-avatar">{{ userName.slice(0, 1) }}</span>
              <span class="user-copy"><strong>{{ userName }}</strong><small>资料完整度 {{ profileCompletion }}%</small></span>
              <span class="chevron">⌄</span>
            </summary>
            <div class="account-popover">
              <RouterLink to="/my/profile">个人资料</RouterLink>
              <RouterLink to="/my/resume">简历管理</RouterLink>
              <RouterLink to="/my/wallet">余额与账单</RouterLink>
              <button @click="handleLogout">退出登录</button>
            </div>
          </details>
          <button v-else class="login-link" data-test="account-entry" @click="showLoginModal = true">登录 / 注册</button>
        </div>
      </div>
    </header>

    <LoginModal :isOpen="showLoginModal" @close="showLoginModal = false" />
    <AiTaskPanel />

    <main class="app-main">
      <RouterView v-slot="{ Component, route: currentRoute }">
        <transition name="fade" mode="out-in">
          <keep-alive include="CareerCompass,MajorAnalysis">
            <component :is="Component" :key="currentRoute.path" />
          </keep-alive>
        </transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
.basic-layout { min-height: 100vh; color: #17253d; background: #f4f7fa; }
.app-topbar { position: sticky; top: 0; z-index: 900; height: 74px; background: #fff; border-bottom: 1px solid #e1e8f1; }
.topbar-inner { display: grid; width: min(1540px,calc(100% - 32px)); height: 100%; margin: 0 auto; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 28px; }
.brand { display: flex; align-items: center; gap: 10px; justify-self: start; color: inherit; text-decoration: none; }.brand-symbol { display: grid; width: 38px; height: 38px; place-items: center; color: #fff; background: linear-gradient(145deg,#173c72,#1e7ce9); border-radius: 11px; font-size: 16px; font-weight: 800; }.brand-copy strong,.brand-copy small { display: block; }.brand-copy strong { color: #17253d; font-size: 19px; }.brand-copy small { margin-top: 2px; color: #6f7f94; font-size: 10px; letter-spacing: .12em; }
.primary-nav { display: flex; height: 100%; align-items: stretch; gap: 34px; }.nav-link { position: relative; display: grid; place-items: center; color: #65758c; font-size: 15px; font-weight: 650; text-decoration: none; }.nav-link.active { color: #145fcc; }.nav-link.active::after { position: absolute; right: 0; bottom: 0; left: 0; height: 3px; background: #176bff; border-radius: 3px 3px 0 0; content: ""; }
.topbar-actions { display: flex; align-items: center; justify-self: end; gap: 12px; }.balance-link { display: flex; align-items: center; gap: 8px; padding: 9px 12px; color: #60738c; background: #f1f6ff; border: 1px solid #dae7fb; border-radius: 9px; font-size: 12px; text-decoration: none; }.balance-link strong { color: #175fc4; font-size: 14px; }.icon-link { position: relative; color: #43566f; font-size: 22px; text-decoration: none; }.icon-link b { position: absolute; top: -6px; right: -8px; min-width: 16px; padding: 2px 4px; color: #fff; background: #e85360; border-radius: 10px; font-size: 9px; text-align: center; }
.account-menu { position: relative; }.account-menu summary { display: flex; align-items: center; gap: 8px; cursor: pointer; list-style: none; }.account-menu summary::-webkit-details-marker { display: none; }.user-avatar { display: grid; width: 36px; height: 36px; place-items: center; color: #fff; background: linear-gradient(145deg,#5a88d7,#1f477c); border-radius: 10px; font-size: 13px; font-weight: 700; }.user-copy strong,.user-copy small { display: block; }.user-copy strong { font-size: 13px; }.user-copy small { margin-top: 2px; color: #718198; font-size: 10px; }.chevron { color: #7c8ca0; }.account-popover { position: absolute; top: calc(100% + 14px); right: 0; display: grid; width: 165px; padding: 8px; background: #fff; border: 1px solid #e0e7f0; border-radius: 12px; box-shadow: 0 18px 45px rgba(24,51,88,.14); }.account-popover a,.account-popover button { padding: 10px 11px; color: #4a5e77; background: transparent; border: 0; border-radius: 8px; font-size: 12px; text-align: left; text-decoration: none; }.account-popover a:hover,.account-popover button:hover { color: #1767dc; background: #eff5ff; }.login-link { padding: 9px 15px; color: #1767dc; background: #fff; border: 1px solid #cfdcf0; border-radius: 9px; font-size: 13px; font-weight: 700; cursor: pointer; }
.app-main { min-height: calc(100vh - 74px); }.fade-enter-active,.fade-leave-active { transition: opacity .16s ease; }.fade-enter-from,.fade-leave-to { opacity: 0; }
@media (max-width: 760px) { .app-topbar { height: 64px; }.topbar-inner { width: calc(100% - 24px); grid-template-columns: 1fr auto; }.brand-copy small,.balance-link,.icon-link,.user-copy,.chevron { display: none; }.primary-nav { position: fixed; right: 0; bottom: 0; left: 0; z-index: 920; height: 58px; gap: 0; background: #fff; border-top: 1px solid #dfe6ef; }.nav-link { width: 50vw; }.nav-link.active::after { top: 0; bottom: auto; }.app-main { min-height: calc(100vh - 64px); padding-bottom: 58px; }.account-popover { position: fixed; right: 12px; top: 62px; } }
@media (prefers-reduced-motion: reduce) { .fade-enter-active,.fade-leave-active { transition: none; } }
</style>

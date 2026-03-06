<script setup>
import { onMounted, onUnmounted, ref } from "vue";
import { RouterLink, RouterView } from "vue-router";
import { ElNotification } from "element-plus";

import LoginModal from "@/components/LoginModal.vue";
import AiTaskPanel from "@/components/AiTaskPanel.vue";
import { messageAPI } from "@/api/message";
import { useAiTaskStore } from "@/stores/aiTask";
import { useAuthStore } from "@/stores/auth";

const authStore = useAuthStore();
const aiTaskStore = useAiTaskStore();
const showLoginModal = ref(false);
const unreadCount = ref(0);

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

    if (data.type === "new_message") {
      unreadCount.value += 1;
    }

    if (data.type === "ai_task_completed" && data.data) {
      aiTaskStore.markCompleted(data.data.task_id, data.data, {
        featureKey: data.data.feature_key,
        executionTime: data.data.execution_time,
      });
      ElNotification({
        title: "Task Completed",
        message: data.data.message || "Your AI task has completed.",
        type: "success",
        duration: 5000,
      });
    }

    if (data.type === "ai_task_failed" && data.data) {
      aiTaskStore.markFailed(data.data.task_id, data.data.error, {
        featureKey: data.data.feature_key,
      });
      ElNotification({
        title: "Task Failed",
        message: data.data.message || "Your AI task has failed.",
        type: "error",
        duration: 8000,
      });
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

  ws.onerror = () => {
    if (ws) ws.close();
  };
};

const handleLogout = () => {
  if (confirm("Confirm logout?")) {
    authStore.logout();
    unreadCount.value = 0;
  }
};

onMounted(() => {
  fetchUnreadCount();
  interval = setInterval(fetchUnreadCount, 30000);

  if (authStore.isAuthenticated) {
    connectWebSocket();
    aiTaskStore.fetchHistory();
  }
});

onUnmounted(() => {
  if (interval) clearInterval(interval);
  if (reconnectInterval) clearInterval(reconnectInterval);
  if (ws) ws.close();
});
</script>

<template>
  <div class="basic-layout">
    <header>
      <div class="wrapper">
        <nav>
          <div class="logo">
            <span class="logo-text">JobInsights</span>
          </div>

          <div class="links">
            <RouterLink to="/">首页</RouterLink>
            <RouterLink to="/career-compass">职业导航罗盘</RouterLink>
            <RouterLink to="/major-analysis">专业分析</RouterLink>
            <RouterLink to="/jobs">职位市场</RouterLink>
            <RouterLink to="/companies">公司列表</RouterLink>
          </div>

          <div class="auth-action">
            <div v-if="authStore.isAuthenticated" class="user-profile">
              <RouterLink to="/my/resume" class="user-nav-link">我的简历</RouterLink>
              <RouterLink to="/my/favorites" class="user-nav-link">我的收藏</RouterLink>
              <RouterLink to="/my/messages" class="user-nav-link msg-link">
                消息
                <span v-if="unreadCount > 0" class="badge">{{ unreadCount }}</span>
              </RouterLink>
              <span class="user-nav-link ai-bell" @click="aiTaskStore.togglePanel">
                AI
                <span v-if="aiTaskStore.pendingCount > 0" class="badge pending-badge">
                  {{ aiTaskStore.pendingCount }}
                </span>
                <span v-else-if="aiTaskStore.hasUnread" class="ai-dot"></span>
              </span>
              <RouterLink to="/my/wallet" class="user-nav-link">钱包</RouterLink>
              <span class="divider">|</span>
              <span class="username">{{ authStore.user?.username || authStore.user?.phone }}</span>
              <button class="logout-btn" @click="handleLogout">退出</button>
            </div>
            <button v-else class="login-btn" @click="showLoginModal = true">登录 / 注册</button>
          </div>
        </nav>
      </div>
    </header>

    <LoginModal :isOpen="showLoginModal" @close="showLoginModal = false" />
    <AiTaskPanel />

    <main>
      <RouterView v-slot="{ Component, route }">
        <transition name="fade" mode="out-in">
          <keep-alive include="CareerCompass,MajorAnalysis">
            <component :is="Component" :key="route.path" />
          </keep-alive>
        </transition>
      </RouterView>
    </main>
  </div>
</template>

<style scoped>
header {
  position: fixed;
  width: 100%;
  top: 0;
  z-index: 1000;
  background: var(--color-glass-bg);
  backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.wrapper {
  max-width: 1440px;
  margin: 0 auto;
  padding: 1rem 2rem;
}

nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
}

.logo-text {
  font-size: 1.4rem;
  font-weight: 800;
}

.links {
  display: flex;
  gap: 1.2rem;
}

nav a {
  color: var(--color-text-mute);
  text-decoration: none;
  font-weight: 500;
}

nav a:hover,
nav a.router-link-active {
  color: var(--color-heading);
}

.auth-action {
  display: flex;
  align-items: center;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 0.8rem;
}

.user-nav-link {
  color: var(--color-text-mute);
  text-decoration: none;
}

.divider {
  color: rgba(255, 255, 255, 0.2);
}

.username {
  color: var(--color-heading);
  font-weight: 600;
}

.login-btn,
.logout-btn {
  border: 1px solid rgba(255, 255, 255, 0.2);
  background: transparent;
  color: var(--color-heading);
  border-radius: 999px;
  padding: 0.35rem 0.9rem;
  cursor: pointer;
}

.msg-link {
  position: relative;
}

.badge {
  position: absolute;
  top: -8px;
  right: -12px;
  background: #ef4444;
  color: #fff;
  font-size: 0.7rem;
  border-radius: 999px;
  padding: 0 0.35rem;
}

.ai-bell {
  position: relative;
  cursor: pointer;
}

.pending-badge {
  right: -16px;
}

.ai-dot {
  position: absolute;
  top: -2px;
  right: -8px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #22c55e;
}

main {
  padding-top: 88px;
  min-height: 100vh;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>

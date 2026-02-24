<script setup>
import { ref } from "vue";
import { RouterLink, RouterView } from "vue-router";
import LoginModal from "./components/LoginModal.vue";
import { useAuthStore } from "./stores/auth";

import api from "./core/api";

const authStore = useAuthStore();
const showLoginModal = ref(false);
const unreadCount = ref(0);

const fetchUnreadCount = async () => {
  if (!authStore.isAuthenticated) return;
  try {
    const res = await api.get("/messages/unread-count");
    unreadCount.value = res.data;
  } catch (e) {
    console.error("Failed to fetch unread count", e);
  }
};

// Poll unread count every 30s as fallback
import { onMounted, onUnmounted } from "vue";
let interval;
let ws;
let reconnectInterval;

const connectWebSocket = () => {
  const token = localStorage.getItem("token");
  if (!token) return;

  // Use wss if https, ws if http
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  // Backend API V1 Prefix is /api/v1 (from code inspection or config assumption)
  // api.js uses axios baseURL. We need to construct full WS URL.
  // Assuming backend is at same host:8000 usually or via proxy.
  // For now hardcode localhost:8000 for dev or use window.location if served from same origin (docker).
  // In docker-compose, frontend is on 8080, api 8000.
  // If user accesses via 8080 (nginx), nginx might proxy /api to backend.

  // Let's assume standard Vite dev proxy or Nginx proxy.
  // If dev mode (npm run dev), usually proxy setup in vite.config.js?
  // Let's use relative path if proxied, or absolute if not.
  // Since axios base url is likely http://localhost:8000, we should use ws://localhost:8000

  // Better: use api.defaults.baseURL to derive.
  const baseUrl = api.defaults.baseURL || "http://localhost:8000/api/v1";
  // Remove http/https
  const wsUrl = baseUrl.replace(/^http/, "ws") + `/ws/${token}`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log("WS Connected");
    // Clear reconnect interval if any
    if (reconnectInterval) clearInterval(reconnectInterval);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "new_message") {
      // Increment unread count
      unreadCount.value++;
      // Show toast (simple alert for now or custom)
      // console.log("New Message:", data.data.title);
      // Ideally use a toast library. For now just visual badge update is enough.
    }

    // Dispatch global event for other components (e.g. Resume Parser)
    window.dispatchEvent(new CustomEvent("ws-message", { detail: data }));
  };

  ws.onclose = () => {
    console.log("WS Disconnected");
    // Try reconnect
    if (!reconnectInterval) {
      reconnectInterval = setInterval(() => {
        if (authStore.isAuthenticated) connectWebSocket();
      }, 5000);
    }
  };

  ws.onerror = (err) => {
    console.error("WS Error", err);
    ws.close();
  };
};

onMounted(() => {
  fetchUnreadCount();
  // Start polling fallback
  interval = setInterval(fetchUnreadCount, 30000);
  // Connect WS
  if (authStore.isAuthenticated) connectWebSocket();
});

onUnmounted(() => {
  clearInterval(interval);
  if (reconnectInterval) clearInterval(reconnectInterval);
  if (ws) ws.close();
});

const handleLogout = () => {
  if (confirm("确定要退出登录吗？")) {
    authStore.logout();
    unreadCount.value = 0;
  }
};
</script>

<template>
  <header>
    <div class="wrapper">
      <nav>
        <div class="logo">
          <span class="logo-icon">🚀</span>
          <span class="logo-text">JobInsights</span>
        </div>
        <div class="links">
          <RouterLink to="/">首页</RouterLink>
          <RouterLink to="/analysis">全站分析</RouterLink>
          <RouterLink to="/major-analysis">专业分析</RouterLink>
          <RouterLink to="/jobs">职位市场</RouterLink>
          <RouterLink to="/companies">公司列表</RouterLink>
        </div>

        <div class="auth-action">
          <div v-if="authStore.isAuthenticated" class="user-profile">
            <RouterLink to="/my/resume" class="user-nav-link"
              >我的简历</RouterLink
            >
            <RouterLink to="/my/favorites" class="user-nav-link"
              >我的收藏</RouterLink
            >
            <RouterLink to="/my/messages" class="user-nav-link msg-link">
              消息
              <span v-if="unreadCount > 0" class="badge">{{
                unreadCount
              }}</span>
            </RouterLink>
            <RouterLink to="/my/wallet" class="user-nav-link">钱包</RouterLink>
            <span class="divider">|</span>
            <span class="username">{{
              authStore.user?.username || authStore.user?.phone
            }}</span>
            <button class="logout-btn" @click="handleLogout">退出</button>
          </div>
          <button v-else class="login-btn" @click="showLoginModal = true">
            登录 / 注册
          </button>
        </div>
      </nav>
    </div>
  </header>

  <LoginModal :isOpen="showLoginModal" @close="showLoginModal = false" />

  <main>
    <RouterView v-slot="{ Component }">
      <transition name="fade" mode="out-in">
        <component :is="Component" />
      </transition>
    </RouterView>
  </main>
</template>

<style scoped>
header {
  position: fixed;
  width: 100%;
  top: 0;
  z-index: 1000;
  background: var(--color-glass-bg);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
  transition: all var(--transition-normal);
}

.wrapper {
  max-width: 1440px;
  margin: 0 auto;
  padding: 1rem 3rem;
}

nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  font-size: 1.6rem;
  font-weight: 800;
  color: var(--color-heading);
  letter-spacing: -0.03em;
  user-select: none;
  cursor: pointer;
  transition: transform var(--transition-fast);
}

.logo:hover {
  transform: scale(1.02);
}

.logo-icon {
  filter: drop-shadow(0 0 10px rgba(14, 165, 233, 0.4));
}

.links {
  display: flex;
  gap: 2.5rem;
}

nav a {
  color: var(--color-text-mute);
  text-decoration: none;
  font-weight: 500;
  font-size: 0.95rem;
  transition: color var(--transition-fast);
  position: relative;
  padding: 0.5rem 0;
}

nav a:hover,
nav a.router-link-active {
  color: var(--color-heading);
}

/* 优雅的下划线滑入伸展动画 */
nav a::after {
  content: "";
  position: absolute;
  bottom: 0;
  left: 50%;
  transform: translateX(-50%);
  width: 0;
  height: 2px;
  background: linear-gradient(
    90deg,
    transparent,
    var(--color-primary),
    transparent
  );
  transition: width var(--transition-normal);
  border-radius: 2px;
  opacity: 0;
}

nav a:hover::after,
nav a.router-link-active::after {
  width: 100%;
  opacity: 1;
}

.auth-action {
  margin-left: 2rem;
  display: flex;
  align-items: center;
}

.login-btn {
  background: hsla(
    var(--color-primary-h),
    var(--color-primary-s),
    var(--color-primary-l),
    0.15
  );
  color: var(--color-primary);
  border: 1px solid
    hsla(
      var(--color-primary-h),
      var(--color-primary-s),
      var(--color-primary-l),
      0.3
    );
  padding: 0.5rem 1.5rem;
  border-radius: var(--radius-huge);
  font-size: 0.9rem;
  font-weight: 600;
  transition: all var(--transition-normal);
  backdrop-filter: blur(4px);
  box-shadow: 0 0 15px transparent;
}

.login-btn:hover {
  background: var(--color-primary);
  color: #fff;
  box-shadow: var(--shadow-glow);
  transform: translateY(-1px);
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  background: rgba(255, 255, 255, 0.03);
  padding: 0.4rem 0.5rem 0.4rem 1.25rem;
  border-radius: var(--radius-huge);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.username {
  color: var(--color-heading);
  font-weight: 600;
  font-size: 0.9rem;
}

.user-nav-link {
  color: var(--color-text-mute);
  text-decoration: none;
  font-size: 0.85rem;
  font-weight: 500;
  transition: color var(--transition-fast);
}

.user-nav-link:hover {
  color: var(--color-heading);
}

.divider {
  color: rgba(255, 255, 255, 0.1);
  user-select: none;
}

.logout-btn {
  border-color: transparent;
  background: rgba(239, 68, 68, 0.1);
  color: #f87171;
  font-size: 0.8rem;
  padding: 0.4rem 1rem;
  border-radius: var(--radius-huge);
  font-weight: 600;
  transition: all var(--transition-fast);
}

.logout-btn:hover {
  background: #ef4444;
  color: white;
  box-shadow: 0 0 15px rgba(239, 68, 68, 0.4);
}

main {
  padding-top: 90px;
  min-height: 100vh;
}

/* 页面切换动画加强 */
.fade-enter-active,
.fade-leave-active {
  transition:
    opacity 0.4s ease,
    transform 0.4s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(10px);
}

.msg-link {
  position: relative;
}

.badge {
  position: absolute;
  top: -6px;
  right: -10px;
  background: linear-gradient(135deg, #ef4444, #dc2626);
  color: white;
  font-size: 0.7rem;
  font-weight: 700;
  padding: 0.1rem 0.4rem;
  border-radius: 12px;
  min-width: 18px;
  text-align: center;
  box-shadow: 0 2px 4px rgba(239, 68, 68, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.2);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4);
  }
  70% {
    box-shadow: 0 0 0 6px rgba(239, 68, 68, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(239, 68, 68, 0);
  }
}

@media (max-width: 768px) {
  .wrapper {
    padding: 1rem;
  }
  .links {
    display: none;
  } /* Mobile menu needed */
  .user-profile {
    gap: 0.5rem;
    padding: 0.4rem;
  }
}
</style>

<script setup>
import { ref } from 'vue';
import { RouterLink, RouterView } from 'vue-router'
import LoginModal from './components/LoginModal.vue';
import { useAuthStore } from './stores/auth';

import api from './core/api';

const authStore = useAuthStore();
const showLoginModal = ref(false);
const unreadCount = ref(0);

const fetchUnreadCount = async () => {
    if (!authStore.isAuthenticated) return;
    try {
        const res = await api.get('/messages/unread-count');
        unreadCount.value = res.data;
    } catch (e) {
        console.error("Failed to fetch unread count", e);
    }
};

// Poll unread count every 30s as fallback
import { onMounted, onUnmounted } from 'vue';
let interval;
let ws;
let reconnectInterval;

const connectWebSocket = () => {
    const token = localStorage.getItem('token');
    if (!token) return;

    // Use wss if https, ws if http
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
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
    const baseUrl = api.defaults.baseURL || 'http://localhost:8000/api/v1';
    // Remove http/https
    const wsUrl = baseUrl.replace(/^http/, 'ws') + `/ws/${token}`;
    
    ws = new WebSocket(wsUrl);
    
    ws.onopen = () => {
        console.log("WS Connected");
        // Clear reconnect interval if any
        if (reconnectInterval) clearInterval(reconnectInterval);
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === 'new_message') {
            // Increment unread count
            unreadCount.value++;
            // Show toast (simple alert for now or custom)
            // console.log("New Message:", data.data.title);
            // Ideally use a toast library. For now just visual badge update is enough.
        }
        
        // Dispatch global event for other components (e.g. Resume Parser)
        window.dispatchEvent(new CustomEvent('ws-message', { detail: data }));
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
    }
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
  if(confirm('确定要退出登录吗？')) {
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
              <RouterLink to="/my/resume" class="user-nav-link">我的简历</RouterLink>
              <RouterLink to="/my/favorites" class="user-nav-link">我的收藏</RouterLink>
              <RouterLink to="/my/messages" class="user-nav-link msg-link">
                  消息
                  <span v-if="unreadCount > 0" class="badge">{{ unreadCount }}</span>
              </RouterLink>
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
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  position: fixed;
  width: 100%;
  top: 0;
  z-index: 1000;
}

.wrapper {
  max-width: 1280px;
  margin: 0 auto;
  padding: 1rem 2rem;
}

nav {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.logo {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 1.5rem;
  font-weight: bold;
  color: var(--color-heading);
}

.links {
  display: flex;
  gap: 2rem;
}

nav a {
  color: var(--color-text);
  text-decoration: none;
  font-weight: 500;
  transition: color 0.3s;
  position: relative;
}

nav a:hover, nav a.router-link-active {
  color: var(--color-primary);
}

nav a.router-link-active::after {
  content: '';
  position: absolute;
  bottom: -5px;
  left: 0;
  width: 100%;
  height: 2px;
  background-color: var(--color-primary);
}

.auth-action {
  margin-left: 2rem;
}

.login-btn, .logout-btn {
  background: rgba(56, 189, 248, 0.1);
  color: var(--color-primary);
  border: 1px solid var(--color-primary);
  padding: 0.4rem 1.2rem;
  border-radius: 2rem;
  font-size: 0.9rem;
  font-weight: 600;
  transition: 0.3s;
}

.login-btn:hover, .logout-btn:hover {
  background: var(--color-primary);
  color: #0f172a;
}

.user-profile {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.username {
  color: var(--color-heading);
  font-weight: 500;
}

.user-nav-link {
    color: var(--color-text);
    text-decoration: none;
    font-size: 0.9rem;
    padding: 0 0.5rem;
}
.user-nav-link:hover { color: var(--color-primary); }
.divider { color: var(--color-border); margin: 0 0.5rem; }

.logout-btn {
  border-color: var(--color-border);
  color: var(--color-text-mute);
  background: transparent;
  font-size: 0.8rem;
  padding: 0.3rem 0.8rem;
}

.logout-btn:hover {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

main {
  padding-top: 80px; /* Space for fixed header */
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

.msg-link { position: relative; }
.badge {
    position: absolute;
    top: -5px;
    right: -8px;
    background: #ef4444;
    color: white;
    font-size: 0.7rem;
    padding: 0px 4px;
    border-radius: 10px;
    min-width: 16px;
    text-align: center;
}
</style>

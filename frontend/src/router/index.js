import { createRouter, createWebHistory } from "vue-router";
const BasicLayout = () => import("@/layout/BasicLayout.vue");
const HomeView = () => import("@/views/HomeView.vue");

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: "/",
      component: BasicLayout,
      children: [
        {
          path: "",
          name: "home",
           component: HomeView,
        },
        {
          path: "career-analysis",
          name: "career-analysis",
          component: () => import("@/views/CareerAnalysisView.vue"),
        },
        {
          path: "agent",
          name: "agent",
          component: () => import("@/views/AgentWorkspace.vue"),
          meta: { requiresAuth: true, feature: "agent" },
        },
        {
          path: "agent/:conversationId",
          name: "agent-conversation",
          component: () => import("@/views/AgentWorkspace.vue"),
          meta: { requiresAuth: true, feature: "agent" },
        },
        {
          path: "my/resume",
          name: "my-resume",
          component: () => import("@/views/MyResume.vue"),
          meta: { requiresAuth: true },
        },
        {
          path: "my/profile",
          name: "my-profile",
          component: () => import("@/views/ProfileCenterView.vue"),
          meta: { requiresAuth: true },
        },
        {
          path: "my/messages",
          name: "my-messages",
          component: () => import("@/views/MessageCenter.vue"),
          meta: { requiresAuth: true },
        },
        {
          path: "my/wallet",
          name: "my-wallet",
          component: () => import("@/views/WalletView.vue"),
          meta: { requiresAuth: true },
        },
      ],
    },
    {
      path: "/payment/success",
      name: "payment-success",
      component: () => import("@/views/WalletView.vue"),
      meta: { requiresAuth: true },
    },
    {
      // Optional: If Login shouldn't have the header
      path: "/login",
      name: "login",
      component: () => import("@/views/LoginView.vue"),
    },
  ],
});

router.beforeEach((to, from, next) => {
  const token = localStorage.getItem("token");
  const requiredAuth = to.matched.some((record) => record.meta.requiresAuth);
  const agentDisabled = to.matched.some((record) => record.meta.feature === "agent")
    && import.meta.env.VITE_AGENT_ENABLED === "false";

  if (agentDisabled) {
    next({ name: "home" });
  } else if (requiredAuth && !token) {
    next({ name: "home", query: { login: "true", redirect: to.fullPath } });
  } else {
    next();
  }
});

export default router;

import { createRouter, createWebHistory } from "vue-router";
const BasicLayout = () => import("@/layout/BasicLayout.vue");
const HomeView = () => import("@/views/HomeView.vue");
const InsightsHub = () => import("@/views/InsightsHub.vue");
const JobMarket = () => import("@/views/JobMarket.vue");
const CompanyList = () => import("@/views/CompanyList.vue");
const JobDetail = () => import("@/views/JobDetail.vue");
const CompanyDetail = () => import("@/views/CompanyDetail.vue");

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
          path: "career-data",
          name: "career-data",
          component: InsightsHub,
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
          path: "jobs",
          name: "jobs",
          component: JobMarket,
        },
        {
          path: "jobs/:id",
          name: "job-detail",
          component: JobDetail,
        },
        {
          path: "companies",
          name: "companies",
          component: CompanyList,
        },
        {
          path: "companies/:id",
          name: "company-detail",
          component: CompanyDetail,
        },
        {
          path: "major-analysis",
          name: "major-analysis",
          component: () => import("@/views/MajorAnalysis.vue"),
        },
        {
          path: "career-compass",
          name: "career-compass",
          component: () => import("@/views/CareerCompass.vue"),
        },
        {
          path: "compare/cities",
          name: "compare-cities",
          component: () => import("@/views/CitySalaryCompareView.vue"),
        },
        {
          path: "compare/industries",
          name: "compare-industries",
          component: () => import("@/views/IndustrySalaryCompareView.vue"),
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
          path: "my/favorites",
          name: "my-favorites",
          component: () => import("@/views/MyFavorites.vue"),
          meta: { requiresAuth: true },
        },
        {
          path: "my/applications",
          name: "my-applications",
          component: () => import("@/views/MyApplications.vue"),
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
      path: "/analysis",
      redirect: { name: "home", hash: "#analysis-panel" },
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

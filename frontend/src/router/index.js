import { createRouter, createWebHistory } from "vue-router";
import BasicLayout from "@/layout/BasicLayout.vue";
import HomeView from "@/views/HomeView.vue";
import JobAnalysis from "@/views/JobAnalysis.vue";
import JobMarket from "@/views/JobMarket.vue";
import CompanyList from "@/views/CompanyList.vue";
import JobDetail from "@/views/JobDetail.vue";
import CompanyDetail from "@/views/CompanyDetail.vue";

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
          path: "analysis",
          name: "analysis",
          component: JobAnalysis,
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
          path: "my/resume",
          name: "my-resume",
          component: () => import("@/views/MyResume.vue"),
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
      ],
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

  if (requiredAuth && !token) {
    next({ name: "home", query: { login: "true" } });
  } else {
    next();
  }
});

export default router;

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  authStore: { isAuthenticated: false, user: null },
  getOverview: vi.fn(),
  getPricing: vi.fn(),
  generateReport: vi.fn(),
  getLatestReport: vi.fn(),
  askQuestion: vi.fn(),
  getRun: vi.fn(),
  getConversation: vi.fn(),
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("@/api/career", () => ({
  careerAPI: {
    getOverview: mocks.getOverview,
    getPricing: mocks.getPricing,
    generateReport: mocks.generateReport,
    getLatestReport: mocks.getLatestReport,
    askQuestion: mocks.askQuestion,
  },
}));
vi.mock("@/api/agent", () => ({
  agentAPI: {
    getRun: mocks.getRun,
    getConversation: mocks.getConversation,
  },
}));

import CareerAnalysisView from "./CareerAnalysisView.vue";

const overview = {
  profile: { name: "林晓雨", completion: 78, school: "浙江理工大学", major: "计算机科学与技术", graduation: "2027 届本科" },
  directions: [
    { title: "AI 产品经理", match: 92, reason: "技术理解与用户洞察形成复合优势", tags: ["岗位增长 +28%", "杭州机会突出"] },
  ],
  cities: [{ city: "杭州", jobs: "12,860", salary: "18.6K", growth: "+19.4%", competition: "中" }],
  skills: [{ name: "数据分析", current: 62, target: 82 }],
  plan: [{ period: "30 天", title: "补齐数据基础", items: ["完成 SQL 核心课程"] }],
  evidence: { sampleSize: "128 万岗位", updatedAt: "2026-07-28 14:20" },
};

describe("CareerAnalysisView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authStore.isAuthenticated = false;
    mocks.authStore.user = null;
    mocks.getOverview.mockResolvedValue({ data: overview });
    mocks.getPricing.mockResolvedValue({
      data: {
        careerReport: { amount: "3.50", currency: "CNY" },
        careerQuestion: { amount: "0.30", currency: "CNY" },
      },
    });
  });

  it("lets a guest read the introduction and gates report generation", async () => {
    const wrapper = mount(CareerAnalysisView);
    await wrapper.get("[data-test='generate-analysis']").trigger("click");

    expect(wrapper.text()).toContain("职业分析如何帮助你");
    expect(mocks.getOverview).not.toHaveBeenCalled();
    expect(mocks.push).toHaveBeenCalledWith({
      name: "career-analysis",
      query: { login: "true", redirect: "/career-analysis", action: "generate" },
    });
  });

  it("loads personalized evidence and backend-managed prices for a signed-in user", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "林晓雨" };

    const wrapper = mount(CareerAnalysisView);
    await flushPromises();

    expect(mocks.getOverview).toHaveBeenCalledOnce();
    expect(mocks.getPricing).toHaveBeenCalledOnce();
    expect(wrapper.text()).toContain("AI 产品经理");
    expect(wrapper.text()).toContain("128 万岗位");
    expect(wrapper.get("[data-test='generate-analysis']").text()).toContain("¥3.50");
    expect(wrapper.get("[data-test='career-ai-price']").text()).toContain("¥0.30");
  });

  it("labels synthetic career analysis sections without replacing the real profile", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.getOverview.mockResolvedValue({
      data: {
        ...overview,
        dataStatus: {
          source: "mixed",
          syntheticDimensions: ["career.agent_report", "career.city_comparison"],
        },
      },
    });

    const wrapper = mount(CareerAnalysisView);
    await flushPromises();

    expect(wrapper.get("[data-test='career-source']").text()).toContain(
      "分析部分使用测试数据",
    );
    expect(wrapper.text()).toContain("林晓雨");
  });

  it("tracks the report run and renders the latest report after completion", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "林晓雨" };
    mocks.generateReport.mockResolvedValue({
      data: { run_id: "9001", conversation_id: "8001", status: "queued" },
    });
    mocks.getRun
      .mockResolvedValueOnce({
        data: { id: "9001", status: "running", current_node: "execute_tools" },
      })
      .mockResolvedValueOnce({
        data: { id: "9001", status: "completed", current_node: "completed" },
      });
    mocks.getLatestReport.mockResolvedValue({
      data: {
        status: "completed",
        run_id: "9001",
        content: "完整报告正文",
        created_at: "2026-08-06T10:00:00",
      },
    });
    mocks.getOverview.mockResolvedValue({ data: { ...overview } });

    const wrapper = mount(CareerAnalysisView);
    await flushPromises();

    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    expect(wrapper.get("[data-test='run-status']").text()).toContain("正在准备");

    vi.advanceTimersByTime(3000);
    await flushPromises();
    expect(wrapper.get("[data-test='run-status']").text()).toContain("查询市场数据");

    vi.advanceTimersByTime(3000);
    await flushPromises();

    expect(wrapper.get("[data-test='run-status']").text()).toContain("分析完成");
    expect(wrapper.get("[data-test='latest-report']").text()).toContain("完整报告正文");
    expect(mocks.getOverview).toHaveBeenCalledTimes(2);
    expect(mocks.getLatestReport).toHaveBeenCalledOnce();

    vi.useRealTimers();
  });
});

import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadMarketDashboard: vi.fn(),
  push: vi.fn(),
  authStore: { isAuthenticated: false },
  askQuestion: vi.fn(),
  getPricing: vi.fn(),
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("@/services/marketDashboard", () => ({
  loadMarketDashboard: mocks.loadMarketDashboard,
}));
vi.mock("@/api/market", () => ({
  marketAPI: { askQuestion: mocks.askQuestion },
}));
vi.mock("@/api/career", () => ({
  careerAPI: { getPricing: mocks.getPricing },
}));

import HomeView from "./HomeView.vue";

const marketFixture = {
  updatedAt: "2026-07-28T10:00:00+08:00",
  filters: {
    ranges: [{ label: "近 12 个月", value: "12m" }],
    cities: [{ label: "全国", value: "" }, { label: "杭州", value: "杭州" }],
    industries: [{ label: "全部行业", value: "" }],
    educations: [{ label: "不限学历", value: "" }],
  },
  kpis: [{ label: "在招岗位", value: "1,284,760", note: "对比上月", delta: "+12.6%", icon: "▦", tone: "blue" }],
  trend: { years: ["1月", "2月"], series: [{ name: "人工智能", values: [100, 130], color: "#176bff" }] },
  citySalaries: [{ name: "杭州", value: 15.4 }],
  skills: [{ name: "Python", value: 68 }],
  salaryDistribution: [{ label: "12–18K", value: 31 }],
  talentStructure: { education: [{ label: "本科", value: 62 }], experience: [{ label: "1–3 年", value: 42 }] },
  cityMatrix: [{ city: "杭州", growth: 19.4, salary: 15.4 }],
  signals: [{ type: "需求加速", title: "AI 产品经理", delta: "+28.4%", tone: "up" }],
  rankings: [{ name: "人工智能 / 大模型", growth: "+24.8%", salary: "¥21.6K", gap: "高", score: "92.4" }],
};

const chartStubs = {
  IndustryTrendChart: { template: "<div data-test='trend-chart' />" },
  SalaryBarChart: { template: "<div data-test='salary-chart' />" },
  SkillDonutChart: { template: "<div data-test='skill-chart' />" },
};

describe("HomeView V2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.authStore.isAuthenticated = false;
    mocks.loadMarketDashboard.mockResolvedValue({
      data: marketFixture,
      source: "fallback",
      updatedAt: marketFixture.updatedAt,
    });
    mocks.getPricing.mockResolvedValue({
      data: { marketQuestion: { amount: "0.20", currency: "CNY" } },
    });
  });

  it("renders the public dashboard from a degraded data source without requesting login", async () => {
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(wrapper.text()).toContain("全行业就业市场");
    expect(wrapper.text()).toContain("1,284,760");
    expect(wrapper.text()).toContain("数据服务已降级，当前展示最近一次可用数据");
    expect(wrapper.find("[data-test='trend-chart']").exists()).toBe(true);
    expect(mocks.getPricing).toHaveBeenCalledOnce();
    expect(mocks.push).not.toHaveBeenCalled();
  });

  it("allows a guest to open AI chat and asks for login only when sending", async () => {
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(wrapper.get("[data-test='market-ai-dialog']").isVisible()).toBe(true);
    await wrapper.get("[data-test='market-ai-close']").trigger("click");
    await wrapper.get("[data-test='market-ai-launcher']").trigger("click");
    expect(mocks.push).not.toHaveBeenCalled();

    await wrapper.get("[data-test='market-ai-input']").setValue("杭州的 AI 岗位趋势如何？");
    await wrapper.get(".ai-composer").trigger("submit");

    expect(mocks.push).toHaveBeenCalledWith({
      name: "home",
      query: { login: "true", redirect: "/", action: "market-ai" },
    });
    expect(mocks.askQuestion).not.toHaveBeenCalled();
  });
});

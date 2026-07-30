import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadMarketDashboard: vi.fn(),
  push: vi.fn(),
  authStore: { isAuthenticated: false },
  askQuestion: vi.fn(),
  getHistory: vi.fn(),
  getRun: vi.fn(),
  getPricing: vi.fn(),
}));

vi.mock("vue-router", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("@/services/marketDashboard", () => ({
  loadMarketDashboard: mocks.loadMarketDashboard,
}));
vi.mock("@/api/market", () => ({
  marketAPI: {
    askQuestion: mocks.askQuestion,
    getHistory: mocks.getHistory,
  },
}));
vi.mock("@/api/agent", () => ({
  agentAPI: { getRun: mocks.getRun },
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
  salarySummary: { median: 12680, p75: 21300 },
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
    mocks.getHistory.mockResolvedValue({ data: { items: [] } });
    mocks.getRun.mockResolvedValue({ data: { status: "completed" } });
  });

  it("renders the public dashboard from a degraded data source without requesting login", async () => {
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(wrapper.text()).toContain("全行业就业市场");
    expect(wrapper.text()).toContain("1,284,760");
    expect(wrapper.text()).toContain("¥12,680");
    expect(wrapper.text()).toContain("¥21,300");
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

  it("labels mixed API data as test display data", async () => {
    mocks.loadMarketDashboard.mockResolvedValue({
      data: {
        ...marketFixture,
        dataStatus: {
          source: "mixed",
          syntheticDimensions: ["market.monthly_job_trend"],
        },
      },
      source: "mixed",
      updatedAt: marketFixture.updatedAt,
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(wrapper.get("[data-test='market-source']").text()).toContain(
      "部分展示使用测试数据",
    );
  });

  it("restores persisted market question history for a signed-in user", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.getHistory.mockResolvedValue({
      data: {
        items: [{
          conversationId: "101",
          latestRunId: "201",
          latestRunStatus: "completed",
          messages: [
            { id: "1", role: "user", content: "杭州 AI 岗位多吗？", createdAt: "2026-07-29T10:00:00Z" },
            { id: "2", role: "assistant", content: "杭州 AI 岗位需求保持增长。", createdAt: "2026-07-29T10:00:10Z" },
          ],
        }],
      },
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(mocks.getHistory).toHaveBeenCalledOnce();
    expect(wrapper.get(".ai-message-list").text()).toContain("杭州 AI 岗位多吗？");
    expect(wrapper.get(".ai-message-list").text()).toContain("杭州 AI 岗位需求保持增长。");
  });

  it("renders assistant markdown safely while keeping user content as plain text", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.getHistory.mockResolvedValue({
      data: {
        items: [{
          conversationId: "101",
          latestRunId: "201",
          latestRunStatus: "completed",
          messages: [
            {
              id: "1",
              role: "user",
              content: "<strong>这不是用户输入的富文本</strong>",
              createdAt: "2026-07-29T10:00:00Z",
            },
            {
              id: "2",
              role: "assistant",
              content: "## 推荐方向\n\n- **Python 后端开发**\n\n> 仅供参考<script>alert('xss')</script>",
              createdAt: "2026-07-29T10:00:10Z",
            },
          ],
        }],
      },
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    const assistant = wrapper.findAll(".ai-message-list .assistant").at(-1);
    const user = wrapper.get(".ai-message-list .user");
    expect(assistant.get("h2").text()).toBe("推荐方向");
    expect(assistant.get("li strong").text()).toBe("Python 后端开发");
    expect(assistant.get("blockquote").text()).toBe("仅供参考");
    expect(assistant.find("script").exists()).toBe(false);
    expect(user.find("strong").exists()).toBe(false);
    expect(user.text()).toContain("<strong>这不是用户输入的富文本</strong>");
  });

  it("waits for an asynchronous market answer and then reloads history", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.getHistory
      .mockResolvedValueOnce({ data: { items: [] } })
      .mockResolvedValueOnce({
        data: {
          items: [{
            conversationId: "101",
            latestRunId: "201",
            latestRunStatus: "completed",
            messages: [
              { id: "1", role: "user", content: "新能源需要哪些技能？", createdAt: "2026-07-29T10:00:00Z" },
              { id: "2", role: "assistant", content: "重点关注电池和数据分析技能。", createdAt: "2026-07-29T10:00:10Z" },
            ],
          }],
        },
      });
    mocks.askQuestion.mockResolvedValue({
      data: { conversationId: "101", runId: "201", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "201", status: "completed" } });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("新能源需要哪些技能？");
    await wrapper.get(".ai-composer").trigger("submit");
    await flushPromises();

    expect(mocks.askQuestion).toHaveBeenCalledOnce();
    expect(mocks.getRun).toHaveBeenCalledWith("201");
    expect(mocks.getHistory).toHaveBeenCalledTimes(2);
    expect(wrapper.get(".ai-message-list").text()).toContain("重点关注电池和数据分析技能。");
  });
});

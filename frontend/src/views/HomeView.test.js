import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  loadMarketDashboard: vi.fn(),
  push: vi.fn(),
  authStore: { isAuthenticated: false },
  askQuestion: vi.fn(),
  getHistory: vi.fn(),
  getRun: vi.fn(),
  sendMessage: vi.fn(),
  cancelRun: vi.fn(),
  getConversation: vi.fn(),
  getPricing: vi.fn(),
  connect: vi.fn(),
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
  agentAPI: {
    getRun: mocks.getRun,
    sendMessage: mocks.sendMessage,
    cancelRun: mocks.cancelRun,
    getConversation: mocks.getConversation,
  },
}));
vi.mock("@/api/career", () => ({
  careerAPI: { getPricing: mocks.getPricing },
}));
vi.mock("@/utils/sseClient", () => ({
  connectAgentEventStream: mocks.connect,
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
    mocks.connect.mockReset();
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
    mocks.getConversation.mockResolvedValue({ data: { latest_run: null, messages: [] } });
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
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.getHistory.mockResolvedValue({ data: { items: [] } });
    mocks.askQuestion.mockResolvedValue({
      data: { conversationId: "101", runId: "201", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "201", status: "completed" } });
    mocks.getConversation.mockResolvedValue({
      data: {
        latest_run: { id: "201" },
        messages: [{ role: "assistant", content: "重点关注电池和数据分析技能。" }],
      },
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("新能源需要哪些技能？");
    await wrapper.get(".ai-composer").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(6000);

    expect(mocks.askQuestion).toHaveBeenCalledOnce();
    expect(mocks.getRun).toHaveBeenCalledWith("201");
    expect(mocks.getConversation).toHaveBeenCalledWith("101");
    expect(wrapper.get(".ai-message-list").text()).toContain("重点关注电池和数据分析技能。");
    wrapper.unmount();
    vi.useRealTimers();
  });

  it("restores a waiting market run into its clarification controls", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.getHistory.mockResolvedValue({
      data: { items: [{ conversationId: "101", latestRunId: "201", latestRunStatus: "waiting_user", messages: [] }] },
    });
    mocks.getConversation.mockResolvedValue({
      data: { messages: [{ role: "assistant", message_type: "clarification_required", content: "请补充目标城市" }] },
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();

    expect(wrapper.get("[data-test='market-ai-clarification']").text()).toContain("请补充目标城市");
    expect(wrapper.get("[data-test='market-ai-input']").attributes("disabled")).toBeDefined();
    wrapper.unmount();
  });

  it("shows an assistant placeholder immediately and renders streamed answer deltas", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { conversationId: "101", runId: "201", status: "queued" },
    });
    let streamOptions;
    let closeStream;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise((resolve) => { closeStream = resolve; });
    });

    let wrapper;
    try {
      wrapper = mount(HomeView, { global: { stubs: chartStubs } });
      await flushPromises();
      await wrapper.get("[data-test='market-ai-input']").setValue("Python 后端岗位需要哪些技能？");
      await wrapper.get(".ai-composer").trigger("submit");
      await flushPromises();

      expect(wrapper.get("[data-test='market-ai-streaming-message']").text()).toContain("正在回答");
      await vi.waitFor(() => expect(mocks.connect).toHaveBeenCalledOnce());

      await streamOptions.onEvent({
        event_id: "1-0",
        sequence: 1,
        event: "message_started",
        run_id: "201",
        conversation_id: "101",
        data: { role: "assistant" },
      });
      await streamOptions.onEvent({
        event_id: "2-0",
        sequence: 2,
        event: "message_delta",
        run_id: "201",
        conversation_id: "101",
        data: { delta: "重点关注 Python、" },
      });
      await streamOptions.onEvent({
        event_id: "3-0",
        sequence: 3,
        event: "message_delta",
        run_id: "201",
        conversation_id: "101",
        data: { delta: "Django 和 Redis。" },
      });
      await streamOptions.onEvent({
        event_id: "4-0",
        sequence: 4,
        event: "message_completed",
        run_id: "201",
        conversation_id: "101",
        data: { message_id: "301" },
      });
      await streamOptions.onEvent({
        event_id: "5-0",
        sequence: 5,
        event: "run_completed",
        run_id: "201",
        conversation_id: "101",
        data: { status: "completed", message_id: "301" },
      });
      await flushPromises();

      expect(wrapper.get("[data-test='market-ai-streaming-message']").text()).toContain(
        "重点关注 Python、Django 和 Redis。",
      );
    } finally {
      closeStream?.({ lastEventId: "5-0" });
      wrapper?.unmount();
    }
  });

  it("recovers a same-feature active market run returned by a 409", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockRejectedValue({
      response: {
        status: 409,
        data: {
          code: "AGENT_ACTIVE_RUN_EXISTS",
          msg: "已有行业问数正在执行",
          data: {
            runId: "active-201", conversationId: "active-101", status: "running", messageType: "market_question",
          },
        },
      },
    });
    mocks.connect.mockImplementation(() => new Promise(() => {}));

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("继续查看市场数据");
    await wrapper.get(".ai-composer").trigger("submit");
    await vi.waitFor(() => expect(mocks.connect).toHaveBeenCalledWith(
      expect.objectContaining({ runId: "active-201" }),
    ));
    expect(wrapper.get("[data-test='market-ai-streaming-message']").exists()).toBe(true);
    wrapper.unmount();
  });

  it("shows clarification controls and can cancel a waiting market run", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { conversationId: "101", runId: "201", status: "queued" } });
    mocks.cancelRun.mockResolvedValue({ data: { id: "201", status: "cancelled" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("帮我分析北京机会");
    await wrapper.get(".ai-composer").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({
      event_id: "1-0", event: "clarification_required", run_id: "201", conversation_id: "101",
      data: { question: "请补充工作年限" },
    });
    await flushPromises();

    expect(wrapper.get("[data-test='market-ai-clarification']").text()).toContain("请补充工作年限");
    await wrapper.get("[data-test='market-ai-clarification'] button[type='button']").trigger("click");
    await flushPromises();
    expect(mocks.cancelRun).toHaveBeenCalledWith("201");
    wrapper.unmount();
  });

  it("replaces partial text with the safe unbilled failure state", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { conversationId: "101", runId: "201", status: "queued" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("测试失败展示");
    await wrapper.get(".ai-composer").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({ event_id: "1-0", event: "message_delta", run_id: "201", data: { delta: "不应保留的片段" } });
    await streamOptions.onEvent({ event_id: "2-0", event: "run_failed", run_id: "201", data: {} });
    await flushPromises();

    const message = wrapper.get("[data-test='market-ai-streaming-message']").text();
    expect(message).toContain("未完成");
    expect(message).toContain("不会扣除余额");
    expect(message).not.toContain("不应保留的片段");
    wrapper.unmount();
  });

  it("explains an Agent provider balance failure without suggesting malformed output", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { conversationId: "101", runId: "201", status: "queued" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("测试模型余额失败展示");
    await wrapper.get(".ai-composer").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({
      event_id: "1-0", event: "run_failed", run_id: "201",
      data: { error_code: "AGENT_LLM_QUOTA_EXCEEDED" },
    });
    await flushPromises();

    const message = wrapper.get("[data-test='market-ai-streaming-message']").text();
    expect(message).toContain("AI 模型服务余额不足");
    expect(message).toContain("不会扣除余额");
    wrapper.unmount();
  });

  it("rejects an unrelated historical answer when recovering a completed run", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { conversationId: "101", runId: "201", status: "queued" } });
    mocks.getConversation.mockResolvedValue({
      data: {
        latest_run: { id: "old-run" },
        messages: [{ role: "assistant", content: "另一轮历史回答" }],
      },
    });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("只接受当前任务答案");
    await wrapper.get(".ai-composer").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({ event_id: "1-0", event: "run_completed", run_id: "201", data: {} });
    await flushPromises();

    const message = wrapper.get("[data-test='market-ai-streaming-message']").text();
    expect(message).toContain("未完成");
    expect(message).not.toContain("另一轮历史回答");
    wrapper.unmount();
  });

  it("shows the standard backend msg when a market question is rejected", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockRejectedValue({
      response: {
        status: 503,
        data: { code: "AGENT_DISPATCH_FAILED", msg: "AI 服务繁忙，请稍后重试。" },
      },
    });

    const wrapper = mount(HomeView, { global: { stubs: chartStubs } });
    await flushPromises();
    await wrapper.get("[data-test='market-ai-input']").setValue("杭州后端岗位怎么样？");
    await wrapper.get(".ai-composer").trigger("submit");
    await flushPromises();

    expect(wrapper.get(".ai-error").text()).toContain("AI 服务繁忙，请稍后重试。");
    wrapper.unmount();
  });
});

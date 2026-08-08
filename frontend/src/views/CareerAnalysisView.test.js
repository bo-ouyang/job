import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  route: { query: {} },
  authStore: { isAuthenticated: false, user: null },
  getOverview: vi.fn(),
  getPricing: vi.fn(),
  generateReport: vi.fn(),
  getLatestReport: vi.fn(),
  askQuestion: vi.fn(),
  getRun: vi.fn(),
  getConversation: vi.fn(),
  sendMessage: vi.fn(),
  cancelRun: vi.fn(),
  connect: vi.fn(),
  listConversations: vi.fn(),
  fetchTaskById: vi.fn(),
}));

vi.mock("vue-router", () => ({
  useRouter: () => ({ push: mocks.push }),
  useRoute: () => mocks.route,
}));
vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("@/stores/aiTask", () => ({ useAiTaskStore: () => ({ fetchTaskById: mocks.fetchTaskById }) }));
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
    sendMessage: mocks.sendMessage,
    cancelRun: mocks.cancelRun,
    listConversations: mocks.listConversations,
  },
}));
vi.mock("@/utils/sseClient", () => ({ connectAgentEventStream: mocks.connect }));

import CareerAnalysisView from "./CareerAnalysisView.vue";

const mountedWrappers = [];
const mountView = () => {
  const wrapper = mount(CareerAnalysisView);
  mountedWrappers.push(wrapper);
  return wrapper;
};

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
    mocks.route.query = {};
    mocks.getOverview.mockResolvedValue({ data: overview });
    mocks.getPricing.mockResolvedValue({
      data: {
        careerReport: { amount: "3.50", currency: "CNY" },
        careerQuestion: { amount: "0.30", currency: "CNY" },
      },
    });
  });

  afterEach(() => {
    while (mountedWrappers.length) mountedWrappers.pop().unmount();
    if (vi.isFakeTimers()) vi.clearAllTimers();
    vi.useRealTimers();
    Object.values(mocks).forEach((value) => value?.mockReset?.());
  });

  it("lets a guest read the introduction and gates report generation", async () => {
    const wrapper = mountView();
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

    const wrapper = mountView();
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

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get("[data-test='career-source']").text()).toContain(
      "分析部分使用测试数据",
    );
    expect(wrapper.text()).toContain("林晓雨");
  });

  it("accepts the real V2 camelCase submission contract and tracks the report run", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.authStore.user = { username: "林晓雨" };
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
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
        runId: "9001",
        content: "完整报告正文",
        createdAt: "2026-08-06T10:00:00",
      },
    });
    mocks.getOverview.mockResolvedValue({ data: { ...overview } });

    const wrapper = mountView();
    await flushPromises();

    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    expect(wrapper.find(".error-message").exists()).toBe(false);
    expect(wrapper.get("[data-test='run-status']").text()).toContain("正在准备");

    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.get("[data-test='run-status']").text()).toContain("查询市场数据");

    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get("[data-test='run-status']").text()).toContain("分析完成");
    const report = wrapper.get("[data-test='latest-report']");
    expect(report.text()).toContain("完整报告正文");
    expect(report.text()).toContain(
      new Date("2026-08-06T10:00:00").toLocaleString("zh-CN"),
    );
    expect(mocks.getOverview).toHaveBeenCalledTimes(2);
    expect(mocks.getLatestReport).toHaveBeenCalledOnce();
  });

  it("loads the owned report selected by a validated runId instead of substituting the latest report", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.route.query = { runId: "9001" };
    mocks.getRun.mockResolvedValue({ data: { id: "9001", conversation_id: "8001", input_message_id: "input-1", status: "completed" } });
    mocks.getConversation.mockResolvedValue({ data: {
      messages: [
        { id: "input-1", role: "user", message_type: "career_report_request", content: "Generate report" },
        { role: "assistant", message_type: "analysis_result", content: "Different report", metadata: { run_id: "8888" } },
        { role: "assistant", message_type: "analysis_result", content: "Selected report", metadata: { run_id: "9001", result: { directions: [] } } },
      ],
    } });

    const wrapper = mountView();
    await flushPromises();

    expect(mocks.getRun).toHaveBeenCalledWith("9001");
    expect(mocks.getConversation).toHaveBeenCalledWith("8001");
    expect(wrapper.get("[data-test='latest-report']").text()).toContain("Selected report");
    expect(wrapper.text()).not.toContain("Different report");
  });

  it("loads the selected completed legacy career task instead of the latest Agent report", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.route.query = { taskId: "legacy_career_1" };
    mocks.fetchTaskById.mockResolvedValue({
      taskId: "legacy_career_1", featureKey: "career_compass", status: "completed",
      result: { report: "Selected legacy career report" },
    });

    const wrapper = mountView();
    await flushPromises();

    expect(mocks.fetchTaskById).toHaveBeenCalledWith("legacy_career_1", "career_compass");
    expect(wrapper.get("[data-test='latest-report']").text()).toContain("Selected legacy career report");
  });

  it("restores only a waiting career question after page refresh", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.listConversations.mockResolvedValue({ data: { items: [{ id: "8101" }, { id: "market-101" }] } });
    mocks.getConversation.mockImplementation(async (id) => ({
      data: id === "8101"
        ? {
          conversation: { id },
          latest_run: { id: "9101", conversation_id: id, input_message_id: "message-1", status: "waiting_user" },
          messages: [
            { id: "message-1", role: "user", message_type: "career_question", content: "职业问题" },
            { role: "assistant", message_type: "clarification_required", content: "请补充目标城市" },
          ],
        }
        : {
          conversation: { id },
          latest_run: { id: "market-run", conversation_id: id, input_message_id: "market-message", status: "running" },
          messages: [{ id: "market-message", role: "user", message_type: "market_question", content: "市场问题" }],
        },
    }));

    const wrapper = mountView();
    await flushPromises();

    expect(wrapper.get("[data-test='clarification-panel']").text()).toContain("请补充目标城市");
    expect(wrapper.get(".career-ai-card textarea").attributes("disabled")).toBeDefined();
    expect(mocks.connect).not.toHaveBeenCalled();
  });

  it("restores a running career report after page refresh", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.listConversations.mockResolvedValue({ data: { items: [{ id: "8001" }] } });
    mocks.getConversation.mockResolvedValue({
      data: {
        conversation: { id: "8001" },
        latest_run: { id: "9001", conversation_id: "8001", input_message_id: "message-1", status: "running" },
        messages: [{ id: "message-1", role: "user", message_type: "career_report_request", content: "报告请求" }],
      },
    });
    mocks.connect.mockImplementation(() => new Promise(() => {}));

    const wrapper = mountView();
    await vi.waitFor(() => expect(mocks.connect).toHaveBeenCalledWith(expect.objectContaining({ runId: "9001" })));

    expect(wrapper.get("[data-test='run-status']").exists()).toBe(true);
    wrapper.unmount();
  });

  it("renders report run progress from SSE and refreshes the completed report", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({ data: { runId: "9001", conversationId: "8001", status: "queued" } });
    mocks.getLatestReport.mockResolvedValue({ data: { content: "流式完成报告" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({ event_id: "1-0", event: "tool_started", run_id: "9001", data: {} });
    await streamOptions.onEvent({ event_id: "2-0", event: "message_completed", run_id: "9001", data: { content: "报告正文" } });
    await streamOptions.onEvent({ event_id: "3-0", event: "run_completed", run_id: "9001", data: {} });
    await flushPromises();

    expect(wrapper.get("[data-test='latest-report']").text()).toContain("流式完成报告");
  });

  it("maps an SSE model timeout to the precise career error message", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({ data: { runId: "9001", conversationId: "8001", status: "queued" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({
      event_id: "1-0", event: "run_failed", run_id: "9001",
      data: { error_code: "AGENT_LLM_TIMEOUT", error_message: "provider timeout" },
    });
    await flushPromises();

    expect(wrapper.get(".error-message").text()).toContain("模型响应超时");
    expect(wrapper.get(".error-message").text()).not.toContain("provider timeout");
  });

  it("streams a career question, resets a new stream attempt, and calibrates its final answer", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { runId: "9101", conversationId: "8101", status: "queued" } });
    mocks.getConversation.mockRejectedValue(new Error("snapshot unavailable"));
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("我适合哪个城市？");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({ event_id: "1-0", event: "message_started", run_id: "9101", data: { streamId: "first" } });
    await streamOptions.onEvent({ event_id: "2-0", event: "message_delta", run_id: "9101", data: { streamId: "first", delta: "旧答案" } });
    await streamOptions.onEvent({ event_id: "3-0", event: "message_started", run_id: "9101", data: { streamId: "second" } });
    await streamOptions.onEvent({ event_id: "4-0", event: "message_delta", run_id: "9101", data: { streamId: "second", delta: "北京" } });
    await streamOptions.onEvent({ event_id: "5-0", event: "message_delta", run_id: "9101", data: { streamId: "second", delta: "机会更多" } });
    await streamOptions.onEvent({ event_id: "6-0", event: "message_completed", run_id: "9101", data: { streamId: "second", content: "最终建议：北京机会更多" } });
    await streamOptions.onEvent({ event_id: "7-0", event: "run_completed", run_id: "9101", data: {} });
    await flushPromises();

    expect(wrapper.get(".assistant-answer").text()).toContain("最终建议：北京机会更多");
    expect(wrapper.get(".assistant-answer").text()).not.toContain("旧答案");
  });

  it("falls back to the existing serial poll only after the question SSE is unavailable", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { runId: "9101", conversationId: "8101", status: "queued" } });
    mocks.connect.mockRejectedValue(new Error("SSE unavailable"));
    mocks.getRun.mockResolvedValue({ data: { id: "9101", status: "running" } });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("测试降级");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    expect(mocks.getRun).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(3000);
    expect(mocks.getRun).toHaveBeenCalledWith("9101");
  });

  it("marks a failed streamed question as unbilled rather than an answer", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({ data: { runId: "9101", conversationId: "8101", status: "queued" } });
    let streamOptions;
    mocks.connect.mockImplementation((options) => {
      streamOptions = options;
      return new Promise(() => {});
    });
    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("失败问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await vi.waitFor(() => expect(streamOptions).toBeTruthy());
    await streamOptions.onEvent({ event_id: "1-0", event: "message_started", run_id: "9101", data: { streamId: "one" } });
    await streamOptions.onEvent({ event_id: "2-0", event: "message_delta", run_id: "9101", data: { streamId: "one", delta: "partial" } });
    await streamOptions.onEvent({ event_id: "3-0", event: "run_failed", run_id: "9101", data: {} });
    await flushPromises();

    expect(wrapper.get(".assistant-answer").text()).toContain("不会扣除余额");
  });

  it("shows the backend msg from the standard code/msg/data error envelope", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockRejectedValue({
      response: {
        status: 402,
        data: {
          code: "INSUFFICIENT_BALANCE",
          msg: "账户余额不足，请先充值。",
          data: { requiredAmount: "3.50" },
        },
      },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();

    expect(wrapper.get(".error-message").text()).toContain("账户余额不足，请先充值。");
  });

  it("recovers the active run returned by a 409 instead of showing task creation failure", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockRejectedValue({
      response: {
        status: 409,
        data: {
          code: "AGENT_ACTIVE_RUN_EXISTS",
          msg: "任务已经创建，正在恢复进度。",
          data: {
            runId: "9001",
            conversationId: "8001",
            status: "running",
            messageType: "career_report_request",
          },
        },
      },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9001", status: "running", current_node: "execute_tools" },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();

    expect(wrapper.find(".error-message").exists()).toBe(false);
    expect(wrapper.get("[data-test='run-status']").text()).toContain("正在准备");

    await vi.advanceTimersByTimeAsync(3000);

    expect(mocks.getRun).toHaveBeenCalledWith("9001");
    expect(wrapper.get("[data-test='run-status']").text()).toContain("查询市场数据");
  });

  it("does not take over an active run owned by another Agent feature", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockRejectedValue({
      response: {
        status: 409,
        data: {
          code: "AGENT_OTHER_RUN_ACTIVE",
          msg: "首页 AI 问数任务正在处理中。",
          data: {
            runId: "9901",
            conversationId: "8901",
            status: "running",
            messageType: "market_question",
            internalState: "must-not-consume",
          },
        },
      },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();

    expect(wrapper.get(".error-message").text()).toContain("首页 AI 问数任务正在处理中");
    expect(mocks.getRun).not.toHaveBeenCalled();
  });

  it("polls serially without overlapping slow run requests", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockImplementation(() => new Promise(() => {}));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();

    await vi.advanceTimersByTimeAsync(9000);

    expect(mocks.getRun).toHaveBeenCalledTimes(1);
  });

  it("lets a report run answer the requested clarification and resume", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9001", status: "waiting_user", current_node: "clarification_required" },
    });
    mocks.getConversation.mockResolvedValue({
      data: {
        messages: [{
          id: "7001",
          role: "assistant",
          message_type: "clarification_required",
          content: "你优先考虑哪个城市？",
        }],
      },
    });
    mocks.sendMessage.mockResolvedValue({
      data: { run: { id: "9001", status: "queued" } },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    expect(wrapper.get("[data-test='run-status']").text()).toContain("等待补充信息");
    expect(mocks.getRun).toHaveBeenCalledOnce();
    expect(wrapper.get("[data-test='clarification-panel']").text()).toContain(
      "你优先考虑哪个城市？",
    );

    await wrapper.get("[data-test='clarification-input']").setValue("杭州，其次上海");
    await wrapper.get("[data-test='clarification-form']").trigger("submit");
    await flushPromises();

    expect(mocks.sendMessage).toHaveBeenCalledWith(
      "8001",
      expect.objectContaining({
        content: "杭州，其次上海",
        message_type: "clarification_response",
      }),
      expect.any(String),
    );
    expect(wrapper.find("[data-test='clarification-panel']").exists()).toBe(false);
    expect(wrapper.get("[data-test='run-status']").text()).toContain("正在准备");
  });

  it("lets a waiting career question resume on its original conversation", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { runId: "9101", conversationId: "8101", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9101", status: "waiting_user", current_node: "clarification_required" },
    });
    mocks.getConversation.mockResolvedValue({
      data: {
        messages: [{
          role: "assistant",
          message_type: "clarification_required",
          content: "你更看重薪资还是成长空间？",
        }],
      },
    });
    mocks.sendMessage.mockResolvedValue({
      data: { run: { id: "9101", status: "queued" } },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("帮我比较两个方向");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get("[data-test='clarification-panel']").text()).toContain("薪资还是成长空间");
    await wrapper.get("[data-test='clarification-input']").setValue("成长空间");
    await wrapper.get("[data-test='clarification-form']").trigger("submit");
    await flushPromises();

    expect(mocks.sendMessage).toHaveBeenCalledWith(
      "8101",
      expect.objectContaining({ content: "成长空间" }),
      expect.any(String),
    );
  });

  it("can cancel a waiting run from the clarification panel", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9001", status: "waiting_user", current_node: "clarification_required" },
    });
    mocks.getConversation.mockResolvedValue({
      data: { messages: [{ role: "assistant", message_type: "clarification_required", content: "请补充目标城市" }] },
    });
    mocks.cancelRun.mockResolvedValue({
      data: { id: "9001", status: "cancelled", current_node: "cancelled" },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    await wrapper.get("[data-test='clarification-cancel']").trigger("click");
    await flushPromises();

    expect(mocks.cancelRun).toHaveBeenCalledWith("9001");
    expect(wrapper.get("[data-test='run-status']").text()).toContain("已取消");
  });

  it("shows cancelled and actual Agent failure states", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9001", status: "cancelled", current_node: "cancelled" },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get("[data-test='run-status']").text()).toContain("已取消");
    expect(wrapper.get(".error-message").text()).toContain("任务已取消");

    mocks.generateReport.mockResolvedValue({
      data: { runId: "9002", conversationId: "8002", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9002", status: "failed", current_node: "failed", error_code: "AGENT_LLM_TIMEOUT" },
    });
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get(".error-message").text()).toContain("模型响应超时");
  });

  it("uses canonical camelCase IDs for career questions", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { runId: "9101", conversationId: "8101", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "9101", status: "running" } });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("我适合什么方向？");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(mocks.getRun).toHaveBeenCalledWith("9101");
    expect(wrapper.get(".assistant-answer").text()).toContain("正在整理建议");
  });

  it("ignores a stale question poll response after a newer question starts", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    let resolveOldPoll;
    const oldPoll = new Promise((resolve) => { resolveOldPoll = resolve; });
    mocks.askQuestion
      .mockResolvedValueOnce({ data: { runId: "9101", conversationId: "8101", status: "queued" } })
      .mockResolvedValueOnce({ data: { runId: "9102", conversationId: "8102", status: "queued" } });
    mocks.getRun
      .mockImplementationOnce(() => oldPoll)
      .mockResolvedValue({ data: { id: "9102", status: "running" } });
    mocks.cancelRun.mockResolvedValue({
      data: { id: "9101", status: "cancelled", current_node: "cancelled" },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第一个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    await wrapper.get("[data-test='question-cancel']").trigger("click");
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第二个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    resolveOldPoll({ data: { id: "9101", status: "completed" } });
    await flushPromises();

    expect(mocks.getConversation).not.toHaveBeenCalledWith("8101");
  });

  it("does not let stale conversation details replace a newer question", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    let resolveOldDetail;
    const oldDetail = new Promise((resolve) => { resolveOldDetail = resolve; });
    mocks.askQuestion
      .mockResolvedValueOnce({ data: { runId: "9101", conversationId: "8101", status: "queued" } })
      .mockResolvedValueOnce({ data: { runId: "9102", conversationId: "8102", status: "queued" } });
    mocks.getRun
      .mockResolvedValueOnce({ data: { id: "9101", status: "completed" } })
      .mockResolvedValue({ data: { id: "9102", status: "running" } });
    mocks.getConversation.mockImplementationOnce(() => oldDetail);

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第一个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    await wrapper.get(".career-ai-card textarea").setValue("第二个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    resolveOldDetail({
      data: { messages: [{ role: "assistant", content: "第一个问题的旧答案" }] },
    });
    await flushPromises();

    expect(wrapper.get(".assistant-answer").text()).not.toContain("第一个问题的旧答案");
    expect(wrapper.get(".assistant-answer").text()).toContain("正在整理建议");
  });

  it("stops report polling after consecutive network failures and allows retry", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockRejectedValue(new Error("socket reset"));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(9000);

    expect(mocks.getRun).toHaveBeenCalledTimes(3);
    expect(wrapper.get(".error-message").text()).toContain("网络连接不稳定");
    expect(wrapper.get("[data-test='generate-analysis']").attributes("disabled")).toBeUndefined();

    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    expect(mocks.generateReport).toHaveBeenCalledTimes(2);
  });

  it("stops an unknown report status instead of polling forever", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "9001", status: "mystery" } });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(12000);

    expect(mocks.getRun).toHaveBeenCalledOnce();
    expect(wrapper.get(".error-message").text()).toContain("任务状态异常");
    expect(wrapper.get("[data-test='generate-analysis']").attributes("disabled")).toBeUndefined();
  });

  it("stops report polling at its total deadline", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-07T09:00:00Z"));
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "9001", status: "running" } });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    vi.setSystemTime(new Date("2026-08-07T09:06:00Z"));
    await vi.advanceTimersByTimeAsync(3000);

    expect(mocks.getRun).not.toHaveBeenCalled();
    expect(wrapper.get(".error-message").text()).toContain("等待时间过长");
    expect(wrapper.get("[data-test='generate-analysis']").attributes("disabled")).toBeUndefined();
  });

  it("stops report polling after the maximum number of attempts", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({ data: { id: "9001", status: "running" } });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(243000);

    expect(mocks.getRun).toHaveBeenCalledTimes(80);
    expect(wrapper.get(".error-message").text()).toContain("等待时间过长");
    expect(wrapper.get("[data-test='generate-analysis']").attributes("disabled")).toBeUndefined();
  });

  it("uses stable safe messages for known and unknown Agent failures", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: {
        id: "9001",
        status: "failed",
        error_code: "AGENT_LLM_NOT_CONFIGURED",
        error_message: "OPENAI_API_KEY=secret-value",
      },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get(".error-message").text()).toContain("AI 服务尚未正确配置");
    expect(wrapper.get(".error-message").text()).not.toContain("secret-value");

    mocks.generateReport.mockResolvedValue({
      data: { runId: "9002", conversationId: "8002", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: {
        id: "9002",
        status: "failed",
        error_code: "AGENT_UNKNOWN_INTERNAL",
        error_message: "postgres://root:password@localhost",
      },
    });
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get(".error-message").text()).toContain("AI 分析暂时失败");
    expect(wrapper.get(".error-message").text()).not.toContain("postgres");
    expect(wrapper.get(".error-message").text()).not.toContain("AGENT_UNKNOWN_INTERNAL");
  });

  it("keeps ordinary career questions disabled until the active run terminates", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { runId: "9101", conversationId: "8101", status: "queued" },
    });
    mocks.getRun.mockRejectedValue(new Error("network down"));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第一个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();

    expect(wrapper.get(".career-ai-card textarea").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".career-ai-card form button").attributes("disabled")).toBeDefined();
    await wrapper.get(".career-ai-card form").trigger("submit");
    expect(mocks.askQuestion).toHaveBeenCalledOnce();

    await vi.advanceTimersByTimeAsync(9000);

    expect(wrapper.get(".error-message").text()).toContain("网络连接不稳定");
    expect(wrapper.get(".career-ai-card textarea").attributes("disabled")).toBeUndefined();
  });

  it("keeps ordinary questions disabled while clarification is required", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { runId: "9101", conversationId: "8101", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9101", status: "waiting_user", current_node: "clarification_required" },
    });
    mocks.getConversation.mockResolvedValue({
      data: { messages: [{ role: "assistant", message_type: "clarification_required", content: "请补充城市" }] },
    });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第一个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);

    expect(wrapper.get("[data-test='clarification-panel']").exists()).toBe(true);
    expect(wrapper.get(".career-ai-card textarea").attributes("disabled")).toBeDefined();
    expect(wrapper.get(".career-ai-card form button").attributes("disabled")).toBeDefined();
  });

  it("does not let a cancelled run's late network failure clear the newer question", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    let rejectOldPoll;
    const oldPoll = new Promise((resolve, reject) => { rejectOldPoll = reject; });
    mocks.askQuestion
      .mockResolvedValueOnce({ data: { runId: "9101", conversationId: "8101", status: "queued" } })
      .mockResolvedValueOnce({ data: { runId: "9102", conversationId: "8102", status: "queued" } });
    mocks.getRun
      .mockRejectedValueOnce(new Error("first failure"))
      .mockRejectedValueOnce(new Error("second failure"))
      .mockImplementationOnce(() => oldPoll)
      .mockResolvedValue({ data: { id: "9102", status: "running" } });
    mocks.cancelRun.mockResolvedValue({ data: { id: "9101", status: "cancelled" } });

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第一个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(9000);

    await wrapper.get("[data-test='question-cancel']").trigger("click");
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("第二个问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    rejectOldPoll(new Error("late third failure"));
    await flushPromises();

    expect(wrapper.find(".error-message").exists()).toBe(false);
    expect(wrapper.get("[data-test='question-cancel']").exists()).toBe(true);
    expect(wrapper.get(".career-ai-card textarea").attributes("disabled")).toBeDefined();
  });

  it("does not start report polling when its POST resolves after unmount", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    let resolveSubmission;
    mocks.generateReport.mockImplementation(() => new Promise((resolve) => {
      resolveSubmission = resolve;
    }));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    wrapper.unmount();
    resolveSubmission({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(6000);

    expect(mocks.getRun).not.toHaveBeenCalled();
  });

  it("ignores a career question POST rejection after unmount", async () => {
    mocks.authStore.isAuthenticated = true;
    let rejectSubmission;
    mocks.askQuestion.mockImplementation(() => new Promise((resolve, reject) => {
      rejectSubmission = reject;
    }));

    const wrapper = mountView();
    await flushPromises();
    const setupState = wrapper.vm.$.setupState;
    await wrapper.get(".career-ai-card textarea").setValue("异步问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    wrapper.unmount();
    rejectSubmission(new Error("late rejection"));
    await flushPromises();

    expect(mocks.getRun).not.toHaveBeenCalled();
    expect(setupState.errorMessage).toBe("");
  });

  it("does not resume polling when clarification submission resolves after unmount", async () => {
    vi.useFakeTimers();
    mocks.authStore.isAuthenticated = true;
    mocks.generateReport.mockResolvedValue({
      data: { runId: "9001", conversationId: "8001", status: "queued" },
    });
    mocks.getRun.mockResolvedValue({
      data: { id: "9001", status: "waiting_user", current_node: "clarification_required" },
    });
    mocks.getConversation.mockResolvedValue({
      data: { messages: [{ role: "assistant", message_type: "clarification_required", content: "请补充城市" }] },
    });
    let resolveClarification;
    mocks.sendMessage.mockImplementation(() => new Promise((resolve) => {
      resolveClarification = resolve;
    }));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get("[data-test='generate-analysis']").trigger("click");
    await flushPromises();
    await vi.advanceTimersByTimeAsync(3000);
    await wrapper.get("[data-test='clarification-input']").setValue("杭州");
    await wrapper.get("[data-test='clarification-form']").trigger("submit");
    wrapper.unmount();
    resolveClarification({ data: { run: { id: "9001", status: "queued" } } });
    await flushPromises();
    await vi.advanceTimersByTimeAsync(6000);

    expect(mocks.getRun).toHaveBeenCalledOnce();
  });

  it("does not write cancellation state when question cancellation resolves after unmount", async () => {
    mocks.authStore.isAuthenticated = true;
    mocks.askQuestion.mockResolvedValue({
      data: { runId: "9101", conversationId: "8101", status: "queued" },
    });
    let resolveCancellation;
    mocks.cancelRun.mockImplementation(() => new Promise((resolve) => {
      resolveCancellation = resolve;
    }));

    const wrapper = mountView();
    await flushPromises();
    await wrapper.get(".career-ai-card textarea").setValue("待取消问题");
    await wrapper.get(".career-ai-card form").trigger("submit");
    await flushPromises();
    await wrapper.get("[data-test='question-cancel']").trigger("click");
    wrapper.unmount();
    resolveCancellation({ data: { id: "9101", status: "cancelled" } });
    await flushPromises();

    expect(mocks.getRun).not.toHaveBeenCalled();
  });
});

# Frontend V2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已确认的 V2 原型落地为正式 Vue 页面，并通过稳定的数据接口、降级策略和按需加载保证可接后端且交互流畅。

**Architecture:** 页面只消费标准化的 view model；`api/` 负责 HTTP 契约，`services/` 负责响应归一化和公开数据降级，`data/` 只保存显式的演示回退数据。主导航收敛为首页与职业分析，个人资料、简历、钱包从用户入口进入；公开首页请求失败不得触发登录。

**Tech Stack:** Vue 3、Vue Router、Pinia、Axios、ECharts、Vitest、Vue Test Utils、Vite

---

### Task 1: V2 数据接口与降级边界

**Files:**
- Create: `frontend/src/api/market.js`
- Create: `frontend/src/api/career.js`
- Create: `frontend/src/api/profile.js`
- Create: `frontend/src/services/marketDashboard.js`
- Create: `frontend/src/services/marketDashboard.test.js`
- Modify: `frontend/src/api/apiContracts.test.js`

- [ ] **Step 1: Write failing API contract tests**

```js
it("requests the public market dashboard without auth-specific parameters", () => {
  marketAPI.getDashboard({ city: "杭州" });
  expect(request.get).toHaveBeenCalledWith("/analysis/market/dashboard", {
    params: { city: "杭州" },
  });
});

it("requests backend-managed AI pricing", () => {
  careerAPI.getPricing();
  expect(request.get).toHaveBeenCalledWith("/ai/pricing");
});
```

- [ ] **Step 2: Run the contract test and verify RED**

Run: `npm test -- src/api/apiContracts.test.js`

Expected: FAIL because `marketAPI`, `careerAPI`, and their modules do not exist.

- [ ] **Step 3: Implement minimal endpoint modules**

```js
export const marketAPI = {
  getDashboard(params = {}) {
    return request.get("/analysis/market/dashboard", { params });
  },
};
```

Career/profile modules follow the same single-responsibility structure and expose only the routes consumed by V2 pages.

- [ ] **Step 4: Write a failing public-data fallback test**

```js
it("returns fallback data when the public dashboard API is unavailable", async () => {
  const client = { getDashboard: vi.fn().mockRejectedValue(new Error("offline")) };
  const result = await loadMarketDashboard({}, { client, fallback: sample });
  expect(result.source).toBe("fallback");
  expect(result.data).toEqual(sample);
});
```

- [ ] **Step 5: Implement and verify the adapter**

Run: `npm test -- src/services/marketDashboard.test.js src/api/apiContracts.test.js`

Expected: PASS. The adapter returns `{ data, source, updatedAt }` and never redirects or requests login.

### Task 2: Formal application shell and access behavior

**Files:**
- Modify: `frontend/src/layout/BasicLayout.vue`
- Modify: `frontend/src/layout/BasicLayout.test.js`
- Modify: `frontend/src/router/index.js`
- Create: `frontend/src/router/routerAccess.test.js`

- [ ] **Step 1: Write failing navigation and login-timing tests**

```js
it("shows only the two primary product destinations", () => {
  const wrapper = mount(BasicLayout);
  expect(wrapper.text()).toContain("行业全景");
  expect(wrapper.text()).toContain("职业分析");
  expect(wrapper.text()).not.toContain("院校趋势");
});
```

Keep the existing test proving that the login modal opens only when `?login=true` is produced by a protected user action.

- [ ] **Step 2: Run the layout tests and verify RED**

Run: `npm test -- src/layout/BasicLayout.test.js`

Expected: FAIL because the old sidebar still contains the legacy navigation set.

- [ ] **Step 3: Implement the top navigation shell**

The shell retains message, AI task, authentication refresh, avatar and wallet behavior while replacing the permanent sidebar with a responsive top bar.

- [ ] **Step 4: Verify public and protected routes**

Run: `npm test -- src/layout/BasicLayout.test.js src/router/routerAccess.test.js`

Expected: PASS for anonymous `/`, anonymous career introduction, and login redirect only after profile/resume/wallet/generation actions.

### Task 3: Production homepage and floating AI assistant

**Files:**
- Modify: `frontend/src/views/HomeView.vue`
- Create: `frontend/src/views/HomeView.test.js`
- Modify: `frontend/src/data/homeMockData.js`
- Modify: `frontend/src/components/home/KpiCard.vue`
- Modify: `frontend/src/components/home/HomePanel.vue`
- Reuse: `frontend/src/components/charts/*.vue`

- [ ] **Step 1: Write failing homepage state tests**

```js
it("renders fallback market data without requesting login", async () => {
  marketService.load.mockResolvedValue({ data: marketFixture, source: "fallback" });
  const wrapper = mount(HomeView, pageOptions);
  await flushPromises();
  expect(wrapper.text()).toContain("行业岗位需求趋势");
  expect(router.push).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/views/HomeView.test.js`

Expected: FAIL because the current page reads `homeMockData` synchronously and does not expose loading/error/AI states.

- [ ] **Step 3: Implement the V2 homepage**

Implement filters, KPI cards, trend/salary/skill charts, salary distribution, talent structure, opportunity matrix, monthly signals, opportunity ranking and a fixed bottom-right AI panel. Querying the assistant emits a protected action; opening/closing it remains public.

- [ ] **Step 4: Add performance constraints**

Use existing async routes and ECharts lazy chunks, debounce filter refresh, keep resize observers scoped to mounted charts, avoid deep reactive copies of large chart arrays, and respect `prefers-reduced-motion`.

- [ ] **Step 5: Verify homepage behavior**

Run: `npm test -- src/views/HomeView.test.js && npm run build`

Expected: PASS and Vite build completes without new circular imports or oversized application chunks.

### Task 4: Career analysis production page

**Files:**
- Create: `frontend/src/views/CareerAnalysisView.vue`
- Create: `frontend/src/views/CareerAnalysisView.test.js`
- Modify: `frontend/src/router/index.js`
- Reuse: `frontend/src/stores/aiTask.js`
- Reuse: `frontend/src/stores/agent.js`

- [ ] **Step 1: Write failing guest and authenticated tests**

```js
it("lets a guest view the career-analysis explanation but gates generation", async () => {
  const wrapper = mount(CareerAnalysisView, guestOptions);
  await wrapper.get("[data-test='generate-analysis']").trigger("click");
  expect(wrapper.emitted("login-required")).toHaveLength(1);
});
```

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/views/CareerAnalysisView.test.js`

Expected: FAIL because the V2 page does not exist.

- [ ] **Step 3: Implement snapshot, filters, evidence and AI actions**

Render profile completion, Top 3 directions, city comparison, skill gaps, 30/60/90-day plan, report evidence and contextual AI chat. Prices come only from `careerAPI.getPricing()`.

- [ ] **Step 4: Verify generation and insufficient-balance events**

Run: `npm test -- src/views/CareerAnalysisView.test.js`

Expected: PASS for guest gating, authenticated generation, backend-managed price display, and wallet navigation on HTTP 402.

### Task 5: Profile center, resume and wallet integration

**Files:**
- Create: `frontend/src/views/ProfileCenterView.vue`
- Create: `frontend/src/views/ProfileCenterView.test.js`
- Modify: `frontend/src/views/MyResume.vue`
- Modify: `frontend/src/views/WalletView.vue`
- Modify: `frontend/src/router/index.js`

- [ ] **Step 1: Write failing profile-field tests**

```js
it("renders education, courses, skills and intentions as separate editable groups", async () => {
  const wrapper = mount(ProfileCenterView, profileOptions);
  expect(wrapper.find("[data-section='education']").exists()).toBe(true);
  expect(wrapper.find("[data-section='courses']").exists()).toBe(true);
  expect(wrapper.find("[data-section='skills']").exists()).toBe(true);
});
```

- [ ] **Step 2: Verify RED, then implement profile groups**

Run: `npm test -- src/views/ProfileCenterView.test.js`

Expected: initial FAIL, then PASS after API-backed groups and save states are implemented.

- [ ] **Step 3: Preserve confirmed resume parsing**

The existing parser remains asynchronous; parsed fields are shown as add/change/conflict candidates and only confirmed selections are posted to the profile API.

- [ ] **Step 4: Align wallet presentation without changing payment behavior**

Retain polling, order ownership checks and pending-order isolation; update only the visual shell and entry points.

### Task 6: Regression, build and browser acceptance

**Files:**
- Modify only files found defective by the checks above.

- [ ] **Step 1: Run all unit tests**

Run: `npm test`

Expected: all Vitest suites pass with no unhandled promise rejection.

- [ ] **Step 2: Run production build**

Run: `npm run build`

Expected: build succeeds and route-level chunks remain split.

- [ ] **Step 3: Browser-check desktop and mobile**

Verify public homepage, filters, AI open/close, login-on-send, career introduction, profile navigation, no horizontal overflow, readable typography and reduced-motion behavior.

- [ ] **Step 4: Check repository hygiene**

Run: `git diff --check`

Expected: no whitespace errors. Existing unrelated dirty-worktree changes remain untouched; no commit or staging is performed in this session.


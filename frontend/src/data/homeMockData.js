const homeMockData = {
  updatedAt: "2026-07-28T14:20:00+08:00",
  filters: {
    ranges: [
      { label: "近 12 个月", value: "12m" },
      { label: "近 6 个月", value: "6m" },
      { label: "近 30 天", value: "30d" },
    ],
    cities: [
      { label: "全国", value: "" },
      { label: "北京", value: "北京" },
      { label: "上海", value: "上海" },
      { label: "深圳", value: "深圳" },
      { label: "杭州", value: "杭州" },
      { label: "成都", value: "成都" },
    ],
    industries: [
      { label: "全部行业", value: "" },
      { label: "互联网 / AI", value: "互联网/AI" },
      { label: "先进制造", value: "先进制造" },
      { label: "新能源", value: "新能源" },
      { label: "生物医药", value: "生物医药" },
    ],
    educations: [
      { label: "不限学历", value: "" },
      { label: "大专", value: "大专" },
      { label: "本科", value: "本科" },
      { label: "硕士及以上", value: "硕士" },
    ],
  },
  heroSignals: [
    { label: "人工智能", value: "+24.8%" },
    { label: "先进制造", value: "+18.3%" },
  ],
  kpis: [
    { label: "在招岗位", value: "1,284,760", note: "对比上月", delta: "↑ 12.6%", icon: "▦", tone: "blue" },
    { label: "全国月薪中位数", value: "¥12,680", note: "税前月薪", delta: "↑ 4.2%", icon: "¥", tone: "mint" },
    { label: "增长最快行业", value: "人工智能", note: "岗位同比", delta: "↑ 24.8%", icon: "↗", tone: "violet" },
    { label: "技能需求热点", value: "数据分析", note: "出现频率", delta: "↑ 17.5%", icon: "⌁", tone: "orange" },
  ],
  trend: {
    years: ["8月", "10月", "12月", "2月", "4月", "6月"],
    series: [
      { name: "人工智能", values: [92, 108, 124, 148, 171, 188], color: "#176bff" },
      { name: "新能源", values: [68, 76, 91, 110, 132, 151], color: "#18a88c" },
      { name: "互联网", values: [105, 108, 113, 116, 122, 126], color: "#78899f" },
    ],
  },
  citySalaries: [
    { name: "北京", value: 18.6 },
    { name: "上海", value: 17.5 },
    { name: "深圳", value: 16.9 },
    { name: "杭州", value: 15.4 },
    { name: "广州", value: 13.3 },
  ],
  skills: [
    { name: "Python", value: 68 },
    { name: "数据分析", value: 61 },
    { name: "SQL", value: 53 },
    { name: "AI 应用", value: 49 },
    { name: "项目管理", value: 42 },
    { name: "产品设计", value: 35 },
  ],
  salaryDistribution: [
    { label: "8K 以下", value: 12 },
    { label: "8–12K", value: 24 },
    { label: "12–18K", value: 31, featured: true },
    { label: "18–25K", value: 21 },
    { label: "25–35K", value: 9 },
    { label: "35K 以上", value: 3 },
  ],
  salarySummary: { median: "¥12,680", p75: "¥21,300" },
  talentStructure: {
    education: [
      { label: "不限", value: 14 },
      { label: "本科", value: 62 },
      { label: "硕士", value: 19 },
      { label: "其他", value: 5 },
    ],
    experience: [
      { label: "应届 / 在校", value: 18 },
      { label: "1–3 年", value: 42 },
      { label: "3–5 年", value: 27 },
      { label: "5 年以上", value: 13 },
    ],
  },
  cityMatrix: [
    { city: "杭州", growth: 19.4, salary: 15.4, size: 76, tone: "blue" },
    { city: "深圳", growth: 16.8, salary: 16.9, size: 66, tone: "green" },
    { city: "上海", growth: 12.8, salary: 17.5, size: 68, tone: "violet" },
    { city: "北京", growth: 10.6, salary: 18.6, size: 70, tone: "navy" },
    { city: "成都", growth: 15.1, salary: 12.8, size: 60, tone: "amber" },
  ],
  signals: [
    { type: "需求加速", title: "AI 产品经理", detail: "岗位发布量连续 6 周上升", delta: "+28.4%", tone: "up", icon: "↗" },
    { type: "薪资上涨", title: "新能源算法", detail: "P50 月薪达到 23.6K", delta: "+11.2%", tone: "salary", icon: "¥" },
    { type: "新兴技能", title: "RAG / Agent", detail: "首次进入技能需求 Top 20", delta: "+46.8%", tone: "skill", icon: "⌁" },
    { type: "需求降温", title: "传统运营岗位", detail: "低经验岗位占比持续收缩", delta: "-8.3%", tone: "down", icon: "↓" },
  ],
  rankings: [
    { name: "人工智能 / 大模型", growth: "+24.8%", salary: "¥21.6K", gap: "高", score: "92.4" },
    { name: "新能源与储能", growth: "+18.3%", salary: "¥15.8K", gap: "高", score: "87.1" },
    { name: "智能制造", growth: "+15.7%", salary: "¥14.9K", gap: "中高", score: "83.6" },
    { name: "跨境电商", growth: "+12.2%", salary: "¥13.4K", gap: "中", score: "78.9" },
  ],
};

export default homeMockData;

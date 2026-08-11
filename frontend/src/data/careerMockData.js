const careerMockData = {
  profile: {
    name: "林晓雨",
    completion: 78,
    school: "浙江理工大学",
    major: "计算机科学与技术",
    graduation: "2027 届本科",
  },
  directions: [
    { title: "AI 产品经理", match: 92, reason: "技术理解与用户洞察形成复合优势，适合连接真实需求与 AI 能力。", tags: ["岗位增长 +28%", "杭州机会突出", "建议首选"] },
    { title: "数据产品经理", match: 86, reason: "专业课程与逻辑分析能力匹配，补齐 SQL 和指标体系后竞争力更强。", tags: ["需求稳定", "迁移能力强", "需补 SQL"] },
    { title: "商业分析师", match: 79, reason: "表达和问题拆解能力可迁移，适合作为拓展商业视野的探索方向。", tags: ["行业覆盖广", "重视表达", "需业务案例"] },
  ],
  cities: [
    { city: "杭州", jobs: "12,860", salary: "18.6K", growth: "+19.4%", competition: "中" },
    { city: "上海", jobs: "18,940", salary: "21.2K", growth: "+12.8%", competition: "高" },
    { city: "深圳", jobs: "13,520", salary: "20.8K", growth: "+16.8%", competition: "中高" },
  ],
  skills: [
    { name: "产品思维", current: 78, target: 90 },
    { name: "数据分析", current: 62, target: 82 },
    { name: "技术理解", current: 72, target: 86 },
    { name: "用户研究", current: 74, target: 84 },
    { name: "沟通协作", current: 82, target: 88 },
    { name: "商业判断", current: 55, target: 80 },
  ],
  plan: [
    { period: "30 天", title: "补齐数据基础", items: ["完成 SQL 核心课程", "拆解 2 个 AI 产品案例", "完成一次用户访谈"] },
    { period: "60 天", title: "形成项目证据", items: ["完成 AI 产品 Demo", "建立指标分析看板", "邀请真实用户试用"] },
    { period: "90 天", title: "验证职业方向", items: ["整理产品案例集", "投递 10 个匹配实习", "完成两轮模拟面试"] },
  ],
  evidence: { sampleSize: "128 万岗位", updatedAt: "2026-07-28 14:20" },
};

export default careerMockData;

export const agentProfile = {
  name: "林晓屿",
  initials: "LY",
  status: "画像已更新",
  school: "华南理工大学",
  major: "计算机科学与技术",
  grade: "大二 · 2028 届",
  location: "广州",
  target: "AI 产品经理",
  completion: 82,
  tags: ["逻辑分析", "用户洞察", "跨团队协作"],
};

export const agentSuggestions = [
  "我适合哪些职业方向？",
  "帮我规划这个学期的提升重点",
  "分析我的技能差距",
  "推荐匹配的实习机会",
];

export const initialMessages = [
  {
    id: "welcome",
    role: "assistant",
    time: "09:42",
    content:
      "你好，晓屿。我已经结合你的专业背景、兴趣偏好和当前能力，生成了一份成长工作台。你可以直接向我提问，也可以让我重新分析你的职业方向。",
  },
];

export const runStages = [
  { id: "profile", label: "读取个人画像", detail: "学业、经历与兴趣偏好" },
  { id: "market", label: "匹配行业趋势", detail: "12,860 条岗位样本" },
  { id: "skills", label: "评估能力差距", detail: "6 个核心能力维度" },
  { id: "plan", label: "生成行动方案", detail: "路线、机会与本周任务" },
];

export const responseLibrary = {
  "我适合哪些职业方向？":
    "你的技术理解、沟通表达和用户洞察形成了不错的复合优势。现阶段最匹配的是 AI 产品经理，其次是数据产品经理和商业分析师。建议先用 1 个完整项目验证产品方向，再通过实习确认行业偏好。",
  "帮我规划这个学期的提升重点":
    "本学期建议聚焦三件事：完成一个可演示的 AI 产品项目、补足 SQL 与数据分析能力、积累 2 次真实用户研究。每周投入 8 小时，按“学习 30% + 实践 50% + 复盘 20%”安排。",
  "分析我的技能差距":
    "你当前的产品思维和协作能力领先同年级，但数据分析、商业判断和 AI 工程认知仍是主要差距。优先提升 SQL、指标体系和大模型应用边界，预计 12 周可达到初级实习要求。",
  "推荐匹配的实习机会":
    "优先关注有明确导师制、能参与完整需求周期的 AI 产品或数据产品实习。当前推荐列表中，深度智联的匹配度最高；云帆科技更适合建立数据产品基本功。",
  default:
    "我结合你的个人画像与目标方向完成了快速分析。建议把问题拆成一个可验证的小目标：本周完成一次行业访谈，并产出一页需求洞察。我已将相关行动加入工作台。",
};

export const documentMock = {
  name: "林晓屿_个人简历.pdf",
  meta: "PDF · 1.8 MB",
  parsed: ["教育经历", "校园项目", "技能证书"],
};

export const careerDirections = [
  {
    id: "ai-pm",
    rank: "首选方向",
    title: "AI 产品经理",
    match: 92,
    tone: "violet",
    summary: "连接技术能力与真实用户需求，与你的复合型优势高度契合。",
    evidence: ["技术理解力较强", "用户洞察突出", "市场需求增长 38%"],
  },
  {
    id: "data-pm",
    rank: "潜力方向",
    title: "数据产品经理",
    match: 86,
    tone: "blue",
    summary: "以数据驱动产品决策，适合你严谨、善于拆解问题的特点。",
    evidence: ["逻辑分析优势", "岗位供给稳定", "需补充 SQL 能力"],
  },
  {
    id: "business-analyst",
    rank: "探索方向",
    title: "商业分析师",
    match: 79,
    tone: "amber",
    summary: "从业务和数据中寻找增长机会，可作为拓展商业视野的方向。",
    evidence: ["表达能力匹配", "行业迁移性强", "需积累业务案例"],
  },
];

export const roadmap = [
  {
    year: "大二",
    period: "现在 · 夯实基础",
    focus: "建立产品与数据双重基本功",
    items: ["掌握 SQL 与数据分析", "完成首个 AI 产品 Demo", "参与 1 次产品竞赛"],
  },
  {
    year: "大三",
    period: "2026–2027 · 实战验证",
    focus: "用真实项目验证职业方向",
    items: ["获得 1–2 段产品实习", "主导校园产品项目", "建立个人案例作品集"],
  },
  {
    year: "大四",
    period: "2027–2028 · 求职冲刺",
    focus: "形成清晰的个人竞争标签",
    items: ["聚焦 AI 产品校招", "完成系统面试训练", "沉淀 3 个深度案例"],
  },
  {
    year: "毕业后",
    period: "2028+ · 快速成长",
    focus: "成为独立负责模块的产品经理",
    items: ["深入一个垂直行业", "构建数据决策习惯", "发展跨团队影响力"],
  },
];

export const skills = [
  { name: "产品思维", score: 78, target: 90, color: "#7457e8" },
  { name: "数据分析", score: 58, target: 82, color: "#3a7cf4" },
  { name: "技术理解", score: 72, target: 86, color: "#13a89e" },
  { name: "用户研究", score: 74, target: 84, color: "#e39b32" },
  { name: "沟通协作", score: 82, target: 88, color: "#e16589" },
  { name: "商业判断", score: 55, target: 80, color: "#7c8ba1" },
];

export const opportunities = [
  {
    id: 1,
    company: "深度智联",
    logo: "深",
    title: "AI 产品经理实习生",
    location: "深圳 · 3天/周",
    match: 94,
    salary: "200–250/天",
    tags: ["大模型应用", "导师制", "可转正"],
  },
  {
    id: 2,
    company: "云帆科技",
    logo: "云",
    title: "数据产品实习生",
    location: "广州 · 4天/周",
    match: 89,
    salary: "180–220/天",
    tags: ["数据中台", "SQL", "B 端产品"],
  },
  {
    id: 3,
    company: "星河互娱",
    logo: "星",
    title: "用户研究实习生",
    location: "远程 · 3天/周",
    match: 84,
    salary: "150–200/天",
    tags: ["用户访谈", "内容产品", "弹性办公"],
  },
];

export const careerPath = [
  { level: "起点", role: "产品实习生", years: "在校", salary: "积累项目", active: true },
  { level: "第 1 阶段", role: "AI 产品助理", years: "0–2 年", salary: "15–22K" },
  { level: "第 2 阶段", role: "AI 产品经理", years: "2–5 年", salary: "25–40K" },
  { level: "长期目标", role: "产品负责人", years: "5–8 年", salary: "40–65K" },
];

export const weeklyActions = [
  { id: 1, category: "学习", title: "完成 SQL 基础课程第 4 章", meta: "预计 90 分钟", priority: "今天" },
  { id: 2, category: "实践", title: "为 AI 校园助手补充用户流程图", meta: "预计 60 分钟", priority: "周三前" },
  { id: 3, category: "探索", title: "访谈 1 位 AI 产品经理", meta: "准备 5 个核心问题", priority: "本周" },
  { id: 4, category: "求职", title: "优化简历中的项目成果描述", meta: "使用 STAR 结构", priority: "本周" },
  { id: 5, category: "复盘", title: "记录本周能力成长与问题", meta: "预计 20 分钟", priority: "周日" },
];

export const marketSignals = [
  { value: "+38%", label: "AI 产品岗位同比" },
  { value: "18.6K", label: "应届平均月薪" },
  { value: "6.2:1", label: "人才供需比" },
];

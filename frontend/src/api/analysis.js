import api from "@/utils/request";

export const analysisAPI = {
  // 获取职位宏观统计数据
  getJobStats(params) {
    return api.get("/analysis/stats", { params });
  },

  // 获取技能需求词云数据
  getSkillCloud(keyword, limit = 20) {
    return api.get("/analysis/skill-cloud", {
      params: { keyword, limit },
    });
  },

  // 获取专业-职业罗盘分析报告 (AI)
  getCareerCompass(majorName, targetIndustry = null) {
    return api.post(
      "/analysis/career-compass",
      {
        major_name: majorName,
        target_industry: targetIndustry,
      },
      { timeout: 60000 },
    );
  },

  getMajorPresets() {
    return api.get("/analysis/major/presets");
  },

  // 获取专业技能与市场分析 (供 MajorAnalysis 组件使用)
  analyzeMajor(payload) {
    return api.post("/analysis/major/analyze", payload);
  },
};

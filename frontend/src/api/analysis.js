import api from "@/utils/request";

export const analysisAPI = {
  // 获取职位宏观统计数据
  getJobStats(params) {
    return api.get("/analysis/stats", { params });
  },

  // 获取技能需求词云数据
  getSkillCloud(
    keyword,
    industry = null,
    industry_2 = null,
    industryName = null,
    industry2Name = null,
    limit = 20,
  ) {
    return api.get("/analysis/skill-cloud", {
      params: {
        keyword,
        industry,
        industry_2,
        industry_name: industryName,
        industry_2_name: industry2Name,
        limit,
      },
    });
  },

  // 获取专业-职业罗盘分析报告（AI）
  getCareerCompass(
    majorName,
    targetIndustry1 = null,
    targetIndustry2 = null,
    targetIndustry1Name = null,
    targetIndustry2Name = null,
  ) {
    return api.post(
      "/analysis/career-compass",
      {
        major_name: majorName,
        target_industry: targetIndustry1,
        target_industry_2: targetIndustry2,
        target_industry_name: targetIndustry1Name,
        target_industry_2_name: targetIndustry2Name,
      },
      { timeout: 60000 },
    );
  },

  getMajorPresets() {
    return api.get("/analysis/major/presets");
  },

  // 获取专业技能与市场分析（供 MajorAnalysis 组件使用）
  analyzeMajor(payload) {
    return api.post("/analysis/major/analyze", payload);
  },

  // 获取专业绑定的父级行业树（供职业罗盘使用）
  getMajorIndustries(majorName) {
    return api.get("/analysis/major/industries", {
      params: { major_name: majorName },
    });
  },
};

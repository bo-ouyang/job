import request from "@/utils/request";

export const commonAPI = {
  getCities(level = 1) {
    return request.get(`/cities/level/${level}`);
  },
  getIndustries(level_or_parent) {
    // If it's 0, 1, 2 it's likely a level. If it's a large number, parent code.
    if ([0, 1, 2].includes(level_or_parent)) {
      return request.get(`/industries/industries/level/${level_or_parent}`);
    }
    return request.get(`/industries/industries/parent/${level_or_parent}`);
  },
  getIndustryTree() {
    return request.get(`/industries/industries/tree/`);
  },
};

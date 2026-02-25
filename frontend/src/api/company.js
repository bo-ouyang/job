import request from "@/utils/request";

export const companyAPI = {
  getCompanies(params) {
    return request.get("/companies/", { params });
  },
  getCompanyDetail(id) {
    return request.get(`/companies/${id}`);
  },
};

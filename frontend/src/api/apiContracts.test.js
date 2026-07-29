import { beforeEach, describe, expect, it, vi } from "vitest";

const request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));
const v2Request = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  patch: vi.fn(),
  delete: vi.fn(),
}));

vi.mock("@/utils/request", () => ({ default: request }));
vi.mock("@/utils/v2Request", () => ({ default: v2Request }));

import { applicationAPI } from "./application";
import { commonAPI } from "./common";
import { companyAPI } from "./company";
import { careerAPI } from "./career";
import { marketAPI } from "./market";
import { profileAPI } from "./profile";
import { resumeAPI } from "./resume";


describe("frontend API contracts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("uses the authenticated applications collection", () => {
    applicationAPI.getMyApplications({ page: 1 });
    expect(request.get).toHaveBeenCalledWith("/applications/", {
      params: { page: 1 },
    });
  });

  it("uses canonical industry level routes", () => {
    commonAPI.getIndustries(1);
    expect(request.get).toHaveBeenCalledWith("/industries/level/1");
  });

  it("uses canonical industry parent routes", () => {
    commonAPI.getIndustries(100001);
    expect(request.get).toHaveBeenCalledWith("/industries/parent/100001");
  });

  it("uses the canonical industry tree route", () => {
    commonAPI.getIndustryTree();
    expect(request.get).toHaveBeenCalledWith("/industries/tree/");
  });

  it("uses the canonical company collection route", () => {
    companyAPI.getCompanies({ page: 1 });
    expect(request.get).toHaveBeenCalledWith("/companies", {
      params: { page: 1 },
    });
  });

  it("uses the canonical upload route", () => {
    const file = new File(["resume"], "resume.pdf", {
      type: "application/pdf",
    });
    resumeAPI.uploadFile(file);
    expect(request.post).toHaveBeenCalledWith(
      "/upload",
      expect.any(FormData),
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  });

  it("uses the public market dashboard route", () => {
    marketAPI.getDashboard({ city: "杭州", range: "12m" });
    expect(v2Request.get).toHaveBeenCalledWith("/market/dashboard", {
      params: { city: "杭州", range: "12m" },
    });
  });

  it("loads backend-managed AI pricing", () => {
    careerAPI.getPricing();
    expect(v2Request.get).toHaveBeenCalledWith("/ai/pricing");
  });

  it("keeps career generation idempotent", () => {
    careerAPI.generateReport({ city: "杭州" }, "request-1");
    expect(v2Request.post).toHaveBeenCalledWith(
      "/career-analysis/reports",
      { city: "杭州" },
      { headers: { "Idempotency-Key": "request-1" } },
    );
  });

  it("exposes profile course and skill collections", () => {
    profileAPI.getCourses();
    profileAPI.getSkills();
    expect(v2Request.get).toHaveBeenNthCalledWith(1, "/profile/courses");
    expect(v2Request.get).toHaveBeenNthCalledWith(2, "/profile/skills");
  });
});

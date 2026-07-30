import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  profile: { isAuthenticated: true, user: { username: "林晓雨" } },
  getProfile: vi.fn(),
  getCourses: vi.fn(),
  getSkills: vi.fn(),
  updateProfile: vi.fn(),
  saveCourses: vi.fn(),
  saveSkills: vi.fn(),
}));

vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.profile }));
vi.mock("@/api/profile", () => ({
  profileAPI: {
    getProfile: mocks.getProfile,
    getCourses: mocks.getCourses,
    getSkills: mocks.getSkills,
    updateProfile: mocks.updateProfile,
    saveCourses: mocks.saveCourses,
    saveSkills: mocks.saveSkills,
  },
}));

import ProfileCenterView from "./ProfileCenterView.vue";

describe("ProfileCenterView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.getProfile.mockResolvedValue({
      data: {
        name: "林晓雨", phone: "13800000000", email: "lin@example.com", city: "杭州",
        school: "浙江理工大学", education: "本科", major: "计算机科学与技术",
        graduationYear: "2027", targetCities: ["杭州", "上海"], targetRoles: ["AI 产品经理"],
        completion: 78,
      },
    });
    mocks.getCourses.mockResolvedValue({ data: [{ name: "数据结构", level: "熟练", core: true }] });
    mocks.getSkills.mockResolvedValue({ data: [{ name: "Python", level: 4, evidence: "课程与项目" }] });
  });

  it("renders education, courses, skills and intentions as separate groups", async () => {
    const wrapper = mount(ProfileCenterView, {
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    await flushPromises();

    expect(wrapper.get("[data-section='basic'] input").element.value).toBe("林晓雨");
    expect(wrapper.get("[data-section='education'] input").element.value).toBe("浙江理工大学");
    expect(wrapper.get("[data-section='courses'] input").element.value).toBe("数据结构");
    expect(wrapper.get("[data-section='skills'] input").element.value).toBe("Python");
    expect(wrapper.get("[data-section='intentions']").text()).toContain("AI 产品经理");
  });

  it("loads profile collections through reserved APIs", async () => {
    mount(ProfileCenterView, {
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    await flushPromises();

    expect(mocks.getProfile).toHaveBeenCalledOnce();
    expect(mocks.getCourses).toHaveBeenCalledOnce();
    expect(mocks.getSkills).toHaveBeenCalledOnce();
  });

  it("keeps course-name focus while the v-model value changes", async () => {
    const wrapper = mount(ProfileCenterView, {
      attachTo: document.body,
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    await flushPromises();
    const input = wrapper.get("[data-section='courses'] input");

    input.element.focus();
    await input.setValue("数据结构与算法");

    expect(document.activeElement).toBe(input.element);
    wrapper.unmount();
  });

  it("keeps skill-name focus while the v-model value changes", async () => {
    const wrapper = mount(ProfileCenterView, {
      attachTo: document.body,
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    await flushPromises();
    const input = wrapper.get("[data-section='skills'] input");

    input.element.focus();
    await input.setValue("Python 开发");

    expect(document.activeElement).toBe(input.element);
    wrapper.unmount();
  });
});

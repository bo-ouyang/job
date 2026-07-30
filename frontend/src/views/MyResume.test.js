import { createPinia, setActivePinia } from "pinia";
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

const resumeAPI = vi.hoisted(() => ({
  getMyResume: vi.fn(),
  createResume: vi.fn(),
  updateResume: vi.fn(),
  addEducation: vi.fn(),
  addWorkExperience: vi.fn(),
}));
const aiAPI = vi.hoisted(() => ({
  parseResume: vi.fn(),
}));
const profileAPI = vi.hoisted(() => ({
  applyResumeCandidates: vi.fn(),
}));
const aiTaskStore = vi.hoisted(() => ({
  addTask: vi.fn(),
  pollAndUpdate: vi.fn(),
}));

vi.mock("@/api/resume", () => ({ resumeAPI }));
vi.mock("@/api/ai", () => ({ aiAPI }));
vi.mock("@/api/profile", () => ({ profileAPI }));
vi.mock("@/stores/aiTask", () => ({ useAiTaskStore: () => aiTaskStore }));

import MyResume from "./MyResume.vue";


describe("MyResume PDF parsing", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setActivePinia(createPinia());
    resumeAPI.getMyResume.mockRejectedValue({ response: { status: 404 } });
    resumeAPI.createResume.mockResolvedValue({
      data: { id: "resume-1", name: "Lin", educations: [], work_experiences: [] },
    });
    aiAPI.parseResume.mockResolvedValue({ data: { task_id: "parse-1" } });
    aiTaskStore.pollAndUpdate.mockResolvedValue({
      result_payload: {
        name: "Lin",
        school: "Example University",
        major: "Computer Science",
        skills: ["Python"],
        educations: [
          { school: "Example University", major: "Computer Science", degree: "Bachelor" },
        ],
        work_experiences: [],
      },
    });
    profileAPI.applyResumeCandidates.mockResolvedValue({ data: {} });
  });

  it("previews parsed candidates and persists them only after confirmation", async () => {
    const wrapper = mount(MyResume, {
      global: { plugins: [createPinia()] },
    });
    await flushPromises();

    const input = wrapper.find('.empty-resume input[accept=".pdf"]');
    const file = new File(["%PDF-1.4"], "resume.pdf", { type: "application/pdf" });
    Object.defineProperty(input.element, "files", { value: [file] });
    await input.trigger("change");
    await flushPromises();

    expect(aiTaskStore.addTask).toHaveBeenCalledWith("parse-1", "resume_parse", {
      filename: "resume.pdf",
    });
    expect(aiTaskStore.pollAndUpdate).toHaveBeenCalledWith(
      "parse-1",
      expect.objectContaining({ timeout: 120000 }),
    );
    expect(wrapper.find('[data-testid="resume-parse-preview"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("Python");
    expect(resumeAPI.createResume).not.toHaveBeenCalled();
    expect(profileAPI.applyResumeCandidates).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="confirm-resume-candidates"]').trigger("click");
    await flushPromises();

    expect(profileAPI.applyResumeCandidates).toHaveBeenCalledWith(
      expect.objectContaining({
        basic: expect.objectContaining({ name: "Lin" }),
        educations: [expect.objectContaining({ school: "Example University" })],
        skills: [expect.objectContaining({ name: "Python" })],
      }),
    );
    expect(resumeAPI.createResume).not.toHaveBeenCalled();
  });
});

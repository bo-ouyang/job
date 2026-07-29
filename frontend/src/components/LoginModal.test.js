import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  authStore: {},
  route: { query: {} },
  router: { replace: vi.fn() },
}));

vi.mock("@/stores/auth", () => ({ useAuthStore: () => mocks.authStore }));
vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  useRouter: () => mocks.router,
}));

import LoginModal from "./LoginModal.vue";

describe("LoginModal credentials", () => {
  it("never pre-fills production account credentials", () => {
    const wrapper = mount(LoginModal, { props: { isOpen: true } });

    expect(wrapper.get('input[type="text"]').element.value).toBe("");
    expect(wrapper.get('input[type="password"]').element.value).toBe("");

    wrapper.unmount();
  });
});

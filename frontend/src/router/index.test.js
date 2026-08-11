import { describe, expect, it } from "vitest";
import router from "./index";

describe("application routes", () => {
  it("does not register retired market-analysis routes", () => {
    const routeNames = router.getRoutes().map((route) => route.name);

    expect(routeNames).not.toContain("career-data");
    expect(routeNames).not.toContain("compare-industries");
  });
});

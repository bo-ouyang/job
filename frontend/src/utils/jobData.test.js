import { describe, expect, it } from "vitest";

import { formatJobSalary, normalizeJobTags } from "./jobData";


describe("job data normalization", () => {
  it("keeps JSONB tag arrays", () => {
    expect(normalizeJobTags(["Python", "SQL"])).toEqual(["Python", "SQL"]);
  });

  it("parses JSON and comma-separated legacy tag strings", () => {
    expect(normalizeJobTags('["Python", "SQL"]')).toEqual(["Python", "SQL"]);
    expect(normalizeJobTags("Python, SQL")).toEqual(["Python", "SQL"]);
  });

  it("returns an empty list for invalid tag values", () => {
    expect(normalizeJobTags(null)).toEqual([]);
    expect(normalizeJobTags({ Python: true })).toEqual([]);
  });

  it("uses salary description when provided", () => {
    expect(formatJobSalary({ salary_desc: "15-25K·14薪" })).toBe("15-25K·14薪");
  });

  it("formats stored yuan values as monthly K values", () => {
    expect(formatJobSalary({ salary_min: 10000, salary_max: 20000 })).toBe("10-20K");
  });

  it("does not multiply values that are already expressed in K", () => {
    expect(formatJobSalary({ salary_min: 10, salary_max: 20 })).toBe("10-20K");
  });
});

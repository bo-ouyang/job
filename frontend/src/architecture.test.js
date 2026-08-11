import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const frontendRoot = process.cwd();
const srcRoot = resolve(frontendRoot, "src");

describe("frontend source boundary", () => {
  it("does not retain unreachable legacy modules", () => {
    const retiredFiles = [
      "api/common.js",
      "api/company.js",
      "components/charts/CareerHeatmap.vue",
      "components/HelloWorld.vue",
      "utils/jobData.js",
      "utils/pollTask.js",
      "views/AgentConversation.vue",
      "style.css",
      "assets/vue.svg",
    ];

    expect(retiredFiles.filter((path) => existsSync(resolve(srcRoot, path)))).toEqual([]);
    expect(existsSync(resolve(frontendRoot, "public/vite.svg"))).toBe(false);
  });

  it("does not install the retired word-cloud renderer", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(frontendRoot, "package.json"), "utf8"),
    );

    expect(packageJson.dependencies).not.toHaveProperty("echarts-wordcloud");
  });

  it("routes historical career tasks to the active career analysis page", () => {
    const taskEntrySources = [
      "components/AiTaskPanel.vue",
      "views/MessageCenter.vue",
    ].map((path) => readFileSync(resolve(srcRoot, path), "utf8"));

    taskEntrySources.forEach((entrySource) => {
      expect(entrySource).not.toContain('"/career-compass"');
      expect(entrySource).not.toContain('"/major-analysis"');
      expect(entrySource).toContain('"/career-analysis"');
    });
  });

  it("does not expose API client methods with no frontend consumer", () => {
    const agentApi = readFileSync(resolve(srcRoot, "api/agent.js"), "utf8");
    const walletApi = readFileSync(resolve(srcRoot, "api/wallet.js"), "utf8");

    ["updateConversation", "updateProfile"].forEach((method) => {
      expect(agentApi).not.toContain(`${method}(`);
    });
    [
      "getTransactions",
      "adminGetOrders",
      "adminRepairOrder",
      "adminMarkFailed",
      "adminManualTopup",
    ].forEach((method) => {
      expect(walletApi).not.toContain(`${method}(`);
    });
  });
});

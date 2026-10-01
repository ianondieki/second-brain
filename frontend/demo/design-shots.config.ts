import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The design-roll-out screenshots (P18; docs/platform/design/p18-design-system.md): every product screen on the running
// demo stack at 1440 and 375 px, light and dark, with a strict axe pass per shot, into docs/demo/screenshots/p18/.
// Run after `make demo` (or make demo-reset) and `python infra/demo/demo.py e2e-env`:
//   cd frontend && npx playwright test -c demo/design-shots.config.ts
//   SHOT_FILTER="login|signup" … one group of pages; SHOT_THEMES=light SHOT_WIDTHS=1440 … fewer variants.
// Not part of the e2e suite or CI; a tool of the quality loop (the scorecard quotes its axe report).
function loadE2eEnv() {
  const file = join(__dirname, "..", ".env.e2e");
  if (!existsSync(file)) return;
  for (const line of readFileSync(file, "utf-8").split(/\r?\n/)) {
    const at = line.indexOf("=");
    if (at <= 0 || line.trimStart().startsWith("#")) continue;
    const name = line.slice(0, at).trim();
    if (process.env[name] === undefined) process.env[name] = line.slice(at + 1).trim();
  }
}
loadE2eEnv();

export default defineConfig({
  testDir: ".",
  testMatch: "design-shots.spec.ts",
  outputDir: join(__dirname, "..", "test-results", "design-shots"),
  timeout: 30 * 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
    trace: "off",
    video: "off",
    screenshot: "off",
  },
});

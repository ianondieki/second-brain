import { existsSync, readFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// The recorded walkthrough of the demo story (P16-W; REQ-FND-02): its own config, apart from the E2E suite
// (playwright.config.ts has testDir ./e2e and never reads this folder). One worker, no retries, generous timeouts, a
// 1280 x 720 video of the desktop part into docs/demo/video/ (gitignored). Run it from a fresh demo:
// `make demo-reset`, `python infra/demo/demo.py e2e-env`, then `make demo-walkthrough` (or, without make,
// `cd frontend && npx playwright test -c demo/walkthrough.config.ts`). See demo/walkthrough.spec.ts and docs/demo/README.md.
//
// In CI (P16-E3: pr.yml's demo-story job; any truthy CI variable) the same story runs as a check: no video, an HTML
// report, a trace and a screenshot on failure, all under frontend/test-results/walkthrough/ and
// frontend/playwright-report/walkthrough/ (gitignored), and the story's screenshots go to
// test-results/walkthrough/screenshots/ instead of the committed docs/demo/screenshots/. WALKTHROUGH_SHOTS_DIR
// overrides where the screenshots go (the spec reads it); in CI it may never name the committed folder.

/** frontend/.env.e2e (written by `python infra/demo/demo.py e2e-env`), for variables the shell has not set. */
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

const CI = Boolean(process.env.CI);
const VIDEO = join(__dirname, "..", "..", "docs", "demo", "video");
const COMMITTED_SHOTS = join(__dirname, "..", "..", "docs", "demo", "screenshots");
const CI_RESULTS = join(__dirname, "..", "test-results", "walkthrough");
const CI_REPORT = join(__dirname, "..", "playwright-report", "walkthrough");

// The spec writes its screenshots where this names (workers inherit the runner's environment).
process.env.WALKTHROUGH_SHOTS_DIR ??= CI ? join(CI_RESULTS, "screenshots") : COMMITTED_SHOTS;
/** True when `dir` is the committed screenshot folder or anywhere inside it. */
export function insideCommittedShots(dir: string): boolean {
  const rel = relative(resolve(COMMITTED_SHOTS), resolve(dir));
  return rel === "" || (!rel.startsWith("..") && !isAbsolute(rel));
}
if (CI && insideCommittedShots(process.env.WALKTHROUGH_SHOTS_DIR)) {
  throw new Error("in CI the walkthrough never writes under docs/demo/screenshots/ (unset WALKTHROUGH_SHOTS_DIR)");
}

export default defineConfig({
  testDir: ".",
  testMatch: "walkthrough.spec.ts",
  outputDir: CI ? CI_RESULTS : VIDEO,
  // In CI well inside the demo-story job's 30 minutes (a cold stack takes about 5), so a stalled story fails the
  // test and the job still uploads its report; the story itself takes about 3 minutes.
  timeout: (CI ? 12 : 20) * 60_000,
  expect: { timeout: 20_000 },
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: CI ? [["list"], ["html", { open: "never", outputFolder: CI_REPORT }]] : "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    video: CI ? "off" : { mode: "on", size: { width: 1280, height: 720 } },
    actionTimeout: 30_000,
    navigationTimeout: 45_000,
    trace: CI ? "retain-on-failure" : "off",
    screenshot: CI ? "only-on-failure" : "off",
  },
});

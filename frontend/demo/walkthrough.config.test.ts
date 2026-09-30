// @vitest-environment node
import { join, resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

// P16-E3 (REQ-FND-02): the walkthrough config's CI switch. Locally it records the video and writes the committed
// screenshots; in CI (pr.yml's demo-story job) it records no video, writes its screenshots to test-results and never
// under docs/demo/screenshots/, and times a stalled story out well inside the job's 30 minutes.

const COMMITTED = resolve(__dirname, "..", "..", "docs", "demo", "screenshots");

async function loadConfig(env: { CI?: string; WALKTHROUGH_SHOTS_DIR?: string }) {
  vi.resetModules();
  vi.stubEnv("CI", env.CI ?? "");
  // The config fills WALKTHROUGH_SHOTS_DIR in only when unset, so each case starts from its own value.
  if (env.WALKTHROUGH_SHOTS_DIR === undefined) delete process.env.WALKTHROUGH_SHOTS_DIR;
  else vi.stubEnv("WALKTHROUGH_SHOTS_DIR", env.WALKTHROUGH_SHOTS_DIR);
  return (await import("./walkthrough.config")).default;
}

describe("walkthrough.config", () => {
  const saved = process.env.WALKTHROUGH_SHOTS_DIR;
  afterEach(() => {
    vi.unstubAllEnvs();
    if (saved === undefined) delete process.env.WALKTHROUGH_SHOTS_DIR;
    else process.env.WALKTHROUGH_SHOTS_DIR = saved;
  });

  it("records the video and writes the committed screenshots locally", async () => {
    const config = await loadConfig({});
    expect(config.use?.video).toEqual({ mode: "on", size: { width: 1280, height: 720 } });
    expect(resolve(process.env.WALKTHROUGH_SHOTS_DIR ?? "")).toBe(COMMITTED);
    expect(config.timeout).toBe(20 * 60_000);
  });

  it("in CI records no video and writes its screenshots to test-results", async () => {
    const config = await loadConfig({ CI: "true" });
    expect(config.use?.video).toBe("off");
    expect(config.use?.trace).toBe("retain-on-failure");
    expect(resolve(process.env.WALKTHROUGH_SHOTS_DIR ?? "")).toBe(
      resolve(__dirname, "..", "test-results", "walkthrough", "screenshots"),
    );
    expect(config.timeout).toBeLessThanOrEqual(15 * 60_000);
  });

  it.each([COMMITTED, join(COMMITTED, "ci"), `${COMMITTED}/../screenshots/nested`])(
    "in CI refuses to write under the committed folder (%s)",
    async (dir) => {
      await expect(loadConfig({ CI: "1", WALKTHROUGH_SHOTS_DIR: dir })).rejects.toThrow(/docs\/demo\/screenshots/);
    },
  );

  it("in CI accepts a folder beside the committed one", async () => {
    const config = await loadConfig({ CI: "1", WALKTHROUGH_SHOTS_DIR: `${COMMITTED}-ci` });
    expect(config.use?.video).toBe("off");
  });
});

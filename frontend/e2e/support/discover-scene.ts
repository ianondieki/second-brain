import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { checkScreen } from "./screen";

/**
 * What Discover's E2E needs from the stack (REQ-TREND-02, REQ-PERS-01): the demo seed's trends (`python -m bridge.seed
 * --demo`, as the CI e2e job runs it before Playwright: backend/src/bridge/seed/demo/trending.py writes simulated
 * `scout_match` and `org_interest` signals, so the demo's P2 problem trends with its project beside it) and its
 * approved research cards (what "Recommended for you" ranks). Nothing is written here: the scene only checks, through
 * the signed-in developer's own session, that the seed is there, and says how to get it when it is not.
 */
export interface Trend {
  problemId: string;
  title: string;
}

interface Board {
  problems: { problem: { id: string; title: string }; trend: { trending: boolean }; project_ids: string[] }[];
  projects: { proposal: { id: string } }[];
}

/** The first trending problem that has a trending or new project beside it (the demo's P2 problem). */
export async function seededTrend(request: APIRequestContext): Promise<Trend> {
  const response = await request.get("/api/discover/trending");
  expect(response.status(), await response.text()).toBe(200);
  const board = (await response.json()) as Board;
  const found = board.problems.find((item) => item.trend.trending && item.project_ids.length > 0);
  expect(found, "Discover needs the demo seed's trends: run `python -m bridge.seed --demo` on the stack").toBeTruthy();
  return { problemId: found!.problem.id, title: found!.problem.title };
}

/** The public problem card behind a link, through the API (the page is REQ-RES-01's, `feat/REQ-RES-01-fe`). */
export async function publishedProblemTitle(request: APIRequestContext, problemId: string): Promise<string> {
  const response = await request.get(`/api/problems/${encodeURIComponent(problemId)}`);
  expect(response.status(), await response.text()).toBe(200);
  return ((await response.json()) as { title: string }).title;
}

/**
 * Saves a full-page screenshot at 375 px (mobile project) or 1440 px (desktop) when E2E_SHOTS_DIR is set, for the task
 * card; the page keeps its viewport afterwards.
 */
export async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  await page.screenshot({ path: join(dir, `${name}-${width}.jpg`), fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  await page.setViewportSize(size);
}

/**
 * The page rules (axe, at most one primary action, no horizontal scroll) at the project's width (360 px or 1440 px)
 * and, on the mobile project, again at 375 px.
 */
export async function checkWidths(page: Page, info: TestInfo) {
  await checkScreen(page);
  if (!info.project.name.startsWith("mobile")) return;
  const size = page.viewportSize()!;
  await page.setViewportSize({ width: 375, height: size.height });
  try {
    await checkScreen(page);
  } finally {
    await page.setViewportSize(size);
  }
}

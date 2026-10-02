import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen } from "./support/screen";

// P19-F (REQ-PROP-04 originality, REQ-REPO-01 over-disclosure, warn only): the editor's "Teaser checks" card against
// the compose stack with the fake LLM (LLM_PROVIDER=fake: every model answer is the labelled demo fallback). Each
// check answers in place in a polite live region; "Continue" stays the one primary action; a reload shows today's
// last overlap answer again; the daily limit of overlap checks is worded; the rules find a teaser that says how it
// works without a model. The page rules (axe, one primary action, no horizontal scroll) hold at 360 px (mobile
// project), 375 px and 1440 px (desktop). E2E_SHOTS_DIR saves screenshots at 375 px and 1440 px.

const SERVER_STEP = { timeout: 20_000 };
const EDIT_URL = /\/dev\/ideas\/([0-9a-f-]{36})\/edit/;
const OVERLAP = "Check overlap";
const DISCLOSURE = "Check what it gives away";

/** axe and the page rules at the project's width, then at 375 px on mobile, with a screenshot when asked. */
async function checkAndShoot(page: Page, info: TestInfo, name: string) {
  await checkScreen(page, { strict: true });
  const mobile = info.project.name.startsWith("mobile");
  const size = page.viewportSize()!;
  const width = mobile ? 375 : 1440;
  if (size.width !== width) {
    await page.setViewportSize({ width, height: size.height });
    await checkScreen(page, { strict: true });
  }
  const dir = process.env.E2E_SHOTS_DIR;
  if (dir) {
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: join(dir, `${name}-${width}.jpg`), fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  }
  await page.setViewportSize(size);
}

async function waitForSave(page: Page) {
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible(SERVER_STEP);
}

/** A new idea with a title and summary, saved; returns its id. */
async function newIdea(page: Page, summary: string) {
  await page.goto("/dev/ideas/new");
  await page.getByLabel("Title", { exact: true }).fill(`Maziwa baridi ${Date.now().toString(36)}`);
  await expect(page).toHaveURL(EDIT_URL, SERVER_STEP);
  await page.getByLabel("Summary").fill(summary);
  await waitForSave(page);
  return EDIT_URL.exec(page.url())![1];
}

const answer = (page: Page, kind: "overlap" | "disclosure") => page.locator(`[data-check='${kind}']`);

test("the owner checks the teaser from the keyboard, the answers are polite, and a reload keeps today's overlap answer", async ({
  page,
}, info) => {
  await signUpDeveloper(page);
  await newIdea(page, "Dairy co-ops keep evening milk fresh until the morning collection.");
  const card = page.getByRole("region", { name: "Teaser checks" });
  await expect(card.getByRole("button")).toHaveText([OVERLAP, DISCLOSURE]);
  await expect(page.locator("[data-primary]")).toHaveText("Continue");
  await checkAndShoot(page, info, "checks-closed");

  // Keyboard: focus the button and press Enter; the answer arrives in a polite live region, focus stays put.
  await card.getByRole("button", { name: OVERLAP }).focus();
  await page.keyboard.press("Enter");
  await expect(answer(page, "overlap")).toHaveText(
    /^(No overlap with other published ideas \(compared with \d+\)\.|No other published ideas to compare with yet\.)$/,
    SERVER_STEP,
  );
  await expect(answer(page, "overlap")).toHaveAttribute("role", "status");
  await expect(card.getByRole("button", { name: OVERLAP })).toBeFocused();

  await card.getByRole("button", { name: DISCLOSURE }).focus();
  await page.keyboard.press("Space");
  await expect(answer(page, "disclosure")).toContainText(
    "No AI model is connected in this demo, and the quick check found nothing that gives away how it works.",
    SERVER_STEP,
  );
  await expect(answer(page, "disclosure").locator("[data-chip]")).toHaveText(["Demo fallback"]);
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0); // the editor keeps an empty live alert region
  await expect(page.locator("[data-primary]")).toHaveText("Continue");
  await checkAndShoot(page, info, "checks-answers");

  // A reload shows today's last overlap answer again, drawn by the server, without checking again.
  let checked = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().endsWith("/originality")) checked += 1;
  });
  await page.reload();
  await expect(card.getByText("From your last check today.")).toBeVisible(SERVER_STEP);
  await expect(card).toContainText(/No overlap with other published ideas|No other published ideas to compare with yet/);
  expect(checked).toBe(0);
});

test("a teaser that says how it works is named by the rules, and warns without blocking", async ({ page }, info) => {
  await signUpDeveloper(page);
  await newIdea(page, "We use a gradient-boosted model over M-Pesa statements to score each co-op.");
  await page.getByRole("button", { name: DISCLOSURE }).click();
  await expect(answer(page, "disclosure").locator("p").first()).toHaveText(
    "This reads like how, not what: summary.",
    SERVER_STEP,
  );
  await expect(answer(page, "disclosure")).toContainText(
    "Methods, tools and code belong in the full details, which stay confidential.",
  );
  await expect(answer(page, "disclosure").locator("[data-chip]")).toHaveCount(0);
  await expect(page.locator("[data-primary]")).toHaveText("Continue");
  await checkAndShoot(page, info, "checks-gives-away");
});

test("the eleventh overlap check of the day is refused in words", async ({ page }) => {
  await signUpDeveloper(page);
  await newIdea(page, "Dairy co-ops keep evening milk fresh until the morning collection.");
  const button = page.getByRole("button", { name: OVERLAP });
  const checked = () =>
    page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/originality"), SERVER_STEP);
  for (let n = 1; n <= 10; n += 1) {
    // One answered check at a time: a press while one runs is ignored (the button is busy).
    const [response] = await Promise.all([checked(), button.click()]);
    expect(response.status()).toBe(200);
    await expect(button).not.toHaveAttribute("aria-disabled", "true");
  }
  await expect(answer(page, "overlap")).toHaveText(/^No (overlap|other published ideas)/);
  await button.click();
  await expect(answer(page, "overlap")).toHaveText(
    "You have used today’s checks; tomorrow brings more.",
    SERVER_STEP,
  );
  await expect(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0); // the editor keeps an empty live alert region
});

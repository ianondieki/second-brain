import { spawnSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen } from "./support/screen";
import { OWNER_DATABASE_URL } from "./support/verification";

// REQ-PROP-05 (P13-F): the writing assistant in the idea editor, against a stack whose LLM is the fake
// (LLM_PROVIDER=fake: every answer is the labelled demo fallback) with FEATURE_TIER2_ENABLED=true. The consent dialog
// shows the API's wording; nothing is recorded or sent before the owner turns the assistant on; the opt-in is per
// sign-in and audited; a suggestion never changes the idea by itself; turning it off asks again next time. The page
// rules (axe, one primary action, no horizontal scroll) hold with the panel closed, the dialog open and the answer
// shown, at 360 px (mobile project), 375 px and 1440 px (desktop).
//
// Needs E2E_DATABASE_OWNER_URL: the consent and audit rows are checked as the database owner (no API lists them).
// E2E_SHOTS_DIR saves screenshots at 375 px (mobile project) and 1440 px (desktop) for the task card.

const SERVER_STEP = { timeout: 20_000 };
const EDIT_URL = /\/dev\/ideas\/([0-9a-f-]{36})\/edit/;
const OPEN = "Suggest a clearer teaser";
const TURN_OFF = "Turn off the assistant for this sign-in";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL reads the consent and audit rows").toBeTruthy();
});

/** SQL as the database owner; values travel as psql variables (quoted by psql), never spliced into the SQL text. */
function ownerSql(sql: string, variables: Record<string, string>): string {
  const args = [OWNER_DATABASE_URL!, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"];
  for (const [name, value] of Object.entries(variables)) args.push("-v", `${name}=${value}`);
  const result = spawnSync("psql", args, { input: sql, encoding: "utf-8", timeout: 15_000 });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

/** The test developer's assistant opt-in decisions, oldest first: "granted|source-kind|text_version". */
function consentRows(email: string): string[] {
  const out = ownerSql(
    "SELECT granted || '|' || split_part(source, ':', 1) || '|' || text_version FROM consents" +
      " WHERE purpose = 'tier2_llm_assistant' AND user_id = (SELECT id FROM users WHERE email = :'email')" +
      " ORDER BY created_at, id;",
    { email },
  );
  return out ? out.split("\n") : [];
}

/** The test developer's audit events of one action, oldest first, as JSON payloads. */
function auditPayloads(email: string, action: string): Array<Record<string, unknown>> {
  const out = ownerSql(
    "SELECT payload::text FROM audit_events WHERE action = :'action'" +
      " AND actor_user_id = (SELECT id FROM users WHERE email = :'email') ORDER BY seq;",
    { email, action },
  );
  return out ? out.split("\n").map((line) => JSON.parse(line) as Record<string, unknown>) : [];
}

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

test("the owner turns the assistant on for this sign-in, sees a labelled answer that changes nothing, and turns it off", async ({
  page,
}, info) => {
  const email = await signUpDeveloper(page);
  const title = `Maziwa baridi ${Date.now().toString(36)}`;
  const summary = "Shared solar chillers for dairy co-ops, booked by SMS.";
  await page.goto("/dev/ideas/new");
  await page.getByLabel("Title", { exact: true }).fill(title);
  await expect(page).toHaveURL(EDIT_URL, SERVER_STEP);
  await page.getByLabel("Summary").fill(summary);
  await waitForSave(page);
  const id = EDIT_URL.exec(page.url())![1];

  // Closed: one secondary button; "Continue" stays the one primary action.
  const panel = page.locator("#assistant-panel");
  await expect(page.getByRole("button", { name: OPEN })).toBeVisible();
  await expect(page.locator("[data-primary]")).toHaveText("Continue");
  await checkAndShoot(page, info, "assistant-closed");

  // The dialog shows the API's own wording; nothing is recorded or sent before the owner chooses.
  const consent = await page.request.get(`/api/me/proposals/${id}/assistant/consent`);
  expect(consent.ok()).toBeTruthy();
  const wording = (await consent.json()) as { granted: boolean; text: string; version: string };
  expect(wording.granted).toBe(false);
  await page.getByRole("button", { name: OPEN }).click();
  const dialog = page.getByRole("dialog", { name: "Turn on the writing assistant?" });
  await expect(dialog).toBeVisible(SERVER_STEP);
  await expect(dialog.locator("[data-consent-version]")).toHaveText(wording.text);
  await expect(dialog.getByRole("button", { name: "Not now" })).toBeFocused();
  expect(consentRows(email)).toEqual([]);
  expect(auditPayloads(email, "proposal.assistant_suggested")).toEqual([]);
  await checkAndShoot(page, info, "assistant-consent");

  // "Not now": the panel closes, focus returns, still nothing recorded or sent.
  await dialog.getByRole("button", { name: "Not now" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: OPEN })).toBeFocused();
  expect(consentRows(email)).toEqual([]);
  expect(auditPayloads(email, "proposal.assistant_suggested")).toEqual([]);

  // Turned on: a session-scoped grant of the version shown, audited, then one answer: the fake's demo fallback.
  await page.getByRole("button", { name: OPEN }).click();
  await dialog.getByRole("button", { name: "Turn on and ask" }).click();
  await expect(dialog).toBeHidden(SERVER_STEP);
  await expect(panel.getByText("This demo has no AI model connected, so there is no suggestion.")).toBeVisible(
    SERVER_STEP,
  );
  await expect(panel.locator("[data-chip]")).toHaveText(["Demo fallback"]);
  await expect(panel.getByRole("button", { name: "Use this" })).toHaveCount(0);
  await expect(panel.getByRole("heading", { name: "Writing assistant's answer" })).toBeFocused();
  expect(consentRows(email)).toEqual([`true|session|${wording.version}`]);
  const granted = auditPayloads(email, "consent.changed").filter((p) => "tier2_llm_assistant" in p);
  expect(granted).toEqual([
    { tier2_llm_assistant: true, scope: "session", text_version: wording.version, from_proposal_id: id },
  ]);
  const asked = auditPayloads(email, "proposal.assistant_suggested");
  expect(asked).toHaveLength(1);
  expect(asked[0]).toMatchObject({ status: "demo_fallback", demo_fallback: true });
  await checkAndShoot(page, info, "assistant-answer");

  // The idea is as the owner wrote it: on the page and in the API.
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(title);
  await expect(page.getByLabel("Summary")).toHaveValue(summary);
  const saved = (await (await page.request.get(`/api/me/proposals/${id}`)).json()) as {
    draft: { teaser: { title: string; summary: string } };
  };
  expect(saved.draft.teaser).toMatchObject({ title, summary });

  // Still on for this sign-in: closing and opening again asks at once, without the dialog.
  await panel.getByRole("button", { name: "Close" }).click();
  await expect(page.getByRole("button", { name: OPEN })).toBeFocused();
  await page.getByRole("button", { name: OPEN }).click();
  await expect(panel.locator("[data-chip]")).toHaveText(["Demo fallback"], SERVER_STEP);
  await expect(dialog).toBeHidden();
  await expect.poll(() => auditPayloads(email, "proposal.assistant_suggested").length).toBe(2);

  // Turned off: withdrawn and audited; the next ask shows the dialog again.
  await panel.getByRole("button", { name: TURN_OFF }).click();
  const off = panel.getByText("The writing assistant is off for this sign-in.");
  await expect(off).toBeVisible(SERVER_STEP);
  await expect(page.locator(":focus")).toContainText("The writing assistant is off for this sign-in.");
  await expect(panel.getByRole("button", { name: TURN_OFF })).toHaveCount(0);
  const after = (await (await page.request.get(`/api/me/proposals/${id}/assistant/consent`)).json()) as {
    granted: boolean;
  };
  expect(after.granted).toBe(false);
  expect(consentRows(email)).toEqual([`true|session|${wording.version}`, `false|session|${wording.version}`]);
  await checkAndShoot(page, info, "assistant-off");

  await expect(panel.getByRole("button", { name: "Ask again" })).toHaveCount(0);
  await panel.getByRole("button", { name: "Turn on and ask" }).click(); // off: asking again means turning it on
  await expect(dialog).toBeVisible(SERVER_STEP);
  await dialog.getByRole("button", { name: "Not now" }).click();
  await expect(page.getByRole("button", { name: OPEN })).toBeFocused();
  expect(auditPayloads(email, "proposal.assistant_suggested")).toHaveLength(2);
});

test("a new idea with no title or summary asks for one first and sends nothing", async ({ page }) => {
  const email = await signUpDeveloper(page);
  await page.goto("/dev/ideas/new");
  await page.getByRole("button", { name: OPEN }).click();
  await expect(page.locator("#assistant-panel").getByRole("alert")).toHaveText(
    "Write a title or a summary first, then ask.",
  );
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page).toHaveURL(/\/dev\/ideas\/new$/); // no draft was made
  expect(consentRows(email)).toEqual([]);
});

// The fake LLM never writes a teaser, so this case stubs the one suggestion response at the network layer (the
// consent, the editor's save and the API's copy of the idea stay real): the suggestion sits beside the current text,
// labelled, and reaches the idea only through "Use this" and the editor's own save.
test("a suggestion reaches the idea only through 'Use this' and the editor's save", async ({ page }, info) => {
  await signUpDeveloper(page);
  const title = `Maziwa baridi ${Date.now().toString(36)}`;
  const summary = "Chillers for co-ops.";
  await page.goto("/dev/ideas/new");
  await page.getByLabel("Title", { exact: true }).fill(title);
  await expect(page).toHaveURL(EDIT_URL, SERVER_STEP);
  await page.getByLabel("Summary").fill(summary);
  await waitForSave(page);
  const id = EDIT_URL.exec(page.url())![1];
  const suggestion = {
    title: "Shared solar chillers for dairy co-ops",
    summary: "Dairy co-ops book shared solar chillers by SMS, so evening milk stays fresh until the morning collection.",
  };
  let asked = 0;
  await page.route(`**/api/me/proposals/${id}/assistant/suggestions`, async (route) => {
    asked += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "suggested",
        message: null,
        ai_drafted: true,
        demo_fallback: false,
        version_id: id,
        teaser: suggestion,
        placement: [
          { field: "impact_claims", move: "to_tier2", reason: "It describes how the chillers are wired, which is detail." },
        ],
      }),
    });
  });
  const patches: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "PATCH" && request.url().endsWith(`/api/me/proposals/${id}`)) patches.push(request.url());
  });

  await page.getByRole("button", { name: OPEN }).click();
  const dialog = page.getByRole("dialog", { name: "Turn on the writing assistant?" });
  await dialog.getByRole("button", { name: "Turn on and ask" }).click();
  const panel = page.locator("#assistant-panel");
  await expect(panel.locator("[data-teaser='suggested']")).toContainText(suggestion.title, SERVER_STEP);
  await expect(panel.locator("[data-teaser='now']")).toContainText(title);
  await expect(panel.locator("[data-chip]")).toHaveText(["AI-drafted"]);
  await expect(panel.getByText("Expected impact might belong in the full details, which stay confidential.")).toBeVisible();
  await checkAndShoot(page, info, "assistant-suggestion");

  // Shown, not applied: the fields and the saved draft keep the owner's text.
  await page.waitForTimeout(2000); // longer than the editor's autosave delay
  expect(patches).toEqual([]);
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(title);

  await panel.getByRole("button", { name: "Use this" }).click();
  await expect(page.locator(":focus")).toContainText("The suggestion is now in your title and summary.");
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(suggestion.title);
  await expect(page.getByLabel("Summary")).toHaveValue(suggestion.summary);
  await waitForSave(page);
  expect(patches.length).toBeGreaterThanOrEqual(1);
  const saved = (await (await page.request.get(`/api/me/proposals/${id}`)).json()) as {
    draft: { teaser: { title: string; summary: string } };
  };
  expect(saved.draft.teaser).toMatchObject(suggestion);
  expect(asked).toBe(1);
  // The owner's own words stay beside it as "Before"; the text is never shown next to itself.
  await expect(panel.locator("[data-teaser='before']")).toContainText(title);
  await expect(panel.locator("[data-teaser='now']")).toHaveCount(0);
  await checkAndShoot(page, info, "assistant-applied");

  // "Undo" puts them back through the same save.
  const saves = patches.length;
  await panel.getByRole("button", { name: "Undo" }).click();
  await expect(page.locator(":focus")).toHaveText("Your title and summary are back as they were.");
  await expect(page.getByLabel("Title", { exact: true })).toHaveValue(title);
  await expect(page.getByLabel("Summary")).toHaveValue(summary);
  await waitForSave(page);
  expect(patches.length).toBeGreaterThan(saves);
  const undone = (await (await page.request.get(`/api/me/proposals/${id}`)).json()) as {
    draft: { teaser: { title: string; summary: string } };
  };
  expect(undone.draft.teaser).toMatchObject({ title, summary });
});

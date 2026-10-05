import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Browser, type Page, type TestInfo } from "@playwright/test";

import { appToday } from "./support/clock";
import { signInThroughScreens } from "./support/moderation-scene";
import { newStaffAdmin } from "./support/research-scene";
import { checkScreen } from "./support/screen";
import { ownerSql, OWNER_DATABASE_URL, PASSWORD, pitchFromDeveloper, post, signUpOrg, type DevSide, type OrgSide } from "./support/tracker-scene";

// REQ-ENG-11 (AC-TRACK-9, N18; docs/spec/06 6.9 "Messages tab", docs/spec/07 item 1): the engagement thread walked by
// both parties in their own browsers against the compose stack. Before Approve to proceed (non-binding) neither side
// can write and the organisation cannot read (the API's 403 thread_not_open); from INTEREST_CONFIRMED the developer
// and the organisation's contact write to each other, with files that are scanned (the stack's fake scanner refuses
// the EICAR test string), contact details refused before first contact, unread counts on the lists and the tab, a
// report of the other side's message, the messages on the History tab for both, and a read-only thread once the
// engagement ends; a moderator reads the one reported message and dismisses the report. Strict axe, one primary action
// and no horizontal scroll on every screen (mobile-360 and desktop).
//
// Needs E2E_DATABASE_OWNER_URL (test-only state: D1/D2, E2, signatory, staff) and an API with
// FEATURE_DEALS_ENABLED=true, like tracker.spec.ts. E2E_SHOTS_DIR saves screenshots at 375 px (mobile project) and
// 1440 px (desktop).

const SERVER_STEP = { timeout: 20_000 };
// The EICAR anti-virus test string (harmless by design), as proposal-wizard.spec.ts sends it.
const EICAR = String.raw`X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*`;
const PLAN = "# Pilot plan\n\nTwo co-ops, six weeks, one chiller each.\n";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  await page.screenshot({ path: join(dir, `${name}-${width}.jpg`), fullPage: true, type: "jpeg", quality: 70, scale: "css" });
  await page.setViewportSize(size);
}

interface Scene {
  dev: DevSide;
  org: OrgSide;
  devPage: Page;
  orgPage: Page;
  close: () => Promise<void>;
}

/** The developer on the test's page, the organisation in its own browser context; a SUBMITTED engagement. */
async function scene(page: Page, browser: Browser, info: TestInfo): Promise<Scene> {
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  const org = await signUpOrg(orgPage.request);
  const dev = await pitchFromDeveloper(page.request, org.orgId);
  return { dev, org, devPage: page, orgPage, close: () => orgContext.close() };
}

/** Runs one tracker command through the API, on the engagement's current lock_version. */
async function command(request: APIRequestContext, id: string, segment: string, body: Record<string, unknown> = {}) {
  const read = await request.get(`/api/engagements/${id}`);
  expect(read.ok()).toBeTruthy();
  const { lock_version } = (await read.json()) as { lock_version: number };
  await post(request, `/api/engagements/${id}/${segment}`, { lock_version, ...body });
}

/** The organisation starts the review and approves to proceed (non-binding), naming itself the contact: INTEREST_CONFIRMED. */
async function approve(request: APIRequestContext, id: string) {
  const me = (await (await request.get("/api/auth/me")).json()) as { user: { id: string } };
  await command(request, id, "start-review");
  await command(request, id, "approve", {
    contact_user_id: me.user.id,
    contact_channel: "email",
    contact_by: await appToday(request),
  });
}

/** Posts a message through the API (the scene's setup, not the screen under test). */
async function postMessage(request: APIRequestContext, id: string, body: string): Promise<string> {
  const sent = await post<{ id: string }>(request, `/api/engagements/${id}/messages`, { body, attachment_ids: [] }, 201);
  return sent.id;
}

/** The thread's buttons work once its island has hydrated. */
async function threadReady(page: Page) {
  await expect(page.locator("[data-thread][data-hydrated='true']")).toBeVisible(SERVER_STEP);
}

const tabs = (page: Page) => page.getByRole("navigation", { name: "Engagement sections" });

test("AC-TRACK-9: the thread opens at Approve to proceed, then both sides write, attach, read and report", async ({ page, browser }, info) => {
  test.setTimeout(300_000);
  const { dev, org, devPage, orgPage, close } = await scene(page, browser, info);
  const id = dev.engagementId;
  const devThread = `/dev/engagements/${id}/messages`;
  const orgThread = `/org/engagements/${id}/messages`;
  try {
    // Before INTEREST_CONFIRMED: one sentence on each side, no composer; the organisation cannot read the thread.
    // Links written before the Messages route (?tab=messages) still land on it.
    await orgPage.goto(`/org/engagements/${id}?tab=messages`);
    await expect(orgPage).toHaveURL(new RegExp(`${orgThread}#messages-heading$`), SERVER_STEP);
    await expect(tabs(orgPage).getByRole("link", { name: "Messages" })).toHaveAttribute("aria-current", "page");
    await expect(orgPage.locator("[data-thread-closed='not_open'] p")).toHaveText(
      "Messages open when your organisation approves to proceed, a non-binding step.",
    );
    await expect(orgPage.locator("[data-composer], [data-thread]")).toHaveCount(0);
    const refused = await orgPage.request.get(`/api/engagements/${id}/messages`);
    expect(refused.status()).toBe(403);
    expect(((await refused.json()) as { detail: { code: string } }).detail.code).toBe("thread_not_open");
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "messages-org-not-open");

    await devPage.goto(devThread);
    await expect(devPage.locator("[data-thread-closed='not_open'] p")).toHaveText(
      `Messages open when ${org.orgName} approves to proceed, a non-binding step.`,
    );
    await expect(devPage.locator("[data-composer]")).toHaveCount(0);
    await checkScreen(devPage, { strict: true });

    await approve(orgPage.request, id);

    // The developer writes: Send is the one primary action; contact details are refused before first contact.
    await devPage.goto(devThread);
    await threadReady(devPage);
    await expect(devPage.locator("[data-thread-empty]")).toHaveText("No messages yet: write the first one below.");
    await expect(devPage.locator("[data-primary]")).toHaveText("Send");
    const box = devPage.getByLabel("Your message");
    await box.fill("Call me on 0712 345 678 to plan the pilot.");
    await devPage.getByRole("button", { name: "Send", exact: true }).click();
    await expect(devPage.locator("#message-body-error")).toContainText(
      "before first contact is made, contact details are shared only through the tracker's contact step",
      SERVER_STEP,
    );
    await expect(box).toHaveAttribute("aria-invalid", "true");

    // Two files: a plan that scans clean and the EICAR test file, which the scan blocks.
    await box.fill("Habari Rita,\nThe pilot plan is attached.\nSix weeks, two co-ops.");
    await devPage.locator("[data-composer] input[type=file]").setInputFiles([
      { name: "pilot-plan.md", mimeType: "text/markdown", buffer: Buffer.from(PLAN) },
      { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from(EICAR) },
    ]);
    await expect(devPage.locator("[data-pending-file='pilot-plan.md']")).toHaveAttribute("data-status", "ready", SERVER_STEP);
    const blocked = devPage.locator("[data-pending-file='notes.txt']");
    await expect(blocked).toHaveAttribute("data-status", "blocked", SERVER_STEP);
    await expect(blocked).toContainText("This file did not pass the malware scan, so it was not kept.");
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "messages-dev-composer");
    await devPage.getByRole("button", { name: "Send", exact: true }).click();
    await expect(devPage.getByText("Remove the blocked files before you send.")).toBeVisible();
    await blocked.getByRole("button", { name: "Remove" }).click();
    await devPage.getByRole("button", { name: "Send", exact: true }).click();
    const sent = devPage.locator("[data-message][data-mine='true']");
    await expect(sent).toHaveCount(1, SERVER_STEP);
    await expect(sent).toContainText("You");
    await expect(sent.locator("[data-body]")).toHaveText("Habari Rita,\nThe pilot plan is attached.\nSix weeks, two co-ops.");
    await expect(sent.locator("a")).toHaveCount(0);
    await expect(sent.locator("[data-file]")).toContainText("pilot-plan.md");
    await expect(box).toHaveValue("");

    // The organisation: the unread count on its list and on the tab, then the message, its file and a reply.
    await orgPage.goto("/org/engagements");
    const row = orgPage.locator("article").filter({ hasText: dev.title });
    await expect(row.locator("[data-unread-messages]")).toHaveText("1 unread message");
    expect(await row.locator("[data-chip]").count()).toBeLessThanOrEqual(2);
    await checkScreen(orgPage, { strict: true });
    await orgPage.goto(`/org/engagements/${id}`);
    const messagesTab = tabs(orgPage).getByRole("link", { name: /^Messages/ });
    await expect(messagesTab.locator("[data-unread='1']")).toHaveText("1");
    await expect(messagesTab).toHaveAccessibleName("Messages 1 unread message");
    await messagesTab.click();
    await expect(orgPage).toHaveURL(new RegExp(`${orgThread}#messages-heading$`), SERVER_STEP);
    await threadReady(orgPage);
    // The route lands on the thread: its heading is on screen (at 360 x 780 too), below the turn card and the spine.
    await expect(orgPage.locator("#messages-heading")).toBeInViewport();
    const fromDev = orgPage.locator("[data-message][data-mine='false']");
    await expect(fromDev).toContainText(dev.name);
    await expect(fromDev).toContainText("Developer");
    await expect(fromDev.locator("[data-body]")).toHaveText("Habari Rita,\nThe pilot plan is attached.\nSix weeks, two co-ops.");
    await expect(orgPage.locator("[data-new-divider]")).toHaveText("New");
    const download = orgPage.waitForEvent("download");
    await fromDev.locator("[data-file]").getByRole("button", { name: "Download" }).click();
    expect((await download).suggestedFilename()).toBe("pilot-plan.md");
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "messages-org-thread");
    await orgPage.getByLabel("Your message").fill("Asante. Can we meet on Thursday at the Kericho branch?");
    await orgPage.getByRole("button", { name: "Send", exact: true }).click();
    await expect(orgPage.locator("[data-message][data-mine='true']")).toHaveCount(1, SERVER_STEP);
    // Read: the tab has no count any more.
    await orgPage.goto(`/org/engagements/${id}`);
    await expect(tabs(orgPage).locator("[data-unread]")).toHaveCount(0);

    // The developer reports the organisation's reply: at least one reason, then what happens next.
    await devPage.goto(devThread);
    await threadReady(devPage);
    const reply = devPage.locator("[data-message][data-mine='false']");
    await expect(reply).toContainText("Rita Wanjiru");
    await expect(reply).toContainText(org.orgName);
    await reply.getByRole("button", { name: "Report" }).click();
    const sheet = devPage.locator("dialog[open]");
    await expect(sheet.getByRole("heading", { name: "Report this message" })).toBeVisible();
    await sheet.getByRole("button", { name: "Send the report" }).click();
    await expect(sheet).toContainText("Choose at least one reason.");
    await sheet.getByLabel("Something else").check();
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "messages-dev-report");
    await sheet.getByRole("button", { name: "Send the report" }).click();
    await expect(reply.locator("[data-reported='reported']")).toHaveText(
      "Reported. A moderator will review this message; it stays in the thread meanwhile.",
      SERVER_STEP,
    );
    await expect(devPage.locator("dialog[open]")).toHaveCount(0);
    await checkScreen(devPage, { strict: true });

    // The History tab lists both messages, the same for both parties, never their text.
    await devPage.goto(`/dev/engagements/${id}?tab=history`);
    await orgPage.goto(`/org/engagements/${id}?tab=history`);
    const devHistory = await devPage.locator("[data-history-message] h3").allTextContents();
    expect(devHistory).toEqual([`Message from Rita Wanjiru`, `Message from ${dev.name}`]);
    expect(await orgPage.locator("[data-history-message] h3").allTextContents()).toEqual(devHistory);
    await expect(devPage.locator("main")).not.toContainText("Kericho branch");
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "messages-dev-history");
  } finally {
    await close();
  }
});

test("an ended engagement keeps its thread to read, without the composer", async ({ page, browser }, info) => {
  test.setTimeout(180_000);
  const { dev, devPage, orgPage, close } = await scene(page, browser, info);
  const id = dev.engagementId;
  try {
    await approve(orgPage.request, id);
    await postMessage(orgPage.request, id, "Welcome aboard.\nWe start the review of terms next week.");
    await command(devPage.request, id, "withdraw");
    for (const [side, view] of [
      ["dev", devPage],
      ["org", orgPage],
    ] as const) {
      await view.goto(`/${side}/engagements/${id}/messages`);
      await threadReady(view);
      await expect(view.locator("[data-message] [data-body]")).toHaveText("Welcome aboard.\nWe start the review of terms next week.");
      await expect(view.locator("[data-composer]")).toHaveCount(0);
      await expect(view.locator("[data-thread-closed='read_only']")).toHaveText(
        "This engagement has ended, so the thread stays here to read and no new messages can be sent.",
      );
      await checkScreen(view, { strict: true });
    }
    await shot(devPage, info, "messages-dev-read-only");
  } finally {
    await close();
  }
});

test("a moderator reads the one reported message and dismisses the report", async ({ page, browser, baseURL }, info) => {
  test.setTimeout(240_000);
  const { dev, devPage, orgPage, close } = await scene(page, browser, info);
  const id = dev.engagementId;
  const staffContext = await browser.newContext({ ...info.project.use });
  const staffPage = await staffContext.newPage();
  try {
    await approve(orgPage.request, id);
    const messageId = await postMessage(orgPage.request, id, "Send the files to our procurement desk.\nThey sign off this week.");
    await post(devPage.request, `/api/engagements/${id}/messages/${messageId}/report`, { reasons: ["spam", "other"] });
    const caseId = ownerSql("SELECT id FROM moderation_cases WHERE subject_type = 'message' AND subject_id = CAST(:'m' AS uuid);", {
      m: messageId,
    });
    expect(caseId).toMatch(/^[0-9a-f-]{36}$/);

    const moderator = await newStaffAdmin(browser, baseURL!, { role: "moderator" });
    await signInThroughScreens(staffPage, moderator, PASSWORD);
    await expect(staffPage).toHaveURL(/\/admin\/moderation$/, SERVER_STEP);
    await staffPage.goto(`/admin/moderation/cases/${caseId}`);
    await expect(staffPage.getByRole("heading", { level: 1, name: "Reported message" })).toBeVisible();
    await expect(staffPage.locator("[data-message-body]")).toHaveText("Send the files to our procurement desk.\nThey sign off this week.");
    await expect(staffPage.locator("[data-sender='org']")).toHaveText("Sent by the organisation");
    await expect(staffPage.locator("[data-reasons] li")).toHaveText(["Spam", "Something else"]);
    await expect(staffPage.locator("[data-message-decision][data-hydrated='true']")).toBeVisible(SERVER_STEP);
    await checkScreen(staffPage, { strict: true });
    await shot(staffPage, info, "messages-moderation-case");
    await staffPage.getByLabel("Note for the record (optional)").fill("An ordinary hand-over request.");
    await staffPage.getByRole("button", { name: "Dismiss", exact: true }).click();
    const dialog = staffPage.locator("dialog[open]");
    await expect(dialog.getByRole("heading", { name: "Dismiss this report?" })).toBeVisible();
    await checkScreen(staffPage, { strict: true });
    await dialog.getByRole("button", { name: "Yes, dismiss" }).click();
    await expect(staffPage.getByRole("status").filter({ hasText: "Dismissed. The case is closed." })).toBeVisible(SERVER_STEP);
    await expect(staffPage.locator("[data-header-tag='outcome']")).toHaveText("Dismissed", SERVER_STEP);
    await checkScreen(staffPage, { strict: true });
  } finally {
    await staffContext.close();
    await close();
  }
});

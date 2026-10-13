import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Browser, type Page, type TestInfo } from "@playwright/test";

import { DEMO_PASSWORD, DemoStaff, signInThroughScreens } from "./support/moderation-scene";
import { checkScreen } from "./support/screen";
import { demoTotpSecret } from "./support/totp";
import {
  actionsReady,
  OWNER_DATABASE_URL,
  ownerSql,
  pitchFromDeveloper,
  post,
  signUpOrg,
} from "./support/tracker-scene";

// P28 track A (REQ-ENG-06, AC-TRACK-5) with track B's line (REQ-NOT-05): a public entity's tracker waits in stage 3b,
// its owner chooses the procurement route in the sheet (the five routes, the direct justification rule, the contact-by
// date), both parties then read the route on their trackers and in History, and the developer's tracker carries no
// escalation line. The page rules (axe strict, one primary action, no horizontal scroll) on each screen, the sheet
// open included.
//
// The scene: the demo seed's State Department D (fixture), where Halima Yusuf (owner and admin) chooses the route of
// Brian Otieno's P4, signed in through the screens with the demo password and the address's TOTP. That engagement
// can take a route once: when it has already left 3b on this stack (the other project's run, a rerun), the spec builds
// the same scene through the API as the tracker's specs do (a new E2 organisation marked a public entity by the
// database owner, a developer's pitch, the review and the approval), so it runs again on any seeded stack.
//
// Needs E2E_DATABASE_OWNER_URL and an API with FEATURE_DEALS_ENABLED=true. E2E_SHOTS_DIR saves screenshots at 375 px
// (mobile project) and 1440 px (desktop), light and dark.

const STEP = { timeout: 20_000 };
const DONE = "Done. The tracker is up to date.";
const STATE_D = "State Department D (fixture)";
const JUSTIFICATION = "The department already runs this developer's USSD gateway; a second supplier would duplicate it.";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL: the seeded engagement's state, and the scene's public entity").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  const size = page.viewportSize()!;
  const width = info.project.name.startsWith("mobile") ? 375 : 1440;
  await page.setViewportSize({ width, height: size.height });
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.screenshot({ path: join(dir, `${name}-${width}-${scheme}.jpg`), fullPage: true, type: "jpeg", quality: 70 });
  }
  await page.emulateMedia({ colorScheme: null });
  await page.setViewportSize(size);
}

interface Scene {
  engagementId: string;
  /** The organisation's page (its owner and admin, signed in). */
  orgPage: Page;
  /** The developer's page, signed in, in its own browser context. */
  devPage: Page;
  close: () => Promise<void>;
}

/** The seeded State Department D engagement while it still waits in 3b, else null. */
function seededInRoute(): string | null {
  const id = ownerSql(
    "SELECT e.id FROM engagements e JOIN organizations o ON o.id = e.org_id" +
      " WHERE o.legal_name = :'org' AND o.public_entity AND e.state = 'PROCUREMENT_ROUTE' LIMIT 1;",
    { org: STATE_D },
  );
  return id || null;
}

async function scene(page: Page, browser: Browser, info: TestInfo): Promise<Scene> {
  const devContext = await browser.newContext({ ...info.project.use });
  const devPage = await devContext.newPage();
  const close = () => devContext.close();
  const seeded = seededInRoute();
  if (seeded) {
    const halima = "owner@state-d.example";
    const brian = "brian@developers.example";
    await signInThroughScreens(page, new DemoStaff(halima, "Halima Yusuf", demoTotpSecret(halima)), DEMO_PASSWORD);
    await expect(page).toHaveURL(/\/org$/, STEP);
    await signInThroughScreens(devPage, new DemoStaff(brian, "Brian Otieno", demoTotpSecret(brian)), DEMO_PASSWORD);
    await expect(devPage).toHaveURL(/\/dev$/, STEP);
    return { engagementId: seeded, orgPage: page, devPage, close };
  }
  // The same scene built through the API: the organisation's first member is its owner, admin and signatory.
  const org = await signUpOrg(page.request, { orgName: `County Department ${Date.now().toString(36)} (test)` });
  ownerSql("UPDATE organizations SET public_entity = true WHERE id = CAST(:'org' AS uuid);", { org: org.orgId });
  const dev = await pitchFromDeveloper(devPage.request, org.orgId);
  const me = (await (await page.request.get("/api/auth/me")).json()) as { user: { id: string } };
  const path = `/api/engagements/${dev.engagementId}`;
  const read = async () => (await (await page.request.get(path)).json()) as { lock_version: number; state: string };
  await post(page.request, `${path}/start-review`, { lock_version: (await read()).lock_version });
  await post(page.request, `${path}/approve`, {
    lock_version: (await read()).lock_version,
    contact_user_id: me.user.id,
    contact_channel: "email",
  });
  expect((await read()).state, "a public entity's approval enters 3b").toBe("PROCUREMENT_ROUTE");
  return { engagementId: dev.engagementId, orgPage: page, devPage, close };
}

test("a public entity's owner chooses the procurement route; the developer reads it (REQ-ENG-06)", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(180_000);
  const { engagementId, orgPage, devPage, close } = await scene(page, browser, info);
  try {
    // 3b on the organisation's tracker: the stage among Contact and NDA's own, the step named, one primary action.
    await orgPage.goto(`/org/engagements/${engagementId}`);
    await actionsReady(orgPage);
    const current = orgPage.locator("[data-stepper] [aria-current='step']");
    await expect(current).toHaveAttribute("data-group", "contact_nda");
    await expect(current.locator("[data-substage='PROCUREMENT_ROUTE']")).toHaveAttribute("data-state", "current");
    await expect(orgPage.locator("[data-whose-turn]")).toContainText("Your next step: Choose the procurement route");
    const choose = orgPage.locator("[data-actions]").getByRole("button", { name: "Choose the procurement route" });
    await expect(choose).toHaveAttribute("data-primary", "");
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "p28a-org-3b");

    // The sheet: loaded on press, the five routes; direct procurement without its justification is refused inline.
    await choose.click();
    const sheet = orgPage.getByRole("dialog", { name: "Choose the procurement route" });
    await expect(sheet).toBeVisible(STEP);
    await expect(sheet.getByRole("radio")).toHaveCount(5);
    await sheet.getByRole("radio", { name: /Direct procurement/ }).check();
    await sheet.getByRole("button", { name: "Confirm the route" }).click();
    await expect(sheet.getByText("Direct procurement needs a written justification of at least 20 characters.")).toBeVisible();
    await expect(sheet.getByLabel("Justification")).toBeFocused();
    await sheet.getByLabel("Justification").fill(JUSTIFICATION);
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "p28a-route-sheet");
    await sheet.getByRole("button", { name: "Confirm the route" }).click();
    await expect(orgPage.getByRole("status").filter({ hasText: DONE })).toBeVisible(STEP);
    await expect(sheet).toHaveCount(0);

    // Stage 3 now, and the route for the organisation.
    await expect(orgPage.locator("[data-stepper] [data-substage='PROCUREMENT_ROUTE']")).toHaveAttribute("data-state", "completed");
    const block = orgPage.getByRole("region", { name: "Procurement route" });
    await expect(block.locator("[data-route]")).toHaveText("Direct procurement");
    await expect(block.locator("[data-justification]")).toHaveText(JUSTIFICATION);
    await checkScreen(orgPage, { strict: true });
    await shot(orgPage, info, "p28a-org-chosen");

    // History names the decision and its route.
    await orgPage.goto(`/org/engagements/${engagementId}?tab=history`);
    const event = orgPage.locator("[data-event='choose_route']");
    await expect(event).toContainText("Procurement route chosen");
    await expect(event.locator("[data-event-route]")).toHaveText("Route: Direct procurement");
    await checkScreen(orgPage, { strict: true });

    // The developer reads the same route; their tracker never carries the organisation's escalation line.
    await devPage.goto(`/dev/engagements/${engagementId}`);
    const theirs = devPage.getByRole("region", { name: "Procurement route" });
    await expect(theirs.locator("[data-route]")).toHaveText("Direct procurement", STEP);
    await expect(theirs.locator("[data-justification]")).toHaveText(JUSTIFICATION);
    await expect(devPage.locator("[data-escalated]")).toHaveCount(0);
    await expect(devPage.locator("[data-stepper] [data-substage='PROCUREMENT_ROUTE']")).toHaveCount(1);
    await checkScreen(devPage, { strict: true });
    await shot(devPage, info, "p28a-dev-chosen");
  } finally {
    await close();
  }
});

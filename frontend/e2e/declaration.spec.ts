import { readFileSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";

import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import { appToday } from "./support/clock";
import { checkScreen } from "./support/screen";
import {
  codeOf,
  proposalOf,
  send,
  signInMember,
  TELCO_A,
  TELCO_A_MEMBERS,
  viewFullProposal,
} from "./support/team-scene";
import { OWNER_DATABASE_URL, pitchFromDeveloper, post, signUpOrg, type Person } from "./support/tracker-scene";

// P27 tracks D and E (acceptance rows 4 and 5).
//
// D (REQ-PROV-06; docs/spec/06 6.4 pt 5): before Telco A's first full-proposal view a declaration is refused
// (no_tier2_access_yet) and the tracker says when the window opens; after the signatory's view, the signatory declares
// with a fixture file fingerprinted in the browser (the hash equals sha256sum's; only the hex, the title and the date
// are sent), the developer is told (N31) and reads the declaration on their tracker; a second is refused 409; a
// finance member is refused 403; History names the event and its chain verifies. On the test clock (E2E_TEST_CLOCK=1,
// run alone: it moves the shared clock 15 days forward), day 11 refuses with declaration_window_closed and the
// action is gone from the screen. The declaration sheet passes axe with no violation of any impact.
//
// E (REQ-DEV-04; docs/spec/06 6.4 pt 8 and 6.1): a developer saves a GitHub login, KECOBO and KIPI references and an
// invalid login is said on its field; the IP note shows with the send_nda step, goes for good when dismissed.
//
// Needs the demo seed (Telco A's members), E2E_DATABASE_OWNER_URL and an API with FEATURE_DEALS_ENABLED=true and
// FEATURE_TIER2_ENABLED=true. E2E_SHOTS_DIR saves the declaration sheet at 375 px (mobile project) and 1440 px.

const SERVER_STEP = { timeout: 20_000 };
const FIXTURE = join(__dirname, "fixtures/prior-knowledge-evidence.txt");
const FIXTURE_SHA256 = createHash("sha256").update(readFileSync(FIXTURE)).digest("hex");
const EVIDENCE_TITLE = "Board minutes on our 2025 cold-chain pilot";

test.beforeAll(() => {
  expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL sets the test-only verification levels").toBeTruthy();
});

async function shot(page: Page, info: TestInfo, name: string) {
  const dir = process.env.E2E_SHOTS_DIR;
  if (!dir) return;
  mkdirSync(dir, { recursive: true });
  await page.screenshot({ path: join(dir, `${name}-${info.project.name.startsWith("mobile") ? 375 : 1440}.png`) });
}

const declarationPath = (orgId: string, id: string) => `/api/orgs/${orgId}/engagements/${id}/prior-knowledge`;
const evidence = (date = "2025-06-10") => ({
  evidence_sha256_hex: FIXTURE_SHA256,
  evidence_title: EVIDENCE_TITLE,
  evidence_dated_on: date,
});

test("Telco A's signatory declares prior knowledge inside the window; the developer is told and sees it", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(240_000);
  const signatory = await signInMember(browser, info, TELCO_A_MEMBERS.signatory);
  // What the page sends to the declaration route, read in the page itself (the client posts a Request whose body
  // the browser's network events do not carry).
  await signatory.page.addInitScript(() => {
    const sent: string[] = [];
    Object.assign(window, { __declarationBodies: sent });
    const original = window.fetch.bind(window);
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
      if (input instanceof Request && input.method === "POST" && input.url.includes("/prior-knowledge")) {
        sent.push(await input.clone().text());
      }
      return original(input, init);
    };
  });
  const reviewer = await signInMember(browser, info, TELCO_A_MEMBERS.reviewer);
  const finance = await signInMember(browser, info, TELCO_A_MEMBERS.finance);
  try {
    const dev = await pitchFromDeveloper(page.request, signatory.orgId);
    const id = dev.engagementId;
    const path = declarationPath(signatory.orgId, id);

    // --- Before any full-proposal view: refused, and the line says when the window opens ---------------------------
    const early = await send(signatory.request, "post", path, evidence());
    expect(early.status()).toBe(403);
    expect(await codeOf(early)).toBe("no_tier2_access_yet");
    await signatory.page.goto(`/org/engagements/${id}`);
    const line = signatory.page.locator("[data-declaration]");
    await expect(line).toHaveAttribute("data-declaration", "notYet");
    await expect(line).toHaveText("The declaration window opens after your organisation's first full-proposal view.");
    await expect(line.getByRole("button")).toHaveCount(0);

    // --- The signatory opens the full proposal: the window opens ----------------------------------------------------
    await viewFullProposal(signatory, await proposalOf(page.request, id));
    await signatory.page.reload();
    await expect(line).toHaveAttribute("data-declaration", "open");
    await expect(line).toContainText("Your organisation can declare existing similar work until");
    // A reviewer reads the window but has no action; finance is refused by the API.
    await reviewer.page.goto(`/org/engagements/${id}`);
    await expect(reviewer.page.locator("[data-declaration='open']")).toContainText("An owner, admin or signatory");
    await expect(reviewer.page.getByRole("button", { name: "Declare prior knowledge" })).toHaveCount(0);
    const byFinance = await send(finance.request, "post", path, evidence());
    expect(byFinance.status()).toBe(403);
    expect(await codeOf(byFinance)).toBe("role_not_allowed");

    // --- The declaration sheet: the file fingerprinted in the browser, only the hex sent --------------------------------
    await line.getByRole("button", { name: "Declare prior knowledge" }).click();
    const sheet = signatory.page.getByRole("dialog", { name: "Declare prior knowledge" });
    await expect(sheet).toContainText("Only a fingerprint (SHA-256) of your file leaves this device", SERVER_STEP);
    await expect(sheet).toContainText("Declarations are not recorded on the platform after");
    await expect(sheet.getByText("A short title, no names. It is kept permanently.")).toBeVisible();
    await sheet.getByLabel("File", { exact: true }).setInputFiles(FIXTURE);
    // The browser's SHA-256 of the fixture is sha256sum's.
    await expect(sheet.locator("[data-file-hash]")).toHaveText(FIXTURE_SHA256, SERVER_STEP);
    await sheet.getByLabel("Title").fill(EVIDENCE_TITLE);
    await sheet.getByLabel("Date of the evidence").fill("2025-06-10");
    await checkScreen(signatory.page, { strict: true });
    await shot(signatory.page, info, "declaration-sheet");
    await sheet.getByRole("button", { name: "Record declaration" }).click();
    const receipt = sheet.locator("[data-declaration-receipt]");
    await expect(receipt).toContainText("A declaration was recorded on", SERVER_STEP);
    await expect(receipt.locator("[data-hash]")).toHaveText(FIXTURE_SHA256);
    await expect(receipt).toContainText(EVIDENCE_TITLE);
    await expect(receipt).toContainText("10 Jun 2025");
    await checkScreen(signatory.page, { strict: true });
    const sent = await signatory.page.evaluate(
      () => (window as unknown as { __declarationBodies: string[] }).__declarationBodies,
    );
    expect(sent).toHaveLength(1);
    expect(JSON.parse(sent[0])).toEqual(evidence());
    await receipt.getByRole("button", { name: "Done" }).click();
    await expect(sheet).toBeHidden();
    // The tracker refreshed: the line says it was declared; no action left.
    await expect(signatory.page.locator("[data-declaration]")).toHaveAttribute(
      "data-declaration",
      "declared",
      SERVER_STEP,
    );
    // Focus follows the refreshed line (the button it came from is gone).
    await expect(signatory.page.locator("#prior-knowledge")).toBeFocused(SERVER_STEP);
    await expect(signatory.page.getByRole("button", { name: "Declare prior knowledge" })).toHaveCount(0);

    // --- One per engagement ------------------------------------------------------------------------------------------
    const again = await send(signatory.request, "post", path, evidence());
    expect(again.status()).toBe(409);
    expect(await codeOf(again)).toBe("already_declared");

    // --- The developer: told (N31), and the declaration on their tracker ------------------------------------------------
    const notices = (await (await page.request.get("/api/me/notifications")).json()) as {
      items: Array<{ kind: string; title: string; body: string | null }>;
    };
    const n31 = notices.items.find((n) => n.kind === "engagement.n31");
    expect(n31, "N31 in the developer's notifications").toBeTruthy();
    expect(`${n31!.title} ${n31!.body ?? ""}`).not.toContain(EVIDENCE_TITLE);
    await page.goto(`/dev/engagements/${id}`);
    const panel = page.getByRole("region", {
      name: new RegExp(`^Prior-knowledge declaration from ${TELCO_A.replace(/[()]/g, "\\$&")} on `),
    });
    await expect(panel).toBeVisible();
    await expect(panel.locator("[data-hash]")).toHaveText(FIXTURE_SHA256);
    await expect(panel).toContainText(EVIDENCE_TITLE);
    await expect(panel).toContainText("10 Jun 2025");
    await checkScreen(page, { strict: true });
    // History names the event, and the chain verifies.
    await page.goto(`/dev/engagements/${id}?tab=history`);
    await expect(page.locator("[data-event='prior_knowledge_declared'] h3")).toHaveText("Prior knowledge declared");
    await expect(page.locator("[data-chain='verified']")).toBeVisible();
  } finally {
    await Promise.all([signatory, reviewer, finance].map((m) => m.close()));
  }
});

test.describe("on the test clock", () => {
  test.skip(!process.env.E2E_TEST_CLOCK, "moves the shared clock 15 days forward: run alone with E2E_TEST_CLOCK=1");

  test("day 11 refuses with declaration_window_closed and the action is gone", async ({ page, browser }, info) => {
    test.setTimeout(180_000);
    const signatory = await signInMember(browser, info, TELCO_A_MEMBERS.signatory);
    try {
      const dev = await pitchFromDeveloper(page.request, signatory.orgId);
      const id = dev.engagementId;
      await viewFullProposal(signatory, await proposalOf(page.request, id));
      await signatory.page.goto(`/org/engagements/${id}`);
      await expect(signatory.page.locator("[data-declaration]")).toHaveAttribute("data-declaration", "open");
      const closesOn = (
        (await (await signatory.request.get(`/api/engagements/${id}`)).json()) as {
          prior_knowledge: { window_closes_on: string };
        }
      ).prior_knowledge.window_closes_on;
      // 15 calendar days hold at least 11 business days (the window is 10).
      await post(signatory.request, "/api/test-clock/advance", { days: 15 });
      expect((await appToday(signatory.request)) > closesOn).toBe(true);
      const late = await send(signatory.request, "post", declarationPath(signatory.orgId, id), evidence());
      expect(late.status()).toBe(403);
      const body = (await late.json()) as { detail: { code: string; message: string; window_closed_on: string } };
      expect(body.detail.code).toBe("declaration_window_closed");
      expect(body.detail.message).toBe("Declarations are not recorded on the platform after this window.");
      expect(body.detail.window_closed_on).toBe(closesOn);
      await signatory.page.reload();
      await expect(signatory.page.locator("[data-declaration]")).toHaveAttribute("data-declaration", "closed");
      await expect(signatory.page.locator("[data-declaration]")).toContainText("The declaration window closed on");
      await expect(signatory.page.getByRole("button", { name: "Declare prior knowledge" })).toHaveCount(0);
      await checkScreen(signatory.page, { strict: true });
    } finally {
      await signatory.close();
    }
  });
});

/** Runs one tracker command through the API, on the engagement's current lock_version (a step-up once if asked). */
async function command(
  request: APIRequestContext,
  who: { person: Person },
  id: string,
  segment: string,
  body: Record<string, unknown> = {},
) {
  const read = await request.get(`/api/engagements/${id}`);
  const { lock_version } = (await read.json()) as { lock_version: number };
  const csrf = ((await (await request.get("/api/auth/csrf")).json()) as { csrf_token: string }).csrf_token;
  const path = `/api/engagements/${id}/${segment}`;
  let response = await request.post(path, { headers: { "X-CSRF-Token": csrf }, data: { lock_version, ...body } });
  if (response.status() === 403 && (await codeOf(response)) === "step_up_required") {
    await post(request, "/api/auth/step-up", { code: await who.person.code() });
    response = await request.post(path, { headers: { "X-CSRF-Token": csrf }, data: { lock_version, ...body } });
  }
  expect(response.status(), `${segment}: ${await response.text()}`).toBe(200);
}

test("a developer states their references and reads the IP note once, with the send_nda step", async ({
  page,
  browser,
}, info) => {
  test.setTimeout(240_000);
  const orgContext = await browser.newContext({ ...info.project.use });
  const orgPage = await orgContext.newPage();
  try {
    const org = await signUpOrg(orgPage.request);
    const dev = await pitchFromDeveloper(page.request, org.orgId);
    const id = dev.engagementId;

    // --- D3 on Settings › Profile ------------------------------------------------------------------------------------
    await page.goto("/settings/profile");
    const references = page.getByRole("group", { name: "Self-reported references" });
    await expect(references).toContainText("Shown on your certificates as self-reported.");
    await references.getByLabel("GitHub login").fill("bad_login!");
    await page.getByRole("button", { name: "Save" }).click();
    const login = references.getByLabel("GitHub login");
    await expect(login).toHaveAttribute("aria-invalid", "true", SERVER_STEP);
    await expect(references).toContainText("A GitHub login has letters, digits and single hyphens");
    await expect(login).toBeFocused();
    await login.fill("@achieng-dev");
    await references.getByLabel("KECOBO reference").fill("KE-CR-2026-0042");
    await references.getByLabel("KIPI reference").fill("KE/UM/2026/0077");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("status")).toHaveText("Profile saved.", SERVER_STEP);
    await expect(login).toHaveValue("achieng-dev");
    const profile = (await (await page.request.get("/api/me/profile")).json()) as Record<string, string | null>;
    expect([profile.github_login, profile.kecobo_number, profile.kipi_number]).toEqual([
      "achieng-dev",
      "KE-CR-2026-0042",
      "KE/UM/2026/0077",
    ]);
    await checkScreen(page, { strict: true });

    // --- The organisation reaches first contact: the developer's next step is send_nda --------------------------------
    const me = (await (await orgPage.request.get("/api/auth/me")).json()) as { user: { id: string } };
    await command(orgPage.request, org, id, "start-review");
    await command(orgPage.request, org, id, "approve", {
      contact_user_id: me.user.id,
      contact_channel: "email",
      contact_by: await appToday(orgPage.request),
    });
    await command(orgPage.request, org, id, "mark-contacted");
    // The developer confirms first contact (their endorsement); then the mutual NDA is theirs to send.
    await command(page.request, dev, id, "confirm-contact");

    await page.goto(`/dev/engagements/${id}`);
    const note = page.locator("[data-ip-nudge]");
    await expect(note).toContainText("Before you share a full proposal for the first time");
    await expect(note).toContainText("Neither is required here.");
    for (const name of [/KIPI \(kipi\.go\.ke\)/, /KECOBO \(copyright\.go\.ke\)/]) {
      await expect(note.getByRole("link", { name })).toHaveAttribute("rel", "noopener noreferrer");
    }
    await expect(note.getByRole("link", { name: /KECOBO \(copyright\.go\.ke\)/ })).toHaveAttribute(
      "href",
      "https://copyright.go.ke",
    );
    await expect(page.locator("[data-turn-card] [data-command='send_nda']")).toBeVisible();
    await checkScreen(page, { strict: true });
    await expect(page.locator("[data-actions][data-hydrated='true']")).toBeVisible(SERVER_STEP);
    await note.getByRole("button", { name: "Dismiss" }).click();
    await expect(note).toBeHidden(SERVER_STEP);
    await page.reload();
    await expect(page.locator("[data-ip-nudge]")).toHaveCount(0);
    const detail = (await (await page.request.get(`/api/engagements/${id}`)).json()) as { ip_nudge: boolean };
    expect(detail.ip_nudge).toBe(false);
  } finally {
    await orgContext.close();
  }
});

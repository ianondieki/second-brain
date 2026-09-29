import { expect, test, type Page } from "@playwright/test";

import { signUpDeveloper } from "./support/accounts";
import { checkScreen, expectEmptyState } from "./support/screen";
import { makeD1, OWNER_DATABASE_URL } from "./support/verification";

// REQ-PROP-01 (F2) and REQ-PROV-02: Developer › My ideas against the compose stack, in both projects (360 px and
// desktop): the list, the three-step editor with autosave, the Tier-1 sanitiser shown inline, attachments (the fake
// scanner refuses EICAR), the three attestations, publishing (403 d1_required below D1; AC-IP-5), the idea page with
// its certificate and /verify link, and deleting (a published idea is hidden, its evidence kept; AC-IP-6).

const SERVER_STEP = { timeout: 20_000 };
const EDIT_URL = /\/dev\/ideas\/[0-9a-f-]{36}\/edit/;
// The EICAR antivirus test string (harmless by design); the stack's fake scanner reports it as infected (D-36).
const EICAR = String.raw`X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*`;

async function waitForSave(page: Page) {
  await expect(page.getByRole("status").filter({ hasText: /^Saved$/ })).toBeVisible(SERVER_STEP);
}

/** Picks the first niche that has a parent (an <optgroup> child), so the test does not depend on seed names. */
async function chooseNiche(page: Page) {
  const value = await page.locator("#idea-niche optgroup option").first().getAttribute("value");
  await page.locator("#idea-niche").selectOption(value!);
}

/** Step 1 with a new developer-reported problem; returns the idea's title. */
async function fillStepOne(page: Page, title: string) {
  await page.getByLabel("Title", { exact: true }).fill(title);
  await expect(page).toHaveURL(EDIT_URL, SERVER_STEP); // the first autosave created the draft
  await chooseNiche(page);
  await page.getByText("Describe a new problem", { exact: true }).first().click();
  await page.getByLabel("Problem title").fill(`${title}: milk spoils before collection`);
  await page.getByLabel("What is the problem?").fill("Small dairy co-ops lose a fifth of the evening milk.");
  await page.getByLabel("The problem it solves").fill("Milk spoils between milking and the morning collection.");
  await page.getByLabel("Summary").fill("Shared solar chillers booked by SMS, paid per litre.");
  await page.getByLabel("How far along is it?").selectOption("prototype");
  await page.getByLabel("What are you looking for?").selectOption("pilot");
  await waitForSave(page);
}

test("signed-out visits to My ideas go to the login page", async ({ page }) => {
  for (const path of ["/dev/ideas", "/dev/ideas/new", "/dev/ideas/01a0ecd8-2e13-71dd-809a-2e817be8fcf3"]) {
    await page.goto(path);
    await expect(page, path).toHaveURL(/\/login$/);
  }
});

test.describe("a signed-in developer", () => {
  let email = "";
  test.beforeEach(async ({ page }) => {
    email = await signUpDeveloper(page);
  });

  test("starts from an empty My ideas and writes a draft that saves itself", async ({ page }) => {
    const nav = page.getByRole("navigation", { name: "Developer" });
    expect(await nav.getByRole("link").count()).toBeLessThanOrEqual(5); // AC-UX-1
    await nav.getByRole("link", { name: "My ideas" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas$/, SERVER_STEP);
    await expect(nav.getByRole("link", { name: "My ideas" })).toHaveAttribute("aria-current", "page");
    await expectEmptyState(
      page,
      "Write up your first idea: a short public teaser, then the confidential details.",
      "New idea",
    );
    await checkScreen(page);

    await page.getByRole("link", { name: "New idea" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas\/new$/, SERVER_STEP);
    await expect(page.locator("ol [aria-current='step']")).toContainText("Problem and teaser");
    await expect(page.locator("[data-primary]")).toHaveText("Continue");
    await checkScreen(page);

    // The sanitiser's findings sit next to their field; nothing is saved until the teaser is clean.
    await page.getByLabel("Title", { exact: true }).fill("Dairy cold chain");
    await expect(page).toHaveURL(EDIT_URL, SERVER_STEP);
    await waitForSave(page);
    await page.getByLabel("Summary").fill("Chillers for co-ops. Write to jane@example.com for a demo.");
    await expect(page.getByText(/Remove the email address/)).toBeVisible(SERVER_STEP);
    await expect(page.getByRole("status").filter({ hasText: "Not saved yet" })).toBeVisible();
    await page.getByLabel("Summary").fill("Chillers for co-ops, booked by SMS.");
    await waitForSave(page);
    await expect(page.getByText(/Remove the email address/)).toHaveCount(0);

    // A reload keeps what was saved.
    await page.reload();
    await expect(page.getByLabel("Summary")).toHaveValue("Chillers for co-ops, booked by SMS.");

    await page.goto("/dev/ideas");
    const row = page.locator("main article").filter({ hasText: "Dairy cold chain" });
    await expect(row).toBeVisible();
    await expect(row.locator("[data-status]")).toHaveText("Draft");
    expect(await row.locator("[data-status], [data-chip]").count()).toBeLessThanOrEqual(2); // AC-UX-1
    await checkScreen(page);
  });

  test("goes through the three steps, attaches files and cannot publish below D1", async ({ page }) => {
    await page.goto("/dev/ideas/new");
    await fillStepOne(page, "Dairy cold chain");

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.locator("ol [aria-current='step']")).toContainText("Full details");
    await expect(page.getByText("Confidential", { exact: true })).toBeVisible();
    await expect(page.getByText(/shown to verified people at organisations that accepted our NDA/)).toBeVisible();
    await page.getByLabel("Approach").fill("Solar chillers with a shared booking queue.");
    await page.getByLabel("Links").fill("not a link");
    await expect(page.getByText(/Each link must be a web address/)).toBeVisible();
    await page.getByLabel("Links").fill("https://example.com/demo");

    const upload = page.getByLabel("Add a file");
    await upload.setInputFiles({ name: "Mpango wa kazi.md", mimeType: "text/markdown", buffer: Buffer.from("# Plan\n") });
    const files = page.getByRole("list", { name: "Attached files" });
    await expect(files.getByText("Mpango wa kazi.md")).toBeVisible(SERVER_STEP);
    await upload.setInputFiles({ name: "eicar.txt", mimeType: "text/plain", buffer: Buffer.from(EICAR) });
    await expect(page.getByText("This file did not pass the malware check, so it was not kept.")).toBeVisible(
      SERVER_STEP,
    );
    await expect(files.getByRole("listitem")).toHaveCount(1);
    await upload.setInputFiles({ name: "setup.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") });
    await expect(page.getByText("Attach a PDF, PNG, JPG, Markdown or plain-text file.")).toBeVisible();
    await waitForSave(page);
    await checkScreen(page);

    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.locator("ol [aria-current='step']")).toContainText("Review and publish");
    await expect(page.locator("[data-primary]")).toHaveText("Publish");
    await expect(page.getByText("Files: 1")).toBeVisible();
    await checkScreen(page);

    // The three statements come from the API and must all be confirmed.
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByText("Confirm this statement.")).toHaveCount(3);
    await expect(page.getByRole("checkbox")).toHaveCount(3); // the step loads when opened
    for (const box of await page.getByRole("checkbox").all()) await box.check();
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: "needs a verified mobile number" })).toBeVisible(
      SERVER_STEP,
    );
    await expect(page).toHaveURL(EDIT_URL);
  });

  test("publishes at D1, gets a certificate and hides the idea", async ({ page }) => {
    expect(OWNER_DATABASE_URL, "E2E_DATABASE_OWNER_URL raises the test developer to D1").toBeTruthy();
    makeD1(email);
    // Unique per run: published problems stay listed on the stack, and the picker search must find this one only.
    const title = `Maziwa baridi ${Date.now().toString(36)}`;
    await page.goto("/dev/ideas/new");
    await fillStepOne(page, title);
    await page.getByRole("button", { name: "Continue" }).click();
    await page.getByLabel("Approach").fill("Solar chillers with a shared booking queue.");
    await waitForSave(page);
    await page.getByRole("button", { name: "Continue" }).click();
    await expect(page.getByRole("checkbox")).toHaveCount(3); // the step loads when opened
    for (const box of await page.getByRole("checkbox").all()) await box.check();
    await page.getByRole("button", { name: "Publish", exact: true }).click();

    await expect(page).toHaveURL(/\/dev\/ideas\/[0-9a-f-]{36}\?published=1$/, SERVER_STEP);
    const published = page.getByRole("status").filter({ hasText: "Published. Your certificate id is" });
    await expect(published).toBeVisible();
    const certId = /certificate id is ([0-9A-Za-z]+)\./.exec((await published.textContent()) ?? "")?.[1];
    expect(certId).toBeTruthy();
    await expect(page.getByRole("link", { name: "Check it on the verify page" })).toHaveAttribute(
      "href",
      `/verify/${certId}`,
    );
    await expect(page.getByRole("heading", { name: "Public teaser" })).toBeVisible();
    await expect(page.getByText(`${title}: milk spoils before collection`)).toBeVisible();
    await expect(page.getByText("Solar chillers with a shared booking queue.")).toBeVisible(); // your own Tier 2
    // A published idea's next step is pitching it (REQ-PROP-03); editing stays one button away.
    await expect(page.locator("[data-primary]")).toHaveText("Pitch to companies");
    await expect(page.getByRole("link", { name: "Edit idea" })).toBeVisible();
    await checkScreen(page);

    // The new problem is now listed: a second idea can link it from the picker.
    await page.goto("/dev/ideas/new");
    await page.getByText("Link a listed problem", { exact: true }).click(); // a new idea asks first
    await page.getByRole("searchbox", { name: "Search problems" }).fill(title);
    await page.getByRole("button", { name: "Search", exact: true }).click();
    await page.getByRole("button", { name: `Link ${title}: milk spoils before collection` }).click();
    await expect(page.getByRole("heading", { name: /Linked problems/ })).toBeVisible();
    await expect(page.getByText("Developer-reported").first()).toBeVisible();

    // Deleting a published idea hides it and says what is kept.
    await page.goto("/dev/ideas");
    await page.getByRole("link", { name: title }).click();
    await page.getByRole("button", { name: "Delete idea" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this idea?" });
    await expect(dialog).toContainText("certificates and /verify records are kept");
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas\?removed=hidden$/, SERVER_STEP);
    await expect(page.locator("main article").filter({ hasText: title }).locator("[data-status]")).toHaveText("Hidden");
  });

  test("deletes a draft that was never published", async ({ page }) => {
    await page.goto("/dev/ideas/new");
    await page.getByLabel("Title", { exact: true }).fill("Throwaway draft");
    await expect(page).toHaveURL(EDIT_URL, SERVER_STEP);
    await waitForSave(page);
    await page.getByRole("link", { name: "All my ideas" }).click();
    await page.getByRole("link", { name: "Throwaway draft" }).click();
    await expect(page.getByText("This idea is a draft: only you can see it until you publish.")).toBeVisible();
    await expect(page.getByText("A certificate is issued when you publish.")).toBeVisible();
    await checkScreen(page);
    await page.getByRole("button", { name: "Delete idea" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete this idea?" });
    await expect(dialog).toContainText("never published");
    await dialog.getByRole("button", { name: "Keep it" }).click();
    await expect(dialog).toBeHidden();
    await page.getByRole("button", { name: "Delete idea" }).click();
    await dialog.getByRole("button", { name: "Delete" }).click();
    await expect(page).toHaveURL(/\/dev\/ideas\?removed=deleted$/, SERVER_STEP);
    await expect(page.getByText("Deleted. It was never published, so nothing was kept.")).toBeVisible();
    await expect(page.locator("[data-empty-state]")).toHaveCount(1);
  });
});

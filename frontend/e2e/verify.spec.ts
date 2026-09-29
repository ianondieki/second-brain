import { createHash, randomBytes } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { checkScreen, expectSeparateTargets } from "./support/screen";

// REQ-PROV-02 (F3): the public /verify pages against the compose stack, in both projects (360 px and desktop).
// A certificate exists only once a proposal is published (T2.3); E2E_VERIFY_CERT_ID names one: CI's e2e job and
// `python infra/demo/demo.py e2e-env` take it from the demo seed (P9, REQ-FND-02). The record test fails without it.

const SERVER_STEP = { timeout: 20_000 };
const UNKNOWN_ID = "ZZZZZZZZZZZZZZZZ";
const CERT_ID = process.env.E2E_VERIFY_CERT_ID;

/** Forms stay inert until React hydrates (components/ui/Form.tsx). */
async function hydrated(page: Page) {
  await page.locator('form[data-hydrated="true"]').first().waitFor(SERVER_STEP);
}

async function chooseFile(page: Page, bytes: Buffer) {
  await page
    .getByLabel("Manifest file")
    .setInputFiles({ name: "manifest.json", mimeType: "application/json", buffer: bytes });
}

test("the lookup page meets the page rules and names nobody", async ({ page }) => {
  await page.goto("/verify");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Check an authorship certificate");
  await expect(page.locator("[data-primary]")).toHaveText("Check certificate");
  await expect(page.getByRole("complementary")).toContainText("Not the owner’s name, the title or the content.");
  await checkScreen(page);
});

test("a malformed id stays on the page with the reason; a typed id is tidied and looked up", async ({ page }) => {
  await page.goto("/verify");
  await page.getByLabel("Certificate ID").fill("not an id!");
  await page.getByRole("button", { name: "Check certificate" }).click();
  await expect(page.getByText("Enter the certificate ID as printed: 8 to 24 letters and numbers.")).toBeVisible();
  await expect(page.getByLabel("Certificate ID")).toHaveAttribute("aria-invalid", "true");
  await checkScreen(page);

  // Lower case, spaces and hyphens are what people type from a printed certificate.
  await page.getByLabel("Certificate ID").fill("zzzz-zzzz zzzz zzzz");
  await page.getByRole("button", { name: "Check certificate" }).click();
  await expect(page).toHaveURL(new RegExp(`/verify/${UNKNOWN_ID}$`), SERVER_STEP);
});

test("an unknown certificate is one sentence and one action", async ({ page }) => {
  await page.goto(`/verify/${UNKNOWN_ID}`);
  await expect(page.getByTestId("verify-message")).toHaveText("No certificate has this ID.");
  await expect(page.getByRole("main").getByRole("link")).toHaveText(["Check another certificate"]);
  await checkScreen(page);
  await page.getByRole("link", { name: "Check another certificate" }).click();
  await expect(page).toHaveURL(/\/verify$/);
});

test("a file that matches nothing says so and shows its fingerprint", async ({ page }) => {
  const bytes = randomBytes(64);
  await page.goto("/verify");
  await hydrated(page);
  await chooseFile(page, bytes);
  await page.getByRole("button", { name: "Check file" }).click();
  await expect(page.getByTestId("file-result")).toHaveText(
    "This file does not match any registered certificate.",
    SERVER_STEP,
  );
  const sha256 = createHash("sha256").update(bytes).digest("hex");
  await expect(page.locator(`[data-fingerprint="${sha256}"]`)).toBeVisible();
  await checkScreen(page);
});

test("checking with no file chosen points at the field", async ({ page }) => {
  await page.goto("/verify");
  await hydrated(page);
  await page.getByRole("button", { name: "Check file" }).click();
  await expect(page.getByText("Choose a file first.")).toBeVisible();
  await expect(page.getByLabel("Manifest file")).toBeFocused();
});

test("a matching file links to its certificate", async ({ page }) => {
  // The API's answer is stubbed here (the match itself is the API's integration test); the screen is under test.
  const hash = "03ed86af3435a56375e52570f69d97cbee68cadf4c63d75ab69112204108c789";
  await page.route("**/api/verify", (route) =>
    route.fulfill({
      json: {
        match: true,
        content_hash: hash,
        certificate: {
          cert_id: "TXEMFBJ89RRTQS87",
          status: "timestamped",
          status_label: "Timestamped",
          content_hash: hash,
          timestamp: "2026-09-29T11:06:25Z",
          tsa_serial: "0x01",
          key_id: "ed25519:e60ca1fa824c4587",
          signature: "c2lnbmF0dXJl",
        },
      },
    }),
  );
  await page.goto("/verify");
  await hydrated(page);
  await chooseFile(page, Buffer.from("{}"));
  await page.getByRole("button", { name: "Check file" }).click();
  await expect(page.getByTestId("file-result")).toHaveText("This file matches certificate TXEMFBJ89RRTQS87.");
  await expect(page.getByRole("link", { name: "View certificate TXEMFBJ89RRTQS87" })).toHaveAttribute(
    "href",
    "/verify/TXEMFBJ89RRTQS87",
  );
  await checkScreen(page);
});

test("a registered certificate shows its evidence, and no name or title", async ({ page }) => {
  expect(CERT_ID, "E2E_VERIFY_CERT_ID: a certificate registered on the stack (the demo seed)").toBeTruthy();
  await page.goto(`/verify/${CERT_ID}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(`Certificate ${CERT_ID}`);
  await expect(page.getByTestId("verify-status")).toHaveText(/^(Timestamped|Timestamp pending)$/);
  await expect(page.locator("[data-fingerprint]")).toHaveAttribute("data-fingerprint", /^[0-9a-f]{64}$/);
  for (const label of ["Timestamp", "Timestamp serial number", "Signing key ID", "Signature (Ed25519)"]) {
    await expect(
      page.getByRole("term").filter({ hasText: new RegExp(`^${label.replace(/[()]/g, "\\$&")}$`) }),
    ).toHaveCount(1);
  }
  await expect(page.getByText("It is not a patent, copyright registration", { exact: false })).toBeVisible();
  await expect(page.locator("[data-primary]")).toHaveText("Check file");
  // The token and keys links are stacked: each has its own 44 px band (ux-review MAJOR, P8 part 1).
  await expectSeparateTargets(page.getByTestId("record-links").getByRole("link"));
  await checkScreen(page);

  // The published keys and the timestamp token come from the API through the web origin.
  const keys = await page.request.get("/.well-known/provenance-keys.json");
  expect(keys.ok()).toBeTruthy();
  expect(((await keys.json()) as { keys: unknown[] }).keys.length).toBeGreaterThan(0);
  if ((await page.getByTestId("verify-status").textContent()) === "Timestamped") {
    const token = await page.request.get(`/api/verify/${CERT_ID}/timestamp.tsr`);
    expect(token.headers()["content-type"]).toBe("application/timestamp-reply");
  }
});

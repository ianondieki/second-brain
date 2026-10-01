import { expect, type Page } from "@playwright/test";

import { pathOf, waitForSignInLink } from "./mailpit";

// example.com is reserved for documentation (RFC 2606) and the stack sends to Mailpit only.
export function uniqueEmail(label: string) {
  return `${label}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}@example.com`;
}

/**
 * A new, signed-in developer: signup through the API (the signup screen has its own tests in auth.spec.ts), then
 * the emailed link from Mailpit, which signs the browser in and lands on /dev.
 */
export async function signUpDeveloper(page: Page, name = "Achieng Otieno"): Promise<string> {
  const email = uniqueEmail("dir");
  const csrf = await page.request.get("/api/auth/csrf");
  expect(csrf.ok()).toBeTruthy();
  const { csrf_token: token } = (await csrf.json()) as { csrf_token: string };
  const signup = await page.request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": token },
    data: {
      email,
      password: "accent season in nairobi",
      display_name: name,
      side: "developer",
      accept_terms: true,
    },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  await page.goto(pathOf(await waitForSignInLink(page.request, email)));
  await expect(page).toHaveURL(/\/dev$/, { timeout: 20_000 });
  return email;
}

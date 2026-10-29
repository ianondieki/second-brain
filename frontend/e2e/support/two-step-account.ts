import type { Page } from "@playwright/test";

import { signUpDeveloper } from "./accounts";
import { type Person, turnOnTotp } from "./tracker-scene";

export { PASSWORD } from "./tracker-scene";

/**
 * A new developer with two-step sign-in on, signed out again: each test signs in with its own account, so no test
 * shares the demo accounts' per-address login throttle (P16-B review MINOR 1).
 */
export async function twoStepDeveloper(page: Page, name = "Njeri Kariuki"): Promise<Person> {
  const email = await signUpDeveloper(page, name);
  const person = await turnOnTotp(page.request, email, name);
  await page.context().clearCookies();
  return person;
}

/** Signs in on /login (already open) with the password, which leaves the second factor owed. */
export async function logInWithPassword(page: Page, person: Person, password: string) {
  await page.locator('form[data-hydrated="true"]').first().waitFor({ timeout: 20_000 });
  await page.getByLabel("Email address").fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Log in", exact: true }).click();
}

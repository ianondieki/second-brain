import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ClientStrings, type StringTree } from "@/components/ClientStrings";
import en from "@/locales/en.json";

import { PasswordSettings } from "./PasswordSettings";
import { PasswordStateProvider } from "./PasswordState";
import { SecuritySettings } from "./SecuritySettings";

// /settings/security reads server-formatted strings (components/ClientStrings) instead of next-intl's client runtime,
// which kept the page within 15 bytes of the 150 KB JS budget (P16-D, REQ-UX-03). The forms render with the strings
// the page sends and no next-intl provider, and no module of the page (nor the password field) imports next-intl.

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

afterEach(cleanup);

/** What the page sends (app/(app)/settings/security/page.tsx): these namespaces whole, and signup's password hint. */
const SENT: Record<string, StringTree> = {
  security: en.security,
  password: en.password,
  fields: en.fields,
  validation: en.validation,
  errors: en.errors,
  signup: { passwordHint: en.signup.passwordHint },
};

describe("the sign-in security page's strings", () => {
  it("render the forms from the strings the page sends, without next-intl", () => {
    render(
      <ClientStrings strings={SENT}>
        <PasswordStateProvider initial>
          <SecuritySettings enrolled={false} required={false} homeHref="/dev" email="a@example.com" productName="Bridge" />
          <PasswordSettings email="a@example.com" />
        </PasswordStateProvider>
      </ClientStrings>,
    );
    expect(screen.getByRole("button", { name: en.security.start })).toBeTruthy();
    expect(screen.getByRole("button", { name: en.password.save })).toBeTruthy();
    expect(screen.getByText(en.signup.passwordHint)).toBeTruthy();
    const [show] = screen.getAllByRole("button", { name: en.fields.showPasswordName });
    fireEvent.click(show);
    expect(screen.getAllByRole("button", { name: en.fields.hidePasswordName })).toHaveLength(1);
    // A missing string would show its key ("security.start"): none does.
    expect(document.body.textContent).not.toMatch(/\b(security|password|fields|validation|errors|signup)\.[a-z]/i);
  });

  it("import no next-intl client code", () => {
    const here = __dirname;
    const files = readdirSync(here)
      .filter((name) => /\.tsx?$/.test(name) && !name.includes(".test."))
      .map((name) => join(here, name))
      .concat(join(here, "../../../../components/ui/PasswordField.tsx"));
    // The page itself formats the strings with next-intl/server, which never reaches the browser.
    for (const file of files) expect(readFileSync(file, "utf8"), file).not.toMatch(/from "next-intl"|IntlScope/);
  });
});

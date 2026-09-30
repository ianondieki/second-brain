import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AccountUsername } from "./AccountUsername";

afterEach(cleanup);

// Password managers save or fill the signed-in account on password-only forms through a hidden username field.
describe("AccountUsername", () => {
  it("is a hidden email field with the account's address for autocomplete=username", () => {
    const { container } = render(
      <form>
        <AccountUsername email="wanjiru@example.test" />
        <input type="password" autoComplete="new-password" aria-label="New password" />
      </form>,
    );
    const field = container.querySelector("input[name='username']") as HTMLInputElement;
    expect([field.type, field.autocomplete, field.defaultValue]).toEqual(["email", "username", "wanjiru@example.test"]);
    expect(field.hidden).toBe(true); // never shown, focused or announced
    expect(field.id).toBe("");
    expect(container.querySelectorAll("input:not([hidden])")).toHaveLength(1);
  });
});

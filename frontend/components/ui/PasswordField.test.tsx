import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PasswordField } from "./PasswordField";

function renderField(extra: { hint?: string; error?: string } = {}) {
  return render(
    <PasswordField
      id="password"
      label="Password"
      showLabel="Show"
      hideLabel="Hide"
      showName="Show password"
      hideName="Hide password"
      defaultValue="a long passphrase"
      {...extra}
    />,
  );
}

afterEach(cleanup);

describe("PasswordField", () => {
  it("starts hidden and toggles between hidden and shown", () => {
    renderField();
    const input = screen.getByLabelText<HTMLInputElement>("Password", { selector: "input" });
    expect(input.type).toBe("password");

    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(input.type).toBe("text");
    expect(input.value).toBe("a long passphrase");

    fireEvent.click(screen.getByRole("button", { name: "Hide password" }));
    expect(input.type).toBe("password");
  });

  it("keeps the toggle's visible text inside its accessible name", () => {
    renderField();
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle.textContent).toBe("Show");
    expect(toggle.getAttribute("type")).toBe("button");
    expect(toggle.getAttribute("aria-controls")).toBe("password");
  });

  it("describes the input with its hint and error", () => {
    renderField({ hint: "At least 12 characters.", error: "Use a longer password." });
    const input = screen.getByLabelText("Password", { selector: "input" });
    expect(input.getAttribute("aria-describedby")).toBe("password-hint password-error");
    expect(input.getAttribute("aria-invalid")).toBe("true");
  });
});

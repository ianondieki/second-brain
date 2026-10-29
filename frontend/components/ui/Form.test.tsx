import { cleanup, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { Form, SubmitButton } from "./Form";

function Login() {
  return (
    <Form aria-label="Log in">
      <input name="email" defaultValue="someone@example.com" />
      <input name="password" type="password" defaultValue="secret" />
      <SubmitButton variant="primary">Log in</SubmitButton>
    </Form>
  );
}

afterEach(cleanup);

describe("Form before hydration (server HTML)", () => {
  const html = renderToString(<Login />);

  it("posts, so a native submit never puts fields in the URL", () => {
    expect(html).toMatch(/<form[^>]*method="post"/);
    expect(html).not.toMatch(/method="get"/i);
  });

  it("renders the submit button disabled, so neither a click nor Enter submits natively", () => {
    expect(html).toMatch(/<button[^>]*type="submit"[^>]*disabled=""/);
    expect(html).toContain('data-hydrated="false"');
  });
});

describe("Form after hydration", () => {
  it("enables the submit button and marks the form as live", () => {
    render(<Login />);
    const button = screen.getByRole("button", { name: "Log in" }) as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    expect(screen.getByRole("form", { name: "Log in" }).getAttribute("data-hydrated")).toBe("true");
    expect(screen.getByRole("form", { name: "Log in" }).getAttribute("method")).toBe("post");
  });
});

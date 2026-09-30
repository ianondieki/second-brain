import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { AccountMenu } from "./AccountMenu";

// REQ-BIL-08: the top bar's avatar menu (docs/spec/07 item 1) holds Plan & billing and Sign out, as a disclosure.

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }) }));

afterEach(cleanup);

function renderMenu() {
  renderWithIntl(
    <>
      <AccountMenu />
      <button type="button">Elsewhere</button>
    </>,
  );
  return screen.getByRole("button", { name: "Account" });
}

describe("AccountMenu", () => {
  it("opens to Plan & billing and Sign out", () => {
    const toggle = renderMenu();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link", { name: "Plan & billing" })).toBeNull(); // hidden while closed
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(panel?.hidden).toBe(false);
    expect(screen.getByRole("link", { name: "Plan & billing" }).getAttribute("href")).toBe("/billing");
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on Escape and gives focus back to its button", () => {
    const toggle = renderMenu();
    fireEvent.click(toggle);
    screen.getByRole("link", { name: "Plan & billing" }).focus();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(toggle);
  });

  it("closes when a press or the focus lands outside it", () => {
    const toggle = renderMenu();
    fireEvent.click(toggle);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Elsewhere" }));
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    act(() => screen.getByRole("button", { name: "Elsewhere" }).focus());
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });
});

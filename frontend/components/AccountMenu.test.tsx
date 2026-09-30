import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { AccountMenu } from "./AccountMenu";

// REQ-BIL-08, REQ-UX-01: the top bar's avatar menu (docs/spec/07 item 1) holds Plan & billing, Notifications, Help and
// Sign out, as a disclosure.

const search = vi.hoisted(() => ({ value: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(search.value),
}));

afterEach(() => {
  cleanup();
  search.value = "";
});

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
  it("opens to Plan & billing, Notifications, Help and Sign out", () => {
    const toggle = renderMenu();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link", { name: "Plan & billing" })).toBeNull(); // hidden while closed
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const panel = document.getElementById(toggle.getAttribute("aria-controls")!);
    expect(panel?.hidden).toBe(false);
    expect(screen.getByRole("link", { name: "Plan & billing" }).getAttribute("href")).toBe("/billing");
    expect(screen.getByRole("link", { name: "Notifications" }).getAttribute("href")).toBe("/settings/notifications");
    expect(screen.getByRole("link", { name: "Help" }).getAttribute("href")).toBe("/help");
    expect(panel?.querySelectorAll("a, button").length).toBe(4);
    expect([...panel!.querySelectorAll("a, button")].map((item) => item.textContent)).toEqual([
      "Plan & billing",
      "Notifications",
      "Help",
      "Sign out",
    ]);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("keeps the organisation a screen acts for, and only a real organisation id", () => {
    search.value = "org=0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f&cursor=x";
    fireEvent.click(renderMenu());
    expect(screen.getByRole("link", { name: "Plan & billing" }).getAttribute("href")).toBe(
      "/billing?org=0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f",
    );
    cleanup();
    search.value = "org=%2F%2Fevil.example";
    fireEvent.click(renderMenu());
    expect(screen.getByRole("link", { name: "Plan & billing" }).getAttribute("href")).toBe("/billing");
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

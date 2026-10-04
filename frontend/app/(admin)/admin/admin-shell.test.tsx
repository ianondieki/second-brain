import { cleanup, fireEvent, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/AccountMenu";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { AdminShell } from "./AdminShell";

// P15-F MINOR 7 (fix round 1 of P16-C2): the console's shell shows Plan & billing in the account menu only to a staff
// account with an organisation of its own; a staff-only account has no plan.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));
// The shell's frame and nav are not under test: the menu inside the shell's scope is.
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => (
    <>
      <AccountMenu />
      <main>{children}</main>
    </>
  ),
}));
vi.mock("@/components/AdminNav", () => ({ AdminNav: () => null }));

const staff = vi.hoisted(() => ({ memberships: [] as Array<{ org_id: string; org_name: string; roles: string[] }> }));
vi.mock("./staff", () => ({
  staffContext: async () => ({ me: { memberships: staff.memberships }, role: "moderator" }),
}));

afterEach(() => {
  cleanup();
  staff.memberships = [];
});

async function menuItems() {
  renderWithIntl(<>{await resolveServerTree(await AdminShell({ role: "moderator", children: <p>Queue</p> }))}</>);
  fireEvent.click(screen.getByRole("button", { name: "Account" }));
  return screen.getAllByRole("link").map((link) => link.textContent);
}

describe("AdminShell's account menu", () => {
  it("leaves out Plan & billing for a staff account with no organisation", async () => {
    expect(await menuItems()).toEqual(["Sign-in security", "Notification settings", "Help"]);
  });

  it("keeps Plan & billing for a staff account that belongs to an organisation", async () => {
    staff.memberships = [{ org_id: "01a0f149-d75d-7317-979d-2d98f1c8a802", org_name: "Telco A", roles: ["owner"] }];
    expect(await menuItems()).toEqual(["Plan & billing", "Sign-in security", "Notification settings", "Help"]);
  });
});

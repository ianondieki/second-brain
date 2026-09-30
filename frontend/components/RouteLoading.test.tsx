import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { AccountLoading, AdminLoading, DevLoading, OrgLoading } from "./RouteLoading";

// P16 (REQ-UX-02, REQ-UX-03): every signed-in section has a loading state: the section's frame and navigation around
// a still skeleton, prefetched by Next.js so a tap shows the next screen at once. No client code of its own.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(), useRouter: () => ({}) }));
// The top bar is an async server component, which React's client renderer cannot run: a stand-in keeps its slot.
vi.mock("./TopBar", () => ({ TopBar: ({ children }: { children?: React.ReactNode }) => <header>{children}</header> }));

afterEach(cleanup);

async function renderTree(node: React.ReactElement) {
  renderWithIntl(<>{await resolveServerTree(node)}</>);
}

describe("route loading states", () => {
  it("keep the developer section current in the navigation, around the skeleton", async () => {
    await renderTree(<DevLoading current="ideas" />);
    const nav = screen.getByRole("navigation", { name: "Developer" });
    expect(within(nav).getByRole("link", { name: "My ideas" }).getAttribute("aria-current")).toBe("page");
    expect(within(screen.getByRole("main")).getByRole("status").textContent).toBe("Loading this page…");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    // No client component: the account menu waits for the page (a prefetched loading state would pull its chunk).
    expect(document.querySelector("[data-account-menu]")).toBeNull();
  });

  it("keep the organisation section current", async () => {
    await renderTree(<OrgLoading current="inbox" />);
    const nav = screen.getByRole("navigation", { name: "Organisation" });
    expect(within(nav).getByRole("link", { name: "Inbox" }).getAttribute("aria-current")).toBe("page");
  });

  it("show no navigation for screens either side opens, and keep the console rail's room", async () => {
    await renderTree(<AccountLoading />);
    expect(screen.queryByRole("navigation")).toBeNull();
    cleanup();
    await renderTree(<AdminLoading />);
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(document.querySelector("[aria-hidden='true'].lg\\:w-52")).not.toBeNull();
  });

  it("exist for every signed-in section and are server components", () => {
    const app = join(dirname(fileURLToPath(import.meta.url)), "../app");
    const found: string[] = [];
    const walk = (dir: string) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else if (name === "loading.tsx") found.push(path.slice(app.length + 1).replaceAll("\\", "/"));
      }
    };
    walk(app);
    for (const section of [
      "(app)/dev/loading.tsx",
      "(app)/dev/discover/loading.tsx",
      "(app)/dev/ideas/loading.tsx",
      "(app)/dev/ideas/[id]/loading.tsx",
      "(app)/dev/engagements/[id]/loading.tsx",
      "(app)/dev/companies/loading.tsx",
      "(app)/org/loading.tsx",
      "(app)/org/inbox/loading.tsx",
      "(app)/org/engagements/[id]/loading.tsx",
      "(app)/billing/loading.tsx",
      "(app)/settings/loading.tsx",
      "(app)/problems/[id]/loading.tsx",
      "(admin)/admin/moderation/loading.tsx",
      "(admin)/admin/claims/[id]/loading.tsx",
    ])
      expect(found).toContain(section);
    for (const file of found) expect(readFileSync(join(app, file), "utf8"), file).not.toContain("use client");
  });
});

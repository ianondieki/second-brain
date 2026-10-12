import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import OfflinePage, { generateMetadata, OFFLINE_SCRIPT } from "@/app/offline/page";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { OfflineSlot, readBuildVersion } from "./OfflineSlot";

// P27 track F (REQ-UX-08; D-69): /offline, what the worker answers for a page it cannot load and holds no copy of:
// the title, one sentence and one action, "Try again" (docs/spec/07 item 4); the way to Engagements only where this
// device keeps that list. And the offline part's island, in production builds only.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("../palette/PaletteSlot", () => ({ accountHash: async () => "a1b2c3d4e5f60718293a" }));
vi.mock("./Register", () => ({ Register: () => <i data-register="" /> }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
});

async function drawAt(path: string) {
  window.history.replaceState(null, "", path);
  return renderWithIntl(<>{await resolveServerTree(await OfflinePage())}</>).container;
}

/** Runs the page's inline script as the browser does, with Cache Storage answering `kept` (or nothing). */
async function runScript(kept: Record<string, Date | null>) {
  const match = vi.fn(async (url: string) =>
    url in kept ? new Response("", { headers: kept[url] ? { date: kept[url]!.toUTCString() } : {} }) : undefined,
  );
  vi.stubGlobal("caches", { match });
  new Function(OFFLINE_SCRIPT)();
  await new Promise((r) => setTimeout(r, 0));
  return match;
}

describe("/offline", () => {
  it("is the title, one sentence and one action, Try again, with no photograph", async () => {
    const container = await drawAt("/offline");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("You're offline");
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe(
      "This page is not kept on this device, so it opens once you're back online.",
    );
    const primary = container.querySelectorAll("[data-primary]");
    expect(primary).toHaveLength(1);
    expect(primary[0].textContent).toBe("Try again");
    expect(container.querySelector("img, picture")).toBeNull();
    // The Engagements line waits for the device's own answer.
    expect(container.querySelector<HTMLElement>("[data-offline-kept]")!.hidden).toBe(true);
    expect((await generateMetadata()).title).toBe("You're offline");
  });

  it("tries again at the address that could not be loaded", async () => {
    await drawAt("/org/inbox?org=7c1d");
    await runScript({});
    expect(screen.getByRole("link", { name: "Try again" }).getAttribute("href")).toBe(
      `${location.origin}/org/inbox?org=7c1d`,
    );
  });

  it("shows the way to the organisation's Engagements only when this device keeps that list", async () => {
    const container = await drawAt("/org/inbox?org=7c1d");
    const match = await runScript({ "/org/engagements?org=7c1d": new Date() });
    expect(match).toHaveBeenCalledWith("/org/engagements?org=7c1d", { ignoreVary: true });
    const kept = container.querySelector<HTMLElement>("[data-offline-kept]")!;
    expect(kept.hidden).toBe(false);
    expect(kept.textContent).toBe("The trackers you opened recently are kept on this device: Engagements.");
    expect(screen.getByRole("link", { name: "Engagements" }).getAttribute("href")).toBe("/org/engagements?org=7c1d");
  });

  it("shows it for the developer's Engagements", async () => {
    const container = await drawAt("/dev/ideas");
    await runScript({ "/dev/engagements": new Date() });
    expect(container.querySelector<HTMLElement>("[data-offline-kept]")!.hidden).toBe(false);
  });

  it.each([
    ["not kept", "/dev/ideas", {}],
    ["older than 7 days", "/dev/ideas", { "/dev/engagements": new Date(Date.now() - 8 * 24 * 60 * 60 * 1000) }],
    ["without a date", "/dev/ideas", { "/dev/engagements": null }],
    ["another organisation's", "/org/inbox?org=7c1d", { "/org/engagements?org=other": new Date() }],
  ])("promises nothing when the list is %s", async (_why, path, kept) => {
    const container = await drawAt(path);
    await runScript(kept);
    expect(container.querySelector<HTMLElement>("[data-offline-kept]")!.hidden).toBe(true);
  });

  it.each(["/settings/profile", "/billing", "/", "/developer"])(
    "asks nothing where the portal is not known (%s)",
    async (path) => {
      await drawAt(path);
      const match = await runScript({ "/dev/engagements": new Date() });
      expect(match).not.toHaveBeenCalled();
    },
  );
});

describe("the offline part's island", () => {
  // NODE_ENV is fixed when the module is compiled (vitest: "test"); the production build's e2e (e2e/offline.spec.ts)
  // shows the island registering there.
  it("is not rendered outside a production build; the banner is", async () => {
    const container = renderWithIntl(<>{await resolveServerTree(OfflineSlot({ page: "Engagements" }))}</>).container;
    expect(container.querySelector("[data-register]")).toBeNull();
    expect(container.querySelector("[data-offline-banner]")).not.toBeNull();
  });
});

describe("the worker's version", () => {
  it("is the build's id from .next/BUILD_ID; 'dev' without one", () => {
    expect(readBuildVersion((path) => (path.endsWith("BUILD_ID") ? "abc123\n" : ""))).toBe("abc123");
    expect(readBuildVersion(() => "")).toBe("dev");
    expect(
      readBuildVersion(() => {
        throw new Error("ENOENT");
      }),
    ).toBe("dev");
  });
});

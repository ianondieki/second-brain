import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import OfflinePage, { generateMetadata } from "@/app/offline/page";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { engagementsFor } from "./OfflineAction";
import { readBuildVersion } from "./OfflineSlot";

// P27 track F (REQ-UX-08; D-69): /offline, what the worker answers for a page it cannot load and holds no copy of:
// the title, one sentence and one action (docs/spec/07 item 4), Engagements of the address's portal, else home.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(() => {
  cleanup();
  window.history.replaceState(null, "", "/");
});

async function drawAt(path: string) {
  window.history.replaceState(null, "", path);
  return renderWithIntl(<>{await resolveServerTree(await OfflinePage())}</>).container;
}

describe("where the kept trackers are listed", () => {
  it.each([
    ["/dev/engagements/0b8f4c1e-5a2d-4e7f-9c3b-1d2e3f4a5b6c/messages", "", "/dev/engagements"],
    ["/dev", "", "/dev/engagements"],
    ["/org/inbox", "?org=7c1d", "/org/engagements?org=7c1d"],
    ["/org/inbox/x", "?org=a%20b&x=1", "/org/engagements?org=a%20b"],
    ["/org", "", "/org/engagements"],
  ])("from %s%s: %s", (path, search, expected) => {
    expect(engagementsFor(path, search)).toBe(expected);
  });

  it.each(["/", "/offline", "/settings/profile", "/billing", "/developer", "/organisation"])(
    "from %s: not known",
    (path) => {
      expect(engagementsFor(path, "")).toBeNull();
    },
  );
});

describe("/offline", () => {
  it("is the title, one sentence and one action, with no photograph", async () => {
    const container = await drawAt("/offline");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("You're offline");
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe(
      "The trackers you opened recently are available from Engagements.",
    );
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(container.querySelector("img, picture")).toBeNull();
    expect((await generateMetadata()).title).toBe("You're offline");
  });

  it("leads home where the portal is not known", async () => {
    await drawAt("/offline");
    expect(screen.getByRole("link", { name: "Go to the home page" }).getAttribute("href")).toBe("/");
  });

  it("leads to the organisation's Engagements for an organisation page that could not load", async () => {
    await drawAt("/org/inbox?org=7c1d");
    expect(screen.getByRole("link", { name: "Go to Engagements" }).getAttribute("href")).toBe(
      "/org/engagements?org=7c1d",
    );
  });

  it("leads to the developer's Engagements for a developer page that could not load", async () => {
    await drawAt("/dev/ideas");
    expect(screen.getByRole("link", { name: "Go to Engagements" }).getAttribute("href")).toBe("/dev/engagements");
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

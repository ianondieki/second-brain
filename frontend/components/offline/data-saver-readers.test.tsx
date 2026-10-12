import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GreetingBand } from "@/app/(app)/dev/GreetingBand";
import { ExploreContent } from "@/app/(public)/explore/ExploreContent";
import { AuthShell } from "@/components/AuthShell";
import { Counties } from "@/components/landing/Counties";
import { Picture } from "@/components/landing/Picture";
import { NicheBand } from "@/components/ui/NicheBand";
import en from "@/locales/en.json";
import { photo } from "@/lib/photos/photos";
import type { PublicExplore } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// P27 track F (REQ-UX-08; docs/spec/07 item 5): every reader of a photograph treats the data-saver switch's cookie
// exactly like `Save-Data: on`: the niche and county bands (the lattice), Home's greeting (the night colour alone), the
// landing's county strip, Explore's tiles and its preload, the credits' thumbnails (Picture) and the sign-in night side.

const request = vi.hoisted(() => ({ headers: new Headers() }));
// A request's headers, readable both as an awaited promise and synchronously through React's `use`.
vi.mock("next/headers", () => ({
  headers: () => Object.assign(Promise.resolve(request.headers), { status: "fulfilled", value: request.headers }),
}));
const preloads = vi.hoisted(() => ({ calls: [] as string[] }));
vi.mock("react-dom", async (actual) => ({
  ...(await actual<typeof import("react-dom")>()),
  preload: (href: string) => preloads.calls.push(href),
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/components/TopBar", () => ({
  TopBar: ({ children }: { children?: ReactNode }) => <header>{children}</header>,
}));
vi.mock("@/components/landing/MotionToggle", () => ({ MotionToggle: () => null }));

const ASKS = {
  "the switch's cookie": () => new Headers({ cookie: "NEXT_LOCALE=en; data-saver=1" }),
  "Save-Data: on": () => new Headers({ "save-data": "on" }),
} as const;

beforeEach(() => {
  request.headers = new Headers({ cookie: "NEXT_LOCALE=en" });
  preloads.calls = [];
});
afterEach(cleanup);

async function draw(node: ReactNode) {
  return renderWithIntl(<>{await resolveServerTree(node)}</>).container;
}

describe.each(Object.keys(ASKS) as (keyof typeof ASKS)[])("under %s", (asked) => {
  beforeEach(() => {
    request.headers = ASKS[asked]();
  });

  it("a niche band is the lattice, with no picture", async () => {
    const container = await draw(<NicheBand niche="agriculture" />);
    expect(container.querySelector<HTMLElement>("[data-niche-band]")!.dataset.nicheBand).toBe("lattice");
    expect(container.querySelector("picture, img")).toBeNull();
  });

  it("Home's greeting is the night colour alone", async () => {
    const container = await draw(await GreetingBand({ part: "morning", children: <h1>Good morning</h1> }));
    expect(container.querySelector<HTMLElement>("[data-greeting]")!.dataset.greeting).toBe("plain");
    expect(container.querySelector("picture, img")).toBeNull();
  });

  it("a Picture (the landing's strip, Explore's tiles, the credits) fills its box with the night colour", async () => {
    const container = await draw(
      <Picture photo={photo("nakuru-lake")!} sizes="7rem" className="aspect-[4/3] w-full" />,
    );
    const saved = container.querySelector<HTMLElement>("[data-photo-saved]")!;
    expect(saved.className).toContain("aspect-[4/3]");
    expect(saved.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector("picture, img")).toBeNull();
  });

  it("the landing's county strip sends no photograph", async () => {
    const container = await draw(await Counties());
    expect(container.querySelectorAll("[data-photo-saved]").length).toBeGreaterThan(0);
    expect(container.querySelector("picture, img")).toBeNull();
  });

  it("Explore preloads no photograph and draws none", async () => {
    const explore: PublicExplore = {
      seeded: false,
      totals: { problems: 1, counties: 1, niches: 1 },
      counties: [{ code: "KE-30", name: "Nairobi City", count: 1, newest: [] }],
      niches: [],
    };
    const container = await draw(await ExploreContent({ explore }));
    expect(preloads.calls).toEqual([]);
    expect(container.querySelector("picture, img")).toBeNull();
  });

  it("the sign-in night side keeps its words, without the photograph or its credit", async () => {
    const container = await draw(await AuthShell({ children: <p>form</p> }));
    const side = container.querySelector<HTMLElement>("aside")!;
    expect(side.dataset.authPhoto).toBe("plain");
    expect(side.querySelector("picture, img, [data-photo-credit]")).toBeNull();
    expect(side.textContent).toContain(en.panel.title);
  });
});

describe("without either", () => {
  it("every reader keeps its photograph", async () => {
    expect(
      (await draw(<NicheBand niche="agriculture" />))
        .querySelector("[data-niche-band]")!
        .getAttribute("data-niche-band"),
    ).toBe("kenya-tea");
    expect((await draw(await GreetingBand({ part: "morning", children: null }))).querySelector("img")).toBeTruthy();
    expect(
      (await draw(<Picture photo={photo("nakuru-lake")!} sizes="7rem" />)).querySelector("picture img"),
    ).toBeTruthy();
    expect((await draw(await AuthShell({ children: null }))).querySelector("aside [data-photo-credit]")).toBeTruthy();
  });

  it("a cookie that is not the switch turned on changes nothing", async () => {
    request.headers = new Headers({ cookie: "data-saver=0" });
    expect((await draw(<NicheBand niche="agriculture" />)).querySelector("picture")).toBeTruthy();
  });
});

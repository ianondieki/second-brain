import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { activityFixture } from "@/components/activity/fixtures";
import en from "@/locales/en.json";
import { briefList, ORG_ID, ORG_NAME } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import OrganisationHome from "./page";
import { ItemCard, ItemGrid } from "./ItemCard";
import { BriefForm } from "./problems/new/BriefForm";
import { BriefPreview } from "./problems/new/BriefPreview";

// D-67 (P25; REQ-UX-01, REQ-UX-02, REQ-UX-06): the organisation side in the portal's page language. Home greets by the
// hour of the app clock on Nairobi's photograph with the eyebrow saying where you are and one primary action, shows
// its figures from the first paint and shows "Your last 26 weeks"; a card is a band, one link and at most two chips; the Brief form's
// preview follows what is typed.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("next/headers", () => ({ cookies: async () => ({ get: () => undefined }), headers: async () => new Headers() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  redirect: () => {
    throw new Error("redirect");
  },
  unstable_rethrow: () => undefined,
}));
vi.mock("react-dom", async (original) => ({ ...(await original<typeof import("react-dom")>()), preload: vi.fn() }));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/tour/FirstLoginTour", () => ({ FirstLoginTour: () => null }));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ nav, children }: { nav: ReactNode; children: ReactNode }) => (
    <>
      {nav}
      <main>{children}</main>
    </>
  ),
}));

const state = vi.hoisted(() => ({ now: "2026-10-08T06:30:00Z", activity: null as unknown }));
vi.mock("@/lib/api/server", () => ({ appNow: () => state.now }));
vi.mock("@/components/activity/fetch", () => ({ getActivity: async () => state.activity }));
const membership = { org_id: ORG_ID, org_name: ORG_NAME, roles: ["reviewer"] };
vi.mock("./data", () => ({
  orgContext: async () => ({
    me: { user: { display_name: "Rita Njeri" }, mfa: { enrolled: true, required: true, verified: true } },
    memberships: [membership],
    org: membership,
    missing: null,
    query: "",
  }),
  getInbox: async () => ({ kind: "page", page: { items: [], next_cursor: null, held_count: 0, verification: "e2" } }),
}));
vi.mock("./scout-data", () => ({ getMatches: async () => ({ kind: "ok", value: [] }) }));
vi.mock("@/components/tracker/data", () => ({ orgEngagements: async () => ({ ok: true, value: [] }) }));
vi.mock("./brief-data", () => ({ getBriefs: async () => ({ kind: "ok", value: briefList() }) }));

beforeEach(() => {
  state.now = "2026-10-08T06:30:00Z"; // 09:30 in Nairobi
  state.activity = null;
});
afterEach(cleanup);

async function home() {
  return renderWithIntl(<>{await resolveServerTree(await OrganisationHome({ searchParams: Promise.resolve({}) } as never))}</>);
}

describe("the organisation Home (P25)", () => {
  it("greets by the hour in Nairobi on that time's photograph, says where you are, and has one primary action", async () => {
    const { container } = await home();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Good morning, Rita Njeri");
    expect(container.querySelector("[data-eyebrow]")?.textContent).toBe("Organisation / Home");
    const band = container.querySelector<HTMLElement>("[data-greeting]")!;
    expect(band.dataset.greeting).toBe("nairobi-morning");
    // Decorative: the photograph says nothing to assistive technology, and is fetched at once (the first screen's).
    const img = band.querySelector("img")!;
    expect(img.getAttribute("alt")).toBe("");
    expect(img.getAttribute("loading")).toBe("eager");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(within(band).getByRole("link", { name: "Open the Inbox" })).toBeTruthy();
  });

  it("says good evening on the evening's photograph", async () => {
    state.now = "2026-10-08T16:30:00Z"; // 19:30 in Nairobi
    const { container } = await home();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Good evening, Rita Njeri");
    expect(container.querySelector<HTMLElement>("[data-greeting]")!.dataset.greeting).toBe("nairobi-golden-hour");
  });

  it("shows its figures as text from the first paint (they drive what to do next: no count-up)", async () => {
    const { container } = await home();
    const tiles = container.querySelector("[data-home='stats']")!;
    expect(tiles.querySelector("[data-count-up]")).toBeNull();
    expect(tiles.querySelector(".count")).toBeNull();
    // briefList() holds one open Brief; the tile says 1 in plain text.
    expect(container.querySelector<HTMLElement>("[data-stat='briefs']")!.textContent).toMatch(/^Problem Briefs1/);
    expect(container.querySelector<HTMLElement>("[data-stat='inbox']")!.textContent).toMatch(/^Inbox0/);
  });

  it("shows 'Your last 26 weeks' when the API answers, and leaves it out when it does not", async () => {
    const { container, unmount } = await home();
    expect(container.querySelector("[data-home='activity']")).toBeNull();
    unmount();
    state.activity = activityFixture({ "2026-10-06": 3, "2026-10-07": 1 });
    await home();
    const section = screen.getByRole("region", { name: "Your last 26 weeks" });
    expect(within(section).getByText("4 actions in the last 26 weeks")).toBeTruthy();
  });
});

describe("ItemCard", () => {
  it("is a band, the title as its one link, the meta line and at most two chips at its foot", () => {
    const { container } = renderWithIntl(
      <ItemGrid>
        <li>
          <ItemCard
            band={<div className="niche-band" data-niche-band="kenya-tea" />}
            title="Cold chain for dairy co-ops"
            href="/org/inbox/p1"
            meta="Agriculture › Dairy"
            chips={[
              <span key="a" data-chip="stage">
                New
              </span>,
            ]}
            data-proposal="p1"
          />
        </li>
      </ItemGrid>,
    );
    const card = container.querySelector("article[data-proposal='p1']")!;
    expect(within(card as HTMLElement).getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Cold chain for dairy co-ops" }).getAttribute("href")).toBe("/org/inbox/p1");
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe("Cold chain for dairy co-ops");
    expect(card.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    // Band, head, foot: three parts, so a row of cards aligns them (subgrid).
    expect(card.children).toHaveLength(3);
    expect(card.parentElement!.className).toContain("card-sub");
    expect(card.parentElement!.parentElement!.className).toContain("card-grid");
  });
});

describe("BriefPreview", () => {
  const props = {
    orgName: ORG_NAME,
    niches: [{ id: "n1", name: "Financial services", children: [{ id: "n2", name: "Microfinance & SACCOs" }] }],
    counties: [{ id: "KE-22", label: "Kiambu" }],
    bands: [{ code: "b1", label: "KES 100,000 to 500,000" }] as never,
    locale: "en",
  };
  const empty = { title: "", statement: "", affected: "", niche: "", county: "", band: "", deadline: "" };

  it("reads as the Discover card would, from what is typed, and is not read twice by assistive technology", () => {
    const { container, unmount } = renderWithIntl(<BriefPreview draft={empty} {...props} />);
    expect(screen.getByRole("heading", { name: "How it reads on Discover" })).toBeTruthy();
    const card = container.querySelector(".brief-preview-card")!;
    expect(card.getAttribute("aria-hidden")).toBe("true");
    expect(card.textContent).toContain("Your title");
    expect(card.textContent).toContain("Anywhere in Kenya");
    expect(card.textContent).toContain("Budget open");
    unmount();
    const filled = renderWithIntl(
      <BriefPreview
        draft={{ ...empty, title: "SACCO members miss repayments", niche: "n2", county: "KE-22", band: "b1", deadline: "2026-11-30" }}
        {...props}
      />,
    ).container.querySelector(".brief-preview-card")!;
    expect(filled.textContent).toContain("SACCO members miss repayments");
    expect(filled.textContent).toContain("Financial services › Microfinance & SACCOs");
    expect(filled.textContent).toContain("Kiambu");
    expect(filled.textContent).toContain(`Posted by ${ORG_NAME}`);
    expect(filled.textContent).toContain("Budget: KES 100,000 to 500,000");
    expect(filled.textContent).toContain("Proposals by 30 Nov 2026");
  });

  it("follows the form as it is filled in", () => {
    renderWithIntl(<PreviewHarness />);
    fireEvent.change(screen.getByLabelText("t"), { target: { value: "Tower sites go dark" } });
    expect(document.querySelector("[data-preview='title']")?.textContent).toBe("Tower sites go dark");
  });

  it("shows the page's own preview first and the live one, fetched on the first edit, after it", async () => {
    renderWithIntl(
      <BriefForm
        orgId={ORG_ID}
        orgName={ORG_NAME}
        niches={props.niches}
        counties={props.counties}
        bands={props.bands}
        today="2026-10-08"
        planLimit={1}
        planNames={{}}
        doneHref="/org/problems"
        hereHref="/org/problems/new"
        cancelHref="/org/problems"
        preview={<p data-static-preview="">How it reads on Discover</p>}
      />,
    );
    expect(document.querySelector("[data-static-preview]")).not.toBeNull();
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Tower sites go dark" } });
    expect(await screen.findByText("Tower sites go dark", { selector: "[data-preview='title']" })).toBeTruthy();
    expect(document.querySelector("[data-static-preview]")).toBeNull();
  });

  function PreviewHarness() {
    const [title, setTitle] = useState("");
    return (
      <>
        <input aria-label="t" value={title} onChange={(e) => setTitle(e.target.value)} />
        <BriefPreview draft={{ ...empty, title }} {...props} />
      </>
    );
  }
});

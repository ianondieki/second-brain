import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import type { PublicProblem } from "@/lib/public/public-data";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import PublicProblemPage, { generateMetadata } from "./page";

// P24 (REQ-UX-03, REQ-UX-04): the public problem page. Its source, title, county and niche, date, statement and who it
// affects; the organisation by its verification level only; "Seeded example" on demo data; one primary action and a
// log-in link back to the signed-in page; the share card in its metadata; not found when the problem is not public.

const read = vi.hoisted(() => vi.fn());
const notFound = vi.hoisted(() => vi.fn(() => {
  throw new Error("NEXT_NOT_FOUND");
}));
vi.mock("@/lib/public/public-data", async (actual) => ({ ...(await actual<object>()), publicProblem: read }));
vi.mock("next/navigation", () => ({ notFound }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => null }));

const ID = "0199b000-0000-7000-8000-0000000000aa";
const PROBLEM: PublicProblem = {
  id: ID,
  title: "Late diesel deliveries darken tower sites",
  statement: "Generators at rural tower sites run dry before the next delivery.",
  affected_group: "Subscribers in rural Nakuru",
  source: "brief",
  posted_at: "2026-10-06T21:30:00Z",
  county: { code: "KE-32", name: "Nakuru" },
  niche: { id: "n", name: "Networks & Telecommunications", parent: { id: "p", name: "ICT" } },
  organisation: { verification: "e2" },
  seeded: true,
};
const params = (id = ID) => ({ params: Promise.resolve({ id }) }) as never;

async function page(id = ID) {
  return renderWithIntl(<>{await resolveServerTree(await PublicProblemPage(params(id)))}</>);
}

beforeEach(() => read.mockReset());
afterEach(cleanup);

describe("the public problem page", () => {
  it("shows the problem with its place, niche, date and organisation level, labelled as seeded", async () => {
    read.mockResolvedValue({ kind: "found", problem: PROBLEM });
    const { container } = await page();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(PROBLEM.title);
    const article = container.querySelector<HTMLElement>(`[data-public-problem='${ID}']`)!;
    expect(article.querySelector(".eyebrow")!.textContent).toBe("Problem Brief");
    expect(article.textContent).toContain("Nakuru");
    expect(article.textContent).toContain("ICT › Networks & Telecommunications");
    expect(article.querySelector("time")!.textContent).toBe("Posted 7 Oct 2026"); // 00:30 in Nairobi
    expect(article.querySelector(".demo-label")!.textContent).toBe("Seeded example");
    expect(article.querySelector("[data-problem='organisation']")!.textContent).toBe("Posted by a verified organisation");
    expect(within(article).getByRole("heading", { level: 2, name: "Who it affects" })).toBeTruthy();
    const primary = container.querySelectorAll("[data-primary]");
    expect([...primary].map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["Create an account to answer this", "/signup"]]);
    expect(within(article).getByRole("link", { name: "Log in" }).getAttribute("href")).toBe(`/login?next=%2Fproblems%2F${ID}`);
    expect(screen.getByRole("link", { name: "Back to Explore" }).getAttribute("href")).toBe("/explore");
  });

  it("says Nationwide with no county, and leaves out what the problem does not carry", async () => {
    read.mockResolvedValue({ kind: "found", problem: { ...PROBLEM, county: null, niche: null, organisation: null, affected_group: null, posted_at: null, seeded: false, source: "developer" } });
    const { container } = await page();
    expect(container.textContent).toContain("Nationwide");
    expect(container.querySelector("[data-problem='organisation']")).toBeNull();
    expect(container.querySelector(".demo-label")).toBeNull();
    expect(container.querySelector("time")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Who it affects" })).toBeNull();
    expect(container.querySelector(".eyebrow")!.textContent).toBe("Reported by a developer");
  });

  it("never names the organisation, only its level", async () => {
    read.mockResolvedValue({ kind: "found", problem: { ...PROBLEM, organisation: { verification: "unclaimed" } } });
    const { container } = await page();
    expect(container.querySelector("[data-problem='organisation']")!.textContent).toBe("Posted by a listed organisation");
  });

  it("is not found when the problem is not public", async () => {
    read.mockResolvedValue({ kind: "notFound" });
    await expect(PublicProblemPage(params())).rejects.toThrow("NEXT_NOT_FOUND");
    expect(notFound).toHaveBeenCalled();
  });

  it("points its share card at the public card route", async () => {
    read.mockResolvedValue({ kind: "found", problem: PROBLEM });
    const meta = await generateMetadata(params());
    expect(meta.title).toBe(PROBLEM.title);
    expect(meta.openGraph?.images).toEqual([{ url: `/og/problem/${ID}`, width: 1200, height: 630, alt: `${PROBLEM.title}, a problem on Wazo` }]);
    read.mockResolvedValue({ kind: "notFound" });
    expect(await generateMetadata(params())).toEqual({});
  });
});

// REQ-FND-04: in the public demo the one action goes to /login's persona picker, and the log-in line (the same place)
// is left out; sign-up is switched off there.
describe("the public problem page in the public demo", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("calls \"Try the demo\" to /login with no sign-up or second log-in link; as before with the mode off", async () => {
    read.mockResolvedValue({ kind: "found", problem: PROBLEM });
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { container } = await page();
    const primary = container.querySelector<HTMLAnchorElement>("a[data-primary]")!;
    expect(primary.getAttribute("href")).toBe("/login");
    expect(primary.textContent).toBe(en.publicDemo.tryDemo);
    expect(container.querySelector('a[href="/signup"]')).toBeNull();
    expect(container.querySelector('a[href^="/login?"]')).toBeNull();
    cleanup();
    vi.stubEnv("PUBLIC_DEMO", "false");
    const off = await page();
    expect(off.container.querySelector("a[data-primary]")!.getAttribute("href")).toBe("/signup");
    expect(off.container.querySelector('a[href^="/login?"]')).not.toBeNull();
  });
});

// REQ-FND-04: signed-out public pages are frozen at the seed in the public demo, so a problem a visitor posted later
// answers 404 to signed-out readers. The page needs nothing of its own for it: the normal not-found screen.
describe("a problem posted after the seed, in the public demo", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("is the normal not-found, as with the mode off", async () => {
    for (const mode of ["true", "false"]) {
      vi.stubEnv("PUBLIC_DEMO", mode);
      notFound.mockClear();
      read.mockResolvedValue({ kind: "notFound" });
      await expect(PublicProblemPage(params())).rejects.toThrow("NEXT_NOT_FOUND");
      expect(notFound).toHaveBeenCalledTimes(1);
    }
  });
});

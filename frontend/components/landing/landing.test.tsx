import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { Counties } from "./Counties";
import { CountUp } from "./CountUp";
import { HeroComposition } from "./HeroComposition";
import { HowItWorks } from "./HowItWorks";
import { Reasons } from "./Reasons";
import { Stats } from "./Stats";

// P23-2 and P24 (REQ-UX-03; D-66): the landing's craft without new claims. The hero's story ends on the real stepper
// (Agreement, "Your turn") and its panel is labelled "Demo data"; the stats are product constants; the county strip
// links to Explore; How it works is three numbered steps; the why-panel quotes the ranker's own words, labelled.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("HeroComposition", () => {
  it("tells the story to assistive technology as it ends: Agreement is the current stage and it is your turn", () => {
    const { container } = renderWithIntl(<HeroComposition />);
    const steppers = screen.getAllByRole("list", { name: "Stages" });
    expect(steppers).toHaveLength(1); // the "before" stepper is aria-hidden
    const current = steppers[0].querySelector("[aria-current='step']")!;
    expect(current.getAttribute("data-group")).toBe("agreement");
    expect(within(container.querySelector(".hero-steps")!).getAllByText("Agreement").length).toBeGreaterThan(0);
    const before = container.querySelectorAll(".hero-before");
    expect(before).toHaveLength(2);
    for (const layer of before) expect(layer.getAttribute("aria-hidden")).toBe("true");
    expect(before[1].querySelector("[aria-current='step']")!.getAttribute("data-group")).toBe("contact_nda");
    expect(container.querySelector(".hero-turn")!.textContent).toBe("Your turn");
    expect(container.querySelector(".hero-arrive")!.textContent).toContain("Scout match");
    expect(container.querySelector("[data-seal] .seal-draw")).not.toBeNull();
  });

  it("labels the panel as demo data and says the ticking countdown once, in words", () => {
    const { container } = renderWithIntl(<HeroComposition />);
    expect(container.querySelector(".demo-label")!.textContent).toBe("Demo data");
    // Days, hours and minutes, as the product's countdown (no seconds: nothing moves between the minutes, WCAG 2.2.2);
    // the boxes are decorative and the words are read instead.
    const boxes = container.querySelectorAll(".due-box");
    expect([...boxes].map((box) => box.querySelector(".due-u")!.textContent)).toEqual(["days", "hrs", "min"]);
    expect(boxes[0].parentElement!.getAttribute("aria-hidden")).toBe("true");
    expect(container.querySelector(".due-m")).not.toBeNull();
    expect(container.querySelector(".due-s")).toBeNull();
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/\.due-m \{\s*counter-reset: due var\(--due-m\);\s*animation: due-m 3600s steps\(60, end\)/);
    expect(css).not.toMatch(/due-s|steps\(60, end\) -?\d+s infinite;\s*\}\s*\.due-s/);
    expect(container.querySelector(".sr-only")!.textContent).toContain("2 days 14 hours left (example)");
  });
});

describe("Stats", () => {
  it("shows four product constants, each with its real figure for assistive technology, in a CountUp box", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(<Stats />)}</>);
    const terms = [...container.querySelectorAll("dt")].map((dt) => dt.textContent);
    expect(terms).toEqual(["Stages on one tracker", "Counties Wazo knows", "Niches to follow", "Contact details shared before an NDA"]);
    const figures = [...container.querySelectorAll("dd")].map((dd) => ({
      read: dd.querySelector(".sr-only")!.textContent,
      to: (dd.querySelector(".count") as HTMLElement).style.getPropertyValue("--to"),
      hidden: dd.querySelector(".count")!.getAttribute("aria-hidden"),
    }));
    expect(figures).toEqual([
      { read: "5", to: "5", hidden: "true" },
      { read: "47", to: "47", hidden: "true" },
      { read: "16", to: "16", hidden: "true" },
      { read: "0", to: "0", hidden: "true" },
    ]);
    expect(container.querySelector("[data-count-up] dl")).not.toBeNull();
  });

  it("counts the niches the reference data seeds", () => {
    const root = join(process.cwd(), "..");
    const reference = readFileSync(join(root, "backend/seed/reference.yaml"), "utf8");
    const niches = reference.slice(reference.indexOf("\nniches:"));
    expect(niches.match(/^\s+- \{slug: /gm)).toHaveLength(16);
    expect(reference.match(/kind: county/g)).toHaveLength(47);
  });
});

describe("CountUp", () => {
  it("starts the count once, the first time half of it is on screen", () => {
    let notify: (entries: Partial<IntersectionObserverEntry>[]) => void = () => undefined;
    const disconnect = vi.fn();
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(callback: (entries: Partial<IntersectionObserverEntry>[]) => void, options: IntersectionObserverInit) {
          notify = callback;
          expect(options.threshold).toBe(0.5);
        }
        observe() {}
        disconnect = disconnect;
      },
    );
    const { container } = renderWithIntl(
      <CountUp>
        <span className="count" />
      </CountUp>,
    );
    const box = container.querySelector("[data-count-up]") as HTMLElement;
    act(() => notify([{ isIntersecting: false }]));
    expect(box.hasAttribute("data-run")).toBe(false);
    act(() => notify([{ isIntersecting: true }]));
    expect(box.hasAttribute("data-run")).toBe(true);
    expect(disconnect).toHaveBeenCalled();
  });
});

describe("Counties", () => {
  it("links six counties to Explore by their reference code, once for the keyboard and assistive technology", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(<Counties />)}</>);
    const rows = container.querySelectorAll(".pan-row");
    expect(rows).toHaveLength(2);
    expect(rows[1].getAttribute("aria-hidden")).toBe("true");
    for (const link of rows[1].querySelectorAll("a")) expect(link.getAttribute("tabindex")).toBe("-1");
    const links = within(rows[0] as HTMLElement).getAllByRole("link");
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/explore#KE-30",
      "/explore#KE-28",
      "/explore#KE-17",
      "/explore#KE-31",
      "/explore#KE-44",
      "/explore#KE-10",
    ]);
    expect(links[4].textContent).toBe("Uasin Gishu");
    // Photographs below the fold: lazy, decoded off the main thread, sized, AVIF first.
    const img = rows[0].querySelector("img")!;
    expect([img.getAttribute("loading"), img.getAttribute("decoding"), img.getAttribute("alt")]).toEqual(["lazy", "async", ""]);
    expect(img.getAttribute("width")).not.toBeNull();
    expect(rows[0].querySelector("source")!.getAttribute("type")).toBe("image/avif");
    expect(screen.getByRole("link", { name: "Explore all counties" }).getAttribute("href")).toBe("/explore");
    // A visible Pause for touch (no hover there), pressed while paused, inside the box it holds still.
    const pause = screen.getByRole("button", { name: "Pause the photographs" });
    expect(pause.getAttribute("aria-pressed")).toBe("false");
    expect(pause.closest("[data-motion]")!.contains(rows[0])).toBe(true);
    fireEvent.click(pause);
    expect(pause.getAttribute("aria-pressed")).toBe("true");
    expect(pause.closest("[data-motion]")!.hasAttribute("data-paused")).toBe(true);
    // Focus on a tile stops the row and makes it scroll, so the tile is never off screen.
    const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
    expect(css).toMatch(/\.pan:focus-within \.pan-track \{\s*animation: none;/);
    expect(css).toMatch(/\.pan:focus-within \{\s*overflow-x: auto;/);
  });
});

describe("HowItWorks", () => {
  it("numbers the three steps in order, each with its chip, marked for the scroll reveal", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(<HowItWorks />)}</>);
    const reveal = [...container.querySelectorAll<HTMLElement>(".reveal")];
    expect(reveal).toHaveLength(3);
    expect(reveal.map((el) => el.style.getPropertyValue("--i"))).toEqual(["0", "1", "2"]);
    expect(reveal.map((el) => el.querySelector("[aria-hidden] span")!.textContent)).toEqual(["01", "02", "03"]);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Publish an idea",
      "Reviewed under NDA",
      "Agree the next step",
    ]);
    expect(container.querySelectorAll(".font-mono.text-xs")).toHaveLength(3);
  });
});

describe("Reasons", () => {
  it("quotes the ranker's own reason texts for one card, labelled as a seeded example", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(<Reasons />)}</>);
    expect(container.querySelector(".terminal .demo-label")!.textContent).toBe("Seeded example");
    const values = [...container.querySelectorAll(".terminal dd")].map((dd) => dd.textContent!);
    const root = join(process.cwd(), "..");
    const ranker = readFileSync(join(root, "backend/src/bridge/matching/ranker.py"), "utf8");
    // Every line but the card's title is a text the ranker writes (the number of proposals is the card's own).
    for (const text of [...values.slice(1), "Strong fit"]) expect(ranker.replace("{proposals} proposals", "2 proposals")).toContain(`"${text}`);
    expect(values[0]).toBe(en.landing.features.sample.trend1);
  });
});

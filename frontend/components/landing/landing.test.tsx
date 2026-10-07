import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { HeroComposition } from "./HeroComposition";
import { HowItWorks } from "./HowItWorks";
import { Trust } from "./Trust";

// P23-2 (REQ-UX-03): the landing's craft without new claims. The hero's story ends on the real stepper (Agreement,
// "Your turn"); the stepper it starts from is hidden from assistive technology; the strip under the hero restates
// four existing truths; How it works marks its items for the scroll reveal.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));

afterEach(cleanup);

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
    expect(container.textContent).toContain("Illustrative example");
  });
});

describe("Trust", () => {
  it("lists four of the product's existing truths, each an icon and words, with no figure", async () => {
    renderWithIntl(<>{await resolveServerTree(<Trust />)}</>);
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Every version timestamped",
      "Full details under one Evaluation NDA",
      "Proposals go only to verified organisations",
      "One tracker for both sides",
    ]);
    for (const item of items) {
      expect(item.querySelector("svg")!.getAttribute("aria-hidden")).toBe("true");
      expect(item.textContent).not.toMatch(/\d/);
    }
  });
});

describe("HowItWorks", () => {
  it("marks the three steps and the five stages for the scroll reveal, in order", async () => {
    const { container } = renderWithIntl(<>{await resolveServerTree(<HowItWorks />)}</>);
    const reveal = [...container.querySelectorAll<HTMLElement>(".reveal")];
    expect(reveal).toHaveLength(8);
    expect(reveal.map((el) => el.style.getPropertyValue("--i"))).toEqual(["0", "1", "2", "0", "1", "2", "3", "4"]);
  });
});

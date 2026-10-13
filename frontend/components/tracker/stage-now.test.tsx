import { cleanup, render } from "@testing-library/react";
import { createTranslator, NextIntlClientProvider } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { detail } from "@/test/engagement";
import { resolveServerTree } from "@/test/server-tree";

import type { Detail, StageStep, State } from "./model";
import { TrackerSpine } from "./TrackerFrame";

// REQ-ENG-06 review: the "Now: …" line under the current step names the stage in the reader's language
// (tracker.stage.<STATE>), as the sub-stages do; the API's English stage_label only for a stage the locales do not
// name. Rendered on the server (TrackerSpine): the names never join the client bundle.

const lang = vi.hoisted(() => ({ locale: "en" as "en" | "sw" }));
const MESSAGES = { en, sw };

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: lang.locale, messages: MESSAGES[lang.locale], namespace: namespace as never }),
  getLocale: async () => lang.locale,
}));

afterEach(() => {
  cleanup();
  lang.locale = "en";
});

const step = (state: State, label: string, group: StageStep["group"]): StageStep => ({ state, label, group });
const STEPS = [
  step("SUBMITTED", "Proposal submitted", "review"),
  step("UNDER_REVIEW", "Under review", "review"),
  step("PROCUREMENT_ROUTE", "Procurement route", "contact_nda"),
  step("INTEREST_CONFIRMED", "Approved to proceed (non-binding)", "contact_nda"),
];

async function spine(value: Detail, locale: "en" | "sw" = "en") {
  lang.locale = locale;
  const tree = await resolveServerTree(await TrackerSpine({ detail: value, history: null }));
  return render(
    <NextIntlClientProvider locale={locale} messages={MESSAGES[locale]}>
      {tree}
    </NextIntlClientProvider>,
  ).container;
}

const inRoute = (overrides: Partial<Detail> = {}) =>
  detail({
    my_party: "org",
    state: "PROCUREMENT_ROUTE",
    stage_label: "Procurement route",
    stage_group: "contact_nda",
    steps: STEPS,
    ...overrides,
  } as Partial<Detail>);

const nowLine = (container: HTMLElement) =>
  [...container.querySelectorAll("[aria-current='step'] span")].find((el) => /^(Now|Sasa): /.test(el.textContent ?? ""))
    ?.textContent;

describe("the current step's \"Now\" line", () => {
  it("names the stage from the locales in English", async () => {
    expect(nowLine(await spine(inRoute({ stage_label: "ignored by the page" } as Partial<Detail>)))).toBe(
      "Now: Procurement route",
    );
  });

  it("names it in Swahili for a Swahili reader, never the API's English label", async () => {
    const container = await spine(inRoute(), "sw");
    expect(nowLine(container)).toBe(`Sasa: ${sw.tracker.stage.PROCUREMENT_ROUTE}`);
    expect(container.querySelector("[aria-current='step']")?.textContent).not.toContain("Procurement route");
  });

  it("names a side state from the locales too (a question waiting for its answer)", async () => {
    const asked = inRoute({
      state: "INFO_REQUESTED",
      stage_label: "Information requested",
      stage_group: null,
      paused_from: "PROCUREMENT_ROUTE",
    } as Partial<Detail>);
    expect(nowLine(await spine(asked, "sw"))).toBe(`Sasa: ${sw.tracker.stage.INFO_REQUESTED}`);
  });

  it("keeps the API's label for a stage the locales do not name", async () => {
    const odd = inRoute({ state: "DISPUTED", stage_label: "In dispute", stage_group: "agreement" } as Partial<Detail>);
    const container = await spine(odd);
    expect(nowLine(container)).toBe("Now: In dispute");
    // No stage list to repeat it: the line shows at every width.
    expect(container.querySelector("[data-substages]")).toBeNull();
    expect(container.querySelector("[data-stage-now]")?.className).not.toContain("max-lg:hidden");
  });

  it("gives way on phones to the stage list, whose current stage says the same (from 1024 px it stays)", async () => {
    const container = await spine(inRoute());
    expect(container.querySelector("[data-substages='column'] [data-substage='PROCUREMENT_ROUTE']")).not.toBeNull();
    expect(container.querySelector("[data-stage-now]")?.className).toContain("max-lg:hidden");
  });
});

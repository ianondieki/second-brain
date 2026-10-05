import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { cleanWords, discoverHref, isNarrowed, parseDiscover, searchQuery, trendQuery } from "./discover";
import { nameProblem, saveBody, savedProblem, type SavedSearch, type SavedSearchRow } from "./saved-searches";
import type { SavedSearchCalls } from "./saved-searches-calls";
import { SavedSearches, type CurrentSearch } from "./SavedSearches";

// REQ-PERS-03, REQ-TREND-02 (P21 track C): Discover's words filter, "Save this search" and the Saved searches panel.

afterEach(cleanup);

// jsdom has no <dialog> methods: the confirmation opens and closes as the browser's would.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});

describe("Discover's words filter", () => {
  it("reads words from the address, trimmed, 1 to 100 characters", () => {
    expect(parseDiscover({ words: "  cold   chain " })).toEqual({ view: "problems", words: "cold chain" });
    expect(parseDiscover({ words: "   " })).toEqual({ view: "problems" });
    expect(parseDiscover({ words: "a".repeat(101) })).toEqual({ view: "problems" });
    expect(cleanWords("maji\u0000")).toBeUndefined();
  });

  it("writes them after the county, as the alert links do (bridge/web_paths.py)", () => {
    expect(discoverHref({ view: "briefs", niche: "agriculture", county: "KE-32", words: "cold chain" })).toBe(
      "/dev/discover?view=briefs&niche=agriculture&county=KE-32&words=cold+chain",
    );
  });

  it("sends them to the trending and Briefs lists, never the gap's", () => {
    const query = { view: "problems" as const, niche: "health", words: "clinic" };
    expect(searchQuery(query)).toEqual({ niche: "health", county: undefined, words: "clinic" });
    expect(trendQuery(query)).toEqual({ niche: "health", county: undefined });
    expect(isNarrowed({ view: "gap", words: "clinic" })).toBe(false);
    expect(isNarrowed({ view: "briefs", words: "clinic" })).toBe(true);
  });
});

describe("a saved search's rules", () => {
  it("sends the view and filters with the name trimmed", () => {
    expect(saveBody({ view: "briefs", county: "KE-32" }, "  Nakuru Briefs ", false)).toEqual({
      name: "Nakuru Briefs",
      view: "briefs",
      niche: null,
      county: "KE-32",
      words: null,
      alerts: false,
    });
    expect(nameProblem(" ")).toBe("nameMissing");
    expect(nameProblem("x".repeat(61))).toBe("nameLong");
    expect(nameProblem("Agriculture in Nakuru")).toBeNull();
  });

  it("words the cap, unknown filters and the rest", () => {
    expect(savedProblem(409, { detail: { code: "saved_searches_limit" } })).toBe("limit");
    expect(savedProblem(422, { detail: { code: "unknown_niche" } })).toBe("unknown");
    expect(savedProblem(422, { detail: { code: "unknown_county" } })).toBe("unknown");
    expect(savedProblem(401, undefined)).toBe("signedOut");
    expect(savedProblem(0, undefined)).toBe("network");
    expect(savedProblem(500, undefined)).toBe("failed");
  });
});

const CURRENT: CurrentSearch = {
  query: { view: "problems", niche: "agriculture", county: "KE-32", words: "cold chain" },
  suggestedName: "Agriculture in Nakuru",
  href: "/dev/discover?niche=agriculture&county=KE-32&words=cold+chain",
  facts: ["Problems", "Agriculture", "Nakuru", "“cold chain”"],
};

const ROW: SavedSearchRow = { id: "s1", name: "Health Briefs", alerts: true, href: "/dev/discover?view=briefs&niche=health", facts: ["Briefs", "Health"] };

function savedOut(name: string): SavedSearch {
  return {
    id: "s2",
    name,
    view: "problems",
    niche: "agriculture",
    county: "KE-32",
    words: "cold chain",
    alerts: true,
    last_alerted_at: null,
    created_at: "2026-10-05T08:00:00Z",
  };
}

function fakeCalls(overrides: Partial<SavedSearchCalls> = {}): SavedSearchCalls {
  return {
    save: vi.fn(async (body) => ({ ok: true as const, value: savedOut(body.name) })),
    setAlerts: vi.fn(async () => ({ ok: true as const, value: savedOut("x") })),
    remove: vi.fn(async () => ({ ok: true as const, value: undefined })),
    ...overrides,
  };
}

function renderPanel(props: { initial?: SavedSearchRow[]; max?: number; current?: CurrentSearch | null; calls?: SavedSearchCalls }) {
  const calls = props.calls ?? fakeCalls();
  renderWithIntl(
    <SavedSearches
      initial={props.initial ?? []}
      max={props.max ?? 10}
      current={props.current === undefined ? CURRENT : props.current}
      settingsHref="/settings/notifications"
      calls={calls}
    />,
  );
  return calls;
}

describe("the saved searches strip", () => {
  it("is one sentence and one action when nothing is saved", () => {
    renderPanel({});
    expect(document.querySelector("[data-saved-empty]")?.textContent).toBe(en.savedSearches.empty);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Save this search" })).toBeTruthy();
  });

  it("shows nothing on a list that cannot be saved when nothing is saved", () => {
    renderPanel({ current: null });
    expect(document.querySelector("[data-saved-searches]")).toBeNull();
  });

  it("saves the current view and filters under a name, alerts on, and lists it", async () => {
    const calls = renderPanel({ initial: [ROW] });
    fireEvent.click(screen.getByRole("button", { name: "Save this search" }));
    const name = screen.getByRole("textbox", { name: "Name" }) as HTMLInputElement;
    expect(name.value).toBe("Agriculture in Nakuru");
    expect(screen.getByRole("checkbox", { name: en.savedSearches.alertsLabel })).toHaveProperty("checked", true);
    fireEvent.change(name, { target: { value: "Cold chain, Nakuru" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save search" })));
    expect(calls.save).toHaveBeenCalledWith({
      name: "Cold chain, Nakuru",
      view: "problems",
      niche: "agriculture",
      county: "KE-32",
      words: "cold chain",
      alerts: true,
    });
    const list = screen.getByRole("list", { name: en.savedSearches.listLabel });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByRole("link", { name: "Cold chain, Nakuru" }).getAttribute("href")).toBe(CURRENT.href);
    expect(items[0].querySelector("[data-facts]")?.textContent).toBe("ProblemsAgricultureNakuru“cold chain”");
    expect(screen.getByRole("status").textContent).toBe("Saved: Cold chain, Nakuru.");
    expect(screen.getByRole("button", { name: "Saved searches (2)" })).toBe(document.activeElement);
  });

  it("checks the name before sending it", () => {
    const calls = renderPanel({});
    fireEvent.click(screen.getByRole("button", { name: "Save this search" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Name" }), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save search" }));
    expect(calls.save).not.toHaveBeenCalled();
    expect(screen.getByText(en.savedSearches.problem.nameMissing)).toBeTruthy();
  });

  it("explains the cap and keeps Save from opening at 10", () => {
    const rows = Array.from({ length: 10 }, (_, i) => ({ ...ROW, id: `s${i}`, name: `Search ${i}` }));
    renderPanel({ initial: rows, max: 10 });
    const save = screen.getByRole("button", { name: "Save this search" });
    expect(save.getAttribute("aria-disabled")).toBe("true");
    const limit = document.getElementById(save.getAttribute("aria-describedby")!);
    expect(limit?.textContent).toBe("You have 10 saved searches, the most you can keep. Delete one to save this search.");
    fireEvent.click(save);
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
  });

  it("says so when the API refuses the 11th", async () => {
    const calls = fakeCalls({ save: vi.fn(async () => ({ ok: false as const, problem: "limit" as const })) });
    renderPanel({ initial: [ROW], calls });
    fireEvent.click(screen.getByRole("button", { name: "Save this search" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Save search" })));
    expect(screen.getByRole("alert").textContent).toContain("You have 10 saved searches");
  });

  it("turns alerts off at once and back on when the API refuses", async () => {
    const setAlerts = vi.fn(async () => ({ ok: false as const, problem: "network" as const }));
    renderPanel({ initial: [ROW], calls: fakeCalls({ setAlerts }) });
    fireEvent.click(screen.getByRole("button", { name: "Saved searches (1)" }));
    const toggle = screen.getByRole("switch", { name: "Alerts Health Briefs" });
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    await act(async () => fireEvent.click(toggle));
    expect(setAlerts).toHaveBeenCalledWith("s1", false);
    expect(toggle.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("alert").textContent).toBe(en.savedSearches.alertsProblem);
  });

  it("deletes after a confirmation", async () => {
    const calls = renderPanel({ initial: [ROW] });
    fireEvent.click(screen.getByRole("button", { name: "Saved searches (1)" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete Health Briefs" }));
    expect(calls.remove).not.toHaveBeenCalled();
    const dialog = document.querySelector("dialog")!;
    expect(dialog.textContent).toContain("Health Briefs goes, and so do its alerts.");
    await act(async () => fireEvent.click(dialog.querySelector("[data-dialog-confirm]")!));
    expect(calls.remove).toHaveBeenCalledWith("s1");
    expect(screen.queryByRole("link", { name: "Health Briefs" })).toBeNull();
    expect(document.querySelector("[data-saved-empty]")).not.toBeNull();
  });
});

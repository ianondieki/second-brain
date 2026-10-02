import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { PitchForm, type PitchFormProps } from "./PitchForm";
import { leadWith } from "./order";
import { MAX_BATCH, parsePickerQuery, pitchHref } from "./picker";

// REQ-DIR-05 (P19-F §F-B): an idea started from an organisation's Problem Brief pitches with that organisation chosen
// first (`?org=`), and the page says so; it is a choice like any other, shown by name before anything is sent.

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));

afterEach(cleanup);

const PROPOSAL = "0199a000-0000-7000-8000-0000000000aa";
const TELCO = "0199a000-0000-7000-8000-00000000000a";
const SACCO = "0199a000-0000-7000-8000-00000000000b";

describe("the picker's ?org=", () => {
  it("chooses the Brief's organisation first, once, in lower case", () => {
    expect(parsePickerQuery({ org: TELCO.toUpperCase(), sel: [SACCO, TELCO] })).toEqual({
      org: TELCO,
      selected: [TELCO, SACCO],
    });
    expect(parsePickerQuery({ org: "not-an-id" })).toEqual({ selected: [] });
  });

  it("still keeps at most one batch", () => {
    const many = Array.from({ length: 25 }, (_, i) => `0199a000-0000-7000-8000-${String(i + 100).padStart(12, "0")}`);
    const query = parsePickerQuery({ org: TELCO, sel: many });
    expect(query.selected).toHaveLength(MAX_BATCH);
    expect(query.selected[0]).toBe(TELCO);
  });

  it("is carried by the idea page's Pitch link", () => {
    expect(pitchHref(PROPOSAL, { selected: [], org: TELCO })).toBe(`/dev/ideas/${PROPOSAL}/pitch?org=${TELCO}`);
    expect(pitchHref(PROPOSAL, { selected: [], org: undefined })).toBe(`/dev/ideas/${PROPOSAL}/pitch`);
  });
});

describe("a pitch started from a Brief", () => {
  function renderForm(overrides: Partial<PitchFormProps> = {}) {
    const props: PitchFormProps = {
      proposalId: PROPOSAL,
      ideaHref: `/dev/ideas/${PROPOSAL}`,
      cap: { used: 0, limit: 5, plan: "dev_free" },
      groups: [
        {
          key: "ict",
          name: "ICT › Networks & Telecommunications",
          rows: [
            { id: TELCO, name: "Telco A (fixture)", available: true, about: null, outcome: <p>Gets it now</p> },
            { id: SACCO, name: "SACCO B (fixture)", available: true, about: null, outcome: <p>Gets it now</p> },
          ],
        },
      ],
      initialSelected: [TELCO],
      preselected: { id: TELCO, name: "Telco A (fixture)" },
      filters: <input aria-label="Search by name, niche or county" name="q" />,
      narrowed: false,
      ...overrides,
    };
    return renderWithIntl(<PitchForm {...props} />);
  }

  it("ticks the organisation and says why", () => {
    renderForm();
    expect((screen.getByRole("checkbox", { name: /Telco A \(fixture\)/ }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("checkbox", { name: /SACCO B \(fixture\)/ }) as HTMLInputElement).checked).toBe(false);
    expect(document.querySelector("[data-preselected]")?.textContent).toBe(
      "Telco A (fixture) is already chosen: your idea answers its Brief. Untick it if you would rather not pitch to them.",
    );
    expect(document.querySelectorAll("[data-primary]").length).toBeLessThanOrEqual(1);
  });

  it("says it only while the organisation stays chosen", () => {
    renderForm();
    fireEvent.click(screen.getByRole("checkbox", { name: /Telco A \(fixture\)/ }));
    expect(document.querySelector("[data-preselected]")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: /Telco A \(fixture\)/ }));
    expect(document.querySelector("[data-preselected]")).not.toBeNull();
  });

  it("says nothing when no organisation was chosen this way", () => {
    renderForm({ preselected: undefined, initialSelected: [] });
    expect(document.querySelector("[data-preselected]")).toBeNull();
  });
});

describe("the picker's order for a Brief", () => {
  const row = (id: string) => ({ id, name: id });
  const groups = [
    { key: "a", rows: [row("a1"), row("a2")] },
    { key: "b", rows: [row("b1"), row(TELCO), row("b3")] },
    { key: "c", rows: [row("c1")] },
  ];

  it("lists the pre-chosen organisation first, its group first, the rest in their order", () => {
    expect(leadWith(groups, TELCO).map((g) => [g.key, g.rows.map((r) => r.id)])).toEqual([
      ["b", [TELCO, "b1", "b3"]],
      ["a", ["a1", "a2"]],
      ["c", ["c1"]],
    ]);
    expect(groups[1].rows.map((r) => r.id)).toEqual(["b1", TELCO, "b3"]); // the input is left as it was
  });

  it("leaves the order alone without ?org= or when the organisation is not on the page", () => {
    expect(leadWith(groups, undefined)).toEqual(groups);
    expect(leadWith(groups, "0199a000-0000-7000-8000-0000000000ff")).toEqual(groups);
  });
});

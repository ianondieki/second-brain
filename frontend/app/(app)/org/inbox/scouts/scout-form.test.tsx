import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { Preview, Scout, ScoutPlan } from "../../scout";
import type { Outcome, ScoutCalls } from "./calls";
import { ScoutForm } from "./ScoutForm";

// REQ-SCOUT-01 (docs/spec/06 6.8, AC-SCOUT-5, AC-SCOUT-7): the scout is a form; Preview shows what it would match
// with the on_new note; Save sends the API's ScoutForm; a 402 links to the next plan up's checkout (upgradeHref).

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  push.mockReset();
  refresh.mockReset();
});

const ORG = "0192a7c4-5b1e-7c3d-8e9f-0a1b2c3d4e5f";
const PARENT = "0192a7c4-0000-7000-8000-0000000000a0";
const CHILD = "0192a7c4-0000-7000-8000-0000000000a1";
const REVIEWER = "0192a7c4-0000-7000-8000-0000000000c1";
const PLAN: ScoutPlan = { plan: "org_claimed", scout_agents: 1, frequencies: ["weekly"], digest_size: 3 };

const PREVIEW: Preview = {
  items: [
    {
      proposal_id: "p1",
      owner_handle: "jacaranda-otter-17",
      published_at: "2026-09-29T08:00:00Z",
      teaser: {
        title: "Maziwa baridi",
        niche: { id: CHILD, slug: "microfinance-saccos", label: "Financial services › Microfinance & SACCOs" },
        country: "KE",
        county_code: "KE-47",
        maturity: "mvp",
        ask: "pilot",
        problem_statement: null,
        impact_claims: null,
        summary: null,
      },
      score: 80,
      why: "Matched on sacco and the niche.",
      keywords_found: ["sacco"],
    },
  ],
  total: 1,
  window_days: 30,
  digest_size: 3,
  note: "Shows what the last 30 days would have matched; this scout sends new proposals only.",
};

function calls(overrides: Partial<ScoutCalls> = {}): ScoutCalls {
  return {
    preview: vi.fn(async () => ({ ok: true as const, value: PREVIEW })),
    create: vi.fn(async () => ({ ok: true as const, value: { id: "s1" } as Scout })),
    update: vi.fn(async () => ({ ok: true as const, value: { id: "s1" } as Scout })),
    ...overrides,
  };
}

function renderForm(scoutCalls: ScoutCalls, scout?: Scout) {
  return renderWithIntl(
    <ScoutForm
      orgId={ORG}
      orgName="Maziwa Buyers"
      scout={scout}
      plan={PLAN}
      niches={[{ id: PARENT, name: "Financial services", children: [{ id: CHILD, name: "Microfinance & SACCOs" }] }]}
      counties={[{ id: "KE-47", label: "Nairobi" }]}
      reviewers={[{ id: REVIEWER, label: "Rita Wanjiru" }]}
      doneHref="/org/inbox?tab=matches"
      hereHref="/org/inbox/scouts/new"
      calls={scoutCalls}
    />,
  );
}

async function submit() {
  await act(async () => fireEvent.submit(document.querySelector("[data-scout-form]")!));
}

describe("the scout form", () => {
  it("asks for a niche before anything is sent, and focuses it", async () => {
    const api = calls();
    renderForm(api);
    await submit();
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByText(en.scoutForm.error.nichesRequired)).toBeTruthy();
    expect(document.activeElement?.id).toBe("scout-niches");
  });

  it("marks the frequencies the plan lacks, and keeps one primary action", () => {
    renderForm(calls());
    const onNew = screen.getByLabelText(/As soon as a proposal is published/);
    expect(onNew.closest("label")!.textContent).toContain(en.scoutForm.notOnPlan);
    expect(screen.getByLabelText(/Every week/).closest("label")!.textContent).not.toContain(en.scoutForm.notOnPlan);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
  });

  it("saves the API's ScoutForm with the chosen reviewer and goes to the matches", async () => {
    const api = calls();
    renderForm(api);
    fireEvent.click(screen.getByLabelText("Microfinance & SACCOs"));
    fireEvent.change(screen.getByLabelText(en.scoutForm.include), { target: { value: "SACCO, loans" } });
    fireEvent.click(screen.getByLabelText("Rita Wanjiru"));
    await submit();
    expect(api.create).toHaveBeenCalledWith(ORG, {
      niches: [CHILD],
      counties: [],
      include_keywords: ["sacco", "loans"],
      exclude_keywords: [],
      maturity: [],
      min_fit: 60,
      frequency: "weekly",
      language: "en",
      recipients: [REVIEWER],
    });
    expect(push).toHaveBeenCalledWith("/org/inbox?tab=matches");
  });

  it("links a 402 to the checkout of the next plan up, coming back here", async () => {
    const refused: Outcome<Scout> = { ok: false, refusal: "planLimit", upgradePlan: "org_growth" };
    renderForm(calls({ create: vi.fn(async () => refused) }));
    fireEvent.click(screen.getByLabelText("Financial services"));
    fireEvent.click(screen.getByLabelText(/As soon as a proposal is published/));
    await submit();
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(en.scoutForm.refusal.planLimit)).toBeTruthy();
    const link = within(alert).getByRole("link", { name: en.scoutForm.upgrade });
    expect(link.getAttribute("href")).toBe(
      `/billing/upgrade?plan=org_growth&org=${ORG}&next=%2Forg%2Finbox%2Fscouts%2Fnew`,
    );
    expect(push).not.toHaveBeenCalled();
  });

  it("shows Preview with the on_new note and the handle, saving nothing", async () => {
    const api = calls();
    renderForm(api);
    fireEvent.click(screen.getByLabelText("Microfinance & SACCOs"));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: en.scoutForm.preview })));
    expect(api.create).not.toHaveBeenCalled();
    const preview = document.querySelector("[data-preview]")!;
    expect(preview.querySelector("[data-preview-note]")!.textContent).toBe(
      "Shows what the last 30 days would have matched; this scout sends new proposals only.",
    );
    expect(preview.textContent).toContain("By jacaranda-otter-17");
    expect(preview.textContent).toContain("Matching proposals from the last 30 days: 1.");
    expect(document.activeElement?.id).toBe("preview-heading");
  });

  it("pauses a saved scout and refreshes", async () => {
    const api = calls();
    const scout = {
      id: "s1",
      niches: [{ id: CHILD, slug: "x", label: "x" }],
      counties: [],
      include_keywords: [],
      exclude_keywords: [],
      maturity: [],
      min_fit: 60,
      frequency: "weekly",
      language: "en",
      recipients: [],
      paused: false,
    } as unknown as Scout;
    renderForm(api, scout);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: en.scoutForm.pause })));
    expect(api.update).toHaveBeenCalledWith(ORG, "s1", { paused: true });
    expect(refresh).toHaveBeenCalled();
  });
});

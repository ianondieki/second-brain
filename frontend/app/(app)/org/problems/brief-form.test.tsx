import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { BAND, BRIEF_ID, brief, NICHE, ORG_ID, ORG_NAME } from "@/test/briefs";
import { renderWithIntl } from "@/test/intl";

import type { Refused } from "../brief-draft";
import { CloseBrief } from "./[id]/CloseBrief";
import type { BriefCalls } from "./calls";
import { BriefForm } from "./new/BriefForm";

// REQ-DIR-05 (docs/spec/06 6.2 last bullet; docs/spec/07 items 2, 4, 6): "Post a brief" checks its fields before
// anything is sent, sends the API's BriefIn, opens the list once posted, and words every refusal (402 with the next
// plan up, 403 verification or role, 422 fields or visibility) in one sentence with at most one action; "Close this
// brief" confirms first and reads the page again.

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  push.mockReset();
  refresh.mockReset();
});

const TODAY = "2026-10-02";
const DONE = "/org/problems?posted=1";
const HERE = "/org/problems/new";

function refused(refusal: Refused["refusal"], extra: Partial<Refused> = {}): Refused {
  return { ok: false, refusal, upgradePlan: null, limit: null, fields: [], ...extra };
}

function calls(overrides: Partial<BriefCalls> = {}): BriefCalls {
  return {
    create: vi.fn(async () => ({ ok: true as const, value: brief() })),
    close: vi.fn(async () => ({ ok: true as const, value: brief({ state: "closed", status: "closed" }) })),
    ...overrides,
  };
}

function renderForm(api: BriefCalls) {
  return renderWithIntl(
    <BriefForm
      orgId={ORG_ID}
      orgName={ORG_NAME}
      niches={[{ id: "parent-ict", name: "ICT", children: [{ id: NICHE.id, name: "Networks & Telecommunications" }] }]}
      counties={[{ id: "KE-30", label: "Nairobi City" }]}
      bands={[BAND]}
      today={TODAY}
      planLimit={1}
      planNames={{ org_starter: "Starter" }}
      doneHref={DONE}
      hereHref={HERE}
      cancelHref="/org/problems"
      calls={api}
    />,
  );
}

function fill() {
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Tower sites go dark when fuel runs out" } });
  fireEvent.change(screen.getByLabelText("Problem statement"), {
    target: { value: "Field teams learn about empty generator tanks only after the site stops working." },
  });
  fireEvent.change(screen.getByLabelText("Niche"), { target: { value: NICHE.id } });
}

async function submit() {
  await act(async () => fireEvent.submit(document.querySelector("[data-brief-form]")!));
}

describe("the brief form", () => {
  it("has one primary action, the quiet note on invited Briefs and a statement meter", () => {
    renderForm(calls());
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Post the brief" }).hasAttribute("data-primary")).toBe(true);
    expect(document.querySelector("[data-invited-note]")?.textContent).toBe(en.briefForm.invitedNote);
    fireEvent.change(screen.getByLabelText("Problem statement"), { target: { value: "Generators run dry" } });
    expect(document.querySelector("[data-meter]")?.textContent).toBe("Words: 3 of 120. Characters: 18 of 1200.");
    // The budget bands as radio cards, with "No band yet" chosen until one is.
    expect((screen.getByLabelText(/No band yet/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByLabelText(BAND.label)).toBeTruthy();
    expect(screen.getByLabelText(/Proposals wanted by/).getAttribute("min")).toBe(TODAY);
  });

  it("asks for the title, the statement and the niche before anything is sent, and focuses the first", async () => {
    const api = calls();
    renderForm(api);
    await submit();
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByText(en.briefForm.error.titleRequired)).toBeTruthy();
    expect(screen.getByText(en.briefForm.error.statementRequired)).toBeTruthy();
    expect(screen.getByText(en.briefForm.error.nicheRequired)).toBeTruthy();
    expect(document.activeElement?.id).toBe("brief-title");
    expect(screen.queryByRole("alert")).toBeNull(); // the fields say it; no refusal above the button
  });

  it("refuses a statement over 1,200 characters and a past deadline, with the limit in words", async () => {
    const api = calls();
    renderForm(api);
    fill();
    fireEvent.change(screen.getByLabelText("Problem statement"), { target: { value: "x".repeat(1201) } });
    fireEvent.change(screen.getByLabelText(/Proposals wanted by/), { target: { value: "2026-10-01" } });
    await submit();
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByText("Keep this to 1200 characters or fewer.")).toBeTruthy();
    expect(screen.getByText(en.briefForm.error.deadlinePast)).toBeTruthy();
    expect(document.activeElement?.id).toBe("brief-statement");
    expect(document.querySelector("[data-meter]")?.className).toContain("text-error");
  });

  it("refuses a statement over 120 words with the meter and the field's sentence", async () => {
    const api = calls();
    renderForm(api);
    fill();
    fireEvent.change(screen.getByLabelText("Problem statement"), { target: { value: Array(121).fill("dry").join(" ") } });
    const meter = document.querySelector("[data-meter]")!;
    expect(meter.textContent).toBe("Words: 121 of 120. Characters: 483 of 1200.");
    expect(meter.className).toContain("text-error");
    await submit();
    expect(api.create).not.toHaveBeenCalled();
    expect(screen.getByText("Keep this to 120 words or fewer.")).toBeTruthy();
    expect(document.activeElement?.id).toBe("brief-statement");
  });

  it("words the API's too_long on a statement within its characters as too many words", async () => {
    renderForm(calls({ create: vi.fn(async () => refused("invalid", { fields: [{ field: "statement", code: "too_long" }] })) }));
    fill();
    await submit();
    expect(screen.getByText("Keep this to 120 words or fewer.")).toBeTruthy();
  });

  it("posts the API's BriefIn and opens the list with the new Brief first", async () => {
    const api = calls();
    renderForm(api);
    fill();
    fireEvent.change(screen.getByLabelText("Who is affected (optional)"), { target: { value: "Rural subscribers" } });
    fireEvent.change(screen.getByLabelText("County"), { target: { value: "KE-30" } });
    fireEvent.click(screen.getByLabelText(BAND.label));
    fireEvent.change(screen.getByLabelText(/Proposals wanted by/), { target: { value: "2026-11-30" } });
    await submit();
    expect(api.create).toHaveBeenCalledWith(ORG_ID, {
      title: "Tower sites go dark when fuel runs out",
      statement: "Field teams learn about empty generator tanks only after the site stops working.",
      affected_group: "Rural subscribers",
      niche_id: NICHE.id,
      county_code: "KE-30",
      budget_band: BAND.code,
      deadline: "2026-11-30",
      visibility: "public",
    });
    expect(push).toHaveBeenCalledWith(DONE);
  });

  it("names the next plan up for a 402 and links to its checkout, coming back here", async () => {
    renderForm(calls({ create: vi.fn(async () => refused("planLimit", { upgradePlan: "org_starter", limit: 1 })) }));
    fill();
    await submit();
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("[data-refusal]")?.textContent).toBe(
      "Open Briefs on your plan: 1, all in use. Close one, or move to Starter to post more.",
    );
    const links = within(alert).getAllByRole("link");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe(`/billing/upgrade?plan=org_starter&org=${ORG_ID}&next=%2Forg%2Fproblems%2Fnew`);
    expect(document.activeElement).toBe(alert);
    expect(push).not.toHaveBeenCalled();
  });

  it("says a 402 at the top of the ladder without a way to buy more", async () => {
    renderForm(calls({ create: vi.fn(async () => refused("planLimit", { limit: 5 })) }));
    fill();
    await submit();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Open Briefs on your plan: 5, all in use. Close one to post another.");
    expect(within(alert).queryAllByRole("link")).toHaveLength(0);
  });

  it.each([
    ["verification", `${ORG_NAME} can post Briefs once its legal verification is complete.`],
    ["forbidden", `Only an owner, admin, signatory or reviewer of ${ORG_NAME} can post or close a Brief.`],
    ["visibility", en.briefForm.refusal.visibility],
    ["dailyLimit", en.briefForm.refusal.dailyLimit],
    ["orgUnavailable", en.briefForm.refusal.orgUnavailable],
    ["mfaSetup", en.briefForm.refusal.mfaSetup],
    ["mfaCode", en.briefForm.refusal.mfaCode],
    ["network", en.briefForm.refusal.network],
    ["generic", en.briefForm.refusal.generic],
  ] as const)("words a %s refusal in one sentence with no action", async (refusal, sentence) => {
    renderForm(calls({ create: vi.fn(async () => refused(refusal)) }));
    fill();
    await submit();
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("[data-refusal]")?.textContent).toBe(sentence);
    expect(within(alert).queryAllByRole("link")).toHaveLength(0);
    expect(alert.textContent).not.toContain("never shown");
  });

  it("marks the fields a 422 refused with their own words and focuses the first", async () => {
    const api = calls({
      create: vi.fn(async () =>
        refused("invalid", {
          fields: [
            { field: "statement", code: "contains_phone" },
            { field: "band", code: "unknown_budget_band" },
          ],
        }),
      ),
    });
    renderForm(api);
    fill();
    await submit();
    expect(screen.getByText(en.briefForm.fieldError.contains_phone)).toBeTruthy();
    expect(screen.getByText(en.briefForm.fieldError.unknown_budget_band)).toBeTruthy();
    expect(screen.getByRole("alert").querySelector("[data-refusal]")?.textContent).toBe(en.briefForm.refusal.invalid);
    await waitFor(() => expect(document.activeElement?.id).toBe("brief-statement"));
    // Changing the field clears its mark.
    fireEvent.change(screen.getByLabelText("Problem statement"), { target: { value: "Generators run dry at night." } });
    expect(screen.queryByText(en.briefForm.fieldError.contains_phone)).toBeNull();
  });
});

describe("closing a Brief", () => {
  function renderClose(api: BriefCalls) {
    // jsdom has no <dialog> methods: open and close as the browser would.
    HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
    return renderWithIntl(<CloseBrief orgId={ORG_ID} briefId={BRIEF_ID} orgName={ORG_NAME} calls={api} />);
  }

  it("is a secondary button that confirms what closing does before anything happens", () => {
    const api = calls();
    renderClose(api);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Close this brief" }));
    expect(api.close).not.toHaveBeenCalled();
    const dialog = document.querySelector("dialog")!;
    expect(dialog.hasAttribute("open")).toBe(true);
    expect(dialog.hasAttribute("data-sheet")).toBe(true); // a bottom sheet on phones
    expect(within(dialog).getByText(en.briefForm.close.body)).toBeTruthy();
    expect(document.activeElement?.textContent).toBe("Keep it open"); // Cancel, the choice that changes nothing
  });

  it("closes it and reads the page again", async () => {
    const api = calls();
    renderClose(api);
    fireEvent.click(screen.getByRole("button", { name: "Close this brief" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Close the brief" })));
    expect(api.close).toHaveBeenCalledWith(ORG_ID, BRIEF_ID);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reads the page again when someone closed it meanwhile (409)", async () => {
    renderClose(calls({ close: vi.fn(async () => refused("closed")) }));
    fireEvent.click(screen.getByRole("button", { name: "Close this brief" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Close the brief" })));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("says a Brief still in review cannot be closed yet (409 brief_not_published)", async () => {
    renderClose(calls({ close: vi.fn(async () => refused("notPublished")) }));
    fireEvent.click(screen.getByRole("button", { name: "Close this brief" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Close the brief" })));
    expect(within(document.querySelector("dialog")!).getByRole("alert").textContent).toContain(
      en.briefForm.refusal.notPublished,
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("keeps any other refusal in the dialog, in words", async () => {
    renderClose(calls({ close: vi.fn(async () => refused("forbidden")) }));
    fireEvent.click(screen.getByRole("button", { name: "Close this brief" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Close the brief" })));
    const dialog = document.querySelector("dialog")!;
    expect(within(dialog).getByRole("alert").textContent).toContain(
      `Only an owner, admin, signatory or reviewer of ${ORG_NAME} can post or close a Brief.`,
    );
    expect(refresh).not.toHaveBeenCalled();
  });
});

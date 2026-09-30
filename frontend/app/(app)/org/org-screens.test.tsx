import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { InboxItem } from "./data";
import { EmptyState } from "./EmptyState";
import { InboxRow } from "./inbox/InboxRow";
import { NdaAccept } from "./inbox/[proposalId]/NdaAccept";
import { StepUp } from "./inbox/[proposalId]/StepUp";
import type { Membership } from "./membership";
import { OrgPicker } from "./OrgPicker";

const mocks = vi.hoisted(() => ({ post: vi.fn(), replace: vi.fn(), refresh: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: mocks.replace, refresh: mocks.refresh }),
}));
vi.mock("@/lib/api/client", () => ({ api: { POST: (...args: unknown[]) => mocks.post(...args) } }));

afterEach(cleanup);
beforeEach(() => {
  mocks.post.mockReset();
  mocks.replace.mockReset();
  mocks.refresh.mockReset();
});

function answer(status: number, code?: string) {
  const error = code ? { detail: { code, message: "server text, never shown" } } : undefined;
  return { data: status < 300 ? {} : undefined, error, response: new Response(null, { status }) };
}

const ORG = "01a0ee62-0000-7000-8000-00000000000a";
const PROPOSAL = "01a0ee62-f783-733e-9321-9f34ec389ac2";
const SHA = "f0b8733eb8366e8f3f325686f1cc53c8ed7584c70c85dc7671522ffdaf01ad65";
const ORG_NAME = "Amani Foods";

function renderNda() {
  return renderWithIntl(
    <NdaAccept
      orgId={ORG}
      proposalId={PROPOSAL}
      templateId="01a0ee5e-69b3-71cd-8bb7-36281a854e93"
      sha256={SHA}
      noticeVersion="v1"
      viewHref={`/org/inbox/${PROPOSAL}?view=full`}
      inboxHref="/org/inbox"
      orgName={ORG_NAME}
    />,
  );
}

async function accept() {
  const button = screen.getByRole("button", { name: "Accept and view" });
  await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false)); // SubmitButton waits for hydration
  fireEvent.click(button);
}

describe("NdaAccept (REQ-REPO-01)", () => {
  it("is the step's one primary action and accepts exactly what was shown, then opens the marked page", async () => {
    mocks.post.mockResolvedValue(answer(201));
    const { container } = renderNda();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    await accept();
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith(`/org/inbox/${PROPOSAL}?view=full`));
    expect(mocks.post).toHaveBeenCalledWith("/api/orgs/{org_id}/proposals/{proposal_id}/nda", {
      params: { path: { org_id: ORG, proposal_id: PROPOSAL } },
      body: { template_id: "01a0ee5e-69b3-71cd-8bb7-36281a854e93", sha256: SHA, logging_notice_version: "v1" },
    });
  });

  it("treats a repeated acceptance (200) like a new one", async () => {
    mocks.post.mockResolvedValue(answer(200));
    renderNda();
    await accept();
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledTimes(1));
  });

  it("says a newer NDA was published and offers the new version instead of accepting it unseen", async () => {
    mocks.post.mockResolvedValue(answer(409, "nda_outdated"));
    renderNda();
    await accept();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(en.orgProposal.refusal.nda_outdated);
    expect(alert.textContent).not.toContain("server text");
    expect(mocks.replace).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Show the new version" }));
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it.each([
    ["grant_required", 403, "The developer has not shared the full proposal with Amani Foods.", "Back to the Inbox"],
    ["mfa_required", 401, en.orgProposal.refusal.mfa_required, "Enter your code"],
    ["master_terms_required", 403, en.orgProposal.refusal.master_terms_required.replace("{org}", ORG_NAME), null],
  ])("names the refusal %s in its own sentence with at most one action", async (code, status, sentence, action) => {
    mocks.post.mockResolvedValue(answer(status, code));
    renderNda();
    await accept();
    const alert = await screen.findByRole("alert");
    expect(alert.querySelector("[data-refusal]")?.textContent).toBe(sentence);
    const actions = alert.querySelectorAll("a, button");
    expect(actions).toHaveLength(action ? 1 : 0);
    if (action) expect(actions[0].textContent).toBe(action);
  });

  it("answers a dropped connection with the generic sentence and a retry", async () => {
    mocks.post.mockRejectedValue(new TypeError("Failed to fetch"));
    renderNda();
    await accept();
    expect((await screen.findByRole("alert")).textContent).toContain(en.orgProposal.refusal.generic);
    screen.getByRole("button", { name: "Try again" });
    expect(screen.getByRole("button", { name: "Accept and view" }).hasAttribute("aria-disabled")).toBe(false);
  });
});

describe("StepUp", () => {
  it("confirms a fresh code, then fetches the page again", async () => {
    mocks.post.mockResolvedValue(answer(200));
    renderWithIntl(<StepUp />);
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "123 456" } });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(confirm);
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1));
    expect(mocks.post).toHaveBeenCalledWith("/api/auth/step-up", { body: { code: "123456" } });
  });

  it("keeps a wrong code next to the field", async () => {
    mocks.post.mockResolvedValue(answer(401, "invalid_code"));
    renderWithIntl(<StepUp />);
    fireEvent.change(screen.getByLabelText("Code from your app"), { target: { value: "000000" } });
    const confirm = screen.getByRole("button", { name: "Confirm" });
    await waitFor(() => expect((confirm as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(confirm);
    await screen.findByText(en.orgProposal.stepUpInvalid);
    expect(mocks.refresh).not.toHaveBeenCalled();
  });
});

describe("OrgPicker", () => {
  const A: Membership = { org_id: ORG, org_name: ORG_NAME, roles: ["reviewer"] };
  const B: Membership = { org_id: "01a0ee62-0000-7000-8000-00000000000b", org_name: "Baraka Bank", roles: ["admin"] };

  it("is not shown to a member of one organisation", () => {
    const { container } = renderWithIntl(<OrgPicker memberships={[A]} current={A.org_id} action="/org/inbox" />);
    expect(container.innerHTML).toBe("");
  });

  it("lets a member of several pick one with a plain GET form", () => {
    const { container } = renderWithIntl(<OrgPicker memberships={[A, B]} current={B.org_id} action="/org/inbox" />);
    const form = container.querySelector("form")!;
    expect(form.getAttribute("method")).toBe("get");
    expect(form.getAttribute("action")).toBe("/org/inbox");
    const select = screen.getByLabelText("Organisation") as HTMLSelectElement;
    expect(select.name).toBe("org");
    expect(select.value).toBe(B.org_id);
    expect([...select.options].map((o) => o.textContent)).toEqual([ORG_NAME, "Baraka Bank"]);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
  });
});

describe("InboxRow (Tier 1 only)", () => {
  const item: InboxItem = {
    tag_id: "01a0ee62-f836-71e7-8a6c-fb437b204df6",
    pitched_at: "2026-09-29T18:17:38Z",
    engagement: { id: "01a0ee62-f839-719d-8432-0d3a82415fe0", state: "SUBMITTED", stage_deadline_at: null },
    proposal: {
      id: PROPOSAL,
      owner_handle: "dev-7k2m9qxp",
      cert_id: "0F2DRAHDCRSMY6CP",
      version_no: 1,
      published_at: "2026-09-29T18:17:38Z",
      teaser: {
        title: "Maziwa baridi",
        niche: { id: "01a0ee5e-695d-72fc-b10b-f8e66d1aec5b", slug: "dairy", label: "Agriculture › Dairy" },
        country: "KE",
        county_code: "KE-47",
        maturity: "prototype",
        ask: "pilot",
        problem_statement: "Milk spoils.",
        impact_claims: null,
        summary: "Shared solar chillers booked by SMS.",
      },
    },
  };

  it("shows the title as a link, the niche, when it was sent, and at most two chips", () => {
    const { container } = renderWithIntl(<InboxRow item={item} href={`/org/inbox/${PROPOSAL}`} />);
    expect(screen.getByRole("link", { name: "Maziwa baridi" }).getAttribute("href")).toBe(`/org/inbox/${PROPOSAL}`);
    screen.getByText("Agriculture › Dairy");
    screen.getByText(/^Sent 29 Sept? 2026$/);
    screen.getByText("Prototype");
    screen.getByText("Wants to run a pilot");
    expect(container.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2); // docs/spec/07 item 2
    expect(container.querySelector("[data-chip]")?.textContent).toBe("New");
  });

  it("links the stage chip to the engagement's tracker (REQ-ENG-03), keeping the chosen organisation", () => {
    const href = `/org/engagements/${item.engagement!.id}?org=01a0ee62-0000-7000-8000-000000000001`;
    const { container } = renderWithIntl(<InboxRow item={item} href="/x" trackerHref={href} />);
    const chip = container.querySelector("[data-chip='stage']")!;
    expect(chip.tagName).toBe("A");
    expect(chip.getAttribute("href")).toBe(href);
    expect(screen.getByRole("link", { name: "New" })).toBe(chip);
  });

  it("names the stage once the organisation has moved it, and 'New' before an engagement exists", () => {
    const moved = { ...item, engagement: { ...item.engagement!, state: "DECLINED" as const } };
    const { container, unmount } = renderWithIntl(<InboxRow item={moved} href="/x" />);
    expect(container.querySelector("[data-chip]")?.textContent).toBe("Declined");
    unmount();
    const fresh = renderWithIntl(<InboxRow item={{ ...item, engagement: null }} href="/x" />);
    expect(fresh.container.querySelector("[data-chip]")?.textContent).toBe("New");
  });
});

describe("EmptyState (AC-UX-5)", () => {
  it("is one sentence and one action", () => {
    const { container } = renderWithIntl(<EmptyState sentence="Nothing yet." action="Back to home" href="/org" />);
    const empty = container.querySelector("[data-empty-state]")!;
    expect(empty.querySelectorAll("p")).toHaveLength(1);
    expect(empty.querySelectorAll("a")).toHaveLength(1);
    expect(empty.querySelectorAll("[data-primary]")).toHaveLength(0);
  });
});

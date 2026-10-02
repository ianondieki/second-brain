import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { NextIntlClientProvider } from "next-intl";

import { ClientStrings, type StringTree } from "@/components/ClientStrings";
import { createApiClient } from "@/lib/api/client";
import en from "@/locales/en.json";
import { detail, inImplementation } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { Actions, type ActionsProps } from "./Actions";
import { refusalOf, runCommand, type CommandOutcome } from "./calls";
import { ContactReveal, mailto } from "./ContactReveal";
import { actionItems, type CommandRequest, type Detail } from "./model";

// REQ-ENG-03: the caller's buttons come only from the API's `actions`; each becomes the right request; the step-up
// (ADR-002) is asked inline and the step runs once more; a 409 or 404 refreshes the page and says so.

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

type Run = (request: CommandRequest) => Promise<CommandOutcome>;

function renderActions(engagement: Detail, props: Partial<Omit<ActionsProps, "runImpl">> & { runImpl?: Run } = {}) {
  const runImpl = vi.fn<Run>(props.runImpl ?? (async () => ({ ok: true })));
  const view = renderWithIntl(
    <Actions
      engagementId={engagement.id}
      lockVersion={engagement.lock_version}
      items={actionItems(engagement)}
      counterpart={engagement.my_party === "developer" ? engagement.org_name : engagement.developer_name}
      enrolled
      {...props}
      runImpl={runImpl}
    />,
  );
  return { ...view, runImpl };
}

const orgReview = () =>
  detail({ my_party: "org", my_roles: ["signatory"], actions: ["start_review", "decline"], lock_version: 4 });

describe("the action buttons", () => {
  it("shows one button per API action, the awaited one primary, and nothing the API did not list", () => {
    renderActions(orgReview());
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["Start the review", "Decline"]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Start the review" }).hasAttribute("data-primary")).toBe(true);
  });

  it("renders nothing for a party with no actions", () => {
    const { container } = renderActions(detail({ actions: [] }));
    expect(container.textContent).toBe("");
  });

  it("runs a step with the lock_version it read, then refreshes the tracker", async () => {
    const { runImpl } = renderActions(orgReview());
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start the review" })));
    expect(runImpl).toHaveBeenCalledWith({
      path: "/api/engagements/{engagement_id}/start-review",
      params: { engagement_id: orgReview().id },
      body: { lock_version: 4 },
    });
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toContain("Done. The tracker is up to date.");
  });

  it("asks before a step that ends the engagement", async () => {
    const engagement = detail({ actions: ["withdraw"], lock_version: 2 });
    const { runImpl } = renderActions(engagement);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(runImpl).not.toHaveBeenCalled();
    expect(screen.getByText(/Withdraw this proposal from Telco A \(fixture\)\?/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(runImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Withdraw" })));
    expect(runImpl).toHaveBeenCalledWith(expect.objectContaining({ path: "/api/engagements/{engagement_id}/withdraw" }));
  });

  it("puts a milestone's number on its button and sends its id", async () => {
    const engagement = inImplementation({ my_party: "org", actions: ["accept_milestone"], lock_version: 11 });
    const { runImpl } = renderActions(engagement);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Accept milestone 1" })));
    expect(runImpl).toHaveBeenCalledWith({
      path: "/api/engagements/{engagement_id}/milestones/{milestone_id}/accept",
      params: { engagement_id: engagement.id, milestone_id: engagement.agreements[0].milestones[0].id },
      body: { lock_version: 11 },
    });
  });
});

describe("the step-up for signatures, endorsements and payments (ADR-002)", () => {
  const signing = () =>
    detail({
      state: "NDA_PENDING",
      actions: ["sign_nda"],
      awaiting: [{ command: "sign_nda", party: "developer" }],
      whose_turn: ["developer"],
      lock_version: 6,
    });

  it("asks for a fresh code inline, then runs the same step once more", async () => {
    const outcomes: CommandOutcome[] = [{ ok: false, refusal: "stepUp", status: 403 }, { ok: true }];
    const runImpl = vi.fn<Run>(async () => outcomes.shift()!);
    const confirmImpl = vi.fn(async () => ({ ok: true as const }));
    renderActions(signing(), { runImpl, confirmImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    expect(screen.getByText("Confirm with the code from your authenticator app to continue.")).toBeTruthy();
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123 456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" })));
    expect(confirmImpl).toHaveBeenCalledWith("123456");
    expect(runImpl).toHaveBeenCalledTimes(2);
    expect(runImpl.mock.calls[1][0]).toEqual(runImpl.mock.calls[0][0]);
    expect(refresh).toHaveBeenCalled();
  });

  it("stops after one retry instead of asking again and again", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    renderActions(signing(), { runImpl, confirmImpl: async () => ({ ok: true }) });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" })));
    expect(runImpl).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("alert").textContent).toContain("Something went wrong");
    expect(screen.queryByLabelText("Authenticator code")).toBeNull();
  });

  it("keeps the form on a wrong code without retrying the step", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    renderActions(signing(), { runImpl, confirmImpl: async () => ({ ok: false, invalidCode: true }) });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "000000" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" })));
    expect(runImpl).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Enter the 6-digit code from your authenticator app.")).toBeTruthy();
  });

  it("keeps Cancel inert while the code is checked, and never runs the step once the form is gone", async () => {
    let settle: (value: { ok: true }) => void = () => {};
    const confirmImpl = vi.fn(() => new Promise<{ ok: true }>((resolve) => (settle = resolve)));
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    const { unmount } = renderActions(signing(), { runImpl, confirmImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    fireEvent.change(screen.getByLabelText("Authenticator code"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm and continue" })));
    const cancel = screen.getByRole("button", { name: "Cancel" });
    expect(cancel.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(cancel);
    expect(screen.getByLabelText("Authenticator code")).toBeTruthy(); // still open: Cancel did nothing
    unmount();
    await act(async () => settle({ ok: true }));
    expect(runImpl).toHaveBeenCalledTimes(1);
  });

  it("does not run the step after Cancel", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    renderActions(signing(), { runImpl, confirmImpl: async () => ({ ok: true }) });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Authenticator code")).toBeNull();
    expect(runImpl).toHaveBeenCalledTimes(1);
  });

  it("points to two-step sign-in when the account has none", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    renderActions(signing(), { runImpl, enrolled: false });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    expect(screen.getByRole("link", { name: "Turn on two-step sign-in" }).getAttribute("href")).toBe(
      "/settings/security",
    );
  });
});

describe("refusals", () => {
  it("refreshes a stale engagement (409) and says so", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stale", status: 409 }));
    renderActions(orgReview(), { runImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start the review" })));
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("This engagement changed since you opened it.");
  });

  it("refreshes a step that is no longer possible (409) or an engagement that is gone (404)", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "notFound", status: 404 }));
    renderActions(orgReview(), { runImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start the review" })));
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("no longer available to you");
  });

  it("words a 403 without refreshing", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "notAllowed", status: 403 }));
    renderActions(orgReview(), { runImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Start the review" })));
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("This step is not yours to take.");
  });

  it.each([
    [409, { detail: { code: "stale" } }, "stale"],
    [403, { detail: { code: "step_up_required" } }, "stepUp"],
    [403, { detail: { code: "d2_required" } }, "d2"],
    [409, { detail: { code: "payment_amount_mismatch" } }, "paymentMismatch"],
    [409, { detail: { code: "illegal_transition" } }, "conflict"],
    [403, { detail: { code: "not_found" } }, "notAllowed"],
    [404, { detail: { code: "not_found" } }, "notFound"],
    [422, { detail: [{ loc: ["body", "reason"], msg: "x", type: "y" }] }, "invalid"],
    [422, { detail: { code: "contains_contact" } }, "containsContact"],
    [422, { detail: { code: "invalid_note" } }, "invalidNote"],
    [422, { detail: { code: "invalid_resume_at" } }, "invalidResumeAt"],
    [409, { detail: { code: "info_request_limit" } }, "questionLimit"],
    [409, { detail: { code: "hold_limit" } }, "holdLimit"],
    [429, { detail: { code: "too_many_actions" } }, "tooMany"],
    [403, { detail: { code: "not_your_action" } }, "notAllowed"],
    [403, { detail: { code: "role_required" } }, "notAllowed"],
    [500, "oops", "generic"],
  ] as const)("maps %i %j to %s", (status, body, refusal) => {
    expect(refusalOf(status, body)).toBe(refusal);
  });
});

describe("forms for commands with a body", () => {
  it("records a payment in minor units after the form is filled in", async () => {
    const engagement = detail({
      my_party: "org",
      state: "PAYMENT_FINAL",
      actions: ["record_payment"],
      awaiting: [{ command: "record_payment", party: "org" }],
      lock_version: 20,
    });
    const { runImpl } = renderActions(engagement);
    fireEvent.click(screen.getByRole("button", { name: "Record the final payment" }));
    const amount = await screen.findByLabelText("Amount paid (KES)");
    fireEvent.click(screen.getByRole("button", { name: "Record the final payment" }));
    expect(screen.getByText("Enter an amount in shillings, for example 250000.")).toBeTruthy();
    expect(runImpl).not.toHaveBeenCalled();
    fireEvent.change(amount, { target: { value: "1,250,000" } });
    fireEvent.change(screen.getByLabelText("Reference (optional)"), { target: { value: "QK12ABC" } });
    fireEvent.change(screen.getByLabelText("Date paid"), { target: { value: "2026-09-28" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Record the final payment" })));
    expect(runImpl).toHaveBeenCalledWith({
      path: "/api/engagements/{engagement_id}/record-payment",
      params: { engagement_id: engagement.id },
      body: { amount_kes_minor: 125_000_000, method: "mpesa", reference: "QK12ABC", paid_on: "2026-09-28", lock_version: 20 },
    });
  });

  it("proposes terms with IP terms and milestones", async () => {
    const engagement = detail({ state: "NDA_SIGNED", actions: ["propose_terms"], lock_version: 8 });
    const { runImpl } = renderActions(engagement);
    fireEvent.click(screen.getByRole("button", { name: "Propose terms" }));
    fireEvent.change(await screen.findByLabelText("Intellectual property"), { target: { value: "revenue_share" } });
    fireEvent.change(screen.getByLabelText("Deliverable"), { target: { value: "Pilot at two co-ops" } });
    fireEvent.change(screen.getByLabelText("Amount (KES)"), { target: { value: "250000" } });
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-10-30" } });
    fireEvent.click(screen.getByRole("button", { name: "Add a milestone" }));
    expect(screen.getAllByLabelText("Deliverable")).toHaveLength(2);
    fireEvent.click(screen.getByRole("button", { name: "Remove milestone 2" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Propose terms" })));
    const request = runImpl.mock.calls[0][0] as CommandRequest;
    expect(request.path).toBe("/api/engagements/{engagement_id}/propose-terms");
    expect(request.body).toEqual({
      ip_terms: "revenue_share",
      deemed_acceptance_days: 0,
      exclusivity: null,
      milestones: [{ deliverable: "Pilot at two co-ops", amount_kes_minor: 25_000_000, due_date: "2026-10-30", review_window_bd: null }],
      lock_version: 8,
    });
  });

  it("declines with a written reason for OTHER, and keeps the form open when the API refuses it (422)", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "reasonText", status: 422 }));
    renderActions(orgReview(), { runImpl });
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    fireEvent.change(await screen.findByLabelText("Reason"), { target: { value: "OTHER" } });
    fireEvent.change(screen.getByLabelText("Explain the reason"), { target: { value: "Too early for us." } });
    // Fix round 1: an ending step submits as the danger button, never the primary one.
    const submit = within(document.querySelector("[data-command-form]") as HTMLElement).getByRole("button", {
      name: "Decline",
    });
    expect(submit.className).toContain("border-error");
    expect(submit.hasAttribute("data-primary")).toBe(false);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Decline" })));
    expect(runImpl.mock.calls[0][0]).toMatchObject({
      path: "/api/engagements/{engagement_id}/decline",
      body: { reason: "OTHER", other_text: "Too early for us.", internal_start_date: null, attested: false, lock_version: 4 },
    });
    expect(screen.getByRole("alert").textContent).toContain("Explain the reason in more detail.");
    expect(screen.getByLabelText("Explain the reason")).toBeTruthy();
  });

  it("says so when the organisation's members could not be read, instead of an empty list", async () => {
    const engagement = detail({ my_party: "org", state: "UNDER_REVIEW", actions: ["approve"], lock_version: 5 });
    const { runImpl } = renderActions(engagement, { members: null });
    fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" }));
    expect((await screen.findByRole("alert")).textContent).toContain("members did not load");
    expect(screen.queryByLabelText("Contact person")).toBeNull();
    expect(runImpl).not.toHaveBeenCalled();
  });

  it("clears a field's error as soon as the field changes", async () => {
    renderActions(orgReview());
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    await screen.findByLabelText("Reason");
    fireEvent.click(within(document.querySelector("[data-command-form]") as HTMLElement).getByRole("button", { name: "Decline" }));
    expect(screen.getByText("Fill in this field.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "BUDGET" } });
    expect(screen.queryByText("Fill in this field.")).toBeNull();
  });

  it("approves naming a contact person from the organisation's members", async () => {
    const engagement = detail({ my_party: "org", state: "UNDER_REVIEW", actions: ["approve", "decline"], lock_version: 5 });
    const { runImpl } = renderActions(engagement, {
      members: [
        { user_id: "u-rita", display_name: "Rita Wanjiru" },
        { user_id: "u-otieno", display_name: "Otieno Kamau" },
      ],
      myUserId: "u-rita",
    });
    fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" }));
    await waitFor(() => expect(screen.getByLabelText("Contact person")).toBeTruthy());
    fireEvent.change(screen.getByLabelText("Contact person"), { target: { value: "u-otieno" } });
    fireEvent.change(screen.getByLabelText("How they will make contact"), { target: { value: "phone" } });
    fireEvent.change(screen.getByLabelText("Contact by"), { target: { value: "2026-10-01" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Approve to proceed (non-binding)" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/approve",
      params: { engagement_id: engagement.id },
      body: { contact_user_id: "u-otieno", contact_channel: "phone", contact_by: "2026-10-01", lock_version: 5 },
    });
  });
});

describe("the calls", () => {
  it("send commands through the CSRF-aware typed client", async () => {
    const seen: Request[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const request = new Request(new URL(String(input instanceof Request ? input.url : input), "http://web.test"), init);
      seen.push(input instanceof Request ? input : request);
      if (request.url.endsWith("/api/auth/csrf")) return Response.json({ csrf_token: "tok" });
      return Response.json({}, { status: 200 });
    });
    const client = createApiClient({ baseUrl: "http://web.test", fetch: fetchImpl });
    const outcome = await runCommand(
      { path: "/api/engagements/{engagement_id}/sign-nda", params: { engagement_id: "e 1" }, body: { lock_version: 3 } },
      client,
    );
    expect(outcome).toEqual({ ok: true });
    const post = seen.find((r) => r.method === "POST")!;
    expect(post.url).toBe("http://web.test/api/engagements/e%201/sign-nda");
    expect(post.headers.get("X-CSRF-Token")).toBe("tok");
    expect(await post.clone().json()).toEqual({ lock_version: 3 });
  });

  it("settle a thrown fetch as a network refusal", async () => {
    const client = createApiClient({ fetch: async () => Promise.reject(new TypeError("offline")) });
    const outcome = await runCommand({ path: "/api/engagements/{engagement_id}/deliver", params: { engagement_id: "e1" }, body: { lock_version: 1 } }, client);
    expect(outcome).toEqual({ ok: false, refusal: "network", status: 0 });
  });
});

describe("the contact reveal", () => {
  it("shows the developer's verified email only when asked", async () => {
    const revealImpl = vi.fn(async () => ({
      ok: true as const,
      contact: { developer_name: "Achieng Otieno", email: "achieng@example.com", phone: null },
    }));
    renderWithIntl(<ContactReveal engagementId="e1" revealImpl={revealImpl} />);
    expect(revealImpl).not.toHaveBeenCalled();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Show the developer's contact details" })));
    expect(revealImpl).toHaveBeenCalledWith("e1");
    expect(screen.getByRole("link", { name: "achieng@example.com" }).getAttribute("href")).toBe("mailto:achieng@example.com");
  });

  it("moves focus to the details that replace the button (WCAG 2.4.3)", async () => {
    const revealImpl = vi.fn(async () => ({
      ok: true as const,
      contact: { developer_name: "Achieng Otieno", email: "achieng@example.com", phone: null },
    }));
    renderWithIntl(<ContactReveal engagementId="e1" revealImpl={revealImpl} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Show the developer's contact details" })));
    const details = document.querySelector("[data-contact-revealed]");
    expect(details).not.toBeNull();
    expect(document.activeElement).not.toBe(document.body);
    expect(document.activeElement).toBe(details?.parentElement);
    expect(document.activeElement?.getAttribute("tabindex")).toBe("-1");
  });

  it("links to the one address only, whatever characters the address holds", () => {
    expect(mailto("achieng@example.com")).toBe("mailto:achieng@example.com");
    expect(mailto("dev?cc=boss@example.com")).toBe("mailto:dev%3Fcc%3Dboss@example.com");
    expect(mailto("x?to=ceo%40corp.com&z=@evil.com")).toBe("mailto:x%3Fto%3Dceo%2540corp.com%26z%3D@evil.com");
  });
});

describe("focus follows the actions (WCAG 2.4.3)", () => {
  it("moves to a form's heading when it opens, and back to its button on Cancel", async () => {
    renderActions(detail({ my_party: "org", state: "UNDER_REVIEW", actions: ["approve", "decline"] }), {
      members: [{ user_id: "u1", display_name: "Rita Wanjiru" }],
      myUserId: "u1",
    });
    fireEvent.click(screen.getByRole("button", { name: "Decline" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Decline" }));
    await screen.findByLabelText("Reason");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Decline" }));
  });

  it("moves to a confirmation's heading, and back to Withdraw on Cancel", () => {
    renderActions(detail({ actions: ["withdraw"] }));
    fireEvent.click(screen.getByRole("button", { name: "Withdraw" }));
    expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Withdraw" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Withdraw" }));
  });

  it("moves to the code field when a step asks for a fresh code", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "stepUp", status: 403 }));
    renderActions(detail({ state: "NDA_PENDING", actions: ["sign_nda"] }), { runImpl });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sign the mutual NDA" })));
    expect(document.activeElement).toBe(screen.getByLabelText("Authenticator code"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Sign the mutual NDA" }));
  });

  it("moves to Add a milestone after a milestone is removed", async () => {
    renderActions(detail({ state: "NDA_SIGNED", actions: ["propose_terms"] }));
    fireEvent.click(screen.getByRole("button", { name: "Propose terms" }));
    fireEvent.click(await screen.findByRole("button", { name: "Add a milestone" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove milestone 2" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Add a milestone" }));
  });

  it("keeps Done, with focus, when the step leaves no buttons", async () => {
    const engagement = detail({ state: "PAYMENT_FINAL", actions: ["deliver"], lock_version: 7 });
    const { rerender } = renderActions(engagement);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Submit the final delivery" })));
    const done = screen.getByRole("status");
    expect(document.activeElement).toBe(done);
    // The refreshed page brings the engagement with no buttons left for this party.
    rerender(
      <NextIntlClientProvider locale="en" messages={en}>
        <ClientStrings strings={en as unknown as Record<string, StringTree>}>
          <Actions engagementId={engagement.id} lockVersion={8} items={[]} counterpart="Telco A (fixture)" enrolled />
        </ClientStrings>
      </NextIntlClientProvider>,
    );
    expect(screen.getByRole("status")).toBe(done);
    expect(document.activeElement).toBe(done);
    expect(document.querySelector("[data-actions]")).toBeNull();
  });
});

// REQ-ENG-10 part (docs/spec/06 6.9 side branches): the side states' sheets. Each opens over the tracker as a modal
// <dialog> (a bottom sheet on phones), sends its text with the lock_version the page read, keeps a refused text open
// with the refusal in words, and gives focus back to its button when closed.
describe("the side states' sheets", () => {
  beforeAll(() => {
    // jsdom implements <dialog> but not its modal methods.
    HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    };
    HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
      this.removeAttribute("open");
      this.dispatchEvent(new Event("close"));
    };
  });

  const question = { body: "Which co-ops ran the pilot?\nAnd for how long?", date: "1 Oct 2026" };
  const devAsked = () =>
    detail({
      state: "INFO_REQUESTED",
      paused_from: "UNDER_REVIEW",
      actions: ["answer_info", "withdraw"],
      awaiting: [{ command: "answer_info", party: "developer" }],
      whose_turn: ["developer"],
      lock_version: 6,
    });
  const orgReviewing = () =>
    detail({
      my_party: "org",
      my_roles: ["signatory"],
      state: "UNDER_REVIEW",
      actions: ["request_info", "pause", "approve", "decline"],
      awaiting: [{ command: "approve", party: "org" }],
      lock_version: 9,
    });
  const sheet = async () => (await screen.findByRole("dialog")) as HTMLDialogElement;

  it("answers the organisation's question: the awaited step, primary, with the question quoted and a counter", async () => {
    const { runImpl } = renderActions(devAsked(), { question });
    const answer = screen.getByRole("button", { name: "Answer the question" });
    expect(answer.hasAttribute("data-primary")).toBe(true);
    fireEvent.click(answer);
    const dialog = await sheet();
    expect(dialog.hasAttribute("data-sheet")).toBe(true); // the bottom sheet on phones (globals.css, D-52)
    expect(within(dialog).getByRole("heading", { name: "Answer the question" })).toBeTruthy();
    expect(within(dialog).getByText("Telco A (fixture) asked on 1 Oct 2026:")).toBeTruthy();
    expect(dialog.querySelector("[data-question]")?.textContent).toBe(question.body);
    const field = within(dialog).getByLabelText("Your answer");
    expect(document.activeElement).toBe(field);
    expect(field.getAttribute("maxlength")).toBe("2000");
    expect(within(dialog).getByText("0 of 2,000 characters")).toBeTruthy();
    // The send button is styled, not marked, as primary: the page keeps one data-primary.
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    fireEvent.click(within(dialog).getByRole("button", { name: "Send the answer" }));
    expect(within(dialog).getByText("Fill in this field.")).toBeTruthy();
    expect(runImpl).not.toHaveBeenCalled();
    const typed = "  Kipkelion and Olenguruone, six weeks.  ";
    fireEvent.change(field, { target: { value: typed } });
    expect(within(dialog).getByText(`${typed.length} of 2,000 characters`)).toBeTruthy();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the answer" })));
    expect(runImpl).toHaveBeenCalledWith({
      path: "/api/engagements/{engagement_id}/answer-info",
      params: { engagement_id: devAsked().id },
      body: { answer: "Kipkelion and Olenguruone, six weeks.", lock_version: 6 },
    });
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("Done. The tracker is up to date.");
  });

  it("asks a question for the organisation, naming the developer and the limits", async () => {
    const { runImpl } = renderActions(orgReviewing());
    const ask = screen.getByRole("button", { name: "Request information" });
    expect(ask.hasAttribute("data-primary")).toBe(false);
    fireEvent.click(ask);
    const dialog = await sheet();
    expect(dialog.textContent).toContain("Ask Achieng Otieno one question.");
    expect(dialog.textContent).toContain("they have ten business days");
    expect(dialog.textContent).toContain("two questions at this stage");
    expect(dialog.textContent).toContain("Keep contact details and links out");
    fireEvent.change(within(dialog).getByLabelText("Your question"), { target: { value: "Which co-ops?" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the question" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/request-info",
      params: { engagement_id: orgReviewing().id },
      body: { question: "Which co-ops?", lock_version: 9 },
    });
  });

  it("keeps a text with contact details open, the reason on the field, which keeps the focus (422 contains_contact)", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "containsContact", status: 422 }));
    renderActions(orgReviewing(), { runImpl });
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    const dialog = await sheet();
    fireEvent.change(within(dialog).getByLabelText("Your question"), { target: { value: "Call me on 0712 345 678" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the question" })));
    const field = within(dialog).getByLabelText("Your question") as HTMLTextAreaElement;
    const sentence =
      "Contact details stay out of the tracker until first contact is made; please remove the email, phone number or link.";
    expect(field.getAttribute("aria-invalid")).toBe("true");
    const described = (field.getAttribute("aria-describedby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent);
    expect(described).toContain(sentence);
    expect(document.activeElement).toBe(field);
    expect(within(dialog).queryByRole("alert")).toBeNull(); // said once, on the field
    expect(field.value).toBe("Call me on 0712 345 678");
    expect(refresh).not.toHaveBeenCalled();
    // Editing the text clears the refusal; the next attempt says it again.
    fireEvent.change(field, { target: { value: "Call me on 0712 345 679" } });
    expect(field.hasAttribute("aria-invalid")).toBe(false);
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the question" })));
    expect(field.getAttribute("aria-invalid")).toBe("true");
    expect(document.activeElement).toBe(field);
  });

  it("keeps a sheet open with what was typed when one party's steps per hour ran out (429)", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "tooMany", status: 429 }));
    renderActions(devAsked(), { runImpl, question });
    fireEvent.click(screen.getByRole("button", { name: "Answer the question" }));
    const dialog = await sheet();
    fireEvent.change(within(dialog).getByLabelText("Your answer"), { target: { value: "Two co-ops." } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the answer" })));
    expect(screen.getByRole("dialog")).toBe(dialog);
    const alert = within(dialog).getByRole("alert");
    expect(alert.textContent).toBe("You have taken many steps on this engagement in the last hour. Try again later.");
    expect(document.activeElement).toBe(alert);
    expect((within(dialog).getByLabelText("Your answer") as HTMLTextAreaElement).value).toBe("Two co-ops.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("closes on a spent question limit (409) and says so after the refresh", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "questionLimit", status: 409 }));
    renderActions(orgReviewing(), { runImpl });
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    const dialog = await sheet();
    fireEvent.change(within(dialog).getByLabelText("Your question"), { target: { value: "One more?" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Send the question" })));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(
      "Your organisation has asked all the questions this stage allows. Decide, or decline.",
    );
  });

  it("pauses with a one-line reason and a resume date, said in words with its weekday", async () => {
    const { runImpl } = renderActions(orgReviewing(), { today: "2026-10-02" });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    expect(dialog.textContent).toContain("Nothing is due while it is on hold.");
    expect(dialog.textContent).toContain("at most 60 days ahead. All the holds of one engagement together may last 60 days.");
    const reason = within(dialog).getByLabelText("Reason");
    expect(reason.tagName).toBe("INPUT"); // one line
    expect(reason.getAttribute("maxlength")).toBe("500");
    const date = within(dialog).getByLabelText("Resumes on") as HTMLInputElement;
    expect(date.type).toBe("date");
    expect(date.min < date.max).toBe(true);
    fireEvent.change(reason, { target: { value: "Budget committee meets on the 20th" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(within(dialog).getByText("Choose a date.")).toBeTruthy();
    expect(document.activeElement).toBe(date);
    fireEvent.change(date, { target: { value: "2026-10-12" } });
    expect(dialog.querySelector("[data-resumes]")?.textContent).toBe("It resumes by itself on 12 Oct 2026.");
    expect(dialog.querySelector("[data-resumes]")?.getAttribute("aria-live")).toBe("polite");
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/pause",
      params: { engagement_id: orgReviewing().id },
      body: { reason: "Budget committee meets on the 20th", resume_at: "2026-10-12", lock_version: 9 },
    });
  });

  it("keeps a hold open when its date passes the days on hold left (409 hold_limit)", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "holdLimit", status: 409 }));
    renderActions(orgReviewing(), { runImpl, today: "2026-10-02" });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Board approval" } });
    fireEvent.change(within(dialog).getByLabelText("Resumes on"), { target: { value: "2026-11-30" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    const date = within(dialog).getByLabelText("Resumes on");
    expect(date.getAttribute("aria-invalid")).toBe("true");
    expect(dialog.textContent).toContain("all its holds together may last 60 days");
    expect(document.activeElement).toBe(date);
    expect(screen.getByRole("dialog")).toBe(dialog);
  });

  it("resumes early with a reason, saying when the hold was due to end", async () => {
    const held = detail({ state: "ON_HOLD", paused_from: "NEGOTIATION", actions: ["resume", "withdraw"], awaiting: [], whose_turn: [], lock_version: 12 });
    const { runImpl } = renderActions(held, { resumeOn: "21 Oct 2026" });
    fireEvent.click(screen.getByRole("button", { name: "Resume now" }));
    const dialog = await sheet();
    expect(dialog.textContent).toContain("It was due to resume on 21 Oct 2026.");
    fireEvent.change(within(dialog).getByLabelText("Reason for resuming now"), { target: { value: "Budget approved early" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Resume now" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/resume",
      params: { engagement_id: held.id },
      body: { reason: "Budget approved early", lock_version: 12 },
    });
  });

  it("asks before the organisation withdraws its question, focusing Cancel, and sends nothing more", async () => {
    const asked = detail({
      my_party: "org",
      state: "INFO_REQUESTED",
      actions: ["cancel_request"],
      awaiting: [{ command: "answer_info", party: "developer" }],
      whose_turn: ["developer"],
      lock_version: 7,
    });
    const { runImpl } = renderActions(asked);
    fireEvent.click(screen.getByRole("button", { name: "Withdraw the question" }));
    const dialog = await sheet();
    expect(dialog.textContent).toContain("Withdraw your question to Achieng Otieno?");
    expect(dialog.textContent).toContain("still counts towards the two this stage allows");
    expect(document.activeElement).toBe(within(dialog).getByRole("button", { name: "Cancel" }));
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Withdraw the question" })));
    expect(runImpl.mock.calls[0][0]).toEqual({
      path: "/api/engagements/{engagement_id}/cancel-request",
      params: { engagement_id: asked.id },
      body: { lock_version: 7 },
    });
  });

  it("closes on Cancel without sending, giving focus back to the button that opened it", async () => {
    const { runImpl } = renderActions(orgReviewing());
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(runImpl).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Pause this engagement" }));
  });

  it("refuses a resume date outside tomorrow to 60 days ahead in the field itself, sending nothing", async () => {
    const { runImpl } = renderActions(orgReviewing(), { today: "2026-10-02" });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    const date = within(dialog).getByLabelText("Resumes on") as HTMLInputElement;
    expect([date.min, date.max]).toEqual(["2026-10-03", "2026-12-01"]);
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Board approval" } });
    for (const day of ["2026-10-02", "2026-12-02"]) {
      fireEvent.change(date, { target: { value: day } });
      await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
      expect(within(dialog).getByText("Choose a resume date from 3 Oct 2026 to 1 Dec 2026.")).toBeTruthy();
      expect(dialog.querySelector("[data-resumes]")?.textContent).toBe(""); // no resume date the API would refuse
      expect(date.getAttribute("aria-invalid")).toBe("true");
      expect(document.activeElement).toBe(date);
    }
    expect(runImpl).not.toHaveBeenCalled();
    fireEvent.change(date, { target: { value: "2026-12-01" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(runImpl).toHaveBeenCalledTimes(1);
  });

  it("shows what side_limits leaves and holds the date within the days on hold left", async () => {
    const limits = { questions_left: null, holds_left: 1, hold_days_left: 10 };
    const { runImpl } = renderActions(orgReviewing(), { today: "2026-10-02", limits });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    expect(within(dialog).getByText("Holds left at this stage: 1")).toBeTruthy();
    expect(within(dialog).getByText("Days on hold left for this engagement: 10")).toBeTruthy();
    expect(dialog.querySelector("[data-left='questionsLeft']")).toBeNull();
    const date = within(dialog).getByLabelText("Resumes on") as HTMLInputElement;
    expect(date.max).toBe("2026-10-12");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Board approval" } });
    fireEvent.change(date, { target: { value: "2026-10-13" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(within(dialog).getByText("Choose a resume date from 3 Oct 2026 to 12 Oct 2026.")).toBeTruthy();
    expect(runImpl).not.toHaveBeenCalled();
  });

  it("shows the questions left only when the API sends the figure", async () => {
    renderActions(orgReviewing(), { limits: { questions_left: 1, holds_left: 2, hold_days_left: 60 } });
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    const dialog = await sheet();
    expect(within(dialog).getByText("Questions left at this stage: 1")).toBeTruthy();
    expect(dialog.querySelector("[data-left='holdsLeft']")).toBeNull();
    cleanup();
    renderActions(orgReviewing());
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    expect((await sheet()).querySelector("[data-left]")).toBeNull();
  });

  it("blocks the sheet's buttons and Escape while its request is in flight", async () => {
    let settle: (outcome: CommandOutcome) => void = () => {};
    const runImpl = vi.fn<Run>(() => new Promise<CommandOutcome>((resolve) => (settle = resolve)));
    renderActions(orgReviewing(), { runImpl });
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    const dialog = await sheet();
    fireEvent.change(within(dialog).getByLabelText("Your question"), { target: { value: "Which co-ops?" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Send the question" }));
    const send = within(dialog).getByRole("button", { name: "Working…" });
    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(send.getAttribute("aria-disabled")).toBe("true");
    expect(cancel.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(send);
    fireEvent.click(cancel);
    const escape = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(escape);
    expect(escape.defaultPrevented).toBe(true);
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(runImpl).toHaveBeenCalledTimes(1);
    await act(async () => settle({ ok: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes on Escape when nothing is in flight", async () => {
    renderActions(orgReviewing());
    fireEvent.click(screen.getByRole("button", { name: "Request information" }));
    const dialog = await sheet();
    const escape = new Event("cancel", { cancelable: true });
    dialog.dispatchEvent(escape);
    expect(escape.defaultPrevented).toBe(false);
    act(() => dialog.close()); // the browser closes the dialog after an unprevented cancel
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Request information" }));
  });

  it("counts the hold's range from the API's today, a platform day moved ahead of the real one", async () => {
    // A test clock 30 days on: the API's today, not the browser's, bounds the date.
    const { runImpl } = renderActions(orgReviewing(), { today: "2026-11-01", limits: { questions_left: 2, holds_left: 2, hold_days_left: 45 } });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    const date = within(dialog).getByLabelText("Resumes on") as HTMLInputElement;
    expect([date.min, date.max]).toEqual(["2026-11-02", "2026-12-16"]);
    expect(dialog.textContent).toContain("From tomorrow to 16 Dec 2026");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Board approval" } });
    fireEvent.change(date, { target: { value: "2026-11-01" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(within(dialog).getByText("Choose a resume date from 2 Nov 2026 to 16 Dec 2026.")).toBeTruthy();
    expect(runImpl).not.toHaveBeenCalled();
    fireEvent.change(date, { target: { value: "2026-11-02" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(runImpl.mock.calls[0][0].body).toMatchObject({ resume_at: "2026-11-02" });
  });

  it("draws and checks no range without the API's today, leaving the date to the API's refusal", async () => {
    const runImpl = vi.fn<Run>(async () => ({ ok: false, refusal: "invalidResumeAt", status: 422 }));
    renderActions(orgReviewing(), { runImpl });
    fireEvent.click(screen.getByRole("button", { name: "Pause this engagement" }));
    const dialog = await sheet();
    const date = within(dialog).getByLabelText("Resumes on") as HTMLInputElement;
    expect(date.hasAttribute("min")).toBe(false);
    expect(date.hasAttribute("max")).toBe(false);
    expect(dialog.textContent).toContain("At most 60 days ahead.");
    expect(dialog.textContent).not.toContain("From tomorrow to");
    fireEvent.change(within(dialog).getByLabelText("Reason"), { target: { value: "Board approval" } });
    fireEvent.change(date, { target: { value: "2030-01-01" } });
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Pause until then" })));
    expect(runImpl).toHaveBeenCalledTimes(1);
    expect(date.getAttribute("aria-invalid")).toBe("true");
    expect(dialog.textContent).toContain("Choose a resume date from tomorrow, no more than 60 days ahead.");
  });
});


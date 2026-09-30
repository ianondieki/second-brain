import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement, ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClientStrings, type StringTree } from "@/components/ClientStrings";
import en from "@/locales/en.json";

import type { decideCase, DecisionOutcome } from "./calls";
import { CaseDecision, type CaseDecisionProps } from "./CaseDecision";
import type { Refusal } from "./moderation";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

afterEach(cleanup);
beforeEach(() => {
  router.refresh.mockReset();
});

// The app's providers as a wrapper, so a rerender (the refreshed page's new props) keeps the same tree.
function Providers({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={en}>
      <ClientStrings strings={en as unknown as Record<string, StringTree>}>{children}</ClientStrings>
    </NextIntlClientProvider>
  );
}
const renderWithIntl = (ui: ReactElement) => render(ui, { wrapper: Providers });

const CASE_ID = "01a0f016-2e64-7294-9e44-77fa421dce09";
const VERSION = "01a0f014-b507-70d8-9f0e-4097336a5fb0";
const NEXT = "/admin/moderation/cases/01a0f020-0000-7000-8000-000000000001";

const props: CaseDecisionProps = {
  caseId: CASE_ID,
  versionId: VERSION,
  kind: "proposal",
  actions: ["approve", "reject"],
  blocked: null,
  decided: null,
  nextHref: NEXT,
};

const approved: DecisionOutcome = { ok: true, data: { id: CASE_ID, status: "approved", subject_state: "clear" } };
const refused = (refusal: Refusal): DecisionOutcome => ({ ok: false, refusal });
const region = (container: HTMLElement) => container.querySelector<HTMLElement>('[role="status"]')!;

describe("CaseDecision (REQ-MOD-01)", () => {
  it("approves the version shown, says so in the status line, and offers the next case", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => approved);
    const { container } = renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    const approve = screen.getByRole("button", { name: "Approve" });
    expect(approve.hasAttribute("data-primary")).toBe(true);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    // The status line is in the tree, empty, before anything happens.
    const status = region(container);
    expect(status.textContent).toBe("");

    fireEvent.click(approve);
    await screen.findByText("Approved. The proposal is public now.");
    expect(decideImpl).toHaveBeenCalledWith(CASE_ID, "approve", VERSION);
    expect(region(container)).toBe(status);
    await waitFor(() => expect(document.activeElement).toBe(status));
    expect(router.refresh).toHaveBeenCalled();
    const next = screen.getByRole("link", { name: "Review the next case" });
    expect(next.getAttribute("href")).toBe(NEXT);
    expect(next.hasAttribute("data-primary")).toBe(true);
    expect(screen.getByRole("link", { name: "Back to Moderation" }).hasAttribute("data-primary")).toBe(false);
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("says a problem is published, and offers the way back when no case is left", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => approved);
    renderWithIntl(<CaseDecision {...props} kind="problem" versionId={null} nextHref={null} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Approved. The problem is published.");
    expect(decideImpl).toHaveBeenCalledWith(CASE_ID, "approve", null);
    expect(screen.queryByRole("link", { name: "Review the next case" })).toBeNull();
    expect(screen.getByRole("link", { name: "Back to Moderation" })).toBeTruthy();
  });

  it("asks once more before rejecting, with focus on the question, and Cancel returns focus to Reject", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => ({
      ok: true,
      data: { id: CASE_ID, status: "rejected", subject_state: "rejected" },
    }));
    renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    const question = screen.getByRole("group", {
      name: "Reject this proposal? It stays hidden. A new version from its author is checked again.",
    });
    await waitFor(() => expect(document.activeElement).toBe(question));
    expect(decideImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Reject" })));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    await screen.findByText("Rejected. It is hidden now.");
    expect(decideImpl).toHaveBeenCalledWith(CASE_ID, "reject", VERSION);
  });

  it("explains a new version, fetches the page again, and decides the new version next", async () => {
    const outcomes = [refused({ kind: "changed" }), approved];
    const decideImpl = vi.fn<typeof decideCase>(async () => outcomes.shift()!);
    const { container, rerender } = renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    const status = region(container);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText(
      "The author published a new version while you were reviewing it. The text above is the new version: read it again, then decide.",
    );
    expect(router.refresh).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(document.activeElement).toBe(status));

    // The refreshed page brings the new version; the status line is the same node and keeps its words.
    const NEW = "01a0f030-0000-7000-8000-000000000002";
    rerender(<CaseDecision {...props} versionId={NEW} decideImpl={decideImpl} />);
    expect(region(container)).toBe(status);
    expect(status.textContent).toContain("new version");
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Approved. The proposal is public now.");
    expect(decideImpl).toHaveBeenLastCalledWith(CASE_ID, "approve", NEW);
  });

  it("asks for a fresh code when the second factor is stale, then repeats the decision", async () => {
    const outcomes = [refused({ kind: "stepUp" }), approved];
    const decideImpl = vi.fn<typeof decideCase>(async () => outcomes.shift()!);
    const confirmImpl = vi.fn(async () => ({ ok: true as const }));
    const { container } = renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} confirmImpl={confirmImpl} />);
    const status = region(container);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const code = await screen.findByLabelText("Code from your app");
    await waitFor(() => expect(document.activeElement).toBe(code));
    expect(region(container)).toBe(status); // outside the part the step-up replaces
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await screen.findByText("Approved. The proposal is public now.");
    expect(confirmImpl).toHaveBeenCalledWith("123456");
    expect(decideImpl).toHaveBeenCalledTimes(2);
    expect(decideImpl).toHaveBeenNthCalledWith(2, CASE_ID, "approve", VERSION);
  });

  it("repeats a rejection, not an approval, after a stale second factor", async () => {
    const rejected: DecisionOutcome = {
      ok: true,
      data: { id: CASE_ID, status: "rejected", subject_state: "rejected" },
    };
    const outcomes = [refused({ kind: "stepUp" }), rejected];
    const decideImpl = vi.fn<typeof decideCase>(async () => outcomes.shift()!);
    const confirmImpl = vi.fn(async () => ({ ok: true as const }));
    renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} confirmImpl={confirmImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Yes, reject" }));
    const code = await screen.findByLabelText("Code from your app");
    fireEvent.change(code, { target: { value: "654321" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await screen.findByText("Rejected. It is hidden now.");
    expect(decideImpl).toHaveBeenCalledTimes(2);
    expect(decideImpl).toHaveBeenNthCalledWith(1, CASE_ID, "reject", VERSION);
    expect(decideImpl).toHaveBeenNthCalledWith(2, CASE_ID, "reject", VERSION);
  });

  it("returns focus to the chosen button when the step-up is cancelled", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => refused({ kind: "stepUp" }));
    renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByLabelText("Code from your app");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Approve" })));
  });

  it("shows a case decided meanwhile with a fixed sentence and fetches the decision", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => refused({ kind: "refusal", code: "already_decided" }));
    const { container, rerender } = renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Someone else decided this case a moment ago. Their decision is shown below.");
    expect(router.refresh).toHaveBeenCalled();
    rerender(
      <CaseDecision
        {...props}
        actions={[]}
        blocked="already_decided"
        decided={{ outcome: "rejected", line: "Rejected by Staff Admin (demo) on 30 Sept 2026, 10:00." }}
        decideImpl={decideImpl}
      />,
    );
    expect(screen.getByText("Rejected by Staff Admin (demo) on 30 Sept 2026, 10:00.")).toBeTruthy();
    expect(container.querySelector('[data-decided="rejected"]')).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it.each([
    ["not_found", "This case is no longer in the queue."],
    ["own_content", "This is your own content, so you cannot decide it."],
    ["subject_gone", "What this case is about no longer exists, so there is nothing to decide."],
    ["unsupported_subject", "Cases of this kind are decided from their own queue, not here."],
    ["forbidden", "Your staff role cannot decide moderation cases."],
  ] as const)("leaves only the way back after %s", async (code, sentence) => {
    const decideImpl = vi.fn<typeof decideCase>(async () => refused({ kind: "refusal", code }));
    const { container } = renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText(sentence);
    expect(screen.queryByRole("button")).toBeNull();
    const back = screen.getByRole("link", { name: "Back to Moderation" });
    expect(back.hasAttribute("data-primary")).toBe(true);
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(1);
    // A subject that is gone changes the page itself (its tag, its choices): it is fetched again.
    expect(router.refresh).toHaveBeenCalledTimes(code === "subject_gone" ? 1 : 0);
  });

  it("leaves only Reject, as the primary action, when the text screens as a vulnerability", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () =>
      refused({ kind: "refusal", code: "cannot_approve_vulnerability" }),
    );
    renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("This text describes a security weakness, so it cannot be approved. Reject it instead.");
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
  });

  it("keeps the choices after a failed call, with a fixed sentence and never the API's words", async () => {
    const decideImpl = vi.fn<typeof decideCase>(async () => refused({ kind: "refusal", code: "generic" }));
    renderWithIntl(<CaseDecision {...props} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("That did not work. Check your connection and try again.");
    expect(screen.getByRole("button", { name: "Approve" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  it("shows a case with a block and no decisions as a fixed sentence and no actions", () => {
    const { container } = renderWithIntl(<CaseDecision {...props} actions={[]} blocked="own_content" />);
    expect(screen.getByText("You wrote this, so another moderator has to decide it.")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Back to Moderation" })).toBeTruthy();
  });

  it("offers only Reject for vulnerability content, with the reason", () => {
    renderWithIntl(<CaseDecision {...props} actions={["reject"]} blocked="cannot_approve_vulnerability" />);
    expect(
      screen.getByText(
        "This text describes a security weakness, so it can never be made public. Reject it: its author can publish a corrected version, which is checked again.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByRole("button", { name: "Reject" }).hasAttribute("data-primary")).toBe(true);
  });
});

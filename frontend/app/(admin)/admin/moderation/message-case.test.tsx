import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { decideMessageCase } from "./calls";
import { CaseRow } from "./CaseRow";
import CasePage from "./cases/[id]/page";
import type { CaseView } from "./data";
import { MessageDecision } from "./MessageDecision";
import type { Case } from "./moderation";

// REQ-ENG-11 (D-57 (4)): a party's report of an engagement message, as staff see it: the queue's row (the reporter's
// first reason, never the text), the case page with the one reported message quoted as plain text (its sender's side
// and time), the reasons, and Dismiss or Uphold with an optional note, each confirmed in a dialog; a report the
// moderator filed or whose engagement they are a party of says so instead of offering the decision.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }),
  notFound: () => {
    throw new Error("notFound");
  },
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("../AdminShell", () => ({ AdminShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("../staff", () => ({ staffContext: async () => ({ me: {}, role: "moderator" }) }));

const data = vi.hoisted(() => ({ view: { kind: "ok", data: { item: null, nextId: null } } as { kind: "ok"; data: CaseView } }));
vi.mock("./data", () => ({ getCase: async () => data.view, getQueue: async () => ({ kind: "ok", data: [] }) }));

const ID = "01a0f016-2e64-7294-9e44-77fa421dce10";

function report(extra: Partial<Case> = {}): Case {
  return {
    id: ID,
    subject_type: "message",
    subject_id: "01a0f010-0000-7000-8000-000000000020",
    reasons: ["contact_details", "spam"],
    source: "report",
    status: "open",
    created_at: "2026-10-05T07:00:00Z",
    subject_state: null,
    subject_version_id: null,
    preview: { title: "Reported message", text: null },
    fields: [],
    flagged_fields: [],
    actions: ["dismiss", "uphold"],
    blocked: null,
    decided_at: null,
    decided_by: null,
    message: {
      message_id: "01a0f010-0000-7000-8000-000000000020",
      engagement_id: "01a0f010-0000-7000-8000-0000000000e1",
      sender_party: "org",
      body: "Call me on 0712 345 678\nor see https://example.com",
      created_at: "2026-10-05T06:30:00Z",
    },
    ...extra,
  };
}

beforeAll(() => {
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
});
beforeEach(() => refresh.mockReset());
afterEach(cleanup);

async function page(item: Case) {
  data.view = { kind: "ok", data: { item, nextId: null } };
  return renderWithIntl(<>{await resolveServerTree(await CasePage({ params: Promise.resolve({ id: ID }) } as never))}</>);
}

describe("the case page", () => {
  it("quotes the one reported message as plain text, with its sender's side and time, and the reasons", async () => {
    await page(report());
    expect(screen.getByRole("heading", { level: 1, name: "Reported message" })).toBeTruthy();
    const quoted = document.querySelector<HTMLElement>("[data-message-body]")!;
    expect(quoted.tagName).toBe("BLOCKQUOTE");
    expect(quoted.textContent).toBe("Call me on 0712 345 678\nor see https://example.com");
    expect(quoted.className).toContain("whitespace-pre-wrap");
    expect(quoted.querySelector("a")).toBeNull();
    expect(document.querySelector("[data-sender='org']")?.textContent).toBe("Sent by the organisation");
    expect(document.body.textContent).toContain("5 Oct 2026, 09:30 EAT");
    const reasons = [...document.querySelectorAll("[data-reasons] li")].map((li) => li.textContent);
    expect(reasons).toEqual(["Shares contact details too early", "Spam"]);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Dismiss" }).hasAttribute("data-primary")).toBe(true);
  });

  it("quotes markup in a reported message as text: no element made, no link, line breaks kept", async () => {
    const raw = "<img src=x onerror=alert(1)><b>hi</b> https://x.example\nsecond line";
    await page(report({ message: { ...report().message!, body: raw } }));
    const quoted = document.querySelector<HTMLElement>("[data-message-body]")!;
    expect(quoted.textContent).toBe(raw);
    expect(quoted.querySelector("img, b, a")).toBeNull();
    expect(quoted.children).toHaveLength(0);
    expect(quoted.textContent?.split("\n")).toHaveLength(2);
  });

  it("says why a moderator cannot decide their own report, without the buttons", async () => {
    await page(report({ actions: [], blocked: "own_content" }));
    expect(document.querySelector("[data-blocked='own_content']")?.textContent).toBe(
      "You filed this report or are a party of its engagement, so another moderator decides it.",
    );
    expect(screen.queryByRole("button", { name: "Dismiss" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Uphold" })).toBeNull();
  });

  it("shows a decided report's outcome and who decided it", async () => {
    await page(report({ status: "rejected", actions: [], decided_at: "2026-10-05T08:00:00Z", decided_by: { id: "s", display_name: "Wanjiku Staff" } }));
    expect(document.querySelector("[data-header-tag='outcome']")?.textContent).toBe("Upheld");
    expect(document.querySelector("[data-decided='upheld']")?.textContent).toBe("Upheld by Wanjiku Staff on 5 Oct 2026, 11:00.");
  });
});

describe("the decision", () => {
  function renderDecision(decideImpl: typeof decideMessageCase) {
    return renderWithIntl(<MessageDecision caseId={ID} actions={["dismiss", "uphold"]} blocked={null} decided={null} nextHref="/admin/moderation/cases/next" decideImpl={decideImpl} />);
  }

  it("asks once more, then dismisses with the note and offers the next case", async () => {
    const decide = vi.fn<typeof decideMessageCase>(async () => ({ ok: true, data: { id: ID, status: "approved", subject_state: null } }));
    renderDecision(decide);
    fireEvent.change(screen.getByLabelText("Note for the record (optional)"), { target: { value: "Ordinary request." } });
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    const dialog = document.querySelector("dialog[open]")!;
    expect(within(dialog as HTMLElement).getByRole("heading", { name: "Dismiss this report?" })).toBeTruthy();
    expect(decide).not.toHaveBeenCalled();
    fireEvent.click(within(dialog as HTMLElement).getByRole("button", { name: "Yes, dismiss" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith(ID, "dismiss", "Ordinary request."));
    expect(await screen.findByText("Dismissed. The case is closed.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Review the next case" }).hasAttribute("data-primary")).toBe(true);
    expect(refresh).toHaveBeenCalled();
  });

  it("upholds after its own question", async () => {
    const decide = vi.fn<typeof decideMessageCase>(async () => ({ ok: true, data: { id: ID, status: "rejected", subject_state: null } }));
    renderDecision(decide);
    fireEvent.click(screen.getByRole("button", { name: "Uphold" }));
    const dialog = document.querySelector<HTMLElement>("dialog[open]")!;
    expect(dialog.textContent).toContain("The case closes as a breach of the rules. The message stays in the thread.");
    fireEvent.click(within(dialog).getByRole("button", { name: "Yes, uphold" }));
    await waitFor(() => expect(decide).toHaveBeenCalledWith(ID, "uphold", ""));
    expect(await screen.findByText("Upheld. The case is closed.")).toBeTruthy();
  });

  it("asks for a fresh code when the second factor is old, and says a refusal in fixed words", async () => {
    const decide = vi.fn<typeof decideMessageCase>(async () => ({ ok: false, refusal: { kind: "stepUp" } }));
    renderDecision(decide);
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    fireEvent.click(within(document.querySelector<HTMLElement>("dialog[open]")!).getByRole("button", { name: "Yes, dismiss" }));
    expect(await screen.findByLabelText("Code from your app")).toBeTruthy();
    cleanup();
    renderDecision(vi.fn(async () => ({ ok: false as const, refusal: { kind: "refusal" as const, code: "already_decided" as const } })));
    fireEvent.click(screen.getByRole("button", { name: "Uphold" }));
    fireEvent.click(within(document.querySelector<HTMLElement>("dialog[open]")!).getByRole("button", { name: "Yes, uphold" }));
    expect(await screen.findByText("Someone else decided this case a moment ago. Their decision is shown below.")).toBeTruthy();
  });
});

describe("the queue's row", () => {
  it("names a message report in the queue's words, with the reporter's first reason and never the text", async () => {
    renderWithIntl(<table><tbody>{await resolveServerTree(await CaseRow({ item: report({ message: null }) }))}</tbody></table>);
    expect(screen.getByRole("link", { name: "Reported message" })).toBeTruthy();
    expect(document.body.textContent).toContain("Message");
    expect(document.querySelector("[data-chip='reason']")?.textContent).toBe("Shares contact details too early");
    expect(document.body.textContent).not.toContain("0712");
  });

  it("says a dismissed report's outcome", async () => {
    renderWithIntl(<table><tbody>{await resolveServerTree(await CaseRow({ item: report({ status: "approved", actions: [], message: null }) }))}</tbody></table>);
    expect(document.body.textContent).toContain("Dismissed");
    expect(document.querySelector("[data-chip='reason']")).toBeNull();
  });
});

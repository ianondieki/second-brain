import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import { DeleteIdea } from "./[id]/DeleteIdea";
import type { MyProposalItem } from "./ideas";
import { IdeaRow } from "./IdeaRow";
import { IdeaStatusBadge } from "./IdeaStatusBadge";

// REQ-PROP-01 (F2), REQ-PROV-05: the My ideas list rows (≤2 chips, status as icon + words + colour; docs/spec/07 items
// 2 and 6) and the delete dialog, which says what is kept before anything happens (AC-IP-6).

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }) }));

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

afterEach(() => {
  cleanup();
  push.mockReset();
});

function item(overrides: Partial<MyProposalItem> = {}): MyProposalItem {
  return {
    id: "0199a000-0000-7000-8000-0000000000aa",
    status: "published",
    moderation_state: "clear",
    title: "Cold chain for dairy co-ops",
    niche: { id: "n1", slug: "dairy", label: "Agriculture › Dairy" },
    current_version_no: 1,
    cert_id: "TXEMFBJ89RRTQS87",
    has_draft: false,
    published_at: "2026-09-28T09:00:00Z",
    updated_at: "2026-09-29T11:06:25Z",
    ...overrides,
  };
}

describe("an idea in the list", () => {
  it("links its title to the idea and shows the niche, status and last change", () => {
    renderWithIntl(<IdeaRow item={item()} />);
    expect(screen.getByRole("link", { name: "Cold chain for dairy co-ops" }).getAttribute("href")).toBe(
      "/dev/ideas/0199a000-0000-7000-8000-0000000000aa",
    );
    expect(screen.getByText("Agriculture › Dairy")).toBeTruthy();
    expect(screen.getByText("Published")).toBeTruthy();
    expect(screen.getByText("Changed 29 Sept 2026")).toBeTruthy();
  });

  it("carries at most two chips: the status and unpublished changes", () => {
    const { container } = renderWithIntl(<IdeaRow item={item({ has_draft: true })} />);
    expect(container.querySelectorAll("[data-status], [data-chip]")).toHaveLength(2);
    expect(screen.getByText("Unpublished changes")).toBeTruthy();
  });

  it("names an untitled draft", () => {
    renderWithIntl(<IdeaRow item={item({ status: "draft", title: null, has_draft: true, niche: null })} />);
    expect(screen.getByRole("link", { name: "Untitled idea" })).toBeTruthy();
    expect(screen.getByText("Draft")).toBeTruthy();
    expect(screen.queryByText("Unpublished changes")).toBeNull();
  });

  it.each([
    ["draft", "Draft"],
    ["published", "Published"],
    ["held", "Held for review"],
    ["rejected", "Not approved"],
    ["hidden", "Hidden"],
  ] as const)("shows %s as an icon and words", (status, words) => {
    const { container } = renderWithIntl(<IdeaStatusBadge status={status} />);
    expect(container.textContent).toBe(words);
    expect(container.querySelector("svg[aria-hidden='true']")).not.toBeNull();
  });
});

describe("deleting an idea", () => {
  it("says a published idea is hidden and its evidence kept, then hides it", async () => {
    const removeImpl = vi.fn(async () => ({ ok: true as const, value: { status: "hidden" as const, message: "" } }));
    renderWithIntl(<DeleteIdea id="p1" registered removeImpl={removeImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this idea?" });
    expect(dialog.textContent).toContain("certificates and /verify records are kept as evidence");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    });
    expect(removeImpl).toHaveBeenCalledWith("p1");
    expect(push).toHaveBeenCalledWith("/dev/ideas?removed=hidden");
  });

  it("says a draft is removed for good, and keeps it when cancelled", () => {
    const removeImpl = vi.fn();
    renderWithIntl(<DeleteIdea id="p1" registered={false} removeImpl={removeImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    expect(screen.getByRole("dialog").textContent).toContain("never published");
    fireEvent.click(screen.getByRole("button", { name: "Keep it" }));
    expect(removeImpl).not.toHaveBeenCalled();
  });

  it("stays open with a reason when the delete failed", async () => {
    const removeImpl = vi.fn(async () => ({ ok: false as const, problem: "network" as const, fields: [] }));
    renderWithIntl(<DeleteIdea id="p1" registered={false} removeImpl={removeImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Delete idea" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    });
    expect(screen.getByRole("alert").textContent).toContain("We could not reach the server");
    expect(push).not.toHaveBeenCalled();
  });
});

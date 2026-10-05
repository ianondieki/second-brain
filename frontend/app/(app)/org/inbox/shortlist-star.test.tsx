import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { InboxItem } from "../data";
import type { Membership } from "../membership";
import { InboxRow } from "./InboxRow";
import { ShortlistControl } from "./ShortlistControl";
import type { ShortlistOutcome } from "./shortlist-calls";
import { ShortlistStar } from "./ShortlistStar";

// REQ-REPO-02 (P21 B1, B6): the Inbox star. Reviewers, signatories and admins toggle it (aria-pressed, named by what
// a press does), at once and back again with one sentence when the API refuses; other members see a read-only mark.

afterEach(cleanup);

const labels = { add: en.shortlist.add, remove: en.shortlist.remove, problem: en.shortlist.problem };
const reviewer: Membership = { org_id: "o1", org_name: "Telco A", roles: ["reviewer"] };
const viewer: Membership = { org_id: "o1", org_name: "Telco A", roles: ["owner", "viewer"] };

function deferred() {
  let resolve!: (value: ShortlistOutcome) => void;
  const promise = new Promise<ShortlistOutcome>((r) => (resolve = r));
  return { promise, resolve };
}

describe("the shortlist star", () => {
  it("adds at once, then stays on when the API agrees", async () => {
    const answer = deferred();
    const setImpl = vi.fn(() => answer.promise);
    renderWithIntl(<ShortlistStar orgId="o1" proposalId="p1" initial={false} labels={labels} setImpl={setImpl} />);
    const star = screen.getByRole("button", { name: "Add to shortlist" });
    expect(star.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(star);
    expect(setImpl).toHaveBeenCalledWith("o1", "p1", true);
    const on = screen.getByRole("button", { name: "Remove from shortlist" });
    expect(on.getAttribute("aria-pressed")).toBe("true");
    await act(async () => answer.resolve({ ok: true }));
    expect(screen.getByRole("button", { name: "Remove from shortlist" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("goes back and says why when the API refuses", async () => {
    const setImpl = vi.fn(async (): Promise<ShortlistOutcome> => ({ ok: false, problem: "gone" }));
    renderWithIntl(<ShortlistStar orgId="o1" proposalId="p1" initial labels={labels} setImpl={setImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Remove from shortlist" }));
    expect(setImpl).toHaveBeenCalledWith("o1", "p1", false);
    expect((await screen.findByRole("alert")).textContent).toBe(en.shortlist.problem.gone);
    expect(screen.getByRole("button", { name: "Remove from shortlist" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("shows its words beside the star on a proposal's page", () => {
    renderWithIntl(<ShortlistStar orgId="o1" proposalId="p1" initial={false} labels={labels} variant="button" />);
    expect(screen.getByRole("button", { name: "Add to shortlist" }).textContent).toBe("Add to shortlist");
  });

  it("is a read-only mark for a member who cannot change the shortlist, and nothing when not on it", () => {
    const marked = renderWithIntl(<ShortlistControl org={viewer} proposalId="p1" shortlisted />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(marked.container.querySelector("[data-shortlisted]")?.textContent).toBe(en.shortlist.marked);
    cleanup();
    const unmarked = renderWithIntl(<ShortlistControl org={viewer} proposalId="p1" shortlisted={false} />);
    expect(unmarked.container.textContent).toBe("");
  });
});

describe("an Inbox row", () => {
  const item = {
    tag_id: "t1",
    pitched_at: "2026-10-05T08:00:00Z",
    engagement: null,
    shortlisted: true,
    proposal: {
      id: "p1",
      teaser: { title: "Maziwa baridi", niche: null, maturity: "mvp", ask: "pilot", summary: "Shared chillers." },
    },
  } as unknown as InboxItem;

  it("carries the star state for the reviewer (P21 B6) and at most two chips", () => {
    renderWithIntl(<InboxRow item={item} href="/org/inbox/p1" org={reviewer} />);
    expect(screen.getByRole("button", { name: "Remove from shortlist" }).getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
  });

  it("shows the mark, not the star, to a viewer", () => {
    renderWithIntl(<InboxRow item={item} href="/org/inbox/p1" org={viewer} />);
    expect(screen.queryByRole("button", { name: /shortlist/ })).toBeNull();
    expect(document.querySelector("[data-shortlisted]")).not.toBeNull();
  });
});

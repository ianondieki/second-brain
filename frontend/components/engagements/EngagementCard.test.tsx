import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { EngagementCard } from "./EngagementCard";

afterEach(cleanup);

// P25 (D-67; REQ-UX-02): an engagement as a card for both sides' lists: the title as the one link, five dots for where
// it stands (one image with its words), at most two chips, who it waits on, the countdown.
describe("EngagementCard", () => {
  it("links its title, reads its stage as one image and keeps to two chips when it is your turn", () => {
    renderWithIntl(
      <EngagementCard
        item={summary({ state: "NEGOTIATION", stage_group: "agreement", stage_label: "Terms drafting", whose_turn: ["developer"] })}
        mine="developer"
        href="/dev/engagements/e1"
      />,
    );
    const card = screen.getByRole("article");
    expect(within(card).getAllByRole("link")).toHaveLength(1);
    expect(within(card).getByRole("img", { name: "Stage 3 of 5: Terms drafting" })).toBeTruthy();
    expect(card.querySelectorAll("[data-dot]")).toHaveLength(5);
    expect([...card.querySelectorAll("[data-dot]")].map((d) => d.getAttribute("data-dot"))).toEqual(["completed", "completed", "current", "pending", "pending"]);
    expect(card.querySelectorAll("[data-chip]").length).toBeLessThanOrEqual(2);
    expect(within(card).getByText("Your turn")).toBeTruthy();
    expect(card.getAttribute("data-turn")).toBe("mine");
  });

  it("says who it waits on otherwise, titled by the organisation under an idea", () => {
    renderWithIntl(
      <EngagementCard
        item={summary({ state: "NEGOTIATION", stage_group: "agreement", whose_turn: ["org"], org_name: "SACCO B" })}
        mine="developer"
        titleBy="organisation"
        href="/dev/engagements/e1"
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "SACCO B" })).toBeTruthy();
    expect(screen.getByText("Waiting on SACCO B")).toBeTruthy();
    expect(screen.queryByText("Your turn")).toBeNull();
  });
});

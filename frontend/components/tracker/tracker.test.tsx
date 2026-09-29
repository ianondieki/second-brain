import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { detail, history, inImplementation } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { Chip } from "./Chip";
import { Agreements, Payments, Signatures } from "./Deal";
import { EngagementRow } from "./EngagementRow";
import { Endorsements } from "./Endorsements";
import { HistoryList } from "./HistoryList";
import { stepperSteps, type ChipKind } from "./model";
import { Stepper } from "./Stepper";
import { WhoseTurn } from "./WhoseTurn";

// REQ-ENG-03 (AC-TRACK-3, docs/spec/06 6.9 Rendering, docs/spec/07 items 2 and 6): the tracker's read-only parts as
// both parties see them.

afterEach(cleanup);

describe("chips", () => {
  it.each([
    ["completed", "Completed", "text-ok"],
    ["current", "Current", "text-jacaranda"],
    ["pending", "Pending", "text-ink-soft"],
    ["onHold", "On hold", "text-ink"],
    ["overdue", "Overdue", "text-error"],
    ["ended", "Ended", "text-ink-soft"],
  ] as const)("shows %s as a mark, words and a colour", (kind: ChipKind, words, tone) => {
    const { container } = renderWithIntl(<Chip kind={kind}>{words}</Chip>);
    const chip = container.querySelector(`[data-chip='${kind}']`)!;
    expect(chip.textContent).toBe(words);
    expect(chip.className).toContain(tone);
    expect(chip.querySelector(`svg[aria-hidden='true'][data-mark='${kind}']`)).not.toBeNull();
  });
});

describe("the stepper", () => {
  it("is an ordered list of the five groups with the current one marked as the step", () => {
    const steps = stepperSteps({ state: "NDA_PENDING", stage_group: "contact_nda", due: null });
    renderWithIntl(<Stepper steps={steps} detail={<span>Now: Mutual NDA</span>} />);
    const list = screen.getByRole("list", { name: "Stages" });
    expect(list.tagName).toBe("OL");
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector("p")?.textContent)).toEqual([
      "Review",
      "Contact and NDA",
      "Agreement",
      "Implementation",
      "Close",
    ]);
    expect(items[0].textContent).toContain("Completed");
    expect(items[1].getAttribute("aria-current")).toBe("step");
    expect(items[1].textContent).toContain("Current");
    expect(items[1].textContent).toContain("Now: Mutual NDA");
    expect(items[2].textContent).toContain("Pending");
    expect(list.querySelectorAll("[aria-current]")).toHaveLength(1);
  });

  it("is vertical on phones and a horizontal spine from 1024 px", () => {
    renderWithIntl(<Stepper steps={stepperSteps({ state: "SUBMITTED", stage_group: "review", due: null })} />);
    const list = screen.getByRole("list", { name: "Stages" });
    expect(list.className).toContain("flex-col");
    expect(list.className).toContain("lg:grid-cols-5");
  });
});

describe("the whose-turn banner", () => {
  it("tells the developer the organisation is next, and with what", () => {
    renderWithIntl(<WhoseTurn detail={detail()} />);
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(banner.getAttribute("data-whose-turn")).toBe("other");
    expect(banner.textContent).toContain("Awaiting: Telco A (fixture)");
    expect(banner.textContent).toContain("Next step for Telco A (fixture): Start the review");
    expect(banner.textContent).toContain("8 business days left, due 7 Oct 2026");
  });

  it("tells the organisation it is their turn", () => {
    renderWithIntl(<WhoseTurn detail={detail({ my_party: "org", my_roles: ["signatory"] })} />);
    expect(screen.getByText("Awaiting: you")).toBeTruthy();
    expect(screen.getByText("Your next step: Start the review")).toBeTruthy();
  });

  it("names both parties when both owe a signature", () => {
    renderWithIntl(
      <WhoseTurn
        detail={detail({
          state: "NDA_PENDING",
          whose_turn: ["developer", "org"],
          awaiting: [
            { command: "sign_nda", party: "developer" },
            { command: "sign_nda", party: "org" },
          ],
        })}
      />,
    );
    expect(screen.getByText("Awaiting: you and Telco A (fixture)")).toBeTruthy();
    expect(screen.getByText("Your next step: Sign the mutual NDA")).toBeTruthy();
  });

  it("says an engagement ended, and why", () => {
    renderWithIntl(
      <WhoseTurn detail={detail({ state: "DECLINED", whose_turn: [], awaiting: [], due: null, end_reason: "BUDGET" })} />,
    );
    expect(screen.getByText("This engagement has ended.")).toBeTruthy();
    expect(screen.getByText("Reason: Budget")).toBeTruthy();
  });

  it("says overdue in words, not colour alone", () => {
    renderWithIntl(<WhoseTurn detail={detail({ due: { due_on: "2026-09-25", business_days_left: -2, overdue: true } })} />);
    expect(screen.getByText("Overdue by 2 business days, was due 25 Sep 2026")).toBeTruthy();
  });
});

describe("dual endorsement rows (AC-TRACK-3)", () => {
  it("renders two labelled rows with name, role, time in EAT and method", () => {
    renderWithIntl(
      <Endorsements
        detail={detail({
          state: "CONTACT_MADE",
          endorsements: [
            {
              id: "x1",
              stage: "CONTACT_MADE",
              stage_round: 1,
              milestone_id: null,
              party: "org",
              user_id: "u1",
              name: "Rita Wanjiru",
              role: "signatory",
              method: "totp",
              endorsed_at: "2026-09-23T11:05:00Z",
            },
          ],
        })}
      />,
    );
    const org = document.querySelector("[data-endorsement='org']")!;
    const dev = document.querySelector("[data-endorsement='developer']")!;
    expect(within(org as HTMLElement).getByRole("heading").textContent).toBe("Endorsement by Enterprise");
    expect(within(dev as HTMLElement).getByRole("heading").textContent).toBe("Endorsement by Developer");
    expect(org.textContent).toContain("Endorsed");
    expect(org.textContent).toContain("Rita Wanjiru");
    expect(org.textContent).toContain("Signatory");
    expect(org.textContent).toMatch(/23 Sep 2026, 14:05 EAT/);
    expect(org.textContent).toContain("Authenticator code");
    expect(dev.getAttribute("data-endorsed")).toBe("false");
    expect(dev.textContent).toContain("Not endorsed yet");
  });
});

describe("the deal's records", () => {
  it("shows the signed agreement with its milestones, amounts and the review due date", () => {
    renderWithIntl(<Agreements detail={inImplementation()} />);
    const m1 = document.querySelector("[data-milestone-row='1']")!;
    expect(m1.textContent).toContain("Milestone 1: Pilot at two co-ops");
    expect(m1.textContent).toContain("KES 250,000");
    expect(m1.textContent).toContain("Submitted for review");
    expect(m1.textContent).toMatch(/Review due by 9 Oct 2026/);
    expect(screen.getByText("Non-exclusive licence")).toBeTruthy();
    expect(screen.getByText("Never: every milestone needs an acceptance")).toBeTruthy();
    expect(document.querySelector("[data-milestone-row='2']")!.textContent).toContain("KES 1,000,000");
  });

  it("lists signatures with signer, party, method and fingerprint", () => {
    renderWithIntl(
      <Signatures
        signatures={[
          {
            id: "s1",
            document_kind: "mutual_nda",
            document_ref: "r1",
            document_sha256: "3f5a9c017be2aa00bb",
            party: "org",
            signer_user_id: "u1",
            signer_name: "Rita Wanjiru",
            step_up_method: "totp",
            signed_at: "2026-09-23T11:05:00Z",
          },
        ]}
      />,
    );
    const row = document.querySelector("[data-signature='mutual_nda']")!;
    expect(row.textContent).toContain("Mutual NDA");
    expect(row.textContent).toContain("Signed by Rita Wanjiru for the organisation, with Authenticator code");
    expect(row.textContent).toContain("Fingerprint 3f5a 9c01 7be2");
  });

  it("shows a recorded payment until the developer confirms it", () => {
    renderWithIntl(
      <Payments
        payments={[
          {
            id: "p1",
            milestone_id: null,
            amount_kes_minor: 125_000_000,
            method: "mpesa",
            reference: "QK12ABC",
            paid_on: "2026-09-28",
            recorded_by: "u1",
            recorded_at: "2026-09-28T09:00:00Z",
            confirmed_by: null,
            confirmed_at: null,
            confirmed_amount_kes_minor: null,
          },
        ]}
      />,
    );
    const row = document.querySelector("[data-payment]")!;
    expect(row.getAttribute("data-payment")).toBe("recorded");
    expect(row.textContent).toContain("KES 1,250,000");
    expect(row.textContent).toContain("M-Pesa");
    expect(row.textContent).toContain("QK12ABC");
    expect(row.textContent).toContain("Not confirmed yet");
  });
});

describe("the History tab", () => {
  it("lists events newest first with the actor, role and EAT time, and the chain check", () => {
    renderWithIntl(<HistoryList history={history()} />);
    const events = document.querySelectorAll("[data-event]");
    expect([...events].map((e) => e.getAttribute("data-event"))).toEqual(["start_review", "create"]);
    expect(events[0].textContent).toContain("Review started");
    expect(events[0].textContent).toContain("Rita Wanjiru, Signatory");
    expect(events[0].textContent).toMatch(/24 Sep 2026, 09:30 EAT/);
    expect(events[1].textContent).toContain("Engagement opened");
    expect(document.querySelector("[data-chain='verified']")).not.toBeNull();
  });

  it("warns when the chain does not check out, and words unknown events", () => {
    const h = history({ chain_verified: false });
    h.events[1] = { ...h.events[1], command: "something_new" };
    renderWithIntl(<HistoryList history={h} />);
    expect(document.querySelector("[data-chain='unverified']")!.textContent).toContain("could not be checked");
    expect(screen.getByText("Step recorded")).toBeTruthy();
  });
});

describe("a row in the Engagements list", () => {
  it("links to the tracker with at most two chips: the stage and whose turn", () => {
    const { container } = renderWithIntl(
      <EngagementRow item={detail({ whose_turn: ["developer"] })} mine="developer" href="/dev/engagements/e1" />,
    );
    expect(screen.getByRole("link", { name: "Cold chain for dairy co-ops" }).getAttribute("href")).toBe(
      "/dev/engagements/e1",
    );
    expect(screen.getByText("With Telco A (fixture)")).toBeTruthy();
    const chips = container.querySelectorAll("[data-chip]");
    expect([...chips].map((c) => c.textContent)).toEqual(["Proposal submitted", "Your turn"]);
  });

  it("shows the developer's name to the organisation and no turn chip when it waits on the other side", () => {
    const { container } = renderWithIntl(<EngagementRow item={detail({ whose_turn: ["developer"] })} mine="org" href="/x" />);
    expect(screen.getByText("From Achieng Otieno")).toBeTruthy();
    expect(container.querySelectorAll("[data-chip]")).toHaveLength(1);
  });
});

describe("the contact person", () => {
  it("names the contact's role in words", async () => {
    const { ContactPerson } = await import("./Deal");
    renderWithIntl(
      <ContactPerson
        detail={detail({
          contact: { user_id: "u1", name: "Rita Wanjiru", role: "signatory", channel: "whatsapp", contact_by: "2026-10-01" },
        })}
      />,
    );
    expect(screen.getByText("Signatory")).toBeTruthy();
    expect(screen.getByText("WhatsApp")).toBeTruthy();
  });
});

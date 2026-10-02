import { cleanup, screen, within } from "@testing-library/react";
import { documentLinkClass } from "./document-link";
import { afterEach, describe, expect, it } from "vitest";

import { detail, history, inImplementation, summary } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";

import { Chip } from "./Chip";
import { Agreements, Payments, Signatures } from "./Deal";
import { EngagementCard } from "./EngagementCard";
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
    ["current", "Current", "text-accent"],
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
    // The same step owed by both: said once, naming both.
    expect(screen.getByText("Next step for both of you: Sign the mutual NDA")).toBeTruthy();
    expect(screen.queryByText("Your next step: Sign the mutual NDA")).toBeNull();
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
    // The date is its own span (it never splits across lines), so the sentence is read from the element's text.
    expect(document.querySelector("[data-due='overdue']")?.textContent).toBe("Overdue by 2 business days, was due 25 Sep 2026");
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

  it("draws no rule under the Agreement heading: the rule belongs to lists (P16-B ux-review)", () => {
    renderWithIntl(<Agreements detail={inImplementation()} />);
    const latest = document.querySelector("[data-agreement]")!;
    expect(latest.className).not.toContain("border-t");
    // The label column is the one DescriptionList of the design system (the same width as Contact person's).
    expect(latest.querySelector("dl")!.className).toContain("sm:grid-cols-[minmax(9rem,11rem)_minmax(0,1fr)]");
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
    expect(document.querySelector("[data-chain='unverified']")!.textContent).toContain("did not pass its integrity check");
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
    // P16-B ux-review: the solid "Your turn" badge carries a mark as well as words and colour (docs/spec/07 item 6).
    expect(container.querySelector("[data-chip='turn'] svg[aria-hidden='true']")).not.toBeNull();
  });

  it("shows the developer's name to the organisation and no turn chip when it waits on the other side", () => {
    const { container } = renderWithIntl(<EngagementRow item={detail({ whose_turn: ["developer"] })} mine="org" href="/x" />);
    expect(screen.getByText("From Achieng Otieno")).toBeTruthy();
    expect(container.querySelectorAll("[data-chip]")).toHaveLength(1);
  });

  it("is titled by the organisation under its proposal's heading, without repeating the proposal (P16-C1)", () => {
    const { container } = renderWithIntl(
      <EngagementRow item={detail({ whose_turn: ["developer"] })} mine="developer" href="/dev/engagements/e1" titleBy="organisation" />,
    );
    expect(screen.getByRole("link", { name: "Telco A (fixture)" }).getAttribute("href")).toBe("/dev/engagements/e1");
    expect(container.textContent).not.toContain("Cold chain for dairy co-ops");
    expect(screen.queryByText("With Telco A (fixture)")).toBeNull();
    expect([...container.querySelectorAll("[data-chip]")].map((c) => c.textContent)).toEqual(["Proposal submitted", "Your turn"]);
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

describe("the Documents tab's links (fix round 1)", () => {
  it("shows the current document in ink without an underline, the others as links", () => {
    const current = documentLinkClass(true).split(" ");
    expect(current).toEqual(expect.arrayContaining(["text-ink", "no-underline", "min-h-11"]));
    expect(current).not.toContain("text-accent");
    expect(current).not.toContain("underline");
    const other = documentLinkClass(false).split(" ");
    expect(other).toEqual(expect.arrayContaining(["text-accent", "underline", "min-h-11"]));
    expect(other).not.toContain("text-ink");
  });
});

// REQ-ENG-10 part (docs/spec/06 6.9 side branches): the side states are said in the pinned whose-turn banner, on the
// stage where they occurred (never as extra steps), and their texts appear on the History tab in order.
describe("the side states in the whose-turn banner", () => {
  const asked = {
    kind: "info_request" as const,
    body: "Which co-ops ran the pilot? <b>details</b> https://example.com/x",
    by: "org" as const,
    at: "2026-10-01T07:00:00Z",
    resume_at: null,
  };
  const questionOpen = (party: "developer" | "org") =>
    detail({
      my_party: party,
      state: "INFO_REQUESTED",
      stage_label: "Information requested",
      stage_group: null,
      paused_from: "UNDER_REVIEW",
      whose_turn: ["developer"],
      awaiting: [{ command: "answer_info", party: "developer" }],
      due: { due_on: "2026-10-15", business_days_left: 10, overdue: false },
      notes: [asked],
    });

  it("shows the developer the question, their next step and the answer-by date, the text as plain text", () => {
    renderWithIntl(<WhoseTurn detail={questionOpen("developer")} />);
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(banner.getAttribute("data-whose-turn")).toBe("you");
    expect(screen.getByText("Awaiting: you")).toBeTruthy();
    const side = banner.querySelector("[data-side='info']")!;
    expect(side.textContent).toBe(`Information requested on 1 Oct 2026: ${asked.body}`);
    // Escaped, never markup or a link.
    expect(side.querySelector("b, a")).toBeNull();
    expect(banner.textContent).toContain("Your next step: Answer the question");
    expect(banner.querySelector("[data-info-clock]")?.textContent).toBe(
      "The stage's deadline waits while you answer. Unanswered by 15 Oct 2026, the engagement expires.",
    );
    expect(banner.querySelector("[data-due]")).toBeNull(); // the date is said once, in the sentence
  });

  it("shows the organisation it waits on the developer's answer", () => {
    renderWithIntl(<WhoseTurn detail={questionOpen("org")} />);
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(banner.textContent).toContain("Awaiting: Achieng Otieno");
    expect(banner.textContent).toContain("Next step for Achieng Otieno: Answer the question");
    expect(banner.querySelector("[data-info-clock]")?.textContent).toContain("waits until Achieng Otieno answers");
  });

  it("says a question past its answer-by date is overdue, in words", () => {
    const late = { ...questionOpen("developer"), due: { due_on: "2026-10-15", business_days_left: -1, overdue: true } };
    renderWithIntl(<WhoseTurn detail={late} />);
    expect(document.querySelector("[data-due='overdue']")?.textContent).toBe("Overdue by 1 business day, was due 15 Oct 2026");
    expect(document.querySelector("[data-info-clock]")).toBeNull();
  });

  it("says who paused, until when and why, with the On hold mark", () => {
    const held = detail({
      my_party: "developer",
      state: "ON_HOLD",
      stage_group: null,
      paused_from: "NEGOTIATION",
      whose_turn: [],
      awaiting: [],
      due: { due_on: "2026-10-21", business_days_left: 13, overdue: false },
      notes: [{ kind: "hold", body: "Budget committee meets on the 20th.", by: "org", at: "2026-10-02T08:00:00Z", resume_at: "2026-10-21" }],
    });
    renderWithIntl(<WhoseTurn detail={held} />);
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(screen.getByText("This engagement is on hold.")).toBeTruthy();
    expect(banner.querySelector("[data-mark='onHold']")).not.toBeNull();
    expect(banner.querySelector("[data-side='hold']")?.textContent).toBe(
      "Paused by Telco A (fixture) until 21 Oct 2026: Budget committee meets on the 20th.",
    );
    expect(banner.textContent).toContain("It resumes by itself that day");
    expect(banner.querySelector("[data-due]")).toBeNull();
  });

  it("tells the party who paused that they did", () => {
    const held = detail({
      state: "ON_HOLD",
      stage_group: null,
      paused_from: "NEGOTIATION",
      whose_turn: [],
      awaiting: [],
      notes: [{ kind: "hold", body: "Exams week", by: "developer", at: "2026-10-02T08:00:00Z", resume_at: "2026-10-09" }],
    });
    renderWithIntl(<WhoseTurn detail={held} />);
    expect(document.querySelector("[data-side='hold']")?.textContent).toBe("You paused this engagement until 9 Oct 2026: Exams week");
  });

  it.each([
    ["NO_REVIEW", "Expired: the organisation did not start a review in time."],
    ["NO_DECISION", "Expired: the organisation did not decide in time."],
    ["CONTACT_NOT_MADE", "Expired: first contact was not made in time."],
    ["NO_DEV_RESPONSE", "Expired: the developer did not answer in time."],
  ] as const)("says an expiry (%s) in words, in the ended tone", (reason, words) => {
    renderWithIntl(<WhoseTurn detail={detail({ state: "EXPIRED", end_reason: reason, whose_turn: [], awaiting: [], due: null })} />);
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(banner.getAttribute("data-whose-turn")).toBe("ended");
    expect(banner.getAttribute("data-callout")).toBe("neutral");
    expect(banner.querySelector("[data-mark='ended']")).not.toBeNull();
    expect(screen.getByText("This engagement has ended.")).toBeTruthy();
    expect(banner.querySelector("[data-side='expired']")?.textContent).toBe(words);
    expect(screen.queryByText(/^Reason:/)).toBeNull();
  });

  it("says the question was answered, with the answer, once the stage resumed with its moved deadline", () => {
    const answer = { kind: "info_answer" as const, body: "Kipkelion and Olenguruone.", by: "developer" as const, at: "2026-10-05T09:00:00Z", resume_at: null };
    renderWithIntl(
      <WhoseTurn
        detail={detail({
          my_party: "org",
          state: "UNDER_REVIEW",
          stage_entered_at: answer.at,
          whose_turn: ["org"],
          awaiting: [{ command: "approve", party: "org" }],
          due: { due_on: "2026-10-20", business_days_left: 11, overdue: false },
          notes: [asked, answer],
        })}
      />,
    );
    const banner = document.querySelector("[data-whose-turn]")!;
    expect(banner.querySelector("[data-side='answered']")?.textContent).toBe("Question answered on 5 Oct 2026: Kipkelion and Olenguruone.");
    expect(banner.querySelector("[data-due]")?.textContent).toBe("11 business days left, due 20 Oct 2026");
  });
});

describe("the stepper through a side state", () => {
  it("keeps the stage it paused from as the current step, on hold, never an extra step", () => {
    const steps = stepperSteps({ state: "INFO_REQUESTED", stage_group: null, due: null, paused_from: "SUBMITTED" });
    renderWithIntl(<Stepper steps={steps} detail={<span>Now: Information requested</span>} />);
    const items = within(screen.getByRole("list", { name: "Stages" })).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0].getAttribute("aria-current")).toBe("step");
    expect(items[0].getAttribute("data-state")).toBe("onHold");
    // Its own word: an open question is the developer's turn, not a hold (the mark says the clock is paused).
    expect(items[0].textContent).toContain("Waiting for an answer");
    expect(items[0].textContent).not.toContain("On hold");
    expect(items[0].textContent).toContain("Now: Information requested");
  });

  it("says On hold for a hold, once", () => {
    const steps = stepperSteps({ state: "ON_HOLD", stage_group: null, due: null, paused_from: "NEGOTIATION" });
    renderWithIntl(<Stepper steps={steps} />);
    const current = screen.getByRole("list", { name: "Stages" }).querySelector("[aria-current='step']")!;
    expect(current.textContent).toBe("AgreementOn hold");
  });
});

describe("the side states' texts on the History tab", () => {
  it("shows each note under its event, in order, as plain text", () => {
    const base = history().events[1];
    const h = history({
      events: [
        ...history().events,
        { ...base, id: "q", seq: 3, command: "request_info", from_state: "UNDER_REVIEW", to_state: "INFO_REQUESTED" },
        { ...base, id: "a", seq: 4, command: "answer_info", actor_role: "developer", actor_name: "Achieng Otieno", from_state: "INFO_REQUESTED", to_state: "UNDER_REVIEW" },
        { ...base, id: "p", seq: 5, command: "pause", from_state: "UNDER_REVIEW", to_state: "ON_HOLD" },
        { ...base, id: "r", seq: 6, command: "resume", actor_role: "system", actor_name: null, actor_user_id: null, from_state: "ON_HOLD", to_state: "UNDER_REVIEW" },
        { ...base, id: "x", seq: 7, command: "expire", actor_role: "system", actor_name: null, actor_user_id: null, from_state: "UNDER_REVIEW", to_state: "EXPIRED" },
      ],
    });
    const notes = [
      { kind: "info_request" as const, body: "Which co-ops?\n<i>Two</i> or more?", by: "org" as const, at: "2026-10-01T07:00:00Z", resume_at: null },
      { kind: "info_answer" as const, body: "Kipkelion and Olenguruone.", by: "developer" as const, at: "2026-10-05T09:00:00Z", resume_at: null },
      { kind: "hold" as const, body: "Budget committee", by: "org" as const, at: "2026-10-06T08:00:00Z", resume_at: "2026-10-21" },
    ];
    renderWithIntl(<HistoryList history={h} notes={notes} />);
    const rows = [...document.querySelectorAll("[data-event]")];
    expect(rows.map((r) => r.getAttribute("data-event"))).toEqual([
      "expire",
      "resume",
      "pause",
      "answer_info",
      "request_info",
      "start_review",
      "create",
    ]);
    expect(rows[0].textContent).toContain("Expired");
    expect(rows[0].textContent).toContain("Platform");
    expect(rows[1].textContent).toContain("Resumed");
    expect(rows[1].querySelector("[data-note]")).toBeNull(); // the system's resume writes none
    expect(rows[2].querySelector("[data-note='hold']")?.textContent).toBe("Reason, until 21 Oct 2026Budget committee");
    expect(rows[3].querySelector("[data-note='info_answer']")?.textContent).toBe("AnswerKipkelion and Olenguruone.");
    const question = rows[4].querySelector("[data-note='info_request']")!;
    expect(rows[4].textContent).toContain("Information requested");
    expect(question.textContent).toBe("QuestionWhich co-ops?\n<i>Two</i> or more?");
    expect(question.querySelector("i, a")).toBeNull();
  });
});

// ux round: a list row never states a deadline nobody has. A hold says when it resumes; an open question, on the
// organisation's side, is the developer's answer-by date.
describe("the deadline line of list rows in a side state", () => {
  const held = summary({
    state: "ON_HOLD",
    stage_label: "On hold",
    stage_group: null,
    paused_from: "NEGOTIATION",
    whose_turn: [],
    due: { due_on: "2026-10-09", business_days_left: 5, overdue: false },
  });
  const asked = summary({
    state: "INFO_REQUESTED",
    stage_label: "Information requested",
    stage_group: null,
    paused_from: "UNDER_REVIEW",
    whose_turn: ["developer"],
    due: { due_on: "2026-10-16", business_days_left: 10, overdue: false },
  });

  it.each(["developer", "org"] as const)("says when a hold resumes, never a countdown (%s)", (mine) => {
    const { container } = renderWithIntl(<EngagementRow item={held} mine={mine} href="/x" />);
    expect(container.querySelector("[data-due]")?.textContent).toBe("Resumes 9 Oct 2026");
    expect(container.textContent).not.toContain("business days left");
    cleanup();
    const card = renderWithIntl(<EngagementCard item={held} mine={mine} href="/x" />);
    expect(card.container.querySelector("[data-due]")?.textContent).toBe("Resumes 9 Oct 2026");
  });

  it("names the developer as the one who owes an open question's answer, for the organisation", () => {
    const { container } = renderWithIntl(<EngagementRow item={asked} mine="org" href="/x" />);
    expect(container.querySelector("[data-due]")?.textContent).toBe("Answer from Achieng Otieno due by 16 Oct 2026");
    cleanup();
    const late = renderWithIntl(
      <EngagementRow item={{ ...asked, due: { due_on: "2026-10-16", business_days_left: -1, overdue: true } }} mine="org" href="/x" />,
    );
    expect(late.container.querySelector("[data-due='overdue']")?.textContent).toBe("Answer from Achieng Otieno was due 16 Oct 2026");
  });

  it("keeps the countdown for the developer, whose answer it is", () => {
    const { container } = renderWithIntl(<EngagementRow item={asked} mine="developer" href="/x" />);
    expect(container.querySelector("[data-due]")?.textContent).toBe("10 business days left, due 16 Oct 2026");
  });

  it("keeps the banner's dates whole on one line", () => {
    const hold = { kind: "hold" as const, body: "Budget", by: "org" as const, at: "2026-10-02T08:00:00Z", resume_at: "2026-10-09", seq: 4 };
    renderWithIntl(
      <WhoseTurn detail={detail({ ...held, notes: [hold], awaiting: [], my_party: "developer" })} />,
    );
    const side = document.querySelector("[data-side='hold']")!;
    expect([...side.querySelectorAll(".whitespace-nowrap")].map((n) => n.textContent)).toEqual(["9 Oct 2026"]);
  });
});

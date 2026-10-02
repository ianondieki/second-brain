import { DevNav } from "@/components/DevNav";
import { OrgNav } from "@/components/OrgNav";
import { SignedInShell } from "@/components/SignedInShell";
import { EngagementScreen } from "@/components/tracker/EngagementScreen";
import type { Detail } from "@/components/tracker/model";

import { DETAIL, ME } from "../fixtures";

/** The tracker's side states (REQ-ENG-10 part) on the fixture engagement: `?variant=question|question-org|hold|answered`. */
const QUESTION = {
  kind: "info_request" as const,
  body: "Which co-ops ran the pilot, and how many litres a day did the chillers hold?\nA rough figure is enough.",
  by: "org" as const,
  at: "2026-10-01T07:00:00Z",
  resume_at: null,
};
const ANSWER = {
  kind: "info_answer" as const,
  body: "Kipkelion and Olenguruone, about 1,200 litres a day between them over six weeks.",
  by: "developer" as const,
  at: "2026-10-05T09:00:00Z",
  resume_at: null,
};
const REVIEW = { ...DETAIL, contact: null, documents: [] };

export const TRACKER_VARIANTS: Record<string, Detail> = {
  question: {
    ...REVIEW,
    state: "INFO_REQUESTED",
    stage_label: "Information requested",
    stage_group: null,
    paused_from: "UNDER_REVIEW",
    whose_turn: ["developer"],
    awaiting: [{ command: "answer_info", party: "developer" }],
    actions: ["answer_info", "withdraw"],
    due: { due_on: "2026-10-15", business_days_left: 9, overdue: false },
    notes: [QUESTION],
  },
  "question-org": {
    ...REVIEW,
    my_party: "org",
    my_roles: ["signatory"],
    state: "INFO_REQUESTED",
    stage_label: "Information requested",
    stage_group: null,
    paused_from: "UNDER_REVIEW",
    whose_turn: ["developer"],
    awaiting: [{ command: "answer_info", party: "developer" }],
    actions: ["cancel_request"],
    due: { due_on: "2026-10-15", business_days_left: 9, overdue: false },
    notes: [QUESTION],
  },
  hold: {
    ...DETAIL,
    state: "ON_HOLD",
    stage_label: "On hold",
    stage_group: null,
    paused_from: "NEGOTIATION",
    whose_turn: [],
    awaiting: [],
    actions: ["resume", "withdraw"],
    due: { due_on: "2026-10-21", business_days_left: 13, overdue: false },
    notes: [{ kind: "hold", body: "Our budget committee meets on 20 October.", by: "org", at: "2026-10-02T08:00:00Z", resume_at: "2026-10-21" }],
  },
  answered: {
    ...REVIEW,
    my_party: "org",
    my_roles: ["signatory"],
    state: "UNDER_REVIEW",
    stage_label: "Under review",
    stage_group: "review",
    stage_entered_at: ANSWER.at,
    whose_turn: ["org"],
    awaiting: [{ command: "approve", party: "org" }],
    actions: ["request_info", "pause", "decline"],
    due: { due_on: "2026-10-20", business_days_left: 11, overdue: false },
    notes: [QUESTION, ANSWER],
    side_limits: { questions_left: 1, holds_left: 2, hold_days_left: 60 },
    today: "2026-10-05",
  },
};

/** The real tracker (components/tracker/EngagementScreen) on a fixture engagement: both parties owe the NDA. */
export function TrackerScreen({ variant }: { variant?: string }) {
  const detail = (variant && TRACKER_VARIANTS[variant]) || DETAIL;
  const org = detail.my_party === "org";
  return (
    <SignedInShell homeHref={org ? "/org" : "/dev"} nav={org ? <OrgNav current="engagements" /> : <DevNav current="engagements" />} wide>
      <EngagementScreen detail={detail} me={ME} tab="tracker" doc={null} basePath={org ? "/org/engagements" : "/dev/engagements"} />
    </SignedInShell>
  );
}

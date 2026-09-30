import type { Detail, History, Summary } from "@/components/tracker/model";

// Engagement fixtures for the tracker's tests (REQ-ENG-03), shaped like GET /api/engagements/{id} answers.

export const ENGAGEMENT_ID = "0199b000-0000-7000-8000-00000000e001";
export const DEV_ID = "0199b000-0000-7000-8000-00000000d001";
export const ORG_ID = "0199b000-0000-7000-8000-00000000c001";
export const SIGNATORY_ID = "0199b000-0000-7000-8000-00000000c002";

export function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    id: ENGAGEMENT_ID,
    proposal_id: "0199b000-0000-7000-8000-00000000f001",
    version_id: "0199b000-0000-7000-8000-00000000f002",
    proposal_title: "Cold chain for dairy co-ops",
    org_id: ORG_ID,
    org_name: "Telco A (fixture)",
    developer_id: DEV_ID,
    developer_name: "Achieng Otieno",
    developer_named: true,
    origin: "tagged",
    state: "SUBMITTED",
    stage_label: "Proposal submitted",
    stage_group: "review",
    end_reason: null,
    stage_entered_at: "2026-09-23T11:05:00Z",
    stage_deadline_at: "2026-10-07T20:59:59Z",
    due: { due_on: "2026-10-07", business_days_left: 8, overdue: false },
    ended_at: null,
    lock_version: 3,
    whose_turn: ["org"],
    updated_at: "2026-09-23T11:05:00Z",
    ...overrides,
  };
}

export function detail(overrides: Partial<Detail> = {}): Detail {
  return {
    ...summary(),
    my_party: "developer",
    my_roles: ["developer"],
    actions: ["withdraw"],
    awaiting: [{ command: "start_review", party: "org" }],
    contact: null,
    endorsements: [],
    agreements: [],
    signatures: [],
    payments: [],
    documents: [],
    ...overrides,
  };
}

/** An engagement in implementation with a signed agreement of two milestones. */
export function inImplementation(overrides: Partial<Detail> = {}): Detail {
  return detail({
    state: "IN_IMPLEMENTATION",
    stage_label: "Agreement signed: implementation",
    stage_group: "implementation",
    due: null,
    whose_turn: ["developer", "org"],
    awaiting: [
      { command: "start_milestone", party: "developer" },
      { command: "accept_milestone", party: "org" },
    ],
    actions: ["start_milestone"],
    agreements: [
      {
        id: "0199b000-0000-7000-8000-00000000a001",
        version: 2,
        status: "signed",
        ip_terms: "non_exclusive_licence",
        exclusivity: null,
        deemed_acceptance_days: 0,
        document_sha256: "3f5a9c017be2aa00",
        drafted_by: "org",
        created_at: "2026-09-24T07:00:00Z",
        milestones: [
          {
            id: "0199b000-0000-7000-8000-0000000000m1",
            seq: 1,
            deliverable: "Pilot at two co-ops",
            amount_kes_minor: 25_000_000,
            due_date: "2026-10-30",
            review_window_bd: 5,
            state: "SUBMITTED_FOR_REVIEW",
            review_due_on: "2026-10-09",
          },
          {
            id: "0199b000-0000-7000-8000-0000000000m2",
            seq: 2,
            deliverable: "Roll-out to ten co-ops",
            amount_kes_minor: 100_000_000,
            due_date: "2026-12-15",
            review_window_bd: 10,
            state: "PLANNED",
            review_due_on: null,
          },
        ],
      },
    ],
    ...overrides,
  });
}

export function history(overrides: Partial<History> = {}): History {
  return {
    engagement_id: ENGAGEMENT_ID,
    chain_verified: true,
    endorsements: [],
    events: [
      {
        id: "0199b000-0000-7000-8000-0000000000e1",
        seq: 1,
        created_at: "2026-09-23T11:05:00Z",
        actor_user_id: DEV_ID,
        actor_name: "Achieng Otieno",
        actor_role: "developer",
        command: "create",
        from_state: null,
        to_state: "SUBMITTED",
        end_reason: null,
        hash: "a".repeat(64),
        prev_hash: "0".repeat(64),
        payload: {},
        stage_deadline_at: null,
      },
      {
        id: "0199b000-0000-7000-8000-0000000000e2",
        seq: 2,
        created_at: "2026-09-24T06:30:00Z",
        actor_user_id: SIGNATORY_ID,
        actor_name: "Rita Wanjiru",
        actor_role: "signatory",
        command: "start_review",
        from_state: "SUBMITTED",
        to_state: "UNDER_REVIEW",
        end_reason: null,
        hash: "b".repeat(64),
        prev_hash: "a".repeat(64),
        payload: {},
        stage_deadline_at: null,
      },
    ],
    ...overrides,
  };
}

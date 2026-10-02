import type { Brief, BriefList } from "@/app/(app)/org/briefs";
import type { DiscoverBrief } from "@/app/(app)/dev/discover/discover";

// Problem Brief fixtures for the P19-B screens' tests (REQ-DIR-05), shaped like the API's BriefOut, BriefList and
// DiscoverBrief (backend/openapi.json) for Telco A (fixture).

export const ORG_ID = "01a0ee62-0000-7000-8000-00000000000a";
export const ORG_NAME = "Telco A (fixture)";
export const BRIEF_ID = "01a0f070-0000-7000-8000-000000000001";
export const NICHE = { id: "01a0f067-99ac-71a6-8c49-822887f625e2", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" };
export const BAND = { code: "kes_100k_1m", label: "KES 100,000 – 1,000,000" };

export function brief(extra: Partial<Brief> = {}): Brief {
  return {
    id: BRIEF_ID,
    title: "Tower sites go dark when fuel runs out",
    statement: "Field teams learn about empty generator tanks only after the site stops working.",
    affected_group: "Rural subscribers",
    niche: NICHE,
    country: "KE",
    county_code: "KE-30",
    budget_band: BAND,
    deadline: "2026-11-30",
    created_at: "2026-10-01T07:00:00Z",
    published_at: null,
    proposal_count: 0,
    problem_status: "pending_review",
    moderation_state: "clear",
    state: "in_review",
    status: "published",
    visibility: "public",
    ...extra,
  };
}

export function briefList(extra: Partial<BriefList> = {}): BriefList {
  return {
    items: [brief()],
    next_cursor: null,
    plan: { plan: "org_claimed", problem_briefs: 1, used: 1 },
    budget_bands: [BAND, { code: "kes_1m_5m", label: "KES 1,000,000 – 5,000,000" }],
    ...extra,
  };
}

export function discoverBrief(extra: Partial<DiscoverBrief> = {}): DiscoverBrief {
  const org = { id: ORG_ID, slug: "telco-a-fixture", name: ORG_NAME };
  return {
    problem: {
      id: BRIEF_ID,
      title: "Tower sites go dark when fuel runs out",
      source: "org_brief",
      label: `Posted by ${ORG_NAME}`,
      niche: NICHE,
      statement: "Field teams learn about empty generator tanks only after the site stops working.",
      country: "KE",
      county_code: "KE-30",
      published_at: "2026-10-01T09:00:00+03:00",
      seeded_example: false,
      org,
    },
    brief: { org, budget_band: BAND, deadline: "2026-11-30", open: true },
    proposal_count: 2,
    ...extra,
  };
}

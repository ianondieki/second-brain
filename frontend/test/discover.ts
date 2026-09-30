import type { TrendingProblem, TrendingProject } from "@/app/(app)/dev/discover/discover";
import type { Recommendation, Recommendations } from "@/app/(app)/dev/discover/recommendations";

// Discover and "Recommended for you" fixtures for the P12-F tests (REQ-TREND-02, REQ-PERS-01), shaped like the demo
// seed's answers from GET /api/discover/trending and GET /api/me/recommendations.

export const PROBLEM_ID = "01a0f067-b61f-7121-8f83-4293f5a2c7cd";
export const PROJECT_ID = "01a0f067-b5c5-721c-9fcf-24dd3d70b42e";
export const TELECOMS = { id: "01a0f067-99ac-71a6-8c49-822887f625e2", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" };
export const BADGE = "Trending in ICT › Networks & Telecommunications · Kenya: 4 companies scouting, 1 new proposal";

export function trendingProblem(overrides: Partial<TrendingProblem> = {}): TrendingProblem {
  return {
    problem: {
      id: PROBLEM_ID,
      title: "Tower sites go down when generators run dry",
      source: "developer",
      label: "Developer-reported",
      niche: TELECOMS,
      statement: "Operators of off-grid tower sites learn about empty fuel tanks only after the site stops working.",
      country: "KE",
      county_code: null,
      published_at: "2026-09-30T06:42:03+03:00",
    },
    trend: { trending: true, new_this_week: true, z: 2.5, score: 35.9, badge: BADGE },
    why: ["4 companies scouting", "1 new proposal this month", "New this week"],
    sources: [
      {
        url: "https://www.ca.go.ke/report",
        publisher: "Communications Authority of Kenya",
        source_type: "official",
        published_date: "2026-09-28",
        retrieved_at: "2026-09-29T00:00:00+03:00",
        quote: "Off-grid sites reported more fuel-related outages this quarter.",
      },
    ],
    proposal_count: 1,
    project_ids: [PROJECT_ID],
    ...overrides,
  };
}

export function trendingProject(overrides: Partial<TrendingProject> = {}): TrendingProject {
  return {
    proposal: {
      id: PROJECT_ID,
      owner_handle: "amina-wanjiru-a1baf8",
      cert_id: "WYP2C35185CQF7K3",
      version_no: 1,
      published_at: "2026-09-30T06:42:03+03:00",
      teaser: {
        title: "Fuel-level alerts for off-grid tower sites",
        niche: TELECOMS,
        country: "KE",
        county_code: null,
        maturity: "mvp",
        ask: "licence",
        problem_statement: "Generators at off-grid tower sites run dry.",
        impact_claims: null,
        summary: "A low-cost sensor kit reports each tank's level every hour.",
      },
    },
    problem: {
      id: PROBLEM_ID,
      title: "Tower sites go down when generators run dry",
      source: "developer",
      label: "Developer-reported",
      niche: TELECOMS,
    },
    trend: { trending: true, new_this_week: true, badge: "Trending in ICT › Networks & Telecommunications" },
    why: ["Verified organisations expressed interest", "Solves a trending problem", "New this week"],
    ...overrides,
  };
}

export function recommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    problem: {
      id: "01a0f067-d873-7f06-941f-2e211f23caf3",
      title: "Clinics must move claims onto the national digital health system",
      source: "research_agent",
      label: "AI-drafted, human-reviewed on 30 September 2026",
      niche: { id: "01a0f067-9996-7360-a92b-49e34d57ce92", slug: "health", label: "Health" },
      statement: "Healthcare providers must integrate their systems.",
      country: "KE",
      county_code: null,
      published_at: "2026-09-30T06:42:03+03:00",
    },
    position: 1,
    score: 71,
    label: "Good fit",
    exploring: false,
    pursuit: { decision: "pursue", label: "Pursue", reasons: ["Trending in its niche", "Good fit for you"] },
    why: ["In a niche you like", "Trending in its niche", "Backed by cited sources"],
    why_not: null,
    trend: { trending: false, new_this_week: true, z: 1.2, score: 4, badge: null },
    ...overrides,
  } as Recommendation; // `features` is not read by the screens (its shape is P12-B's to tighten)
}

export function recommendations(overrides: Partial<Recommendations> = {}): Recommendations {
  return {
    generated_at: "2026-09-30T06:42:45+03:00",
    ranker_version: "hybrid-v1",
    personalised: false,
    liked_niches: [{ id: "01a0f067-9996-7360-a92b-49e34d57ce92", slug: "health", label: "Health" }],
    items: [recommendation()],
    ...overrides,
  };
}

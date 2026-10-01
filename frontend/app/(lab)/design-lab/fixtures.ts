import type { Recommendation, RecommendationsState } from "@/app/(app)/dev/discover/recommendations";
import type { MyProposal, MyProposalItem } from "@/app/(app)/dev/ideas/ideas";
import type { EvaluationNda, TeaserCard } from "@/app/(app)/org/data";
import type { Detail, Summary } from "@/components/tracker/model";
import type { Me } from "@/lib/auth/routing";

// Fixture data for the design lab, shaped like the API's answers (lib/api/schema.d.ts). Lab only: never imported by
// a product screen (test/ fixtures cannot be imported under app/, so these are the lab's own copies). Every figure is
// a demo figure and the screens label them so.

export const PLACEHOLDER_NAME = "Wazo";

export const ME: Me = {
  side: "developer",
  memberships: [],
  mfa: { enrolled: true, required: false, verified: true },
  user: {
    id: "0199b000-0000-7000-8000-00000000d001",
    display_name: "Achieng Otieno",
    email: "achieng@example.test",
    email_verified: true,
    locale: "en",
    password_set: true,
    staff_role: null,
    totp_enabled: true,
  },
};

const PROPOSAL_ID = "0199b000-0000-7000-8000-00000000f001";
export const CERT_ID = "WYP2C35185CQF7K3";
export const SHA256 = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";

const NICHE = { id: "01a0f067-99ac-71a6-8c49-822887f625e2", slug: "agri-cold-chain", label: "Agriculture › Cold chain" };
const TELECOMS = { id: "01a0f067-99ac-71a6-8c49-822887f625e3", slug: "networks-telecommunications", label: "ICT › Networks & Telecommunications" };
const HEALTH = { id: "01a0f067-9996-7360-a92b-49e34d57ce92", slug: "health", label: "Health" };

export function summary(overrides: Partial<Summary> = {}): Summary {
  return {
    id: "0199b000-0000-7000-8000-00000000e001",
    proposal_id: PROPOSAL_ID,
    version_id: "0199b000-0000-7000-8000-00000000f002",
    proposal_title: "Cold chain for dairy co-ops",
    org_id: "0199b000-0000-7000-8000-00000000c001",
    org_name: "Telco A (fixture)",
    developer_id: ME.user.id,
    developer_name: ME.user.display_name,
    developer_named: true,
    origin: "tagged",
    state: "NDA_PENDING",
    stage_label: "Mutual NDA",
    stage_group: "contact_nda",
    end_reason: null,
    stage_entered_at: "2026-09-28T09:05:00Z",
    stage_deadline_at: "2026-10-07T20:59:59Z",
    due: { due_on: "2026-10-07", business_days_left: 4, overdue: false },
    ended_at: null,
    lock_version: 7,
    whose_turn: ["developer", "org"],
    updated_at: "2026-09-30T11:05:00Z",
    ...overrides,
  };
}

/** The tracker's engagement: both parties owe the mutual NDA, the developer's turn too. */
export const DETAIL: Detail = {
  ...summary(),
  my_party: "developer",
  my_roles: ["developer"],
  actions: ["sign_nda", "withdraw"],
  awaiting: [
    { command: "sign_nda", party: "developer" },
    { command: "sign_nda", party: "org" },
  ],
  contact: { channel: "email", contact_by: "2026-10-02", name: "Wanjiru Kamau", role: "Head of partnerships", user_id: "0199b000-0000-7000-8000-00000000c002" },
  endorsements: [],
  agreements: [],
  signatures: [],
  payments: [],
  documents: [],
};

export const HOME_ENGAGEMENTS: Summary[] = [
  summary(),
  summary({
    id: "0199b000-0000-7000-8000-00000000e002",
    proposal_title: "Fuel-level alerts for off-grid tower sites",
    org_name: "Kenya Towers (fixture)",
    state: "UNDER_REVIEW",
    stage_label: "Under review",
    stage_group: "review",
    whose_turn: ["org"],
    due: { due_on: "2026-10-03", business_days_left: 2, overdue: false },
  }),
  summary({
    id: "0199b000-0000-7000-8000-00000000e003",
    proposal_title: "Clinic claims bridge to the national system",
    org_name: "Jamii Health (fixture)",
    state: "IN_IMPLEMENTATION",
    stage_label: "Agreement signed: implementation",
    stage_group: "implementation",
    whose_turn: [],
    due: null,
  }),
];

export const IDEAS: MyProposalItem[] = [
  { id: PROPOSAL_ID, title: "Cold chain for dairy co-ops", status: "published", moderation_state: "clear", niche: NICHE, cert_id: CERT_ID, current_version_no: 2, has_draft: false, published_at: "2026-09-20T07:10:00Z", updated_at: "2026-09-28T09:05:00Z" },
  { id: "0199b000-0000-7000-8000-00000000f011", title: "Fuel-level alerts for off-grid tower sites", status: "published", moderation_state: "clear", niche: TELECOMS, cert_id: "K3Q9C2M7X1P4T8R6", current_version_no: 1, has_draft: true, published_at: "2026-09-25T06:42:00Z", updated_at: "2026-09-29T14:20:00Z" },
  { id: "0199b000-0000-7000-8000-00000000f012", title: "Boda fleet maintenance reminders", status: "draft", moderation_state: "clear", niche: null, cert_id: null, current_version_no: null, has_draft: true, published_at: null, updated_at: "2026-09-30T18:00:00Z" },
];

const features = (): Recommendation["features"] =>
  Object.fromEntries(
    ["semantic_fit", "niche_match", "region_match", "skill_coverage", "trend", "evidence_confidence", "market_pull", "crowding", "track_record", "freshness"].map((name) => [
      name,
      { raw: null, value: null, weight: 0, applies: false },
    ]),
  ) as Recommendation["features"];

export const RECOMMENDATIONS: RecommendationsState = {
  kind: "list",
  personalised: true,
  more: true,
  items: [
    {
      problem: { id: "01a0f067-d873-7f06-941f-2e211f23caf3", title: "Clinics must move claims onto the national digital health system", source: "research_agent", label: "AI-drafted, human-reviewed on 30 September 2026", niche: HEALTH, statement: "Providers must integrate their systems with the national claims platform.", country: "KE", county_code: null, published_at: "2026-09-30T06:42:03+03:00", seeded_example: true },
      position: 1,
      score: 71,
      label: "Good fit",
      exploring: false,
      pursuit: { decision: "pursue", label: "Pursue", reasons: ["Trending in its niche", "Good fit for you"] },
      why: ["In a niche you like", "Trending in its niche", "Backed by cited sources"],
      why_not: null,
      trend: { trending: true, new_this_week: true, z: 2.1, score: 9, badge: "Trending in Health · Kenya: 3 companies scouting" },
      features: features(),
    },
    {
      problem: { id: "01a0f067-b61f-7121-8f83-4293f5a2c7cd", title: "Tower sites go down when generators run dry", source: "developer", label: "Developer-reported", niche: TELECOMS, statement: "Operators learn about empty fuel tanks only after the site stops working.", country: "KE", county_code: null, published_at: "2026-09-29T06:42:03+03:00", seeded_example: true },
      position: 2,
      score: 64,
      label: "Strong fit",
      exploring: false,
      pursuit: { decision: "consider", label: "Consider", reasons: ["Two proposals already compete"] },
      why: ["Matches your published idea", "4 companies scouting"],
      why_not: "Two proposals already compete for it.",
      trend: { trending: true, new_this_week: false, z: 1.4, score: 6, badge: null },
      features: features(),
    },
  ],
};

export const IDEA: MyProposal = {
  id: PROPOSAL_ID,
  status: "published",
  moderation: { state: "clear", message: null },
  published_at: "2026-09-20T07:10:00Z",
  hidden_at: null,
  draft: null,
  current: {
    id: "0199b000-0000-7000-8000-00000000f002",
    version_no: 2,
    status: "registered",
    cert_id: CERT_ID,
    registered_at: "2026-09-28T09:05:12Z",
    provenance: { status: "timestamped", label: "Timestamped", verify_path: `/verify/${CERT_ID}` },
    problems: [],
    new_problem: null,
    teaser: {
      title: "Cold chain for dairy co-ops",
      niche: NICHE,
      country: "KE",
      county_code: "022",
      maturity: "mvp",
      ask: "pilot",
      problem_statement: "Evening milk collections spoil before the morning truck reaches the co-op's cooler.",
      summary: "Solar-chilled collection points with a shared cooling schedule and SMS pickup alerts, built with two Kiambu co-ops.",
      impact_claims: "Pilot data: 11% less spoilage over six weeks (demo figure).",
    },
    confidential: { approach: null, architecture: null, pricing: null, notes: null, links: [], attachments: [] },
  },
};

export const TEASER: TeaserCard = {
  id: PROPOSAL_ID,
  cert_id: CERT_ID,
  owner_handle: "achieng-otieno-7f2a1c",
  registered_at: "2026-09-28T09:05:12Z",
  version_no: 2,
  provenance: { status: "timestamped", label: "Timestamped", verify_path: `/verify/${CERT_ID}` },
  problems: [],
  teaser: IDEA.current!.teaser,
};

export const NDA: EvaluationNda = {
  template_id: "0199b000-0000-7000-8000-00000000a001",
  version: "v1",
  sha256: SHA256,
  acceptance_id: null,
  accepted_at: null,
  is_placeholder: true,
  logging_notice: {
    version: "2026-09",
    text: "Each opening of the full proposal is recorded with your name, your organisation and the time, and the developer can see that record.",
  },
  body:
    "Evaluation NDA (fixture text for the design lab; the real wording is set by the owner, D-39).\n\n" +
    "1. Purpose. The organisation receives the full proposal only to evaluate it for a possible engagement.\n\n" +
    "2. Confidentiality. The organisation keeps the full proposal confidential, shares it only with the people who evaluate it, and does not build from it without a signed agreement.\n\n" +
    "3. Record. The platform records every opening and shows that record to the developer.\n\n" +
    "4. Term. These obligations last two years from the first opening.",
};

export const EMAIL = {
  subject: `Your day on ${PLACEHOLDER_NAME} (Thu 1 Oct): 2 things need you`,
  headline: "Good morning Achieng. Two engagements wait on you today, one deadline is close.",
  sections: [
    { title: "Needs you", lines: ["Sign the mutual NDA with Telco A (fixture) — due Tuesday 7 October", "Reply to Jamii Health (fixture) on milestone 2"] },
    { title: "Waiting on others", lines: ["Kenya Towers (fixture) is reviewing Fuel-level alerts for off-grid tower sites (2 business days left)"] },
  ],
  nextStep: "Open the tracker and sign the NDA: it takes about a minute with your authenticator.",
  cta: "Open your tracker",
  footer: "You get this daily reminder because reminders are on for your account. Sent from Nairobi, 07:30 EAT.",
};

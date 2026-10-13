import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import AdminEventPage from "./events/[id]/page";
import NewPlatformEventPage from "./events/new/page";
import AdminEventsPage from "./events/page";
import QuizSetPage from "./quiz/[id]/page";
import ReviewPage from "./research/candidates/[id]/page";
import ResearchPage from "./research/page";
import TrendReviewPage from "./research/trends/[id]/page";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD): in the public demo staff are read-only (the API answers every staff
// write with 403 public_demo_locked). Each screen region that would hold a decision or a create form shows the locked
// line instead, once per region (never once per row); the queues and the detail views still read. With the mode off,
// every control is where it was. The controls are stand-ins here: each draws a marker this test looks for. A decision
// region says "Deciding is switched off" (the card or case still reads); a run, a draft or a create form, where the whole
// feature is off, keeps the generic line (ux review of P28-PD, MAJOR 1).

const LOCKED = en.publicDemo.locked;
const DECIDE = en.publicDemo.decideLocked;

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
  getMessages: async () => en,
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  notFound: () => {
    throw new Error("notFound");
  },
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("./AdminShell", () => ({ AdminShell: ({ children }: { children: ReactNode }) => <main>{children}</main> }));
vi.mock("./StaffEyebrow", () => ({ StaffEyebrow: () => null }));
vi.mock("./staff", () => ({ staffContext: async () => ({ me: {}, role: "admin" }) }));
vi.mock("./strings", () => ({ stepUpStrings: async () => ({}) }));

vi.mock("./research/StartRun", async () => ({ StartRun: await marker("start-run") }));
vi.mock("./research/trends/DraftTrends", async () => ({ DraftTrends: await marker("draft-trends") }));
vi.mock("./research/Decision", async () => ({ Decision: await marker("candidate-decision") }));
vi.mock("./research/trends/TrendDecision", async () => ({ TrendDecision: await marker("trend-decision") }));
vi.mock("./quiz/SetDecision", async () => ({ SetDecision: await marker("set-decision") }));
vi.mock("./quiz/QuestionActions", async () => ({ QuestionActions: await marker("question-actions") }));
vi.mock("./events/EventDecision", async () => ({ EventDecision: await marker("event-decision") }));
vi.mock("@/components/events/CancelEvent", async () => ({ CancelEvent: await marker("cancel-event") }));
vi.mock("@/components/events/EventForm", async () => ({ EventForm: await marker("event-form") }));
vi.mock("@/app/(app)/org/scout-data", () => ({ getCounties: async () => [] }));

/** A stand-in for a control: an element with its name, to find on the page. */
async function marker(name: string) {
  const { createElement } = await import("react");
  return () => createElement("i", { "data-control": name });
}
const fx = vi.hoisted(() => {
  const NICHE = { id: "01a0f000-0000-7000-8000-0000000000b1", slug: "dairy", name: "Dairy", label: "Dairy", parent_slug: null, isic_code: null, active: true, sort_order: 1 };
  const CANDIDATE = {
    id: "01a0f000-0000-7000-8000-0000000000c1",
    title: "Milk spoils before collection",
    statement: "Cooling at collection points fails in the afternoon.",
    affected_group: "Dairy farmers",
    niche: "dairy",
    country: "KE",
    county_code: null,
    confidence: "0.8",
    research_run_id: null,
    created_at: "2026-10-01T07:00:00Z",
    seeded_example: true,
    named_orgs: [],
    checklist: [],
    sources: [],
  };
  const TREND = {
    id: "01a0f000-0000-7000-8000-0000000000f1",
    title: "Edge caching for rural schools",
    summary: "Schools cache lessons locally.",
    topic_slug: "edge",
    status: "candidate",
    confidence: "0.7",
    named_orgs: [],
    llm_trace_id: null,
    created_at: "2026-10-01T07:00:00Z",
    decided_at: null,
    published_at: null,
    sources: [],
  };
  const QUESTION = (position: number) => ({
    id: `01a0f000-0000-7000-8000-00000000000${position}`,
    position,
    prompt: `Question ${position}?`,
    options: ["A", "B", "C"],
    answer: 0,
    why: "Because.",
    topic: "ict",
    source_id: "s1",
    source_title: "Source",
    source_url: "https://example.org/source",
    status: "live",
    pulled_at: null,
    pulled_reason: null,
    restored_at: null,
    flags: 0,
    flag_reasons: {},
    notes: [],
  });
  const SET = {
    id: "01a0f000-0000-7000-8000-0000000000a1",
    quiz_date: "2099-01-01",
    status: "draft",
    origin: "seeded",
    created_at: "2026-10-01T07:00:00Z",
    flags: 0,
    pulled: 0,
    decided_by: null,
    decided_at: null,
    llm_trace_id: null,
    stats: { attempts: 0, average_score: null, per_question_correct: null },
    questions: [QUESTION(1), QUESTION(2), QUESTION(3)],
  };
  const EVENT = (status: "draft" | "published") => ({
    id: "01a0f000-0000-7000-8000-0000000000e1",
    org_id: null,
    organiser: "Platform",
    title: "Demo day",
    description: "d",
    starts_at: "2099-01-01T07:00:00Z",
    ends_at: "2099-01-01T09:00:00Z",
    online: true,
    venue: null,
    county_code: null,
    county_name: null,
    join_url: "https://meet.example/x",
    link: null,
    status,
    decided_at: null,
    cancelled_at: null,
    created_at: "2026-10-01T07:00:00Z",
    updated_at: "2026-10-01T07:00:00Z",
  });
  return { NICHE, CANDIDATE, TREND, QUESTION, SET, EVENT };
});
const { CANDIDATE, TREND, SET, EVENT } = fx;

const data = vi.hoisted(() => ({ event: null as unknown, events: [] as unknown[] }));
vi.mock("./research/data", () => ({
  getResearch: async () => ({
    kind: "ok",
    data: { runs: [], candidates: [fx.CANDIDATE], sources: {
      as_of: "2026-10-01",
      allowlist: [],
      excerpts: [
        {
          id: "x1",
          niche: "dairy",
          country: "KE",
          url: "https://example.org/x",
          publisher: "Ministry",
          source_type: "official",
          official: true,
          published_date: "2026-09-01",
          retrieved_at: "2026-09-02T07:00:00Z",
          quote: "A quote.",
          topic: "cooling",
          freshness: "fresh",
        },
      ],
    }, niches: [fx.NICHE] },
  }),
  getTrendCandidates: async () => ({ kind: "ok", data: [] }),
  getReview: async () => ({ kind: "ok", data: { candidate: fx.CANDIDATE, niches: [fx.NICHE] } }),
  getTrendCard: async () => ({ kind: "ok", data: fx.TREND }),
}));
vi.mock("./quiz/data", () => ({ getQuizSet: async () => ({ kind: "ok", data: fx.SET }) }));
vi.mock("./events/data", () => ({
  getAdminEvent: async () => ({ kind: "ok", data: data.event }),
  getAdminEvents: async () => ({ kind: "ok", data: data.events }),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

const params = (id: string) => ({ params: Promise.resolve({ id }), searchParams: Promise.resolve({}) }) as never;

/** Renders a page with the mode on or off; answers its locked lines and the controls drawn. */
async function draw(render: () => Promise<ReactNode>, demo: boolean) {
  vi.stubEnv("PUBLIC_DEMO", demo ? "true" : "false");
  cleanup();
  const { container } = renderWithIntl(<>{await resolveServerTree(await render())}</>);
  return {
    container,
    locked: container.querySelectorAll("[data-demo-locked]").length,
    lines: [...container.querySelectorAll("[data-demo-locked]")].map((el) => el.textContent),
    controls: [...container.querySelectorAll("[data-control]")].map((el) => el.getAttribute("data-control")),
  };
}

describe("the staff console in the public demo", () => {
  it("Research: no run and no trend drafting, the queue still listed", async () => {
    const on = await draw(() => ResearchPage(), true);
    expect(on.controls).toEqual([]);
    expect(on.locked).toBe(2); // the run panel and the trends section
    expect(on.lines).toEqual([LOCKED, LOCKED]);
    expect(on.container.textContent).toContain(CANDIDATE.title);
    const off = await draw(() => ResearchPage(), false);
    expect(off.controls.sort()).toEqual(["draft-trends", "start-run"]);
    expect(off.locked).toBe(0);
  });

  it("a research candidate: the card reads, its decision is locked", async () => {
    const on = await draw(() => ReviewPage(params(CANDIDATE.id)), true);
    expect(on.controls).toEqual([]);
    expect(on.lines).toEqual([DECIDE]);
    expect(on.container.textContent).toContain(CANDIDATE.statement);
    expect((await draw(() => ReviewPage(params(CANDIDATE.id)), false)).controls).toEqual(["candidate-decision"]);
  });

  it("a trend card: the card reads, its decision is locked", async () => {
    const on = await draw(() => TrendReviewPage(params(TREND.id)), true);
    expect(on.controls).toEqual([]);
    expect(on.lines).toEqual([DECIDE]);
    expect(on.container.textContent).toContain(TREND.summary);
    expect((await draw(() => TrendReviewPage(params(TREND.id)), false)).controls).toEqual(["trend-decision"]);
  });

  it("a quiz set: one locked line for the questions (not one per question) and one for the decision", async () => {
    const on = await draw(() => QuizSetPage(params(SET.id)), true);
    expect(on.controls).toEqual([]);
    expect(on.lines).toEqual([LOCKED, DECIDE]); // Pull and Restore on the list; the set's decision
    expect(on.container.querySelectorAll("[data-admin-question]")).toHaveLength(3);
    const off = await draw(() => QuizSetPage(params(SET.id)), false);
    expect(off.controls.filter((c) => c === "question-actions")).toHaveLength(3);
    expect(off.controls).toContain("set-decision");
    expect(off.locked).toBe(0);
  });

  it("an event: no decision on a draft, no cancelling a published one", async () => {
    data.event = EVENT("draft");
    const draft = await draw(() => AdminEventPage(params(EVENT("draft").id)), true);
    expect(draft.controls).toEqual([]);
    expect(draft.lines).toEqual([DECIDE]);
    expect((await draw(() => AdminEventPage(params(EVENT("draft").id)), false)).controls).toEqual(["event-decision"]);
    data.event = EVENT("published");
    const published = await draw(() => AdminEventPage(params(EVENT("published").id)), true);
    expect(published.controls).toEqual([]);
    expect(published.lines).toEqual([LOCKED]); // cancelling: not a decision region
    expect((await draw(() => AdminEventPage(params(EVENT("published").id)), false)).controls).toEqual(["cancel-event"]);
  });

  it("events: no \"Post an event\" on the list, and the locked line in place of the form", async () => {
    const list = await draw(() => AdminEventsPage(params("")), true);
    expect(list.container.querySelector('a[href="/admin/events/new"]')).toBeNull();
    expect((await draw(() => AdminEventsPage(params("")), false)).container.querySelector('a[href="/admin/events/new"]')).not.toBeNull();
    const form = await draw(() => NewPlatformEventPage(), true);
    expect(form.controls).toEqual([]);
    expect(form.lines).toEqual([LOCKED]);
    expect((await draw(() => NewPlatformEventPage(), false)).controls).toEqual(["event-form"]);
  });
});

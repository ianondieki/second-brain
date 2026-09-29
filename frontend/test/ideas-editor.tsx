import { act } from "@testing-library/react";
import { vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { Outcome } from "@/app/(app)/dev/ideas/calls";
import {
  type AttestationText,
  type EditorState,
  type MyProposal,
  type NicheNode,
  type ProblemCard,
  type PublishResult,
} from "@/app/(app)/dev/ideas/ideas";
import type { PublishProblem, SaveProblem } from "@/app/(app)/dev/ideas/outcomes";
import { EMPTY_STATE } from "@/app/(app)/dev/ideas/versions";
import { Editor, preloadSteps, type EditorProps } from "@/app/(app)/dev/ideas/editor/Editor";

// Shared fixtures of the editor's component tests (REQ-PROP-01).

export const NICHES: NicheNode[] = [
  {
    id: "0199a000-0000-7000-8000-00000000000a",
    slug: "agriculture",
    name: "Agriculture",
    label: "Agriculture",
    isic_code: null,
    children: [
      {
        id: "0199a000-0000-7000-8000-00000000000b",
        slug: "dairy",
        name: "Dairy",
        label: "Agriculture › Dairy",
        isic_code: null,
      },
    ],
  },
];

export const TEXT: AttestationText = {
  version: "2026-09-29.1",
  sha256: "ab",
  statements: [
    { key: "created_it", text: "I created this proposal." },
    { key: "not_owned_by_employer_or_client", text: "It is not owned by my employer, a university or a client." },
    { key: "no_third_party_confidential", text: "It contains no confidential information that belongs to anyone else." },
  ],
};

export const PROBLEM: ProblemCard = {
  id: "0199a000-0000-7000-8000-000000000101",
  title: "Milk spoils before collection",
  source: "developer",
  label: "Developer-reported",
  niche: null,
  statement: "Co-ops lose a fifth of the evening milk.",
  published_at: "2026-09-28T09:00:00Z",
};

export const READY: EditorState = {
  ...EMPTY_STATE,
  title: "Cold chain for dairy co-ops",
  nicheId: "0199a000-0000-7000-8000-00000000000b",
  maturity: "prototype",
  ask: "pilot",
  problemStatement: "Milk spoils.",
  summary: "Solar chillers.",
  problemMode: "pick",
  problems: [{ id: PROBLEM.id, title: PROBLEM.title, source: "developer", label: null, niche: null }],
};

export const SAVED = { id: "p1", draft: { confidential: { attachments: [] } } } as unknown as MyProposal;

export type Calls = NonNullable<EditorProps["calls"]>;

export function calls(overrides: Partial<Calls> = {}) {
  return {
    saveState: vi.fn<Calls["saveState"]>(async () => ({
      outcome: { ok: true, value: SAVED } as Outcome<MyProposal, SaveProblem>,
      held: [],
    })),
    publish: vi.fn<Calls["publish"]>(async (): Promise<Outcome<PublishResult, PublishProblem>> => ({
      ok: true,
      value: { cert_id: "C1" } as PublishResult,
    })),
    attestationText: vi.fn(async (): Promise<Outcome<AttestationText, PublishProblem>> => ({ ok: true, value: TEXT })),
    uploadAttachment: vi.fn<Calls["uploadAttachment"]>(async () => ({ ok: false, problem: "failed", fields: [] })),
    removeAttachment: vi.fn<Calls["removeAttachment"]>(async () => ({ ok: true, value: undefined })),
    ...overrides,
  };
}

/** Lets the lazily loaded steps (Full details, Review) resolve. */
/** The later steps' code, loaded before a render so the editor reads it synchronously (as the server does). */
export async function settleLazy() {
  await act(async () => {
    await preloadSteps();
  });
}

export async function renderEditor(props: Partial<Omit<EditorProps, "calls">> & { calls?: ReturnType<typeof calls> } = {}) {
  const fake = props.calls ?? calls();
  await preloadSteps();
  renderWithIntl(
    <Editor
      id={null}
      initial={EMPTY_STATE}
      attachments={[]}
      step={1}
      niches={NICHES}
      counties={[{ code: "KE-30", name: "Nairobi City" }]}
      attestations={TEXT}
      problems={[PROBLEM]}
      {...props}
      calls={fake}
    />,
  );
  await settleLazy();
  return fake;
}


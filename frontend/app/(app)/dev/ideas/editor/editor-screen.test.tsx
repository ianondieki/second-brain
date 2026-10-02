import { cleanup, screen } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { HIGH_DEMO, NONE, SOME } from "@/test/checks";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import type { Originality } from "../checks";
import type { MyProposal } from "../ideas";
import { EditorScreen } from "./EditorScreen";

// P19-F (REQ-PROP-04): the editor's page draws today's last overlap check on the server (no script for it on the
// page): the band in words, the AI labels and the "From your last check today." caption, handed to the editor.

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("@/components/SignedInShell", () => ({
  SignedInShell: ({ children }: { children: ReactNode }) => <main>{children}</main>,
}));
vi.mock("@/lib/api/server", () => ({ requireMe: async () => ({ side: "developer" }) }));
// The editor itself is tested elsewhere: here it only shows what the page hands it.
vi.mock("./Editor", () => ({
  Editor: ({ lastOverlap }: { lastOverlap?: ReactNode }) => <div data-testid="last">{lastOverlap}</div>,
}));

const ID = "01a0f30a-cdee-70e7-bdac-2912717f8783";
const reads = vi.hoisted(() => ({ overlap: null as unknown, asked: [] as string[] }));
vi.mock("../data", () => ({
  myIdea: async (id: string) =>
    ({ id, status: "draft", current: null, draft: { teaser: {}, confidential: { attachments: [] } } }) as unknown as MyProposal,
  editorOptions: async () => ({ niches: [], counties: [], attestations: {}, problems: [] }),
  linkableProblem: async () => null,
  lastOverlap: async (id: string) => {
    reads.asked.push(id);
    return reads.overlap;
  },
}));
vi.mock("../versions", () => ({ editableVersion: () => null, stateFromVersion: () => ({}), stateWithProblem: () => ({}) }));

afterEach(() => {
  cleanup();
  reads.asked = [];
});

async function open(overlap: Originality | null, id: string | null = ID) {
  reads.overlap = overlap;
  renderWithIntl(<>{await resolveServerTree(await EditorScreen({ id, step: 1 }))}</>);
  return screen.getByTestId("last");
}

describe("today's last overlap check on the editor's page", () => {
  it("draws the band sentence with the count and the caption", async () => {
    const last = await open(NONE);
    expect(reads.asked).toEqual([ID]);
    expect(last.querySelector("p")!.textContent).toBe("No overlap with other published ideas (compared with 12).");
    expect(last.textContent).toContain("From your last check today.");
    expect(last.querySelectorAll("[data-chip]")).toHaveLength(0);
  });

  it("draws the explainer with the AI-drafted label", async () => {
    const last = await open(SOME);
    expect(last.textContent).toContain("Some overlap with another published idea.");
    expect(last.textContent).toContain(SOME.explanation);
    expect([...last.querySelectorAll("[data-chip]")].map((chip) => chip.textContent)).toEqual(["AI-drafted"]);
    expect(last.textContent).toContain("From your last check today.");
  });

  it("labels the demo fallback", async () => {
    const last = await open(HIGH_DEMO);
    expect(last.textContent).toContain("High overlap: your teaser reads close to another published idea.");
    expect([...last.querySelectorAll("[data-chip]")].map((chip) => chip.textContent)).toEqual(["Demo fallback"]);
  });

  it("draws nothing when there is no check today, and asks nothing for a new idea", async () => {
    expect((await open(null)).childElementCount).toBe(0);
    cleanup();
    reads.asked = [];
    expect((await open(NONE, null)).childElementCount).toBe(0);
    expect(reads.asked).toEqual([]);
  });
});

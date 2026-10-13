import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EditorScreen } from "./EditorScreen";

// REQ-FND-04: in the public demo file uploads are switched off; the editor's page hands the editor the sentence that
// stands where "Add a file" would (Attachments; components/demo-locked.test.tsx checks what it draws).

const editor = vi.hoisted(() => vi.fn());

vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getMessages: async () => en,
}));
vi.mock("next/navigation", () => ({
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => ({ side: "developer", mfa: { enrolled: true, verified: true, required: false }, user: {}, memberships: [] }),
}));
vi.mock("@/lib/i18n/client-strings", () => ({ clientStrings: async () => ({}) }));
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("@/components/DevNav", () => ({ DevNav: () => null }));
vi.mock("../data", () => ({
  myIdea: async () => null,
  editorOptions: async () => ({ niches: [], counties: [], attestations: { version: "1", items: [] }, problems: [] }),
  linkableProblem: async () => null,
  lastOverlap: async () => null,
}));
vi.mock("./Editor", () => ({
  Editor: (props: Record<string, unknown>) => {
    editor(props);
    return null;
  },
}));

beforeEach(() => editor.mockReset());
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

/** The props the page hands the editor. */
async function editorProps(): Promise<Record<string, unknown>> {
  renderWithIntl(<>{await resolveServerTree(await EditorScreen({ id: null, step: 2 }))}</>);
  expect(editor).toHaveBeenCalled();
  return editor.mock.calls.at(-1)![0];
}

describe("the editor's page", () => {
  it("hands the editor the locked sentence in the public demo", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    expect((await editorProps()).uploadsLocked).toBe(en.publicDemo.locked);
  });

  it("hands it nothing with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect((await editorProps()).uploadsLocked).toBeUndefined();
  });
});

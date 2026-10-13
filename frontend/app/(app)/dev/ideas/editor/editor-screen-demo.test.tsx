import { cleanup } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ClientStrings } from "@/components/ClientStrings";
import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

import { EMPTY_STATE } from "../versions";
import { EditorScreen } from "./EditorScreen";

// REQ-FND-04: in the public demo file uploads are switched off; the editor's page adds the sentence that stands where
// "Add a file" would to the editor's strings (ideaEditor.uploadsLocked), and the Files part reads it there (Attachments;
// components/demo-locked.test.tsx checks what it draws). Not a prop of the editor: it would ride in the editor's first
// download, and /dev/ideas/new is at its 150 KB (AC-UX-3).

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
vi.mock("./Editor", async () => {
  const { useStrings } = await import("@/components/ClientStrings");
  return {
    Editor: function Editor(props: Record<string, unknown>) {
      editor({ ...props, uploadsLockedString: useStrings("ideaEditor")("uploadsLocked" as never) });
      return null;
    },
  };
});

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
  it("adds the locked sentence to the editor's strings in the public demo, not to its props", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const props = await editorProps();
    expect(props.uploadsLockedString).toBe(en.publicDemo.locked);
    expect(props).not.toHaveProperty("uploadsLocked");
  });

  it("adds nothing with the mode off (the key is in no catalogue)", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    expect((await editorProps()).uploadsLockedString).toBe("ideaEditor.uploadsLocked");
    expect(en.ideaEditor).not.toHaveProperty("uploadsLocked");
    expect(sw.ideaEditor).not.toHaveProperty("uploadsLocked");
  });
});

describe("the Files part (step 2)", () => {
  const props = {
    state: EMPTY_STATE,
    update: vi.fn(),
    attachments: [],
    onAttachments: vi.fn(),
    ensureDraft: vi.fn(),
    getCalls: vi.fn(),
  };

  it("draws the locked line in place of \"Add a file\" when the page added the sentence", async () => {
    const { DetailsStep } = await import("./DetailsStep");
    renderWithIntl(
      <ClientStrings strings={{ ideaEditor: { ...en.ideaEditor, uploadsLocked: en.publicDemo.locked } }}>
        <DetailsStep {...props} />
      </ClientStrings>,
    );
    expect(document.querySelector("[data-demo-locked]")!.textContent).toBe(en.publicDemo.locked);
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  it("offers \"Add a file\" without it", async () => {
    const { DetailsStep } = await import("./DetailsStep");
    renderWithIntl(<DetailsStep {...props} />);
    expect(document.querySelector('input[type="file"]')).not.toBeNull();
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
  });
});

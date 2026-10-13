import { cleanup, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { detail, ENGAGEMENT_ID } from "@/test/engagement";
import { renderWithIntl } from "@/test/intl";
import { thread } from "@/test/messages";
import { resolveServerTree } from "@/test/server-tree";

import { DemoLocked } from "./DemoLocked";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD; AT-PD-6): while the public demo is on, every switched-off control
// shows one calm line where its form or button would be, and the API's 403 public_demo_locked reads the same.

const LOCKED = "Switched off in the public demo.";

const mocks = vi.hoisted(() => ({ thread: vi.fn() }));

vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getMessages: async () => en,
  getTranslations: async (namespace?: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/headers", () => ({ headers: async () => new Headers(), cookies: async () => ({ get: () => undefined }) }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/settings/security",
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("@/lib/api/server", () => ({
  requireMe: async () => ({
    side: "org",
    mfa: { enrolled: true, verified: true, required: true },
    user: { id: "u-grace", email: "grace@telco-a.example", password_set: true, staff_role: null },
    memberships: [],
  }),
  getSignedIn: async () => null,
  getSignupConsents: async () => ({ items: [] }),
}));
// The page's frame is not under test here: the shell and the portal's navigation pass the content through.
vi.mock("@/components/SignedInShell", () => ({ SignedInShell: ({ children }: { children: ReactNode }) => <>{children}</> }));
vi.mock("@/components/PortalNavFor", () => ({ PortalNavFor: () => null }));
vi.mock("@/components/IntlScope", () => ({ IntlScope: ({ children }: { children: ReactNode }) => children }));
// The composer's thread: what the server hands it is what this test reads.
vi.mock("@/components/tracker/messages/EngagementThread", () => ({
  EngagementThread: (props: { initial: { limits: { max_attachments: number } } }) => {
    mocks.thread(props);
    return <div data-thread="" data-max-attachments={props.initial.limits.max_attachments} />;
  },
}));

beforeEach(() => mocks.thread.mockReset());
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("DemoLocked", () => {
  it("is one line, the card's sentence by default or the one given", async () => {
    renderWithIntl(<>{await resolveServerTree(<DemoLocked />)}</>);
    renderWithIntl(<>{await resolveServerTree(<DemoLocked sentence="Attaching files is switched off in the public demo." />)}</>);
    const lines = document.querySelectorAll("[data-demo-locked]");
    expect([...lines].map((line) => line.textContent)).toEqual([LOCKED, en.publicDemo.attachLocked]);
    for (const line of lines) expect(line.querySelectorAll("button, input, a")).toHaveLength(0);
  });

  // ux review of P28-PD (MAJOR 1): under a feature's heading the generic line read as the feature's state ("two-step
  // sign-in: switched off") while the persona's two-step sign-in is on. Each variant names what is switched off.
  it("says that changing or deciding is off with the change and decide variants", async () => {
    renderWithIntl(<>{await resolveServerTree(<DemoLocked variant="change" />)}</>);
    renderWithIntl(<>{await resolveServerTree(<DemoLocked variant="decide" />)}</>);
    const lines = [...document.querySelectorAll("[data-demo-locked]")];
    expect(lines.map((line) => line.textContent)).toEqual([
      "Changing this is switched off in the public demo.",
      "Deciding is switched off in the public demo.",
    ]);
    expect(lines.map((line) => line.getAttribute("data-demo-locked"))).toEqual(["change", "decide"]);
  });
});

describe("Settings › Security", () => {
  async function renderSecurity() {
    const { default: SecurityPage } = await import("@/app/(app)/settings/security/page");
    return renderWithIntl(<>{await resolveServerTree(await SecurityPage())}</>);
  }

  it("keeps both headings and says changing each is off, in place of two-step sign-in and the password", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    await renderSecurity();
    const locked = document.querySelector("[data-security-locked]")!;
    expect(within(locked as HTMLElement).getByRole("heading", { name: en.security.title })).toBeTruthy();
    expect(within(locked as HTMLElement).getByRole("heading", { name: en.password.title })).toBeTruthy();
    // Not the generic line: under "Two-step sign-in" it would read as the persona's state (it is on).
    const lines = [...locked.querySelectorAll("[data-demo-locked]")].map((line) => line.textContent);
    expect(lines).toEqual([en.publicDemo.changeLocked, en.publicDemo.changeLocked]);
    expect(lines).not.toContain(LOCKED);
    // No form, field or button of either: enrol, turn off, recovery codes and the password are all gone.
    expect(document.querySelectorAll("form, input, button")).toHaveLength(0);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("is today's page with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await renderSecurity();
    expect(document.querySelector("[data-security-locked]")).toBeNull();
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
    expect(screen.getByRole("button", { name: en.password.save })).toBeTruthy();
  });
});

describe("the message composer's files", () => {
  async function renderMessages() {
    const { MessagesTab } = await import("@/components/tracker/MessagesTab");
    const read = { kind: "thread" as const, thread: thread({ can_post: true, status: "open" }) };
    return renderWithIntl(
      <>{await resolveServerTree(await MessagesTab({ detail: detail(), read: read as never, trackerHref: `/dev/engagements/${ENGAGEMENT_ID}` }))}</>,
    );
  }

  it("hands the composer a thread that takes no files (so it draws no Attach) and says why under it", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    await renderMessages();
    expect(document.querySelector("[data-thread]")!.getAttribute("data-max-attachments")).toBe("0");
    expect(document.querySelector("[data-demo-locked]")!.textContent).toBe(en.publicDemo.attachLocked);
  });

  it("is unchanged with the mode off", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await renderMessages();
    expect(Number(document.querySelector("[data-thread]")!.getAttribute("data-max-attachments"))).toBeGreaterThan(0);
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
  });
});

describe("the idea editor's files", () => {
  it("shows the locked line in place of \"Add a file\" (no file input), keeping the files already there", async () => {
    const { Attachments } = await import("@/app/(app)/dev/ideas/editor/Attachments");
    const file = { id: "a1", file_name: "plan.pdf", content_type: "application/pdf", size_bytes: 1000, sha256: "x", av_status: "clean" };
    const props = { attachments: [file as never], onAttachments: vi.fn(), ensureDraft: vi.fn(), getCalls: vi.fn() };
    renderWithIntl(<Attachments {...props} uploadsLocked={LOCKED} />);
    expect(document.querySelector("[data-demo-locked]")!.textContent).toBe(LOCKED);
    expect(document.querySelector('input[type="file"]')).toBeNull();
    expect(screen.getByText("plan.pdf")).toBeTruthy();
    // No hint about adding files, and nothing left pointing at it (ux review of P28-PD, MINOR 4).
    const { MAX_ATTACHMENTS } = await import("@/app/(app)/dev/ideas/ideas");
    const hint = en.ideaEditor.filesHint.replace("{max}", String(MAX_ATTACHMENTS));
    expect(screen.queryByText(hint)).toBeNull();
    expect(document.querySelector('[id$="-hint"]')).toBeNull();
    expect(document.querySelector("[aria-describedby]")).toBeNull();
    cleanup();
    renderWithIntl(<Attachments {...props} />);
    const input = document.querySelector('input[type="file"]')!;
    expect(input).not.toBeNull();
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
    expect(document.getElementById(input.getAttribute("aria-describedby")!)!.textContent).toBe(hint);
  });
});

describe("/signup", () => {
  async function renderSignup() {
    const { default: SignupPage } = await import("@/app/(public)/signup/page");
    return renderWithIntl(<>{await resolveServerTree(await SignupPage())}</>);
  }

  it("is one sentence and one action, to the persona picker, in the public demo", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    await renderSignup();
    const empty = document.querySelector<HTMLElement>("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe(en.publicDemo.signupLocked);
    // One name for the action (ux review of P28-PD, MINOR 5): a persona, as on /login and in "Switch persona".
    const action = within(empty).getByRole("link", { name: "Choose a persona" });
    expect(action.getAttribute("href")).toBe("/login");
    expect(document.querySelectorAll("form, input")).toHaveLength(0);
  });

  it("is the sign-up form with the mode off, with no persona action", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await renderSignup();
    expect(document.querySelector("form")).not.toBeNull();
    expect(screen.queryByRole("link", { name: "Choose a persona" })).toBeNull();
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
  });
});

// The API keeps POST /api/verify open in the public demo (it hashes the file and keeps nothing): the check has no
// demo branch and works as anywhere else.
describe("the certificate file check in the public demo", () => {
  it("works as without the mode", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    const { checkFile } = await import("@/app/(public)/verify/upload");
    const match = { match: true, cert_id: "TXEMFBJ89RRTQS87", sha256: "0".repeat(64) };
    const answer = new Response(JSON.stringify(match), { status: 200, headers: { "content-type": "application/json" } });
    expect(await checkFile(new Blob(["x"]), undefined, async () => answer)).toEqual({ ok: true, result: match });
  });
});

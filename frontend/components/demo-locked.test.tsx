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
});

describe("Settings › Security", () => {
  async function renderSecurity() {
    const { default: SecurityPage } = await import("@/app/(app)/settings/security/page");
    return renderWithIntl(<>{await resolveServerTree(await SecurityPage())}</>);
  }

  it("keeps both headings and shows the locked line in place of two-step sign-in and the password", async () => {
    vi.stubEnv("PUBLIC_DEMO", "true");
    await renderSecurity();
    const locked = document.querySelector("[data-security-locked]")!;
    expect(within(locked as HTMLElement).getByRole("heading", { name: en.security.title })).toBeTruthy();
    expect(within(locked as HTMLElement).getByRole("heading", { name: en.password.title })).toBeTruthy();
    expect([...locked.querySelectorAll("[data-demo-locked]")].map((line) => line.textContent)).toEqual([LOCKED, LOCKED]);
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
    cleanup();
    renderWithIntl(<Attachments {...props} />);
    expect(document.querySelector('input[type="file"]')).not.toBeNull();
    expect(document.querySelector("[data-demo-locked]")).toBeNull();
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
    const action = within(empty).getByRole("link", { name: en.publicDemo.signupAction });
    expect(action.getAttribute("href")).toBe("/login");
    expect(document.querySelectorAll("form, input")).toHaveLength(0);
  });
});

describe("the API's 403 public_demo_locked on the certificate file check", () => {
  it("reads as the demo's sentence, not as a failed check", async () => {
    const { checkFile } = await import("@/app/(public)/verify/upload");
    const locked = new Response(JSON.stringify({ detail: { code: "public_demo_locked", message: "x" } }), { status: 403 });
    expect(await checkFile(new Blob(["x"]), undefined, async () => locked)).toEqual({ ok: false, problem: "demoLocked" });
    const other = new Response(JSON.stringify({ detail: { code: "forbidden" } }), { status: 403 });
    expect(await checkFile(new Blob(["x"]), undefined, async () => other)).toEqual({ ok: false, problem: "failed" });
    expect(en.verifyFile.demoLocked).toBe(en.errors.public_demo_locked);
  });
});

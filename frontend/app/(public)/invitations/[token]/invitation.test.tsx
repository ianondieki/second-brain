import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ApiClient } from "@/lib/api/client";
import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-TEN-02 (P28 track C, AT-C-1 on the web): an invitation link's page. The preview is read with no session and the
// visitor's forwarded address only; a malformed token never reaches the API; a dead link (one answer) is one sentence
// and one action; signed out, sign in comes back here; signed in, Accept joins and opens the organisation; a mismatch
// names nothing about the invited address; the public demo switches accepting off; no referrer leaves the page.

const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE";
const ORG_ID = "0199c000-0000-7000-8000-0000000000a1";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  forward: vi.fn(),
  me: null as null | { user: { email: string } },
  demo: false,
  push: vi.fn(),
}));

vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: mocks.get }),
  forwardHeaders: mocks.forward,
  getSignedIn: async () => mocks.me,
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/public-demo", () => ({ publicDemoOn: () => mocks.demo }));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/lib/data-saver-request", () => ({ savesData: async () => true }));

const { isInvitationToken, readInvitation } = await import("./invitation");
const { default: InvitationPage, generateMetadata } = await import("./page");
const { AcceptInvitation, acceptRefusal } = await import("./AcceptInvitation");

function preview(answer: { status: number; data?: unknown }) {
  mocks.get.mockResolvedValue({ data: answer.data, response: new Response(null, { status: answer.status }) });
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.forward.mockReset();
  mocks.forward.mockResolvedValue({ "x-forwarded-for": "198.51.100.7" });
  mocks.me = null;
  mocks.demo = false;
  mocks.push.mockReset();
  preview({ status: 200, data: { org_name: "Telco A (fixture)", roles: ["reviewer", "admin"] } });
});
afterEach(cleanup);

async function renderPage(token = TOKEN) {
  const node = await InvitationPage({ params: Promise.resolve({ token }) } as never);
  return renderWithIntl(<>{await resolveServerTree(node)}</>);
}

describe("the preview read", () => {
  it("sends no session, only the visitor's address, bounded and never cached", async () => {
    expect(await readInvitation(TOKEN)).toEqual({
      kind: "ok",
      preview: { org_name: "Telco A (fixture)", roles: ["reviewer", "admin"] },
    });
    expect(mocks.forward).toHaveBeenCalledWith({ session: false });
    const [path, options] = mocks.get.mock.calls[0];
    expect(path).toBe("/api/invitations/{token}");
    expect(options.params).toEqual({ path: { token: TOKEN } });
    expect(options.headers).toEqual({ "x-forwarded-for": "198.51.100.7" });
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.cache).toBe("no-store");
  });

  it("answers a malformed token as a dead link without asking the API", async () => {
    for (const token of ["short", `${TOKEN}x`, `${TOKEN.slice(1)}.`, "../../api/auth/me"]) {
      expect(isInvitationToken(token), token).toBe(false);
      expect(await readInvitation(token)).toEqual({ kind: "gone" });
    }
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("reads 404 as a dead link and 429 as too many tries, and throws on anything else", async () => {
    preview({ status: 404 });
    expect(await readInvitation(TOKEN)).toEqual({ kind: "gone" });
    preview({ status: 429 });
    expect(await readInvitation(TOKEN)).toEqual({ kind: "rateLimited" });
    preview({ status: 503 });
    await expect(readInvitation(TOKEN)).rejects.toThrow("GET /api/invitations/{token} answered 503");
  });
});

describe("the invitation page", () => {
  it("is never indexed and sends no referrer", async () => {
    const meta = await generateMetadata();
    expect(meta.title).toBe("Invitation");
    expect(meta.robots).toEqual({ index: false, follow: false });
    expect(meta.referrer).toBe("no-referrer");
  });

  it("signed out: names the organisation and roles, Sign in to accept returns here, and the way to sign up", async () => {
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Join Telco A (fixture)");
    expect(screen.getByText("Telco A (fixture) invited you to join as admin and reviewer.")).toBeTruthy();
    const signIn = screen.getByRole("link", { name: "Sign in to accept" });
    expect(signIn.getAttribute("href")).toBe(`/login?next=%2Finvitations%2F${TOKEN}`);
    expect(signIn.hasAttribute("data-primary")).toBe(true);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Create an account" }).getAttribute("href")).toBe("/signup");
    expect(screen.queryByRole("button", { name: "Accept and join" })).toBeNull();
  });

  it("signed in: says who is signed in and offers Accept as the one primary action", async () => {
    mocks.me = { user: { email: "wanjiru@telco-a.example" } };
    await renderPage();
    expect(screen.getByText("You are signed in as wanjiru@telco-a.example.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Accept and join" }).hasAttribute("data-primary")).toBe(true);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "Sign in to accept" })).toBeNull();
  });

  it("a dead link is one calm sentence and the home page", async () => {
    preview({ status: 404 });
    await renderPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(en.invitation.deadTitle);
    const empty = document.querySelector<HTMLElement>('[data-invitation="gone"]')!;
    expect(within(empty).getAllByRole("paragraph").map((p) => p.textContent)).toEqual([en.invitation.dead]);
    expect(within(empty).getByRole("link").getAttribute("href")).toBe("/");
    expect(screen.queryByText(/Telco A/)).toBeNull();
  });

  it("too many tries is one sentence and Try again", async () => {
    preview({ status: 429 });
    await renderPage();
    const empty = document.querySelector<HTMLElement>('[data-invitation="rateLimited"]')!;
    expect(empty.textContent).toContain(en.invitation.rateLimited);
    expect(within(empty).getByRole("link", { name: "Try again" }).getAttribute("href")).toBe(`/invitations/${TOKEN}`);
  });

  it("in the public demo, accepting is switched off, signed in or out", async () => {
    mocks.demo = true;
    await renderPage();
    expect(document.querySelector("[data-demo-locked]")?.textContent).toBe(en.invitation.demoLocked);
    expect(screen.queryByRole("link", { name: "Sign in to accept" })).toBeNull();
    mocks.me = { user: { email: "x@example.com" } };
    cleanup();
    await renderPage();
    expect(screen.queryByRole("button", { name: "Accept and join" })).toBeNull();
  });
});

describe("Accept and join", () => {
  function client(answer: { status: number; data?: unknown; error?: unknown } | Error) {
    const post = vi.fn(async () => {
      if (answer instanceof Error) throw answer;
      return { data: answer.data, error: answer.error, response: new Response(null, { status: answer.status }) };
    });
    return { api: { POST: post } as unknown as ApiClient, post };
  }

  function renderAccept(api: ApiClient) {
    return renderWithIntl(<AcceptInvitation token={TOKEN} orgName="Telco A (fixture)" client={api} />);
  }

  it("joins and opens the organisation's portal", async () => {
    const { api, post } = client({ status: 200, data: { org_id: ORG_ID, org_name: "Telco A (fixture)", roles: ["reviewer"] } });
    renderAccept(api);
    fireEvent.click(screen.getByRole("button", { name: "Accept and join" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(`/org?org=${ORG_ID}`));
    expect(post).toHaveBeenCalledWith("/api/invitations/{token}/accept", { params: { path: { token: TOKEN } } });
  });

  it("says only that the invitation is for a different address, and offers no second try", async () => {
    const { api } = client({ status: 403, error: { detail: { code: "invitation_email_mismatch", message: "x" } } });
    renderAccept(api);
    fireEvent.click(screen.getByRole("button", { name: "Accept and join" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(en.invitationAccept.refusal.mismatch);
    expect(alert.textContent).not.toMatch(/@/);
    expect(screen.queryByRole("button", { name: "Accept and join" })).toBeNull();
  });

  it.each([
    [404, undefined, en.invitationAccept.refusal.gone, false],
    [409, "already_member", en.invitationAccept.refusal.member, false],
    [402, "plan_limit", "Telco A (fixture) has no free seat on its plan just now. Ask the person who invited you.", false],
    [403, "public_demo_locked", en.invitationAccept.refusal.locked, false],
    [429, "rate_limited", en.invitationAccept.refusal.rateLimited, true],
    [500, undefined, en.invitationAccept.refusal.generic, true],
  ])("answers %i %s in words", async (status, code, sentence, again) => {
    const { api } = client({ status, error: code ? { detail: { code, message: "x" } } : undefined });
    renderAccept(api);
    fireEvent.click(screen.getByRole("button", { name: "Accept and join" }));
    expect((await screen.findByRole("alert")).querySelector("p")?.textContent).toBe(sentence);
    expect(screen.queryByRole("button", { name: "Accept and join" }) !== null).toBe(again);
  });

  it("offers the way back through sign-in when the session ended", async () => {
    const { api } = client({ status: 401, error: { detail: { code: "unauthenticated", message: "x" } } });
    renderAccept(api);
    fireEvent.click(screen.getByRole("button", { name: "Accept and join" }));
    const alert = await screen.findByRole("alert");
    expect(within(alert).getByRole("link", { name: "Sign in again" }).getAttribute("href")).toBe(
      `/login?next=%2Finvitations%2F${TOKEN}`,
    );
  });

  it("says no connection when the request never left", async () => {
    const { api } = client(new TypeError("Failed to fetch"));
    renderAccept(api);
    fireEvent.click(screen.getByRole("button", { name: "Accept and join" }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.invitationAccept.refusal.network);
  });

  it("maps codes before statuses", () => {
    expect(acceptRefusal(403, { detail: { code: "invitation_email_mismatch" } })).toBe("mismatch");
    expect(acceptRefusal(403, { detail: { code: "something_else" } })).toBe("generic");
  });
});

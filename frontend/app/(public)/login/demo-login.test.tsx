import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-FND-04 (docs/platform/tasks/P28.md, track PD; AT-PD-6): /login in the public demo offers the API's personas, one
// press each, with the email form folded below; with the mode off, /login is as it was.

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
  forget: vi.fn(async () => undefined),
  personas: vi.fn(),
  signedIn: vi.fn(async () => null),
  fetch: vi.fn<(request: Request) => Promise<Response>>(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, push: mocks.push, refresh: vi.fn() }),
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("next-intl/server", () => ({
  getLocale: async () => "en",
  getMessages: async () => en,
  getTranslations: async (namespace?: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
}));
vi.mock("next/headers", () => ({ headers: async () => new Headers(), cookies: async () => ({ get: () => undefined }) }));
// renderWithIntl provides the messages; the server's IntlScope picks them on the server only.
vi.mock("@/components/IntlScope", () => ({ IntlScope: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/offline/clear", () => ({ forgetOffline: () => mocks.forget() }));
vi.mock("@/lib/public/demo-personas", () => ({ demoPersonas: () => mocks.personas() }));
vi.mock("@/lib/api/server", () => ({ getSignedIn: () => mocks.signedIn() }));
// The real sign-in helper and its CSRF wrapper (lib/api/csrf.ts withCsrf), over a fake network at an absolute origin
// (Node's Request takes no relative URL): the request is checked as the API would see it.
vi.mock("@/lib/api/demo-sign-in", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/demo-sign-in")>();
  const { withCsrf } = await import("@/lib/api/csrf");
  const send = withCsrf((input, init) => mocks.fetch(new Request(input, init)), "http://web.test/api/auth/csrf");
  return {
    ...actual,
    demoSignIn: (persona: string) =>
      actual.demoSignIn(persona, (input, init) => send(new URL(String(input), "http://web.test"), init)),
  };
});

const PERSONAS = [
  { key: "amina", name: "Amina Wanjiru", role: "developer", detail: "Developer, verified D2", home: "/dev" },
  { key: "brian", name: "Brian Otieno", role: "developer", detail: "Developer, verified D1", home: "/dev" },
  { key: "grace", name: "Grace Mwangi", role: "org_admin", detail: "Telco A, owner and admin", home: "/org" },
  { key: "peter", name: "Peter Kamau", role: "org_signatory", detail: "Telco A, signatory", home: "/org" },
  { key: "rita", name: "Rita Njeri", role: "org_reviewer", detail: "Telco A, reviewer", home: "/org" },
  { key: "hassan", name: "Hassan Abdi", role: "org_admin", detail: "County Government of C, admin", home: "/org" },
  { key: "moderator", name: "Staff Moderator", role: "staff", detail: "Platform staff", home: "/admin" },
];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** The API: a CSRF token, then the sign-in's answer. */
function api(signIn: () => Response) {
  mocks.fetch.mockImplementation(async (request) =>
    new URL(request.url).pathname === "/api/auth/csrf" ? json({ csrf_token: "tok-1" }) : signIn(),
  );
}

async function renderLogin() {
  const { default: LoginPage } = await import("./page");
  const tree = await LoginPage({ searchParams: Promise.resolve({}) } as never);
  return renderWithIntl(<>{await resolveServerTree(tree)}</>);
}

beforeEach(() => {
  for (const mock of [mocks.replace, mocks.push, mocks.forget, mocks.personas, mocks.fetch]) mock.mockReset();
  mocks.personas.mockResolvedValue(PERSONAS);
  vi.stubEnv("PUBLIC_DEMO", "true");
  document.cookie = "bridge_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  document.cookie = "__Host-bridge_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("/login in the public demo", () => {
  it("offers every persona the API returned, in its order: the name as a heading, the role, the detail, one button", async () => {
    await renderLogin();
    expect(screen.getByRole("heading", { level: 1, name: "Try the demo as…" })).toBeTruthy();
    const list = screen.getByRole("list", { name: "People you can sign in as" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(7);
    expect(rows.map((row) => within(row).getByRole("heading", { level: 2 }).textContent)).toEqual(PERSONAS.map((p) => p.name));
    const grace = rows[2];
    expect(within(grace).getByText("Organisation admin")).toBeTruthy();
    expect(within(grace).getByText("Telco A, owner and admin")).toBeTruthy();
    expect(within(rows[6]).getByText("Platform staff", { selector: "p.font-semibold" })).toBeTruthy();
    // One button per row, its accessible name naming the persona; its visible word is "Continue".
    for (const [index, row] of rows.entries()) {
      const buttons = within(row).getAllByRole("button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0].textContent).toBe(`Continue as ${PERSONAS[index].name}`);
      expect(within(row).getByRole("button", { name: `Continue as ${PERSONAS[index].name}` })).toBe(buttons[0]);
    }
  });

  it("renders whatever count the API returns (no fixed number)", async () => {
    mocks.personas.mockResolvedValue(PERSONAS.slice(0, 2));
    await renderLogin();
    expect(within(screen.getByRole("list", { name: "People you can sign in as" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("folds the email form under \"Sign in with an account\", without sign-up or the emailed link", async () => {
    await renderLogin();
    const details = document.querySelector<HTMLDetailsElement>("details[data-account-sign-in]")!;
    expect(details.open).toBe(false);
    expect(details.querySelector("summary")?.textContent).toBe("Sign in with an account");
    expect(within(details).getByLabelText("Email address")).toBeTruthy();
    expect(within(details).queryByRole("button", { name: /sign-in link/i })).toBeNull();
    expect(document.querySelector('a[href="/signup"]')).toBeNull();
    // At most one primary action on the screen (AC-UX-2): the folded form's Log in; the persona buttons are secondary.
    expect(document.querySelectorAll("[data-primary]").length).toBeLessThanOrEqual(1);
  });

  it("presses: POSTs the persona's key with the CSRF header, then goes to that persona's Home", async () => {
    api(() => json({ user: { id: "u-grace" }, mfa_required: false }));
    await renderLogin();
    fireEvent.click(screen.getByRole("button", { name: "Continue as Grace Mwangi" }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/org"));
    const post = mocks.fetch.mock.calls.map(([request]) => request).find((request) => request.method === "POST")!;
    expect(new URL(post.url).pathname).toBe("/api/auth/demo/sign-in");
    expect(post.headers.get("X-CSRF-Token")).toBe("tok-1");
    expect(post.headers.get("Content-Type")).toBe("application/json");
    expect(await post.json()).toEqual({ persona: "grace" });
    expect(mocks.forget).toHaveBeenCalled(); // the previous person's offline copies go first
  });

  it("says \"Signing in…\" on the pressed button while it waits, and ignores a second press", async () => {
    let answer: (response: Response) => void = () => {};
    mocks.fetch.mockImplementation(async (request) =>
      new URL(request.url).pathname === "/api/auth/csrf"
        ? json({ csrf_token: "tok-1" })
        : new Promise<Response>((resolve) => (answer = resolve)),
    );
    await renderLogin();
    fireEvent.click(screen.getByRole("button", { name: "Continue as Amina Wanjiru" }));
    expect(await screen.findByRole("button", { name: "Signing in…" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Continue as Brian Otieno" }));
    answer(json({ user: { id: "u-amina" }, mfa_required: false }));
    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/dev"));
    expect(mocks.fetch.mock.calls.filter(([request]) => request.method === "POST")).toHaveLength(1);
  });

  it("puts a 429 as one line in that persona's row: try again in a minute", async () => {
    api(() => json({ detail: { code: "too_many_attempts", message: "x" } }, 429));
    await renderLogin();
    const row = document.querySelector<HTMLElement>('[data-persona="peter"]')!;
    fireEvent.click(within(row).getByRole("button"));
    expect((await within(row).findByRole("alert")).textContent).toBe("Too many sign-ins from here just now. Try again in a minute.");
    expect(document.querySelectorAll('[role="alert"]')).toHaveLength(1);
    expect(mocks.replace).not.toHaveBeenCalled();
    // The button is back for another try.
    expect(within(row).getByRole("button", { name: "Continue as Peter Kamau" })).toBeTruthy();
  });

  it("puts anything else as a calm generic line, a dropped connection included", async () => {
    api(() => json({ detail: { code: "unknown_persona", message: "x" } }, 400));
    await renderLogin();
    const row = document.querySelector<HTMLElement>('[data-persona="rita"]')!;
    fireEvent.click(within(row).getByRole("button"));
    expect((await within(row).findByRole("alert")).textContent).toBe("That sign-in did not go through. Try again in a moment.");

    mocks.fetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const other = document.querySelector<HTMLElement>('[data-persona="hassan"]')!;
    fireEvent.click(within(other).getByRole("button"));
    expect((await within(other).findByRole("alert")).textContent).toBe("That sign-in did not go through. Try again in a moment.");
    expect(within(row).queryByRole("alert")).toBeNull(); // one line at a time
  });

  it("says so in one line and opens the email form when no persona could be read", async () => {
    mocks.personas.mockResolvedValue(null);
    await renderLogin();
    expect(screen.queryByRole("list", { name: "People you can sign in as" })).toBeNull();
    expect(document.querySelector("[data-personas-unavailable]")?.textContent).toBe(en.publicDemo.unavailable);
    expect(document.querySelector<HTMLDetailsElement>("details[data-account-sign-in]")!.open).toBe(true);
  });
});

describe("/login with the mode off", () => {
  it("is today's page: the email form with the emailed link and sign-up, no personas, no disclosure", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await renderLogin();
    expect(mocks.personas).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: en.login.title })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "People you can sign in as" })).toBeNull();
    expect(document.querySelector("details")).toBeNull();
    expect(screen.getByRole("button", { name: en.login.magicLink })).toBeTruthy();
    expect(document.querySelector('a[href="/signup"]')).not.toBeNull();
  });
});

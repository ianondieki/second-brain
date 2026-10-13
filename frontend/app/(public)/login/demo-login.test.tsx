import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import sw from "@/locales/sw.json";
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
  locale: { value: "en" as "en" | "sw" },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, push: mocks.push, refresh: vi.fn() }),
  redirect: (to: string) => {
    throw new Error(`redirect:${to}`);
  },
}));
vi.mock("next-intl/server", () => ({
  getLocale: async () => mocks.locale.value,
  getMessages: async () => en,
  // The page's language: the catalogue of the locale this test set (the rendered tree's own provider is English).
  getTranslations: async (namespace?: string) =>
    createTranslator({
      locale: mocks.locale.value,
      messages: (mocks.locale.value === "sw" ? sw : en) as typeof en,
      namespace: namespace as never,
    }),
}));
vi.mock("next/headers", () => ({ headers: async () => new Headers(), cookies: async () => ({ get: () => undefined }) }));
// renderWithIntl provides the messages; the server's IntlScope picks them on the server only.
vi.mock("@/components/IntlScope", () => ({ IntlScope: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/components/offline/clear", () => ({ forgetOffline: () => mocks.forget() }));
vi.mock("@/lib/public/demo-personas", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/public/demo-personas")>()),
  demoPersonas: () => mocks.personas(),
}));
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
  { key: "amina", name: "Amina Wanjiru", role: "developer", detail: "Developer, D2", home: "/dev" },
  { key: "brian", name: "Brian Otieno", role: "developer", detail: "Developer, D1", home: "/dev" },
  { key: "grace", name: "Grace Mwangi", role: "org_admin", detail: "Telco A (fixture): owner and admin", home: "/org" },
  { key: "peter", name: "Peter Kamau", role: "org_signatory", detail: "Telco A (fixture): signatory", home: "/org" },
  { key: "rita", name: "Rita Njeri", role: "org_reviewer", detail: "Telco A (fixture): reviewer", home: "/org" },
  { key: "halima", name: "Halima Yusuf", role: "org_admin", detail: "State Department D (fixture): owner and admin", home: "/org" },
  { key: "moderator", name: "Staff Moderator (demo)", role: "staff", detail: "Platform staff: moderator", home: "/admin" },
];
/** The names as drawn: the seed's " (demo)" dropped. */
const NAMES = ["Amina Wanjiru", "Brian Otieno", "Grace Mwangi", "Peter Kamau", "Rita Njeri", "Halima Yusuf", "Staff Moderator"];

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
  mocks.locale.value = "en";
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
    // The same noun as /signup's "Choose a persona" and the menu's "Switch persona" (ux review of P28-PD, MINOR 5).
    expect(screen.getByText("Choose a persona. One press signs you in and opens their Home.")).toBeTruthy();
    const list = screen.getByRole("list", { name: "Personas you can sign in as" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(7);
    expect(rows.map((row) => within(row).getByRole("heading", { level: 2 }).textContent)).toEqual(NAMES);
    const grace = rows[2];
    expect(within(grace).getByText("Organisation admin")).toBeTruthy();
    expect(within(rows[6]).getByText("Platform staff", { selector: "p.font-semibold" })).toBeTruthy();
    // One button per row, its accessible name naming the persona; its visible word is "Continue".
    for (const [index, row] of rows.entries()) {
      const buttons = within(row).getAllByRole("button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0].textContent).toBe(`Continue as ${NAMES[index]}`);
      expect(within(row).getByRole("button", { name: `Continue as ${NAMES[index]}` })).toBe(buttons[0]);
    }
  });

  // ux review of P28-PD (MINOR 3): the line under each name says what the persona does, built here in every language;
  // never the API's English detail (it repeats the role above it and carries the seed's "(fixture)").
  const line = (key: string) => document.querySelector(`[data-persona="${key}"] h2 + p + p`)?.textContent ?? null;

  it("says under each name what the persona does, with the organisation's plain name", async () => {
    await renderLogin();
    expect(line("amina")).toBe("Publishes ideas and answers the organisations that want them");
    expect(line("brian")).toBe("Publishes ideas and answers the organisations that want them");
    expect(line("grace")).toBe("Runs the team, scouts and pipeline at Telco A");
    expect(line("peter")).toBe("Approves and signs for Telco A");
    expect(line("rita")).toBe("Reviews proposals and makes recommendations for Telco A");
    expect(line("halima")).toBe("Runs the team, scouts and pipeline at State Department D");
    expect(line("moderator")).toBe("Reads the moderation and research queues");
    const text = document.querySelector("[data-personas]")!.textContent!;
    for (const word of ["(fixture)", "(demo)", "owner and admin", "Developer, D2", "Platform staff: moderator"]) {
      expect(text).not.toContain(word);
    }
  });

  it("builds the same lines in Swahili, the organisation's name as written", async () => {
    mocks.locale.value = "sw";
    await renderLogin();
    expect(line("amina")).toBe(sw.publicDemo.about.developer);
    expect(line("grace")).toBe("Huendesha timu, skauti na mchakato wa Telco A");
    expect(line("peter")).toBe("Huidhinisha na kutia sahihi kwa niaba ya Telco A");
    expect(line("rita")).toBe("Hukagua mapendekezo na kutoa ushauri kwa Telco A");
    expect(line("moderator")).toBe(sw.publicDemo.about.staff);
    expect(screen.getByRole("button", { name: "Endelea kama Staff Moderator" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("owner and admin");
    expect(document.body.textContent).not.toContain("(fixture)");
  });

  it("draws no line for an organisation persona whose organisation cannot be read", async () => {
    mocks.personas.mockResolvedValue([{ ...PERSONAS[2], detail: "owner and admin" }]);
    await renderLogin();
    expect(line("grace")).toBeNull();
    expect(screen.getByText("Organisation admin")).toBeTruthy();
  });

  it("renders whatever count the API returns (no fixed number)", async () => {
    mocks.personas.mockResolvedValue(PERSONAS.slice(0, 2));
    await renderLogin();
    expect(within(screen.getByRole("list", { name: "Personas you can sign in as" })).getAllByRole("listitem")).toHaveLength(2);
  });

  it("offers personas only: no email or password form, no emailed link, no sign-up (all switched off in the demo)", async () => {
    await renderLogin();
    expect(document.querySelector("form")).toBeNull();
    expect(document.querySelector("details")).toBeNull();
    expect(document.querySelector("input")).toBeNull();
    expect(screen.queryByLabelText("Email address")).toBeNull();
    expect(screen.queryByRole("button", { name: /log in|sign-in link/i })).toBeNull();
    expect(document.querySelector('a[href="/signup"]')).toBeNull();
    // Every button on the page is a persona's; none is the screen's primary action (AC-UX-2: at most one).
    expect(screen.getAllByRole("button")).toHaveLength(7);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
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
    const other = document.querySelector<HTMLElement>('[data-persona="halima"]')!;
    fireEvent.click(within(other).getByRole("button"));
    expect((await within(other).findByRole("alert")).textContent).toBe("That sign-in did not go through. Try again in a moment.");
    expect(within(row).queryByRole("alert")).toBeNull(); // one line at a time
  });

  it("says so in one line with \"Try again\" (the page itself), and no form, when no persona could be read", async () => {
    mocks.personas.mockResolvedValue(null);
    await renderLogin();
    expect(screen.queryByRole("list", { name: "Personas you can sign in as" })).toBeNull();
    const empty = document.querySelector<HTMLElement>("[data-personas-unavailable]")!;
    expect(empty.querySelector("p")!.textContent).toBe(en.publicDemo.unavailable);
    expect(within(empty).getByRole("link", { name: "Try again" }).getAttribute("href")).toBe("/login");
    expect(document.querySelector("form")).toBeNull();
  });

  it("treats an empty list as unreadable too", async () => {
    mocks.personas.mockResolvedValue([]);
    await renderLogin();
    expect(document.querySelector("[data-personas-unavailable]")).not.toBeNull();
  });
});

describe("/login with the mode off", () => {
  it("is today's page: the email form with the emailed link and sign-up, no personas, no disclosure", async () => {
    vi.stubEnv("PUBLIC_DEMO", "false");
    await renderLogin();
    expect(mocks.personas).not.toHaveBeenCalled();
    expect(screen.getByRole("heading", { level: 1, name: en.login.title })).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Personas you can sign in as" })).toBeNull();
    expect(document.querySelector("details")).toBeNull();
    expect(screen.getByRole("button", { name: en.login.magicLink })).toBeTruthy();
    expect(document.querySelector('a[href="/signup"]')).not.toBeNull();
  });
});

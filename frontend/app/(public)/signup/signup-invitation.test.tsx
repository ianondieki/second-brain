import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";
import { resolveServerTree } from "@/test/server-tree";

// REQ-TEN-02 (P28 review BLOCKER 2): "Create an account" from an invitation link opens sign-up in the invitee's mode:
// the organisation named, no developer/organisation choice and no organisation details; the request says side "org"
// with the link's token and no organisation; a link closed meanwhile (422 org_details_required) is said as such. A
// /signup?invitation= that opens nothing is the dead-link sentence; the page sends no referrer.

const TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_AbCdE";
const mocks = vi.hoisted(() => ({ post: vi.fn(), push: vi.fn(), get: vi.fn() }));

vi.mock("@/lib/api/client", () => ({ api: { POST: mocks.post, GET: vi.fn() } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push, replace: vi.fn(), refresh: vi.fn() }),
  redirect: () => {
    throw new Error("redirect");
  },
}));
vi.mock("@/lib/api/server", () => ({
  serverApi: () => ({ GET: mocks.get }),
  forwardHeaders: async () => ({}),
  getSignedIn: async () => null,
  getSignupConsents: async () => ({ version: "v1", items: [] }),
}));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) =>
    createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
  getMessages: async () => en,
}));
vi.mock("@/lib/i18n/client-strings", () => ({
  clientStrings: async (namespaces: string[]) =>
    Object.fromEntries(namespaces.map((ns) => [ns, (en as unknown as Record<string, unknown>)[ns]])),
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
// The page's next-intl scope; renderWithIntl provides the messages here.
vi.mock("@/components/IntlScope", () => ({ IntlScope: ({ children }: { children: React.ReactNode }) => children }));
vi.mock("@/lib/data-saver-request", () => ({ savesData: async () => true }));

const { SignupForm } = await import("./SignupForm");
const { default: SignupPage, generateMetadata } = await import("./page");

beforeEach(() => {
  mocks.post.mockReset();
  mocks.push.mockReset();
  mocks.get.mockReset();
});
afterEach(cleanup);

function fill() {
  fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Wanjiku Mutua" } });
  fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "wanjiku@telco-a.example" } });
  fireEvent.change(screen.getByLabelText("Password", { exact: true }), { target: { value: "accent season in nairobi" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /terms of service/ }));
}

describe("sign-up from an invitation", () => {
  it("names the organisation, asks neither side nor organisation details, and sends side org with the token", async () => {
    mocks.post.mockResolvedValue({ data: {}, response: new Response(null, { status: 202 }) });
    renderWithIntl(
      <SignupForm initialConsents={{ version: "v1", items: [] }} invitation={{ token: TOKEN, org: "Telco A (fixture)" }} />,
    );
    expect(document.querySelector("[data-signup-invitation]")?.textContent).toContain("join Telco A (fixture)");
    expect(screen.queryByRole("radiogroup")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByLabelText("Organisation name")).toBeNull();
    await waitFor(() => expect(document.querySelector('form[data-hydrated="true"]')).not.toBeNull());
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalled());
    const [path, { body }] = mocks.post.mock.calls[0];
    expect(path).toBe("/api/auth/signup");
    expect(body).toMatchObject({ side: "org", org: null, invitation: TOKEN, email: "wanjiku@telco-a.example" });
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/signup/check-email"));
  });

  it("says the link no longer works when the API answers as for missing organisation details", async () => {
    mocks.post.mockResolvedValue({
      error: { detail: { code: "org_details_required", message: "x" } },
      response: new Response(null, { status: 422 }),
    });
    renderWithIntl(
      <SignupForm initialConsents={{ version: "v1", items: [] }} invitation={{ token: TOKEN, org: "Telco A (fixture)" }} />,
    );
    await waitFor(() => expect(document.querySelector('form[data-hydrated="true"]')).not.toBeNull());
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect((await screen.findByRole("alert")).textContent).toBe(en.signup.invitationGone);
  });

  it("sends no invitation and keeps the side choice without one", async () => {
    renderWithIntl(<SignupForm initialConsents={{ version: "v1", items: [] }} />);
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(document.querySelector("[data-signup-invitation]")).toBeNull();
  });
});

describe("/signup?invitation=", () => {
  const page = async (search: Record<string, string>) =>
    renderWithIntl(<>{await resolveServerTree(await SignupPage({ searchParams: Promise.resolve(search) } as never))}</>);

  it("reads the link's preview and opens the invitee's form", async () => {
    mocks.get.mockResolvedValue({
      data: { org_name: "Telco A (fixture)", roles: ["reviewer"] },
      response: new Response(null, { status: 200 }),
    });
    await page({ invitation: TOKEN });
    expect(document.querySelector("[data-signup-invitation]")?.textContent).toContain("Telco A (fixture)");
  });

  it("is the dead-link sentence for a link that opens nothing, or a token of another shape", async () => {
    mocks.get.mockResolvedValue({ response: new Response(null, { status: 404 }) });
    await page({ invitation: TOKEN });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(en.invitation.deadTitle);
    expect(screen.getByRole("link", { name: en.signup.plainSignup }).getAttribute("href")).toBe("/signup");
    cleanup();
    mocks.get.mockClear();
    await page({ invitation: "nope" });
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(en.invitation.deadTitle);
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("sends no referrer and is not indexed with an invitation, and is as before without", async () => {
    expect(await generateMetadata({ searchParams: Promise.resolve({ invitation: TOKEN }) } as never)).toMatchObject({
      referrer: "no-referrer",
      robots: { index: false, follow: false },
    });
    expect(await generateMetadata({ searchParams: Promise.resolve({}) } as never)).toEqual({ title: en.signup.title });
  });
});

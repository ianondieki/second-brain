import { spawnSync } from "node:child_process";

import { expect, type APIRequestContext, type Browser } from "@playwright/test";

import { waitForSignInLink } from "./mailpit";
import { PASSWORD, Person } from "./tracker-scene";

/**
 * The research screens' E2E state (REQ-RES-01, M2 walkthrough step 3), built through the API wherever it has a path:
 *
 * - a staff admin: signed up as a developer, then given the staff admin role and the demo-account flag by the
 *   database owner (no application path sets either; the demo seed does the same for admin@staff.example, and the
 *   dev stack's seed has no staff account), then two-step sign-in turned on through the API;
 * - a research candidate: runs on the dev stack's fake LLM end in the demo fallback with no card (D-37), so the card a
 *   run would have drafted is written by the owner as `app_create_research_candidate` writes one (source
 *   research_agent, status candidate, created_by NULL, sources exactly as saved with their excerpt ids), from the
 *   saved excerpts the admin API lists. Approval then goes through the real publish checks and app_moderate_problem.
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner. Every account is under example.com.
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

/** Runs SQL as the database owner; values travel as psql variables (quoted by psql, never spliced into the SQL). */
export function ownerSql(sql: string, variables: Record<string, string>): string {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  const args = [OWNER_DATABASE_URL, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"];
  for (const [name, value] of Object.entries(variables)) args.push("-v", `${name}=${value}`);
  const result = spawnSync("psql", args, { input: sql, encoding: "utf-8", timeout: 15_000 });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  return result.stdout.trim();
}

/** A short tag of letters only: card text may carry no digit a cited quote does not (the publish checks). */
export function letterTag(): string {
  const letters = "abcdefghijklmnopqrstuvwxyz";
  return Array.from({ length: 6 }, () => letters[Math.floor(Math.random() * letters.length)]).join("");
}

async function csrf(request: APIRequestContext): Promise<string> {
  const response = await request.get("/api/auth/csrf");
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as { csrf_token: string }).csrf_token;
}

async function post<T>(request: APIRequestContext, path: string, data: unknown, status = 200): Promise<T> {
  const response = await request.post(path, { headers: { "X-CSRF-Token": await csrf(request) }, data });
  expect(response.status(), `${path}: ${await response.text()}`).toBe(status);
  return (await response.json()) as T;
}

/** A new account signed in on `request` (sign up, then the emailed link). */
async function signUp(request: APIRequestContext, email: string, name: string): Promise<void> {
  const signup = await request.post("/api/auth/signup", {
    headers: { "X-CSRF-Token": await csrf(request) },
    data: { email, password: PASSWORD, display_name: name, side: "developer", accept_terms: true },
  });
  expect(signup.status(), await signup.text()).toBeLessThan(300);
  const token = new URL(await waitForSignInLink(request, email)).hash.replace(/^#token=/, "");
  await post(request, "/api/auth/magic-link/consume", { token });
}

/**
 * A new staff admin (or, with `role`, a moderator) with two-step sign-in on, set up in a browser context of its own
 * (so the test's page signs in through the login screen, as a person would). Returns the person, whose `code()` gives
 * fresh codes. With `totp: false` two-step sign-in stays off (the API does not admit such staff to the console).
 */
export async function newStaffAdmin(
  browser: Browser,
  baseURL: string,
  { totp = true, role = "admin" }: { totp?: boolean; role?: "admin" | "moderator" } = {},
): Promise<Person> {
  const context = await browser.newContext({ baseURL });
  try {
    const request = context.request;
    const email = `staff-${letterTag()}${Date.now().toString(36)}@staff-e2e.example.com`;
    const name = "Wanjiku Staff";
    await signUp(request, email, name);
    const updated = ownerSql(
      "UPDATE users SET staff_role = CAST(:'role' AS staff_role), demo_account = true WHERE email = :'email'" +
        " AND email LIKE '%@staff-e2e.example.com' RETURNING id;",
      { email, role },
    );
    expect(updated, "the staff admin").toMatch(/^[0-9a-f-]{36}$/);
    if (!totp) return new Person(email, name, "");
    const { secret } = await post<{ secret: string }>(request, "/api/auth/totp/enrol", { password: PASSWORD });
    const person = new Person(email, name, secret);
    await post(request, "/api/auth/totp/confirm", { code: await person.code() });
    return person;
  } finally {
    await context.close();
  }
}

/** A new developer signed in on `request` (the page's context), for the problem card as developers see it. */
export async function newDeveloper(request: APIRequestContext): Promise<string> {
  const email = `dev-${letterTag()}${Date.now().toString(36)}@example.com`;
  await signUp(request, email, "Achieng Otieno");
  return email;
}

export interface SavedExcerpt {
  id: string;
  niche: string;
  url: string;
  publisher: string;
  source_type: string;
  official: boolean;
  published_date: string;
  quote: string;
  freshness: "fresh" | "stale" | "archived";
}

/** The saved excerpts, as a signed-in staff admin reads them (GET /api/admin/research/sources). */
export async function savedExcerpts(request: APIRequestContext): Promise<SavedExcerpt[]> {
  const response = await request.get("/api/admin/research/sources");
  expect(response.status(), await response.text()).toBe(200);
  return ((await response.json()) as { excerpts: SavedExcerpt[] }).excerpts;
}

/**
 * Two live excerpts of the SACCO niche that publish a card naming SASRA: an official one (SASRA's own site, which
 * a card naming an organisation needs; D-45) and one from another publisher.
 */
export function saccoSources(excerpts: SavedExcerpt[]): [SavedExcerpt, SavedExcerpt] {
  const live = excerpts.filter((e) => e.niche === "microfinance-saccos" && e.freshness !== "archived");
  const official = live.find((e) => e.official);
  const other = live.find((e) => !e.official && e.publisher !== official?.publisher);
  expect(official && other, "a live official and a live news excerpt for microfinance-saccos").toBeTruthy();
  return [official!, other!];
}

export interface CandidateCard {
  title: string;
  statement: string;
  affectedGroup: string;
  namedOrgs: string[];
  sources: SavedExcerpt[];
  /** A run to attach the card to (the one the test started), or none. */
  runId?: string;
}

/**
 * Writes a research candidate as app_create_research_candidate would (see the module comment): the card's niche is
 * the sources' niche, its sources the saved excerpts with their ids as `excerpt_ref`. Returns the card's id.
 */
export function insertCandidate(card: CandidateCard): string {
  const sources = card.sources.map(({ id, url, publisher, source_type, published_date, quote }) => ({
    id,
    url,
    publisher,
    source_type,
    published_date,
    quote,
  }));
  return ownerSql(
    "WITH card AS (" +
      " INSERT INTO problems (id, source, niche_id, country, title, statement, affected_group, status, ai_generated," +
      " confidence, moderation_state, research_run_id, named_orgs)" +
      " SELECT gen_random_uuid(), 'research_agent', n.id, 'KE', :'title', :'statement', :'affected', 'candidate', true," +
      " 0.720, 'clear', CAST(NULLIF(:'run', '') AS uuid)," +
      " ARRAY(SELECT jsonb_array_elements_text(CAST(:'orgs' AS jsonb)))" +
      " FROM niches n WHERE n.slug = :'niche' RETURNING id" +
      "), cited AS (" +
      " INSERT INTO problem_sources (id, problem_id, url, publisher, source_type, published_date, retrieved_at, quote," +
      " excerpt_ref)" +
      " SELECT gen_random_uuid(), card.id, s.url, s.publisher, s.source_type, CAST(s.published_date AS date), now()," +
      " s.quote, s.id FROM card, jsonb_to_recordset(CAST(:'sources' AS jsonb))" +
      " AS s(id text, url text, publisher text, source_type text, published_date text, quote text)" +
      ") SELECT id FROM card;",
    {
      title: card.title,
      statement: card.statement,
      affected: card.affectedGroup,
      run: card.runId ?? "",
      orgs: JSON.stringify(card.namedOrgs),
      niche: card.sources[0].niche,
      sources: JSON.stringify(sources),
    },
  );
}

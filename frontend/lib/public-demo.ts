// The public-demo mode (REQ-FND-04; docs/platform/tasks/P28.md, track PD): one container serves the seeded product to
// anyone, with persona sign-in, a banner on every page, the account and upload controls switched off, and no indexing.
//
// The web reads the switch here and only here, on the server at run time: the same image runs with the mode on (the
// public demo) or off (everything else), so the value must never be fixed at build. It is not a NEXT_PUBLIC_ variable
// (those are inlined into the browser's bundles at build), it is read with a computed key (nothing the bundler can
// replace), and no client component imports this module (lib/public-demo.test.ts checks both). Client components that
// behave differently in the mode get a prop or a server-formatted sentence from the page instead.

/** The environment variable, the same name as the API's setting (backend Settings.PUBLIC_DEMO). */
export const PUBLIC_DEMO_VARIABLE = "PUBLIC_DEMO";

// What the API's settings read as true (pydantic's bool parsing): anything else, unset included, is off.
const TRUE_VALUES = new Set(["1", "true", "t", "yes", "y", "on"]);

type Env = Readonly<Record<string, string | undefined>>;

/** Whether the public-demo mode is on for this server process, read now (never cached, never inlined). */
export function publicDemoOn(env: Env = process.env): boolean {
  const value = env[PUBLIC_DEMO_VARIABLE];
  return typeof value === "string" && TRUE_VALUES.has(value.trim().toLowerCase());
}

/** The response header that keeps every page out of search engines while the mode is on (the API sends its own). */
export const ROBOTS_HEADER = { key: "X-Robots-Tag", value: "noindex, nofollow" } as const;

/** /robots.txt while the mode is on: every crawler, every path, disallowed. */
export const DISALLOW_ALL_ROBOTS = "User-agent: *\nDisallow: /\n";

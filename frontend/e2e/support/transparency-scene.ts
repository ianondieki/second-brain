import { spawnSync } from "node:child_process";

/**
 * Signed daily roots for /transparency (REQ-AUD-01, AT-D-1), so the page's populated state is asserted on every run
 * rather than only after the stack has been up for a full Nairobi day. Written as the database owner, the way the
 * other scenes reach the database (E2E_DATABASE_OWNER_URL, a libpq URL of the stack's database as bridge_owner).
 *
 * The rows: the Nairobi days three to five before today (never yesterday, which the nightly job closes, so a seeded
 * row cannot pre-empt a real root), each with a snapshot 30 minutes after its day ended (schema v2's
 * transparency_roots_guard), a 32-byte root and a 64-byte stand-in signature derived from the day (the page shows
 * them and never verifies them), signed under the newest key in use (the foreign key needs a published one).
 * transparency_roots is append-only (triggers refuse DELETE and TRUNCATE), so the rows stay; re-runs insert nothing
 * (ON CONFLICT DO NOTHING), and a day that already has a real root keeps it.
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

const SEED_ROOTS = `
INSERT INTO transparency_roots (day, merkle_root, signature, key_id, snapshot_at)
SELECT d.day,
       sha256(convert_to('e2e-transparency-root:' || d.day::text, 'UTF8')),
       sha512(convert_to('e2e-transparency-signature:' || d.day::text, 'UTF8')),
       k.key_id,
       (CAST(d.day + 1 AS timestamp) + interval '30 minutes') AT TIME ZONE 'Africa/Nairobi'
  FROM (SELECT CAST(now() AT TIME ZONE 'Africa/Nairobi' AS date) - n AS day FROM generate_series(3, 5) AS n) AS d
 CROSS JOIN (SELECT key_id FROM provenance_keys WHERE retired_at IS NULL ORDER BY created_at DESC LIMIT 1) AS k
    ON CONFLICT (day) DO NOTHING;
SELECT 'newest ' || day::text || ' ' || encode(merkle_root, 'hex') FROM transparency_roots ORDER BY day DESC LIMIT 1;
SELECT 'seeded ' || day::text FROM transparency_roots
 WHERE day BETWEEN CAST(now() AT TIME ZONE 'Africa/Nairobi' AS date) - 5 AND CAST(now() AT TIME ZONE 'Africa/Nairobi' AS date) - 3
 ORDER BY day DESC;
`;

export interface SeededRoots {
  /** The newest root of all (the page's latest sheet): its day (YYYY-MM-DD) and its root in lowercase hex. */
  newest: { day: string; root: string };
  /** The three seeded days present, newest first. */
  days: string[];
}

/** Seeds the three roots (idempotent) and reads back what the page should show. */
export function seedTransparencyRoots(): SeededRoots {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  const result = spawnSync("psql", [OWNER_DATABASE_URL, "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1"], {
    input: SEED_ROOTS,
    encoding: "utf-8",
    timeout: 15_000,
  });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
  const lines = result.stdout.trim().split("\n");
  const newest = lines.find((line) => line.startsWith("newest "))?.split(" ");
  if (!newest) throw new Error("no transparency root after seeding (is a provenance key registered?)");
  return {
    newest: { day: newest[1], root: newest[2] },
    days: lines.filter((line) => line.startsWith("seeded ")).map((line) => line.slice("seeded ".length)),
  };
}

import { spawnSync } from "node:child_process";

/**
 * D1 for a test developer (AC-IP-5: publishing needs a verified mobile number). The stack's SMS provider is the
 * in-memory fake (SMS_PROVIDER=fake): its codes never leave the API process, and the stored code is an HMAC under the
 * API's SECRET_KEY, so a browser test cannot read or recompute one. The helper therefore does what
 * app_confirm_phone_otp does on a correct code (d0 → d1), directly in the test database as its owner role, exactly as
 * the backend's integration builders create D1 developers.
 *
 * E2E_DATABASE_OWNER_URL is a libpq URL of the stack's database as bridge_owner (for example
 * postgresql://bridge_owner:…@127.0.0.1:5432/bridge). Without it, tests that need D1 skip. Test accounts only.
 */
export const OWNER_DATABASE_URL = process.env.E2E_DATABASE_OWNER_URL;

export function makeD1(email: string): void {
  if (!OWNER_DATABASE_URL) throw new Error("E2E_DATABASE_OWNER_URL is not set");
  if (!email.endsWith("@example.com")) throw new Error("makeD1 is for test accounts (@example.com) only");
  const sql =
    "UPDATE developer_profiles SET verification_level = 'd1', updated_at = now()" +
    " WHERE verification_level = 'd0' AND user_id = (SELECT id FROM users WHERE email = :'email');";
  // The address travels as a psql variable (quoted by psql), never spliced into the SQL text.
  const result = spawnSync("psql", [OWNER_DATABASE_URL, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", `email=${email}`], {
    input: sql,
    encoding: "utf-8",
    timeout: 15_000,
  });
  if (result.status !== 0) throw new Error(`psql failed: ${result.stderr || result.error?.message}`);
}

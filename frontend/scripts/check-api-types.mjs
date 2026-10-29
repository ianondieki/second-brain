// Fails when lib/api/schema.d.ts is out of date with backend/openapi.json (OpenAPI drift, docs/spec/08 CI).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "api-types-"));
const out = join(dir, "schema.d.ts");
try {
  const bin = join("node_modules", "openapi-typescript", "bin", "cli.js");
  execFileSync(process.execPath, [bin, "../backend/openapi.json", "-o", out], { stdio: "ignore" });
  const fresh = readFileSync(out, "utf8").replace(/\r\n/g, "\n");
  const committed = readFileSync("lib/api/schema.d.ts", "utf8").replace(/\r\n/g, "\n");
  if (fresh !== committed) {
    console.error("lib/api/schema.d.ts is stale: run `make api-types` and commit the result.");
    process.exit(1);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { accountHash } from "../palette/PaletteSlot";

import { Register } from "./Register";

/**
 * This build's id (`.next/BUILD_ID`, written by `next build`), which versions the service worker (`/sw.js?v=`): a new
 * build installs a new worker, which drops the old build's files and pages. "dev" where there is none (`next dev`).
 */
export function readBuildVersion(read: (path: string) => string = (path) => readFileSync(path, "utf8")): string {
  try {
    return read(join(process.cwd(), ".next", "BUILD_ID")).trim() || "dev";
  } catch {
    return "dev";
  }
}

let build: string | undefined;
/** The build's id, read once per server process. */
export function buildVersion(): string {
  build ??= readBuildVersion();
  return build;
}

/**
 * The offline part of the signed-in shell (P27 track F; D-69): the client island with the signed-in person's hash (the
 * command palette's, never the id) and the build. Never in the staff console (SignedInShell leaves it out there).
 */
export async function OfflineSlot() {
  return <Register hash={await accountHash()} version={buildVersion()} />;
}

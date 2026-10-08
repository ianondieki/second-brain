import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { ADMIN_SECTIONS } from "@/components/AdminNav";
import { DEV_SECTIONS } from "@/components/DevNav";
import { ORG_SECTIONS } from "@/components/OrgNav";

import { LOADING_DEV, LOADING_ORG, LOADING_STAFF } from "./LoadingNav";

// D-67 (P25; REQ-UX-01, REQ-UX-05): a loading screen draws the portal's own navigation, so nothing moves when the page
// arrives, with no client code (a link's prefetch of it then fetches no route script). Its section lists repeat the
// navs' (whose modules import next/link): they must stay equal, and the loading modules must import nothing client-side.
const shape = (list: readonly { key: string; href: string; Icon: unknown; roles?: readonly string[] }[]) =>
  list.map(({ key, href, Icon, roles }) => ({ key, href, Icon, roles: roles ? [...roles] : undefined }));

describe("LoadingNav", () => {
  it("lists exactly the sections OrgNav, DevNav and AdminNav list, with their icons and roles", () => {
    expect(shape(LOADING_ORG)).toEqual(shape(ORG_SECTIONS));
    expect(shape(LOADING_DEV)).toEqual(shape(DEV_SECTIONS));
    expect(shape(LOADING_STAFF)).toEqual(shape(ADMIN_SECTIONS));
  });

  it("and the loading screens import no client code: no next/link, no LinkPending, no nav module", () => {
    for (const file of ["LoadingNav.tsx", "PortalLoading.tsx", "AccountLoading.tsx", "../PortalNavBase.tsx"]) {
      const source = readFileSync(join(process.cwd(), "components/loading", file), "utf8");
      const imports = source.split("\n").filter((line) => line.startsWith("import ") && !line.startsWith("import type "));
      for (const line of imports) {
        expect(line, file).not.toMatch(/next\/link|LinkPending|\/(OrgNav|DevNav|AdminNav|PortalNav|PortalNavFor|SignedInShell|NotificationBell|TopBar)"/);
      }
    }
  });
});

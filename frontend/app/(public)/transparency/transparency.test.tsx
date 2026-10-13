import { cleanup, render, screen, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { resolveServerTree } from "@/test/server-tree";

import type { ProvenanceKey, TransparencyRoot } from "./transparency";

// REQ-AUD-01 (P28 track D, AT-D-1): the public /transparency page. The signed daily roots from GET /api/transparency
// (newest first, at most 30: day, root, snapshot time, key, signature) and the keys from
// GET /.well-known/provenance-keys.json (id, algorithm, public key, in use or retired), read on the server with no
// session; how to check a certificate links to /verify; no root yet is one sentence and one action; a failed read is
// one sentence and "Try again". The page carries no primary action and is indexable.

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api/server", () => ({ serverApi: () => ({ GET: mocks.get }) }));
vi.mock("next-intl/server", () => ({
  getTranslations: async (namespace: string) => createTranslator({ locale: "en", messages: en, namespace: namespace as never }),
  getLocale: async () => "en",
}));
vi.mock("@/components/TopBar", () => ({ TopBar: () => null }));
vi.mock("@/components/ThemeToggle", () => ({ ThemeToggle: () => null }));

const { readKeys, readRoots, readTransparency, keyAnchor, ROOTS_SHOWN } = await import("./transparency");
const { default: TransparencyPage, generateMetadata } = await import("./page");
const { VerifyShell } = await import("../verify/VerifyShell");

afterEach(cleanup);

const KID = "ed25519:e60ca1fa824c4587";
const OLD_KID = "ed25519:0b1d2c3e4f5a6b7c";
const SIGNATURE = "yOb8f/tzOczTbHQKg5eZY9ru2rIRb/26WUfNJKBr0LtcFTgXeoDKO6d/BOQCRSLT5iDow/VUlOTTf+P/lWtYDw==";

function root(day: string, overrides: Partial<TransparencyRoot> = {}): TransparencyRoot {
  const digit = day.slice(-1);
  return { day, merkle_root: digit.repeat(64), signature: SIGNATURE, key_id: KID, snapshot_at: `${day}T21:30:05Z`, ...overrides };
}

const ACTIVE: ProvenanceKey = {
  kid: KID,
  kty: "OKP",
  crv: "Ed25519",
  alg: "EdDSA",
  use: "sig",
  x: "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo",
  pem: "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo=\n-----END PUBLIC KEY-----\n",
  created_at: "2026-09-20T08:00:00Z",
  retired_at: null,
};
const RETIRED: ProvenanceKey = { ...ACTIVE, kid: OLD_KID, created_at: "2026-08-01T08:00:00Z", retired_at: "2026-09-20T08:00:00Z" };

/** The API as the page reads it: one answer per path (a thrown error stands for a timeout or a refused connection). */
function api({ roots, keys }: { roots?: TransparencyRoot[] | Error | number; keys?: ProvenanceKey[] | Error | number }) {
  mocks.get.mockImplementation(async (path: string) => {
    const answer = path === "/api/transparency" ? roots : keys;
    if (answer instanceof Error) throw answer;
    if (typeof answer === "number") return { data: undefined, response: new Response(null, { status: answer }) };
    const data = path === "/api/transparency" ? { roots: answer } : { keys: answer };
    return { data, response: new Response(null, { status: 200 }) };
  });
}

beforeEach(() => {
  mocks.get.mockReset();
});

describe("the reads", () => {
  it("ask for a month of roots with no session or address, bounded, and keep them newest first", async () => {
    api({ roots: [root("2026-10-10"), root("2026-10-12"), root("2026-10-11")] });
    expect((await readRoots())!.map((r) => r.day)).toEqual(["2026-10-12", "2026-10-11", "2026-10-10"]);
    const [path, options] = mocks.get.mock.calls[0];
    expect(path).toBe("/api/transparency");
    expect(options.params).toEqual({ query: { limit: ROOTS_SHOWN } });
    expect(ROOTS_SHOWN).toBe(30);
    expect(options.headers).toBeUndefined();
    expect(options.signal).toBeInstanceOf(AbortSignal);
    expect(options.cache).toBe("no-store");
  });

  it("never show more than 30 roots", async () => {
    const days = Array.from({ length: 40 }, (_, i) => root(`2026-09-${String((i % 28) + 1).padStart(2, "0")}`, { key_id: `k${i}` }));
    api({ roots: days });
    expect(await readRoots()).toHaveLength(30);
  });

  it("list keys in use first, then retired ones", async () => {
    api({ keys: [RETIRED, ACTIVE] });
    expect((await readKeys())!.map((k) => k.kid)).toEqual([KID, OLD_KID]);
    expect(mocks.get.mock.calls[0][0]).toBe("/.well-known/provenance-keys.json");
  });

  it.each([
    ["an error status", 503],
    ["a thrown call (a timeout, a refused connection)", Object.assign(new Error("timed out"), { name: "TimeoutError" })],
  ])("settle %s into null, each part on its own", async (_, failure) => {
    api({ roots: failure as never, keys: [ACTIVE] });
    expect(await readTransparency()).toEqual({ roots: null, keys: [ACTIVE] });
    api({ roots: [], keys: failure as never });
    expect(await readTransparency()).toEqual({ roots: [], keys: null });
  });

  it("anchor a key id so a root can link to it", () => {
    expect(keyAnchor(KID)).toBe("key-ed25519-e60ca1fa824c4587");
  });
});

async function openPage() {
  return render(<>{await resolveServerTree(await TransparencyPage())}</>);
}

const part = (name: string) => document.querySelector<HTMLElement>(`[data-transparency='${name}']`)!;

describe("/transparency", () => {
  it("says what the roots are, links to /verify and is indexable", async () => {
    api({ roots: [root("2026-10-12")], keys: [ACTIVE] });
    await openPage();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Daily audit fingerprints");
    expect(screen.getByText(en.transparency.lead)).toBeTruthy();
    expect(within(part("how-to")).getByRole("link", { name: "Check a certificate" }).getAttribute("href")).toBe("/verify");
    expect(document.querySelector("[data-primary]")).toBeNull();
    const metadata = await generateMetadata();
    expect(metadata).toEqual({ title: "Transparency", description: en.transparency.description });
    expect(metadata.robots).toBeUndefined();
  });

  it("shows the latest root as the sheet and the earlier days newest first, with their time, key and signature", async () => {
    api({ roots: [root("2026-10-10"), root("2026-10-12"), root("2026-10-11", { snapshot_at: null, key_id: OLD_KID })], keys: [ACTIVE, RETIRED] });
    await openPage();

    const sheet = screen.getByRole("region", { name: "The fingerprint for 12 Oct 2026" });
    expect(sheet.getAttribute("data-root")).toBe("2026-10-12");
    // 21:30:05 UTC on the 12th is 00:30 on the 13th in Nairobi.
    expect(sheet.textContent).toContain("It covers the whole audit history as it stood on 13 Oct 2026, 00:30 Nairobi time.");
    expect(sheet.querySelector("[data-fingerprint]")!.getAttribute("data-fingerprint")).toBe("2".repeat(64));
    expect(within(sheet).getByRole("link", { name: KID }).getAttribute("href")).toBe(`#${keyAnchor(KID)}`);
    expect(sheet.textContent).toContain(SIGNATURE);

    const rows = [...part("earlier").querySelectorAll("li")];
    expect(rows.map((row) => row.getAttribute("data-root"))).toEqual(["2026-10-11", "2026-10-10"]);
    expect(rows[0].querySelector("h3")!.textContent).toBe("11 Oct 2026");
    expect(rows[0].querySelector("[data-merkle-root]")!.textContent).toBe("1".repeat(64));
    expect(rows[0].textContent).toContain(`Signed with ${OLD_KID}.`);
    expect(within(rows[0]).getByRole("link", { name: OLD_KID }).getAttribute("href")).toBe(`#${keyAnchor(OLD_KID)}`);
    expect(rows[1].textContent).toContain(`Taken 11 Oct 2026, 00:30 Nairobi time, signed with ${KID}.`);
    expect(rows[1].querySelector("details summary")!.textContent).toBe("Signature");
    expect(rows[1].querySelector("details")!.textContent).toContain(SIGNATURE);

    expect(within(part("roots")).getByRole("link", { name: "These fingerprints as JSON" }).getAttribute("href")).toBe(
      "/api/transparency?limit=30",
    );
  });

  it("lists the signing keys with their algorithm, public key and status in words", async () => {
    api({ roots: [root("2026-10-12")], keys: [RETIRED, ACTIVE] });
    await openPage();
    const keys = part("keys");
    expect(within(keys).getByRole("heading", { level: 2 }).textContent).toBe("Signing keys");
    expect(keys.textContent).toContain("bridge-transparency-root-v1:<day>:<root>");
    const rows = [...keys.querySelectorAll<HTMLElement>("[data-key]")];
    expect(rows.map((row) => row.id)).toEqual([keyAnchor(KID), keyAnchor(OLD_KID)]);
    expect(within(rows[0]).getByRole("heading", { level: 3 }).textContent).toBe(KID);
    expect(rows[0].querySelector("[data-key-status]")!.textContent).toBe("In use");
    expect(rows[0].textContent).toContain("Ed25519 (EdDSA)");
    expect(rows[0].textContent).toContain("20 Sep 2026");
    expect(rows[0].querySelector("pre")!.textContent).toBe(ACTIVE.pem.trim());
    expect(rows[1].querySelector("[data-key-status]")!.textContent).toBe("Retired 20 Sep 2026");
    expect(rows[1].querySelector("[data-key-status] svg")).not.toBeNull();
    expect(within(keys).getByRole("link", { name: "The keys as JSON" }).getAttribute("href")).toBe("/.well-known/provenance-keys.json");
  });

  it("before the first full day: one sentence and one action, and the keys still listed", async () => {
    api({ roots: [], keys: [ACTIVE] });
    await openPage();
    const empty = part("roots").querySelector<HTMLElement>("[data-empty-state]")!;
    expect(empty.querySelector("p")!.textContent).toBe("The first daily fingerprint appears after the first full day.");
    expect(within(empty).getAllByRole("link").map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["Check a certificate", "/verify"],
    ]);
    expect(document.querySelector("[data-root]")).toBeNull();
    expect(part("keys").querySelectorAll("[data-key]")).toHaveLength(1);
  });

  it("a part that did not load says so and offers to try again; the other part still shows", async () => {
    api({ roots: 503, keys: [ACTIVE] });
    await openPage();
    const roots = part("roots").querySelector<HTMLElement>("[data-empty-state]")!;
    expect(roots.querySelector("p")!.textContent).toBe(en.transparency.unavailable);
    expect(within(roots).getByRole("link", { name: "Try again" }).getAttribute("href")).toBe("/transparency");
    expect(part("keys").querySelectorAll("[data-key]")).toHaveLength(1);

    cleanup();
    api({ roots: [root("2026-10-12")], keys: new Error("refused") });
    await openPage();
    const keys = part("keys").querySelector<HTMLElement>("[data-empty-state]")!;
    expect(keys.querySelector("p")!.textContent).toBe(en.transparency.keysUnavailable);
    expect(within(keys).getByRole("link", { name: "Try again" }).getAttribute("href")).toBe("/transparency");
    expect(document.querySelector("[data-root='2026-10-12']")).not.toBeNull();
  });

  it("is linked from the public footer and, in one line, from /verify", async () => {
    api({ roots: [], keys: [] });
    await openPage();
    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Transparency" }).getAttribute("href")).toBe("/transparency");

    cleanup();
    render(<>{await resolveServerTree(<VerifyShell>{null}</VerifyShell>)}</>);
    const aside = screen.getByRole("complementary");
    expect(aside.querySelector("[data-verify='transparency']")!.textContent).toBe(
      "Every day’s audit fingerprint is public on the transparency page.",
    );
    expect(within(aside).getByRole("link", { name: "transparency page" }).getAttribute("href")).toBe("/transparency");
  });
});

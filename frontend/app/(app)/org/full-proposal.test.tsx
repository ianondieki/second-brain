import { cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { EvaluationNda, NdaResult } from "./data";
import { FullProposal, type FullProposalProps } from "./inbox/[proposalId]/FullProposal";

// The Tier-2 area of the organisation's proposal page (REQ-REPO-01, REQ-PROV-03): the marked page is framed only when
// the person asked for it after accepting the NDA (each load is a logged view), and the frame can run no script,
// submit no form and not navigate this page (only its links may open new tabs), with no referrer sent.

vi.mock("next-intl/server", async () => {
  const en = (await import("@/locales/en.json")).default as unknown as Record<string, unknown>;
  const lookup = (namespace: string, key: string, values: Record<string, unknown> = {}) => {
    let node: unknown = en[namespace];
    for (const part of key.split(".")) node = (node as Record<string, unknown> | undefined)?.[part];
    if (typeof node !== "string") throw new Error(`missing message ${namespace}.${key}`);
    return node.replace(/\{(\w+)\}/g, (slot, name: string) => (name in values ? String(values[name]) : slot));
  };
  return {
    getTranslations: async (namespace: string) => (key: string, values?: Record<string, unknown>) =>
      lookup(namespace, key, values),
    getLocale: async () => "en",
  };
});
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: vi.fn() } }));

afterEach(cleanup);

const ORG = "01a0ee62-0000-7000-8000-00000000000a";
const PROPOSAL = "01a0ee62-f783-733e-9321-9f34ec389ac2";
const NDA: EvaluationNda = {
  template_id: "01a0ee5e-69b3-71cd-8bb7-36281a854e93",
  version: "v1",
  sha256: "f0b8733eb8366e8f3f325686f1cc53c8ed7584c70c85dc7671522ffdaf01ad65",
  body: "DRAFT\n\n[[LEGAL-PLACEHOLDER:evaluation-nda-v1]]\n",
  is_placeholder: true,
  logging_notice: { version: "v1", text: "The owner of this proposal will see that you opened it." },
  acceptance_id: null,
  accepted_at: null,
};
const ACCEPTED: EvaluationNda = {
  ...NDA,
  acceptance_id: "01a0ee62-f915-7394-babc-2c053d15626b",
  accepted_at: "2026-09-29T18:17:38Z",
};

const STATES: Record<string, NdaResult> = {
  refused: { kind: "refused", refusal: "grant_required" },
  nda: { kind: "nda", nda: NDA },
  accepted: { kind: "nda", nda: ACCEPTED },
};

async function render(nda: NdaResult, viewing: boolean) {
  const props: FullProposalProps = {
    orgId: ORG,
    orgName: "Amani Foods",
    proposalId: PROPOSAL,
    title: "Maziwa baridi",
    nda,
    viewing,
    hrefs: {
      here: `/org/inbox/${PROPOSAL}`,
      view: `/org/inbox/${PROPOSAL}?view=full`,
      inbox: "/org/inbox",
    },
  };
  return renderWithIntl(await FullProposal(props));
}

describe("FullProposal", () => {
  it.each(Object.entries(STATES))("never frames the marked page in the %s state without ?view=full", async (_, nda) => {
    const { container } = await render(nda, false);
    expect(container.querySelectorAll("iframe")).toHaveLength(0);
    expect(container.innerHTML).not.toContain("/tier2");
  });

  it.each([
    ["refused", STATES.refused],
    ["nda", STATES.nda],
  ])("never frames it in the %s state, even when ?view=full is asked for", async (_, nda) => {
    const { container } = await render(nda, true);
    expect(container.querySelectorAll("iframe")).toHaveLength(0);
  });

  it("frames the marked page, sandboxed and without a referrer, once accepted and asked for", async () => {
    const { container } = await render(STATES.accepted, true);
    const frames = container.querySelectorAll("iframe");
    expect(frames).toHaveLength(1);
    const frame = frames[0];
    expect(frame.hasAttribute("data-tier2-frame")).toBe(true);
    expect(frame.getAttribute("src")).toBe(`/api/orgs/${ORG}/proposals/${PROPOSAL}/tier2`);
    // Exactly this: no allow-scripts, allow-same-origin, allow-forms or allow-top-navigation.
    expect(frame.getAttribute("sandbox")).toBe("allow-popups allow-popups-to-escape-sandbox");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(frame.getAttribute("title")).toBe("Full proposal: Maziwa baridi, marked for you");
    expect(container.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("offers each state's one primary action", async () => {
    const primary = async (nda: NdaResult) =>
      [...(await render(nda, false)).container.querySelectorAll("[data-primary]")].map((el) => el.textContent);
    expect(await primary(STATES.nda)).toEqual(["Accept and view"]);
    cleanup();
    expect(await primary(STATES.accepted)).toEqual(["View full proposal"]);
    cleanup();
    expect(await primary(STATES.refused)).toEqual([]);
  });

  it("points an owner who is also a member to their own preview, with a plain link", async () => {
    const { container } = await render({ kind: "refused", refusal: "nda_not_needed" }, true);
    expect(container.querySelectorAll("iframe")).toHaveLength(0);
    const refusal = container.querySelector('[data-refusal="nda_not_needed"]')!;
    expect(refusal.querySelector("p")?.textContent).toContain("You own this proposal");
    const links = refusal.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe(`/api/me/proposals/${PROPOSAL}/tier2`);
  });
});

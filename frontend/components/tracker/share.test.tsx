import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import { SHARE_ORIGINS, shareRefusalOf, type ShareOutcome } from "./share";
import { ShareTier2 } from "./ShareTier2";

// REQ-ENG-04: the developer's manual Tier-2 share on an engagement an organisation opened, with a fresh second
// factor when the API asks (ADR-002), the confirmation in the approved logging phrasing (docs/spec/04 4.2).

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  refresh.mockReset();
});

const SHARED: ShareOutcome = {
  ok: true,
  share: {
    engagement_id: "e1",
    shared: true,
    grant_id: "g1",
    source: "org_interest",
    shared_at: "2026-09-30T08:00:00Z",
    counts_as_unlock: true,
  },
};

function renderShare(shareImpl: (id: string) => Promise<ShareOutcome>, primary = true) {
  const confirmImpl = vi.fn(async () => ({ ok: true as const }));
  renderWithIntl(
    <ShareTier2
      engagementId="e1"
      orgName="Maziwa Buyers"
      enrolled
      primary={primary}
      shareImpl={shareImpl}
      confirmImpl={confirmImpl}
    />,
  );
  return { confirmImpl };
}

describe("the share's refusals", () => {
  it("are words of their own for each API code, by status otherwise", () => {
    const code = (c: string) => ({ detail: { code: c, message: "server text" } });
    expect(shareRefusalOf(403, code("step_up_required"))).toBe("stepUp");
    expect(shareRefusalOf(403, code("not_your_action"))).toBe("notAllowed");
    expect(shareRefusalOf(409, code("share_not_applicable"))).toBe("notApplicable");
    expect(shareRefusalOf(409, code("engagement_ended"))).toBe("ended");
    expect(shareRefusalOf(409, code("proposal_unavailable"))).toBe("unavailable");
    expect(shareRefusalOf(403, code("mfa_enrolment_required"))).toBe("mfaSetup");
    expect(shareRefusalOf(404, code("not_found"))).toBe("notFound");
    expect(shareRefusalOf(500, undefined)).toBe("generic");
  });

  it("are offered only on engagements an organisation opened", () => {
    expect([...SHARE_ORIGINS].sort()).toEqual(["org_agent_match", "org_browse"]);
  });
});

describe("Share the full proposal", () => {
  it("asks first, in the approved logging phrasing, then shares and refreshes the tracker", async () => {
    const shareImpl = vi.fn(async () => SHARED);
    renderShare(shareImpl);
    expect(screen.getByText(/sees only the public teaser/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" }));
    expect(shareImpl).not.toHaveBeenCalled();
    const question = document.querySelector("[data-share-confirm]")!;
    expect(question.textContent).toContain("every view is logged and watermarked to the viewer");
    expect(question.textContent).toContain("Maziwa Buyers");
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" })));
    expect(shareImpl).toHaveBeenCalledWith("e1");
    expect(screen.getByRole("status").textContent).toBe(
      en.tier2Share.sharedNow.replace("{org}", "Maziwa Buyers"),
    );
    expect(refresh).toHaveBeenCalled();
  });

  it("asks for a fresh code when the API wants one, then shares once more", async () => {
    const shareImpl = vi
      .fn<(id: string) => Promise<ShareOutcome>>()
      .mockResolvedValueOnce({ ok: false, refusal: "stepUp" })
      .mockResolvedValueOnce(SHARED);
    const { confirmImpl } = renderShare(shareImpl);
    fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" })));
    const code = screen.getByLabelText("Authenticator code");
    fireEvent.change(code, { target: { value: "123456" } });
    await act(async () => fireEvent.submit(code.closest("form")!));
    expect(confirmImpl).toHaveBeenCalledWith("123456");
    await waitFor(() => expect(shareImpl).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("status").textContent).toContain("can now open the full proposal");
  });

  it("says why when it was refused, with nothing shared", async () => {
    renderShare(async () => ({ ok: false, refusal: "ended" }));
    fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" }));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Share the full proposal" })));
    expect(screen.getByRole("alert").textContent).toBe(en.tier2Share.refusal.ended);
    expect(refresh).toHaveBeenCalled();
  });

  it("is a secondary button while the tracker has another primary action", () => {
    renderShare(async () => SHARED, false);
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });
});

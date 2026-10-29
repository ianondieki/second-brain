import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en.json";
import { renderWithIntl } from "@/test/intl";

import type { InterestRefusal } from "../../../scout";
import { ExpressInterest } from "./ExpressInterest";

// REQ-ENG-04 (AC-TRACK-8/a from a scout match): the signatory names the contact, the POST carries origin
// org_agent_match with the match, a stale second factor asks for a code and the request runs once more, and the
// tracker opens; refusals are fixed sentences (never the server's text).

const push = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh }) }));

afterEach(() => {
  cleanup();
  push.mockReset();
  refresh.mockReset();
});

const ME = "0192a7c4-0000-7000-8000-0000000000c1";
const OTHER = "0192a7c4-0000-7000-8000-0000000000c2";
type Post = NonNullable<Parameters<typeof ExpressInterest>[0]["post"]>;
type Result = Awaited<ReturnType<Post>>;

function renderInterest(post: Post, query = "", today?: string | null) {
  const confirmImpl = vi.fn(async () => ({ ok: true as const }));
  renderWithIntl(
    <ExpressInterest
      orgId="org-1"
      orgName="Maziwa Buyers"
      matchId="match-1"
      proposalId="proposal-1"
      members={[
        { user_id: OTHER, display_name: "Baraka Mwangi" },
        { user_id: ME, display_name: "Rita Wanjiru" },
      ]}
      myUserId={ME}
      enrolled
      query={query}
      today={today}
      post={post}
      confirmImpl={confirmImpl}
    />,
  );
  return { confirmImpl };
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: en.expressInterest.button }));
  await waitFor(() => expect(document.querySelector("[data-interest-form]")).not.toBeNull());
}

async function send() {
  await act(async () => fireEvent.submit(document.querySelector("[data-interest-form]")!));
}

describe("Express interest", () => {
  it("starts the contact-by date on the platform's day the API sends (REQ-ENG-10), the earliest it takes", async () => {
    const post = vi.fn<Post>(async () => ({ ok: true, engagementId: "eng-1" }));
    renderInterest(post, "", "2031-03-04");
    await open();
    const by = screen.getByLabelText(en.expressInterest.by) as HTMLInputElement;
    expect(by.value).toBe("2031-03-04");
    expect(by.min).toBe("2031-03-04");
    await send();
    expect(post.mock.calls[0][0]).toMatchObject({ contact_by: "2031-03-04" });
  });

  it("without the platform's day, defaults to the browser's day and sets no earliest date", async () => {
    const post = vi.fn<Post>(async () => ({ ok: true, engagementId: "eng-1" }));
    renderInterest(post, "", null);
    await open();
    const by = screen.getByLabelText(en.expressInterest.by) as HTMLInputElement;
    expect(by.value).toBe(new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Nairobi" }).format(new Date()));
    expect(by.hasAttribute("min")).toBe(false);
  });

  it("sends the match's interest with the signed-in contact by default, then opens the tracker", async () => {
    const post = vi.fn<Post>(async () => ({ ok: true, engagementId: "eng-1" }));
    renderInterest(post, "?org=org-1");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    await open();
    expect((screen.getByLabelText(en.expressInterest.person) as HTMLSelectElement).value).toBe(ME);
    fireEvent.change(screen.getByLabelText(en.expressInterest.channel), { target: { value: "phone" } });
    await send();
    expect(post).toHaveBeenCalledWith({
      proposal_id: "proposal-1",
      origin: "org_agent_match",
      match_id: "match-1",
      contact_user_id: ME,
      channel: "phone",
      contact_by: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
    });
    expect(push).toHaveBeenCalledWith("/org/engagements/eng-1?org=org-1");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(0);
  });

  it("asks for a fresh code when the API wants one, then sends once more", async () => {
    const post = vi
      .fn<Post>()
      .mockResolvedValueOnce({ ok: false, refusal: "stepUp" })
      .mockResolvedValueOnce({ ok: true, engagementId: "eng-1" });
    const { confirmImpl } = renderInterest(post);
    await open();
    await send();
    const code = screen.getByLabelText("Authenticator code");
    expect(document.querySelectorAll("[data-primary]")).toHaveLength(1);
    fireEvent.change(code, { target: { value: "654321" } });
    await act(async () => fireEvent.submit(code.closest("form")!));
    expect(confirmImpl).toHaveBeenCalledWith("654321");
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(push).toHaveBeenCalledWith("/org/engagements/eng-1");
  });

  it("focuses the refusal that follows a step-up, and gives focus back to the button on Cancel", async () => {
    const post = vi
      .fn<Post>()
      .mockResolvedValueOnce({ ok: false, refusal: "stepUp" })
      .mockResolvedValueOnce({ ok: false, refusal: "org_not_e2" });
    renderInterest(post);
    await open();
    await send();
    const code = screen.getByLabelText("Authenticator code");
    fireEvent.change(code, { target: { value: "654321" } });
    await act(async () => fireEvent.submit(code.closest("form")!));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("alert")));
    fireEvent.click(screen.getByRole("button", { name: en.expressInterest.cancel }));
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("button", { name: en.expressInterest.button })),
    );
  });

  it.each<[InterestRefusal, string, boolean]>([
    ["role_required", en.expressInterest.refusal.role_required.replace("{org}", "Maziwa Buyers"), false],
    ["org_not_e2", en.expressInterest.refusal.org_not_e2.replace("{org}", "Maziwa Buyers"), false],
    ["engagement_exists", en.expressInterest.refusal.engagement_exists.replace("{org}", "Maziwa Buyers"), true],
    ["proposal_unavailable", en.expressInterest.refusal.proposal_unavailable, true],
    ["invalidContactBy", en.expressInterest.refusal.invalidContactBy, false],
  ])("words %s with its fixed sentence", async (refusal, sentence, refreshes) => {
    renderInterest(async (): Promise<Result> => ({ ok: false, refusal }));
    await open();
    await send();
    expect(screen.getByRole("alert").textContent).toBe(sentence);
    expect(refresh).toHaveBeenCalledTimes(refreshes ? 1 : 0);
    expect(push).not.toHaveBeenCalled();
  });
});

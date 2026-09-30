import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { decide, getRun, Outcome, startRun } from "./calls";
import { Decision } from "./Decision";
import type { Run } from "./research";
import { StartRun } from "./StartRun";

const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));

afterEach(cleanup);
beforeEach(() => {
  router.refresh.mockReset();
});

const OPTIONS = [
  { slug: "agriculture", label: "Agriculture" },
  { slug: "health", label: "Health" },
];

function run(status: Run["status"], extra: Partial<Run> = {}): Run {
  return {
    id: "01a0f016-2e64-7294-9e44-77fa421dce09",
    niche: "health",
    country: "KE",
    county_code: null,
    status,
    started_by: "01a0f014-b507-70d8-9f0e-4097336a5fb0",
    created_at: "2026-09-30T02:13:00Z",
    finished_at: null,
    searches: 0,
    fetches: 0,
    input_tokens: 0,
    candidates: 0,
    discarded: 0,
    cost_usd: "0.000000",
    stop_reason: null,
    demo_fallback: false,
    ...extra,
  };
}

async function hydrate() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Start run" })).toHaveProperty("disabled", false));
}

describe("StartRun (REQ-RES-01)", () => {
  it("starts a run for the chosen niche, follows it until it ends, then fetches the page again", async () => {
    const startImpl = vi.fn<typeof startRun>(async () => ({ ok: true, data: run("running") }) as Outcome<Run>);
    const statuses: Run["status"][] = ["running", "completed"];
    const getRunImpl = vi.fn<typeof getRun>(async () => ({ ok: true, data: run(statuses.shift() ?? "completed") }));
    renderWithIntl(<StartRun options={OPTIONS} startImpl={startImpl} getRunImpl={getRunImpl} pollMs={5} />);
    await hydrate();
    expect(screen.getByRole("button", { name: "Start run" }).hasAttribute("data-primary")).toBe(true);

    fireEvent.change(screen.getByLabelText("Niche"), { target: { value: "health" } });
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveProperty(
        "textContent",
        "The Health run is going. This usually takes a few seconds.",
      ),
    );
    expect(startImpl).toHaveBeenCalledWith("health");

    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveProperty(
        "textContent",
        "The Health run has finished. Its result is under Recent runs.",
      ),
    );
    expect(getRunImpl).toHaveBeenCalledTimes(2);
    expect(router.refresh).toHaveBeenCalledTimes(1);
  });

  it("follows a run that was already going when the page was drawn", async () => {
    const getRunImpl = vi.fn<typeof getRun>(async () => ({ ok: true, data: run("stopped") }));
    renderWithIntl(
      <StartRun options={OPTIONS} active={{ runId: "r1", name: "Agriculture" }} getRunImpl={getRunImpl} pollMs={5} />,
    );
    await waitFor(() => expect(router.refresh).toHaveBeenCalledTimes(1));
    expect(getRunImpl).toHaveBeenCalledWith("r1");
    expect(screen.getByRole("status").textContent).toBe(
      "The Agriculture run has finished. Its result is under Recent runs.",
    );
  });

  it("stops following after about a minute and offers a refresh", async () => {
    vi.useFakeTimers();
    try {
      const getRunImpl = vi.fn<typeof getRun>(async () => ({ ok: true, data: run("running") }));
      renderWithIntl(
        <StartRun options={OPTIONS} active={{ runId: "r1", name: "Health" }} getRunImpl={getRunImpl} pollMs={1500} />,
      );
      for (let i = 0; i < 40; i++) {
        await act(async () => {
          await vi.advanceTimersByTimeAsync(1500);
        });
      }
      expect(getRunImpl).toHaveBeenCalledTimes(40);
      expect(screen.getByRole("status").textContent).toBe(
        "The Health run is still going. Refresh the page in a minute to see its result.",
      );
      fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
      expect(router.refresh).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows each refusal as its own sentence, never the API's words", async () => {
    const startImpl = vi.fn<typeof startRun>(async () => ({
      ok: false,
      refusal: { kind: "refusal", code: "run_in_progress" },
    }));
    renderWithIntl(<StartRun options={OPTIONS} startImpl={startImpl} />);
    await hydrate();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "A run of this niche is already going. Wait for it to finish, then start another.",
    );
    expect(startImpl).toHaveBeenCalledWith("agriculture");
  });

  it("asks for a fresh code when the second factor is stale, then starts the run", async () => {
    const outcomes: Outcome<Run>[] = [
      { ok: false, refusal: { kind: "stepUp" } },
      { ok: true, data: run("running") },
    ];
    const startImpl = vi.fn<typeof startRun>(async () => outcomes.shift()!);
    const getRunImpl = vi.fn<typeof getRun>(async () => ({ ok: true, data: run("completed") }));
    const { container } = renderWithIntl(
      <StartRun options={OPTIONS} startImpl={startImpl} getRunImpl={getRunImpl} pollMs={5} />,
    );
    await hydrate();
    fireEvent.click(screen.getByRole("button", { name: "Start run" }));
    await screen.findByLabelText("Code from your app");
    expect(container.querySelector('[data-refusal="step_up_required"]')).not.toBeNull();
    expect(startImpl).toHaveBeenCalledTimes(1);
  });
});

describe("Decision (REQ-RES-01, D-45)", () => {
  const props = {
    problemId: "01a0f015-0feb-76bd-8eec-21b72f9f10e8",
    publicHref: "/problems/01a0f015-0feb-76bd-8eec-21b72f9f10e8",
    researchHref: "/admin/research",
  };

  it("approves a card and links to its public page", async () => {
    const decideImpl = vi.fn<typeof decide>(async () => ({ ok: true, data: { status: "published" } }));
    renderWithIntl(<Decision {...props} needsChecklist={false} decideImpl={decideImpl} />);
    expect(screen.getByRole("button", { name: "Approve and publish" }).hasAttribute("data-primary")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    expect(await screen.findByText("Published. Signed-in people can now see this card and its sources.")).toBeTruthy();
    expect(decideImpl).toHaveBeenCalledWith(props.problemId, "approve", false);
    expect(screen.getByRole("link", { name: "Open the public card" }).getAttribute("href")).toBe(props.publicHref);
    expect(screen.queryByRole("button", { name: "Approve and publish" })).toBeNull();
  });

  it("needs the checklist ticked before a card naming an organisation is approved", async () => {
    const decideImpl = vi.fn<typeof decide>(async () => ({ ok: true, data: { status: "published" } }));
    renderWithIntl(<Decision {...props} needsChecklist decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    expect(screen.getByText("Tick the checklist before you approve this card.")).toBeTruthy();
    expect(decideImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("I have worked through the checklist above for this card."));
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    await screen.findByText("Published. Signed-in people can now see this card and its sources.");
    expect(decideImpl).toHaveBeenCalledWith(props.problemId, "approve", true);
  });

  it("explains a failed publish check in plain words and keeps the card open for a decision", async () => {
    const decideImpl = vi.fn<typeof decide>(async () => ({
      ok: false,
      refusal: { kind: "publish", reason: "non_latin_text" },
    }));
    renderWithIntl(<Decision {...props} needsChecklist={false} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      "This card cannot be published: its text uses letters or digits outside the Latin alphabet, which can disguise a name. Reject it.",
    );
    expect(screen.getByRole("button", { name: "Reject" })).toBeTruthy();
  });

  it("asks once more before rejecting, then keeps the card private", async () => {
    const decideImpl = vi.fn<typeof decide>(async () => ({ ok: true, data: { status: "rejected" } }));
    renderWithIntl(<Decision {...props} needsChecklist={false} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(screen.getByText("Reject this card? It stays private and cannot be published later.")).toBeTruthy();
    expect(decideImpl).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getByRole("button", { name: "Reject card" }));
    await screen.findByText("Rejected. The card stays private.");
    expect(decideImpl).toHaveBeenCalledWith(props.problemId, "reject", false);
    expect(screen.queryByRole("link", { name: "Open the public card" })).toBeNull();
  });

  it("asks for a fresh code when the second factor is stale", async () => {
    const decideImpl = vi.fn<typeof decide>(async () => ({ ok: false, refusal: { kind: "stepUp" } }));
    renderWithIntl(<Decision {...props} needsChecklist={false} decideImpl={decideImpl} />);
    fireEvent.click(screen.getByRole("button", { name: "Approve and publish" }));
    expect(await screen.findByLabelText("Code from your app")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy();
  });
});

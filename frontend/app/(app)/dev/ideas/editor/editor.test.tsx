import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { Outcome } from "../calls";
import {
  EMPTY_STATE,
  type Attachment,
  type AttestationText,
  type EditorState,
  type MyProposal,
  type NicheNode,
  type ProblemCard,
  type PublishResult,
} from "../ideas";
import type { PublishProblem, SaveProblem, UploadProblem } from "../outcomes";
import { Attachments } from "./Attachments";
import { Editor, type EditorProps } from "./Editor";
import { ProblemPicker, type ProblemPickerProps } from "./ProblemPicker";

// REQ-PROP-01 (F2): the three-step editor. docs/spec/07 items 2 and 6 (one primary action per step; the stepper is an
// <ol> with aria-current="step"), the sanitiser's findings next to their fields, the three attestations and the
// publish refusals (403 d1_required, 402 plan_limit, 409 attestation text changed).

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }) }));

// jsdom has no layout: the editor scrolls a new step's heading into view.
Element.prototype.scrollIntoView ??= function scrollIntoView() {};

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  push.mockReset();
});

const NICHES: NicheNode[] = [
  {
    id: "0199a000-0000-7000-8000-00000000000a",
    slug: "agriculture",
    name: "Agriculture",
    label: "Agriculture",
    isic_code: null,
    children: [
      {
        id: "0199a000-0000-7000-8000-00000000000b",
        slug: "dairy",
        name: "Dairy",
        label: "Agriculture › Dairy",
        isic_code: null,
      },
    ],
  },
];

const TEXT: AttestationText = {
  version: "2026-09-29.1",
  sha256: "ab",
  statements: [
    { key: "created_it", text: "I created this proposal." },
    { key: "not_owned_by_employer_or_client", text: "It is not owned by my employer, a university or a client." },
    { key: "no_third_party_confidential", text: "It contains no confidential information that belongs to anyone else." },
  ],
};

const PROBLEM: ProblemCard = {
  id: "0199a000-0000-7000-8000-000000000101",
  title: "Milk spoils before collection",
  source: "developer",
  label: "Developer-reported",
  niche: null,
  statement: "Co-ops lose a fifth of the evening milk.",
  published_at: "2026-09-28T09:00:00Z",
};

const READY: EditorState = {
  ...EMPTY_STATE,
  title: "Cold chain for dairy co-ops",
  nicheId: "0199a000-0000-7000-8000-00000000000b",
  maturity: "prototype",
  ask: "pilot",
  problemStatement: "Milk spoils.",
  summary: "Solar chillers.",
  problems: [{ id: PROBLEM.id, title: PROBLEM.title, source: "developer", label: null, niche: null }],
};

const SAVED = { id: "p1", draft: { confidential: { attachments: [] } } } as unknown as MyProposal;

type Calls = NonNullable<EditorProps["calls"]>;

function calls(overrides: Partial<Calls> = {}) {
  return {
    saveDraft: vi.fn<Calls["saveDraft"]>(async (): Promise<Outcome<MyProposal, SaveProblem>> => ({
      ok: true,
      value: SAVED,
    })),
    publish: vi.fn<Calls["publish"]>(async (): Promise<Outcome<PublishResult, PublishProblem>> => ({
      ok: true,
      value: { cert_id: "C1" } as PublishResult,
    })),
    attestationText: vi.fn(async (): Promise<Outcome<AttestationText, PublishProblem>> => ({ ok: true, value: TEXT })),
    ...overrides,
  };
}

function renderEditor(props: Partial<Omit<EditorProps, "calls">> & { calls?: ReturnType<typeof calls> } = {}) {
  const fake = props.calls ?? calls();
  renderWithIntl(
    <Editor
      id={null}
      initial={EMPTY_STATE}
      attachments={[]}
      step={1}
      niches={NICHES}
      counties={[{ code: "KE-30", name: "Nairobi City" }]}
      attestations={TEXT}
      problems={[PROBLEM]}
      {...props}
      calls={fake}
    />,
  );
  return fake;
}

const primary = () => document.querySelectorAll("[data-primary]");

describe("the stepper and primary action", () => {
  it("is an ordered list marking the current step, with one primary action per step", () => {
    renderEditor();
    const steps = within(screen.getByRole("navigation", { name: "Steps" })).getAllByRole("listitem");
    expect(steps).toHaveLength(3);
    expect(steps[0].getAttribute("aria-current")).toBe("step");
    expect(primary()).toHaveLength(1);
    expect(primary()[0].textContent).toBe("Continue");

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(steps[1].getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Confidential")).toBeTruthy();
    expect(primary()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /Review and publish/ }));
    expect(primary()).toHaveLength(1);
    expect(primary()[0].textContent).toBe("Publish");
  });
});

describe("autosave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("creates the draft on the first save, then saves changes to it", async () => {
    const fake = renderEditor();
    const replace = vi.spyOn(window.history, "replaceState");
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain" } });
    expect(fake.saveDraft).not.toHaveBeenCalled(); // waits until typing stops
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(fake.saveDraft).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fake.saveDraft).mock.calls[0][0]).toBeNull();
    expect(vi.mocked(fake.saveDraft).mock.calls[0][1].teaser?.title).toBe("Cold chain");
    expect(replace.mock.lastCall?.[2]).toBe("/dev/ideas/p1/edit"); // the address now names the draft
    expect(screen.getByRole("status").textContent).toBe("Saved");

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain v2" } });
    expect(screen.getByRole("status").textContent).toBe("Not saved yet");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(fake.saveDraft).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fake.saveDraft).mock.calls[1][0]).toBe("p1");
  });

  it("creates nothing before anything is typed", async () => {
    const fake = renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fake.saveDraft).not.toHaveBeenCalled();
  });

  it("puts the sanitiser's finding next to its field", async () => {
    const fake = calls({
      saveDraft: vi.fn(async () => ({
        ok: false as const,
        problem: "fields" as const,
        fields: [{ field: "summary" as const, code: "contains_email" }],
      })),
    });
    renderEditor({ id: "p1", calls: fake });
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "Mail jane@example.com" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    const summary = screen.getByLabelText("Summary");
    expect(summary.getAttribute("aria-invalid")).toBe("true");
    const described = (summary.getAttribute("aria-describedby") ?? "").split(" ");
    const message = described.map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
    expect(message).toContain("Remove the email address: the teaser is public");
    expect(screen.getByRole("alert").textContent).toContain("Some fields need changes");
  });

  it("counts summary words against the limit", () => {
    renderEditor({ initial: { ...READY, summary: "one two three" } });
    expect(screen.getByText("3 words of 150")).toBeTruthy();
  });
});

describe("publishing", () => {
  function check(all = true) {
    const boxes = screen.getAllByRole("checkbox");
    for (const box of all ? boxes : boxes.slice(0, 1)) fireEvent.click(box);
  }

  it("shows the attestation text from the API and needs all three statements", async () => {
    const fake = renderEditor({ id: "p1", initial: READY, step: 3 });
    for (const statement of TEXT.statements) expect(screen.getByLabelText(statement.text)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getAllByText("Confirm this statement.")).toHaveLength(3);
    expect(fake.publish).not.toHaveBeenCalled();
  });

  it("lists what is missing, with a way back to the step", async () => {
    renderEditor({ id: "p1", initial: { ...READY, title: "", maturity: "" }, step: 3 });
    check();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getByText("Title: Add a title.")).toBeTruthy();
    expect(screen.getByText("How far along is it?: Choose how far along it is.")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Go to step 1" })[0]);
    expect(screen.getByLabelText("Title").getAttribute("aria-invalid")).toBe("true");
  });

  it("publishes with the attestation text version and opens the idea", async () => {
    const fake = renderEditor({ id: "p1", initial: READY, step: 3 });
    check();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(fake.publish).toHaveBeenCalledWith("p1", TEXT, {
      created_it: true,
      not_owned_by_employer_or_client: true,
      no_third_party_confidential: true,
    });
    expect(push).toHaveBeenCalledWith("/dev/ideas/p1?published=1");
  });

  it.each([
    [{ problem: "d1Required" }, "To publish, your account needs a verified mobile number."],
    [{ problem: "planLimit", limit: 3 }, "Your plan allows 3 published ideas. Hide one to publish this one."],
    [{ problem: "planLimit" }, "Your plan does not allow more published ideas."],
    [{ problem: "nothingToPublish" }, "There are no changes to publish."],
  ] as const)("explains a refusal: %j", async (refusal, text) => {
    const fake = calls({ publish: vi.fn(async () => ({ ok: false as const, fields: [], ...refusal })) });
    renderEditor({ id: "p1", initial: READY, step: 3, calls: fake });
    check();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getByRole("alert").textContent).toContain(text);
    expect(push).not.toHaveBeenCalled();
  });

  it("reads the statements again when their wording changed, and asks to confirm again", async () => {
    const changed: AttestationText = {
      ...TEXT,
      version: "2026-10-01.1",
      statements: [{ key: "created_it", text: "I wrote this proposal myself." }, ...TEXT.statements.slice(1)],
    };
    const fake = calls({
      publish: vi.fn(async () => ({ ok: false as const, problem: "attestationsChanged" as const, fields: [] })),
      attestationText: vi.fn(async () => ({ ok: true as const, value: changed })),
    });
    renderEditor({ id: "p1", initial: READY, step: 3, calls: fake });
    check();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getByLabelText("I wrote this proposal myself.")).toBeTruthy();
    for (const box of screen.getAllByRole("checkbox")) expect((box as HTMLInputElement).checked).toBe(false);
    expect(screen.getByRole("alert").textContent).toContain("The statements changed.");
  });
});

describe("the problem picker", () => {
  function renderPicker(overrides: Partial<ProblemPickerProps> = {}) {
    const props: ProblemPickerProps = {
      mode: "pick",
      linked: [],
      newTitle: "",
      newStatement: "",
      niches: NICHES,
      initialResults: [PROBLEM],
      errors: {},
      onMode: vi.fn(),
      onLinked: vi.fn(),
      onNewTitle: vi.fn(),
      onNewStatement: vi.fn(),
      ...overrides,
    };
    renderWithIntl(<ProblemPicker {...props} />);
    return props;
  }

  it("links a listed problem and labels developer-reported ones", () => {
    const props = renderPicker();
    expect(screen.getByText("Developer-reported")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: `Link ${PROBLEM.title}` }));
    expect(props.onLinked).toHaveBeenCalledWith([
      { id: PROBLEM.id, title: PROBLEM.title, source: "developer", label: "Developer-reported", niche: null },
    ]);
  });

  it("searches by words and niche", async () => {
    const searchImpl = vi.fn(async () => ({ ok: true as const, value: { items: [] } }));
    renderPicker({ searchImpl });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search problems" }), { target: { value: "maziwa" } });
    fireEvent.change(screen.getByLabelText("Niche"), { target: { value: "agriculture" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Search" }));
    });
    expect(searchImpl).toHaveBeenCalledWith({ q: "maziwa", niche: "agriculture" });
    // Nothing found: one sentence and one action.
    const empty = document.querySelector("[data-empty-state]")!;
    expect(empty.querySelector("p")?.textContent).toBe("No listed problems match these words.");
    fireEvent.click(within(empty as HTMLElement).getByRole("button", { name: "Describe a new problem" }));
  });

  it("describes a new problem instead", () => {
    const props = renderPicker({ mode: "new", errors: { newTitle: "Give the problem a title." } });
    expect(screen.getByLabelText("Problem title").getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(screen.getByLabelText("What is the problem?"), { target: { value: "Late payments" } });
    expect(props.onNewStatement).toHaveBeenCalledWith("Late payments");
  });
});

describe("attachments", () => {
  const FILE: Attachment = {
    id: "a1",
    file_name: "plan.pdf",
    content_type: "application/pdf",
    size_bytes: 820_400,
    sha256: "x",
    av_status: "clean",
  };

  function choose(name: string, content = "x") {
    const input = screen.getByLabelText("Add a file");
    fireEvent.change(input, { target: { files: [new File([content], name)] } });
  }

  it("refuses a type the API does not accept before sending it", async () => {
    const uploadImpl = vi.fn();
    renderWithIntl(<Attachments attachments={[]} onChange={vi.fn()} ensureId={async () => "p1"} uploadImpl={uploadImpl} />);
    await act(async () => choose("setup.exe"));
    expect(uploadImpl).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe("Attach a PDF, PNG, JPG, Markdown or plain-text file.");
  });

  it("uploads with the type for its extension and lists the file", async () => {
    const onChange = vi.fn();
    const uploadImpl = vi.fn(async (): Promise<Outcome<Attachment, UploadProblem>> => ({ ok: true, value: FILE }));
    renderWithIntl(
      <Attachments attachments={[]} onChange={onChange} ensureId={async () => "p1"} uploadImpl={uploadImpl} />,
    );
    await act(async () => choose("plan.pdf", "%PDF-1.7"));
    expect(uploadImpl).toHaveBeenCalledWith("p1", expect.any(File), "plan.pdf", "application/pdf");
    expect(onChange).toHaveBeenCalledWith([FILE]);
  });

  it("says when the scan refused a file", async () => {
    const uploadImpl = vi.fn(async (): Promise<Outcome<Attachment, UploadProblem>> => ({
      ok: false,
      problem: "infected",
      fields: [],
    }));
    renderWithIntl(<Attachments attachments={[FILE]} onChange={vi.fn()} ensureId={async () => "p1"} uploadImpl={uploadImpl} />);
    expect(screen.getByText("820 KB")).toBeTruthy();
    await act(async () => choose("eicar.txt"));
    expect(screen.getByRole("alert").textContent).toBe("This file did not pass the malware check, so it was not kept.");
  });
});

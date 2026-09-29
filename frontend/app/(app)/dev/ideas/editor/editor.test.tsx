import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithIntl } from "@/test/intl";

import type { Attachment, AttestationText } from "../ideas";
import { Attachments } from "./Attachments";
import { calls, NICHES, PROBLEM, READY, renderEditor, settleLazy, TEXT } from "@/test/ideas-editor";
import { preloadPanels, ProblemPicker, type ProblemPickerProps } from "./ProblemPicker";

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

const primary = () => document.querySelectorAll("[data-primary]");

describe("the stepper and primary action", () => {
  it("is an ordered list marking the current step, with one primary action per step", async () => {
    await renderEditor();
    const steps = within(screen.getByRole("navigation", { name: "Steps" })).getAllByRole("button");
    expect(within(screen.getByRole("navigation", { name: "Steps" })).getAllByRole("listitem")).toHaveLength(3);
    expect(steps[0].getAttribute("aria-current")).toBe("step");
    expect(primary()).toHaveLength(1);
    expect(primary()[0].textContent).toBe("Continue");

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await settleLazy();
    expect(steps[1].getAttribute("aria-current")).toBe("step");
    expect(screen.getByText("Confidential")).toBeTruthy();
    expect(primary()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: /Review and publish/ }));
    await settleLazy();
    expect(primary()).toHaveLength(1);
    expect(primary()[0].textContent).toBe("Publish");
  });
});

describe("autosave", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("creates the draft on the first save, then saves changes to it", async () => {
    const fake = await renderEditor();
    const replace = vi.spyOn(window.history, "replaceState");
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain" } });
    expect(fake.saveState).not.toHaveBeenCalled(); // waits until typing stops
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(fake.saveState).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fake.saveState).mock.calls[0][0]).toBeNull();
    expect(vi.mocked(fake.saveState).mock.calls[0][1].title).toBe("Cold chain");
    expect(replace.mock.lastCall?.[2]).toBe("/dev/ideas/p1/edit"); // the address now names the draft
    expect(screen.getByRole("status").textContent).toBe("Saved");

    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Cold chain v2" } });
    expect(screen.getByRole("status").textContent).toBe("Not saved yet");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    expect(fake.saveState).toHaveBeenCalledTimes(2);
    expect(vi.mocked(fake.saveState).mock.calls[1][0]).toBe("p1");
  });

  it("creates nothing before anything is typed", async () => {
    const fake = await renderEditor();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(fake.saveState).not.toHaveBeenCalled();
  });

  it("puts the sanitiser's finding next to its field", async () => {
    const fake = calls({
      saveState: vi.fn(async () => ({
        outcome: {
          ok: false as const,
          problem: "fields" as const,
          fields: [
            { field: "summary" as const, code: "contains_email" },
            { field: "summary" as const, code: "contains_url" },
            { field: "title" as const, code: "a_code_added_later" },
          ],
        },
        held: [],
      })),
    });
    await renderEditor({ id: "p1", calls: fake });
    fireEvent.change(screen.getByLabelText("Summary"), { target: { value: "Mail jane@example.com" } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1300);
    });
    const summary = screen.getByLabelText("Summary");
    expect(summary.getAttribute("aria-invalid")).toBe("true");
    const described = (summary.getAttribute("aria-describedby") ?? "").split(" ");
    const message = described.map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
    expect(message).toContain("Remove the email address: the teaser is public");
    expect(message).toContain("Remove the web address: the teaser is public"); // every finding, not the first
    expect(screen.queryByRole("button", { name: "Save again" })).toBeNull(); // saving again cannot help
    // A finding without its own message gets the general one.
    expect(screen.getByText("Change this field, then try again.")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Some fields need changes");
  });

  it("counts summary words against the limit", async () => {
    await renderEditor({ initial: { ...READY, summary: "one two three" } });
    expect(screen.getByText("Words: 3 of 150")).toBeTruthy();
  });
});

describe("publishing", () => {
  function check(all = true) {
    const boxes = screen.getAllByRole("checkbox");
    for (const box of all ? boxes : boxes.slice(0, 1)) fireEvent.click(box);
  }

  it("shows the attestation text from the API and needs all three statements", async () => {
    const fake = await renderEditor({ id: "p1", initial: READY, step: 3 });
    for (const statement of TEXT.statements) expect(screen.getByLabelText(statement.text)).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getAllByText("Confirm this statement.")).toHaveLength(3);
    expect(fake.publish).not.toHaveBeenCalled();
  });

  it("lists what is missing, with a way back to the step", async () => {
    await renderEditor({ id: "p1", initial: { ...READY, title: "", maturity: "" }, step: 3 });
    check();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    });
    expect(screen.getByText("Add a title.")).toBeTruthy();
    expect(screen.getByText("Choose how far along it is.")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Go to step 1" })).toHaveLength(1); // one per step to fix
    fireEvent.click(screen.getByRole("button", { name: "Go to step 1" }));
    expect(screen.getByLabelText("Title").getAttribute("aria-invalid")).toBe("true");
  });

  it("publishes with the attestation text version and opens the idea", async () => {
    const fake = await renderEditor({ id: "p1", initial: READY, step: 3 });
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
    [{ problem: "planLimit", limit: 3 }, "Published ideas your plan allows: 3. Hide one to publish this one."],
    [{ problem: "planLimit" }, "Your plan does not allow more published ideas."],
    [{ problem: "nothingToPublish" }, "There are no changes to publish."],
  ] as const)("explains a refusal: %j", async (refusal, text) => {
    const fake = calls({ publish: vi.fn(async () => ({ ok: false as const, fields: [], ...refusal })) });
    await renderEditor({ id: "p1", initial: READY, step: 3, calls: fake });
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
    await renderEditor({ id: "p1", initial: READY, step: 3, calls: fake });
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
  async function renderPicker(overrides: Partial<ProblemPickerProps> = {}) {
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
    await preloadPanels();
    renderWithIntl(<ProblemPicker {...props} />);
    return props;
  }

  it("asks first, then opens the chosen way", async () => {
    const onMode = vi.fn();
    renderWithIntl(<ProblemPicker {...{ mode: null, linked: [], newTitle: "", newStatement: "", niches: NICHES, initialResults: [PROBLEM], errors: {}, onMode, onLinked: vi.fn(), onNewTitle: vi.fn(), onNewStatement: vi.fn() }} />);
    expect(screen.queryByRole("searchbox")).toBeNull();
    fireEvent.click(screen.getByLabelText(/Link a listed problem/));
    expect(onMode).toHaveBeenCalledWith("pick");
  });

  it("links a listed problem and labels developer-reported ones", async () => {
    const props = await renderPicker();
    expect(screen.getByText("Developer-reported")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: `Link ${PROBLEM.title}` }));
    expect(props.onLinked).toHaveBeenCalledWith([
      { id: PROBLEM.id, title: PROBLEM.title, source: "developer", label: "Developer-reported", niche: null },
    ]);
  });

  it("searches by words and niche", async () => {
    const searchImpl = vi.fn(async () => ({ ok: true as const, value: { items: [] } }));
    await renderPicker({ searchImpl });
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

  it("describes a new problem instead", async () => {
    const props = await renderPicker({ mode: "new", errors: { newTitle: "Give the problem a title." } });
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

  function renderFiles(list: Attachment[], fake = calls()) {
    let current = list;
    const onAttachments = vi.fn((change: (l: Attachment[]) => Attachment[]) => {
      current = change(current);
    });
    renderWithIntl(
      <Attachments
        attachments={list}
        onAttachments={onAttachments}
        ensureDraft={async () => ({ id: "p1", attachments: current })}
        getCalls={async () => fake}
      />,
    );
    return { fake, list: () => current };
  }

  function choose(name: string, content = "x") {
    const input = screen.getByLabelText("Add a file");
    fireEvent.change(input, { target: { files: [new File([content], name)] } });
  }

  it("refuses a type the API does not accept, or a name too long to send, before sending it", async () => {
    const { fake } = renderFiles([]);
    await act(async () => choose("setup.exe"));
    expect(screen.getByRole("alert").textContent).toBe("Attach a PDF, PNG, JPG, Markdown or plain-text file.");
    await act(async () => choose(`${"ü".repeat(200)}.pdf`)); // 1,204 characters once percent-encoded
    expect(screen.getByRole("alert").textContent).toBe("Rename the file, then try again.");
    expect(fake.uploadAttachment).not.toHaveBeenCalled();
  });

  it("uploads with the type for its extension and adds the file to the latest list", async () => {
    const fake = calls({ uploadAttachment: vi.fn(async () => ({ ok: true as const, value: FILE })) });
    const files = renderFiles([], fake);
    await act(async () => choose("plan.pdf", "%PDF-1.7"));
    expect(fake.uploadAttachment).toHaveBeenCalledWith("p1", expect.any(File), "plan.pdf", "application/pdf");
    expect(files.list()).toEqual([FILE]);
  });

  it("says when the scan refused a file", async () => {
    const fake = calls({
      uploadAttachment: vi.fn(async () => ({ ok: false as const, problem: "infected" as const, fields: [] })),
    });
    renderFiles([FILE], fake);
    expect(screen.getByText("820 KB")).toBeTruthy();
    await act(async () => choose("eicar.txt"));
    expect(screen.getByRole("alert").textContent).toBe("This file did not pass the malware check, so it was not kept.");
  });
});
